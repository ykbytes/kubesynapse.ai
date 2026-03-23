"""System prompt constants and prompt construction helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from config import MAX_SYSTEM_PROMPT_CHARS

logger = logging.getLogger("opencode-runtime")

FORMAT_INSTRUCTIONS: dict[str, str] = {
    "json": (
        "IMPORTANT: Your final response MUST be valid JSON only. "
        "No markdown fencing, no explanation text before or after the JSON. "
        "The output must be directly parseable by json.loads(). "
        "Ensure all required fields are present, values have correct types, "
        "no trailing commas appear, and no comments are included in the JSON."
    ),
    "code": (
        "IMPORTANT: Respond with the requested code only. No markdown code fences "
        "wrapping it. Include code comments where helpful but no explanatory prose "
        "outside the code. Provide complete, working implementations — never "
        "truncate with placeholders like '...' or 'rest of code here'."
    ),
    "markdown": "Respond in well-formatted Markdown.",
    "text": "Respond in plain text without any special formatting.",
}

AUTONOMY_SYSTEM_PROMPT = (
    "You are an autonomous coding agent. Follow these rules:\n"
    "1. PLAN FIRST: For complex tasks (3+ steps), use todowrite to create a structured plan "
    "before writing any code. Order steps by dependency — prerequisites first. Each step "
    "must be a single, verifiable unit of work. Track progress by updating todo status as you work.\n"
    "2. USE NATIVE TOOLS: Use your built-in tools (write, edit, bash, read, glob, grep, "
    "webfetch, websearch, codesearch) for all file and code operations — do NOT rely on "
    "external MCP servers for tasks you can do natively.\n"
    "3. ATOMIC TASK COMMITMENT: Complete each task fully before starting the next. "
    "Do not leave tasks partially done or switch to another task mid-way. "
    "One task at a time, done right.\n"
    "4. DIAGNOSE BEFORE FIXING: When you encounter an error, STOP. Read the full error message "
    "and stack trace. Identify the root cause before attempting any fix — never apply "
    "speculative patches. Address causes, not symptoms.\n"
    "5. NO USER INPUT: Do not ask for user input or clarification — make reasonable decisions "
    "and proceed autonomously.\n"
    "6. FILE OPERATIONS: Use write to create files, edit to modify existing files, "
    "bash to run commands and install dependencies.\n"
    "7. VERIFY BEFORE CLAIMING DONE: Task completion is not goal achievement. After each change, "
    "verify it works: read files back, run the code, execute tests. Work backwards from the goal — "
    "what must be TRUE for this to work? What must EXIST? What must be CONNECTED? Confirm each "
    "before marking complete.\n"
    "8. DELEGATE SUBTASKS: For complex multi-part work, use the task tool to delegate "
    "independent subtasks to parallel sub-agents.\n"
    "9. SEARCH BEFORE WRITING: Use glob, grep, and codesearch to understand existing code "
    "before making changes. Understand the codebase structure first.\n"
    "10. NO REPEATED FAILURES: If the same approach fails twice, step back and try a "
    "fundamentally different strategy. Do not retry identical commands expecting different results.\n"
    "11. CONTEXT AWARENESS: Keep your responses and plans focused. Avoid generating unnecessary "
    "output that wastes context window space. Prefer targeted edits over full-file rewrites.\n"
    "12. GIT OPERATIONS: For git operations (clone, commit, push, pull, branch), prefer using "
    "the git MCP sidecar tools (git_clone, git_commit, git_push, git_pull, git_branch) when "
    "available — they have authentication pre-configured. Only fall back to bash git commands "
    "if no git MCP tools are available. The shared repository URL is available in the "
    "GIT_REPO_URL environment variable — read it with `echo $GIT_REPO_URL` and use it as "
    "the repo_url parameter for git_clone. When cloning into the workspace, use "
    "target_dir='/workspace' and full_clone=true for push support.\n"
    "13. SUMMARIZE: Summarize what you accomplished in your final response, including "
    "files created/modified and verification results.\n"
    "14. CONTEXT BUDGET MANAGEMENT: When working on long tasks, keep your todowrite plan "
    "as the primary checkpoint — it survives context compaction. Keep tool outputs brief: "
    "avoid reading entire large files when you only need specific sections. Use read with "
    "offset/limit for large files. Prefer grep to find specific content rather than reading "
    "everything.\n"
    "15. INCREMENTAL VERIFICATION: After each significant change, verify it immediately. "
    "Do not batch all verification to the end — errors compound and become harder to diagnose "
    "when multiple changes are unverified.\n"
    "16. EFFICIENT FILE OPERATIONS: Use grep/glob to find what you need before reading entire "
    "files. Use targeted edits (edit tool) instead of full file rewrites (write tool) whenever "
    "possible. For large files, use read with offset and limit parameters.\n"
    "17. ERROR PATTERN TRACKING: Track error patterns across retries. If a tool fails, inspect "
    "its input carefully. If a command fails, check prerequisites (is the package installed? does "
    "the directory exist? are permissions correct?). Never retry without changing the approach."
)

AUTONOMY_CONTINUATION_PROMPT = (
    "Continue working on the task. Before proceeding:\n"
    "1. REVIEW: Summarize what you have completed so far and what remains.\n"
    "2. CHECK: Verify your completed work actually functions — read files back, "
    "run tests, or execute the code. Fix any issues you find.\n"
    "3. CONTINUE: Proceed with the next incomplete step in your plan.\n"
    "4. VERIFY BEFORE FINISHING: Before your final response, confirm every "
    "requirement from the original task is met — do not claim completion "
    "without fresh evidence."
)

# Context-budget-aware continuation prompts
CONTEXT_AWARE_CONTINUATION_PROMPTS: dict[str, str] = {
    "ok": AUTONOMY_CONTINUATION_PROMPT,
    "warning": (
        "Continue working on the task. Context space is becoming limited — be efficient:\n"
        "1. REVIEW: Check your todowrite plan for completed vs. remaining steps.\n"
        "2. FOCUS: Complete the most important remaining steps first.\n"
        "3. BE CONCISE: Avoid reading large files unnecessarily. Use targeted reads and "
        "grep to find specific content. Keep tool outputs brief.\n"
        "4. CHECKPOINT: Update your todowrite plan with detailed progress notes — this "
        "is your primary state checkpoint if context compaction occurs.\n"
        "5. VERIFY: Test your changes incrementally, not all at once."
    ),
    "critical": (
        "CONTEXT CRITICALLY LOW. Complete only the most essential remaining work:\n"
        "1. UPDATE PLAN: Immediately write a detailed summary of ALL progress, remaining "
        "work, and key decisions into your todowrite plan — compaction is imminent.\n"
        "2. PRIORITIZE: Identify the single most important remaining step and complete it.\n"
        "3. MINIMIZE OUTPUT: Do not read files unless absolutely necessary. Use the "
        "smallest possible tool operations.\n"
        "4. SUMMARIZE: Write a comprehensive status summary as your response, including "
        "what was done, what remains, and any blockers."
    ),
}

# Task-type-specific supplementary prompt fragments
TASK_TYPE_PROMPTS: dict[str, str] = {
    "exploration": (
        "TASK TYPE: EXPLORATION/RESEARCH. Focus on reading, understanding, and reporting. "
        "Use glob, grep, read, and codesearch to investigate. Report findings clearly and "
        "concisely. Do not make code changes unless specifically requested. Organize your "
        "findings by topic or component."
    ),
    "debugging": (
        "TASK TYPE: DEBUGGING. Follow a systematic debugging approach:\n"
        "1. REPRODUCE: First confirm the issue exists — run the failing test/command.\n"
        "2. ISOLATE: Narrow down to the specific file, function, and line causing the issue.\n"
        "3. DIAGNOSE: Read error messages carefully. Trace the execution path.\n"
        "4. FIX: Apply a targeted fix addressing the root cause, not symptoms.\n"
        "5. VERIFY: Run the test/command again to confirm the fix works. Check for regressions."
    ),
    "feature": (
        "TASK TYPE: FEATURE IMPLEMENTATION. Build incrementally:\n"
        "1. Understand existing patterns — search for similar features in the codebase.\n"
        "2. Plan the implementation steps and create a todowrite plan.\n"
        "3. Implement each component and verify it independently before moving on.\n"
        "4. Follow existing code style, naming conventions, and architectural patterns.\n"
        "5. Add tests if the project has a test suite. Run existing tests to check for regressions."
    ),
    "edit": (
        "TASK TYPE: TARGETED EDIT. Make precise, focused changes:\n"
        "1. Read the target file to understand the current state.\n"
        "2. Use the edit tool for modifications — avoid full file rewrites.\n"
        "3. Verify the edit is correct by reading the file back.\n"
        "4. Run relevant tests or checks."
    ),
    "review": (
        "TASK TYPE: CODE REVIEW. Analyze systematically:\n"
        "1. Read the relevant files thoroughly.\n"
        "2. Check for correctness, edge cases, error handling, and security issues.\n"
        "3. Look for anti-patterns, code smells, and opportunities for improvement.\n"
        "4. Provide specific, actionable feedback with file/line references."
    ),
    "refactor": (
        "TASK TYPE: REFACTORING. Preserve behavior while improving structure:\n"
        "1. Understand the current behavior — read tests and usage sites.\n"
        "2. Plan changes to minimize risk. Prefer small, incremental steps.\n"
        "3. Run tests after each change to ensure behavior is preserved.\n"
        "4. Update tests if interfaces change."
    ),
    "deployment": (
        "TASK TYPE: DEPLOYMENT/INFRASTRUCTURE. Be cautious with system changes:\n"
        "1. Read existing configuration carefully before making changes.\n"
        "2. Validate configuration syntax before applying.\n"
        "3. Check for environment-specific considerations.\n"
        "4. Document any manual steps required."
    ),
}


def get_continuation_prompt(context_budget_status: str = "ok") -> str:
    """Return the appropriate continuation prompt based on context budget status."""
    return CONTEXT_AWARE_CONTINUATION_PROMPTS.get(context_budget_status, AUTONOMY_CONTINUATION_PROMPT)


def get_task_type_prompt(task_type: str) -> str | None:
    """Return a supplementary prompt fragment for the given task type, or None."""
    return TASK_TYPE_PROMPTS.get(task_type)


def combine_system_prompt(*parts: str | None) -> str | None:
    """Combine multiple system prompt fragments into one, truncating if needed."""
    rendered = [str(item).strip() for item in parts if str(item or "").strip()]
    if not rendered:
        return None
    combined = "\n\n".join(rendered)
    if len(combined) > MAX_SYSTEM_PROMPT_CHARS:
        logger.warning(
            "Combined system prompt (%d chars) exceeds MAX_SYSTEM_PROMPT_CHARS (%d); "
            "truncating to fit. Consider shortening your system prompt.",
            len(combined),
            MAX_SYSTEM_PROMPT_CHARS,
        )
        combined = combined[:MAX_SYSTEM_PROMPT_CHARS]
    return combined


def build_format_system_prompt(output_format: str | None) -> str | None:
    """Return a system-prompt fragment for the requested output format."""
    if not output_format:
        return None
    return FORMAT_INSTRUCTIONS.get(output_format.strip().lower())


def format_team_context_system_prompt(team_context: dict[str, Any] | None) -> str | None:
    """Render team context as a system prompt fragment."""
    if not team_context:
        return None
    serialized = json.dumps(team_context, ensure_ascii=False, sort_keys=True)
    return f"Team context:\n{serialized}"


def format_memory_context(memory_entries: list[dict[str, Any]]) -> str | None:
    """Render cross-session memory entries as a system prompt fragment.

    Each entry is a dict with at least ``type`` and ``content`` keys.
    """
    if not memory_entries:
        return None
    lines = ["PRIOR SESSION MEMORY (context carried from previous sessions):"]
    for entry in memory_entries:
        entry_type = entry.get("type", "note")
        content = entry.get("content", "")
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        lines.append(f"- [{entry_type}] {content}")
    return "\n".join(lines)


def format_workspace_system_prompt(snapshot: dict[str, Any] | None) -> str | None:
    """Render a workspace snapshot as a system prompt fragment.

    The snapshot dict is produced by :func:`workspace.capture_workspace_snapshot`.
    """
    if not snapshot:
        return None
    parts = ["WORKSPACE AWARENESS (pre-computed codebase context):"]

    tech = snapshot.get("tech_stack")
    if tech:
        parts.append(f"Tech stack: {', '.join(tech) if isinstance(tech, list) else str(tech)}")

    tree = snapshot.get("directory_tree")
    if tree:
        parts.append(f"Directory structure:\n{tree}")

    key_files = snapshot.get("key_files")
    if key_files:
        parts.append(f"Key files: {', '.join(key_files[:30])}")

    file_stats = snapshot.get("file_stats")
    if file_stats:
        stats_str = ", ".join(f"{ext}: {count}" for ext, count in sorted(file_stats.items(), key=lambda x: -x[1])[:15])
        parts.append(f"File counts by extension: {stats_str}")

    git_info = snapshot.get("git_info")
    if git_info:
        parts.append(f"Git: branch={git_info.get('branch', 'unknown')}")

    return "\n".join(parts)


def build_recovery_prompt(pre_compaction_state: dict[str, Any]) -> str:
    """Build a structured recovery prompt from a pre-compaction state snapshot.

    The *pre_compaction_state* dict should contain keys such as ``todos``,
    ``artifacts``, ``last_action``, and ``current_step``.
    """
    lines = ["Context was compacted. Here is your preserved state:"]

    todos = pre_compaction_state.get("todos") or []
    completed = [t for t in todos if t.get("status") == "completed"]
    in_progress = [t for t in todos if t.get("status") == "in_progress"]
    pending = [t for t in todos if t.get("status") == "pending"]

    if completed:
        items = ", ".join(t.get("content", "?")[:80] for t in completed[:10])
        lines.append(f"COMPLETED STEPS: {items}")
    if in_progress:
        items = ", ".join(t.get("content", "?")[:80] for t in in_progress[:5])
        lines.append(f"IN PROGRESS: {items}")
    if pending:
        items = ", ".join(t.get("content", "?")[:80] for t in pending[:10])
        lines.append(f"REMAINING: {items}")

    artifacts = pre_compaction_state.get("artifacts") or []
    if artifacts:
        file_list = ", ".join(a.get("path", "?") for a in artifacts[:20])
        lines.append(f"FILES MODIFIED: {file_list}")

    last_action = pre_compaction_state.get("last_action")
    if last_action:
        lines.append(f"LAST ACTION: {last_action}")

    lines.append(
        "\nContinue from the in-progress or next pending step. "
        "Do NOT recreate files that already exist. "
        "Run `glob **/*` if you need to verify which files are present. "
        "Verify the last completed step before proceeding."
    )
    return "\n".join(lines)


def build_handoff_resumption_prompt(handoff_memory: dict[str, Any]) -> str:
    """Build a prompt to seed a new session with context from a prior session.

    The *handoff_memory* dict comes from a saved handoff memory entry.
    """
    lines = [
        "RESUMING FROM PRIOR SESSION. The previous session ran out of context space. "
        "Here is the context you need to continue:"
    ]
    original_prompt = handoff_memory.get("original_prompt")
    if original_prompt:
        lines.append(f"\nORIGINAL TASK: {original_prompt}")

    summary = handoff_memory.get("summary")
    if summary:
        lines.append(f"\nPROGRESS SUMMARY: {summary}")

    todos = handoff_memory.get("todos") or []
    completed = [t for t in todos if t.get("status") == "completed"]
    pending = [t for t in todos if t.get("status") in ("pending", "in_progress")]
    if completed:
        items = "\n".join(f"  [done] {t.get('content', '?')[:100]}" for t in completed[:15])
        lines.append(f"\nCOMPLETED:\n{items}")
    if pending:
        items = "\n".join(f"  [todo] {t.get('content', '?')[:100]}" for t in pending[:15])
        lines.append(f"\nREMAINING:\n{items}")

    artifacts = handoff_memory.get("artifacts") or []
    if artifacts:
        file_list = "\n".join(f"  - {a.get('path', '?')}" for a in artifacts[:20])
        lines.append(f"\nFILES CREATED/MODIFIED:\n{file_list}")

    lines.append(
        "\nINSTRUCTIONS:\n"
        "1. First run `glob **/*` to see all existing files.\n"
        "2. Recreate your todowrite plan from the REMAINING items above.\n"
        "3. Verify the last completed item actually works.\n"
        "4. Continue from where the previous session left off."
    )
    return "\n".join(lines)
