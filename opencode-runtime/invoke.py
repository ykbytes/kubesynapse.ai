"""Core invocation logic — the autonomous multi-turn loop."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from analysis import (
    _build_response_metadata,
    build_compaction_hints,
    check_context_overflow,
    classify_error_type,
    classify_task_type,
    compute_context_budget,
    derive_task_status,
    detect_anti_patterns,
    detect_completion_status,
    extract_artifacts_from_messages,
    extract_reasoning_from_parts,
    extract_response_text,
    extract_tool_calls_from_messages,
    get_latest_assistant_payload,
    detect_task_errors,
    build_prompt_format,
    recommend_compaction_strategy,
    runtime_capabilities,
    select_agent_for_prompt,
)
from config import (
    A2A_ALLOWED_CALLERS,
    ARTIFACT_COLLECTION_MAX_FILES,
    AUTONOMOUS_MAX_RETRIES,
    AUTONOMOUS_MAX_TURNS,
    COMPACTION_MIN_TURN_SPACING,
    DEFAULT_AGENT,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    MAX_COMPACTION_ATTEMPTS,
    MAX_PROMPT_CHARS,
    MEMORY_ENABLED,
    OPENCODE_WORKDIR,
    SERVICE_NAME,
    SERVICE_NAMESPACE,
    SESSION_ABORT_TIMEOUT_SECONDS,
    SESSION_INIT_ON_CREATE,
    WORKSPACE_SNAPSHOT_ENABLED,
)
from hitl import hitl_gate
from memory import (
    SESSION_MEMORY,
    build_handoff_entry,
    build_task_summary_entry,
)
from models import InvokeRequest, InvokeResponse
from opencode_client import (
    _send_prompt_with_session_recovery,
    abort_session,
    create_remote_session,
    ensure_server_running,
    get_session_messages,
    get_session_todos,
    init_session,
    summarize_session,
    wait_for_session_idle,
)
from prompts import (
    AUTONOMY_CONTINUATION_PROMPT,
    AUTONOMY_SYSTEM_PROMPT,
    build_format_system_prompt,
    build_handoff_resumption_prompt,
    build_recovery_prompt,
    combine_system_prompt,
    format_memory_context,
    format_skills_system_prompt,
    format_team_context_system_prompt,
    format_workspace_system_prompt,
    get_continuation_prompt,
    get_task_type_prompt,
)
from session import SESSION_REGISTRY
from skills import SKILL_RUNTIME_CONFIG
from utils import dedupe_items, truncate_text
from workspace import get_or_refresh_snapshot

logger = logging.getLogger("opencode-runtime")

StreamCallback = Any  # Callable[[str, dict[str, Any]], None] | None


def validate_inbound_a2a_request(request: InvokeRequest) -> None:
    """Validate that the caller is allowed to invoke this agent."""
    caller_agent_name = (request.caller_agent_name or "").strip()
    caller_agent_namespace = (request.caller_agent_namespace or "").strip()
    if not caller_agent_name and not caller_agent_namespace:
        return
    if not A2A_ALLOWED_CALLERS:
        return
    if (caller_agent_namespace, caller_agent_name) not in A2A_ALLOWED_CALLERS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Agent '{caller_agent_name}' in namespace '{caller_agent_namespace}' is not allowed "
                f"to invoke agent '{SERVICE_NAME}' in namespace '{SERVICE_NAMESPACE}'."
            ),
        )


def a2a_response_metadata(request: InvokeRequest) -> dict[str, Any] | None:
    """Build A2A response metadata if the request is from another agent."""
    if not request.caller_agent_name or not request.caller_agent_namespace:
        return None
    return {
        "callerAgent": request.caller_agent_name,
        "callerNamespace": request.caller_agent_namespace,
        "parentThreadId": request.parent_thread_id,
        "callerRequestId": request.caller_request_id,
    }


def build_invoke_warnings(request: InvokeRequest) -> list[str]:
    """Build the initial warnings list for an invocation."""
    warnings: list[str] = []
    if request.no_session:
        warnings.append(
            "Session persistence is disabled for this invocation; the returned thread_id cannot be resumed."
        )
    warnings.extend(str(item).strip() for item in (SKILL_RUNTIME_CONFIG.get("warnings") or []) if str(item).strip())
    return dedupe_items(warnings)


def resolve_working_directory(raw_value: str | None) -> str:
    """Resolve and validate the working directory for an invocation."""
    root = Path(OPENCODE_WORKDIR).resolve()
    if raw_value is None or not raw_value.strip():
        return str(root)
    candidate = raw_value.strip()
    target = (root / candidate).resolve() if not Path(candidate).is_absolute() else Path(candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"working_directory '{raw_value}' must stay inside the OpenCode workspace"
        ) from exc
    if not target.exists() or not target.is_dir():
        raise HTTPException(
            status_code=400, detail=f"working_directory '{raw_value}' does not exist inside the OpenCode workspace"
        )
    return str(target)


def _capture_pre_compaction_state(
    session_id: str,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Capture structured task state before compaction for recovery prompts.

    Fetches todos, recent artifacts, and the last successful tool action.
    """
    state: dict[str, Any] = {}

    # Fetch todos
    try:
        todos = get_session_todos(session_id)
        state["todos"] = todos
    except Exception:
        state["todos"] = []

    # Extract artifacts and last action from messages
    if messages is None:
        try:
            messages = get_session_messages(session_id)
        except Exception:
            messages = []

    if messages:
        from analysis import extract_artifacts_from_messages, extract_tool_calls_from_messages

        state["artifacts"] = extract_artifacts_from_messages(messages)
        tool_calls = extract_tool_calls_from_messages(messages)
        if tool_calls:
            last_successful = None
            for tc in reversed(tool_calls):
                if tc.get("status") == "completed":
                    last_successful = tc
                    break
            if last_successful:
                state["last_action"] = (
                    f"{last_successful.get('tool', '?')}: {truncate_text(str(last_successful.get('input', '')), 200)}"
                )

    return state


