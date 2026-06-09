"""Webhook security helpers.

Security Best Practices
-----------------------
- Webhook secrets should be rotated every 90 days.
- Use unique secrets per webhook receiver (never reuse across endpoints).
- Prefer Kubernetes Secrets (secret_ref) over plaintext env vars.
- IP allowlisting is defense-in-depth, not primary security; always verify HMAC.
- Monitor the webhook invocation audit log for anomalies (spikes, signature failures).
- Supports provider-specific signature verification (GitHub, Slack, Stripe, PagerDuty).
- Supports multiple active secrets per receiver via key-id header for rotation.
- In production, the gateway Redis is used for rate limiting; falls back to DB counting.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger("api-gateway.webhook-security")

# ---------------------------------------------------------------------------
# Rate limiting — Redis-backed with in-memory fallback
# ---------------------------------------------------------------------------

_WEBHOOK_CONCURRENT: dict[str, int] = {}
_WEBHOOK_CONCURRENT_LOCK = threading.Lock()


def _get_redis_client():
    """Reuse the existing Redis client from agent_cache.py if available."""
    try:
        from agent_cache import _get_redis
        return _get_redis()
    except Exception:
        return None


_WEBHOOK_RATE_STATE: dict[str, list[float]] = {}
_WEBHOOK_RATE_LOCK = threading.Lock()


def check_webhook_rate_limit(webhook_key: str, limit: int, window_seconds: int = 60) -> None:
    """Check webhook rate limit using Redis when available, in-memory as fallback.

    Returns None if allowed, raises HTTPException(429) if exceeded.
    """
    now = time.monotonic()
    redis = _get_redis_client()

    if redis is not None:
        redis_key = f"wh:rate:{webhook_key}"
        try:
            current = redis.get(redis_key)
            count = int(current) if current else 0
            if count >= limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            pipe = redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds)
            pipe.execute()
            return
        except HTTPException:
            raise
        except Exception:
            pass  # Fall through to in-memory

    # In-memory fallback
    with _WEBHOOK_RATE_LOCK:
        timestamps = _WEBHOOK_RATE_STATE.get(webhook_key, [])
        timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(timestamps) >= limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        timestamps.append(now)
        _WEBHOOK_RATE_STATE[webhook_key] = timestamps
        if len(_WEBHOOK_RATE_STATE) > 10000:
            _WEBHOOK_RATE_STATE.clear()


def check_webhook_concurrency(webhook_key: str, max_concurrent: int) -> None:
    """Track and enforce concurrent invocation limits."""
    if max_concurrent <= 0:
        return
    with _WEBHOOK_CONCURRENT_LOCK:
        current = _WEBHOOK_CONCURRENT.get(webhook_key, 0)
        if current >= max_concurrent:
            raise HTTPException(status_code=429, detail="Concurrent invocation limit exceeded")
        _WEBHOOK_CONCURRENT[webhook_key] = current + 1


def release_webhook_concurrency(webhook_key: str) -> None:
    """Release a concurrent invocation slot."""
    with _WEBHOOK_CONCURRENT_LOCK:
        current = _WEBHOOK_CONCURRENT.get(webhook_key, 0)
        if current > 0:
            _WEBHOOK_CONCURRENT[webhook_key] = current - 1


# ---------------------------------------------------------------------------
# Timestamp / replay protection
# ---------------------------------------------------------------------------


def verify_webhook_timestamp(timestamp_header: str | None, max_age_seconds: int = 300) -> None:
    """Prevent replay attacks by checking timestamp freshness."""
    if not timestamp_header:
        raise HTTPException(status_code=401, detail="Missing X-kubesynapse-Timestamp header")
    try:
        request_time = int(timestamp_header)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid X-kubesynapse-Timestamp header")
    if abs(time.time() - request_time) > max_age_seconds:
        raise HTTPException(status_code=401, detail="Webhook timestamp is too old")


# ---------------------------------------------------------------------------
# Provider-specific signature verification
# ---------------------------------------------------------------------------


def _verify_hmac_sha256(payload: bytes, signature: str, secret: str) -> bool:
    """Generic HMAC-SHA256 verification."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (X-Hub-Signature-256)."""
    if not signature.startswith("sha256="):
        return False
    provided = signature[len("sha256="):]
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def _verify_slack_signature(payload: bytes, signature: str, secret: str, timestamp: str | None = None) -> bool:
    """Verify Slack webhook signature (X-Slack-Signature)."""
    if not timestamp:
        return False
    basestring = f"v0:{timestamp}:{payload.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(secret.encode("utf-8"), basestring.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


