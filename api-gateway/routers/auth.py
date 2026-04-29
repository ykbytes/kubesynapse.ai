"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

from typing import Any, cast

# Re-import all shared symbols from the gateway core
from _core import *
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter(tags=["auth"])

@router.get("/auth/config")
def get_auth_config() -> dict[str, Any]:
    return auth_configuration_payload()


@router.post("/auth/register")
def register_local_user(body: AuthRegisterRequest, raw_request: Request):
    if not local_access_enabled():
        raise HTTPException(status_code=503, detail="Local authentication is not enabled")
    if not registration_allowed():
        raise HTTPException(status_code=403, detail="Self-registration is disabled")

    # Rate-limit registration using the same mechanism as login
    rate_limit_key = login_rate_limit_key(request_client_ip(raw_request), body.username.strip().lower())
    if login_rate_limited(rate_limit_key):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Try again shortly.")

    # Validate email early before DB operations
    try:
        validated_email = validate_email(body.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Atomic first-user check: count once and use that value
    user_count = count_users()
    is_first_user = user_count == 0
    role = "admin" if is_first_user else "operator"
    namespaces = ["*"] if is_first_user else ["default"]
    try:
        user = create_local_user(
            username=body.username,
            password=body.password,
            email=validated_email,
            display_name=body.display_name,
            role=role,
            allowed_namespaces=namespaces,
        )
    except ValueError as exc:
        note_login_attempt(rate_limit_key, success=False)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_record, refresh_token = create_session_for_user(
        int(user["id"]),
        auth_provider=str(user.get("auth_provider") or "local"),
        ip_address=request_client_ip(raw_request),
        user_agent=raw_request.headers.get("user-agent"),
        ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
    )
    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.register",
        principal=principal,
        detail={"role": role},
        ip_address=request_client_ip(raw_request),
    )
    note_login_attempt(rate_limit_key, success=True)
    return issue_session_response(user, session_record, refresh_token, status_code=201)


@router.post("/auth/login")
def login(body: AuthLoginRequest, raw_request: Request):
    provider = body.provider.strip().lower() or "local"
    username = body.username.strip().lower()
    rate_limit_key = login_rate_limit_key(request_client_ip(raw_request), username)
    if login_rate_limited(rate_limit_key):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again shortly.")

    user: dict[str, Any]
    if provider == "local":
        if not local_access_enabled():
            raise HTTPException(status_code=503, detail="Local authentication is not enabled")
        db_user = get_user_by_username(username)
        if db_user is None or not verify_password(body.password, cast(str, db_user.password_hash)):
            note_login_attempt(rate_limit_key, success=False)
            record_failed_login(username)
            raise HTTPException(status_code=401, detail="Invalid username or password")
        if not bool(db_user.is_active):
            raise HTTPException(status_code=403, detail="User account is inactive")
        if is_user_locked(db_user):
            raise HTTPException(status_code=423, detail="User account is temporarily locked")
        reset_failed_logins(cast(int, db_user.id))
        user = get_active_user_context(cast(int, db_user.id)) or serialize_user(db_user)
    elif provider == "ldap":
        if not ldap_enabled():
            raise HTTPException(status_code=503, detail="LDAP authentication is not enabled")
        try:
            ldap_identity = authenticate_ldap_user(username, body.password)
            user = upsert_external_user(
                username=str(ldap_identity["username"]),
                email=ldap_identity.get("email"),
                display_name=ldap_identity.get("display_name"),
                auth_provider=str(ldap_identity.get("auth_provider") or "ldap"),
                external_id=str(ldap_identity["external_id"]),
                role=str(ldap_identity.get("role") or "viewer"),
                allowed_namespaces=ldap_identity.get("allowed_namespaces"),
            )
        except ValueError as exc:
            note_login_attempt(rate_limit_key, success=False)
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported auth provider '{provider}'")

    note_login_attempt(rate_limit_key, success=True)
    session_record, refresh_token = create_session_for_user(
        int(user["id"]),
        auth_provider=str(user.get("auth_provider") or provider),
        ip_address=request_client_ip(raw_request),
        user_agent=raw_request.headers.get("user-agent"),
        ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
    )
    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.login",
        principal=principal,
        detail={"provider": provider},
        ip_address=request_client_ip(raw_request),
    )
    return issue_session_response(user, session_record, refresh_token)


