"""JWT helpers for local browser sessions."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

_logger = logging.getLogger("api-gateway.jwt")

ACCESS_TOKEN_TTL_SECONDS = max(int(os.getenv("AUTH_ACCESS_TOKEN_TTL_SECONDS", "900")), 60)
REFRESH_TOKEN_TTL_SECONDS = max(int(os.getenv("AUTH_REFRESH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600))), 300)
JWT_ISSUER = os.getenv("JWT_ISSUER", "ai-agent-sandbox").strip() or "ai-agent-sandbox"
_JWT_SECRET_EXPLICIT = os.getenv("JWT_SECRET", "").strip() or os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
JWT_SECRET = _JWT_SECRET_EXPLICIT or "dev-insecure-jwt-secret"
if not _JWT_SECRET_EXPLICIT:
    _logger.warning(
        "JWT_SECRET is not configured — using an insecure default. "
        "Set JWT_SECRET or API_GATEWAY_SHARED_TOKEN before deploying to production."
    )
REFRESH_COOKIE_NAME = os.getenv("AUTH_REFRESH_COOKIE_NAME", "ai-agent-refresh").strip() or "ai-agent-refresh"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def jwt_secret_configured() -> bool:
    return bool(_JWT_SECRET_EXPLICIT)


def access_token_expiry() -> datetime:
    return utc_now() + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS)


def create_access_token(user: dict[str, Any], session_id: str) -> tuple[str, str, int]:
    expires_at = access_token_expiry()
    claims = {
        "sub": str(user["id"]),
        "username": user["username"],
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "role": user.get("role", "viewer"),
        "allowed_namespaces": user.get("allowed_namespaces", []),
        "auth_provider": user.get("auth_provider", "local"),
        "session_id": session_id,
        "token_type": "access",
        "iss": JWT_ISSUER,
        "iat": int(utc_now().timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, JWT_SECRET, algorithm="HS256")
    return token, expires_at.isoformat(), ACCESS_TOKEN_TTL_SECONDS


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            issuer=JWT_ISSUER,
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise ValueError(str(exc)) from exc
    if claims.get("token_type") != "access":
        raise ValueError("Token is not an access token.")
    return claims