_STRIPE_TOLERANCE_SECONDS = max(
    int(os.getenv("WEBHOOK_STRIPE_TOLERANCE_SECONDS", "300")), 1
)


def _verify_stripe_signature(payload: bytes, signature: str, secret: str, timestamp: str | None = None) -> bool:
    """Verify Stripe webhook signature (Stripe-Signature header).

    Stripe signs HMAC_SHA256(secret, f"{t}.{raw_body}") where *t* is the
    Unix timestamp from the ``t=`` field in the Stripe-Signature header.
    Passing only the raw body to HMAC (as the previous implementation did)
    always produces the wrong digest and rejects every real Stripe event.

    The ``timestamp`` kwarg accepts the already-extracted ``t=`` value so
    the caller can pass it via ``PROVIDER_VERIFIERS``'s **kwargs.
    If not provided, the function extracts it from the ``signature`` string.
    """
    if not signature:
        return False

    # Parse t= and v1= fields from the Stripe-Signature header value.
    ts_value: str | None = timestamp
    v1_signatures: list[str] = []
    for part in signature.split(","):
        part = part.strip()
        if part.startswith("t=") and ts_value is None:
            ts_value = part[2:].strip()
        elif part.startswith("v1="):
            v1_signatures.append(part[3:])

    if not ts_value or not v1_signatures:
        return False

    # Replay-attack protection: reject if timestamp is too old.
    try:
        event_time = int(ts_value)
        if abs(time.time() - event_time) > _STRIPE_TOLERANCE_SECONDS:
            logger.warning(
                "Stripe webhook timestamp too old: age=%ds tolerance=%ds",
                abs(time.time() - event_time),
                _STRIPE_TOLERANCE_SECONDS,
            )
            return False
    except ValueError:
        return False

    # Compute expected signature over "{ts}.{raw_payload}".
    signed_payload = f"{ts_value}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

    return any(hmac.compare_digest(expected, v1) for v1 in v1_signatures)


