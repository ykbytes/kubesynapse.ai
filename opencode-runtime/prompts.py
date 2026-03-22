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
    "files created/modified and verification results."
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