def invoke_opencode(request: InvokeRequest, stream_callback: StreamCallback = None) -> InvokeResponse:
    """Execute the autonomous multi-turn invocation loop."""
    ensure_server_running()
    validate_inbound_a2a_request(request)

    if request.require_approval:
        try:
            approval = hitl_gate(
                action_description=request.approval_action or f"Invoke OpenCode agent '{SERVICE_NAME}'",
                request_id=request.thread_id or str(uuid.uuid4()),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if approval.get("decision") == "pending":
            return InvokeResponse(
                thread_id=request.thread_id or str(uuid.uuid4()),
                response="",
                model=request.model or DEFAULT_MODEL,
                status="approval_pending",
                approval_name=approval.get("approval_name"),
                a2a=a2a_response_metadata(request),
                warnings=build_invoke_warnings(request),
            )

    working_directory = resolve_working_directory(request.working_directory)
    selected_model = request.model or DEFAULT_MODEL
    logical_thread_id = request.thread_id or str(uuid.uuid4())
    created_new_session = False
    if request.no_session:
        session_id = create_remote_session(working_directory)
        created_new_session = True
    else:
        existing_session = SESSION_REGISTRY.get(logical_thread_id)
        if existing_session:
            session_id = existing_session
        else:
            session_id = create_remote_session(working_directory)
            session_id = SESSION_REGISTRY.get_or_set(logical_thread_id, session_id)
            created_new_session = True

    if created_new_session and request.autonomous and SESSION_INIT_ON_CREATE:
        if not init_session(session_id, selected_model):
            logger.warning("Session init failed for %s", session_id)

    # --- Build enhanced system prompt with workspace and memory context ---
    pre_auth_prompt: str | None = None
    if request.pre_authorized_actions:
        allowed = ", ".join(request.pre_authorized_actions)
        pre_auth_prompt = (
            f"PRE-AUTHORIZED ACTIONS: The following actions have been pre-approved "
            f"by the workflow owner and may be executed without hesitation: {allowed}. "
            f"You do NOT need confirmation to perform these actions."
        )

    # Workspace awareness: inject pre-computed codebase context
    workspace_prompt: str | None = None
    if WORKSPACE_SNAPSHOT_ENABLED and created_new_session:
        snapshot = get_or_refresh_snapshot(working_directory)
        workspace_prompt = format_workspace_system_prompt(snapshot)

    # Cross-session memory: inject prior context
    memory_prompt: str | None = None
    has_prior_memory = False
    memory_entry_count = 0
    handoff_memory: dict[str, Any] | None = None
    if MEMORY_ENABLED and not request.no_session:
        has_prior_memory = SESSION_MEMORY.has_memory(logical_thread_id)
        if has_prior_memory:
            # Check for handoff entry (session continuity from context exhaustion)
            handoff_memory = SESSION_MEMORY.get_handoff_memory(logical_thread_id)
            if handoff_memory:
                memory_prompt = None  # Will inject via the prompt, not system prompt
            else:
                memory_entries = SESSION_MEMORY.build_memory_context(logical_thread_id)
                memory_entry_count = len(memory_entries)
                memory_prompt = format_memory_context(memory_entries)

    # Task type classification for supplementary prompt
    task_type = classify_task_type(request.prompt) if request.autonomous else "unknown"
    task_type_prompt = get_task_type_prompt(task_type) if request.autonomous else None

    # Skills awareness: inject available skill names and descriptions
    skills_prompt = format_skills_system_prompt(SKILL_RUNTIME_CONFIG.get("skillMeta"))

    system_prompt = combine_system_prompt(
        AUTONOMY_SYSTEM_PROMPT if request.autonomous else None,
        DEFAULT_SYSTEM_PROMPT,
        request.system,
        pre_auth_prompt,
        workspace_prompt,
        memory_prompt,
        skills_prompt,
        task_type_prompt,
        build_format_system_prompt(request.output_format),
        format_team_context_system_prompt(request.team_context),
    )
    prompt_format = build_prompt_format(request)
    max_retries = request.max_retries if request.max_retries is not None else AUTONOMOUS_MAX_RETRIES
    effective_max_turns = request.max_turns if request.max_turns is not None else AUTONOMOUS_MAX_TURNS

    # --- Autonomous multi-turn loop ---
    all_warnings: list[str] = list(build_invoke_warnings(request))
    retries_used = 0
    last_payload: dict[str, Any] = {}
    current_prompt = request.prompt
    compaction_attempts = 0
    last_compaction_turn = -COMPACTION_MIN_TURN_SPACING
    handoff_summary: dict[str, Any] | None = None
    _resend_format = False
    current_budget_status = "ok"
    session_recovered = False

    # If resuming from handoff, inject the resumption prompt
    if handoff_memory and created_new_session:
        resumption = build_handoff_resumption_prompt(handoff_memory)
        current_prompt = f"{resumption}\n\n---\n\nNEW INSTRUCTIONS:\n{current_prompt}"
        all_warnings.append("Resuming from prior session handoff - context from previous session injected.")

    current_agent = (
        select_agent_for_prompt(
            request.prompt,
            is_first_turn=True,
            context_budget_status=current_budget_status,
            has_prior_memory=has_prior_memory,
        )
        if request.autonomous
        else DEFAULT_AGENT
    )
    if current_agent == "plan" and current_agent != DEFAULT_AGENT:
        all_warnings.append("Using plan agent for initial analysis before execution.")
    if current_agent != DEFAULT_AGENT and current_agent != "plan":
        all_warnings.append(f"Using '{current_agent}' agent based on task type classification ({task_type}).")

    def _emit(event_type: str, data: dict[str, Any]) -> None:
        if stream_callback is not None:
            try:
                stream_callback(event_type, data)
            except Exception:
                pass

    for turn in range(effective_max_turns):
        _emit("response.turn_started", {"turn": turn + 1, "max_turns": effective_max_turns, "agent": current_agent})
        use_system = system_prompt if turn == 0 else None
        try:
            session_id, payload = _send_prompt_with_session_recovery(
                session_id=session_id,
                prompt=current_prompt,
                model=selected_model,
                system_prompt=use_system,
                prompt_format=prompt_format if (turn == 0 or _resend_format) else None,
                working_directory=working_directory,
                agent=current_agent,
                logical_thread_id=logical_thread_id,
                allow_session_recovery=(not request.no_session),
            )
            recovered = bool(payload.pop("_session_recovered", False)) if isinstance(payload, dict) else False
            session_recovered = session_recovered or recovered
        except httpx.HTTPError as exc:
            is_permanent = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code < 500
                and exc.response.status_code not in (408, 429)
            )
            if is_permanent or retries_used >= max_retries:
                raise HTTPException(
                    status_code=502,
                    detail=f"OpenCode invocation failed after {retries_used} retries: {exc}",
                ) from exc
            retries_used += 1
            _emit(
                "response.error_recovery",
                {"turn": turn + 1, "error_type": "http", "retry": retries_used, "max_retries": max_retries},
            )
            all_warnings.append(f"Turn {turn + 1}: HTTP error '{exc}', retrying ({retries_used}/{max_retries})")
            recovery_note = (
                f"[Note: the previous request encountered a transient error ({type(exc).__name__}). "
                f"Check whether the previous operation partially completed before retrying. "
                f"If files were partially written or commands partially executed, verify their "
                f"state before continuing.]\n\n"
            )
            current_prompt = truncate_text(f"{recovery_note}{current_prompt}", MAX_PROMPT_CHARS)
            continue

        last_payload = payload
        completion = detect_completion_status(payload)
        _resend_format = False

        # Update context budget status for prompt selection
        turn_budget = compute_context_budget(payload)
        current_budget_status = turn_budget.get("status", "ok")

        turn_text = extract_response_text(payload).strip()
        _emit(
            "response.turn_completed",
            {
                "turn": turn + 1,
                "status": completion,
                "response_length": len(turn_text),
                "context_budget_status": current_budget_status,
            },
        )
        if turn_text:
            _emit("response.delta", {"turn": turn + 1, "delta": turn_text, "source": "opencode"})

        # Emit reasoning/thinking content if present
        parts = payload.get("parts")
        if isinstance(parts, list):
            reasoning_text = extract_reasoning_from_parts(parts)
            if reasoning_text:
                _emit("response.reasoning", {"turn": turn + 1, "reasoning": reasoning_text})

            # Emit structured tool call and patch events
            for part in parts:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "tool":
                    state = part.get("state") or {}
                    if isinstance(state, dict):
                        _emit("response.tool_call", {
                            "turn": turn + 1,
                            "tool": str(part.get("tool", "")),
                            "status": str(state.get("status", "unknown")),
                            "input": state.get("input"),
                            "output": truncate_text(str(state.get("output", "")), 4000),
                            "source": "opencode",
                        })
                elif part_type == "patch":
                    _emit("response.patch", {
                        "turn": turn + 1,
                        "files": part.get("files") or [],
                        "source": "opencode",
                    })

        if current_agent == "plan" and completion in ("completed", "incomplete"):
            current_agent = DEFAULT_AGENT
            if completion == "completed":
                all_warnings.append("Plan phase completed, switching to build agent for execution.")
                current_prompt = (
                    "Now execute the plan you just created. For each step:\n"
                    "1. Implement the step completely — do not skip ahead.\n"
                    "2. Verify it works (read files back, run code, check output).\n"
                    "3. Fix any issues before moving to the next step.\n"
                    "4. Update the todo list to mark the step complete.\n"
                    "After all steps: run the full test suite or verify the overall "
                    "result meets the original objective."
                )
                continue

        _can_compact = (
            compaction_attempts < MAX_COMPACTION_ATTEMPTS
            and (turn - last_compaction_turn) >= COMPACTION_MIN_TURN_SPACING
        )

        # --- Graduated compaction logic ---
        if completion == "context_overflow" and _can_compact:
            compaction_attempts += 1
            last_compaction_turn = turn
            _emit(
                "response.compaction",
                {
                    "turn": turn + 1,
                    "reason": "context_overflow",
                    "attempt": compaction_attempts,
                    "max": MAX_COMPACTION_ATTEMPTS,
                },
            )

            # Capture state before compaction for structured recovery
            pre_state = _capture_pre_compaction_state(session_id)

            if summarize_session(session_id, model_ref=selected_model):
                all_warnings.append(
                    f"Turn {turn + 1}: context overflow detected, triggered compaction ({compaction_attempts}/{MAX_COMPACTION_ATTEMPTS})."
                )
                wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                # Use structured recovery prompt
                current_prompt = build_recovery_prompt(pre_state)
                continue
            all_warnings.append(f"Turn {turn + 1}: context overflow, compaction failed.")

        if completion == "completed":
            break

        # Proactive compaction with graduated strategy
        if _can_compact and check_context_overflow(payload):
            strategy = recommend_compaction_strategy(turn_budget)
            if strategy in ("summarize", "aggressive"):
                compaction_attempts += 1
                last_compaction_turn = turn
                _emit(
                    "response.compaction",
                    {
                        "turn": turn + 1,
                        "reason": "proactive",
                        "strategy": strategy,
                        "attempt": compaction_attempts,
                        "max": MAX_COMPACTION_ATTEMPTS,
                    },
                )

                # Capture state and hints
                pre_state = _capture_pre_compaction_state(session_id)

                if summarize_session(session_id, model_ref=selected_model):
                    all_warnings.append(
                        f"Turn {turn + 1}: proactively triggered {strategy} compaction ({compaction_attempts}/{MAX_COMPACTION_ATTEMPTS})."
                    )
                    wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                    current_prompt = build_recovery_prompt(pre_state)
                    continue
            elif strategy == "prune_outputs":
                all_warnings.append(
                    f"Turn {turn + 1}: context usage high — prune_outputs strategy recommended but continuing."
                )

        if completion == "error":
            error_type = classify_error_type(payload)
            if error_type == "context_overflow" and _can_compact:
                compaction_attempts += 1
                last_compaction_turn = turn
                _emit(
                    "response.compaction",
                    {
                        "turn": turn + 1,
                        "reason": "error_overflow",
                        "attempt": compaction_attempts,
                        "max": MAX_COMPACTION_ATTEMPTS,
                    },
                )
                pre_state = _capture_pre_compaction_state(session_id)
                if summarize_session(session_id, model_ref=selected_model):
                    all_warnings.append(
                        f"Turn {turn + 1}: context overflow error, compacting ({compaction_attempts}/{MAX_COMPACTION_ATTEMPTS})."
                    )
                    wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                    current_prompt = build_recovery_prompt(pre_state)
                    continue
            if error_type == "structured_output" and retries_used < max_retries:
                retries_used += 1
                _resend_format = True
                _emit(
                    "response.error_recovery",
                    {
                        "turn": turn + 1,
                        "error_type": "structured_output",
                        "retry": retries_used,
                        "max_retries": max_retries,
                    },
                )
                all_warnings.append(
                    f"Turn {turn + 1}: structured output validation failed, retrying ({retries_used}/{max_retries})"
                )
                current_prompt = (
                    "Your previous response did not satisfy the required JSON schema. Fix it now:\n"
                    "1. Re-read the schema requirements — check all required fields and their types.\n"
                    "2. Ensure every required field is present with the correct type.\n"
                    "3. Output ONLY the valid JSON — no markdown fencing, no explanation text.\n"
                    "4. Validate mentally: would json.loads() parse this without error?"
                )
                continue
            if error_type == "auth":
                all_warnings.append(f"Turn {turn + 1}: authentication error, cannot retry.")
                break
            if retries_used < max_retries:
                retries_used += 1
                _emit(
                    "response.error_recovery",
                    {
                        "turn": turn + 1,
                        "error_type": error_type or "unknown",
                        "retry": retries_used,
                        "max_retries": max_retries,
                    },
                )
                all_warnings.append(
                    f"Turn {turn + 1}: agent error ({error_type or 'unknown'}), retrying ({retries_used}/{max_retries})"
                )
                current_prompt = (
                    "The previous step encountered an error. Before retrying:\n"
                    "1. Read the error message carefully — what specifically failed?\n"
                    "2. Identify the root cause — not just the symptom.\n"
                    "3. Fix the underlying issue, then retry.\n"
                    "If the same approach has already failed, try a fundamentally "
                    "different strategy instead of repeating the same steps."
                )
                continue
            break

        if completion == "incomplete" and turn + 1 < effective_max_turns:
            all_warnings.append(f"Turn {turn + 1}: task incomplete, sending continuation prompt")
            # Use context-budget-aware continuation prompt
            current_prompt = get_continuation_prompt(current_budget_status)
            continue

        break

    # --- Handoff summary with memory persistence ---
    if compaction_attempts >= MAX_COMPACTION_ATTEMPTS and last_payload:
        budget = compute_context_budget(last_payload)
        if budget.get("status") == "critical":
            handoff_summary = {
                "reason": "context_exhausted",
                "compaction_attempts": compaction_attempts,
                "context_budget": budget,
                "turns_completed": min(turn + 1, effective_max_turns),
                "original_prompt": truncate_text(request.prompt, 500),
                "recommendation": "Start a new session. The context window is exhausted.",
            }
            all_warnings.append("Context exhausted after max compaction attempts; handoff summary generated.")

    # --- Collect full session history for artifacts and tool calls ---
    collected_tool_calls: list[dict[str, Any]] = []
    collected_artifacts: list[dict[str, Any]] = []
    collected_todos: list[dict[str, Any]] = []
    authoritative_payload = dict(last_payload)
    try:
        if detect_completion_status(last_payload) not in ("completed",):
            final_status = wait_for_session_idle(session_id)
            if str(final_status.get("type", "idle")) != "idle":
                abort_session(session_id)
                all_warnings.append(f"Session {session_id} remained {final_status.get('type', 'busy')}, aborted.")
                wait_for_session_idle(session_id, timeout_seconds=5.0)

        messages = get_session_messages(session_id)
        collected_tool_calls = extract_tool_calls_from_messages(messages)
        collected_artifacts = extract_artifacts_from_messages(messages)
        collected_todos = get_session_todos(session_id)
        if len(collected_artifacts) >= ARTIFACT_COLLECTION_MAX_FILES:
            all_warnings.append(
                f"Artifact collection limited to {ARTIFACT_COLLECTION_MAX_FILES} files; some may have been omitted."
            )
        latest_assistant = get_latest_assistant_payload(messages)
        if latest_assistant is not None:
            authoritative_payload = latest_assistant

        residual_errors = detect_task_errors(messages)
        for err in residual_errors[:5]:
            all_warnings.append(f"Tool error: {truncate_text(err, 200)}")
    except Exception as exc:
        logger.warning("Failed to collect session history for %s: %s", session_id, exc)

    response_text = extract_response_text(authoritative_payload).strip() or "(no output)"
    final_status_str = detect_completion_status(authoritative_payload)
    response_metadata = _build_response_metadata(authoritative_payload)
    if response_metadata is None:
        response_metadata = {}
    if collected_todos:
        response_metadata["todos"] = collected_todos

    response_status = final_status_str
    if final_status_str == "context_overflow":
        response_status = "error"
    elif final_status_str == "unknown":
        response_status = "incomplete"
    if response_status != final_status_str:
        response_metadata["raw_status"] = final_status_str

    ctx_budget = compute_context_budget(authoritative_payload)
    response_metadata["context_budget"] = ctx_budget

    anti_patterns = detect_anti_patterns(response_text)
    if anti_patterns:
        response_metadata["anti_patterns"] = anti_patterns

    task_status = derive_task_status(response_status, all_warnings, ctx_budget, anti_patterns)
    response_metadata["task_status"] = task_status

    # Include task type and agent selection info
    if task_type != "unknown":
        response_metadata["task_type"] = task_type
    response_metadata["agent_used"] = current_agent

    if handoff_summary:
        response_metadata["handoff_summary"] = handoff_summary

    continuity = {
        "created_new_session": created_new_session,
        "session_recovered": session_recovered,
        "has_prior_memory": has_prior_memory,
        "memory_applied": bool(memory_prompt) or bool(handoff_memory),
        "memory_entry_count": memory_entry_count,
        "handoff_resumed": bool(handoff_memory and created_new_session),
        "remote_session_id": session_id,
    }

    # --- Persist memory after invocation ---
    if MEMORY_ENABLED and not request.no_session:
        try:
            # Save task summary
            summary_entry = build_task_summary_entry(
                prompt=request.prompt,
                response_text=response_text,
                status=response_status,
                artifacts=collected_artifacts,
                tool_calls=collected_tool_calls,
                todos=collected_todos,
                warnings=all_warnings,
                context_budget=ctx_budget,
            )
            SESSION_MEMORY.save_memory(logical_thread_id, summary_entry)

            # Save handoff entry if context was exhausted
            if handoff_summary:
                handoff_entry = build_handoff_entry(
                    prompt=request.prompt,
                    summary=response_text[:2000],
                    todos=collected_todos,
                    artifacts=collected_artifacts,
                    context_budget=ctx_budget,
                )
                SESSION_MEMORY.save_memory(logical_thread_id, handoff_entry)
        except Exception as exc:
            logger.warning("Failed to persist session memory for %s: %s", logical_thread_id, exc)

    return InvokeResponse(
        thread_id=logical_thread_id,
        response=response_text,
        model=selected_model,
        status=response_status,
        a2a=a2a_response_metadata(request),
        warnings=dedupe_items(all_warnings),
        artifacts=collected_artifacts,
        tool_calls=collected_tool_calls,
        continuity=continuity,
        metadata=response_metadata or None,
    )
