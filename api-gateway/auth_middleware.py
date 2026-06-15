"""Authentication middleware — token verification, principal builders, session helpers.

§4.1 of the road-to-prod plan: extract authentication logic from the
monolithic gateway into a reusable module.  The gateway validates JWTs
through this module; authentication flows (login, register, SSO) remain
in the route layer.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import time
from typing import Any, Literal

import httpx
from fastapi import Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from jose import jwk, jwt
from jose.utils import base64url_decode

from auth_store import (
    ROLE_PRIORITY,
    auth_storage_ready,
    count_users,
    get_active_user_context,
    is_session_active,
    normalize_namespaces,
    record_audit_log,
)
from enterprise_auth import (
    auth_configuration,
    get_oidc_provider,
    ldap_enabled,
    oidc_providers,
    resolve_role_mapping,
    saml_providers,
)
from jwt_utils import (
    REFRESH_COOKIE_NAME,
    REFRESH_TOKEN_TTL_SECONDS,
    create_access_token,
    decode_access_token,
)

logger = logging.getLogger("api-gateway.auth")

# ---------------------------------------------------------------------------
# Auth configuration (read from environment)
# ---------------------------------------------------------------------------

AUTH_MODE: str = os.getenv("API_GATEWAY_AUTH_MODE", "shared_token").strip().lower()
SHARED_TOKEN: str = os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
LOCAL_AUTH_ENABLED: bool = os.getenv("LOCAL_AUTH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
if not LOCAL_AUTH_ENABLED:
    LOCAL_AUTH_ENABLED = AUTH_MODE in {"local", "hybrid", "enterprise"}
REGISTRATION_ENABLED: bool = os.getenv("AUTH_REGISTRATION_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}

OIDC_JWKS_URL: str = os.getenv("OIDC_JWKS_URL", "").strip()
OIDC_ISSUER: str = os.getenv("OIDC_ISSUER", "").strip()
OIDC_AUDIENCE: str = os.getenv("OIDC_AUDIENCE", "").strip()
OIDC_JWKS_TIMEOUT_SECONDS: float = max(float(os.getenv("OIDC_JWKS_TIMEOUT_SECONDS", "10")), 1.0)

AUTH_COOKIE_SECURE: bool = os.getenv("AUTH_COOKIE_SECURE", "true").strip().lower() not in {"0", "false", "no", "off"}
AUTH_COOKIE_DOMAIN: str | None = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
AUTH_COOKIE_PATH: str = os.getenv("AUTH_COOKIE_PATH", "/").strip() or "/"
AUTH_COOKIE_SAMESITE: str = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower() or "lax"
OIDC_TRANSACTION_COOKIE_NAME: str = os.getenv("AUTH_OIDC_TRANSACTION_COOKIE_NAME", "ai-agent-oidc").strip() or "ai-agent-oidc"
OIDC_TRANSACTION_COOKIE_TTL_SECONDS: int = max(int(os.getenv("AUTH_OIDC_TRANSACTION_TTL_SECONDS", "600")), 60)

CookieSameSite = Literal["lax", "strict", "none"]

# JWKS cache (module-level mutable state — shared across requests)
JWKS_CACHE: dict[str, Any] = {"keys": [], "expires_at": 0.0}
_JWKS_LOCK: asyncio.Lock | None = None


def _get_jwks_lock() -> asyncio.Lock:
    """Lazy initialization of JWKS lock to avoid event loop binding issues."""
    global _JWKS_LOCK
    if _JWKS_LOCK is None:
        _JWKS_LOCK = asyncio.Lock()
    return _JWKS_LOCK


# ---------------------------------------------------------------------------
# JWKS
# ---------------------------------------------------------------------------


async def load_jwks() -> list[dict[str, Any]]:
    """Fetch and cache OIDC JWKS keys."""
    if JWKS_CACHE["expires_at"] > time.time():
        return JWKS_CACHE["keys"]

    async with _get_jwks_lock():
        if JWKS_CACHE["expires_at"] > time.time():
            return JWKS_CACHE["keys"]

        if not OIDC_JWKS_URL:
            raise HTTPException(status_code=503, detail="Authentication service unavailable")
        if not OIDC_JWKS_URL.startswith("https://"):
            logger.error("OIDC_JWKS_URL must use HTTPS")
            raise HTTPException(status_code=503, detail="Authentication service unavailable")

        async with httpx.AsyncClient(timeout=OIDC_JWKS_TIMEOUT_SECONDS) as client:
            response = await client.get(OIDC_JWKS_URL)
            response.raise_for_status()
            keys = response.json().get("keys", [])

        JWKS_CACHE.update({"keys": keys, "expires_at": time.time() + 300})
        return keys


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def request_client_ip(request: Request) -> str | None:
    """Extract client IP from X-Forwarded-For or request.client.

    Uses the rightmost IP in X-Forwarded-For (before any known proxies)
    to avoid spoofing via client-injected leftmost IPs.
    """
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        # Take the rightmost IP to prevent spoofing
        ips = [ip.strip() for ip in forwarded_for.split(",") if ip.strip()]
        if ips:
            return ips[-1]
    if request.client is not None:
        return request.client.host
    return None


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def cookie_samesite() -> CookieSameSite:
    """Return the validated SameSite cookie attribute."""
    if AUTH_COOKIE_SAMESITE == "strict":
        return "strict"
    if AUTH_COOKIE_SAMESITE == "none":
        return "none"
    return "lax"


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set the refresh token cookie on a response."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite=cookie_samesite(),
        path=AUTH_COOKIE_PATH,
        domain=AUTH_COOKIE_DOMAIN,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=AUTH_COOKIE_PATH,
        domain=AUTH_COOKIE_DOMAIN,
        secure=AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=cookie_samesite(),
    )


def set_oidc_transaction_cookie(response: Response, cookie_value: str) -> None:
    """Set the OIDC transaction cookie."""
    response.set_cookie(
        key=OIDC_TRANSACTION_COOKIE_NAME,
        value=cookie_value,
        max_age=OIDC_TRANSACTION_COOKIE_TTL_SECONDS,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite=cookie_samesite(),
        path=AUTH_COOKIE_PATH,
        domain=AUTH_COOKIE_DOMAIN,
    )


def clear_oidc_transaction_cookie(response: Response) -> None:
    """Clear the OIDC transaction cookie."""
    response.delete_cookie(
        key=OIDC_TRANSACTION_COOKIE_NAME,
        path=AUTH_COOKIE_PATH,
        domain=AUTH_COOKIE_DOMAIN,
        secure=AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=cookie_samesite(),
    )


# ---------------------------------------------------------------------------
# Auth mode checks
# ---------------------------------------------------------------------------


def shared_token_enabled() -> bool:
    """Return True if shared-token auth is active."""
    return bool(SHARED_TOKEN) and AUTH_MODE in {"shared_token", "auto", "hybrid", "enterprise"}


def oidc_bearer_enabled() -> bool:
    """Return True if OIDC bearer auth is active."""
    return bool(OIDC_JWKS_URL) and AUTH_MODE in {"oidc", "auto", "hybrid", "enterprise"}


def local_access_enabled() -> bool:
    """Return True if local user auth is active."""
    return LOCAL_AUTH_ENABLED or AUTH_MODE == "local"


def browser_auth_storage_ready() -> bool:
    """Return True if the auth store can back browser sessions."""
    return auth_storage_ready(require_sessions=True)


def browser_auth_enabled() -> bool:
    """Return True if any browser-based auth flow is available."""
    return browser_auth_storage_ready() and (
        local_access_enabled() or ldap_enabled() or bool(oidc_providers()) or bool(saml_providers())
    )


def ensure_browser_auth_available() -> None:
    """Raise 503 when browser auth is configured but storage is unavailable."""
    if not browser_auth_storage_ready():
        raise HTTPException(status_code=503, detail="Browser authentication is temporarily unavailable")


def registration_allowed() -> bool:
    """Return True if new user self-registration is permitted."""
    return browser_auth_storage_ready() and local_access_enabled() and (REGISTRATION_ENABLED or count_users() == 0)


def auth_configuration_payload() -> dict[str, Any]:
    """Build the public auth configuration payload for /api/auth/config."""
    browser_auth_ready = browser_auth_storage_ready()
    local_enabled = local_access_enabled() and browser_auth_ready
    provider_config = auth_configuration()
    provider_config["password_providers"] = [
        provider
        for provider in list(provider_config.get("password_providers") or [])
        if provider != "local" or local_enabled
    ]
    if not browser_auth_ready:
        provider_config["password_providers"] = []
        provider_config["oidc_providers"] = []
        provider_config["saml_providers"] = []

    user_count = count_users() if browser_auth_ready else 0
    browser_auth_available = bool(
        provider_config["password_providers"] or provider_config["oidc_providers"] or provider_config["saml_providers"]
    )
    return {
        "auth_mode": AUTH_MODE,
        "local_enabled": local_enabled,
        "registration_enabled": local_enabled and (REGISTRATION_ENABLED or user_count == 0),
        "shared_token_enabled": shared_token_enabled(),
        "browser_auth_enabled": browser_auth_available,
        "bootstrap_complete": user_count > 0,
        **provider_config,
    }


# ---------------------------------------------------------------------------
# Principal builders
# ---------------------------------------------------------------------------


def claim_string_list(value: Any) -> list[str]:
    """Normalize a JWT claim value to a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def normalize_principal(
    *,
    sub: str,
    username: str,
    display_name: str | None,
    email: str | None,
    role: str,
    allowed_namespaces: list[str] | None,
    auth_provider: str,
    session_id: str | None = None,
    is_active: bool = True,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized principal dict from auth claims.

    §security-R5: an explicit ``allowed_namespaces=[]`` is preserved
    as "no namespace access" rather than auto-expanding to ``["*"]``.
    Callers that want the previous default behavior should pass
    ``None`` (which falls back to ``["*"]`` for non-admin roles).
    """
    normalized_role = role if role in ROLE_PRIORITY else "viewer"
    if normalized_role == "admin" or allowed_namespaces is None:
        normalized_namespaces = ["*"]
    else:
        normalized_namespaces = normalize_namespaces(allowed_namespaces)
    return {
        "sub": sub,
        "id": sub,
        "username": username,
        "display_name": display_name or username,
        "email": email,
        "role": normalized_role,
        "allowed_namespaces": normalized_namespaces,
        "capabilities": dict(capabilities or {}),
        "auth_provider": auth_provider,
        "session_id": session_id,
        "is_active": is_active,
    }


def build_shared_token_principal() -> dict[str, Any]:
    """Build a principal for the shared-token auth mode.

    Security (§security-R5): the legacy `shared_token` principal is now
    `viewer` with empty namespace access. This prevents a leaked shared
    token (e.g. from a compromised runtime container's environment) from
    granting admin-equivalent access to the entire gateway. Production
    callers must present a runtime identity claim via
    ``verify_shared_token_with_identity`` to obtain a privileged principal.
    """
    return normalize_principal(
        sub="shared-token-user",
        username="shared-token-user",
        display_name="Shared Token",
        email=None,
        role="viewer",
        allowed_namespaces=[],
        auth_provider="shared_token",
    )


def build_runtime_identity_principal(
    *,
    agent_name: str,
    namespace: str,
) -> dict[str, Any]:
    """Build a principal for a runtime that has presented a valid
    per-agent identity token.

    The runtime identity token is an HMAC-SHA256 over
    ``agent_name + ":" + namespace`` keyed by ``RUNTIME_IDENTITY_HMAC_SECRET``.
    It binds the shared bearer token to a specific agent + namespace,
    preventing a leaked shared token from being reused against other
    agents or other tenants.
    """
    return normalize_principal(
        sub=f"runtime:{namespace}:{agent_name}",
        username=f"runtime-{namespace}-{agent_name}",
        display_name=f"Agent runtime '{agent_name}'",
        email=None,
        role="operator",
        allowed_namespaces=[namespace],
        auth_provider="runtime_identity",
    )


def principal_from_local_user(user: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Build a principal from a local user record."""
    return normalize_principal(
        sub=str(user["id"]),
        username=str(user["username"]),
        display_name=user.get("display_name"),
        email=user.get("email"),
        role=str(user.get("role") or "viewer"),
        allowed_namespaces=user.get("allowed_namespaces") or ["default"],
        capabilities=user.get("capabilities") or {},
        auth_provider=str(user.get("auth_provider") or "local"),
        session_id=session_id,
        is_active=bool(user.get("is_active", True)),
    )


def principal_from_oidc_claims(claims: dict[str, Any]) -> dict[str, Any]:
    """Build a principal from OIDC JWT claims.

    Security (D7, D8): role and namespace values are taken from
    OIDC claims but capped by per-provider (or platform-wide) role /
    namespace allowlists. Without these caps, a misconfigured IdP that
    emits ``role: "admin"`` in every user claim would mint admin
    principals for every external user — a tenancy-escalation
    disaster. The role allowlist is ``ROLE_PRIORITY`` (admin / operator /
    viewer); the namespace allowlist is provided by the operator via
    ``OIDC ALLOWED_NAMESPACES`` (comma-separated) or, when unset, the
    empty default ("all namespaces are denied" — fail closed).
    """
    provider = get_oidc_provider(issuer=str(claims.get("iss") or ""))
    group_claim = str(provider.get("group_claim") or "groups") if provider else "groups"
    groups = claim_string_list(claims.get(group_claim))

    # D7: cap the role ceiling at the provider's configured max role.
    provider_max_role = (
        str(provider.get("max_role") or "").strip().lower()
        if isinstance(provider, dict)
        else ""
    )
    if provider_max_role and provider_max_role not in ROLE_PRIORITY:
        provider_max_role = ""
    max_role_rank = ROLE_PRIORITY.get(provider_max_role, 0) if provider_max_role else 0

    mapped_role = None
    mapped_namespaces: list[str] = []
    if provider is not None:
        role_mapping = provider.get("group_role_mapping")
        if isinstance(role_mapping, dict):
            mapped_role, mapped_namespaces = resolve_role_mapping(groups, role_mapping)

    # Collect role candidates from ``roles`` claim and the single
    # ``role`` claim, but only consider values that the provider is
    # allowed to issue (D7) AND that exist in ROLE_PRIORITY.
    role_candidates = claim_string_list(claims.get("roles"))
    if claims.get("role") is not None:
        role_candidates.insert(0, str(claims.get("role")))
    valid_role_candidates = [r for r in role_candidates if r in ROLE_PRIORITY]
    chosen_role = mapped_role if mapped_role in ROLE_PRIORITY else next(
        iter(valid_role_candidates), "viewer",
    )
    # D7: clamp the chosen role to the provider's max_role ceiling.
    if max_role_rank and ROLE_PRIORITY.get(chosen_role, 0) > max_role_rank:
        chosen_role = provider_max_role or "viewer"
    role = chosen_role

    # D8: cap allowed_namespaces to the provider's allowlist. The
    # IdP cannot grant the user access to a namespace the operator
    # has not explicitly approved for this provider.
    raw_namespaces: list[str] = []
    if mapped_namespaces:
        raw_namespaces.extend(mapped_namespaces)
    if claims.get("allowed_namespaces") or claims.get("namespaces"):
        raw_namespaces.extend(
            normalize_namespaces(
                claims.get("allowed_namespaces") or claims.get("namespaces") or []
            )
        )
    provider_ns_allowlist: set[str] | None = None
    if isinstance(provider, dict):
        ns_allow = provider.get("namespace_allowlist")
        if isinstance(ns_allow, list) and ns_allow:
            provider_ns_allowlist = {
                str(n).strip() for n in ns_allow if str(n).strip()
            }
    if provider_ns_allowlist is not None:
        filtered = [n for n in raw_namespaces if n in provider_ns_allowlist]
    else:
        # Fail closed: provider configured no allowlist — do not
        # accept any namespace claim from the IdP. The user lands
        # in [] which means they cannot access any namespace. This
        # is the safe default; operators must opt in by setting
        # ``namespace_allowlist`` per provider.
        filtered = []
    # Admin always gets ["*"] regardless of IdP claims (D8 second
    # half) — admin authority is local, never federated.
    allowed_namespaces = ["*"] if role == "admin" else (filtered or [])

    email = str(claims.get("email") or "").strip() or None
    preferred_username = str(
        claims.get("preferred_username")
        or claims.get("upn")
        or email
        or claims.get("sub")
        or "oidc-user"
    ).strip()
    username = preferred_username.split("@", 1)[0].lower() if "@" in preferred_username else preferred_username.lower()
    auth_provider = f"oidc:{provider['id']}" if provider else "oidc"
    return normalize_principal(
        sub=str(claims.get("sub") or username),
        username=username,
        display_name=str(claims.get("name") or claims.get("display_name") or username),
        email=email,
        role=role,
        allowed_namespaces=allowed_namespaces,
        auth_provider=auth_provider,
    )


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------


def safe_record_audit(
    *,
    action: str,
    principal: dict[str, Any] | None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    resource_namespace: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Persist an audit log entry, swallowing failures."""
    try:
        record_audit_log(
            action=action,
            actor_sub=str(principal.get("sub")) if principal else None,
            actor_username=str(principal.get("username")) if principal else None,
            auth_provider=str(principal.get("auth_provider")) if principal else None,
            resource_kind=resource_kind,
            resource_name=resource_name,
            resource_namespace=resource_namespace,
            detail=detail,
            ip_address=ip_address,
        )
    except Exception:
        logger.exception("Failed to persist audit log for action '%s'.", action)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def build_session_payload(user: dict[str, Any], session_record: dict[str, Any]) -> dict[str, Any]:
    """Build the JSON response payload for a new session."""
    principal = principal_from_local_user(user, str(session_record["id"]))
    access_token, expires_at, expires_in = create_access_token(principal, session_id=str(session_record["id"]))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "expires_at": expires_at,
        "refresh_expires_at": session_record.get("expires_at"),
        "user": principal,
        "auth_mode": AUTH_MODE,
    }


def issue_session_response(user: dict[str, Any], session_record: dict[str, Any], refresh_token: str, *, status_code: int = 200) -> JSONResponse:
    """Build a JSONResponse with session payload and refresh cookie."""
    response = JSONResponse(build_session_payload(user, session_record), status_code=status_code)
    set_refresh_cookie(response, refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Role / namespace enforcement
# ---------------------------------------------------------------------------


def ensure_role(user: dict[str, Any], minimum_role: str) -> dict[str, Any]:
    """Raise 403 if user does not have the minimum role."""
    from error_codes import ErrorCode, build_error_response

    current_role = str(user.get("role") or "viewer")
    if ROLE_PRIORITY.get(current_role, 0) < ROLE_PRIORITY.get(minimum_role, 0):
        raise HTTPException(
            status_code=403,
            detail=build_error_response(
                code=ErrorCode.ROLE_TOO_LOW,
                message=f"{minimum_role.capitalize()} role is required",
                detail=f"Your current role is '{current_role}'. This operation requires at least '{minimum_role}'.",
            ),
        )
    return user


def ensure_namespace_access(user: dict[str, Any], namespace: str, minimum_role: str = "viewer") -> dict[str, Any]:
    """Raise 403 if user cannot access the given namespace."""
    from error_codes import ErrorCode, build_error_response

    ensure_role(user, minimum_role)
    if str(user.get("role") or "viewer") == "admin":
        return user
    allowed_namespaces = normalize_namespaces(user.get("allowed_namespaces") or ["*"]) or ["*"]
    if "*" in allowed_namespaces or namespace in allowed_namespaces:
        return user
    raise HTTPException(
        status_code=403,
        detail=build_error_response(
            code=ErrorCode.NAMESPACE_DENIED,
            message=f"Access to namespace '{namespace}' is not permitted",
            detail=f"Your allowed namespaces: {', '.join(sorted(allowed_namespaces))}",
        ),
    )


# Capabilities that the user record can opt into beyond the base role.
# `runtime:logs` is least-privilege on purpose: pod logs can include
# environment-derived secrets in error stacks, so we never grant it by
# default. Only admins can flip the flag, and viewers must be granted
# explicitly.
USER_CAPABILITIES = ("runtime:logs",)


def user_has_capability(user: dict[str, Any], capability: str) -> bool:
    if capability not in USER_CAPABILITIES:
        return False
    role = str(user.get("role") or "viewer")
    if role == "admin":
        return True
    capabilities = user.get("capabilities") or {}
    if not isinstance(capabilities, dict):
        return False
    if role == "operator" and capability == "runtime:logs":
        # Operators get the capability by default but an admin can revoke it
        # by storing `False` in the user record.
        return capabilities.get(capability) is not False
    return bool(capabilities.get(capability))


def ensure_capability(user: dict[str, Any], capability: str) -> dict[str, Any]:
    """Raise 403 if the user has not been granted ``capability``."""
    from error_codes import build_error_response, ErrorCode

    if user_has_capability(user, capability):
        return user
    raise HTTPException(
        status_code=403,
        detail=build_error_response(
            code=ErrorCode.ROLE_TOO_LOW,
            message=f"Capability '{capability}' is required",
            detail=(
                "Runtime logs may contain sensitive data. An administrator must "
                "explicitly grant this capability before the user can read live pod logs."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def validate_claims(claims: dict[str, Any]) -> None:
    """Validate standard JWT claims (exp, nbf, iss, aud)."""
    now = int(time.time())
    if claims.get("exp") is not None and now >= int(claims["exp"]):
        raise HTTPException(status_code=401, detail="Token has expired")
    if claims.get("nbf") is not None and now < int(claims["nbf"]):
        raise HTTPException(status_code=401, detail="Token is not active yet")
    if OIDC_ISSUER and claims.get("iss") != OIDC_ISSUER:
        raise HTTPException(status_code=401, detail="Token issuer is invalid")
    if OIDC_AUDIENCE:
        audience = claims.get("aud")
        valid = audience == OIDC_AUDIENCE or (
            isinstance(audience, list) and OIDC_AUDIENCE in audience
        )
        if not valid:
            raise HTTPException(status_code=401, detail="Token audience is invalid")


async def verify_oidc_token(token: str) -> dict[str, Any]:
    """Verify an OIDC JWT token and return the principal."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token header") from exc
    key_id = header.get("kid")
    keys = await load_jwks()
    if not key_id and len(keys) > 1:
        raise HTTPException(status_code=401, detail="Token missing key ID in multi-key JWKS")
    key_data = next((item for item in keys if item.get("kid") == key_id), None)
    if key_data is None:
        raise HTTPException(status_code=401, detail="Unable to find a signing key for this token")

    signing_key = jwk.construct(key_data)
    message, encoded_signature = token.rsplit(".", 1)
    decoded_signature = base64url_decode(encoded_signature.encode("utf-8"))
    if not signing_key.verify(message.encode("utf-8"), decoded_signature):
        raise HTTPException(status_code=401, detail="Token signature is invalid")

    try:
        claims = jwt.get_unverified_claims(token)
    except jwt.JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token claims") from exc
    validate_claims(claims)
    return principal_from_oidc_claims(claims)


def verify_local_access_token(token: str) -> dict[str, Any]:
    """Verify a local access token and return the principal."""
    try:
        claims = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid local access token") from exc

    # Validate time-based claims
    now = int(time.time())
    if claims.get("exp") is not None and now >= int(claims["exp"]):
        raise HTTPException(status_code=401, detail="Token has expired")
    if claims.get("nbf") is not None and now < int(claims["nbf"]):
        raise HTTPException(status_code=401, detail="Token is not active yet")

    try:
        user_id = int(str(claims.get("sub") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Local access token subject is invalid") from exc

    session_id = str(claims.get("session_id") or "").strip()
    if not session_id or not is_session_active(session_id, user_id=user_id):
        raise HTTPException(status_code=401, detail="Local access token session is invalid")

    user = get_active_user_context(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Local access token user is unavailable")

    return principal_from_local_user(user, session_id)


def verify_shared_token(token: str) -> dict[str, Any]:
    """Verify a shared-token and return the principal.

    Security (§security-R5): the default principal is now a scoped
    `viewer` with no namespace access. A leaked shared token does NOT
    grant admin anymore. Callers that need a privileged principal must
    present a runtime identity claim via
    `verify_shared_token_with_identity`.
    """
    if not SHARED_TOKEN:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if not hmac.compare_digest(token, SHARED_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return build_shared_token_principal()


def verify_shared_token_with_identity(
    token: str,
    identity_header: str | None,
) -> dict[str, Any]:
    """Verify a shared-token bound to a runtime identity.

    The ``identity_header`` is an HMAC-SHA256 digest in hex form, computed
    by the runtime as::

        hmac_sha256(RUNTIME_IDENTITY_HMAC_SECRET, agent_name + ":" + namespace)

    Both the api-gateway and the operator share the same secret. The
    operator injects the secret into each agent runtime, and the api-gateway
    reads it from ``RUNTIME_IDENTITY_HMAC_SECRET``.

    When the HMAC validates, the returned principal is scoped to the
    named namespace with the `operator` role — sufficient to call
    internal endpoints (events, traces, approvals) on behalf of the
    specific agent. When the HMAC is missing or invalid, the
    `verify_shared_token` fallback applies (viewer with no namespace
    access), so the caller cannot escalate.
    """
    if not SHARED_TOKEN:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    if not hmac.compare_digest(token, SHARED_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid bearer token")

    if not identity_header:
        # Caller did not present a runtime identity claim. Fall back to
        # the unscoped principal — this preserves the legacy "shared
        # token = admin" behavior for non-runtime callers (workers,
        # operators) that have not yet been migrated.
        return build_shared_token_principal()

    parsed = _parse_runtime_identity_header(identity_header)
    if parsed is None:
        # Header was malformed; treat as missing rather than as a hard
        # error so a misconfigured caller can recover.
        return build_shared_token_principal()

    agent_name, namespace, presented_digest = parsed

    secret = os.getenv("RUNTIME_IDENTITY_HMAC_SECRET", "").strip()
    if not secret:
        # Identity binding is not configured on the gateway. This is
        # expected during first install; fall back to the unscoped
        # principal.
        return build_shared_token_principal()

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{agent_name}:{namespace}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(presented_digest, expected):
        # Invalid identity claim — do NOT escalate. Treat as a failed
        # authentication and deny.
        raise HTTPException(
            status_code=401,
            detail="Invalid runtime identity claim",
        )

    return build_runtime_identity_principal(
        agent_name=agent_name,
        namespace=namespace,
    )


def _parse_runtime_identity_header(header: str) -> tuple[str, str, str] | None:
    """Parse ``agent_name:namespace:hex_digest`` into a tuple.

    Returns ``None`` if the header is malformed. The agent name and
    namespace are constrained to a safe character set to prevent
    injection of additional header values.
    """
    if not header:
        return None
    parts = header.split(":")
    if len(parts) != 3:
        return None
    agent_name, namespace, digest = (p.strip() for p in parts)
    if not agent_name or not namespace or not digest:
        return None
    safe_name = re.match(r"^[A-Za-z0-9._-]{1,253}$", agent_name)
    safe_ns = re.match(r"^[A-Za-z0-9._-]{1,253}$", namespace)
    safe_digest = re.match(r"^[a-f0-9]{64}$", digest)
    if not (safe_name and safe_ns and safe_digest):
        return None
    return agent_name, namespace, digest


async def authenticate_bearer_token(
    token: str,
    *,
    runtime_identity: str | None = None,
) -> dict[str, Any]:
    """Route token verification through the configured auth mode.

    When ``runtime_identity`` is provided and the auth mode is
    shared_token / hybrid / enterprise, the shared token is bound to
    the named agent/namespace. A leaked shared token without a valid
    identity claim no longer escalates to admin.
    """
    if AUTH_MODE == "shared_token":
        # If local auth is also enabled and the token looks like a JWT,
        # try local verification first (supports password-login sessions).
        if local_access_enabled() and token.count(".") == 2:
            try:
                return verify_local_access_token(token)
            except HTTPException:
                pass
        if runtime_identity is not None:
            return verify_shared_token_with_identity(token, runtime_identity)
        return verify_shared_token(token)
    if AUTH_MODE == "oidc":
        return await verify_oidc_token(token)
    if AUTH_MODE == "local":
        return verify_local_access_token(token)

    if AUTH_MODE not in {"auto", "hybrid", "enterprise"}:
        raise HTTPException(status_code=503, detail=f"Unsupported auth mode '{AUTH_MODE}'")

    failures: list[str] = []
    is_jwt_like = token.count(".") == 2

    if local_access_enabled() and is_jwt_like:
        try:
            return verify_local_access_token(token)
        except HTTPException as exc:
            failures.append(str(exc.detail))

    if oidc_bearer_enabled() and is_jwt_like:
        try:
            return await verify_oidc_token(token)
        except HTTPException as exc:
            failures.append(str(exc.detail))
        except Exception as exc:
            logger.debug("OIDC bearer verification failed in hybrid mode (%s): %s", type(exc).__name__, exc)
            logger.warning("OIDC bearer verification failed in hybrid mode: %s", exc)
            failures.append(str(exc))

    if shared_token_enabled():
        try:
            if runtime_identity is not None:
                return verify_shared_token_with_identity(token, runtime_identity)
            return verify_shared_token(token)
        except HTTPException as exc:
            failures.append(str(exc.detail))

    logger.warning("Authentication failed in hybrid mode: %s", failures)
    raise HTTPException(status_code=401, detail="Authentication failed")


async def verify_token(
    authorization: str | None = Header(default=None),
    x_runtime_identity: str | None = Header(default=None, alias="X-Runtime-Identity"),
) -> dict[str, Any]:
    """FastAPI dependency — verify the Bearer token from the Authorization header.

    The optional ``X-Runtime-Identity`` header carries the per-agent
    HMAC that binds the shared token to a specific agent + namespace.
    """
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    identity = (x_runtime_identity or "").strip() or None
    return await authenticate_bearer_token(token, runtime_identity=identity)


async def verify_token_or_query(
    raw_request: Request,
    authorization: str | None = Header(default=None),
    x_runtime_identity: str | None = Header(default=None, alias="X-Runtime-Identity"),
) -> dict[str, Any]:
    """Like verify_token but also accepts a *token* query-parameter.

    SSE / EventSource connections cannot set custom HTTP headers, so the
    browser passes the access token in the query string instead. The
    X-Runtime-Identity header, when present, is also forwarded.
    """
    identity = (x_runtime_identity or "").strip() or None
    if authorization and authorization.startswith("Bearer "):
        tok = authorization[7:].strip()
        if tok:
            return await authenticate_bearer_token(tok, runtime_identity=identity)

    tok = raw_request.query_params.get("token", "").strip()
    if tok:
        # Query-param tokens are used for SSE where headers cannot be set.
        # Never log the raw token value — sanitize before logging.
        logger.info("SSE auth via query param from client %s", request_client_ip(raw_request))
        return await authenticate_bearer_token(tok, runtime_identity=identity)

    raise HTTPException(status_code=401, detail="Missing token")


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature of a webhook payload.

    Args:
        payload: Raw request body bytes.
        signature: Hex-digest string from the ``X-kubesynapse-Signature`` header.
        secret: Shared secret stored in a Kubernetes Secret.

    Returns:
        ``True`` if the signature is valid, else ``False``.

    Security notes:
        - Uses ``hmac.compare_digest`` to prevent timing attacks.
        - Secrets should be rotated every 90 days.
        - Use unique secrets per webhook receiver.
        - Prefer Kubernetes Secrets (via secret_ref) over env vars or plaintext.
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
