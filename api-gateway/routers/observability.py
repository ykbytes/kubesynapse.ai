"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

import importlib
from typing import Any, cast

import trace_store

# Re-import all shared symbols from the gateway core
from _core import *
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

import routers.auth as auth_router
from routers.auth import (
    MCP_HUB_SERVERS,
    MCP_PROFILES,
    MCP_REGISTRY,
    MCP_TOOL_CATEGORIES,
    _build_mcp_registry_entry,
    _build_mcp_registry_results,
    _resolve_sidecar_image,
    _resolve_sidecar_port,
)

router = APIRouter(tags=["observability"])


def _observation_helpers() -> Any:
    """Load observation helper definitions from the admin router lazily.

    The observation CRUD/overview code was split across routers, but the shared
    validation constants and helper functions still live in `routers.admin`.
    Resolve them at call time to avoid a circular import during module import.
    """
    return importlib.import_module("routers.admin")

@router.get("/skills/catalog")
def get_skills_catalog(
    category: str | None = None,
    search: str | None = None,
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    del user
    catalog = auth_router._load_skills_catalog()
    results = catalog

    if category:
        category_lower = category.strip().lower()
        results = [s for s in results if s.get("category", "").lower() == category_lower]

    if search:
        search_lower = search.strip().lower()
        results = [
            s
            for s in results
            if search_lower in s.get("name", "").lower()
            or search_lower in s.get("description", "").lower()
            or search_lower in s.get("id", "").lower()
        ]

    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "description": s.get("description"),
            "category": s.get("category"),
            "source": s.get("source"),
            "license": s.get("license"),
            "instructions_preview": s.get("instructions_preview"),
            "allowed_mcp_servers": s.get("allowed_mcp_servers", []),
            "allowed_sandbox_tools": s.get("allowed_sandbox_tools", []),
            "bundled_assets": s.get("bundled_assets", []),
            "files": dict.fromkeys(s.get("files", {}).keys(), "") if isinstance(s.get("files"), dict) else {},
        }
        for s in results
    ]


