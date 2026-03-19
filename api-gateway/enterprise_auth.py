"""Enterprise authentication helpers for LDAP, OIDC, and SAML providers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from jose import jwt

ROLE_PRIORITY = {"viewer": 1, "operator": 2, "admin": 3}
logger = logging.getLogger("api-gateway.enterprise-auth")


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _json_env(name: str, default: Any) -> Any:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid JSON value for %s.", name)
        return default


LDAP_ENABLED = _truthy(os.getenv("LDAP_ENABLED"), False)
LDAP_SERVER_URL = os.getenv("LDAP_SERVER_URL", "").strip()
LDAP_BIND_DN = os.getenv("LDAP_BIND_DN", "").strip()
LDAP_BIND_PASSWORD = os.getenv("LDAP_BIND_PASSWORD", "").strip()
LDAP_USER_SEARCH_BASE = os.getenv("LDAP_USER_SEARCH_BASE", "").strip()
LDAP_USER_SEARCH_FILTER = os.getenv("LDAP_USER_SEARCH_FILTER", "(uid={username})").strip() or "(uid={username})"
LDAP_GROUP_SEARCH_BASE = os.getenv("LDAP_GROUP_SEARCH_BASE", "").strip()
LDAP_GROUP_SEARCH_FILTER = os.getenv("LDAP_GROUP_SEARCH_FILTER", "(member={user_dn})").strip() or "(member={user_dn})"
LDAP_GROUP_ATTRIBUTE = os.getenv("LDAP_GROUP_ATTRIBUTE", "memberOf").strip() or "memberOf"
LDAP_USERNAME_ATTRIBUTE = os.getenv("LDAP_USERNAME_ATTRIBUTE", "uid").strip() or "uid"
LDAP_EMAIL_ATTRIBUTE = os.getenv("LDAP_EMAIL_ATTRIBUTE", "mail").strip() or "mail"
LDAP_DISPLAY_NAME_ATTRIBUTE = os.getenv("LDAP_DISPLAY_NAME_ATTRIBUTE", "displayName").strip() or "displayName"
LDAP_USE_STARTTLS = _truthy(os.getenv("LDAP_TLS_ENABLED"), False)
LDAP_GROUP_ROLE_MAPPING = _json_env("LDAP_GROUP_ROLE_MAPPING", {})

OIDC_PROVIDER_CACHE: dict[str, dict[str, Any]] = {}
_OIDC_CACHE_TTL_SECONDS = 3600  # 1 hour


def _normalize_group_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray)):
        return [value.decode("utf-8", errors="ignore").strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            normalized.extend(_normalize_group_values(item))
        return [item for item in normalized if item]
    return [str(value).strip()] if str(value).strip() else []


def _namespaces_from_mapping(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def resolve_role_mapping(groups: list[str], mapping: dict[str, Any], default_role: str = "viewer") -> tuple[str, list[str]]:
    role = default_role if default_role in ROLE_PRIORITY else "viewer"
    namespaces: set[str] = set()
    lowered_groups = {group.lower(): group for group in groups}
    for raw_group, config in mapping.items():
        if raw_group.lower() not in lowered_groups:
            continue
        candidate_role = role
        candidate_namespaces: list[str] = []
        if isinstance(config, str):
            candidate_role = config
        elif isinstance(config, dict):
            candidate_role = str(config.get("role") or role)
            candidate_namespaces = _namespaces_from_mapping(config.get("allowed_namespaces"))
        if ROLE_PRIORITY.get(candidate_role, 0) > ROLE_PRIORITY.get(role, 0):
            role = candidate_role
        namespaces.update(candidate_namespaces)
    return role, sorted(namespaces)


def ldap_enabled() -> bool:
    return LDAP_ENABLED and bool(LDAP_SERVER_URL and LDAP_USER_SEARCH_BASE)


def _ldap_escape(value: str) -> str:
    """Escape special characters for safe LDAP filter interpolation (RFC 4515)."""
    result: list[str] = []
    for ch in value:
        if ch == '\\':
            result.append('\\5c')
        elif ch == '*':
            result.append('\\2a')
        elif ch == '(':
            result.append('\\28')
        elif ch == ')':
            result.append('\\29')
        elif ch == '\x00':
            result.append('\\00')
        else:
            result.append(ch)
    return ''.join(result)


def authenticate_ldap_user(username: str, password: str) -> dict[str, Any]:
    if not ldap_enabled():
        raise ValueError("LDAP authentication is not configured.")
    if not username.strip() or not password:
        raise ValueError("Username and password are required.")

    try:
        import ldap  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError("python-ldap is not installed in this environment.") from exc

    connection = ldap.initialize(LDAP_SERVER_URL)
    if LDAP_SERVER_URL.startswith("ldap://") and not LDAP_USE_STARTTLS:
        logger.warning(
            "LDAP connection uses plaintext ldap:// without StartTLS. "
            "Credentials will transit in cleartext. Set LDAP_TLS_ENABLED=true "
            "or use ldaps:// to encrypt the connection."
        )
    user_connection = None
    try:
        connection.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        if LDAP_USE_STARTTLS:
            connection.start_tls_s()
        if LDAP_BIND_DN:
            connection.simple_bind_s(LDAP_BIND_DN, LDAP_BIND_PASSWORD)

        search_filter = LDAP_USER_SEARCH_FILTER.format(username=_ldap_escape(username.strip()))
        results = connection.search_s(
            LDAP_USER_SEARCH_BASE,
            ldap.SCOPE_SUBTREE,
            search_filter,
            [LDAP_USERNAME_ATTRIBUTE, LDAP_EMAIL_ATTRIBUTE, LDAP_DISPLAY_NAME_ATTRIBUTE, LDAP_GROUP_ATTRIBUTE],
        )
        if not results:
            raise ValueError("User was not found in LDAP.")

        user_dn, attributes = results[0]
        user_connection = ldap.initialize(LDAP_SERVER_URL)
        user_connection.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        if LDAP_USE_STARTTLS:
            user_connection.start_tls_s()
        user_connection.simple_bind_s(user_dn, password)

        group_values = _normalize_group_values(attributes.get(LDAP_GROUP_ATTRIBUTE, []))
        if LDAP_GROUP_SEARCH_BASE:
            group_results = connection.search_s(
                LDAP_GROUP_SEARCH_BASE,
                ldap.SCOPE_SUBTREE,
                LDAP_GROUP_SEARCH_FILTER.format(user_dn=_ldap_escape(user_dn), username=_ldap_escape(username.strip())),
                ["cn", "distinguishedName"],
            )
            for group_dn, group_attrs in group_results:
                if group_dn:
                    group_values.append(str(group_dn))
                group_values.extend(_normalize_group_values(group_attrs.get("cn", [])))

        role, allowed_namespaces = resolve_role_mapping(group_values, LDAP_GROUP_ROLE_MAPPING)

        username_values = _normalize_group_values(attributes.get(LDAP_USERNAME_ATTRIBUTE, []))
        email_values = _normalize_group_values(attributes.get(LDAP_EMAIL_ATTRIBUTE, []))
        display_name_values = _normalize_group_values(attributes.get(LDAP_DISPLAY_NAME_ATTRIBUTE, []))

        return {
            "username": (username_values[0] if username_values else username).strip().lower(),
            "email": email_values[0] if email_values else None,
            "display_name": display_name_values[0] if display_name_values else username.strip(),
            "external_id": str(user_dn),
            "auth_provider": "ldap",
            "role": role,
            "allowed_namespaces": allowed_namespaces,
            "groups": sorted(set(group_values)),
        }
    finally:
        try:
            connection.unbind_s()
        except Exception:
            pass
        if user_connection is not None:
            try:
                user_connection.unbind_s()
            except Exception:
                pass


def oidc_providers() -> list[dict[str, Any]]:
    raw_providers = _json_env("OIDC_PROVIDERS_JSON", [])
    if not isinstance(raw_providers, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_providers:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("id") or "").strip()
        if not provider_id:
            continue
        normalized.append(
            {
                "id": provider_id,
                "name": str(item.get("name") or provider_id).strip() or provider_id,
                "issuer": str(item.get("issuer") or "").strip(),
                "client_id": str(item.get("client_id") or item.get("clientId") or "").strip(),
                "client_secret": str(item.get("client_secret") or item.get("clientSecret") or "").strip(),
                "scopes": item.get("scopes") or ["openid", "profile", "email"],
                "redirect_uri": str(item.get("redirect_uri") or item.get("redirectUri") or "").strip(),
                "group_claim": str(item.get("group_claim") or item.get("groupClaim") or "groups").strip() or "groups",
                "group_role_mapping": item.get("group_role_mapping") or item.get("groupRoleMapping") or {},
                "authorization_endpoint": str(item.get("authorization_endpoint") or item.get("authorizationEndpoint") or "").strip(),
                "token_endpoint": str(item.get("token_endpoint") or item.get("tokenEndpoint") or "").strip(),
                "userinfo_endpoint": str(item.get("userinfo_endpoint") or item.get("userinfoEndpoint") or "").strip(),
                "jwks_url": str(item.get("jwks_url") or item.get("jwksUrl") or "").strip(),
                "end_session_endpoint": str(item.get("end_session_endpoint") or item.get("endSessionEndpoint") or "").strip(),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return [item for item in normalized if item["enabled"]]


def _configured_saml_providers() -> list[dict[str, Any]]:
    raw_providers = _json_env("SAML_PROVIDERS_JSON", [])
    if not isinstance(raw_providers, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_providers:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("id") or "").strip()
        if not provider_id:
            continue
        normalized.append(
            {
                "id": provider_id,
                "name": str(item.get("name") or provider_id).strip() or provider_id,
                "kind": "saml",
                "enabled": bool(item.get("enabled", True)),
                "idp_entity_id": str(item.get("idp_entity_id") or item.get("idpEntityId") or item.get("entity_id") or item.get("entityId") or "").strip(),
                "sso_url": str(item.get("sso_url") or item.get("ssoUrl") or item.get("entry_point") or item.get("entryPoint") or "").strip(),
                "idp_slo_url": str(item.get("idp_slo_url") or item.get("idpSloUrl") or item.get("slo_url") or item.get("sloUrl") or "").strip(),
                "x509cert": str(item.get("x509cert") or item.get("x509Cert") or item.get("certificate") or "").strip(),
                "x509cert_multi": item.get("x509cert_multi") or item.get("x509CertMulti") or {},
                "sp_entity_id": str(item.get("sp_entity_id") or item.get("spEntityId") or "").strip(),
                "acs_url": str(item.get("acs_url") or item.get("acsUrl") or "").strip(),
                "sp_slo_url": str(item.get("sp_slo_url") or item.get("spSloUrl") or "").strip(),
                "nameid_format": str(item.get("nameid_format") or item.get("nameIdFormat") or "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress").strip(),
                "username_attribute": str(item.get("username_attribute") or item.get("usernameAttribute") or "uid").strip() or "uid",
                "email_attribute": str(item.get("email_attribute") or item.get("emailAttribute") or "mail").strip() or "mail",
                "display_name_attribute": str(item.get("display_name_attribute") or item.get("displayNameAttribute") or "displayName").strip() or "displayName",
                "group_attribute": str(item.get("group_attribute") or item.get("groupAttribute") or "groups").strip() or "groups",
                "group_role_mapping": item.get("group_role_mapping") or item.get("groupRoleMapping") or {},
                "requested_authn_context": item.get("requested_authn_context") or item.get("requestedAuthnContext") or False,
                "authn_requests_signed": bool(item.get("authn_requests_signed") or item.get("authnRequestsSigned") or False),
                "want_assertions_signed": bool(item.get("want_assertions_signed", True)),
                "want_messages_signed": bool(item.get("want_messages_signed") or item.get("wantMessagesSigned") or False),
                "sp_x509cert": str(item.get("sp_x509cert") or item.get("spX509Cert") or "").strip(),
                "sp_private_key": str(item.get("sp_private_key") or item.get("spPrivateKey") or "").strip(),
            }
        )
    return [item for item in normalized if item["enabled"]]


def saml_providers() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "kind": "saml",
            "supported": True,
        }
        for item in _configured_saml_providers()
    ]


def auth_configuration() -> dict[str, Any]:
    return {
        "password_providers": [provider for provider in ["local", "ldap" if ldap_enabled() else None] if provider],
        "oidc_providers": [
            {"id": item["id"], "name": item["name"], "kind": "oidc", "supported": True}
            for item in oidc_providers()
        ],
        "saml_providers": saml_providers(),
    }


def get_oidc_provider(*, provider_id: str | None = None, issuer: str | None = None) -> dict[str, Any] | None:
    for provider in oidc_providers():
        if provider_id and provider["id"] == provider_id:
            return provider
        if issuer and provider.get("issuer") == issuer:
            return provider
    return None


def get_saml_provider(*, provider_id: str) -> dict[str, Any] | None:
    for provider in _configured_saml_providers():
        if provider["id"] == provider_id:
            return provider
    return None


def _load_saml_runtime() -> Any:
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("python3-saml is not installed or is missing runtime dependencies.") from exc
    return OneLogin_Saml2_Auth


def _saml_settings(provider: dict[str, Any], base_url: str) -> dict[str, Any]:
    parsed_base_url = urlparse(base_url)
    if not parsed_base_url.scheme or not parsed_base_url.netloc:
        raise ValueError("A valid public base URL is required for SAML authentication.")

    provider_id = str(provider["id"])
    idp_entity_id = str(provider.get("idp_entity_id") or "").strip()
    sso_url = str(provider.get("sso_url") or "").strip()
    x509cert = str(provider.get("x509cert") or "").strip()
    x509cert_multi = provider.get("x509cert_multi") if isinstance(provider.get("x509cert_multi"), dict) else {}
    if not idp_entity_id or not sso_url or (not x509cert and not x509cert_multi):
        raise ValueError(f"SAML provider '{provider_id}' is missing required IdP metadata.")

    acs_url = str(provider.get("acs_url") or f"{base_url}/api/auth/saml/callback/{provider_id}").strip()
    sp_entity_id = str(provider.get("sp_entity_id") or f"{base_url}/api/auth/saml/metadata/{provider_id}").strip()
    settings: dict[str, Any] = {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": sp_entity_id,
            "assertionConsumerService": {
                "url": acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": str(provider.get("nameid_format") or "").strip(),
            "x509cert": str(provider.get("sp_x509cert") or "").strip(),
            "privateKey": str(provider.get("sp_private_key") or "").strip(),
        },
        "idp": {
            "entityId": idp_entity_id,
            "singleSignOnService": {
                "url": sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": x509cert,
        },
        "security": {
            "authnRequestsSigned": bool(provider.get("authn_requests_signed")),
            "wantAssertionsSigned": bool(provider.get("want_assertions_signed", True)),
            "wantMessagesSigned": bool(provider.get("want_messages_signed")),
            "requestedAuthnContext": provider.get("requested_authn_context", False),
        },
    }

    sp_slo_url = str(provider.get("sp_slo_url") or "").strip()
    if sp_slo_url:
        settings["sp"]["singleLogoutService"] = {
            "url": sp_slo_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    idp_slo_url = str(provider.get("idp_slo_url") or "").strip()
    if idp_slo_url:
        settings["idp"]["singleLogoutService"] = {
            "url": idp_slo_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    if x509cert_multi:
        settings["idp"]["x509certMulti"] = x509cert_multi

    return settings


def _saml_request_data(
    *,
    base_url: str,
    request_path: str,
    query_data: dict[str, Any] | None = None,
    post_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_base_url = urlparse(base_url)
    server_port = parsed_base_url.port or (443 if parsed_base_url.scheme == "https" else 80)
    return {
        "https": "on" if parsed_base_url.scheme == "https" else "off",
        "http_host": parsed_base_url.hostname or "",
        "server_port": str(server_port),
        "script_name": request_path,
        "query_string": urlencode(query_data or {}, doseq=True),
        "get_data": query_data or {},
        "post_data": post_data or {},
    }


def build_saml_authorization_request(provider_id: str, base_url: str, next_path: str | None) -> dict[str, str]:
    provider = get_saml_provider(provider_id=provider_id)
    if provider is None:
        raise ValueError(f"SAML provider '{provider_id}' is not configured.")

    OneLogin_Saml2_Auth = _load_saml_runtime()
    auth = OneLogin_Saml2_Auth(
        _saml_request_data(base_url=base_url, request_path=f"/api/auth/saml/start/{provider_id}"),
        old_settings=_saml_settings(provider, base_url),
    )
    relay_state = secrets.token_urlsafe(24)
    authorization_url = auth.login(return_to=relay_state)
    if not authorization_url:
        raise ValueError(f"SAML provider '{provider_id}' did not produce a valid redirect URL.")

    cookie_payload = {
        "kind": "saml",
        "provider_id": provider_id,
        "relay_state": relay_state,
        "request_id": auth.get_last_request_id(),
        "next": sanitize_redirect_path(next_path),
        "created_at": int(time.time()),
    }
    return {
        "authorization_url": authorization_url,
        "cookie_value": _encode_transaction(cookie_payload),
        "redirect_path": sanitize_redirect_path(next_path),
    }


def exchange_saml_response(
    provider_id: str,
    *,
    saml_response: str,
    relay_state: str | None,
    cookie_value: str,
    base_url: str,
    request_path: str,
    query_data: dict[str, Any] | None = None,
    post_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = get_saml_provider(provider_id=provider_id)
    if provider is None:
        raise ValueError(f"SAML provider '{provider_id}' is not configured.")
    if not saml_response.strip():
        raise ValueError("SAML response payload is missing.")

    cookie_payload = decode_transaction_cookie(cookie_value)
    if cookie_payload.get("kind") != "saml" or cookie_payload.get("provider_id") != provider_id:
        raise ValueError("SAML state validation failed.")
    if relay_state != cookie_payload.get("relay_state"):
        raise ValueError("SAML relay state validation failed.")

    OneLogin_Saml2_Auth = _load_saml_runtime()
    auth = OneLogin_Saml2_Auth(
        _saml_request_data(
            base_url=base_url,
            request_path=request_path,
            query_data=query_data,
            post_data=post_data,
        ),
        old_settings=_saml_settings(provider, base_url),
    )
    auth.process_response(request_id=cookie_payload.get("request_id") or None)
    errors = auth.get_errors()
    if errors:
        raise ValueError(f"SAML response validation failed: {', '.join(errors)}")
    if not auth.is_authenticated():
        raise ValueError("SAML authentication was not established.")

    attributes = auth.get_attributes() or {}
    username_values = _normalize_group_values(attributes.get(str(provider.get("username_attribute") or "uid")))
    email_values = _normalize_group_values(attributes.get(str(provider.get("email_attribute") or "mail")))
    display_name_values = _normalize_group_values(attributes.get(str(provider.get("display_name_attribute") or "displayName")))
    group_values = _normalize_group_values(attributes.get(str(provider.get("group_attribute") or "groups")))
    role_mapping = provider.get("group_role_mapping")
    role, allowed_namespaces = resolve_role_mapping(group_values, role_mapping if isinstance(role_mapping, dict) else {})

    name_id = str(auth.get_nameid() or "").strip()
    preferred_username = username_values[0] if username_values else email_values[0] if email_values else name_id
    if not preferred_username:
        raise ValueError("SAML provider did not return a usable username.")

    username = preferred_username.split("@", 1)[0].lower() if "@" in preferred_username else preferred_username.lower()
    display_name = display_name_values[0] if display_name_values else preferred_username
    return {
        "username": username,
        "email": email_values[0] if email_values else None,
        "display_name": display_name,
        "external_id": name_id or preferred_username,
        "auth_provider": f"saml:{provider_id}",
        "role": role,
        "allowed_namespaces": allowed_namespaces,
        "groups": sorted(set(group_values)),
        "next": sanitize_redirect_path(cookie_payload.get("next")),
    }


def saml_metadata_xml(provider_id: str, base_url: str) -> str:
    provider = get_saml_provider(provider_id=provider_id)
    if provider is None:
        raise ValueError(f"SAML provider '{provider_id}' is not configured.")

    OneLogin_Saml2_Auth = _load_saml_runtime()
    auth = OneLogin_Saml2_Auth(
        _saml_request_data(base_url=base_url, request_path=f"/api/auth/saml/metadata/{provider_id}"),
        old_settings=_saml_settings(provider, base_url),
    )
    metadata = auth.get_settings().get_sp_metadata()
    errors = auth.get_settings().validate_metadata(metadata)
    if errors:
        raise ValueError(f"SAML service provider metadata is invalid: {', '.join(errors)}")
    return metadata


def _load_oidc_discovery(provider: dict[str, Any]) -> dict[str, Any]:
    cache_key = provider["id"]
    cached = OIDC_PROVIDER_CACHE.get(cache_key)
    if cached is not None:
        cached_at = cached.get("_cached_at", 0)
        if (time.time() - cached_at) < _OIDC_CACHE_TTL_SECONDS:
            return cached
        # TTL expired — re-fetch
        OIDC_PROVIDER_CACHE.pop(cache_key, None)

    discovered = dict(provider)
    issuer = str(provider.get("issuer") or "").rstrip("/")
    if issuer and (not provider.get("authorization_endpoint") or not provider.get("token_endpoint")):
        try:
            response = httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"Failed to fetch OIDC discovery from {issuer}: {exc}") from exc
        payload = response.json()
        discovered["authorization_endpoint"] = discovered.get("authorization_endpoint") or payload.get("authorization_endpoint", "")
        discovered["token_endpoint"] = discovered.get("token_endpoint") or payload.get("token_endpoint", "")
        discovered["userinfo_endpoint"] = discovered.get("userinfo_endpoint") or payload.get("userinfo_endpoint", "")
        discovered["jwks_url"] = discovered.get("jwks_url") or payload.get("jwks_uri", "")
        discovered["end_session_endpoint"] = discovered.get("end_session_endpoint") or payload.get("end_session_endpoint", "")
    discovered["_cached_at"] = time.time()
    OIDC_PROVIDER_CACHE[cache_key] = discovered
    return discovered


def _fetch_oidc_jwks(jwks_url: str) -> list[dict[str, Any]]:
    """Fetch JWKS keys from the OIDC provider's jwks_uri endpoint."""
    if not jwks_url:
        return []
    try:
        response = httpx.get(jwks_url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        return data.get("keys", [])
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Failed to fetch OIDC JWKS from %s: %s", jwks_url, exc)
        return []


def _verify_oidc_id_token(id_token: str, discovered: dict[str, Any]) -> dict[str, Any]:
    """Verify the OIDC ID token signature using the provider's JWKS, then return claims."""
    from jose import jwk as jose_jwk, jwt as jose_jwt, JWTError
    from jose.utils import base64url_decode as _b64decode

    jwks_url = str(discovered.get("jwks_url") or "").strip()
    client_id = str(discovered.get("client_id") or "").strip()
    issuer = str(discovered.get("issuer") or "").strip()

    if not jwks_url:
        # No JWKS URL available — fall back to unverified claims with a warning.
        logger.warning(
            "OIDC provider '%s' has no jwks_url configured; falling back to unverified ID token claims.",
            discovered.get("id", "unknown"),
        )
        return jose_jwt.get_unverified_claims(id_token)

    keys = _fetch_oidc_jwks(jwks_url)
    if not keys:
        raise ValueError(
            f"OIDC provider '{discovered.get('id', 'unknown')}' returned no JWKS keys from {jwks_url}"
        )

    # Decode the token header to find the key ID (kid)
    unverified_header = jose_jwt.get_unverified_header(id_token)
    token_kid = unverified_header.get("kid")
    token_alg = unverified_header.get("alg", "RS256")

    # Find the matching key
    matching_key = None
    for key_data in keys:
        if token_kid and key_data.get("kid") != token_kid:
            continue
        if key_data.get("alg") and key_data["alg"] != token_alg:
            continue
        matching_key = key_data
        break

    if matching_key is None:
        raise ValueError(
            f"OIDC ID token kid='{token_kid}' not found in provider JWKS."
        )

    # Build the RSA/EC public key and verify
    public_key = jose_jwk.construct(matching_key).public_key()
    try:
        claims = jose_jwt.decode(
            id_token,
            public_key,
            algorithms=[token_alg],
            audience=client_id or None,
            issuer=issuer or None,
            options={
                "verify_aud": bool(client_id),
                "verify_iss": bool(issuer),
                "verify_exp": True,
            },
        )
    except JWTError as exc:
        raise ValueError(f"OIDC ID token signature verification failed: {exc}") from exc

    return claims


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


# Key used to HMAC-sign OIDC/SAML transaction cookies so they cannot be tampered with.
_TRANSACTION_HMAC_KEY: bytes = (os.getenv("TRANSACTION_COOKIE_HMAC_KEY", "").strip().encode("utf-8")
                                or os.getenv("JWT_SECRET", "").strip().encode("utf-8")
                                or secrets.token_bytes(32))


def _encode_transaction(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_TRANSACTION_HMAC_KEY, data, hashlib.sha256).digest()
    return _base64url(sig + data)


def decode_transaction_cookie(value: str) -> dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode((value + padding).encode("utf-8"))
    if len(raw) < 32:
        raise ValueError("OIDC state cookie is too short.")
    sig, data = raw[:32], raw[32:]
    expected = hmac.new(_TRANSACTION_HMAC_KEY, data, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("OIDC state cookie signature is invalid.")
    parsed = json.loads(data.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("OIDC state cookie is invalid.")
    return parsed


def sanitize_redirect_path(value: str | None) -> str:
    """Ensure redirect target is a safe, same-origin relative path."""
    from urllib.parse import unquote

    candidate = str(value or "").strip()
    if not candidate or not candidate.startswith("/"):
        return "/"
    # Reject protocol-relative URLs, backslash tricks, and dangerous schemes
    if candidate.startswith("//") or candidate.startswith("/\\"):
        return "/"
    # Decode percent-encoding and re-validate
    try:
        decoded = unquote(candidate)
    except Exception:
        return "/"
    if decoded.startswith("//") or decoded.startswith("/\\"):
        return "/"
    # Block javascript: / data: / vbscript: after decoding
    stripped = decoded.lstrip("/").lower()
    if any(stripped.startswith(s) for s in ("javascript:", "data:", "vbscript:")):
        return "/"
    # Reject paths with host component (e.g. /@evil.com, /\evil.com)
    parsed = urlparse(decoded)
    if parsed.scheme or parsed.netloc:
        return "/"
    return candidate


def build_oidc_authorization_request(provider_id: str, base_url: str, next_path: str | None) -> dict[str, str]:
    provider = get_oidc_provider(provider_id=provider_id)
    if provider is None:
        raise ValueError(f"OIDC provider '{provider_id}' is not configured.")
    discovered = _load_oidc_discovery(provider)
    authorize_endpoint = str(discovered.get("authorization_endpoint") or "").strip()
    client_id = str(discovered.get("client_id") or "").strip()
    if not authorize_endpoint or not client_id:
        raise ValueError(f"OIDC provider '{provider_id}' is missing authorization metadata.")

    redirect_uri = str(discovered.get("redirect_uri") or f"{base_url}/api/auth/oidc/callback/{provider_id}").strip()
    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = _base64url(hashlib.sha256(code_verifier.encode("utf-8")).digest())
    requested_next = sanitize_redirect_path(next_path)
    cookie_payload = {
        "provider_id": provider_id,
        "state": state,
        "code_verifier": code_verifier,
        "next": requested_next,
        "created_at": int(time.time()),
    }
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(discovered.get("scopes") or ["openid", "profile", "email"]),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return {
        "authorization_url": f"{authorize_endpoint}?{query}",
        "cookie_value": _encode_transaction(cookie_payload),
        "redirect_path": requested_next,
    }


def exchange_oidc_code(provider_id: str, code: str, state: str, cookie_value: str, base_url: str) -> dict[str, Any]:
    provider = get_oidc_provider(provider_id=provider_id)
    if provider is None:
        raise ValueError(f"OIDC provider '{provider_id}' is not configured.")
    discovered = _load_oidc_discovery(provider)
    token_endpoint = str(discovered.get("token_endpoint") or "").strip()
    client_id = str(discovered.get("client_id") or "").strip()
    if not token_endpoint or not client_id:
        raise ValueError(f"OIDC provider '{provider_id}' is missing token metadata.")

    cookie_payload = decode_transaction_cookie(cookie_value)
    if cookie_payload.get("provider_id") != provider_id or cookie_payload.get("state") != state:
        raise ValueError("OIDC state validation failed.")

    redirect_uri = str(discovered.get("redirect_uri") or f"{base_url}/api/auth/oidc/callback/{provider_id}").strip()
    try:
        token_response = httpx.post(
            token_endpoint,
            timeout=10.0,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": discovered.get("client_secret") or "",
                "code_verifier": cookie_payload.get("code_verifier") or "",
            },
            headers={"Accept": "application/json"},
        )
        token_response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError(f"OIDC token exchange failed for provider '{provider_id}': {exc}") from exc
    token_payload = token_response.json()

    claims: dict[str, Any] = {}
    id_token = str(token_payload.get("id_token") or "").strip()
    if id_token:
        claims = _verify_oidc_id_token(id_token, discovered)
    elif discovered.get("userinfo_endpoint"):
        try:
            userinfo_response = httpx.get(
                str(discovered["userinfo_endpoint"]),
                timeout=10.0,
                headers={"Authorization": f"Bearer {token_payload.get('access_token', '')}"},
            )
            userinfo_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"OIDC userinfo request failed for provider '{provider_id}': {exc}") from exc
        claims = userinfo_response.json()

    if not isinstance(claims, dict) or not claims.get("sub"):
        raise ValueError("OIDC provider did not return a valid subject claim.")

    issuer = str(discovered.get("issuer") or "").strip()
    if issuer and str(claims.get("iss") or issuer) != issuer:
        raise ValueError("OIDC issuer validation failed.")
    audience = claims.get("aud")
    if audience is not None and not (
        audience == client_id or (isinstance(audience, list) and client_id in audience)
    ):
        raise ValueError("OIDC audience validation failed.")

    group_claim = str(discovered.get("group_claim") or "groups")
    groups = _normalize_group_values(claims.get(group_claim))
    role_mapping = discovered.get("group_role_mapping")
    role, allowed_namespaces = resolve_role_mapping(groups, role_mapping if isinstance(role_mapping, dict) else {})

    preferred_username = str(
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
        or claims.get("sub")
    ).strip()
    username = preferred_username.split("@", 1)[0].lower() if "@" in preferred_username else preferred_username.lower()
    display_name = str(claims.get("name") or claims.get("given_name") or username).strip() or username

    return {
        "username": username,
        "email": str(claims.get("email") or "").strip() or None,
        "display_name": display_name,
        "external_id": str(claims.get("sub")),
        "auth_provider": f"oidc:{provider_id}",
        "role": role,
        "allowed_namespaces": allowed_namespaces,
        "groups": groups,
        "next": sanitize_redirect_path(cookie_payload.get("next")),
    }
