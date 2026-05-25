"""Runtime secret redaction for tool call inputs and outputs.

Collects known secret values from environment variables at import time and
provides ``redact_secrets(text)`` to replace them with ``[REDACTED]``.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("opencode-runtime.sanitize")

# ---------------------------------------------------------------------------
# Secret env-var names whose *values* must never appear in user-facing output.
# ---------------------------------------------------------------------------
_SECRET_ENV_NAMES: list[str] = [
    "API_GATEWAY_SHARED_TOKEN",
    "MCP_BEARER_TOKEN",
    "GITHUB_MCP_TOKEN",
    "LITELLM_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
]

# Env vars whose values are sensitive infrastructure URLs.
_URL_ENV_NAMES: list[str] = [
    "API_GATEWAY_INTERNAL_URL",
]

# ---------------------------------------------------------------------------
# Build redaction table at import time.
# ---------------------------------------------------------------------------

_REDACTION_LITERALS: list[tuple[str, str]] = []
_REDACTION_PREFIXES: list[tuple[re.Pattern[str], str]] = []


def _build_redaction_table() -> None:
    """Collect non-empty secret values and build literal + prefix matchers."""
    for name in _SECRET_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if len(value) >= 6:
            _REDACTION_LITERALS.append((value, f"[{name}_REDACTED]"))
            # Also catch partial leaks (e.g. ${VAR:0:20})
            prefix = value[:20]
            if len(prefix) >= 6 and prefix != value:
                pattern = re.compile(re.escape(prefix) + r"[\w.~+/=-]*", re.IGNORECASE)
                _REDACTION_PREFIXES.append((pattern, f"[{name}_REDACTED]"))
    for name in _URL_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            _REDACTION_LITERALS.append((value, "[INTERNAL-URL]"))


_build_redaction_table()

# ---------------------------------------------------------------------------
# Regex-based fallbacks (catch patterns even if exact values aren't loaded).
# ---------------------------------------------------------------------------

_SECRET_ENV_REF_RE = re.compile(
    r"\$[{]?[A-Z_]*(?:TOKEN|SECRET|KEY|PASSWORD|CREDENTIALS|AUTH|INTERNAL_URL|GATEWAY|BEARER)[A-Z_]*(?::[^}]*)?\}?",
    re.IGNORECASE,
)
_INLINE_SECRET_RE = re.compile(
    r"(?:token|key|secret|password|api[_-]?key|shared[_-]?token)\s*[=:]\s*['\"]?[\w.~+/=-]{8,}['\"]?",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"Bearer\s+[\w.~+/=-]{6,}", re.IGNORECASE)
_K8S_INTERNAL_URL_RE = re.compile(
    r"https?://[\w][\w.-]*\.svc\.cluster\.local(?::\d+)?(?:/\S*)?",
    re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Replace known secret values and common secret patterns with redaction placeholders."""
    if not text:
        return text

    result = text

    # 1. Exact value matches (highest fidelity)
    for literal, replacement in _REDACTION_LITERALS:
        if literal in result:
            result = result.replace(literal, replacement)

    # 2. Prefix-based matches (partial leaks)
    for pattern, replacement in _REDACTION_PREFIXES:
        result = pattern.sub(replacement, result)

    # 3. Regex fallbacks
    result = _SECRET_ENV_REF_RE.sub("$***", result)
    result = _INLINE_SECRET_RE.sub("[REDACTED]", result)
    result = _BEARER_RE.sub("Bearer [REDACTED]", result)
    result = _K8S_INTERNAL_URL_RE.sub("[INTERNAL-URL]", result)

    return result
