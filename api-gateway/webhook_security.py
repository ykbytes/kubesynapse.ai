"""Webhook security helpers.

Security Best Practices
-----------------------
- Webhook secrets should be rotated every 90 days.
- Use unique secrets per webhook receiver (never reuse across endpoints).
- Prefer Kubernetes Secrets (secret_ref) over plaintext env vars.
- IP allowlisting is defense-in-depth, not primary security; always verify HMAC.
- Monitor the webhook invocation audit log for anomalies (spikes, signature failures).
- In production, replace the in-memory rate limiter with Redis (e.g., using redis-py).
"""
from __future__ import annotations

import os
import time
import hmac
import hashlib
import threading
from typing import Optional
from fastapi import HTTPException, Request

# In-memory rate limiting state. In production, replace with Redis.
_webhook_rate_state: dict[str, list[float]] = {}
_webhook_rate_lock = threading.Lock()


def check_webhook_rate_limit(webhook_key: str, limit: int, window_seconds: int = 60) -> None:
    """Simple in-memory rate limiter. Replace with Redis for production."""
    now = time.monotonic()
    with _webhook_rate_lock:
        timestamps = _webhook_rate_state.get(webhook_key, [])
        timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(timestamps) >= limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        timestamps.append(now)
        _webhook_rate_state[webhook_key] = timestamps
        if len(_webhook_rate_state) > 10000:
            _webhook_rate_state.clear()  # prevent memory leak


def verify_webhook_timestamp(timestamp_header: Optional[str], max_age_seconds: int = 300) -> None:
    """Prevent replay attacks by checking timestamp freshness."""
    if not timestamp_header:
        raise HTTPException(status_code=401, detail="Missing X-KubeSynth-Timestamp header")
    try:
        request_time = int(timestamp_header)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid X-KubeSynth-Timestamp header")
    if abs(time.time() - request_time) > max_age_seconds:
        raise HTTPException(status_code=401, detail="Webhook timestamp is too old")


def sanitize_webhook_payload(payload: dict, _depth: int = 0) -> dict:
    """Remove potentially dangerous keys from webhook payloads."""
    if not isinstance(payload, dict):
        return payload
    if _depth > 10:
        # Prevent stack exhaustion from deeply nested payloads
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


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    """Read request body, raising 413 if it exceeds max_bytes."""
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > max_bytes:
            raise HTTPException(status_code=413, detail="Payload exceeds maximum size")
    return body


def resolve_trusted_client_ip(request: Request) -> str:
    """Extract client IP, only trusting X-Forwarded-For behind a known proxy."""
    trusted_proxy = os.getenv("WEBHOOK_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded and trusted_proxy:
        # Use the rightmost IP to prevent spoofing via client-injected leftmost IPs.
        ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
        if ips:
            return ips[-1]
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"
