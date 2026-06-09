"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

# Re-import all shared symbols from the gateway core
from _core import *
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from services.audit import emit_invoke_audit
from services.model_router import get_fallback_chain, record_model_failure, record_model_success
from services.runtime_client import (
    CircuitBreakerOpenError,
    RuntimeUnhealthyError,
    invoke_with_retry,
    stream_with_retry,
)

from routers.observability import _agent_wants_intelligence, _build_auto_intelligence_context

router = APIRouter(tags=["agents"])


def _invoke_error_detail(
    reason: str,
    agent_name: str,
    namespace: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build a structured ErrorResponse for agent invocation failures."""
    from error_codes import ErrorCode, build_error_response
    return build_error_response(
        code=ErrorCode.INVOKE_FAILED,
        message=reason,
        detail=f"agent={agent_name}, namespace={namespace}",
        request_id=request_id,
    )


def _invoke_username(user: dict[str, Any]) -> str | None:
    return str(user.get("sub") or user.get("username") or "").strip() or None


def _build_invoke_execution_id(
    *,
    thread_id: str | None = None,
    request_id: str | None = None,
) -> str:
    request_seed = str(request_id or "").strip()
    if request_seed:
        digest = hashlib.sha256(f"request:{request_seed}".encode()).hexdigest()[:24]
        return f"exec-{digest}"

    thread_seed = str(thread_id or "").strip()
    if thread_seed:
        return f"exec-{thread_seed[:16]}"

    return f"exec-{uuid.uuid4().hex[:16]}"


def _record_invoke_trace(
    namespace: str,
    agent_name: str,
    agent: dict[str, Any],
    data: dict[str, Any],
    request_id: str,
) -> None:
    """Record a WorkflowExecution with LLM/tool metadata from an invoke response.

    This creates an observatory-visible execution record so that direct
    agent invokes (not just workflow steps) appear in the Execution
    Observatory with token counts, cost, duration, and tool-call details.
    """
    from datetime import UTC, datetime

    from trace_store import (
        ExecutionStatus,
        LLMCallRecord,
        ToolCallRecord,
        WorkflowExecution,
        db_session,
        ensure_trace_database,
        utc_now,
    )

    try:
        ensure_trace_database()
    except Exception:
        logger.warning("Trace database not available for invoke trace recording", exc_info=True)
        return

    thread_id = str(data.get("thread_id") or "").strip() or request_id
    execution_id = _build_invoke_execution_id(thread_id=thread_id, request_id=request_id)
    now = utc_now()
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    token_info = metadata.get("tokens") if isinstance(metadata.get("tokens"), dict) else {}
    if not token_info and isinstance(data.get("usage"), dict):
        token_info = data["usage"]
    context_budget = metadata.get("context_budget", {}) if isinstance(metadata.get("context_budget"), dict) else {}
    time_info = metadata.get("time", {}) if isinstance(metadata.get("time"), dict) else {}
    cost_info = metadata.get("cost", 0)
    status = str(data.get("status", "completed") or "completed")
    if status not in {s.value for s in ExecutionStatus}:
        status = "completed"
    created_ms = int(time_info.get("created", 0)) if time_info else 0
    completed_ms = int(time_info.get("completed", 0)) if time_info else 0
    duration_ms = (completed_ms - created_ms) if created_ms and completed_ms else None
    prompt_tokens = int(token_info.get("input", token_info.get("prompt_tokens", 0)))
    completion_tokens = int(token_info.get("output", token_info.get("completion_tokens", 0)))
    total_tokens = int(token_info.get("total", token_info.get("total_tokens", 0)))
    cache_read_tokens = int(token_info.get("cache_read", token_info.get("cache_read_tokens", 0)))
    cache_write_tokens = int(token_info.get("cache_write", token_info.get("cache_write_tokens", 0)))
    reasoning_tokens = int(token_info.get("reasoning", token_info.get("reasoning_tokens", 0)))
    tool_calls = data.get("tool_calls") or []
    tool_calls_count = len(tool_calls)
    llm_calls_count = 1 if total_tokens > 0 else 0
    started_at = datetime.fromtimestamp(created_ms / 1000, tz=UTC) if created_ms else now
    completed_at = datetime.fromtimestamp(completed_ms / 1000, tz=UTC) if completed_ms else now
    if not duration_ms and started_at and completed_at:
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

    step_id = f"step-{execution_id[:12]}"

    with db_session() as session:
        try:
            existing = session.query(WorkflowExecution).filter_by(id=execution_id).one_or_none()
            if existing is not None:
                return
            execution = WorkflowExecution(
                id=execution_id,
                namespace=namespace,
                workflow_name=f"invoke-{agent_name}",
                agent_name=agent_name,
                run_id=request_id[:64] if request_id else execution_id,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                input_summary=data.get("prompt") if isinstance(data.get("prompt"), str) else None,
                output_summary=str(data.get("response", ""))[:4096] if data.get("response") else None,
                total_steps=0,
                completed_steps=0,
                failed_steps=0,
                total_llm_calls=llm_calls_count,
                total_tool_calls=tool_calls_count,
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                reasoning_tokens=reasoning_tokens,
                estimated_cost_usd=float(cost_info) if cost_info else None,
                triggered_by="direct-invoke",
                error_message=data.get("error_message") or (str(data.get("detail", ""))[:4096] if data.get("detail") else None),
            )
            session.add(execution)
            session.flush()

            if llm_calls_count > 0:
                model_name = str(data.get("model") or agent.get("spec", {}).get("model", "unknown"))
                llm_record = LLMCallRecord(
                    id=f"llm-{execution_id[:12]}",
                    execution_id=execution_id,
                    step_id=step_id,
                    model=model_name,
                    provider=model_name.split("/")[0] if "/" in model_name else None,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    reasoning_tokens=reasoning_tokens,
                    total_tokens=total_tokens,
                    cost_usd=float(cost_info) if cost_info else None,
                    latency_ms=duration_ms,
                    started_at=started_at,
                )
                session.add(llm_record)

            for idx, tc in enumerate(tool_calls):
                tc_id = f"tc-{execution_id[:12]}-{idx}"
                # Support both runtime format (tool/input/output/duration_ms)
                # and legacy format (name/args/result)
                tc_duration = tc.get("duration_ms") or tc.get("duration") or None
                tc_record = ToolCallRecord(
                    id=tc_id,
                    execution_id=execution_id,
                    step_id=step_id,
                    tool_name=str(tc.get("tool") or tc.get("name") or "unknown"),
                    tool_args=tc.get("input") or tc.get("args") if isinstance(tc.get("input") or tc.get("args"), (dict, list, str)) else None,
                    tool_result=str(tc.get("output") or tc.get("result") or "")[:4096] or None,
                    error_message=str(tc.get("error", ""))[:4096] if tc.get("error") else None,
                    duration_ms=float(tc_duration) if tc_duration else None,
                    started_at=started_at,
                )
                session.add(tc_record)

            session.commit()
        except Exception:
            session.rollback()
            logger.warning("Failed to record invoke trace for %s", agent_name, exc_info=True)


def _apply_recalled_memory_to_request(
    agent_name: str,
    namespace: str,
    agent: dict[str, Any],
    prompt: str,
    request_payload: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    policy_memory = resolve_agent_memory_policy(agent, namespace)
    normalized_memory_policy = _normalize_memory_policy(policy_memory)
    promoted_memory = list_promoted_memory_records(
        namespace,
        agent_name,
        username=_invoke_username(user),
    )
    ranked_memory = rank_promoted_memory_records(
        prompt,
        promoted_memory,
        memory_policy=normalized_memory_policy,
    )
    memory_note = build_memory_context_system_note(ranked_memory)
    if memory_note:
        existing_system = str(request_payload.get("system") or "").strip()
        request_payload["system"] = f"{memory_note}\n\n{existing_system}" if existing_system else memory_note
        logger.info(
            "Memory injected for %s/%s: %d candidates → %d ranked → %d chars injected",
            namespace,
            agent_name,
            len(promoted_memory),
            len(ranked_memory),
            len(memory_note),
        )
    else:
        logger.info(
            "No memory injected for %s/%s: %d candidates, %d ranked (policy: autoPromote=%s, max=%d)",
            namespace,
            agent_name,
            len(promoted_memory),
            len(ranked_memory),
            normalized_memory_policy.get("autoPromote", False),
            normalized_memory_policy.get("maxInjectedMemories", 5),
        )
    return normalized_memory_policy


def _record_invoke_response_side_effects(
    namespace: str,
    agent_name: str,
    agent: dict[str, Any],
    data: dict[str, Any],
    user: dict[str, Any],
    request_id: str,
    normalized_memory_policy: dict[str, Any],
) -> None:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    agent_spec = agent.get("spec") if isinstance(agent.get("spec"), dict) else {}
    if usage or data.get("model"):
        try:
            record_usage(
                agent_name=agent_name,
                namespace=namespace,
                user_id=user.get("sub"),
                model=data.get("model") or agent_spec.get("model"),
                prompt_tokens=int((usage or {}).get("prompt_tokens", 0)),
                completion_tokens=int((usage or {}).get("completion_tokens", 0)),
                total_tokens=int((usage or {}).get("total_tokens", 0)),
                session_id=data.get("thread_id"),
                request_id=request_id,
            )
        except Exception:
            logger.warning("Failed to record usage for %s", agent_name, exc_info=True)
    try:
        record_runtime_memory(
            namespace,
            agent_name,
            session_id=str(data.get("thread_id") or "").strip() or None,
            username=_invoke_username(user),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
            auto_promote=bool(normalized_memory_policy.get("autoPromote", False)),
        )
    except Exception:
        logger.warning("Failed to record runtime memory for %s", agent_name, exc_info=True)
    _record_invoke_trace(
        namespace=namespace,
        agent_name=agent_name,
        agent=agent,
        data=data,
        request_id=request_id,
    )

@router.get("/agents", response_model=list[AgentInfo])
def list_agents(namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    return sorted([agent_info_from_resource(agent) for agent in get_agents(namespace)], key=lambda item: item.name)


@router.post("/agents", response_model=AgentDetail, status_code=201)
def create_agent(
    body: CreateAgentRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    agent = create_agent_resource(body, namespace)
    return agent_detail_from_resource(agent)


@router.get("/namespaces")
async def list_namespaces(user=Depends(verify_token)):
    """Return Kubernetes namespaces the caller is permitted to access."""
    ensure_role(user, "viewer")
    allowed = user.get("allowed_namespaces") or []
    try:
        from kubernetes import client

        ns_list = client.CoreV1Api().list_namespace()
        all_ns = sorted(ns.metadata.name for ns in ns_list.items if ns.metadata and ns.metadata.name)
    except Exception as exc:
        logger.warning("Could not list K8s namespaces: %s", exc)
        # Fall back to what the user's token says they can access
        if "*" in allowed:
            return {"namespaces": ["default"]}
        return {"namespaces": sorted(set(allowed)) if allowed else ["default"]}

    if "*" in allowed:
        return {"namespaces": all_ns}
    return {"namespaces": [ns for ns in all_ns if ns in allowed]}


@router.get("/agents/{agent_name}", response_model=AgentDetail)
def get_agent(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    return agent_detail_from_resource(read_agent(agent_name, namespace))


@router.get("/agents/{agent_name}/discover", response_model=AgentDiscoveryResponse)
def discover_agent_targets(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    return discover_agent_peers(agent_name, namespace)


@router.patch("/agents/{agent_name}", response_model=AgentDetail)
def update_agent(
    agent_name: str,
    body: UpdateAgentRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    current_agent = read_agent(agent_name, namespace)
    next_spec = build_agent_spec(body, current_agent.get("spec", {}), namespace=namespace)
    validate_agent_runtime_compatibility(next_spec)
    updated = replace_custom_resource_spec(
        "aiagents",
        agent_name,
        namespace,
        next_spec,
    )

    opa_config = next_spec.get("opa") if isinstance(next_spec, dict) else None
    if isinstance(opa_config, dict):
        ensure_opa_configmap(agent_name, namespace, opa_config)

    return agent_detail_from_resource(updated)


@router.delete("/agents/{agent_name}", response_model=DeleteResponse)
def delete_agent(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    delete_custom_resource("aiagents", agent_name, namespace, "Agent")
    return DeleteResponse(status="deleted", kind="agent", name=agent_name, namespace=namespace)


@router.post("/agents/{agent_name}/clone", response_model=AgentDetail, status_code=201)
def clone_agent(
    agent_name: str,
    namespace: str = "default",
    new_name: str | None = None,
    user=Depends(verify_token),
):
    """Clone an existing agent CRD into a new resource."""
    ensure_namespace_access(user, namespace, "operator")
    source = read_agent(agent_name, namespace)

    # Determine clone name
    clone_name = new_name or f"{agent_name}-copy"
    # Sanitize to DNS-1123 label (max 63 chars, lowercase alphanumeric and hyphens)
    import re as _re

    clone_name = _re.sub(r"[^a-z0-9-]", "-", clone_name.lower()).strip("-")[:63]

    spec = dict(source.get("spec", {}))

    try:
        from kubernetes import client

        resource_body: dict[str, Any] = {
            "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
            "kind": "AIAgent",
            "metadata": {
                "name": clone_name,
                "namespace": namespace,
                "labels": {"cloned-from": agent_name},
            },
            "spec": spec,
        }

        created = client.CustomObjectsApi().create_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="aiagents",
            body=resource_body,
        )
        invalidate_agent_read_cache(agent_name=clone_name, namespace=namespace)
        return agent_detail_from_resource(created)
    except Exception as exc:
        if getattr(exc, "status", None) == 409:
            raise HTTPException(status_code=409, detail=f"Agent '{clone_name}' already exists") from exc
        logger.error("Failed to clone agent %s → %s: %s", agent_name, clone_name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to clone agent: {exc}") from exc


# ---- Git credential management ----


def _git_secret_name(agent_name: str) -> str:
    return f"{agent_name}-git-credentials"


def _github_secret_name(agent_name: str) -> str:
    return f"{agent_name}-github-credentials"


@router.post("/agents/{agent_name}/git-credentials", status_code=201)
def create_git_credentials(
    agent_name: str,
    body: GitCredentialRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a K8s Secret with git credentials for an agent."""
    ensure_namespace_access(user, namespace, "operator")
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _git_secret_name(agent_name)
    string_data: dict[str, str] = {"auth_method": body.auth_method}
    if body.auth_method == "token":
        string_data["token"] = body.token or ""
    elif body.auth_method == "basic":
        string_data["username"] = body.username or ""
        string_data["password"] = body.password or ""
    elif body.auth_method == "ssh":
        string_data["ssh_private_key"] = body.ssh_private_key or ""

    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={"app.kubernetes.io/managed-by": "kubesynapse", "agent": agent_name},
        ),
        type="Opaque",
        string_data=string_data,
    )
    try:
        client.CoreV1Api().create_namespaced_secret(namespace=namespace, body=secret)
    except ApiException as e:
        if e.status == 409:
            client.CoreV1Api().replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
        else:
            raise HTTPException(status_code=502, detail=f"Failed to create git credential secret: {e}") from e
    return {"status": "created", "secret_name": secret_name, "auth_method": body.auth_method}


