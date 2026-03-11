"""
Guardrails Engine for AI Agent Sandbox.
Provides input sanitization (prompt injection detection) and output filtering (PII masking).
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("guardrails")

# --- Prompt Injection Detection ---
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?previous",
    r"you\s+are\s+now\s+DAN",
    r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions",
    r"jailbreak",
    r"do\s+anything\s+now",
    r"override\s+safety",
    r"bypass\s+filter",
    r"system\s*prompt\s*:",
    r"\[INST\]",
    r"<\|im_start\|>",
]

# --- PII Patterns ---
PII_PATTERNS = {
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "CREDIT_CARD": r"\b(?:\d{4}[\s-]?){3}\d{4}\b",
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "PHONE_US": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "IP_ADDRESS": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "AWS_KEY": r"(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}",
    "GENERIC_SECRET": r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[\w\-\.]{8,}['\"]?",
}


class GuardrailsEngine:
    """Enforces input and output safety policies for AI Agents."""

    def __init__(
        self,
        block_prompt_injection: bool = True,
        mask_pii: bool = True,
        blocked_input_patterns: Optional[list[str]] = None,
        blocked_output_patterns: Optional[list[str]] = None,
        max_input_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ):
        self.block_prompt_injection = block_prompt_injection
        self.mask_pii = mask_pii
        self.blocked_input_patterns = blocked_input_patterns or []
        self.blocked_output_patterns = blocked_output_patterns or []
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens

        self._compiled_input = self._compile_patterns(self.blocked_input_patterns, "input")
        self._compiled_output = self._compile_patterns(self.blocked_output_patterns, "output")
        self._injection_patterns = self._compile_patterns(
            PROMPT_INJECTION_PATTERNS,
            "prompt-injection",
        )
        self._pii_patterns = {
            name: pattern
            for name, value in PII_PATTERNS.items()
            for pattern in [self._compile_pattern(value, f"pii:{name}")]
            if pattern is not None
        }

    @staticmethod
    def _compile_pattern(pattern: str, label: str) -> re.Pattern[str] | None:
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            logger.warning("Skipping invalid %s regex '%s': %s", label, pattern, exc)
            return None

    @classmethod
    def _compile_patterns(cls, patterns: list[str], label: str) -> list[re.Pattern[str]]:
        compiled: list[re.Pattern[str]] = []
        for pattern in patterns:
            compiled_pattern = cls._compile_pattern(pattern, label)
            if compiled_pattern is not None:
                compiled.append(compiled_pattern)
        return compiled

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def validate_input(self, text: str) -> tuple[bool, str]:
        """
        Validate user input. Returns (is_safe, reason).
        If not safe, reason explains why.
        """
        if not text.strip():
            return False, "Input must not be empty"

        if self.max_input_tokens:
            estimated_tokens = self._estimate_tokens(text)
            if estimated_tokens > self.max_input_tokens:
                return False, f"Input exceeds max token limit ({estimated_tokens} > {self.max_input_tokens})"

        if self.block_prompt_injection:
            for pattern in self._injection_patterns:
                if pattern.search(text):
                    logger.warning("BLOCKED: Prompt injection detected: %s", pattern.pattern)
                    return False, f"Prompt injection detected (pattern: {pattern.pattern})"

        for pattern in self._compiled_input:
            if pattern.search(text):
                logger.warning("BLOCKED: Input matched blocked pattern: %s", pattern.pattern)
                return False, f"Input blocked by policy (pattern: {pattern.pattern})"

        return True, "OK"

    def sanitize_output(self, text: str) -> str:
        """
        Sanitize LLM output by masking PII and applying output guardrails.
        Returns the sanitized text.
        """
        sanitized = text or ""

        if self.max_output_tokens:
            estimated_tokens = self._estimate_tokens(sanitized)
            if estimated_tokens > self.max_output_tokens:
                max_chars = self.max_output_tokens * 4
                sanitized = sanitized[:max_chars] + "\n\n[OUTPUT TRUNCATED BY POLICY]"
                logger.warning("Output truncated to %s tokens", self.max_output_tokens)

        if self.mask_pii:
            for pii_type, pattern in self._pii_patterns.items():
                count = len(pattern.findall(sanitized))
                if count > 0:
                    sanitized = pattern.sub(f"[{pii_type}_REDACTED]", sanitized)
                    logger.info("Masked %s instance(s) of %s", count, pii_type)

        for pattern in self._compiled_output:
            sanitized = pattern.sub("[REDACTED_BY_POLICY]", sanitized)

        return sanitized