@router.post("/auth/refresh")
def refresh_session(
    raw_request: Request,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token cookie is missing")
    try:
        user, session_record, new_refresh_token = rotate_refresh_session(
            refresh_token,
            ip_address=request_client_ip(raw_request),
            user_agent=raw_request.headers.get("user-agent"),
            ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.refresh",
        principal=principal,
        ip_address=request_client_ip(raw_request),
    )
    return issue_session_response(user, session_record, new_refresh_token)


@router.post("/auth/logout")
async def logout(
    raw_request: Request,
    authorization: str | None = Header(default=None),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    principal: dict[str, Any] | None = None
    if authorization and authorization.startswith("Bearer "):
        with contextlib.suppress(HTTPException):
            principal = await authenticate_bearer_token(authorization[7:].strip())

    if refresh_token:
        revoke_refresh_token(refresh_token)

    response = JSONResponse({"status": "logged_out"})
    clear_refresh_cookie(response)
    clear_oidc_transaction_cookie(response)
    safe_record_audit(
        action="auth.logout",
        principal=principal,
        ip_address=request_client_ip(raw_request),
    )
    return response


@router.get("/auth/me")
def get_current_user(user=Depends(verify_token)) -> dict[str, Any]:
    return {"user": user, "auth_mode": AUTH_MODE}


@router.post("/auth/change-password")
def change_password_endpoint(
    body: ChangePasswordRequest,
    raw_request: Request,
    user=Depends(verify_token),
) -> dict[str, Any]:
    if str(user.get("auth_provider") or "") != "local":
        raise HTTPException(status_code=400, detail="Password changes are only supported for local users")
    try:
        updated_user = change_user_password(int(str(user.get("sub") or "0")), body.current_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    principal = principal_from_local_user(updated_user, str(user.get("session_id") or ""))
    safe_record_audit(
        action="auth.change-password",
        principal=principal,
        ip_address=request_client_ip(raw_request),
    )
    return {"status": "updated", "user": principal}


@router.get("/auth/oidc/start/{provider_id}")
def start_oidc_login(provider_id: str, raw_request: Request, next: str = "/"):
    if get_oidc_provider(provider_id=provider_id) is None:
        raise HTTPException(status_code=404, detail=f"OIDC provider '{provider_id}' is not configured")
    try:
        auth_request = build_oidc_authorization_request(provider_id, public_base_url(raw_request), next)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = RedirectResponse(url=auth_request["authorization_url"], status_code=status.HTTP_302_FOUND)
    set_oidc_transaction_cookie(response, auth_request["cookie_value"])
    return response


@router.get("/auth/oidc/callback/{provider_id}")
def finish_oidc_login(
    provider_id: str,
    raw_request: Request,
    code: str,
    state: str,
    oidc_transaction: str | None = Cookie(default=None, alias=OIDC_TRANSACTION_COOKIE_NAME),
):
    if not oidc_transaction:
        raise HTTPException(status_code=400, detail="OIDC login transaction cookie is missing")

    try:
        identity = exchange_oidc_code(
            provider_id,
            code,
            state,
            oidc_transaction,
            public_base_url(raw_request),
        )
        user = upsert_external_user(
            username=str(identity["username"]),
            email=identity.get("email"),
            display_name=identity.get("display_name"),
            auth_provider=str(identity.get("auth_provider") or f"oidc:{provider_id}"),
            external_id=str(identity["external_id"]),
            role=str(identity.get("role") or "viewer"),
            allowed_namespaces=identity.get("allowed_namespaces"),
        )
        session_record, refresh_token = create_session_for_user(
            int(user["id"]),
            auth_provider=str(user.get("auth_provider") or f"oidc:{provider_id}"),
            ip_address=request_client_ip(raw_request),
            user_agent=raw_request.headers.get("user-agent"),
            ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    redirect_path = sanitize_redirect_path(str(identity.get("next") or "/"))
    separator = "&" if "?" in redirect_path else "?"
    response = RedirectResponse(
        url=f"{redirect_path}{separator}auth=success&provider={provider_id}",
        status_code=status.HTTP_302_FOUND,
    )
    set_refresh_cookie(response, refresh_token)
    clear_oidc_transaction_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.oidc-login",
        principal=principal,
        detail={"provider": provider_id},
        ip_address=request_client_ip(raw_request),
    )
    return response


@router.get("/auth/saml/start/{provider_id}")
def start_saml_login(provider_id: str, raw_request: Request, next: str = "/"):
    if get_saml_provider(provider_id=provider_id) is None:
        raise HTTPException(status_code=404, detail=f"SAML provider '{provider_id}' is not configured")
    try:
        auth_request = build_saml_authorization_request(provider_id, public_base_url(raw_request), next)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = RedirectResponse(url=auth_request["authorization_url"], status_code=status.HTTP_302_FOUND)
    set_oidc_transaction_cookie(response, auth_request["cookie_value"])
    return response


@app.api_route("/auth/saml/callback/{provider_id}", methods=["POST"])
async def finish_saml_login(
    provider_id: str,
    raw_request: Request,
    oidc_transaction: str | None = Cookie(default=None, alias=OIDC_TRANSACTION_COOKIE_NAME),
):
    if not oidc_transaction:
        raise HTTPException(status_code=400, detail="SAML login transaction cookie is missing")

    query_data = dict(raw_request.query_params.multi_items())
    form_data = await raw_request.form()
    post_data = {str(key): str(value) for key, value in form_data.multi_items()}

    saml_response = str(post_data.get("SAMLResponse") or "").strip()
    relay_state = str(post_data.get("RelayState") or "").strip() or None

    try:
        identity = exchange_saml_response(
            provider_id,
            saml_response=saml_response,
            relay_state=relay_state,
            cookie_value=oidc_transaction,
            base_url=public_base_url(raw_request),
            request_path=raw_request.url.path,
            query_data=query_data,
            post_data=post_data,
        )
        user = upsert_external_user(
            username=str(identity["username"]),
            email=identity.get("email"),
            display_name=identity.get("display_name"),
            auth_provider=str(identity.get("auth_provider") or f"saml:{provider_id}"),
            external_id=str(identity["external_id"]),
            role=str(identity.get("role") or "viewer"),
            allowed_namespaces=identity.get("allowed_namespaces"),
        )
        session_record, refresh_token = create_session_for_user(
            int(user["id"]),
            auth_provider=str(user.get("auth_provider") or f"saml:{provider_id}"),
            ip_address=request_client_ip(raw_request),
            user_agent=raw_request.headers.get("user-agent"),
            ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    redirect_path = sanitize_redirect_path(str(identity.get("next") or "/"))
    separator = "&" if "?" in redirect_path else "?"
    response = RedirectResponse(
        url=f"{redirect_path}{separator}auth=success&provider={provider_id}",
        status_code=status.HTTP_302_FOUND,
    )
    set_refresh_cookie(response, refresh_token)
    clear_oidc_transaction_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.saml-login",
        principal=principal,
        detail={"provider": provider_id},
        ip_address=request_client_ip(raw_request),
    )
    return response


@router.get("/auth/saml/metadata/{provider_id}")
def get_saml_metadata(provider_id: str, raw_request: Request) -> Response:
    if get_saml_provider(provider_id=provider_id) is None:
        raise HTTPException(status_code=404, detail=f"SAML provider '{provider_id}' is not configured")
    try:
        metadata_xml = saml_metadata_xml(provider_id, public_base_url(raw_request))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=metadata_xml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Skills Catalog
# ---------------------------------------------------------------------------

SKILLS_CATALOG_PATH = os.getenv("SKILLS_CATALOG_PATH", "/data/skills-catalog.json")
_SKILLS_CATALOG_CACHE: list[dict[str, Any]] | None = None
_MCP_SIDECAR_CATALOG_CACHE: dict[str, dict[str, Any]] | None = None

MCP_TOOL_CATEGORY_KEY_MAP: dict[str, str] = {
    "code-exec": "codeExec",
    "web-search": "webSearch",
    "documents": "documents",
    "browser": "browser",
    "database": "database",
    "git": "git",
    "kubernetes": "kubernetes",
    "messaging": "messaging",
    "rag": "rag",
}


def _load_skills_catalog() -> list[dict[str, Any]]:
    global _SKILLS_CATALOG_CACHE
    if _SKILLS_CATALOG_CACHE is not None:
        return _SKILLS_CATALOG_CACHE

    env_json = os.getenv("SKILLS_CATALOG_JSON", "").strip()
    if env_json:
        try:
            data = json.loads(env_json)
            if isinstance(data, list):
                _SKILLS_CATALOG_CACHE = data
                logger.info("Loaded skills catalog from SKILLS_CATALOG_JSON env (%d skills)", len(data))
                return _SKILLS_CATALOG_CACHE
        except json.JSONDecodeError:
            logger.warning("SKILLS_CATALOG_JSON env is not valid JSON; falling back to file.")

    if os.path.isfile(SKILLS_CATALOG_PATH):
        with open(SKILLS_CATALOG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            _SKILLS_CATALOG_CACHE = data
            logger.info("Loaded skills catalog from %s (%d skills)", SKILLS_CATALOG_PATH, len(data))
            return _SKILLS_CATALOG_CACHE

    _SKILLS_CATALOG_CACHE = []
    logger.info("No skills catalog found; catalog endpoints will return empty results.")
    return _SKILLS_CATALOG_CACHE


def _load_mcp_sidecar_catalog() -> dict[str, dict[str, Any]]:
    global _MCP_SIDECAR_CATALOG_CACHE
    if _MCP_SIDECAR_CATALOG_CACHE is not None:
        return _MCP_SIDECAR_CATALOG_CACHE

    raw = os.getenv("MCP_SIDECAR_CATALOG_JSON", "").strip()
    if not raw:
        _MCP_SIDECAR_CATALOG_CACHE = {}
        return _MCP_SIDECAR_CATALOG_CACHE

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("MCP_SIDECAR_CATALOG_JSON env is not valid JSON; tool image metadata will be unavailable.")
        _MCP_SIDECAR_CATALOG_CACHE = {}
        return _MCP_SIDECAR_CATALOG_CACHE

    if not isinstance(data, dict):
        logger.warning("MCP_SIDECAR_CATALOG_JSON env is not a JSON object; tool image metadata will be unavailable.")
        _MCP_SIDECAR_CATALOG_CACHE = {}
        return _MCP_SIDECAR_CATALOG_CACHE

    normalized: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key] = value
    _MCP_SIDECAR_CATALOG_CACHE = normalized
    return _MCP_SIDECAR_CATALOG_CACHE


def _resolve_sidecar_catalog_entry(tool_id: str) -> dict[str, Any] | None:
    catalog = _load_mcp_sidecar_catalog()
    entry = catalog.get(tool_id)
    if not isinstance(entry, dict):
        mapped_key = MCP_TOOL_CATEGORY_KEY_MAP.get(tool_id, tool_id)
        entry = catalog.get(mapped_key)
    return entry if isinstance(entry, dict) else None


def _resolve_sidecar_image(tool_id: str) -> str | None:
    entry = _resolve_sidecar_catalog_entry(tool_id)
    if entry is None:
        return None
    image = entry.get("image")
    return image if isinstance(image, str) and image.strip() else None


def _resolve_sidecar_port(tool_id: str, fallback_port: int) -> int:
    entry = _resolve_sidecar_catalog_entry(tool_id)
    if entry is None:
        return fallback_port

    port = entry.get("port")
    if isinstance(port, bool):
        return fallback_port
    if isinstance(port, int) and 1 <= port <= 65535:
        return port
    if isinstance(port, str):
        port_text = port.strip()
        if port_text.isdigit():
            normalized_port = int(port_text)
            if 1 <= normalized_port <= 65535:
                return normalized_port
    return fallback_port


MCP_TOOL_CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "code-exec",
        "name": "Code Execution",
        "description": "Run Python, Bash, and Node.js code in a sandboxed environment.",
        "icon": "terminal",
        "default_port": 8090,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "web-search",
        "name": "Web Search",
        "description": "Search the web, fetch URLs, and extract text content.",
        "icon": "globe",
        "default_port": 8091,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "documents",
        "name": "PDF & Office",
        "description": "Read, create, and manipulate PDF, DOCX, XLSX, and PPTX files.",
        "icon": "file-text",
        "default_port": 8092,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "browser",
        "name": "Browser Automation",
        "description": "Browse pages, take screenshots, click elements, and fill forms.",
        "icon": "monitor",
        "default_port": 8093,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "database",
        "name": "Database",
        "description": "Query SQL databases, list tables, and describe schemas.",
        "icon": "database",
        "default_port": 8094,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "git",
        "name": "Git & GitHub",
        "description": "Clone repos, view diffs, create commits, and interact with GitHub API.",
        "icon": "git-branch",
        "default_port": 8095,
        "credential_type": "git",
        "config_schema": [
            {
                "key": "repo_url",
                "label": "Repository URL",
                "type": "text",
                "placeholder": "https://github.com/org/repo.git",
                "required": True,
                "group": "repository",
                "help": "HTTPS or SSH URL of the Git repository to clone into the sandbox",
            },
            {
                "key": "default_branch",
                "label": "Default Branch",
                "type": "text",
                "placeholder": "main",
                "group": "repository",
            },
            {
                "key": "push_policy",
                "label": "Push Policy",
                "type": "select",
                "options": [
                    {"value": "after-each-commit", "label": "After Each Commit"},
                    {"value": "end-of-session", "label": "End of Session"},
                    {"value": "on-approval", "label": "On Approval"},
                    {"value": "never", "label": "Never"},
                ],
                "default": "end-of-session",
                "group": "repository",
            },
            {
                "key": "auth_method",
                "label": "Authentication Method",
                "type": "select",
                "options": [
                    {"value": "token", "label": "Personal Access Token"},
                    {"value": "basic", "label": "Username & Password"},
                    {"value": "ssh", "label": "SSH Key"},
                ],
                "default": "token",
                "group": "credentials",
            },
            {
                "key": "token",
                "label": "Access Token",
                "type": "password",
                "placeholder": "ghp_...",
                "group": "credentials",
                "is_credential": True,
                "visible_when": {"field": "auth_method", "values": ["token"]},
            },
            {
                "key": "username",
                "label": "Username",
                "type": "text",
                "group": "credentials",
                "is_credential": True,
                "visible_when": {"field": "auth_method", "values": ["basic"]},
            },
            {
                "key": "password",
                "label": "Password",
                "type": "password",
                "group": "credentials",
                "is_credential": True,
                "visible_when": {"field": "auth_method", "values": ["basic"]},
            },
            {
                "key": "ssh_private_key",
                "label": "SSH Private Key",
                "type": "textarea",
                "placeholder": "-----BEGIN OPENSSH PRIVATE KEY-----",
                "group": "credentials",
                "is_credential": True,
                "visible_when": {"field": "auth_method", "values": ["ssh"]},
            },
        ],
    },
    {
        "id": "kubernetes",
        "name": "Kubernetes & Cloud",
        "description": "List pods, get logs, apply manifests, and manage cluster resources.",
        "icon": "server",
        "default_port": 8096,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "messaging",
        "name": "Email & Messaging",
        "description": "Send emails and Slack messages, list conversations.",
        "icon": "mail",
        "default_port": 8097,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "rag",
        "name": "RAG & Vector Search",
        "description": "Index documents, perform semantic search, and retrieve context.",
        "icon": "search",
        "default_port": 8098,
        "config_schema": [],
        "credential_type": None,
    },
]

MCP_HUB_SERVERS: list[dict[str, Any]] = [
    {
        "id": "github",
        "name": "GitHub",
        "description": "Shared GitHub API access via the platform MCP hub.",
        "icon": "git-branch",
        "credential_type": "github",
        "config_schema": [
            {
                "key": "token",
                "label": "GitHub Personal Access Token",
                "type": "password",
                "placeholder": "ghp_...",
                "required": True,
                "group": "credentials",
                "is_credential": True,
                "help": "A GitHub PAT with appropriate scopes for the repositories you want to access.",
            },
        ],
    },
]

# ── MCP Registry ── comprehensive catalog of all known MCP servers ──

MCP_REGISTRY: list[dict[str, Any]] = [
    # ── Remote-native servers (vendor-hosted, zero containers) ──
    {
        "id": "github-remote",
        "name": "GitHub MCP",
        "description": "Access GitHub repos, issues, PRs, code search, and actions via GitHub's hosted MCP endpoint.",
        "icon": "git-branch",
        "category": "developer",
        "transport": "remote",
        "endpoint": "https://api.githubcopilot.com/mcp/",
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["git", "code", "issues", "pull-requests"],
        "tools_count": 35,
        "docs_url": "https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md",
        "repository_url": "https://github.com/github/github-mcp-server",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "GitHub-hosted remote",
        "connection_notes": "The hosted GitHub endpoint works with PAT auth today. GitHub Enterprise Cloud with data residency uses a different copilot-api.<subdomain>.ghe.com endpoint.",
        "config_schema": [
            {"key": "token", "label": "GitHub PAT", "type": "password", "placeholder": "ghp_...", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "context7",
        "name": "Context7",
        "description": "Up-to-date documentation and code examples for any library, pulled from source. Prevents hallucinated APIs.",
        "icon": "book-open",
        "category": "developer",
        "transport": "remote",
        "endpoint": "https://mcp.context7.com/mcp",
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["documentation", "libraries", "code-examples"],
        "tools_count": 2,
        "docs_url": "https://context7.com/docs/resources/all-clients",
        "repository_url": "https://github.com/upstash/context7",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Context7 works without auth, but the vendor recommends an API key for higher rate limits in supported clients.",
        "auth_header_name": "CONTEXT7_API_KEY",
        "config_schema": [
            {"key": "api_key", "label": "Context7 API Key", "type": "password", "required": False, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "microsoft-learn",
        "name": "Microsoft Learn",
        "description": "Trusted Microsoft documentation and code samples from the official Learn MCP endpoint.",
        "icon": "book-open",
        "category": "developer",
        "transport": "remote",
        "endpoint": "https://learn.microsoft.com/api/mcp",
        "auth_type": "none",
        "enabled": True,
        "tags": ["documentation", "microsoft", "azure", "code-samples"],
        "tools_count": 3,
        "tool_names": ["microsoft_docs_search", "microsoft_docs_fetch", "microsoft_code_sample_search"],
        "docs_url": "https://learn.microsoft.com/en-us/training/support/mcp",
        "repository_url": "https://github.com/MicrosoftDocs/mcp",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "The Learn endpoint is public. A plain browser-style GET may return 405 even though the MCP server is healthy; connect with a real MCP client over Streamable HTTP.",
        "config_schema": [],
    },
    {
        "id": "brave-search",
        "name": "Brave Search",
        "description": "Web and local search using Brave's Search API with privacy-focused results.",
        "icon": "globe",
        "category": "search",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["web-search", "local-search", "news"],
        "tools_count": 2,
        "config_schema": [
            {"key": "api_key", "label": "Brave API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "firecrawl",
        "name": "Firecrawl",
        "description": "Web scraping, crawling, and content extraction. Convert any website to clean markdown or structured data.",
        "icon": "globe",
        "category": "search",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["web-scraping", "crawling", "extraction"],
        "tools_count": 14,
        "tool_names": [
            "firecrawl_scrape",
            "firecrawl_batch_scrape",
            "firecrawl_check_batch_status",
            "firecrawl_map",
            "firecrawl_search",
            "firecrawl_crawl",
            "firecrawl_check_crawl_status",
            "firecrawl_extract",
            "firecrawl_agent",
            "firecrawl_agent_status",
            "firecrawl_browser_create",
            "firecrawl_browser_execute",
            "firecrawl_browser_list",
            "firecrawl_browser_delete",
        ],
        "docs_url": "https://github.com/firecrawl/firecrawl-mcp-server",
        "repository_url": "https://github.com/firecrawl/firecrawl-mcp-server",
        "protocol_label": "stdio or self-hosted Streamable HTTP",
        "deployment_model": "Self-hosted or local bridge",
        "suggested_endpoint": "http://localhost:3000/mcp",
        "connection_notes": "The official package runs over stdio by default and can expose a local Streamable HTTP endpoint at http://localhost:3000/mcp. No vendor-hosted default MCP endpoint is published in the docs.",
        "config_schema": [
            {"key": "api_key", "label": "Firecrawl API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "sentry",
        "name": "Sentry (Self-hosted / local)",
        "description": "Run Sentry's MCP server locally or against self-hosted Sentry with token-based auth.",
        "icon": "alert-triangle",
        "category": "observability",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["errors", "monitoring", "debugging", "stack-traces"],
        "tools_count": 8,
        "docs_url": "https://docs.sentry.io/product/sentry-mcp/",
        "repository_url": "https://github.com/getsentry/sentry-mcp",
        "protocol_label": "Local stdio or self-hosted HTTP",
        "deployment_model": "Self-hosted or local bridge",
        "connection_notes": "Use this entry when you run the open-source MCP server yourself for self-hosted Sentry or local stdio workflows. The official sentry.io hosted endpoint is listed separately.",
        "config_schema": [
            {"key": "token", "label": "Sentry Auth Token", "type": "password", "required": True, "group": "credentials", "is_credential": True},
            {"key": "organization", "label": "Organization Slug", "type": "text", "required": True, "group": "connection"},
        ],
    },
    {
        "id": "sentry-remote",
        "name": "Sentry Cloud",
        "description": "Official Sentry-hosted MCP endpoint for sentry.io with OAuth login and optional org/project scoping.",
        "icon": "alert-triangle",
        "category": "observability",
        "transport": "remote",
        "endpoint": "https://mcp.sentry.dev/mcp",
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["errors", "monitoring", "debugging", "stack-traces", "oauth"],
        "tools_count": 8,
        "docs_url": "https://docs.sentry.io/product/sentry-mcp/",
        "repository_url": "https://github.com/getsentry/sentry-mcp",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "The hosted sentry.io endpoint uses OAuth and supports scoped URLs like /mcp/<org>/<project>. Self-hosted Sentry still requires the local stdio server.",
        "config_schema": [],
    },
    {
        "id": "linear",
        "name": "Linear",
        "description": "Manage issues, projects, and cycles in Linear. Create, update, search, and comment on issues.",
        "icon": "layout-list",
        "category": "project-management",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["issues", "project-management", "agile", "tracking"],
        "tools_count": 12,
        "config_schema": [
            {"key": "api_key", "label": "Linear API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "atlassian-rovo",
        "name": "Atlassian Rovo",
        "description": "Official Atlassian-hosted MCP endpoint for Jira, Confluence, Bitbucket, and Compass workflows.",
        "icon": "layout-list",
        "category": "project-management",
        "transport": "remote",
        "endpoint": "https://mcp.atlassian.com/v1/mcp",
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["jira", "confluence", "bitbucket", "compass", "project-management"],
        "tools_count": 20,
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Atlassian's hosted MCP endpoint supports Jira, Confluence, Bitbucket, and Compass. OAuth is the default interactive path, while service-account style bearer tokens are suitable for headless saved connections.",
        "config_schema": [
            {"key": "token", "label": "Atlassian Access Token", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "slack",
        "name": "Slack",
        "description": "Read and send messages, manage channels, search history, and interact with Slack workspaces.",
        "icon": "message-square",
        "category": "communication",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["messaging", "channels", "team-communication"],
        "tools_count": 10,
        "config_schema": [
            {"key": "token", "label": "Slack Bot Token", "type": "password", "placeholder": "xoxb-...", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "notion",
        "name": "Notion (Self-hosted)",
        "description": "Open-source Notion API MCP server for self-hosted stdio or Streamable HTTP deployments.",
        "icon": "file-text",
        "category": "productivity",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["wiki", "documents", "databases", "knowledge-base"],
        "tools_count": 22,
        "docs_url": "https://github.com/makenotion/notion-mcp-server",
        "repository_url": "https://github.com/makenotion/notion-mcp-server",
        "protocol_label": "stdio or self-hosted Streamable HTTP",
        "deployment_model": "Self-hosted or local bridge",
        "connection_notes": "This entry is for the open-source Notion server that you run yourself. The official hosted Notion MCP endpoint is listed separately below.",
        "config_schema": [
            {"key": "token", "label": "Notion Integration Token", "type": "password", "placeholder": "ntn_...", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "notion-remote",
        "name": "Notion Cloud",
        "description": "Official Notion-hosted MCP endpoint for workspace search, content fetch, comments, views, and page operations.",
        "icon": "file-text",
        "category": "productivity",
        "transport": "remote",
        "endpoint": "https://mcp.notion.com/mcp",
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["wiki", "documents", "databases", "knowledge-base", "oauth"],
        "tools_count": 18,
        "tool_names": [
            "search",
            "fetch",
            "create-page",
            "update-page",
            "move-page",
            "duplicate-page",
            "create-database",
            "update-data-source",
            "create-view",
            "update-view",
            "query-data-sources",
            "query-database-view",
            "add-comment",
            "get-comments",
            "get-teams",
            "list-users",
            "get-current-user",
            "get-bot-info",
        ],
        "docs_url": "https://developers.notion.com/guides/mcp/get-started-with-mcp",
        "repository_url": "https://github.com/makenotion/notion-mcp-server",
        "protocol_label": "Streamable HTTP or SSE",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Official hosted Notion MCP uses OAuth and also exposes a legacy SSE endpoint for older clients. Save the connection once, supply your Notion OAuth app credentials, and complete the browser sign-in from the MCP page.",
        "oauth_authorization_url": "https://api.notion.com/v1/oauth/authorize",
        "oauth_token_url": "https://api.notion.com/v1/oauth/token",
        "oauth_token_auth_method": "client_secret_basic",
        "oauth_extra_authorize_params": {"owner": "user"},
        "config_schema": [
            {"key": "client_id", "label": "OAuth Client ID", "type": "text", "required": True, "group": "connection"},
            {"key": "client_secret", "label": "OAuth Client Secret", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    # ── Shared Hub servers (deployed centrally in mcp-hub namespace) ──
    {
        "id": "github-hub",
        "name": "GitHub (Hub)",
        "description": "Shared GitHub API access deployed in the platform MCP hub namespace. Central management for all agents.",
        "icon": "git-branch",
        "category": "developer",
        "transport": "hub",
        "hub_server_name": "github",
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["git", "code", "issues", "pull-requests"],
        "tools_count": 35,
        "config_schema": [
            {"key": "token", "label": "GitHub PAT", "type": "password", "placeholder": "ghp_...", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "postgres-hub",
        "name": "PostgreSQL (Hub)",
        "description": "Shared read-only PostgreSQL access deployed in the MCP hub. Query tables, list schemas, describe databases.",
        "icon": "database",
        "category": "data",
        "transport": "hub",
        "hub_server_name": "postgres-readonly",
        "auth_type": "connection_string",
        "enabled": True,
        "tags": ["sql", "database", "postgres", "read-only"],
        "tools_count": 5,
        "config_schema": [
            {"key": "connection_string", "label": "PostgreSQL Connection String", "type": "password", "placeholder": "postgresql://user:pass@host:5432/db", "required": True, "group": "connection", "is_credential": True},
        ],
    },
    # ── Sidecar servers (run as containers in the agent pod) ──
    {
        "id": "playwright-sidecar",
        "name": "Playwright Browser",
        "description": "Full browser automation with Playwright. Navigate pages, take screenshots, click elements, fill forms, and extract content.",
        "icon": "monitor",
        "category": "browser",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["browser", "automation", "screenshots", "testing"],
        "tools_count": 18,
        "config_schema": [],
    },
    {
        "id": "filesystem-sidecar",
        "name": "Filesystem",
        "description": "Safe file system operations within a sandboxed workspace. Read, write, search, and manage files.",
        "icon": "folder",
        "category": "developer",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["files", "filesystem", "workspace"],
        "tools_count": 11,
        "config_schema": [],
    },
    {
        "id": "memory-sidecar",
        "name": "Memory & Knowledge Graph",
        "description": "Persistent memory with a knowledge graph backend. Store entities, relations, and retrieve context across sessions.",
        "icon": "brain",
        "category": "ai",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["memory", "knowledge-graph", "persistence", "context"],
        "tools_count": 7,
        "config_schema": [],
    },
    {
        "id": "puppeteer-sidecar",
        "name": "Puppeteer",
        "description": "Headless Chrome automation for web scraping, screenshot capture, and page interaction.",
        "icon": "monitor",
        "category": "browser",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["browser", "headless", "chrome", "scraping"],
        "tools_count": 9,
        "config_schema": [],
    },
    # ── Cloud & Infrastructure ──
    {
        "id": "azure-mcp",
        "name": "Azure MCP Server",
        "description": "276 tools across 57 Azure services including Compute, Storage, AI, DevOps, Networking, and more.",
        "icon": "cloud",
        "category": "cloud",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["azure", "cloud", "infrastructure", "devops"],
        "tools_count": 276,
        "docs_url": "https://learn.microsoft.com/azure/developer/azure-mcp-server/",
        "repository_url": "https://github.com/microsoft/mcp",
        "protocol_label": "stdio or self-hosted Streamable HTTP",
        "deployment_model": "Self-hosted remote preview",
        "connection_notes": "Azure publishes packages, IDE integrations, and a self-hosted remote preview for platforms like Foundry and Copilot Studio, but no shared vendor-hosted MCP endpoint is documented.",
        "config_schema": [
            {"key": "tenant_id", "label": "Azure Tenant ID", "type": "text", "required": True, "group": "connection"},
            {"key": "client_id", "label": "Client ID", "type": "text", "required": True, "group": "credentials"},
            {"key": "client_secret", "label": "Client Secret", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "aws-kb-retrieval",
        "name": "AWS Knowledge Base",
        "description": "Retrieve information from AWS Knowledge Bases using Amazon Bedrock Agent Runtime.",
        "icon": "cloud",
        "category": "cloud",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["aws", "knowledge-base", "bedrock", "rag"],
        "tools_count": 1,
        "config_schema": [
            {"key": "access_key", "label": "AWS Access Key", "type": "text", "required": True, "group": "credentials"},
            {"key": "secret_key", "label": "AWS Secret Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
            {"key": "region", "label": "AWS Region", "type": "text", "placeholder": "us-east-1", "required": True, "group": "connection"},
        ],
    },
    # ── Data & Analytics ──
    {
        "id": "qdrant",
        "name": "Qdrant Vector Search",
        "description": "Semantic vector search operations. Create collections, upsert points, and query with filters.",
        "icon": "search",
        "category": "data",
        "transport": "sidecar",
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["vector-search", "embeddings", "semantic", "rag"],
        "tools_count": 6,
        "config_schema": [
            {"key": "url", "label": "Qdrant URL", "type": "text", "placeholder": "http://qdrant:6333", "required": True, "group": "connection"},
            {"key": "api_key", "label": "Qdrant API Key", "type": "password", "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "sqlite",
        "name": "SQLite",
        "description": "Interact with SQLite databases. Run queries, describe schemas, and manage tables.",
        "icon": "database",
        "category": "data",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["sql", "database", "sqlite", "local"],
        "tools_count": 6,
        "config_schema": [
            {"key": "db_path", "label": "Database Path", "type": "text", "placeholder": "/data/mydb.sqlite", "required": True, "group": "connection"},
        ],
    },
    # ── DevOps & CI/CD ──
    {
        "id": "docker",
        "name": "Docker",
        "description": "Manage Docker containers, images, volumes and networks. Build, run, and inspect containers.",
        "icon": "box",
        "category": "devops",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["docker", "containers", "images", "devops"],
        "tools_count": 15,
        "config_schema": [],
    },
    {
        "id": "kubernetes-mcp",
        "name": "Kubernetes",
        "description": "Full Kubernetes cluster operations. Get pods, logs, apply manifests, scale deployments, and manage resources.",
        "icon": "server",
        "category": "devops",
        "transport": "sidecar",
        "auth_type": "kubeconfig",
        "enabled": True,
        "tags": ["kubernetes", "k8s", "cluster", "pods", "deployments"],
        "tools_count": 20,
        "config_schema": [],
    },
    # ── Communication ──
    {
        "id": "gmail",
        "name": "Gmail",
        "description": "Read, send, search, and manage emails via Gmail API with OAuth2 authentication.",
        "icon": "mail",
        "category": "communication",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["email", "gmail", "google"],
        "tools_count": 8,
        "docs_url": "https://developers.google.com/gmail/api/guides",
        "connection_notes": "Use this entry with your own Gmail MCP deployment endpoint. Save the endpoint URL, register a Google OAuth app with this gateway as the redirect target, and complete the browser sign-in from the MCP page.",
        "oauth_authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "oauth_token_url": "https://oauth2.googleapis.com/token",
        "oauth_scopes": [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        "oauth_extra_authorize_params": {
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent"
        },
        "config_schema": [
            {"key": "client_id", "label": "OAuth Client ID", "type": "text", "required": True, "group": "credentials"},
            {"key": "client_secret", "label": "OAuth Client Secret", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "discord",
        "name": "Discord",
        "description": "Interact with Discord servers. Read messages, send messages, manage channels, and respond to events.",
        "icon": "message-square",
        "category": "communication",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["messaging", "discord", "community"],
        "tools_count": 7,
        "config_schema": [
            {"key": "token", "label": "Discord Bot Token", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    # ── Design & Content ──
    {
        "id": "figma",
        "name": "Figma",
        "description": "Official Figma-hosted MCP server for design context, screenshots, Code Connect, and write-to-canvas workflows.",
        "icon": "palette",
        "category": "design",
        "transport": "remote",
        "endpoint": "https://mcp.figma.com/mcp",
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["design", "figma", "ui", "components", "design-systems"],
        "tools_count": 16,
        "tool_names": [
            "get_design_context",
            "generate_figma_design",
            "get_variable_defs",
            "get_code_connect_map",
            "add_code_connect_map",
            "get_code_connect_suggestions",
            "send_code_connect_mappings",
            "get_screenshot",
            "create_design_system_rules",
            "get_metadata",
            "get_figjam",
            "generate_diagram",
            "whoami",
            "use_figma",
            "search_design_system",
            "create_new_file",
        ],
        "docs_url": "https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/",
        "repository_url": "https://github.com/figma/mcp-server-guide",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Figma only allows approved MCP clients to connect to the hosted endpoint. Interactive OAuth is required, and some write-to-canvas tools are available only in supported clients.",
        "config_schema": [],
    },
    # ── AI & ML ──
    {
        "id": "exa",
        "name": "Exa Search",
        "description": "AI-powered web search that understands meaning. Find similar content, get clean page extracts.",
        "icon": "sparkles",
        "category": "ai",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["search", "ai-search", "semantic", "content"],
        "tools_count": 3,
        "config_schema": [
            {"key": "api_key", "label": "Exa API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "tavily",
        "name": "Tavily Search",
        "description": "AI-optimized Tavily remote MCP endpoint for search, extract, map, and crawl workflows.",
        "icon": "globe",
        "category": "search",
        "transport": "remote",
        "endpoint": "https://mcp.tavily.com/mcp",
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["search", "ai-search", "research"],
        "tools_count": 4,
        "tool_names": ["tavily-search", "tavily-extract", "tavily-map", "tavily-crawl"],
        "docs_url": "https://github.com/tavily-ai/tavily-mcp",
        "repository_url": "https://github.com/tavily-ai/tavily-mcp",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Tavily supports either OAuth or API-key auth. kubesynapse uses Bearer-token API-key auth for headless saved connections.",
        "auth_header_name": "Authorization",
        "auth_header_prefix": "Bearer ",
        "config_schema": [
            {"key": "api_key", "label": "Tavily API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    # ── Monitoring & Observability ──
    {
        "id": "grafana",
        "name": "Grafana",
        "description": "Query dashboards, explore metrics, search logs, and manage alerts from Grafana.",
        "icon": "activity",
        "category": "observability",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["monitoring", "metrics", "dashboards", "alerts"],
        "tools_count": 8,
        "config_schema": [
            {"key": "url", "label": "Grafana URL", "type": "text", "placeholder": "https://grafana.example.com", "required": True, "group": "connection"},
            {"key": "api_key", "label": "Grafana API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "datadog",
        "name": "Datadog",
        "description": "Query metrics, search logs, manage monitors, and explore traces from Datadog.",
        "icon": "activity",
        "category": "observability",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["monitoring", "apm", "logs", "infrastructure"],
        "tools_count": 10,
        "config_schema": [
            {"key": "api_key", "label": "Datadog API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
            {"key": "app_key", "label": "Datadog App Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
            {"key": "site", "label": "Datadog Site", "type": "text", "placeholder": "datadoghq.com", "group": "connection"},
        ],
    },
    {
        "id": "netdata-cloud",
        "name": "Netdata Cloud",
        "description": "Official Netdata-hosted MCP endpoint for infrastructure troubleshooting and observability workflows.",
        "icon": "activity",
        "category": "observability",
        "transport": "remote",
        "endpoint": "https://app.netdata.cloud/api/v1/mcp",
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["observability", "metrics", "infrastructure", "troubleshooting"],
        "tools_count": 6,
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Netdata Cloud uses bearer-token authentication against the hosted MCP endpoint. Use this entry for hosted Netdata Cloud troubleshooting rather than self-hosted collectors.",
        "config_schema": [
            {"key": "token", "label": "Netdata Cloud Token", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
]

# ── MCP Profiles ── curated presets for common use cases ──

MCP_PROFILES: list[dict[str, Any]] = [
    {
        "id": "developer-essentials",
        "name": "Developer Essentials",
        "description": "Core toolkit for software development: GitHub access, code documentation, browser testing, and filesystem operations.",
        "icon": "code",
        "color": "sky",
        "servers": ["github-remote", "context7", "playwright-sidecar", "filesystem-sidecar"],
        "tags": ["development", "recommended"],
    },
    {
        "id": "cloud-ops",
        "name": "Cloud Operations",
        "description": "Full-stack infrastructure management with Azure, Kubernetes, Docker, and observability tools.",
        "icon": "cloud",
        "color": "violet",
        "servers": ["azure-mcp", "kubernetes-mcp", "docker", "grafana", "netdata-cloud", "sentry"],
        "tags": ["infrastructure", "devops", "monitoring"],
    },
    {
        "id": "data-science",
        "name": "Data & Analytics",
        "description": "Database access, vector search, and knowledge retrieval for data-intensive workflows.",
        "icon": "database",
        "color": "emerald",
        "servers": ["postgres-hub", "sqlite", "qdrant", "exa"],
        "tags": ["data", "analytics", "ml"],
    },
    {
        "id": "research-writer",
        "name": "Research & Writing",
        "description": "Web research, content retrieval, documentation lookup, and AI-powered search for writing and analysis tasks.",
        "icon": "book-open",
        "color": "amber",
        "servers": ["brave-search", "tavily", "context7", "firecrawl", "notion"],
        "tags": ["research", "writing", "content"],
    },
    {
        "id": "team-collaboration",
        "name": "Team Collaboration",
        "description": "Connect with your team through Slack, Linear, email, and knowledge bases like Notion.",
        "icon": "users",
        "color": "rose",
        "servers": ["slack", "linear", "atlassian-rovo", "notion", "gmail"],
        "tags": ["communication", "project-management", "team"],
    },
    {
        "id": "full-stack",
        "name": "Full Stack",
        "description": "Everything included: development, cloud, data, communication, and research tools for maximum capability.",
        "icon": "layers",
        "color": "fuchsia",
        "servers": ["github-remote", "context7", "playwright-sidecar", "filesystem-sidecar", "azure-mcp", "kubernetes-mcp", "postgres-hub", "brave-search", "slack", "grafana"],
        "tags": ["everything", "maximum-capability"],
    },
]

MCP_REGISTRY_TOOL_NAMES: dict[str, list[str]] = {
    "github-remote": [
        "Search repositories",
        "Search code",
        "Read issues",
        "Create issues",
        "Read pull requests",
        "Create pull requests",
        "Review pull request files",
        "Trigger Actions workflows",
    ],
    "context7": [
        "Resolve library IDs",
        "Fetch library docs",
    ],
    "brave-search": [
        "Web search",
        "Local search",
    ],
    "firecrawl": [
        "Scrape page",
        "Crawl site",
        "Map site",
        "Extract structured data",
        "Search indexed pages",
        "Deep research",
    ],
    "sentry": [
        "Find issues",
        "Inspect issue details",
        "Read stack traces",
        "Query traces",
        "Search releases",
        "List projects",
        "Comment on issues",
        "Assign issues",
    ],
    "linear": [
        "Search issues",
        "Create issue",
        "Update issue",
        "Comment on issue",
        "List projects",
        "List cycles",
        "Search teams",
        "Create project",
    ],
    "slack": [
        "Search messages",
        "Read channel history",
        "Post message",
        "Reply in thread",
        "List channels",
        "Read channel info",
        "Lookup users",
        "Open direct message",
    ],
    "notion": [
        "Search pages",
        "Read page",
        "Create page",
        "Update page",
        "Search databases",
        "Query database",
        "Create database row",
        "Update database row",
    ],
    "github-hub": [
        "Search repositories",
        "Search code",
        "Read issues",
        "Create issues",
        "Read pull requests",
        "Create pull requests",
        "Review pull request files",
        "Trigger Actions workflows",
    ],
    "postgres-hub": [
        "List schemas",
        "List tables",
        "Describe table",
        "Run read-only query",
        "Explain query",
    ],
    "playwright-sidecar": [
        "Open page",
        "Click element",
        "Fill form",
        "Take screenshot",
        "Evaluate script",
        "Wait for selector",
        "Extract text",
        "Manage tabs",
    ],
    "filesystem-sidecar": [
        "List directory",
        "Read file",
        "Write file",
        "Edit file",
        "Create directory",
        "Move file",
        "Delete file",
        "Search workspace",
    ],
    "memory-sidecar": [
        "Store memory",
        "Search memories",
        "Read entities",
        "Write entities",
        "Link related facts",
        "Summarize context",
        "Pin memory",
    ],
    "puppeteer-sidecar": [
        "Open page",
        "Click element",
        "Fill form",
        "Take screenshot",
        "Evaluate script",
        "Extract text",
        "Generate PDF",
        "Manage tabs",
    ],
    "azure-mcp": [
        "List subscriptions",
        "Manage resource groups",
        "Inspect virtual machines",
        "Query storage accounts",
        "Deploy templates",
        "Manage Container Apps",
        "Read Azure Monitor metrics",
        "Work with Azure OpenAI resources",
    ],
    "aws-kb-retrieval": [
        "Retrieve knowledge base context",
    ],
    "qdrant": [
        "Create collection",
        "List collections",
        "Upsert points",
        "Query points",
        "Delete points",
        "Inspect collection",
    ],
    "sqlite": [
        "Open database",
        "List tables",
        "Describe table",
        "Run query",
        "Insert row",
        "Update row",
    ],
    "docker": [
        "List containers",
        "Inspect container",
        "View logs",
        "Build image",
        "Run container",
        "Stop container",
        "List images",
        "Manage networks",
    ],
    "kubernetes-mcp": [
        "List resources",
        "Read logs",
        "Describe resource",
        "Apply manifest",
        "Delete resource",
        "Scale workload",
        "Restart workload",
        "Inspect events",
    ],
    "gmail": [
        "Search mail",
        "Read message",
        "Send message",
        "Draft reply",
        "List threads",
        "Read attachments",
        "Label message",
        "Archive message",
    ],
    "discord": [
        "List guilds",
        "List channels",
        "Read messages",
        "Send message",
        "Reply in thread",
        "Manage channels",
        "Lookup members",
    ],
    "figma": [
        "Read file",
        "Inspect components",
        "Read design tokens",
        "Read frames",
        "Inspect styles",
    ],
    "exa": [
        "Search web",
        "Find similar pages",
        "Answer with citations",
    ],
    "tavily": [
        "Search web",
        "Deep research",
    ],
    "grafana": [
        "List dashboards",
        "Read dashboard",
        "Query metrics",
        "Search logs",
        "Inspect traces",
        "List alerts",
        "Read alert rule",
        "Explore datasources",
    ],
    "datadog": [
        "Query metrics",
        "Search logs",
        "Inspect traces",
        "List monitors",
        "Read monitor",
        "Manage downtime",
        "Query events",
        "Read dashboards",
    ],
}


def _build_mcp_registry_entry(entry: dict[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    tool_names = result.get("tool_names")
    if not isinstance(tool_names, list):
        tool_names = MCP_REGISTRY_TOOL_NAMES.get(str(result.get("id") or ""), [])
    result["tool_names"] = [str(name).strip() for name in tool_names if str(name).strip()]

    if result.get("transport") == "sidecar":
        tid = str(result.get("id", "")).replace("-sidecar", "")
        image = _resolve_sidecar_image(tid)
        if image:
            result["sidecar_image"] = image
        port = _resolve_sidecar_port(tid, 0)
        if port:
            result["sidecar_port"] = port

    transport = str(result.get("transport") or "").strip().lower()
    auth_type = str(result.get("auth_type") or "none").strip().lower()
    registry_endpoint = str(result.get("endpoint") or "").strip()
    config_schema = result.get("config_schema") if isinstance(result.get("config_schema"), list) else []

    for metadata_key in (
        "docs_url",
        "repository_url",
        "connection_notes",
        "auth_header_name",
        "suggested_endpoint",
        "oauth_authorization_url",
        "oauth_token_url",
    ):
        cleaned_value = str(result.get(metadata_key) or "").strip()
        if cleaned_value:
            result[metadata_key] = cleaned_value
        else:
            result.pop(metadata_key, None)
    if result.get("auth_header_prefix") is not None:
        result["auth_header_prefix"] = str(result.get("auth_header_prefix"))
    oauth_scopes = result.get("oauth_scopes") if isinstance(result.get("oauth_scopes"), list) else []
    cleaned_oauth_scopes = [str(scope).strip() for scope in oauth_scopes if str(scope).strip()]
    if cleaned_oauth_scopes:
        result["oauth_scopes"] = cleaned_oauth_scopes
    else:
        result.pop("oauth_scopes", None)
    oauth_extra_authorize_params = _trimmed_string_mapping(result.get("oauth_extra_authorize_params"))
    if oauth_extra_authorize_params:
        result["oauth_extra_authorize_params"] = oauth_extra_authorize_params
    else:
        result.pop("oauth_extra_authorize_params", None)
    oauth_extra_token_params = _trimmed_string_mapping(result.get("oauth_extra_token_params"))
    if oauth_extra_token_params:
        result["oauth_extra_token_params"] = oauth_extra_token_params
    else:
        result.pop("oauth_extra_token_params", None)
    oauth_token_auth_method = str(result.get("oauth_token_auth_method") or "").strip().lower()
    if oauth_token_auth_method in {"client_secret_post", "client_secret_basic", "none"}:
        result["oauth_token_auth_method"] = oauth_token_auth_method
    else:
        result.pop("oauth_token_auth_method", None)
    if "oauth_pkce" in result:
        result["oauth_pkce"] = bool(result.get("oauth_pkce"))

    protocol_label = str(result.get("protocol_label") or "").strip()
    if not protocol_label:
        if transport == "remote":
            protocol_label = "Streamable HTTP"
        elif transport == "hub":
            protocol_label = "Cluster service HTTP"
        elif transport == "sidecar":
            protocol_label = "Pod-local HTTP"
    if protocol_label:
        result["protocol_label"] = protocol_label

    deployment_model = str(result.get("deployment_model") or "").strip()
    if not deployment_model:
        if transport == "remote":
            deployment_model = "Vendor-hosted remote" if registry_endpoint else "Self-hosted remote"
        elif transport == "hub":
            deployment_model = "Shared hub service"
        elif transport == "sidecar":
            deployment_model = "Per-agent sidecar"
    if deployment_model:
        result["deployment_model"] = deployment_model

    if transport == "remote":
        if auth_type == "oauth":
            oauth_supported, oauth_reason = _saved_oauth_support(result)
            if not oauth_supported:
                result.update(
                    {
                        "support_level": "planned",
                        "attachable": False,
                        "status_reason": oauth_reason
                        or "This OAuth-backed MCP entry still needs provider metadata before kubesynapse can drive the sign-in flow.",
                    }
                )
                return result
            result.update(
                {
                    "support_level": "ready" if registry_endpoint else "limited",
                    "attachable": True,
                    "status_reason": (
                        "Attachable after you save the connection and complete browser-based OAuth once from the MCP page. kubesynapse stores the resulting token on the saved connection and reuses it for runtime headers."
                        if registry_endpoint
                        else "Attachable after you save the connection, provide the endpoint URL for your own deployment, and complete browser-based OAuth once from the MCP page."
                    ),
                }
            )
            return result
        if auth_type == "kubeconfig":
            result.update(
                {
                    "support_level": "planned",
                    "attachable": False,
                    "status_reason": "Kubeconfig-backed remote MCP flows still need runtime-specific credential mounting before they can be attached to agents.",
                }
            )
            return result
        if registry_endpoint:
            result.update(
                {
                    "support_level": "ready",
                    "attachable": True,
                    "status_reason": "Attachable with a saved namespace-scoped connection. The published remote MCP endpoint is prefilled from the registry; add credentials or optional overrides only when needed.",
                }
            )
            return result
        result.update(
            {
                "support_level": "limited",
                "attachable": True,
                "status_reason": "No default endpoint is published for this MCP. Use it only when you run your own remote MCP deployment and can provide its endpoint URL and credentials.",
            }
        )
        return result

    if transport == "hub":
        support_level = "ready" if auth_type in {"none", "bearer", "api_key"} else "limited"
        result.update(
            {
                "support_level": support_level,
                "attachable": True,
                "status_reason": (
                    "Attachable through the shared MCP hub with saved namespace-scoped connection metadata and credentials."
                    if support_level == "ready"
                    else "Attachable through the shared MCP hub, but non-standard credential flows may still need adapter-specific follow-up."
                ),
            }
        )
        return result

    if transport == "sidecar":
        if not result.get("sidecar_image"):
            result.update(
                {
                    "support_level": "planned",
                    "attachable": False,
                    "status_reason": "This sidecar is listed in the registry, but no managed sidecar image is registered for it yet.",
                }
            )
            return result
        result.update(
            {
                "support_level": "ready",
                "attachable": True,
                "status_reason": (
                    "Attachable today as a managed per-agent sidecar. Saved connections preserve image, port, and per-sidecar configuration."
                    if config_schema
                    else "Attachable today as a managed per-agent sidecar."
                ),
            }
        )
        return result

    result.update(
        {
            "support_level": "planned",
            "attachable": False,
            "status_reason": "This MCP server has an unknown transport and is not attachable yet.",
        }
    )
    return result


def _build_mcp_registry_results() -> list[dict[str, Any]]:
    return [_build_mcp_registry_entry(entry) for entry in MCP_REGISTRY]