@router.get("/agents/{agent_name}/git-credentials")
def get_git_credentials(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Get git credential metadata (auth method only, never exposes secrets)."""
    ensure_namespace_access(user, namespace)
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _git_secret_name(agent_name)
    try:
        secret_result = client.CoreV1Api().read_namespaced_secret(name=secret_name, namespace=namespace)
        data: dict[str, str] = getattr(secret_result, "data", None) or {}
        # Only return auth_method, never actual credentials
        import base64

        auth_method = base64.b64decode(data.get("auth_method", "")).decode() if data.get("auth_method") else "unknown"
        return {"exists": True, "secret_name": secret_name, "auth_method": auth_method}
    except ApiException as e:
        if e.status == 404:
            return {"exists": False, "secret_name": secret_name}
        raise HTTPException(status_code=502, detail=f"Failed to read git credential secret: {e}") from e


@router.delete("/agents/{agent_name}/git-credentials")
def delete_git_credentials(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete git credential secret for an agent."""
    ensure_namespace_access(user, namespace, "operator")
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _git_secret_name(agent_name)
    try:
        client.CoreV1Api().delete_namespaced_secret(name=secret_name, namespace=namespace)
        return {"status": "deleted", "secret_name": secret_name}
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Git credentials not found for agent '{agent_name}'") from e
        raise HTTPException(status_code=502, detail=f"Failed to delete git credential secret: {e}") from e


@router.post("/agents/{agent_name}/github-credentials", status_code=201)
def create_github_credentials(
    agent_name: str,
    body: GitHubCredentialRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a K8s Secret with GitHub MCP credentials for an agent."""
    ensure_namespace_access(user, namespace, "operator")
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _github_secret_name(agent_name)
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={"app.kubernetes.io/managed-by": "kubesynapse", "agent": agent_name},
        ),
        type="Opaque",
        string_data={"token": body.token},
    )
    try:
        client.CoreV1Api().create_namespaced_secret(namespace=namespace, body=secret)
    except ApiException as e:
        if e.status == 409:
            client.CoreV1Api().replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
        else:
            raise HTTPException(status_code=502, detail=f"Failed to create GitHub credential secret: {e}") from e
    return {"status": "created", "secret_name": secret_name}


@router.get("/agents/{agent_name}/github-credentials")
def get_github_credentials(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Get GitHub credential metadata without exposing secrets."""
    ensure_namespace_access(user, namespace)
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _github_secret_name(agent_name)
    try:
        client.CoreV1Api().read_namespaced_secret(name=secret_name, namespace=namespace)
        return {"exists": True, "secret_name": secret_name}
    except ApiException as e:
        if e.status == 404:
            return {"exists": False, "secret_name": secret_name}
        raise HTTPException(status_code=502, detail=f"Failed to read GitHub credential secret: {e}") from e


@router.delete("/agents/{agent_name}/github-credentials")
def delete_github_credentials(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete GitHub credential secret for an agent."""
    ensure_namespace_access(user, namespace, "operator")
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _github_secret_name(agent_name)
    try:
        client.CoreV1Api().delete_namespaced_secret(name=secret_name, namespace=namespace)
        return {"status": "deleted", "secret_name": secret_name}
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"GitHub credentials not found for agent '{agent_name}'") from e
        raise HTTPException(status_code=502, detail=f"Failed to delete GitHub credential secret: {e}") from e


@router.post("/agents/{agent_name}/invoke", response_model=InvokeResponse)
async def invoke_agent(
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    invoke_started_at = time.perf_counter()

    def _log_invoke_step(step: str) -> None:
        logger.info(
            "Invoke step agent=%s namespace=%s step=%s elapsed_ms=%.1f",
            agent_name,
            namespace,
            step,
            (time.perf_counter() - invoke_started_at) * 1000.0,
        )

    agent_name, namespace = resolve_invoke_agent_reference(agent_name, namespace)
    _log_invoke_step("resolved_reference")
    ensure_namespace_access(user, namespace, "operator")
    _log_invoke_step("namespace_access_checked")

    # Rate-limit agent invocation by user
    username = _invoke_username(user) or "anonymous"
    rate_key = api_rate_limit_key("invoke", username)
    if api_rate_limited(rate_key):
        raise HTTPException(status_code=429, detail="Too many agent invocations. Please retry shortly.")
    note_api_request(rate_key)

    agent = await asyncio.to_thread(read_agent_cached, agent_name, namespace)
    _log_invoke_step("agent_loaded")
    validate_invoke_runtime_compatibility(runtime_kind_from_spec(agent.get("spec", {})), request)
    _log_invoke_step("runtime_validated")
    if request.factory_mode and not is_factory_agent_resource(agent_name, agent):
        raise HTTPException(status_code=400, detail="factory_mode is only supported for the kubesynapse factory agent.")
    request_payload = request.model_dump(exclude={"factory_mode"})
    _log_invoke_step("memory_policy_resolved")
    normalized_memory_policy = _apply_recalled_memory_to_request(
        agent_name,
        namespace,
        agent,
        request.prompt,
        request_payload,
        user,
    )
    _log_invoke_step("promoted_memory_loaded")
    _log_invoke_step("promoted_memory_ranked")
    append_system_note(request_payload, build_agent_collaboration_system_note(agent_name, namespace, agent))
    _log_invoke_step("collaboration_note_appended")
    # Auto-inject intelligence context for intelligence-aware agents
    if _agent_wants_intelligence(agent):
        intel_ctx = _build_auto_intelligence_context(namespace)
        if intel_ctx:
            existing_system = str(request_payload.get("system") or "").strip()
            request_payload["system"] = f"{existing_system}\n\n{intel_ctx}" if existing_system else intel_ctx
        _log_invoke_step("intelligence_context_processed")
    if request.factory_mode:
        append_system_note(request_payload, FACTORY_MODE_SYSTEM_NOTES.get(request.factory_mode))
    request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())

    # Validate model availability and get fallback chain
    agent_model = agent.get("spec", {}).get("model", "")
    fallback_models = await get_fallback_chain(agent_model) if agent_model else [agent_model]
    _log_invoke_step("model_fallback_resolved")

    runtime_url = agent_runtime_url(agent_name, namespace)
    agent_key = f"{namespace}/{agent_name}"

    for model in fallback_models:
        try:
            _log_invoke_step(f"runtime_request_start_model={model}")
            response = await invoke_with_retry(
                runtime_url,
                "/invoke",
                {**request_payload, "model": model} if model != agent_model else request_payload,
                headers={"x-request-id": request_id},
                timeout=AGENT_RUNTIME_TIMEOUT_SECONDS,
                agent_key=agent_key,
            )
            _log_invoke_step("runtime_request_complete")
        except (CircuitBreakerOpenError, RuntimeUnhealthyError) as exc:
            logger.warning("Runtime unavailable for %s: %s", agent_key, exc)
            raise HTTPException(
                status_code=503,
                detail=_invoke_error_detail(str(exc), agent_name, namespace, request_id),
            ) from exc
        except Exception as exc:
            logger.error("Agent invocation failed (agent=%s, namespace=%s, request_id=%s): %s",
                         agent_name, namespace, request_id, exc)
            if model != fallback_models[-1]:
                logger.info("Trying fallback model: %s", model)
                continue
            raise HTTPException(
                status_code=502,
                detail=_invoke_error_detail("Agent invocation failed", agent_name, namespace, request_id),
            ) from exc

        if response.status_code >= 400:
            error_payload = error_payload_from_body(response.content, "Agent invocation failed")
            if model != fallback_models[-1] and response.status_code in (429, 500, 502, 503, 504):
                logger.info("Model %s failed with %d, trying fallback", model, response.status_code)
                record_model_failure(model, error_payload.get("error", "unknown"))
                continue
            record_model_failure(model, error_payload.get("error", "unknown"))
            raise HTTPException(
                status_code=502,
                detail=_invoke_error_detail(
                    error_payload.get("error", "Agent invocation failed"), agent_name, namespace, request_id
                ),
            )

        data = parse_json_object_response(response, context="Agent runtime /invoke")
        _log_invoke_step("runtime_response_parsed")
        record_model_success(model, (time.perf_counter() - invoke_started_at) * 1000)

        latency_ms = (time.perf_counter() - invoke_started_at) * 1000
        emit_invoke_audit(
            user=username,
            agent=agent_name,
            namespace=namespace,
            request_id=request_id,
            status="success",
            latency_ms=latency_ms,
            model=model,
        )
        _record_invoke_response_side_effects(
            namespace,
            agent_name,
            agent,
            data,
            user,
            request_id,
            normalized_memory_policy,
        )
        return InvokeResponse(
            agent_name=agent_name,
            response=data.get("response", ""),
            thread_id=data.get("thread_id", ""),
            model=data.get("model") or agent["spec"].get("model", "unknown"),
            policy_name=data.get("policy_name"),
            tool_name=data.get("tool_name"),
            tool_result=data.get("tool_result"),
            sandbox_session=data.get("sandbox_session"),
            status=data.get("status", "completed"),
            approval_name=data.get("approval_name"),
            retry_after_seconds=data.get("retry_after_seconds"),
            a2a=data.get("a2a"),
            subagents=data.get("subagents"),
            warnings=data.get("warnings") or [],
            artifacts=data.get("artifacts") or [],
            tool_calls=data.get("tool_calls") or [],
            metadata=data.get("metadata"),
        )

    raise HTTPException(
        status_code=502,
        detail=_invoke_error_detail("No runtime response returned", agent_name, namespace, request_id),
    )


@router.post("/agents/{agent_namespace}/{agent_name}/invoke", response_model=InvokeResponse)
async def invoke_agent_with_namespace_path(
    agent_namespace: str,
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str | None = None,
    user=Depends(verify_token),
):
    resolved_agent_name, resolved_namespace = resolve_invoke_agent_reference(
        agent_name,
        namespace,
        path_namespace=agent_namespace,
    )
    return await invoke_agent(resolved_agent_name, request, raw_request, resolved_namespace, user)


@router.post("/agents/{agent_name}/invoke/stream")
async def invoke_agent_stream(
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    invoke_started_at = time.perf_counter()
    agent_name, namespace = resolve_invoke_agent_reference(agent_name, namespace)
    ensure_namespace_access(user, namespace, "operator")  # P1-7: invoke is a mutating operation
    agent = await asyncio.to_thread(read_agent_cached, agent_name, namespace)
    validate_invoke_runtime_compatibility(runtime_kind_from_spec(agent.get("spec", {})), request)
    if request.factory_mode and not is_factory_agent_resource(agent_name, agent):
        raise HTTPException(status_code=400, detail="factory_mode is only supported for the kubesynapse factory agent.")
    request_payload = request.model_dump(exclude={"factory_mode"})
    normalized_memory_policy = _apply_recalled_memory_to_request(
        agent_name,
        namespace,
        agent,
        request.prompt,
        request_payload,
        user,
    )
    memory_injected = str(request_payload.get("system") or "").startswith(
        "You have persistent memory from prior conversations"
    )
    append_system_note(request_payload, build_agent_collaboration_system_note(agent_name, namespace, agent))
    # Auto-inject intelligence context for intelligence-aware agents
    if _agent_wants_intelligence(agent):
        intel_ctx = _build_auto_intelligence_context(namespace)
        if intel_ctx:
            existing_system = str(request_payload.get("system") or "").strip()
            request_payload["system"] = f"{existing_system}\n\n{intel_ctx}" if existing_system else intel_ctx
    if request.factory_mode:
        append_system_note(request_payload, FACTORY_MODE_SYSTEM_NOTES.get(request.factory_mode))
    request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())
    username = _invoke_username(user) or "anonymous"
    agent_key = f"{namespace}/{agent_name}"
    runtime_url = agent_runtime_url(agent_name, namespace)

    async def event_generator():
        stream_buffer = ""

        try:
            # Validate model and get fallback chain
            agent_model = agent.get("spec", {}).get("model", "")
            fallback_models = await get_fallback_chain(agent_model) if agent_model else [agent_model]

            for model in fallback_models:
                payload = {**request_payload, "model": model} if model != agent_model else request_payload
                try:
                    if memory_injected:
                        thread_id = str(payload.get("thread_id") or "").strip() or str(uuid.uuid4())
                        payload["thread_id"] = thread_id
                        yield sse_event("response.started", {"thread_id": thread_id, "source": "gateway"})
                        response = await invoke_with_retry(
                            runtime_url,
                            "/invoke",
                            payload,
                            headers={"x-request-id": request_id},
                            timeout=AGENT_RUNTIME_TIMEOUT_SECONDS,
                            agent_key=agent_key,
                            skip_health_check=True,
                        )
                        if response.status_code >= 400:
                            err = error_payload_from_body(response.content, "Agent invocation failed")
                            err["detail"] = _invoke_error_detail(
                                err.get("error", "Agent invocation failed"), agent_name, namespace, request_id
                            )
                            if model != fallback_models[-1] and response.status_code in (429, 500, 502, 503, 504):
                                record_model_failure(model, err.get("error", "unknown"))
                                continue
                            yield sse_event("response.error", err)
                            return
                        data = parse_json_object_response(response, context="Agent runtime /invoke")
                        record_model_success(model, (time.perf_counter() - invoke_started_at) * 1000)
                        _record_invoke_response_side_effects(
                            namespace,
                            agent_name,
                            agent,
                            data,
                            user,
                            request_id,
                            normalized_memory_policy,
                        )
                        response_text = str(data.get("response") or "")
                        if response_text:
                            yield sse_event(
                                "response.delta",
                                {
                                    "thread_id": data.get("thread_id") or thread_id,
                                    "delta": response_text,
                                    "source": "gateway",
                                },
                            )
                        yield sse_event(
                            "response.completed",
                            {
                                "thread_id": data.get("thread_id") or thread_id,
                                "response": response_text,
                                "model": data.get("model") or model,
                                "status": data.get("status", "completed"),
                                "approval_name": data.get("approval_name"),
                                "a2a": data.get("a2a"),
                                "warnings": data.get("warnings") or [],
                                "artifacts": data.get("artifacts") or [],
                                "tool_calls": data.get("tool_calls") or [],
                                "metadata": data.get("metadata"),
                            },
                        )
                        latency_ms = (time.perf_counter() - invoke_started_at) * 1000
                        emit_invoke_audit(
                            user=username,
                            agent=agent_name,
                            namespace=namespace,
                            request_id=request_id,
                            status="success",
                            latency_ms=latency_ms,
                            model=model,
                        )
                        return

                    async for response in stream_with_retry(
                        runtime_url,
                        "/invoke/stream",
                        payload,
                        headers={"x-request-id": request_id},
                        # WP-4: pass no explicit timeout so stream_with_retry
                        # uses AGENT_STREAM_TIMEOUT_SECONDS (default: unlimited).
                        timeout=None,
                        agent_key=agent_key,
                    ):
                        if response.status_code >= 400:
                            body = await response.aread()
                            err = error_payload_from_body(body, "Agent invocation failed")
                            err["detail"] = _invoke_error_detail(
                                err.get("error", "Agent invocation failed"), agent_name, namespace, request_id
                            )
                            if model != fallback_models[-1] and response.status_code in (429, 500, 502, 503, 504):
                                record_model_failure(model, err.get("error", "unknown"))
                                break
                            yield sse_event("response.error", err)
                            return
                        stream_iterator = response.aiter_text()

                        async def _next_chunk(it=stream_iterator) -> str:
                            return await anext(it)

                        next_chunk_task = asyncio.create_task(_next_chunk())
                        try:
                            while True:
                                done, _ = await asyncio.wait({next_chunk_task}, timeout=STREAM_KEEPALIVE_SECONDS)
                                if not done:
                                    yield sse_keepalive_comment()
                                    continue

                                try:
                                    chunk = next_chunk_task.result()
                                except StopAsyncIteration:
                                    break

                                if chunk:
                                    yield chunk
                                    stream_buffer += chunk
                                    while "\n\n" in stream_buffer:
                                        raw_event, stream_buffer = stream_buffer.split("\n\n", 1)
                                        event_name = "message"
                                        data_lines: list[str] = []
                                        for line in raw_event.splitlines():
                                            if line.startswith(":"):
                                                continue
                                            if line.startswith("event:"):
                                                event_name = line[6:].strip() or "message"
                                            elif line.startswith("data:"):
                                                data_lines.append(line[5:].strip())
                                        if event_name != "response.completed" or not data_lines:
                                            continue
                                        try:
                                            completion_payload = json.loads("\n".join(data_lines))
                                        except json.JSONDecodeError:
                                            continue
                                        if isinstance(completion_payload, dict):
                                            _record_invoke_response_side_effects(
                                                namespace,
                                                agent_name,
                                                agent,
                                                completion_payload,
                                                user,
                                                request_id,
                                                normalized_memory_policy,
                                            )
                                            record_model_success(model, (time.perf_counter() - invoke_started_at) * 1000)
                                            latency_ms = (time.perf_counter() - invoke_started_at) * 1000
                                            emit_invoke_audit(
                                                user=username,
                                                agent=agent_name,
                                                namespace=namespace,
                                                request_id=request_id,
                                                status="success",
                                                latency_ms=latency_ms,
                                                model=model,
                                            )

                                next_chunk_task = asyncio.create_task(_next_chunk())
                        finally:
                            try:
                                if not next_chunk_task.done():
                                    next_chunk_task.cancel()
                                    with contextlib.suppress(asyncio.CancelledError):
                                        await next_chunk_task
                            except NameError:
                                pass
                        return
                except (CircuitBreakerOpenError, RuntimeUnhealthyError) as exc:
                    logger.warning("Runtime unavailable for %s: %s", agent_key, exc)
                    yield sse_event("response.error", {
                        "error": "Runtime unavailable",
                        "detail": _invoke_error_detail(str(exc), agent_name, namespace, request_id),
                    })
                    return
                except Exception as exc:
                    if model != fallback_models[-1]:
                        logger.info("Stream failed with model %s, trying fallback", model)
                        record_model_failure(model, str(exc))
                        continue
                    raise

        except Exception as exc:
            logger.error("Streaming invoke error (agent=%s, namespace=%s, request_id=%s): %s",
                         agent_name, namespace, request_id, exc)
            emit_invoke_audit(
                user=username,
                agent=agent_name,
                namespace=namespace,
                request_id=request_id,
                status="failed",
                latency_ms=(time.perf_counter() - invoke_started_at) * 1000,
                detail=str(exc),
            )
            yield sse_event("response.error", {
                "error": str(exc),
                "detail": _invoke_error_detail("Streaming invocation error", agent_name, namespace, request_id),
            })

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/agents/{agent_namespace}/{agent_name}/invoke/stream")
async def invoke_agent_stream_with_namespace_path(
    agent_namespace: str,
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str | None = None,
    user=Depends(verify_token),
):
    resolved_agent_name, resolved_namespace = resolve_invoke_agent_reference(
        agent_name,
        namespace,
        path_namespace=agent_namespace,
    )
    return await invoke_agent_stream(resolved_agent_name, request, raw_request, resolved_namespace, user)


@router.get("/agents/{agent_name}/todo")
async def get_agent_todos(
    agent_name: str,
    thread_id: str,
    request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    # Forward If-None-Match from client for ETag-based conditional polling
    upstream_headers: dict[str, str] = {}
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        upstream_headers["If-None-Match"] = if_none_match
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/todo",
                params={"thread_id": thread_id},
                headers=upstream_headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch agent todos: {exc}") from exc

    if response.status_code == 304:
        return Response(status_code=304, headers={"ETag": response.headers.get("etag", "")})
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Agent thread not found")
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Agent todo request failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Agent todo request failed")
    resp_headers: dict[str, str] = {}
    if etag := response.headers.get("etag"):
        resp_headers["ETag"] = etag
    return JSONResponse(content=response.json(), headers=resp_headers)


@router.get("/agents/{agent_name}/diff")
async def get_agent_diff(
    agent_name: str,
    thread_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return the unified diff of file changes for the given agent thread."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/diff",
                params={"thread_id": thread_id},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch session diff: {exc}") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Agent thread not found")
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Agent diff request failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Agent diff request failed")
    return JSONResponse(content=response.json())


@router.get("/agents/{agent_name}/question")
async def get_agent_questions(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """List pending question requests for an agent."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/question",
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch agent questions: {exc}") from exc
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Agent question request failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Agent question request failed")
    return JSONResponse(content=response.json())


@router.post("/agents/{agent_name}/question/{request_id}/reply")
async def reply_agent_question(
    agent_name: str,
    request_id: str,
    request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Reply to a pending question request."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.post(
                f"{agent_runtime_url(agent_name, namespace)}/question/{request_id}/reply",
                json=body,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reply to question: {exc}") from exc
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Question reply failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Question reply failed")
    return JSONResponse(content=response.json())


@router.post("/agents/{agent_name}/question/{request_id}/reject")
async def reject_agent_question(
    agent_name: str,
    request_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Reject a pending question request."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.post(
                f"{agent_runtime_url(agent_name, namespace)}/question/{request_id}/reject",
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reject question: {exc}") from exc
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Question reject failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Question reject failed")
    return JSONResponse(content=response.json())


@router.get("/agents/{agent_name}/artifacts/download")
async def download_agent_artifact(
    agent_name: str,
    path: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent_cached, agent_name, namespace)

    async with httpx.AsyncClient(timeout=AGENT_RUNTIME_TIMEOUT_SECONDS, trust_env=False) as client:
        try:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/artifacts/download",
                params={"path": path},
            )
        except Exception as exc:
            logger.error("Artifact download failed (%s/%s): %s", namespace, agent_name, exc)
            raise HTTPException(status_code=502, detail="Artifact download failed") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Artifact download failed")
        status_code = response.status_code if response.status_code in {400, 404} else 502
        raise HTTPException(status_code=status_code, detail=error_payload["error"])

    passthrough_headers = {}
    content_disposition = response.headers.get("content-disposition")
    if content_disposition:
        passthrough_headers["content-disposition"] = content_disposition
    content_length = response.headers.get("content-length")
    if content_length:
        passthrough_headers["content-length"] = content_length

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type") or "application/octet-stream",
        headers=passthrough_headers,
    )


@router.get("/agents/{agent_name}/artifacts/zip")
async def download_agent_artifacts_zip(
    agent_name: str,
    namespace: str = "default",
    root: str = "",
    user=Depends(verify_token),
):
    """Download a ZIP archive of all workspace files from an agent runtime."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent_cached, agent_name, namespace)

    params: dict[str, str] = {}
    if root:
        params["root"] = root

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False) as client:
        try:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/artifacts/zip",
                params=params,
            )
        except Exception as exc:
            logger.error("Artifact zip download failed (%s/%s): %s", namespace, agent_name, exc)
            raise HTTPException(status_code=502, detail="Artifact zip download failed") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Artifact zip download failed")
        status_code = response.status_code if response.status_code in {400, 404} else 502
        raise HTTPException(status_code=status_code, detail=error_payload["error"])

    passthrough_headers = {}
    content_disposition = response.headers.get("content-disposition")
    if content_disposition:
        passthrough_headers["content-disposition"] = content_disposition
    content_length = response.headers.get("content-length")
    if content_length:
        passthrough_headers["content-length"] = content_length

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type") or "application/zip",
        headers=passthrough_headers,
    )


@router.get("/agents/{agent_name}/artifacts/list")
async def list_agent_artifacts(
    agent_name: str,
    namespace: str = "default",
    root: str = "",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent_cached, agent_name, namespace)

    params: dict[str, str] = {}
    if root:
        params["root"] = root

    async with httpx.AsyncClient(timeout=AGENT_RUNTIME_TIMEOUT_SECONDS, trust_env=False) as client:
        try:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/artifacts/list",
                params=params,
            )
        except Exception as exc:
            logger.error("Artifact list failed (%s/%s): %s", namespace, agent_name, exc)
            raise HTTPException(status_code=502, detail="Artifact listing failed") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Artifact listing failed")
        status_code = response.status_code if response.status_code in {400, 404} else 502
        raise HTTPException(status_code=status_code, detail=error_payload["error"])

    return response.json()


@router.get("/agents/{agent_name}/logs")
def get_agent_logs(
    agent_name: str,
    namespace: str = "default",
    tail: int = 200,
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    read_agent(agent_name, namespace)
    tail = max(1, min(tail, 5000))
    try:
        pods = list_agent_pods(agent_name, namespace)
        if not pods:
            raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

        pod_name = str(getattr(pods[0].metadata, "name", "") or "")
        if not pod_name:
            raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

        from kubernetes import client

        logs = client.CoreV1Api().read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container="agent-runtime",
            tail_lines=tail,
            timestamps=True,
        )
        return {"agent_name": agent_name, "pod_name": pod_name, "logs": logs}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Could not retrieve logs for %s/%s: %s", namespace, agent_name, exc)
        raise HTTPException(
            status_code=404,
            detail=f"Could not retrieve logs (agent={agent_name}, namespace={namespace}): {exc}",
        ) from exc


@router.get("/agents/{agent_name}/logs/stream")
async def stream_agent_logs(
    agent_name: str,
    request: Request,
    namespace: str = "default",
    tail: int = 50,
    user=Depends(verify_token),
):
    """Stream pod logs via SSE using Kubernetes follow=True."""
    ensure_namespace_access(user, namespace)
    read_agent(agent_name, namespace)
    tail = max(1, min(tail, 5000))

    pods = list_agent_pods(agent_name, namespace)
    if not pods:
        raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

    pod_name = str(getattr(pods[0].metadata, "name", "") or "")
    if not pod_name:
        raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

    async def log_event_generator():
        import time

        from kubernetes import client as k8s_client
        from kubernetes import watch as k8s_watch

        yield sse_event("log.started", {"agent_name": agent_name, "pod_name": pod_name})

        w = k8s_watch.Watch()
        try:
            log_stream = w.stream(
                k8s_client.CoreV1Api().read_namespaced_pod_log,
                name=pod_name,
                namespace=namespace,
                container="agent-runtime",
                follow=True,
                tail_lines=tail,
                timestamps=True,
                _request_timeout=0,
            )
            last_event_time = time.monotonic()
            for line in log_stream:
                if await request.is_disconnected():
                    break
                yield sse_event("log.line", {"line": line})
                last_event_time = time.monotonic()
                await asyncio.sleep(0)  # yield control so disconnect check works
                # Send keepalive if idle for too long (prevents proxy timeouts)
                if time.monotonic() - last_event_time > STREAM_KEEPALIVE_SECONDS:
                    yield sse_keepalive_comment()
                    last_event_time = time.monotonic()
        except Exception as exc:
            yield sse_event("log.error", {"error": str(exc)})
        finally:
            w.stop()
            yield sse_event("log.stopped", {"agent_name": agent_name})

    return StreamingResponse(log_event_generator(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────
# Chat Session Persistence
# ─────────────────────────────────────────────────────────────


class ChatSessionCreate(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=128)
    title: str = Field("Untitled", max_length=256)


class ChatSessionUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)


class ChatMessagePayload(BaseModel):
    message_id: str = Field(..., min_length=1, max_length=128)
    role: str = Field(..., min_length=1, max_length=32)
    content: str = ""
    status: str = "complete"
    toolName: str | None = None
    toolNode: str | None = None


class ChatMessagesSave(BaseModel):
    messages: list[ChatMessagePayload]


def _resolve_chat_session_owner(session_id: str) -> tuple[str, str, str]:
    """Return (namespace, username, agent_name) for *session_id*.  Raises 404 when the session doesn't exist."""
    from auth_store import ChatSession, db_session
    with db_session() as dbs:
        row = dbs.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return (
        str(getattr(row, "namespace", "") or ""),
        str(getattr(row, "username", "") or ""),
        str(getattr(row, "agent_name", "") or ""),
    )


def _validate_session_ownership(session_id: str, user: dict[str, Any]) -> tuple[str, str]:
    """Resolve session ownership and validate the caller has namespace access AND username match.

    Returns (namespace, agent_name) when authorized.
    Raises 403 on access denied, 404 on missing session.
    """
    namespace, session_username, agent_name = _resolve_chat_session_owner(session_id)
    ensure_namespace_access(user, namespace)
    caller_username = user.get("sub") or user.get("username")
    if session_username and caller_username and session_username != caller_username:
        from error_codes import ErrorCode, build_error_response
        raise HTTPException(
            status_code=403,
            detail=build_error_response(
                code=ErrorCode.SESSION_NOT_OWNED,
                message="Access denied: session belongs to another user",
                detail=f"Session '{session_id}' is owned by a different user.",
            ),
        )
    return namespace, agent_name


@router.get("/agents/{agent_name}/memory", response_model=list[MemoryRecordInfo])
async def api_list_agent_memory(
    agent_name: str,
    namespace: str = "default",
    session_id: str | None = None,
    limit: int = 50,
    user=Depends(verify_token),
):
    """List persisted memory records for an agent, optionally scoped to a session."""
    ensure_namespace_access(user, namespace)
    username = user.get("sub") or user.get("username")
    return [
        MemoryRecordInfo(**item)
        for item in list_memory_records(
            namespace,
            agent_name,
            username=username,
            session_id=session_id,
            limit=limit,
        )
    ]


def _resolve_memory_record_owner(record_id: int) -> tuple[str, str]:
    """Return (namespace, username) for *record_id*.  Raises 404 when the record doesn't exist."""
    from auth_store import MemoryRecord, db_session
    with db_session() as dbs:
        row = dbs.query(MemoryRecord).filter(MemoryRecord.id == record_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return (
        str(getattr(row, "namespace", "") or ""),
        str(getattr(row, "username", "") or ""),
    )
