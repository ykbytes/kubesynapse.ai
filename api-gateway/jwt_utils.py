"""JWT helpers for local browser sessions."""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

_logger = logging.getLogger("api-gateway.jwt")

ACCESS_TOKEN_TTL_SECONDS = max(int(os.getenv("AUTH_ACCESS_TOKEN_TTL_SECONDS", "900")), 60)
REFRESH_TOKEN_TTL_SECONDS = max(int(os.getenv("AUTH_REFRESH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600))), 300)
JWT_ISSUER = os.getenv("JWT_ISSUER", "kubesynth").strip() or "kubesynth"
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "").strip()  # P2-10: optionally enforce 'aud' claim


class JwtKey:
    """Represents a single JWT signing key with metadata for rotation."""

    def __init__(self, kid: str, secret: str, created_at: float | None = None) -> None:
        self.kid = kid
        self.secret = secret
        self.created_at = created_at or datetime.now(UTC).timestamp()


def _load_keys() -> dict[str, JwtKey]:
    """Load active signing keys from environment supporting rotation."""
    keys: dict[str, JwtKey] = {}

    # Primary secret
    primary = os.getenv("JWT_SECRET", "").strip() or os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
    if primary:
        keys["primary"] = JwtKey("primary", primary)

    # Previous secret for rotation grace period
    previous = os.getenv("JWT_SECRET_PREVIOUS", "").strip()
    if previous:
        keys["previous"] = JwtKey("previous", previous)

    # JSON list of keys for advanced rotation scenarios
    keys_json = os.getenv("JWT_SECRET_LIST", "").strip()
    if keys_json:
        try:
            parsed = json.loads(keys_json)
            for item in parsed:
                if isinstance(item, dict) and item.get("secret"):
                    kid = str(item.get("kid", "key"))
                    keys[kid] = JwtKey(
                        kid,
                        str(item["secret"]),
                        item.get("created_at"),
                    )
        except json.JSONDecodeError:
            _logger.warning("JWT_SECRET_LIST is not valid JSON, ignoring")

    if not keys:
        # Generate ephemeral key — sessions will not survive restart
        ephemeral = secrets.token_urlsafe(32)
        keys["primary"] = JwtKey("primary", ephemeral)
        _logger.critical(
            "SECURITY: JWT_SECRET is not configured — using a random ephemeral secret. "
            "Tokens will NOT survive restarts and all sessions will be lost. "
            "Set JWT_SECRET or API_GATEWAY_SHARED_TOKEN before deploying to production."
        )
        if os.getenv("REQUIRE_JWT_SECRET", "").strip().lower() in {"1", "true", "yes"}:
            raise SystemExit("FATAL: JWT_SECRET or API_GATEWAY_SHARED_TOKEN must be set when REQUIRE_JWT_SECRET is enabled.")

    return keys


def _get_signing_key() -> JwtKey:
    """Return the current signing key (prefer 'primary', else newest)."""
    if "primary" in _JWT_KEYS:
        return _JWT_KEYS["primary"]
    return max(_JWT_KEYS.values(), key=lambda k: k.created_at)


def _get_key_by_kid(kid: str | None) -> JwtKey | None:
    """Find a verification key by kid, with sensible fallbacks."""
    if kid and kid in _JWT_KEYS:
        return _JWT_KEYS[kid]
    # If no kid in token, try primary then previous for backward compatibility
    for fallback in ("primary", "previous"):
        if fallback in _JWT_KEYS:
            return _JWT_KEYS[fallback]
    # Last resort: any available key
    return next(iter(_JWT_KEYS.values())) if _JWT_KEYS else None


# Initialize keys and backward-compatible exports after helper functions are defined
_JWT_KEYS: dict[str, JwtKey] = _load_keys()
REFRESH_COOKIE_NAME = os.getenv("AUTH_REFRESH_COOKIE_NAME", "ai-agent-refresh").strip() or "ai-agent-refresh"
JWT_SECRET = _JWT_KEYS.get("primary", _get_signing_key()).secret
JWT_ROTATION_DAYS = max(int(os.getenv("JWT_ROTATION_DAYS", "0")), 0)


def utc_now() -> datetime:
    return datetime.now(UTC)


def jwt_secret_configured() -> bool:
    return bool(os.getenv("JWT_SECRET", "").strip() or os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip())


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
    key = _get_signing_key()
    token = jwt.encode(claims, key.secret, algorithm="HS256", headers={"kid": key.kid})
    return token, expires_at.isoformat(), ACCESS_TOKEN_TTL_SECONDS


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a local access token, supporting key rotation via kid."""
    try:
        unverified = jwt.get_unverified_header(token)
    except JWTError:
        unverified = {}

    kid = unverified.get("kid")
    key = _get_key_by_kid(kid)

    if key is None:
        raise ValueError("No valid JWT key found for token verification.")

    # Explicitly reject the 'none' algorithm to prevent algorithm confusion attacks
    if unverified.get("alg") == "none":
        raise ValueError("JWT algorithm 'none' is not permitted.")

    # Try the matched key first; if verification fails and we used a fallback,
    # iterate over all keys to support rotation edge cases.
    keys_to_try = [key]
    if kid is None:
        keys_to_try = list({k.kid: k for k in _JWT_KEYS.values()}.values())

    last_error: Exception | None = None
    verify_options: dict[str, bool] = {"verify_aud": bool(JWT_AUDIENCE)}
    audience = JWT_AUDIENCE if JWT_AUDIENCE else None
    for attempt_key in keys_to_try:
        try:
            claims = jwt.decode(
                token,
                attempt_key.secret,
                algorithms=["HS256"],
                issuer=JWT_ISSUER,
                audience=audience,
                options=verify_options,
            )
        except JWTError as exc:
            last_error = exc
            continue
        if claims.get("token_type") != "access":
            raise ValueError("Token is not an access token.")
        return claims

    raise ValueError(str(last_error)) from last_error


def rotate_jwt_key() -> JwtKey:
    """Generate a new primary signing key and demote the current one to previous.

    Returns the new key.  Callers should persist the new secret via
    JWT_SECRET / JWT_SECRET_PREVIOUS environment variables for durability.
    """
    global _JWT_KEYS
    new_secret = secrets.token_urlsafe(32)

    # Demote current primary to previous so in-flight tokens stay valid
    if "primary" in _JWT_KEYS:
        old_primary = _JWT_KEYS["primary"]
        _JWT_KEYS["previous"] = JwtKey("previous", old_primary.secret, old_primary.created_at)

    new_key = JwtKey("primary", new_secret)
    _JWT_KEYS["primary"] = new_key
    _logger.info("JWT signing key rotated. New kid='primary' created.")
    return new_key


def list_jwt_key_kids() -> list[str]:
    """Return the kids of all currently loaded keys (useful for debugging)."""
    return list(_JWT_KEYS.keys())