@router.post("/skills/catalog/refresh")
def refresh_skills_catalog(
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Invalidate the in-memory skills catalog cache so the next read reloads from disk."""
    del user
    auth_router._SKILLS_CATALOG_CACHE = None
    reloaded = auth_router._load_skills_catalog()
    return {"refreshed": True, "count": len(reloaded)}


@router.get("/skills/catalog/{skill_id}")
def get_skill_detail(
    skill_id: str,
    user=Depends(verify_token),
) -> dict[str, Any]:
    del user
    catalog = auth_router._load_skills_catalog()
    for s in catalog:
        if s.get("id") == skill_id:
            return s
    raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found in catalog")


@router.get("/skills/tools")
def get_tool_categories(
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    del user
    return [
        {
            **tool,
            "default_port": _resolve_sidecar_port(str(tool.get("id", "")), int(tool.get("default_port", 0))),
            "sidecar_image": _resolve_sidecar_image(str(tool.get("id", ""))),
        }
        for tool in MCP_TOOL_CATEGORIES
    ]


@router.get("/mcp-hub/servers")
def get_mcp_hub_servers(
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return metadata about shared MCP hub servers available for agents."""
    del user
    return MCP_HUB_SERVERS


# ── MCP Registry & Management API ──


@router.get("/mcp/registry")
def get_mcp_registry(
    category: str | None = None,
    transport: str | None = None,
    search: str | None = None,
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return the full MCP server registry with optional filtering."""
    del user
    results = _build_mcp_registry_results()

    if category:
        cat_lower = category.strip().lower()
        results = [s for s in results if s.get("category", "").lower() == cat_lower]

    if transport:
        t_lower = transport.strip().lower()
        results = [s for s in results if s.get("transport", "").lower() == t_lower]

    if search:
        search_lower = search.strip().lower()
        results = [
            s
            for s in results
            if search_lower in s.get("name", "").lower()
            or search_lower in s.get("description", "").lower()
            or search_lower in s.get("id", "").lower()
            or any(search_lower in tag for tag in s.get("tags", []))
        ]

    return results


@router.get("/mcp/profiles")
def get_mcp_profiles(
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return curated MCP profiles (presets)."""
    del user
    registry_index = {s["id"]: s for s in _build_mcp_registry_results()}
    enriched = []
    for profile in MCP_PROFILES:
        resolved_servers = []
        attachable_servers = []
        blocked_servers = []
        total_tools = 0
        for sid in profile.get("servers", []):
            entry = registry_index.get(sid)
            if entry:
                resolved_entry = {
                    "id": sid,
                    "name": entry["name"],
                    "transport": entry["transport"],
                    "support_level": entry.get("support_level", "planned"),
                    "attachable": bool(entry.get("attachable")),
                    "status_reason": entry.get("status_reason"),
                }
                resolved_servers.append(resolved_entry)
                if resolved_entry["attachable"]:
                    attachable_servers.append(resolved_entry)
                else:
                    blocked_servers.append(resolved_entry)
                total_tools += entry.get("tools_count", 0)
        support_level = "planned"
        if attachable_servers and not blocked_servers:
            support_level = "ready"
        elif attachable_servers:
            support_level = "limited"
        enriched.append(
            {
                **profile,
                "resolved_servers": resolved_servers,
                "attachable_servers": attachable_servers,
                "blocked_servers": blocked_servers,
                "can_apply": bool(attachable_servers),
                "support_level": support_level,
                "total_tools": total_tools,
            }
        )
    return enriched


@router.get("/mcp/registry/{server_id}")
def get_mcp_server_detail(
    server_id: str,
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Return full detail for a single MCP registry entry."""
    del user
    for entry in MCP_REGISTRY:
        if entry["id"] == server_id:
            return _build_mcp_registry_entry(entry)
    raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found in registry.")


@router.get("/mcp/categories")
def get_mcp_categories(
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return all unique MCP categories with counts."""
    del user
    category_counts: dict[str, int] = {}
    for entry in MCP_REGISTRY:
        cat = entry.get("category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1
    return [{"id": cat, "name": cat.replace("-", " ").title(), "count": count} for cat, count in sorted(category_counts.items())]


@router.get("/mcp/stats")
def get_mcp_stats(
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Return aggregate MCP registry statistics."""
    del user
    transport_counts: dict[str, int] = {}
    total_tools = 0
    for entry in MCP_REGISTRY:
        t = entry.get("transport", "unknown")
        transport_counts[t] = transport_counts.get(t, 0) + 1
        total_tools += entry.get("tools_count", 0)
    return {
        "total_servers": len(MCP_REGISTRY),
        "total_tools": total_tools,
        "total_profiles": len(MCP_PROFILES),
        "by_transport": transport_counts,
        "categories": len({e.get("category", "other") for e in MCP_REGISTRY}),
    }


@router.get("/mcp/connections")
def get_mcp_connections(
    namespace: str = "default",
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    ensure_namespace_access(user, namespace)
    bindings_by_id = _list_mcp_connection_bindings(namespace)
    return [
        _serialize_saved_mcp_connection_record(record, binding_count=len(bindings_by_id.get(record["id"], [])))
        for record in list_mcp_connections(namespace)
    ]


@router.post("/mcp/connections", status_code=201)
def create_saved_mcp_connection(
    body: McpConnectionRequest,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    entry = _lookup_mcp_registry_entry(body.server_id)
    config = _normalize_mcp_connection_config(entry, body.config, source="body")
    credentials = _normalize_mcp_connection_credentials(entry, body.credentials, source="body")
    credential_metadata = _build_mcp_connection_credential_metadata(entry, configured_keys=set(credentials))
    created = create_mcp_connection(
        namespace=namespace,
        name=body.name,
        server_id=str(entry.get("id") or body.server_id),
        transport=str(entry.get("transport") or "remote"),
        auth_type=str(entry.get("auth_type") or "none"),
        config=config,
        credential_metadata=credential_metadata,
        validation_status="draft",
        validation_message="Saved but not validated yet.",
    )
    try:
        secret_name = _upsert_mcp_connection_secret(namespace, created["id"], credentials)
        validation_status = "draft"
        validation_message = "Saved but not validated yet."
        validation_detail: dict[str, Any] | None = None
        validated_at: datetime | None = None
        if body.validate_on_save:
            validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(
                {**created, "secret_name": secret_name, "credential_metadata": credential_metadata}
            )
            validated_at = datetime.now(UTC)
        updated = update_mcp_connection(
            namespace,
            created["id"],
            transport=str(entry.get("transport") or "remote"),
            auth_type=str(entry.get("auth_type") or "none"),
            config=config,
            credential_metadata=credential_metadata,
            secret_name=secret_name,
            validation_status=validation_status,
            validation_message=validation_message,
            validation_detail=validation_detail,
            last_validated_at=validated_at,
        )
    except Exception:
        delete_mcp_connection(namespace, created["id"])
        raise
    return _serialize_saved_mcp_connection_record(updated)


@router.get("/mcp/connections/{connection_id}")
def get_saved_mcp_connection(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace)
    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return _serialize_saved_mcp_connection_record(record, binding_count=len(bindings))


@router.patch("/mcp/connections/{connection_id}")
def update_saved_mcp_connection(
    connection_id: str,
    body: McpConnectionUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    existing = get_mcp_connection(namespace, connection_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")

    next_server_id = str(body.server_id or existing["server_id"]).strip()
    entry = _lookup_mcp_registry_entry(next_server_id)
    server_changed = next_server_id != str(existing.get("server_id") or "")

    config_source = body.config if body.config is not None else ({} if server_changed else existing.get("config") or {})
    config = _normalize_mcp_connection_config(entry, config_source, source="body")

    existing_configured_keys = set() if server_changed else _configured_credential_keys(existing.get("credential_metadata"))
    credentials = _normalize_mcp_connection_credentials(entry, body.credentials, source="body") if body.credentials is not None else {}
    configured_keys = existing_configured_keys | set(credentials)
    credential_metadata = _build_mcp_connection_credential_metadata(entry, configured_keys=configured_keys)

    existing_secret_name = str(existing.get("secret_name") or "").strip() or None
    existing_secret_values = {} if server_changed else _read_mcp_connection_secret_values(namespace, existing_secret_name)
    secret_name = existing_secret_name
    next_secret_values = dict(existing_secret_values)
    if server_changed and existing_secret_name:
        _delete_mcp_connection_secret(namespace, existing_secret_name)
        secret_name = None
        next_secret_values = {}
    if credentials:
        next_secret_values.update(credentials)

    should_reset_oauth_session = str(entry.get("auth_type") or "none").strip().lower() == "oauth" and (
        server_changed or body.config is not None or body.credentials is not None
    )
    if should_reset_oauth_session:
        next_secret_values = _clear_mcp_oauth_session_values(next_secret_values)

    if body.credentials is not None or should_reset_oauth_session:
        if next_secret_values:
            secret_name = _upsert_mcp_connection_secret(namespace, connection_id, next_secret_values)
        else:
            if existing_secret_name and not server_changed:
                _delete_mcp_connection_secret(namespace, existing_secret_name)
            secret_name = None

    validation_status = str((existing.get("validation") or {}).get("status") or "draft")
    validation_message = str((existing.get("validation") or {}).get("message") or "Saved but not validated yet.")
    validation_detail = (existing.get("validation") or {}).get("detail")
    validated_at_raw = (existing.get("validation") or {}).get("last_validated_at")
    validated_at: datetime | None = None
    if isinstance(validated_at_raw, str) and validated_at_raw:
        with contextlib.suppress(ValueError):
            validated_at = datetime.fromisoformat(validated_at_raw.replace("Z", "+00:00"))

    if server_changed or body.config is not None or body.credentials is not None:
        validation_status = "draft"
        validation_message = "Saved but not validated yet."
        validation_detail = None
        validated_at = None
    if body.validate_on_save:
        validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(
            {
                **existing,
                "id": connection_id,
                "name": body.name or existing.get("name"),
                "server_id": next_server_id,
                "transport": entry.get("transport"),
                "auth_type": entry.get("auth_type"),
                "config": config,
                "credential_metadata": credential_metadata,
                "secret_name": secret_name,
            }
        )
        validated_at = datetime.now(UTC)

    updated = update_mcp_connection(
        namespace,
        connection_id,
        name=body.name,
        transport=str(entry.get("transport") or "remote"),
        auth_type=str(entry.get("auth_type") or "none"),
        config=config,
        credential_metadata=credential_metadata,
        secret_name=secret_name,
        validation_status=validation_status,
        validation_message=validation_message,
        validation_detail=validation_detail if isinstance(validation_detail, dict) else None,
        last_validated_at=validated_at,
    )
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return _serialize_saved_mcp_connection_record(updated, binding_count=len(bindings))


@router.post("/mcp/connections/{connection_id}/validate")
def validate_saved_mcp_connection(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    existing = get_mcp_connection(namespace, connection_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")

    validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(existing)
    updated = update_mcp_connection(
        namespace,
        connection_id,
        validation_status=validation_status,
        validation_message=validation_message,
        validation_detail=validation_detail,
        last_validated_at=datetime.now(UTC),
    )
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return _serialize_saved_mcp_connection_record(updated, binding_count=len(bindings))


def _clean_expired_mcp_oauth_flows() -> None:
    now = datetime.now(UTC)
    expired_states = [
        state
        for state, flow in _MCP_OAUTH_PENDING_FLOWS.items()
        if _parse_iso_datetime(flow.get("expires_at")) and cast(datetime, _parse_iso_datetime(flow.get("expires_at"))) <= now
    ]
    for state in expired_states:
        _MCP_OAUTH_PENDING_FLOWS.pop(state, None)


def _mcp_oauth_callback_response(
    connection_id: str,
    *,
    status_value: str,
    message: str,
    restarted_agents: list[str] | None = None,
) -> Response:
    payload = json.dumps(
        {
            "type": "kubesynapse-mcp-oauth-result",
            "connectionId": connection_id,
            "status": status_value,
            "message": message,
            "restartedAgents": restarted_agents or [],
        }
    )
    title = "MCP OAuth connected" if status_value == "success" else "MCP OAuth failed"
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    html_body = f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>{safe_title}</title>
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <style>
      body {{ font-family: ui-sans-serif, system-ui, sans-serif; background: #0c1117; color: #f5f7fa; margin: 0; }}
      main {{ max-width: 32rem; margin: 12vh auto; padding: 2rem; border-radius: 1rem; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.04); }}
      h1 {{ margin: 0 0 0.75rem; font-size: 1.125rem; }}
      p {{ margin: 0; line-height: 1.6; color: rgba(245,247,250,0.82); }}
    </style>
  </head>
  <body>
    <main>
      <h1>{safe_title}</h1>
      <p>{safe_message}</p>
    </main>
    <script>
      (function() {{
        const payload = {payload};
        try {{
          if (window.opener && !window.opener.closed) {{
            window.opener.postMessage(payload, "*");
          }}
        }} catch (_error) {{}}
        try {{
          window.close();
        }} catch (_error) {{}}
      }})();
    </script>
  </body>
</html>"""
    return Response(content=html_body, media_type="text/html")


@router.post("/mcp/connections/{connection_id}/oauth/start")
def start_saved_mcp_connection_oauth(
    connection_id: str,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")

    entry = _lookup_mcp_registry_entry(str(record.get("server_id") or ""))
    if str(entry.get("auth_type") or "none").strip().lower() != "oauth":
        raise HTTPException(status_code=400, detail="This MCP connection does not use OAuth.")
    supported, support_reason = _saved_oauth_support(entry)
    if not supported:
        raise HTTPException(status_code=400, detail=support_reason or "OAuth is not configured for this MCP entry yet.")

    secret_values = _mcp_connection_secret_values_for_record(record)
    metadata = _mcp_oauth_entry_metadata(entry)
    redirect_uri = _mcp_oauth_redirect_uri(raw_request, connection_id)
    code_verifier = _mcp_oauth_code_verifier()
    state = uuid.uuid4().hex
    params = {
        "response_type": "code",
        "client_id": _mcp_oauth_client_id(record, entry, secret_values),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if metadata["scopes"]:
        params["scope"] = " ".join(metadata["scopes"])
    if bool(metadata["pkce"]):
        params["code_challenge"] = _mcp_oauth_code_challenge(code_verifier)
        params["code_challenge_method"] = "S256"
    params.update(metadata["authorize_params"])

    _clean_expired_mcp_oauth_flows()
    expires_at = datetime.now(UTC) + timedelta(seconds=_MCP_OAUTH_FLOW_TTL_SECONDS)
    _MCP_OAUTH_PENDING_FLOWS[state] = {
        "connection_id": connection_id,
        "namespace": namespace,
        "user_sub": str(user.get("sub") or "").strip(),
        "code_verifier": code_verifier,
        "expires_at": expires_at.isoformat(),
    }
    return {
        "authorization_url": f"{metadata['authorization_url']}?{urlencode(params)}",
        "expires_at": expires_at.isoformat(),
    }


@router.get("/mcp/connections/{connection_id}/oauth/callback")
async def complete_saved_mcp_connection_oauth(
    connection_id: str,
    raw_request: Request,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> Response:
    _clean_expired_mcp_oauth_flows()
    flow = _MCP_OAUTH_PENDING_FLOWS.get(state)
    if flow is None or str(flow.get("connection_id") or "") != connection_id:
        return _mcp_oauth_callback_response(
            connection_id,
            status_value="error",
            message="This OAuth sign-in session expired or no longer matches the saved connection.",
        )

    namespace = str(flow.get("namespace") or "default").strip() or "default"
    _MCP_OAUTH_PENDING_FLOWS.pop(state, None)
    if error:
        message = str(error_description or error).strip() or "OAuth provider rejected the sign-in request."
        return _mcp_oauth_callback_response(connection_id, status_value="error", message=message)

    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        return _mcp_oauth_callback_response(
            connection_id,
            status_value="error",
            message="The saved MCP connection was deleted before OAuth completed.",
        )

    entry = _lookup_mcp_registry_entry(str(record.get("server_id") or ""))
    secret_values = _mcp_connection_secret_values_for_record(record)
    try:
        token_url, headers, data = _build_mcp_oauth_token_request(
            entry,
            record,
            grant_type="authorization_code",
            secret_values=secret_values,
            code=code,
            redirect_uri=_mcp_oauth_redirect_uri(raw_request, connection_id),
            code_verifier=str(flow.get("code_verifier") or "").strip() or None,
        )
        # §security-R6: follow_redirects=False to prevent the OAuth
        # token endpoint from redirecting the api-gateway to an
        # internal address (SSRF). If the upstream returns 3xx, the
        # caller should re-submit with the new Location.
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False, verify=certifi.where()) as client:
            response = await client.post(token_url, data=data, headers=headers)
            if response.status_code in (301, 302, 303, 307, 308):
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"MCP OAuth token endpoint at {token_url} returned a "
                        f"redirect to {response.headers.get('Location')!r}; "
                        f"this is not allowed for security reasons. Update the "
                        f"registry entry with a non-redirecting token endpoint."
                    ),
                )
            response.raise_for_status()
            token_payload = response.json()
        token_bundle = _extract_mcp_oauth_token_bundle(token_payload, secret_values)
        secret_name, _merged_secret_values = _store_mcp_oauth_token_bundle(namespace, connection_id, secret_values, token_bundle)
        validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(
            {
                **record,
                "secret_name": secret_name,
            }
        )
        updated = update_mcp_connection(
            namespace,
            connection_id,
            secret_name=secret_name,
            validation_status=validation_status,
            validation_message=validation_message,
            validation_detail=validation_detail if isinstance(validation_detail, dict) else None,
            last_validated_at=datetime.now(UTC),
        )
        restarted_agents = _restart_bound_agents_for_mcp_connection(namespace, connection_id)
    except HTTPException as exc:
        return _mcp_oauth_callback_response(connection_id, status_value="error", message=str(exc.detail))
    except Exception as exc:
        logger.exception("Failed to complete MCP OAuth callback for %s/%s", namespace, connection_id)
        return _mcp_oauth_callback_response(
            connection_id,
            status_value="error",
            message=f"Failed to complete OAuth sign-in: {exc}",
        )

    message = "OAuth sign-in completed and the saved MCP connection is ready to use."
    if restarted_agents:
        message = f"OAuth sign-in completed. Restarted {len(restarted_agents)} bound agent(s) so they pick up the refreshed token."
    del updated
    return _mcp_oauth_callback_response(
        connection_id,
        status_value="success",
        message=message,
        restarted_agents=restarted_agents,
    )


@router.post("/mcp/connections/{connection_id}/oauth/refresh")
def refresh_saved_mcp_connection_oauth(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")

    entry = _lookup_mcp_registry_entry(str(record.get("server_id") or ""))
    if str(entry.get("auth_type") or "none").strip().lower() != "oauth":
        raise HTTPException(status_code=400, detail="This MCP connection does not use OAuth.")

    _refresh_mcp_connection_oauth_access_token_sync(record, entry)
    refreshed_record = get_mcp_connection(namespace, connection_id) or record
    validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(refreshed_record)
    updated = update_mcp_connection(
        namespace,
        connection_id,
        secret_name=str(refreshed_record.get("secret_name") or "").strip() or None,
        validation_status=validation_status,
        validation_message=validation_message,
        validation_detail=validation_detail if isinstance(validation_detail, dict) else None,
        last_validated_at=datetime.now(UTC),
    )
    _restart_bound_agents_for_mcp_connection(namespace, connection_id)
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return _serialize_saved_mcp_connection_record(updated, binding_count=len(bindings))


@router.get("/mcp/connections/{connection_id}/bindings")
def get_saved_mcp_connection_bindings(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    ensure_namespace_access(user, namespace)
    if get_mcp_connection(namespace, connection_id) is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return sorted(bindings, key=lambda item: (item.get("namespace", ""), item.get("agent_name", "")))


@router.delete("/mcp/connections/{connection_id}", response_model=DeleteResponse)
def delete_saved_mcp_connection(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> DeleteResponse:
    ensure_namespace_access(user, namespace, "operator")
    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    if bindings:
        bound_agents = ", ".join(sorted({str(item.get("agent_name") or "") for item in bindings if item.get("agent_name")}))
        raise HTTPException(
            status_code=409,
            detail=(
                f"MCP connection '{record['name']}' is still bound to {len(bindings)} agent(s): {bound_agents or 'unknown'}"
            ),
        )

    _delete_mcp_connection_secret(namespace, record.get("secret_name"))
    delete_mcp_connection(namespace, connection_id)
    return DeleteResponse(status="deleted", kind="mcp_connection", name=record["name"], namespace=namespace)


@router.get("/observability/overview")
def observability_overview(
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Aggregated observability dashboard data — targets, policies, reports, connectors."""
    ensure_namespace_access(user, namespace)
    from kubernetes import client as k8s_client

    helpers = _observation_helpers()
    custom_api = k8s_client.CustomObjectsApi()
    data: dict[str, Any] = {}

    for label, plural in helpers.OBSERVATION_PLURALS.items():
        try:
            items = custom_api.list_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural=plural,
            ).get("items", [])
            data[label] = items
        except Exception:
            data[label] = []

    # ----- Derive summary stats -----
    targets = data.get("targets", [])
    reports = data.get("reports", [])
    connectors = data.get("connectors", [])

    active_targets = sum(
        1 for t in targets
        if (t.get("status") or {}).get("phase") == "Active"
    )
    degraded_targets = sum(
        1 for t in targets
        if (t.get("status") or {}).get("phase") == "Degraded"
    )
    failed_targets = sum(
        1 for t in targets
        if (t.get("status") or {}).get("phase") == "Failed"
    )
    total_findings = sum(
        (r.get("status") or {}).get("findingsCount", 0) for r in reports
    )
    avg_health = 0
    scores = [
        (r.get("status") or {}).get("healthScore", -1) for r in reports
        if (r.get("status") or {}).get("healthScore") is not None
    ]
    valid_scores = [s for s in scores if s >= 0]
    if valid_scores:
        avg_health = round(sum(valid_scores) / len(valid_scores))

    ready_connectors = sum(
        1 for c in connectors
        if (c.get("status") or {}).get("ready") == "True"
    )

    # ----- Agent metrics summary (from K8s pod status) -----
    agent_pod_summary: dict[str, Any] = {"total": 0, "ready": 0, "notReady": 0}
    try:
        v1 = k8s_client.CoreV1Api()
        pods = v1.list_namespaced_pod(
            namespace=namespace,
            label_selector="kubesynapse.ai/managed-by=kubesynapse-operator",
        )
        agent_pod_summary["total"] = len(pods.items)
        for pod in pods.items:
            ready = all(
                cs.ready for cs in (pod.status.container_statuses or [])
            ) if pod.status and pod.status.container_statuses else False
            if ready:
                agent_pod_summary["ready"] += 1
            else:
                agent_pod_summary["notReady"] += 1
    except Exception:
        logger.warning("Failed to list agent pods for observability summary", exc_info=True)

    return {
        "summary": {
            "targets": {
                "total": len(targets),
                "active": active_targets,
                "degraded": degraded_targets,
                "failed": failed_targets,
            },
            "reports": {
                "total": len(reports),
                "totalFindings": total_findings,
                "avgHealthScore": avg_health,
            },
            "connectors": {
                "total": len(connectors),
                "ready": ready_connectors,
            },
            "policies": {
                "total": len(data.get("policies", [])),
            },
            "agents": agent_pod_summary,
        },
        "targets": [
            {
                "name": t["metadata"]["name"],
                "namespace": t["metadata"].get("namespace", namespace),
                "description": t.get("spec", {}).get("description", ""),
                "targetType": t.get("spec", {}).get("targetType", "unknown"),
                "connectorRef": t.get("spec", {}).get("connectorRef", ""),
                "policyRef": t.get("spec", {}).get("policyRef"),
                "endpoint": t.get("spec", {}).get("endpoint", ""),
                "scrapeInterval": t.get("spec", {}).get("scrapeInterval", "30s"),
                "phase": (t.get("status") or {}).get("phase", "Pending"),
                "lastScrapeTime": (t.get("status") or {}).get("lastScrapeTime"),
                "metricsCollected": (t.get("status") or {}).get("metricsCollected", 0),
                "connectorHealth": (t.get("status") or {}).get("connectorHealth", "Unknown"),
                "createdAt": t["metadata"].get("creationTimestamp", ""),
            }
            for t in targets
        ],
        "reports": [
            {
                "name": r["metadata"]["name"],
                "targetRef": r.get("spec", {}).get("targetRef", ""),
                "reportType": r.get("spec", {}).get("reportType", "anomaly"),
                "phase": (r.get("status") or {}).get("phase", "Pending"),
                "healthScore": (r.get("status") or {}).get("healthScore"),
                "findingsCount": (r.get("status") or {}).get("findingsCount", 0),
                "lastEvaluated": (r.get("status") or {}).get("lastEvaluated"),
                "findings": (r.get("status") or {}).get("findings", []),
                "summary": (r.get("status") or {}).get("summary", ""),
                "createdAt": r["metadata"].get("creationTimestamp", ""),
            }
            for r in reports
        ],
        "connectors": [
            {
                "name": c["metadata"]["name"],
                "description": c.get("spec", {}).get("description", ""),
                "image": c.get("spec", {}).get("image", ""),
                "protocol": c.get("spec", {}).get("protocol", "grpc"),
                "port": c.get("spec", {}).get("port", 9090),
                "capabilities": c.get("spec", {}).get("capabilities", []),
                "ready": (c.get("status") or {}).get("ready", "Unknown"),
                "lastHealthCheck": (c.get("status") or {}).get("lastHealthCheck"),
                "createdAt": c["metadata"].get("creationTimestamp", ""),
            }
            for c in connectors
        ],
        "policies": [
            {
                "name": p["metadata"]["name"],
                "description": p.get("spec", {}).get("description", ""),
                "retentionDays": p.get("spec", {}).get("retention", {}).get("days", 30),
                "anomalyEnabled": p.get("spec", {}).get("anomalyDetection", {}).get("enabled", False),
                "anomalyAlgorithm": p.get("spec", {}).get("anomalyDetection", {}).get("algorithm", "ensemble"),
                "alertRulesCount": len(p.get("spec", {}).get("alertRules", [])),
                "activeAlerts": (p.get("status") or {}).get("activeAlerts", 0),
                "createdAt": p["metadata"].get("creationTimestamp", ""),
            }
            for p in data.get("policies", [])
        ],
        "timestamp": now_iso(),
    }


@router.post("/observability/targets")
def create_observation_target(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a new ObservationTarget CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    helpers = _observation_helpers()
    name, spec = helpers.extract_observation_spec(body, require_name=True, required_fields=("targetType", "connectorRef"))
    spec = helpers.validate_observation_target_spec(spec, partial=False)
    return create_custom_resource("observationtargets", namespace, name, spec)


@router.get("/observability/targets/{name}")
def get_observation_target(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return the full ObservationTarget resource."""
    ensure_namespace_access(user, namespace)
    return read_custom_resource("observationtargets", name, namespace, "ObservationTarget")


@router.patch("/observability/targets/{name}")
def update_observation_target(
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Patch an ObservationTarget spec."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    helpers = _observation_helpers()
    provided_name, spec = helpers.extract_observation_spec(body, require_name=False)
    if provided_name and provided_name != name:
        raise HTTPException(status_code=400, detail="Body name does not match path name")
    spec = helpers.validate_observation_target_spec(spec, partial=True)
    return helpers.replace_custom_resource_spec_patch("observationtargets", name, namespace, spec)


@router.delete("/observability/targets/{name}")
def delete_observation_target(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete an ObservationTarget CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    return delete_custom_resource("observationtargets", name, namespace, "ObservationTarget")


@router.post("/observability/policies")
def create_observation_policy(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a new ObservationPolicy CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    helpers = _observation_helpers()
    name, spec = helpers.extract_observation_spec(body, require_name=True)
    spec = helpers.validate_observation_policy_spec(spec, partial=False)
    return create_custom_resource("observationpolicies", namespace, name, spec)


@router.get("/observability/policies/{name}")
def get_observation_policy(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return the full ObservationPolicy resource."""
    ensure_namespace_access(user, namespace)
    return read_custom_resource("observationpolicies", name, namespace, "ObservationPolicy")


@router.patch("/observability/policies/{name}")
def update_observation_policy(
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Patch an ObservationPolicy spec."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    helpers = _observation_helpers()
    provided_name, spec = helpers.extract_observation_spec(body, require_name=False)
    if provided_name and provided_name != name:
        raise HTTPException(status_code=400, detail="Body name does not match path name")
    spec = helpers.validate_observation_policy_spec(spec, partial=True)
    return helpers.replace_custom_resource_spec_patch("observationpolicies", name, namespace, spec)


@router.delete("/observability/policies/{name}")
def delete_observation_policy(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete an ObservationPolicy CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    return delete_custom_resource("observationpolicies", name, namespace, "ObservationPolicy")


@router.post("/observability/connectors")
def create_connector_plugin(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a new ConnectorPlugin CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    helpers = _observation_helpers()
    name, spec = helpers.extract_observation_spec(body, require_name=True, required_fields=("image", "protocol"))
    spec = helpers.validate_connector_plugin_spec(spec, partial=False)
    return create_custom_resource("connectorplugins", namespace, name, spec)


@router.get("/observability/connectors/{name}")
def get_connector_plugin(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return the full ConnectorPlugin resource."""
    ensure_namespace_access(user, namespace)
    return read_custom_resource("connectorplugins", name, namespace, "ConnectorPlugin")


@router.patch("/observability/connectors/{name}")
def update_connector_plugin(
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Patch a ConnectorPlugin spec."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    helpers = _observation_helpers()
    provided_name, spec = helpers.extract_observation_spec(body, require_name=False)
    if provided_name and provided_name != name:
        raise HTTPException(status_code=400, detail="Body name does not match path name")
    spec = helpers.validate_connector_plugin_spec(spec, partial=True)
    return helpers.replace_custom_resource_spec_patch("connectorplugins", name, namespace, spec)


@router.delete("/observability/connectors/{name}")
def delete_connector_plugin(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete a ConnectorPlugin CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    return delete_custom_resource("connectorplugins", name, namespace, "ConnectorPlugin")


# =========================================================================
# Intelligence Collector API
# =========================================================================

# In-memory cache of collectors — authoritative source is DB (IntelligenceCollectorRow)
_collector_registry: dict[str, dict[str, dict[str, Any]]] = {}
_collection_tasks: dict[str, dict[str, Any]] = {}
_ALERT_HISTORY_CAP = 500
_COLLECTION_TASKS_CAP = 200

# Thread-safety locks for in-memory intelligence dicts
_collector_lock = threading.Lock()
_tasks_lock = threading.Lock()

COLLECTOR_TIMEOUT = int(os.environ.get("COLLECTOR_TIMEOUT", "45"))

# ─── SSRF protection for collector URLs ───────────────────────────────────
import ipaddress as _ipaddress

_SSRF_BLOCKED_NETS = [
    _ipaddress.ip_network("169.254.0.0/16"),   # AWS / cloud metadata
    _ipaddress.ip_network("100.100.100.0/24"), # Alibaba metadata
]
_INTELLIGENCE_SCRIPT_TYPES = {"bash", "python"}
_INTELLIGENCE_ALERT_CONDITION_TYPES = {"contains", "not_contains", "exit_code", "regex"}
_INTELLIGENCE_ALERT_ACTIONS = {"notify", "invoke_agent"}
_INTELLIGENCE_BUILTINS = {
    "cluster_overview",
    "node_health",
    "pod_resources",
    "logs_collector",
    "helm_releases",
    "network_info",
    "storage_info",
    "configmap_secrets",
    "security_posture",
    "crd_inventory",
}

_DEFAULT_COLLECTOR_TOKEN = os.environ.get("KUBESYNAPSE_COLLECTOR_TOKEN", "")
_DEFAULT_COLLECTOR_TOKEN_HASH = (
    hashlib.sha256(_DEFAULT_COLLECTOR_TOKEN.encode("utf-8")).hexdigest() if _DEFAULT_COLLECTOR_TOKEN else ""
)
_COLLECTOR_TOKEN_MISSING_ERROR = "Collector token is unavailable in the gateway. Re-register this collector with a valid token."
_collector_secret_warning_emitted = False


def _collector_token_secret() -> str:
    global _collector_secret_warning_emitted

    explicit_secret = os.getenv("INTELLIGENCE_COLLECTOR_TOKEN_KEY", "").strip()
    if explicit_secret:
        return explicit_secret

    explicit_secret = os.getenv("JWT_SECRET", "").strip() or os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
    if explicit_secret:
        return explicit_secret

    if not _collector_secret_warning_emitted:
        logger.warning(
            "INTELLIGENCE_COLLECTOR_TOKEN_KEY, JWT_SECRET, and API_GATEWAY_SHARED_TOKEN are unset. "
            "Collector tokens are encrypted with an ephemeral process secret and will not survive gateway restarts."
        )
        _collector_secret_warning_emitted = True
    return JWT_SECRET


def _collector_fernet():
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(_collector_token_secret().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_collector_token(token: str) -> str:
    normalized = str(token or "").strip()
    if not normalized:
        raise ValueError("Collector token cannot be empty")
    return _collector_fernet().encrypt(normalized.encode("utf-8")).decode("utf-8")


def _decrypt_collector_token(encrypted_token: str | None) -> str | None:
    if not encrypted_token:
        return None
    try:
        from cryptography.fernet import InvalidToken

        return _collector_fernet().decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("Failed to decrypt a persisted collector token. Re-register the collector to restore task execution.")
    except Exception:
        logger.exception("Unexpected error while decrypting a persisted collector token.")
    return None


def _recover_collector_token(row: IntelligenceCollectorRow) -> str | None:
    decrypted = _decrypt_collector_token(getattr(row, "encrypted_token", None))
    if decrypted:
        return decrypted
    if getattr(row, "token_hash", None) == _DEFAULT_COLLECTOR_TOKEN_HASH:
        return _DEFAULT_COLLECTOR_TOKEN
    return None


def _collector_auth_headers(token: str | None) -> dict[str, str]:
    normalized = str(token or "").strip()
    if not normalized:
        return {}
    return {"Authorization": f"Bearer {normalized}"}

def _validate_collector_url(url: str) -> str:
    """Validate a collector URL: must be http/https, no cloud-metadata IPs."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Collector URL must use http or https scheme")
    hostname = parsed.hostname or ""
    try:
        addr = _ipaddress.ip_address(hostname)
        for net in _SSRF_BLOCKED_NETS:
            if addr in net:
                raise HTTPException(status_code=400, detail=f"Collector URL targets a blocked IP range ({net})")
    except ValueError:
        pass  # hostname is a DNS name, not a raw IP — allowed
    return url.rstrip("/")


def _normalize_intelligence_namespace(namespace: str | None) -> str:
    normalized = str(namespace or "default").strip()
    return normalized or "default"


def _slugify_identifier(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def _build_namespace_scoped_collector_id(namespace: str, name: str) -> str:
    namespace_slug = _slugify_identifier(namespace, "default")
    collector_slug = _slugify_identifier(name, "collector")
    candidate = f"{namespace_slug}-{collector_slug}"
    if len(candidate) <= 128:
        return candidate
    digest = hashlib.sha256(f"{namespace}:{name}".encode()).hexdigest()[:8]
    head = max(1, 128 - len(namespace_slug) - len(digest) - 2)
    trimmed_slug = collector_slug[:head].rstrip("-") or "collector"
    return f"{namespace_slug}-{trimmed_slug}-{digest}"


def _get_namespaced_collectors(namespace: str) -> dict[str, dict[str, Any]]:
    normalized = _normalize_intelligence_namespace(namespace)
    with _collector_lock:
        return {
            collector_id: copy.deepcopy(info)
            for collector_id, info in _collector_registry.get(normalized, {}).items()
        }


def _set_namespaced_collector(namespace: str, collector_id: str, info: dict[str, Any]) -> None:
    normalized = _normalize_intelligence_namespace(namespace)
    with _collector_lock:
        bucket = _collector_registry.setdefault(normalized, {})
        bucket[collector_id] = {**copy.deepcopy(info), "namespace": normalized}


def _remove_namespaced_collector(namespace: str, collector_id: str) -> None:
    normalized = _normalize_intelligence_namespace(namespace)
    with _collector_lock:
        bucket = _collector_registry.get(normalized, {})
        bucket.pop(collector_id, None)
        if not bucket and normalized in _collector_registry:
            del _collector_registry[normalized]


def _list_namespaced_tasks(namespace: str) -> list[dict[str, Any]]:
    normalized = _normalize_intelligence_namespace(namespace)
    with _tasks_lock:
        tasks = [
            copy.deepcopy(task)
            for task in _collection_tasks.values()
            if _normalize_intelligence_namespace(task.get("namespace")) == normalized
        ]
    return sorted(tasks, key=lambda task: task.get("submitted_at", ""), reverse=True)


def _validate_intelligence_builtin(builtin: Any) -> str:
    normalized = str(builtin or "").strip()
    if normalized not in _INTELLIGENCE_BUILTINS:
        allowed = ", ".join(sorted(_INTELLIGENCE_BUILTINS))
        raise HTTPException(status_code=400, detail=f"Unknown built-in script '{normalized}'. Allowed values: {allowed}")
    return normalized


def _normalize_intelligence_timeout(value: Any, default: int = 30) -> int:
    try:
        timeout = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Timeout must be an integer between 1 and 60 seconds") from exc
    return max(1, min(timeout, 60))


def _normalize_intelligence_script_type(value: Any) -> str:
    normalized = str(value or "bash").strip().lower() or "bash"
    if normalized not in _INTELLIGENCE_SCRIPT_TYPES:
        raise HTTPException(status_code=400, detail="Script type must be 'bash' or 'python'")
    return normalized


def _normalize_collection_payload(body: dict[str, Any], *, require_execution: bool = True) -> dict[str, Any]:
    builtin = str(body.get("builtin") or "").strip()
    script = str(body.get("script") or "").strip()
    if builtin and script:
        raise HTTPException(status_code=400, detail="Specify either 'builtin' or 'script', not both")
    if require_execution and not builtin and not script:
        raise HTTPException(status_code=400, detail="'builtin' or 'script' required")

    payload: dict[str, Any] = {"timeout": _normalize_intelligence_timeout(body.get("timeout"), 30)}
    if builtin:
        payload["builtin"] = _validate_intelligence_builtin(builtin)
        return payload
    if script:
        if len(script) > 10000:
            raise HTTPException(status_code=400, detail="Script too large (max 10000 chars)")
        payload["script"] = script
        payload["type"] = _normalize_intelligence_script_type(body.get("type") or body.get("script_type"))
    return payload


def _resolve_collection_targets(namespace: str, collector_id: str) -> dict[str, dict[str, Any]]:
    collectors = _get_namespaced_collectors(namespace)
    if collector_id == "all":
        if not collectors:
            raise HTTPException(status_code=404, detail=f"No collectors registered in namespace '{namespace}'")
        return collectors
    if collector_id not in collectors:
        raise HTTPException(status_code=404, detail=f"Collector '{collector_id}' not found in namespace '{namespace}'")
    return {collector_id: collectors[collector_id]}


def _ensure_intelligence_agent_exists(agent_name: Any, namespace: str) -> str | None:
    normalized = str(agent_name or "").strip() or None
    if normalized:
        read_agent(normalized, namespace)
    return normalized


def _task_matches_request(task: dict[str, Any], collector_id: str, payload: dict[str, Any]) -> bool:
    if collector_id != "all" and task.get("collector_id") != collector_id:
        return False
    task_payload = task.get("payload") or {}
    builtin = payload.get("builtin")
    if builtin:
        return task_payload.get("builtin") == builtin
    return (
        task_payload.get("script") == payload.get("script")
        and str(task_payload.get("type") or "bash") == str(payload.get("type") or "bash")
    )


def _build_intelligence_task_record(
    namespace: str,
    *,
    task_id: str,
    collector_id: str,
    payload: dict[str, Any],
    results: dict[str, Any],
    submitted_by: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "namespace": _normalize_intelligence_namespace(namespace),
        "collector_id": collector_id,
        "payload": payload,
        "results": results,
        "submitted_by": submitted_by,
        "submitted_at": datetime.now(UTC).isoformat(),
        "total": len(results),
        "completed": sum(1 for result in results.values() if result.get("status") == "completed"),
    }


def _load_collectors_from_db() -> None:
    """Populate the in-memory collector cache from the database at startup."""
    with db_session() as ses:
        rows = ses.query(IntelligenceCollectorRow).all()
        for row in rows:
            recovered_token = _recover_collector_token(row)
            _set_namespaced_collector(
                row.namespace,
                row.id,
                {
                    "id": row.id,
                    "name": row.name,
                    "url": row.url,
                    "token": recovered_token,
                    "cluster": row.cluster,
                    "registered_at": row.registered_at.isoformat() if row.registered_at else None,
                    "tags": row.tags or [],
                },
            )
    logger.info("Loaded %d collectors from database.", len(_collector_registry))


def _load_tasks_from_db() -> None:
    """Populate the in-memory task cache from the database at startup."""
    with db_session() as ses:
        rows = (
            ses.query(IntelligenceTaskRow)
            .order_by(IntelligenceTaskRow.submitted_at.desc())
            .limit(_COLLECTION_TASKS_CAP)
            .all()
        )
        for row in rows:
            _collection_tasks[row.task_id] = {
                "task_id": row.task_id,
                "namespace": row.namespace,
                "collector_id": row.collector_id,
                "payload": row.payload or {},
                "results": row.results or {},
                "submitted_by": row.submitted_by,
                "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
                "total": row.total or 0,
                "completed": row.completed or 0,
            }
    logger.info("Loaded %d tasks from database.", len(_collection_tasks))


def _persist_task(task_record: dict[str, Any]) -> None:
    """Write a task record to the database."""
    with db_session() as ses:
        ses.add(IntelligenceTaskRow(
            task_id=task_record["task_id"],
            namespace=_normalize_intelligence_namespace(task_record.get("namespace")),
            collector_id=task_record.get("collector_id"),
            payload=task_record.get("payload"),
            results=task_record.get("results"),
            submitted_by=task_record.get("submitted_by"),
            submitted_at=datetime.fromisoformat(task_record["submitted_at"]) if task_record.get("submitted_at") else datetime.now(UTC),
            total=task_record.get("total", 0),
            completed=task_record.get("completed", 0),
        ))


def _enforce_collection_tasks_cap() -> None:
    """Evict oldest tasks when the in-memory dict exceeds _COLLECTION_TASKS_CAP."""
    if len(_collection_tasks) <= _COLLECTION_TASKS_CAP:
        return
    sorted_ids = sorted(
        _collection_tasks,
        key=lambda tid: _collection_tasks[tid].get("submitted_at", ""),
    )
    to_remove = len(_collection_tasks) - _COLLECTION_TASKS_CAP
    for tid in sorted_ids[:to_remove]:
        del _collection_tasks[tid]
    # Also trim the DB
    with db_session() as ses:
        total = ses.query(IntelligenceTaskRow).count()
        if total > _COLLECTION_TASKS_CAP:
            oldest = (
                ses.query(IntelligenceTaskRow)
                .order_by(IntelligenceTaskRow.submitted_at.asc())
                .limit(total - _COLLECTION_TASKS_CAP)
                .all()
            )
            for old in oldest:
                ses.delete(old)


def _delete_collection_tasks(namespace: str, task_ids: list[Any]) -> tuple[list[str], list[str]]:
    normalized = _normalize_intelligence_namespace(namespace)
    requested: list[str] = []
    seen: set[str] = set()
    for value in task_ids:
        task_id = str(value or "").strip()
        if task_id and task_id not in seen:
            requested.append(task_id)
            seen.add(task_id)
    if not requested:
        raise HTTPException(status_code=400, detail="'task_ids' must contain at least one task id")

    deleted: set[str] = set()
    with db_session() as ses:
        rows = (
            ses.query(IntelligenceTaskRow)
            .filter(
                IntelligenceTaskRow.namespace == normalized,
                IntelligenceTaskRow.task_id.in_(requested),
            )
            .all()
        )
        for row in rows:
            deleted.add(row.task_id)
            ses.delete(row)

    with _tasks_lock:
        for task_id in requested:
            task = _collection_tasks.get(task_id)
            if task and _normalize_intelligence_namespace(task.get("namespace")) == normalized:
                deleted.add(task_id)
                _collection_tasks.pop(task_id, None)

    deleted_ids = [task_id for task_id in requested if task_id in deleted]
    missing_ids = [task_id for task_id in requested if task_id not in deleted]
    return deleted_ids, missing_ids

# ─── Auto-inject intelligence context into agent invocations ─────────────

_INTELLIGENCE_SYSTEM_KEYWORDS = {"cluster intelligence", "intelligence data", "sre assistant", "cluster intel"}

def _agent_wants_intelligence(agent: dict[str, Any]) -> bool:
    """Return True if the agent's system prompt indicates it uses intelligence."""
    sys_prompt = (agent.get("spec", {}).get("systemPrompt") or "").lower()
    return any(kw in sys_prompt for kw in _INTELLIGENCE_SYSTEM_KEYWORDS)


def _build_auto_intelligence_context(
    namespace: str,
    max_scripts: int = 5,
    max_chars: int = 6000,
    max_age_minutes: int = 30,
) -> str:
    """Build a condensed intelligence context from recent collection tasks.
    Skips tasks older than max_age_minutes to avoid injecting stale data."""
    recent_tasks = _list_namespaced_tasks(namespace)
    if not recent_tasks:
        return ""
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    # Group by builtin script, keep most recent per script
    latest_by_script: dict[str, dict[str, Any]] = {}
    for task in recent_tasks:
        # Staleness check
        submitted_str = task.get("submitted_at", "")
        if submitted_str:
            try:
                submitted = datetime.fromisoformat(submitted_str)
                if submitted.tzinfo is None:
                    submitted = submitted.replace(tzinfo=UTC)
                if submitted < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
        builtin = task.get("payload", {}).get("builtin", "")
        if not builtin or builtin in latest_by_script:
            continue
        latest_by_script[builtin] = task
        if len(latest_by_script) >= max_scripts:
            break
    if not latest_by_script:
        return ""
    parts = ["## Auto-injected Cluster Intelligence Summary", ""]
    total_len = 0
    for builtin, task in latest_by_script.items():
        section = [f"### {builtin} (collected {task.get('submitted_at', 'unknown')})"]
        for _cid, result in task.get("results", {}).items():
            if result.get("status") == "completed":
                stdout = (result.get("stdout") or "").strip()
                if stdout:
                    remaining = max_chars - total_len
                    if remaining <= 200:
                        break
                    snippet = stdout[:remaining]
                    section.append(f"```\n{snippet}\n```")
                    total_len += len(snippet)
        parts.extend(section)
        parts.append("")
        if total_len >= max_chars:
            break
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Run Intelligence Layer — Agent Graph & Spend Lens
# ---------------------------------------------------------------------------


@router.get("/agent-graph")
def get_agent_interaction_graph(
    namespace: str | None = None,
    hours: int = 24,
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Build agent-to-agent dependency graph from A2A events."""
    if namespace:
        ensure_namespace_access(user, namespace)

    graph = trace_store.get_agent_interaction_graph(
        namespace=namespace,
        hours=min(hours, 168),
    )
    return graph


@router.get("/spend")
def get_spend_breakdown(
    namespace: str | None = None,
    hours: int = 24,
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Aggregate token/cost spend by agent, model, runtime, namespace."""
    if namespace:
        ensure_namespace_access(user, namespace)

    items = trace_store.get_spend_breakdown(
        namespace=namespace,
        hours=min(hours, 720),
    )
    return {"items": items, "window_hours": hours}
