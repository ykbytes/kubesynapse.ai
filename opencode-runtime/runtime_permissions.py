"""§security — Runtime permission enforcement for the OpenCode runtime.

This module closes three production security gaps:

1. **Admin tool ceiling enforcement.** The operator injects a per-policy
   ``OPENCODE_ADMIN_PERMISSION_CEILING_JSON`` (derived from
   ``AgentPolicy.toolPolicy.adminToolCeiling``) that caps the maximum
   permission level an agent may exercise for each tool. Previously the
   runtime never read this value, so the cap was silently ignored. This
   module clamps the generated OpenCode config to that ceiling and gates
   autonomous auto-approval against it.

2. **Fail-closed permission baseline.** When the hardened immutable config is
   required but missing/unreadable, the runtime falls back to a restrictive
   permission set instead of OpenCode's wide-open ``"allow"``.

3. **Dangerous command denylist.** Catastrophic, unambiguous shell commands
   (``rm -rf /``, fork bombs, ``mkfs``, ``dd`` to block devices, ...) are
   never auto-approved, regardless of policy.

The OpenCode permission model (see opencode/src/permission) uses three
actions — ``ask``, ``allow``, ``deny`` — evaluated per tool. ``bash`` and
other path/command tools also support ``{pattern: action}`` objects where the
*last* matching rule wins. We preserve that contract: when injecting deny
patterns we keep the catch-all ``"*"`` first so specific deny patterns added
afterwards take precedence.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("opencode-runtime.permissions")

# ---------------------------------------------------------------------------
# Permission action model
# ---------------------------------------------------------------------------

#: Ordering used to clamp a configured action down to a ceiling. Higher = more
#: permissive. ``deny`` (0) < ``ask`` (1) < ``allow`` (2).
PERMISSION_STRENGTH: dict[str, int] = {"deny": 0, "ask": 1, "allow": 2}
_STRENGTH_TO_ACTION: dict[int, str] = {0: "deny", 1: "ask", 2: "allow"}

VALID_ACTIONS: frozenset[str] = frozenset(PERMISSION_STRENGTH)

#: Tool identifiers recognised by the ceiling/clamp logic. Mirrors the set the
#: operator validates in builders/manifests.py plus OpenCode's native tools.
VALID_TOOL_IDS: frozenset[str] = frozenset({
    "bash", "edit", "write", "read", "glob", "grep", "list",
    "webfetch", "websearch", "task", "todowrite", "skill", "question",
    "webbrowse", "external_directory", "lsp", "doom_loop", "patch",
})

#: OpenCode collapses write/patch/apply_patch into the ``edit`` permission.
_EDIT_ALIASES: frozenset[str] = frozenset({"edit", "write", "patch", "apply_patch"})


def normalize_tool_id(tool: Any) -> str:
    """Normalise a tool name to its permission key (lowercased, edit-collapsed)."""
    name = str(tool or "").strip().lower()
    if name in _EDIT_ALIASES:
        return "edit"
    return name


def _weaker_action(a: str, b: str) -> str:
    """Return the *more restrictive* (weaker) of two permission actions."""
    sa = PERMISSION_STRENGTH.get(a, 1)
    sb = PERMISSION_STRENGTH.get(b, 1)
    return _STRENGTH_TO_ACTION[min(sa, sb)]


# ---------------------------------------------------------------------------
# Admin tool ceiling (operator-injected, derived from AgentPolicy)
# ---------------------------------------------------------------------------

CEILING_ENV = "OPENCODE_ADMIN_PERMISSION_CEILING_JSON"


def load_permission_ceiling() -> dict[str, str]:
    """Load and validate the admin tool ceiling from the environment.

    Returns a mapping ``{tool_id: action}`` containing only valid tool IDs and
    actions. Returns an empty dict when no ceiling is configured (the common
    case for agents without a policy), which makes all downstream enforcement
    a no-op for backward compatibility.
    """
    raw = os.getenv(CEILING_ENV, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("%s contains invalid JSON; ignoring ceiling.", CEILING_ENV)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s must be a JSON object; ignoring ceiling.", CEILING_ENV)
        return {}

    ceiling: dict[str, str] = {}
    for tool_id, action in parsed.items():
        norm_tool = normalize_tool_id(tool_id)
        norm_action = str(action or "").strip().lower()
        if norm_tool not in VALID_TOOL_IDS:
            logger.warning("Ignoring unknown tool '%s' in %s", tool_id, CEILING_ENV)
            continue
        if norm_action not in VALID_ACTIONS:
            logger.warning("Ignoring invalid action '%s' for tool '%s' in %s", action, tool_id, CEILING_ENV)
            continue
        # If both edit and write map to "edit", keep the most restrictive.
        if norm_tool in ceiling:
            ceiling[norm_tool] = _weaker_action(ceiling[norm_tool], norm_action)
        else:
            ceiling[norm_tool] = norm_action
    return ceiling


def _clamp_rule_to_action(rule: Any, ceiling_action: str) -> Any:
    """Clamp a single permission rule (string or {pattern: action}) to a ceiling."""
    if isinstance(rule, str):
        return _weaker_action(rule, ceiling_action)
    if isinstance(rule, dict):
        clamped: dict[str, str] = {}
        for pattern, action in rule.items():
            act = str(action or "").strip().lower()
            if act not in VALID_ACTIONS:
                act = "ask"
            clamped[str(pattern)] = _weaker_action(act, ceiling_action)
        return clamped
    # Unknown shape — be safe and fall back to the ceiling action itself.
    return ceiling_action


def clamp_permissions_to_ceiling(
    permission: Any,
    ceiling: dict[str, str] | None = None,
) -> Any:
    """Clamp a generated OpenCode ``permission`` value to the admin ceiling.

    ``permission`` may be a bare action string (e.g. ``"allow"``) or a mapping
    of ``{tool: rule}``. Clamping only ever *tightens* permissions; it can
    never grant more than what was configured. Tools without a ceiling entry
    are left unchanged.

    Returns the clamped permission (same shape family as the input). When no
    ceiling is configured the input is returned unchanged.
    """
    ceiling = ceiling or {}
    if not ceiling:
        return permission

    # Normalise a bare-string permission into an explicit per-tool map so we
    # can clamp individual tools that have a ceiling entry.
    if isinstance(permission, str):
        base_action = permission.strip().lower()
        if base_action not in VALID_ACTIONS:
            base_action = "ask"
        result: dict[str, Any] = {"*": base_action}
        for tool_id, ceiling_action in ceiling.items():
            result[tool_id] = _weaker_action(base_action, ceiling_action)
        return result

    if isinstance(permission, dict):
        result = dict(permission)
        for tool_id, ceiling_action in ceiling.items():
            if tool_id in result:
                result[tool_id] = _clamp_rule_to_action(result[tool_id], ceiling_action)
            else:
                # Tool not explicitly configured: inherit catch-all if present,
                # otherwise apply the ceiling directly so it is genuinely capped.
                catch_all = result.get("*")
                if isinstance(catch_all, str):
                    result[tool_id] = _weaker_action(catch_all, ceiling_action)
                else:
                    result[tool_id] = ceiling_action
        return result

    # Unknown shape — replace with the explicit ceiling map (fail safe).
    return dict(ceiling)


# ---------------------------------------------------------------------------
# Fail-closed safe defaults
# ---------------------------------------------------------------------------

#: Restrictive permission baseline used when the hardened immutable config is
#: required but cannot be loaded. Read-only/discovery tools stay usable; any
#: tool that can mutate state, run code, or reach the network requires a human.
SAFE_DEFAULT_PERMISSION: dict[str, Any] = {
    "bash": "deny",
    "edit": "ask",
    "write": "ask",
    "read": {
        "*": "allow",
        "*clipboard*": "deny",
        "*.git-credentials*": "deny",
        "*.netrc*": "deny",
        "*.ssh/*": "deny",
        "*.kube/config*": "deny",
        "*opencode/auth*": "deny",
    },
    "glob": "allow",
    "grep": "allow",
    "list": "allow",
    "webfetch": "ask",
    "websearch": "ask",
    "task": "ask",
    "todowrite": "allow",
    "skill": "ask",
    "question": "allow",
    "webbrowse": "deny",
    "external_directory": "deny",
}


def require_immutable_config() -> bool:
    """Return True when the operator mandates a hardened immutable config.

    Set by the operator (``OPENCODE_REQUIRE_IMMUTABLE_CONFIG=true``) whenever
    ``opencodeRuntime.immutableConfig`` is enabled. When true and the immutable
    config cannot be loaded, the runtime must fail closed rather than run with
    OpenCode's permissive defaults.
    """
    return os.getenv("OPENCODE_REQUIRE_IMMUTABLE_CONFIG", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Dangerous command denylist (never auto-approved)
# ---------------------------------------------------------------------------

#: Catastrophic, unambiguous shell patterns that must never run unattended.
#: Patterns deliberately target *absolute / root / device* paths only so that
#: ordinary workspace operations (e.g. ``rm -rf node_modules``) are unaffected.
_CATASTROPHIC_BASH_PATTERNS: tuple[re.Pattern[str], ...] = (
    # rm -rf / , rm -rf /* , rm -rf ~ , rm -rf $HOME, rm -fr //
    re.compile(r"\brm\s+(?:-[a-z]*\s+)*-[a-z]*[rf][a-z]*\s+(?:-[a-z]+\s+)*(?:/|/\*|~|\$HOME|\$\{HOME\})(?:\s|$|/\*?)", re.IGNORECASE),
    re.compile(r"\brm\s+--no-preserve-root\b", re.IGNORECASE),
    # fork bomb :(){ :|:& };:
    re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
    # mkfs on any device
    re.compile(r"\bmkfs(?:\.\w+)?\s+/dev/", re.IGNORECASE),
    # dd writing to a block device
    re.compile(r"\bdd\b[^\n|]*\bof=\s*/dev/(?:sd|nvme|vd|xvd|hd|mmcblk|disk)", re.IGNORECASE),
    # overwrite raw disk / partition table
    re.compile(r">\s*/dev/(?:sd|nvme|vd|xvd|hd|mmcblk|disk)", re.IGNORECASE),
    # recursive chmod/chown of the filesystem root
    re.compile(r"\bch(?:mod|own)\s+(?:-[a-z]*\s+)*-?R[a-z]*\s+\S+\s+/(?:\s|$)", re.IGNORECASE),
    re.compile(r"\bchmod\s+(?:-[a-z]*\s+)*-?R[a-z]*\s+0*777\s+/(?:\s|$)", re.IGNORECASE),
    # wipe via find -delete from root
    re.compile(r"\bfind\s+/\s+.*-delete\b", re.IGNORECASE),
)

#: Sensitive patterns that should require a human (treated as ``ask``). In
#: autonomous mode where no human is present, these are rejected too.
_SENSITIVE_BASH_PATTERNS: tuple[re.Pattern[str], ...] = (
    # piping remote content straight into a shell (classic RCE vector)
    re.compile(r"(?:curl|wget|fetch)\b[^|]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b", re.IGNORECASE),
    # writing to system configuration / credential locations
    re.compile(r">\s*/etc/(?:passwd|shadow|sudoers|crontab|hosts)\b", re.IGNORECASE),
    re.compile(r"\b(?:tee|cp|mv)\b[^\n]*\s/etc/(?:passwd|shadow|sudoers|sudoers\.d|cron)", re.IGNORECASE),
    # privilege escalation
    re.compile(r"\bsudo\s+(?!-n\b)", re.IGNORECASE),
    # editing the kube/cloud credentials of the node
    re.compile(r"\b(?:cat|cp|mv|tee)\b[^\n]*~?/\.kube/config\b", re.IGNORECASE),
)


def _denylist_enabled() -> bool:
    return os.getenv("OPENCODE_BASH_DENYLIST_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def _extra_deny_patterns() -> list[re.Pattern[str]]:
    raw = os.getenv("OPENCODE_BASH_DENY_PATTERNS_JSON", "").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("OPENCODE_BASH_DENY_PATTERNS_JSON is invalid JSON; ignoring.")
        return []
    patterns: list[re.Pattern[str]] = []
    if isinstance(items, list):
        for item in items:
            try:
                patterns.append(re.compile(str(item), re.IGNORECASE))
            except re.error as exc:
                logger.warning("Ignoring invalid bash deny pattern %r: %s", item, exc)
    return patterns


def classify_bash_command(command: str) -> str:
    """Classify a bash command into ``deny`` | ``ask`` | ``allow``.

    ``deny`` — catastrophic, never run unattended.
    ``ask``  — sensitive, requires a human (rejected in autonomous mode).
    ``allow``— no dangerous signature detected.
    """
    text = (command or "").strip()
    if not text or not _denylist_enabled():
        return "allow"
    for pattern in _CATASTROPHIC_BASH_PATTERNS:
        if pattern.search(text):
            return "deny"
    for pattern in _extra_deny_patterns():
        if pattern.search(text):
            return "deny"
    for pattern in _SENSITIVE_BASH_PATTERNS:
        if pattern.search(text):
            return "ask"
    return "allow"


def bash_permission_with_denylist(base_rule: Any) -> Any:
    """Augment a bash permission rule with catastrophic-pattern deny entries.

    Keeps the catch-all (``"*"``) first so the appended deny patterns — which
    are inserted afterwards — take precedence under OpenCode's last-match-wins
    evaluation. Returns the rule unchanged when the denylist is disabled.
    """
    if not _denylist_enabled():
        return base_rule

    # Build the base mapping with the catch-all first.
    if isinstance(base_rule, str):
        merged: dict[str, str] = {"*": base_rule}
    elif isinstance(base_rule, dict):
        merged = {}
        if "*" in base_rule:
            merged["*"] = str(base_rule["*"])
        for pattern, action in base_rule.items():
            if pattern == "*":
                continue
            merged[str(pattern)] = str(action)
    else:
        merged = {"*": "ask"}

    # Human-readable deny globs appended last (highest precedence).
    for glob in (
        "rm -rf /*", "rm -rf /", "rm -fr /*", "rm -fr /",
        "rm --no-preserve-root *",
        "mkfs*", "dd *of=/dev/*", ":(){*", "chmod -R 777 /*", "chown -R * /",
    ):
        merged[glob] = "deny"
    return merged


# ---------------------------------------------------------------------------
# Autonomous auto-approval gating
# ---------------------------------------------------------------------------


def _permission_command_text(pending: dict[str, Any]) -> str:
    """Extract a best-effort command/pattern string from a pending permission."""
    parts: list[str] = []
    patterns = pending.get("patterns")
    if isinstance(patterns, list):
        parts.extend(str(p) for p in patterns if p)
    metadata = pending.get("metadata")
    if isinstance(metadata, dict):
        for key in ("command", "cmd", "script", "input"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
    return " ".join(parts).strip()


def evaluate_pending_permission(
    pending: dict[str, Any],
    ceiling: dict[str, str] | None = None,
    *,
    autonomous: bool = True,
) -> str:
    """Decide how to reply to a pending OpenCode permission request.

    Returns one of OpenCode's reply verbs:
      - ``"always"`` — approve (and remember for the session)
      - ``"reject"`` — deny the permission

    Decision order (most restrictive wins):
      1. Catastrophic bash command  → reject.
      2. Sensitive bash command     → reject in autonomous mode (no human).
      3. Admin ceiling ``deny``      → reject.
      4. Admin ceiling ``ask``       → reject in autonomous mode (no human).
      5. Otherwise                   → approve.

    When no ceiling is configured and the command is not dangerous, the
    behaviour matches the historical "auto-approve" default, preserving
    backward compatibility for unrestricted agents.
    """
    ceiling = ceiling or {}
    tool = normalize_tool_id(pending.get("permission") or pending.get("tool"))

    # 1 & 2: bash command-content checks
    if tool == "bash":
        verdict = classify_bash_command(_permission_command_text(pending))
        if verdict == "deny":
            logger.warning("Rejecting catastrophic bash permission %s", pending.get("id"))
            return "reject"
        if verdict == "ask" and autonomous:
            logger.warning("Rejecting sensitive bash permission %s (no human in autonomous mode)", pending.get("id"))
            return "reject"

    # 3 & 4: admin ceiling enforcement
    ceiling_action = ceiling.get(tool)
    if ceiling_action == "deny":
        logger.warning("Rejecting permission %s for tool '%s' (policy ceiling=deny)", pending.get("id"), tool)
        return "reject"
    if ceiling_action == "ask" and autonomous:
        logger.warning("Rejecting permission %s for tool '%s' (policy ceiling=ask, no human)", pending.get("id"), tool)
        return "reject"

    return "always"