def _verify_pagerduty_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify PagerDuty webhook signature (X-PD-Signature v1)."""
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


PROVIDER_VERIFIERS: dict[str, Any] = {
    "generic": lambda p, sig, secret, **kw: _verify_hmac_sha256(p, sig, secret),
    "github": lambda p, sig, secret, **kw: _verify_github_signature(p, sig, secret),
    "slack": lambda p, sig, secret, **kw: _verify_slack_signature(p, sig, secret, kw.get("timestamp")),
    "stripe": lambda p, sig, secret, **kw: _verify_stripe_signature(p, sig, secret, kw.get("timestamp")),
    "pagerduty": lambda p, sig, secret, **kw: _verify_pagerduty_signature(p, sig, secret),
    "grafana": lambda p, sig, secret, **kw: _verify_hmac_sha256(p, sig, secret),
}


def verify_provider_signature(
    provider: str,
    raw_body: bytes,
    signature: str,
    secret: str,
    **kwargs: Any,
) -> bool:
    """Verify a webhook signature using the appropriate provider verifier."""
    verifier = PROVIDER_VERIFIERS.get(provider)
    if verifier is None:
        logger.warning("Unknown webhook provider '%s'; falling back to generic HMAC", provider)
        return _verify_hmac_sha256(raw_body, signature, secret)
    return verifier(raw_body, signature, secret, **kwargs)


# ---------------------------------------------------------------------------
# API key authentication
# ---------------------------------------------------------------------------


def verify_webhook_api_key(api_key_header: str | None, stored_key: str | None) -> bool:
    """Verify an X-API-Key header against a stored key."""
    if not api_key_header or not stored_key:
        return False
    return hmac.compare_digest(api_key_header, stored_key)


# ---------------------------------------------------------------------------
# Key rotation — resolve secret with key-id support
# ---------------------------------------------------------------------------


def resolve_webhook_secret_with_key_id(
    secret_ref: str,
    additional_secrets: dict[str, str] | None,
    key_id: str | None,
) -> tuple[str | None, str | None]:
    """Resolve a webhook secret, supporting key rotation via key-id header.

    Returns (resolved_secret, resolved_key_id).
    If key_id is provided, look up that specific key in additional_secrets first,
    then fall back to the primary secret_ref.
    """
    if key_id and additional_secrets:
        ref = additional_secrets.get(key_id)
        if ref:
            secret = _resolve_k8s_secret(ref)
            if secret:
                return secret, key_id

    secret = _resolve_k8s_secret(secret_ref)
    return secret, None


def _resolve_k8s_secret(secret_ref: str) -> str | None:
    """Resolve a K8s Secret reference (namespace/name#key) or env var."""
    if not secret_ref or not secret_ref.strip():
        return None

    if "/" in secret_ref:
        parts = secret_ref.split("/", 1)
        ns = parts[0].strip()
        rest = parts[1]
        if "#" in rest:
            name_part, key = rest.split("#", 1)
            name = name_part.strip()
            key = key.strip()
            try:
                import base64
                import kubernetes.client
                v1 = kubernetes.client.CoreV1Api()
                secret = v1.read_namespaced_secret(name=name, namespace=ns)
                if secret.data and key in secret.data:
                    return base64.b64decode(secret.data[key]).decode("utf-8")
                logger.warning(
                    "K8s secret '%s/%s' does not contain key '%s'", ns, name, key
                )
            except ImportError:
                logger.warning("kubernetes package not installed; cannot resolve K8s secret ref")
            except Exception as exc:  # noqa: BLE001 — K8s API errors vary widely
                logger.warning("Failed to read K8s secret '%s/%s' key '%s': %s", ns, name, key, exc)

    env_var_name = secret_ref.replace("-", "_").replace(" ", "_").upper()
    return os.environ.get(env_var_name)


# ---------------------------------------------------------------------------
# Payload sanitization
# ---------------------------------------------------------------------------


def sanitize_webhook_payload(payload: dict, _depth: int = 0) -> dict:
    """Remove potentially dangerous keys from webhook payloads."""
    if not isinstance(payload, dict):
        return payload
    if _depth > 10:
        return {}
    safe = {}
    for key, value in payload.items():
        if key.startswith("__") or key in ("$where", "$regex"):
            continue
        if isinstance(value, dict):
            safe[key] = sanitize_webhook_payload(value, _depth + 1)
        else:
            safe[key] = value
    return safe


# ---------------------------------------------------------------------------
# Payload schema validation
# ---------------------------------------------------------------------------


def validate_payload_against_schema(payload: dict[str, Any], schema: dict[str, Any] | None) -> list[str]:
    """Validate a payload against a JSON Schema. Returns list of error messages."""
    if not schema:
        return []

    errors: list[str] = []
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # Check required fields
    for field in required:
        if field not in payload:
            errors.append(f"Missing required field: '{field}'")

    # Check type constraints
    for field, field_schema in properties.items():
        if field not in payload:
            continue
        value = payload[field]
        expected_type = field_schema.get("type", "")

        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"Field '{field}' must be a string")
        elif expected_type == "integer" and not isinstance(value, int):
            errors.append(f"Field '{field}' must be an integer")
        elif expected_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"Field '{field}' must be a number")
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(f"Field '{field}' must be a boolean")
        elif expected_type == "array" and not isinstance(value, list):
            errors.append(f"Field '{field}' must be an array")
        elif expected_type == "object" and not isinstance(value, dict):
            errors.append(f"Field '{field}' must be an object")

        # Check pattern
        pattern = field_schema.get("pattern", "")
        if pattern and isinstance(value, str):
            import re
            if not re.match(pattern, value):
                errors.append(f"Field '{field}' does not match pattern '{pattern}'")

        # Check min/max for numbers
        if isinstance(value, (int, float)):
            if "minimum" in field_schema and value < field_schema["minimum"]:
                errors.append(f"Field '{field}' must be >= {field_schema['minimum']}")
            if "maximum" in field_schema and value > field_schema["maximum"]:
                errors.append(f"Field '{field}' must be <= {field_schema['maximum']}")

    return errors


# ---------------------------------------------------------------------------
# Body reading
# ---------------------------------------------------------------------------


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    """Read request body, raising 413 if it exceeds max_bytes."""
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > max_bytes:
            raise HTTPException(status_code=413, detail="Payload exceeds maximum size")
    return body


# ---------------------------------------------------------------------------
# IP resolution
# ---------------------------------------------------------------------------


def resolve_trusted_client_ip(request: Request) -> str:
    """Extract client IP, only trusting X-Forwarded-For behind a known proxy."""
    trusted_proxy = os.getenv("WEBHOOK_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded and trusted_proxy:
        ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
        if ips:
            return ips[-1]
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"
