"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

import re
from typing import Any, cast

import httpx

# Re-import all shared symbols from the gateway core
from _core import *
from _core import _SHUTDOWN
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from auth_store import get_user_by_id
from services.runtime_client import runtime_auth_headers
from routers.observability import (
    _COLLECTOR_TOKEN_MISSING_ERROR,
    _INTELLIGENCE_ALERT_ACTIONS,
    _INTELLIGENCE_ALERT_CONDITION_TYPES,
    COLLECTOR_TIMEOUT,
    _build_intelligence_task_record,
    _build_namespace_scoped_collector_id,
    _collection_tasks,
    _collector_auth_headers,
    _delete_collection_tasks,
    _encrypt_collector_token,
    _enforce_collection_tasks_cap,
    _get_namespaced_collectors,
    _normalize_collection_payload,
    _normalize_intelligence_namespace,
    _persist_task,
    _remove_namespaced_collector,
    _resolve_collection_targets,
    _set_namespaced_collector,
    _tasks_lock,
    _validate_collector_url,
)

router = APIRouter(tags=["admin"])

_USER_NAMESPACE_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _user_namespace_slug(username: str) -> str:
    slug = _USER_NAMESPACE_SLUG_RE.sub("-", username.strip().lower()).strip("-")
    return (slug[:57].strip("-") or "user")


def _user_namespace_name(username: str) -> str:
    return f"user-{_user_namespace_slug(username)}"


def _user_allowed_namespaces(username: str, role: str, allowed_namespaces: list[str] | None) -> list[str]:
    if role == "admin":
        return ["*"]

    dedicated_namespace = _user_namespace_name(username)
    requested = [str(item).strip() for item in (allowed_namespaces or []) if str(item).strip() and str(item).strip() != "*"]
    requested.append(dedicated_namespace)
    return sorted(set(requested))


def _user_tenant_admin_users(username: str, role: str, is_active: bool) -> list[str]:
    if not is_active or role == "viewer":
        return []
    return [username]


def _custom_objects_api():
    from kubernetes import client

    return client.CustomObjectsApi()


def _reconcile_user_tenant(username: str, role: str, is_active: bool) -> None:
    tenant_name = _user_namespace_name(username)
    tenant_body = {
        "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
        "kind": "AgentTenant",
        "metadata": {"name": tenant_name},
        "spec": {
            "tenantName": _user_namespace_slug(username),
            "namespace": tenant_name,
            "adminUsers": _user_tenant_admin_users(username, role, is_active),
        },
    }

    api = _custom_objects_api()
    try:
        api.create_cluster_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            plural="agenttenants",
            body=tenant_body,
        )
        return
    except Exception as exc:
        if getattr(exc, "status", None) != 409:
            raise HTTPException(status_code=502, detail="Failed to provision the user's dedicated namespace") from exc

    try:
        existing = cast(
            dict[str, Any],
            api.get_cluster_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                plural="agenttenants",
                name=tenant_name,
            ),
        )
        existing["spec"] = tenant_body["spec"]
        api.replace_cluster_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            plural="agenttenants",
            name=tenant_name,
            body=existing,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to update the user's dedicated namespace") from exc

@router.get("/admin/users")
def admin_list_users(user=Depends(verify_token)) -> list[dict[str, Any]]:
    ensure_role(user, "admin")
    return list_local_users()


@router.post("/admin/users", status_code=201)
def admin_create_user(
    body: CreateUserRequest,
    raw_request: Request,
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_role(user, "admin")
    requested_namespaces = _user_allowed_namespaces(body.username, body.role, body.allowed_namespaces)
    try:
        created = create_local_user(
            username=body.username,
            password=body.password,
            email=body.email,
            display_name=body.display_name,
            role=body.role,
            allowed_namespaces=requested_namespaces,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _reconcile_user_tenant(
        str(created.get("username") or body.username).strip().lower(),
        str(created.get("role") or body.role),
        bool(created.get("is_active", True)),
    )

    safe_record_audit(
        action="admin.create-user",
        principal=user,
        resource_kind="user",
        resource_name=str(created.get("username") or body.username),
        detail={"role": created.get("role")},
        ip_address=request_client_ip(raw_request),
    )
    return created


@router.patch("/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    body: UpdateUserRequest,
    raw_request: Request,
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_role(user, "admin")
    existing = get_user_by_id(user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="User was not found.")

    # Prevent admin from demoting themselves
    acting_user_id = int(str(user.get("sub") or "0"))
    if acting_user_id == user_id and body.role is not None and body.role != "admin":
        raise HTTPException(status_code=400, detail="Cannot change your own admin role")
    if acting_user_id == user_id and body.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    next_role = body.role or str(existing.role or "viewer")
    next_is_active = bool(existing.is_active if body.is_active is None else body.is_active)
    next_allowed_namespaces = _user_allowed_namespaces(
        str(existing.username),
        next_role,
        body.allowed_namespaces if body.allowed_namespaces is not None else cast(list[str] | None, existing.allowed_namespaces),
    )

    try:
        updated = update_user_fields(
            user_id,
            display_name=body.display_name,
            role=body.role,
            is_active=body.is_active,
            allowed_namespaces=next_allowed_namespaces,
            capabilities=body.capabilities,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _reconcile_user_tenant(str(existing.username), next_role, next_is_active)

    safe_record_audit(
        action="admin.update-user",
        principal=user,
        resource_kind="user",
        resource_name=str(updated.get("username") or user_id),
        detail={
            "role": updated.get("role"),
            "is_active": updated.get("is_active"),
            "allowed_namespaces": updated.get("allowed_namespaces"),
            "capabilities": updated.get("capabilities"),
        },
        ip_address=request_client_ip(raw_request),
    )
    return updated


@router.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: int,
    raw_request: Request,
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Delete a local user.  Admin-only.  Cannot delete self."""
    ensure_role(user, "admin")
    from auth_store import delete_local_user

    # Prevent admin from deleting themselves
    acting_user_id = int(str(user.get("sub") or "0"))
    if acting_user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account")

    try:
        deleted = delete_local_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    safe_record_audit(
        action="admin.delete-user",
        principal=user,
        resource_kind="user",
        resource_name=str(deleted.get("username") or user_id),
        detail={"role": deleted.get("role", "unknown")},
        ip_address=request_client_ip(raw_request),
    )
    return {"status": "deleted", "user": deleted}


@router.get("/admin/audit")
def get_audit_logs(
    raw_request: Request,
    actor: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    namespace: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(verify_token),
):
    ensure_role(user, "admin")
    from_dt = None
    to_dt = None
    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date format") from None
    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_date format") from None
    return query_audit_logs(
        actor=actor,
        actor_type=actor_type,
        action=action,
        resource_kind=resource_kind,
        resource_name=resource_name,
        namespace=namespace,
        from_date=from_dt,
        to_date=to_dt,
        limit=limit,
        offset=offset,
    )


@router.delete("/admin/audit/purge")
def purge_audit_logs(
    raw_request: Request,
    user=Depends(verify_token),
):
    ensure_role(user, "admin")
    deleted = purge_old_audit_logs()
    record_audit_log(
        action="purged",
        actor_sub=user.get("sub"),
        actor_username=user.get("username"),
        actor_type="user",
        auth_provider=user.get("auth_provider"),
        resource_kind="audit",
        detail={"deleted_count": deleted},
        ip_address=request_client_ip(raw_request),
    )
    return {"deleted": deleted}


# ── Token Usage & Cost Endpoints ──


@router.get("/usage/summary")
def usage_summary(
    user=Depends(verify_token),
    namespace: str | None = None,
    group_by: str = "agent",
    from_date: str | None = None,
    to_date: str | None = None,
):
    from datetime import datetime as _dt

    parsed_from = _dt.fromisoformat(from_date) if from_date else None
    parsed_to = _dt.fromisoformat(to_date) if to_date else None
    rows = query_usage_summary(
        namespace=namespace,
        from_date=parsed_from,
        to_date=parsed_to,
        group_by=group_by,
    )
    return {"items": rows}


@router.get("/usage/detail")
def usage_detail(
    user=Depends(verify_token),
    namespace: str | None = None,
    agent_name: str | None = None,
    model: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    from datetime import datetime as _dt

    parsed_from = _dt.fromisoformat(from_date) if from_date else None
    parsed_to = _dt.fromisoformat(to_date) if to_date else None
    return query_usage_detail(
        namespace=namespace,
        agent_name=agent_name,
        model=model,
        from_date=parsed_from,
        to_date=parsed_to,
        limit=limit,
        offset=offset,
    )


@router.get("/health")
def health() -> dict[str, Any]:
    if _SHUTDOWN.is_set():
        return {"status": "shutting-down", "gateway": "kubesynapse"}
    return {
        "status": "healthy",
        "gateway": "kubesynapse",
        "auth_mode": AUTH_MODE,
        "browser_auth_enabled": browser_auth_enabled(),
        "local_auth_enabled": local_access_enabled(),
        "shared_token_enabled": shared_token_enabled(),
        "nats_url": NATS_URL,
        "qdrant_url": QDRANT_URL,
    }


@router.get("/ready")
async def ready(response: Response) -> dict[str, Any]:
    if _SHUTDOWN.is_set():
        response.status_code = 503
        return {"status": "shutting-down", "gateway": "kubesynapse"}
    checks: dict[str, str] = {}
    try:
        from sqlalchemy import text as _sa_text

        from auth_store import ENGINE

        with ENGINE.connect() as conn:
            conn.execute(_sa_text("select 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    litellm_headers: dict[str, str] = {}
    if LITELLM_MASTER_KEY:
        litellm_headers["Authorization"] = f"Bearer {LITELLM_MASTER_KEY}"
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            readiness_response = await client.get(f"{LITELLM_INTERNAL_URL.rstrip('/')}/v1/models", headers=litellm_headers)
        checks["litellm"] = "ok" if readiness_response.status_code == 200 else "error"
    except Exception:
        checks["litellm"] = "error"
    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = 503
    return {"status": "ready" if all_ok else "degraded", "gateway": "kubesynapse", "checks": checks}


@router.get("/approvals/{approval_name}", response_model=ApprovalInfo)
def get_approval(
    approval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    approval = read_approval(approval_name, namespace)
    spec = approval.get("spec", {})
    status = approval.get("status", {})
    return ApprovalInfo(
        name=approval.get("metadata", {}).get("name", approval_name),
        namespace=approval.get("metadata", {}).get("namespace", namespace),
        decision=status.get("decision", "pending"),
        agent_name=spec.get("agentName", ""),
        action=spec.get("action", ""),
        requested_at=spec.get("requestedAt"),
        decided_by=status.get("decidedBy"),
        decided_at=status.get("decidedAt"),
        reason=status.get("reason"),
    )


@router.get("/policies", response_model=list[PolicyInfo])
def list_policies(namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    try:
        raw_policies = get_policies(namespace)
        return sorted(
            [policy_info_from_resource(p) for p in raw_policies],
            key=lambda item: item.name,
        )
    except Exception:
        logger.exception("Failed to list policies in namespace '%s'", namespace)
        return []


class PolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=253, pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")
    input_guardrails: dict[str, Any] = Field(default_factory=dict)
    output_guardrails: dict[str, Any] = Field(default_factory=dict)
    allowed_models: list[str] = Field(default_factory=list)
    allowed_mcp_servers: list[str] = Field(default_factory=list)
    mcp_require_hitl: bool = True
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    memory_policy: dict[str, Any] = Field(default_factory=dict)


class PolicyUpdateRequest(BaseModel):
    input_guardrails: dict[str, Any] | None = None
    output_guardrails: dict[str, Any] | None = None
    allowed_models: list[str] | None = None
    allowed_mcp_servers: list[str] | None = None
    mcp_require_hitl: bool | None = None
    tool_policy: dict[str, Any] | None = None
    memory_policy: dict[str, Any] | None = None


def build_policy_spec(
    body: PolicyRequest | PolicyUpdateRequest, existing_spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    spec: dict[str, Any] = dict(existing_spec) if existing_spec else {}
    if isinstance(body, PolicyRequest) or body.input_guardrails is not None:
        ig = body.input_guardrails or {}
        spec["inputGuardrails"] = {
            "blockPromptInjection": ig.get("block_prompt_injection", ig.get("blockPromptInjection", False)),
            "blockedPatterns": ig.get("blocked_patterns", ig.get("blockedPatterns", [])),
            "maxInputTokens": ig.get("max_input_tokens", ig.get("maxInputTokens", 4096)),
        }
    if isinstance(body, PolicyRequest) or body.output_guardrails is not None:
        og = body.output_guardrails or {}
        spec["outputGuardrails"] = {
            "maskPII": og.get("mask_pii", og.get("maskPII", False)),
            "blockedOutputPatterns": og.get("blocked_output_patterns", og.get("blockedOutputPatterns", [])),
            "maxOutputTokens": og.get("max_output_tokens", og.get("maxOutputTokens", 4096)),
        }
    if isinstance(body, PolicyRequest) or body.allowed_models is not None:
        spec["allowedModels"] = body.allowed_models or []
    if isinstance(body, PolicyRequest) or body.allowed_mcp_servers is not None:
        spec["allowedMcpServers"] = body.allowed_mcp_servers or []
    if isinstance(body, PolicyRequest) or body.mcp_require_hitl is not None:
        spec["mcpRequireHitl"] = body.mcp_require_hitl if body.mcp_require_hitl is not None else True
    if isinstance(body, PolicyRequest) or body.tool_policy is not None:
        spec["toolPolicy"] = body.tool_policy or {}
    if isinstance(body, PolicyRequest) or body.memory_policy is not None:
        spec["memoryPolicy"] = body.memory_policy or {}
    return spec


@router.post("/policies", response_model=PolicyInfo, status_code=201)
def create_policy(
    body: PolicyRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    # Validate required fields
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="Policy name is required.")
    spec = build_policy_spec(body)
    try:
        created = create_custom_resource("agentpolicies", namespace, body.name.strip(), spec)
        return policy_info_from_resource(created)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create policy '%s/%s'", namespace, body.name)
        raise HTTPException(status_code=502, detail=f"Failed to create policy: {exc}")


@router.get("/policies/{policy_name}", response_model=PolicyInfo)
def get_policy(policy_name: str, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    resource = read_custom_resource("agentpolicies", policy_name, namespace, "Policy")
    return policy_info_from_resource(resource)


@router.patch("/policies/{policy_name}", response_model=PolicyInfo)
def update_policy(
    policy_name: str,
    body: PolicyUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    try:
        existing = read_custom_resource("agentpolicies", policy_name, namespace, "Policy")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Policy '{policy_name}' not found.")
        raise
    existing_spec = existing.get("spec", {})
    updated_spec = build_policy_spec(body, existing_spec)
    try:
        from kubernetes import client
        updated = client.CustomObjectsApi().patch_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentpolicies",
            name=policy_name,
            body={"spec": updated_spec},
        )
        return policy_info_from_resource(updated)
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"Policy '{policy_name}' not found.")
        if status == 409:
            raise HTTPException(status_code=409, detail=f"Policy '{policy_name}' was modified by another request. Please retry.")
        if status == 422:
            raise HTTPException(status_code=400, detail=f"Invalid policy spec: {exc}")
        logger.exception("Failed to update policy '%s/%s'", namespace, policy_name)
        raise HTTPException(status_code=502, detail=f"Failed to update policy: {exc}") from exc


@router.delete("/policies/{policy_name}", response_model=DeleteResponse)
def delete_policy(
    policy_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    try:
        delete_custom_resource("agentpolicies", policy_name, namespace, "Policy")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Policy '{policy_name}' not found.")
        raise
    except Exception as exc:
        logger.exception("Failed to delete policy '%s/%s'", namespace, policy_name)
        raise HTTPException(status_code=502, detail=f"Failed to delete policy: {exc}")
    return DeleteResponse(status="deleted", kind="policy", name=policy_name, namespace=namespace)


@router.patch("/approvals/{approval_name}", response_model=ApprovalInfo)
def decide_approval(
    approval_name: str,
    body: ApprovalDecisionRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Record an approve/deny decision on a pending AgentApproval.

    Patches the AgentApproval CRD status subresource with the decision,
    the deciding user identity (JWT ``sub`` claim), and a UTC timestamp.
    The agent runtime watches ``status.decision`` and resumes or blocks
    execution once the field is set.
    """
    ensure_namespace_access(user, namespace, "operator")
    approval = read_approval(approval_name, namespace)
    spec = approval.get("spec", {})

    decided_by = str(user.get("sub", "unknown"))
    decided_at = datetime.now(UTC).isoformat()

    try:
        from kubernetes import client

        client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group="kubesynapse.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="agentapprovals",
            name=approval_name,
            body={
                "status": {
                    "decision": body.decision,
                    "decidedBy": decided_by,
                    "decidedAt": decided_at,
                    "reason": body.reason or "",
                }
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to record approval decision",
        ) from exc

    return ApprovalInfo(
        name=approval_name,
        namespace=namespace,
        decision=body.decision,
        agent_name=spec.get("agentName", ""),
        action=spec.get("action", ""),
        requested_at=spec.get("requestedAt"),
        decided_by=decided_by,
        decided_at=decided_at,
        reason=body.reason,
    )


@router.get("/export/bundle")
def export_yaml_bundle(
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Export all agents, workflows, and policies in the namespace as a multi-document YAML bundle."""
    ensure_namespace_access(user, namespace)
    import yaml as _yaml

    documents: list[dict[str, Any]] = []
    for plural in ("aiagents", "agentworkflows", "agentpolicies"):
        items = list_custom_resources(plural, namespace)
        for item in items:
            # Strip runtime status and server-managed metadata fields
            doc = {
                "apiVersion": item.get("apiVersion", f"{RESOURCE_GROUP}/{RESOURCE_VERSION}"),
                "kind": item.get("kind", plural),
                "metadata": {
                    "name": (item.get("metadata") or {}).get("name", ""),
                    "namespace": namespace,
                    "labels": (item.get("metadata") or {}).get("labels", {}),
                    "annotations": (item.get("metadata") or {}).get("annotations", {}),
                },
                "spec": item.get("spec", {}),
            }
            # Remove empty labels/annotations
            if not doc["metadata"]["labels"]:
                del doc["metadata"]["labels"]
            if not doc["metadata"]["annotations"]:
                del doc["metadata"]["annotations"]
            documents.append(doc)

    bundle = _yaml.dump_all(documents, default_flow_style=False, sort_keys=False)
    return Response(
        content=bundle,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f"attachment; filename=bundle-{namespace}.yaml"},
    )


@router.post("/import/bundle", status_code=201)
async def import_yaml_bundle(
    request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Import a multi-document YAML bundle, creating or updating resources."""
    ensure_namespace_access(user, namespace, "operator")
    import yaml as _yaml

    raw = await request.body()
    try:
        documents = list(_yaml.safe_load_all(raw.decode("utf-8")))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}") from exc

    results: list[dict[str, str]] = []
    for doc in documents:
        if not isinstance(doc, dict) or "kind" not in doc:
            continue

        kind = doc["kind"]
        plural_map = {
            "AIAgent": "aiagents",
            "AgentWorkflow": "agentworkflows",
            "AgentPolicy": "agentpolicies",
        }
        plural = plural_map.get(kind)
        if not plural:
            results.append(
                {
                    "name": doc.get("metadata", {}).get("name", "?"),
                    "status": "skipped",
                    "reason": f"Unknown kind: {kind}",
                }
            )
            continue

        name = (doc.get("metadata") or {}).get("name", "")
        if not name:
            results.append({"name": "(unnamed)", "status": "skipped", "reason": "Missing metadata.name"})
            continue

        doc.setdefault("metadata", {})["namespace"] = namespace

        from kubernetes import client

        api = client.CustomObjectsApi()

        try:
            # Try creating
            api.create_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural=plural,
                body=doc,
            )
            results.append({"name": name, "kind": kind, "status": "created"})
        except Exception as create_exc:
            if getattr(create_exc, "status", None) == 409:
                # Already exists — update spec only
                try:
                    existing = cast(
                        dict[str, Any],
                        api.get_namespaced_custom_object(
                            group=RESOURCE_GROUP,
                            version=RESOURCE_VERSION,
                            namespace=namespace,
                            plural=plural,
                            name=name,
                        ),
                    )
                    existing["spec"] = doc.get("spec", {})
                    api.replace_namespaced_custom_object(
                        group=RESOURCE_GROUP,
                        version=RESOURCE_VERSION,
                        namespace=namespace,
                        plural=plural,
                        name=name,
                        body=existing,
                    )
                    results.append({"name": name, "kind": kind, "status": "updated"})
                except Exception as upd_exc:
                    results.append({"name": name, "kind": kind, "status": "error", "reason": str(upd_exc)[:200]})
            else:
                results.append({"name": name, "kind": kind, "status": "error", "reason": str(create_exc)[:200]})

    return {"imported": len([r for r in results if r["status"] in ("created", "updated")]), "results": results}


# --------------------------------------------------------------------------- #
#  System health dashboard                                                      #
# --------------------------------------------------------------------------- #


@router.get("/system/health")
def system_health(
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Comprehensive system health check across all subsystems."""
    ensure_namespace_access(user, namespace)

    checks: dict[str, dict[str, Any]] = {}

    # Database
    try:
        from sqlalchemy import text as _sa_text

        from auth_store import ENGINE

        with ENGINE.connect() as conn:
            conn.execute(_sa_text("select 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "message": str(exc)[:200]}

    # Kubernetes API
    try:
        from kubernetes import client

        v1 = client.CoreV1Api()
        v1.list_namespace(limit=1)
        checks["kubernetes"] = {"status": "ok"}
    except Exception as exc:
        checks["kubernetes"] = {"status": "error", "message": str(exc)[:200]}

    # CRD counts
    try:
        agents = list_custom_resources("aiagents", namespace)
        workflows = list_custom_resources("agentworkflows", namespace)
        policies = list_custom_resources("agentpolicies", namespace)

        agent_phases: dict[str, int] = {}
        for a in agents:
            phase = ((a.get("status") or {}).get("phase") or "unknown").lower()
            agent_phases[phase] = agent_phases.get(phase, 0) + 1

        workflow_phases: dict[str, int] = {}
        for w in workflows:
            phase = ((w.get("status") or {}).get("phase") or "unknown").lower()
            workflow_phases[phase] = workflow_phases.get(phase, 0) + 1

        checks["resources"] = {
            "status": "ok",
            "agents": {"total": len(agents), "by_phase": agent_phases},
            "workflows": {"total": len(workflows), "by_phase": workflow_phases},
            "policies": {"total": len(policies)},
        }
    except Exception as exc:
        checks["resources"] = {"status": "error", "message": str(exc)[:200]}

    # NATS
    if NATS_URL:
        checks["nats"] = {"status": "configured", "url": NATS_URL}
    else:
        checks["nats"] = {"status": "not_configured"}

    # Qdrant
    if QDRANT_URL:
        checks["qdrant"] = {"status": "configured", "url": QDRANT_URL}
    else:
        checks["qdrant"] = {"status": "not_configured"}

    overall = (
        "healthy"
        if all(c.get("status") in ("ok", "configured", "not_configured") for c in checks.values())
        else "degraded"
    )

    return {
        "status": overall,
        "namespace": namespace,
        "auth_mode": AUTH_MODE,
        "checks": checks,
        "timestamp": now_iso(),
    }


# --------------------------------------------------------------------------- #
#  AIOps Observability — targets, policies, reports, connectors                #
# --------------------------------------------------------------------------- #

OBSERVATION_PLURALS = {
    "targets": "observationtargets",
    "policies": "observationpolicies",
    "reports": "observationreports",
    "connectors": "connectorplugins",
}

OBSERVATION_TARGET_TYPES = {"prometheus", "kubernetes-api", "snmp", "gnmi", "nats", "custom"}
OBSERVATION_PROTOCOLS = {"grpc", "http"}
OBSERVATION_CAPABILITIES = OBSERVATION_TARGET_TYPES
OBSERVATION_ALERT_SEVERITIES = {"info", "warning", "critical"}
OBSERVATION_ALGORITHMS = {"isolation-forest", "prophet", "ensemble"}


def merge_resource_spec(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_resource_spec(cast(dict[str, Any], merged[key]), cast(dict[str, Any], value))
        else:
            merged[key] = value
    return merged


def replace_custom_resource_spec_patch(plural: str, name: str, namespace: str, patch: dict[str, Any]) -> dict[str, Any]:
    current = read_custom_resource(plural, name, namespace, "Resource")
    current_spec = cast(dict[str, Any], current.get("spec") or {})
    merged_spec = merge_resource_spec(current_spec, patch)
    return replace_custom_resource_spec(plural, name, namespace, merged_spec)


def extract_observation_spec(
    body: dict[str, Any],
    *,
    require_name: bool,
    required_fields: tuple[str, ...] = (),
) -> tuple[str | None, dict[str, Any]]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    name: str | None = None
    raw_name = body.get("name")
    if require_name:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise HTTPException(status_code=400, detail="Missing 'name'")
        name = raw_name.strip()
    elif raw_name is not None:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise HTTPException(status_code=400, detail="Field 'name' must be a non-empty string when provided")
        name = raw_name.strip()

    reserved_fields = {"name", "apiVersion", "kind", "metadata", "status"}
    spec = {key: value for key, value in body.items() if key not in reserved_fields}

    for field in required_fields:
        value = spec.get(field)
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=400, detail=f"Missing '{field}'")

    return name, spec


def validate_observation_target_spec(spec: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    target_type = spec.get("targetType")
    if target_type is not None:
        if not isinstance(target_type, str) or target_type not in OBSERVATION_TARGET_TYPES:
            raise HTTPException(status_code=400, detail="Field 'targetType' must be a valid observation target type")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'targetType'")

    connector_ref = spec.get("connectorRef")
    if connector_ref is not None:
        if not isinstance(connector_ref, str) or not connector_ref.strip():
            raise HTTPException(status_code=400, detail="Field 'connectorRef' must be a non-empty string")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'connectorRef'")

    for optional_string_field in ("description", "endpoint", "scrapeInterval", "policyRef"):
        if optional_string_field in spec and spec[optional_string_field] is not None and not isinstance(spec[optional_string_field], str):
            raise HTTPException(status_code=400, detail=f"Field '{optional_string_field}' must be a string")

    if "selector" in spec and spec["selector"] is not None and not isinstance(spec["selector"], dict):
        raise HTTPException(status_code=400, detail="Field 'selector' must be an object")
    if "credentials" in spec and spec["credentials"] is not None and not isinstance(spec["credentials"], dict):
        raise HTTPException(status_code=400, detail="Field 'credentials' must be an object")
    if "tlsConfig" in spec and spec["tlsConfig"] is not None and not isinstance(spec["tlsConfig"], dict):
        raise HTTPException(status_code=400, detail="Field 'tlsConfig' must be an object")
    if "labels" in spec and spec["labels"] is not None:
        labels = spec["labels"]
        if not isinstance(labels, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in labels.items()):
            raise HTTPException(status_code=400, detail="Field 'labels' must be an object of string values")

    return spec


def validate_observation_policy_spec(spec: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    if "description" in spec and spec["description"] is not None and not isinstance(spec["description"], str):
        raise HTTPException(status_code=400, detail="Field 'description' must be a string")

    retention = spec.get("retention")
    if retention is not None:
        if not isinstance(retention, dict):
            raise HTTPException(status_code=400, detail="Field 'retention' must be an object")
        days = retention.get("days")
        if days is not None and (not isinstance(days, int) or days < 1 or days > 365):
            raise HTTPException(status_code=400, detail="Field 'retention.days' must be an integer between 1 and 365")

    alert_rules = spec.get("alertRules")
    if alert_rules is not None:
        if not isinstance(alert_rules, list):
            raise HTTPException(status_code=400, detail="Field 'alertRules' must be an array")
        for index, rule in enumerate(alert_rules):
            if not isinstance(rule, dict):
                raise HTTPException(status_code=400, detail=f"alertRules[{index}] must be an object")
            name = rule.get("name")
            expr = rule.get("expr")
            severity = rule.get("severity")
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(status_code=400, detail=f"alertRules[{index}].name must be a non-empty string")
            if not isinstance(expr, str) or not expr.strip():
                raise HTTPException(status_code=400, detail=f"alertRules[{index}].expr must be a non-empty string")
            if severity is not None and (not isinstance(severity, str) or severity not in OBSERVATION_ALERT_SEVERITIES):
                raise HTTPException(status_code=400, detail=f"alertRules[{index}].severity must be one of {sorted(OBSERVATION_ALERT_SEVERITIES)}")

    anomaly_detection = spec.get("anomalyDetection")
    if anomaly_detection is not None:
        if not isinstance(anomaly_detection, dict):
            raise HTTPException(status_code=400, detail="Field 'anomalyDetection' must be an object")
        algorithm = anomaly_detection.get("algorithm")
        sensitivity = anomaly_detection.get("sensitivity")
        metrics = anomaly_detection.get("metrics")
        if algorithm is not None and (not isinstance(algorithm, str) or algorithm not in OBSERVATION_ALGORITHMS):
            raise HTTPException(status_code=400, detail=f"Field 'anomalyDetection.algorithm' must be one of {sorted(OBSERVATION_ALGORITHMS)}")
        if sensitivity is not None and not isinstance(sensitivity, (int, float)):
            raise HTTPException(status_code=400, detail="Field 'anomalyDetection.sensitivity' must be numeric")
        if metrics is not None and (not isinstance(metrics, list) or not all(isinstance(item, str) for item in metrics)):
            raise HTTPException(status_code=400, detail="Field 'anomalyDetection.metrics' must be an array of strings")

    notifications = spec.get("notifications")
    if notifications is not None and not isinstance(notifications, dict):
        raise HTTPException(status_code=400, detail="Field 'notifications' must be an object")

    return spec


def validate_connector_plugin_spec(spec: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    image = spec.get("image")
    if image is not None:
        if not isinstance(image, str) or not image.strip():
            raise HTTPException(status_code=400, detail="Field 'image' must be a non-empty string")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'image'")

    protocol = spec.get("protocol")
    if protocol is not None:
        if not isinstance(protocol, str) or protocol not in OBSERVATION_PROTOCOLS:
            raise HTTPException(status_code=400, detail=f"Field 'protocol' must be one of {sorted(OBSERVATION_PROTOCOLS)}")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'protocol'")

    capabilities = spec.get("capabilities")
    if capabilities is not None:
        if not isinstance(capabilities, list) or not capabilities:
            raise HTTPException(status_code=400, detail="Field 'capabilities' must be a non-empty array")
        if not all(isinstance(item, str) and item in OBSERVATION_CAPABILITIES for item in capabilities):
            raise HTTPException(status_code=400, detail=f"Field 'capabilities' must contain only {sorted(OBSERVATION_CAPABILITIES)}")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'capabilities'")

    port = spec.get("port")
    if port is not None and (not isinstance(port, int) or port < 1024 or port > 65535):
        raise HTTPException(status_code=400, detail="Field 'port' must be an integer between 1024 and 65535")

    for optional_string_field in ("description", "healthEndpoint", "secretRef"):
        if optional_string_field in spec and spec[optional_string_field] is not None and not isinstance(spec[optional_string_field], str):
            raise HTTPException(status_code=400, detail=f"Field '{optional_string_field}' must be a string")

    if "resources" in spec and spec["resources"] is not None and not isinstance(spec["resources"], dict):
        raise HTTPException(status_code=400, detail="Field 'resources' must be an object")
    if "env" in spec and spec["env"] is not None and not isinstance(spec["env"], list):
        raise HTTPException(status_code=400, detail="Field 'env' must be an array")

    return spec


@router.get("/intelligence/collectors")
async def list_intelligence_collectors(namespace: str = "default", user=Depends(verify_token)):
    """List all registered collector agents and their status (tokens redacted)."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    collectors = []
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        for cid, info in _get_namespaced_collectors(namespace).items():
            entry = {
                "id": cid,
                "namespace": namespace,
                "name": info.get("name", cid),
                "url": info.get("url", ""),
                "token": "***",
                "cluster": info.get("cluster", "unknown"),
                "registered_at": info.get("registered_at"),
                "tags": info.get("tags", []),
            }
            try:
                health = await client.get(f"{info['url']}/healthz")
                if health.status_code != 200:
                    entry["status"] = "degraded"
                    entry["error"] = f"Health check returned {health.status_code}"
                    collectors.append(entry)
                    continue

                token = str(info.get("token") or "").strip()
                if not token:
                    entry["status"] = "degraded"
                    entry["error"] = _COLLECTOR_TOKEN_MISSING_ERROR
                    collectors.append(entry)
                    continue

                try:
                    metadata = await client.get(
                        f"{info['url']}/info",
                        headers=_collector_auth_headers(token),
                    )
                    metadata.raise_for_status()
                    payload = metadata.json()
                    metadata_payload = payload if isinstance(payload, dict) else {}
                    entry["status"] = "online"
                    for field in ("node", "version", "capabilities", "builtin_scripts", "max_timeout", "cluster"):
                        value = metadata_payload.get(field)
                        if value not in (None, ""):
                            entry[field] = value
                except Exception as exc:
                    entry["status"] = "degraded"
                    entry["error"] = str(exc)
            except Exception as exc:
                entry["status"] = "offline"
                entry["error"] = str(exc)
            collectors.append(entry)
    return {"collectors": collectors, "total": len(collectors)}


@router.post("/intelligence/collectors")
def register_intelligence_collector(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Register a new collector agent (persisted to DB, cached in memory)."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    name = body.get("name")
    url = body.get("url")
    if not name or not url:
        raise HTTPException(status_code=400, detail="'name' and 'url' required")
    validated_url = _validate_collector_url(url)
    token = str(body.get("token", "")).strip()
    if not token:
        raise HTTPException(status_code=400, detail="'token' is required")
    expected_id = _build_namespace_scoped_collector_id(namespace, name)
    now = datetime.now(UTC)
    # Persist to DB (hash the token)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    encrypted_token = _encrypt_collector_token(token)
    with db_session() as ses:
        existing = ses.query(IntelligenceCollectorRow).filter_by(namespace=namespace, id=expected_id).first()
        if existing is None:
            existing = ses.query(IntelligenceCollectorRow).filter_by(namespace=namespace, name=name).first()
        if existing:
            cid = existing.id
            existing.name = name
            existing.namespace = namespace
            existing.url = validated_url
            existing.token_hash = token_hash
            existing.encrypted_token = encrypted_token
            existing.cluster = body.get("cluster", "unknown")
            existing.tags = body.get("tags", [])
            existing.registered_by = user.get("sub", "unknown") if isinstance(user, dict) else "unknown"
        else:
            cid = expected_id
            if ses.query(IntelligenceCollectorRow).filter_by(id=cid).first():
                raise HTTPException(status_code=409, detail="Collector identifier collision. Rename the collector and try again.")
            ses.add(IntelligenceCollectorRow(
                id=cid, namespace=namespace, name=name, url=validated_url, token_hash=token_hash, encrypted_token=encrypted_token,
                cluster=body.get("cluster", "unknown"), tags=body.get("tags", []),
                registered_at=now,
                registered_by=user.get("sub", "unknown") if isinstance(user, dict) else "unknown",
            ))
    # Update in-memory cache (plaintext token kept for outbound requests)
    _set_namespaced_collector(namespace, cid, {
        "id": cid,
        "name": name,
        "url": validated_url,
        "token": token,
        "cluster": body.get("cluster", "unknown"),
        "registered_at": now.isoformat(),
        "tags": body.get("tags", []),
    })
    safe_record_audit(
        action="intelligence.collector.register",
        principal=user,
        resource_kind="intelligence-collector",
        resource_name=cid,
        resource_namespace=namespace,
        detail={"collector_name": name, "cluster": body.get("cluster", "unknown")},
    )
    return {"id": cid, "namespace": namespace, "status": "registered", "name": name, "url": validated_url, "token": "***"}


@router.delete("/intelligence/collectors/{collector_id}")
def unregister_intelligence_collector(
    collector_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Unregister a collector agent (removes from DB and cache)."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    collectors = _get_namespaced_collectors(namespace)
    if collector_id not in collectors:
        raise HTTPException(status_code=404, detail="Collector not found")
    # Remove from DB
    with db_session() as ses:
        row = ses.query(IntelligenceCollectorRow).filter_by(id=collector_id, namespace=namespace).first()
        if row:
            ses.delete(row)
    # Remove from cache
    _remove_namespaced_collector(namespace, collector_id)
    safe_record_audit(
        action="intelligence.collector.unregister",
        principal=user,
        resource_kind="intelligence-collector",
        resource_name=collector_id,
        resource_namespace=namespace,
    )
    return {"status": "unregistered", "id": collector_id, "namespace": namespace}


@router.post("/intelligence/collect")
async def submit_collection_task(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """
    Submit a collection task to one or more collectors.

    Body:
    {
        "collector_id": "my-cluster",      # or "all" for fan-out
        "script": "kubectl get pods -A",   # custom script
        "builtin": "cluster_overview",     # OR use a built-in script
        "type": "bash",                    # bash or python
        "timeout": 30
    }
    """
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")

    collector_id = str(body.get("collector_id") or "").strip()
    if not collector_id:
        raise HTTPException(status_code=400, detail="'collector_id' required")
    task_id = str(uuid.uuid4())[:8]
    payload = _normalize_collection_payload(body)

    # Determine targets
    targets = _resolve_collection_targets(namespace, collector_id)

    # Execute
    results = {}
    async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT, trust_env=False) as client:
        for cid, info in targets.items():
            token = str(info.get("token") or "").strip()
            if not token:
                results[cid] = {"status": "error", "error": _COLLECTOR_TOKEN_MISSING_ERROR}
                continue
            try:
                resp = await client.post(
                    f"{info['url']}/collect",
                    headers=_collector_auth_headers(token),
                    json=payload,
                )
                resp.raise_for_status()
                results[cid] = resp.json()
            except Exception as e:
                results[cid] = {"status": "error", "error": str(e)}

    task_record = _build_intelligence_task_record(
        namespace,
        task_id=task_id,
        collector_id=collector_id,
        payload=payload,
        results=results,
        submitted_by=user.get("sub", "unknown") if isinstance(user, dict) else "unknown",
    )
    with _tasks_lock:
        _collection_tasks[task_id] = task_record
    _enforce_collection_tasks_cap()
    _persist_task(task_record)
    safe_record_audit(
        action="intelligence.task.submit",
        principal=user,
        resource_kind="intelligence-task",
        resource_name=task_id,
        resource_namespace=namespace,
        detail={"collector_id": collector_id, "builtin": payload.get("builtin")},
    )
    return task_record


@router.get("/intelligence/tasks")
def list_collection_tasks(
    limit: int = 50,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """List recent collection tasks."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        rows = (
            ses.query(IntelligenceTaskRow)
            .filter_by(namespace=namespace)
            .order_by(IntelligenceTaskRow.submitted_at.desc())
            .limit(limit)
            .all()
        )
        tasks = [row.to_dict() for row in rows]
        total = ses.query(IntelligenceTaskRow).filter_by(namespace=namespace).count()
    return {"tasks": tasks, "total": total}


@router.get("/intelligence/tasks/{task_id}")
def get_collection_task(
    task_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Get a specific collection task and its results."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        row = ses.query(IntelligenceTaskRow).filter_by(task_id=task_id, namespace=namespace).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row.to_dict()


@router.delete("/intelligence/tasks/{task_id}", response_model=DeleteResponse)
def delete_collection_task(
    task_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete a specific collection task and remove it from intelligence context caches."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    deleted_ids, _missing_ids = _delete_collection_tasks(namespace, [task_id])
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="Task not found")
    safe_record_audit(
        action="intelligence.task.delete",
        principal=user,
        resource_kind="intelligence-task",
        resource_name=task_id,
        resource_namespace=namespace,
    )
    return {"status": "deleted", "kind": "intelligence-task", "name": task_id, "namespace": namespace}


@router.post("/intelligence/tasks/delete")
def bulk_delete_collection_tasks(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete multiple collection tasks in one request."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    task_ids = body.get("task_ids")
    if not isinstance(task_ids, list):
        raise HTTPException(status_code=400, detail="'task_ids' must be a list")
    deleted_ids, missing_ids = _delete_collection_tasks(namespace, task_ids)
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="No matching tasks found")
    safe_record_audit(
        action="intelligence.task.delete.bulk",
        principal=user,
        resource_kind="intelligence-task",
        resource_name="bulk",
        resource_namespace=namespace,
        detail={"deleted_ids": deleted_ids[:20], "missing_ids": missing_ids[:20], "deleted": len(deleted_ids)},
    )
    return {
        "status": "deleted",
        "kind": "intelligence-task",
        "namespace": namespace,
        "deleted": len(deleted_ids),
        "requested": len(deleted_ids) + len(missing_ids),
        "deleted_ids": deleted_ids,
        "missing_ids": missing_ids,
    }


# =========================================================================
# Intelligence Schedules & Alerts API  (PostgreSQL-backed)
# =========================================================================


def _normalize_schedule_configuration(
    body: dict[str, Any],
    *,
    namespace: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(current or {})
    merged.update(body)

    name = str(merged.get("name") or "").strip()
    cron_expr = str(merged.get("cron") or "").strip()
    if not name or not cron_expr:
        raise HTTPException(status_code=400, detail="'name' and 'cron' required")
    try:
        from croniter import croniter

        croniter(cron_expr)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}") from exc

    payload = _normalize_collection_payload(merged)
    collector_id = str(merged.get("collector_id") or "all").strip() or "all"
    if collector_id != "all":
        _resolve_collection_targets(namespace, collector_id)
    agent_name = _ensure_intelligence_agent_exists(merged.get("agent_name"), namespace)
    return {
        "name": name,
        "cron": cron_expr,
        "collector_id": collector_id,
        "builtin": payload.get("builtin"),
        "script": payload.get("script"),
        "script_type": payload.get("type", "bash"),
        "timeout": payload.get("timeout", 30),
        "agent_name": agent_name,
        "enabled": bool(merged.get("enabled", True)),
    }


def _normalize_alert_configuration(
    body: dict[str, Any],
    *,
    namespace: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(current or {})
    merged.update(body)

    name = str(merged.get("name") or "").strip()
    condition_type = str(merged.get("condition_type") or "").strip()
    if not name or condition_type not in _INTELLIGENCE_ALERT_CONDITION_TYPES:
        raise HTTPException(status_code=400, detail="'name' and valid 'condition_type' required")

    condition_value = str(merged.get("condition_value") or "")
    if condition_type == "regex":
        try:
            re.compile(condition_value)
        except re.error as exc:
            raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}") from exc

    action = str(merged.get("action") or "notify").strip() or "notify"
    if action not in _INTELLIGENCE_ALERT_ACTIONS:
        raise HTTPException(status_code=400, detail="Action must be 'notify' or 'invoke_agent'")

    schedule_id = str(merged.get("schedule_id") or "").strip() or None
    if schedule_id:
        with db_session() as ses:
            linked_schedule = ses.query(IntelligenceScheduleRow).filter_by(id=schedule_id, namespace=namespace).first()
        if linked_schedule is None:
            raise HTTPException(status_code=400, detail=f"Schedule '{schedule_id}' was not found in namespace '{namespace}'")

    agent_name = _ensure_intelligence_agent_exists(merged.get("agent_name"), namespace)
    if action == "invoke_agent" and not agent_name:
        raise HTTPException(status_code=400, detail="'agent_name' is required when action is 'invoke_agent'")

    prompt_template = str(merged.get("prompt_template") or "").strip() or None
    if action == "invoke_agent" and not prompt_template:
        prompt_template = "Intelligence alert:\n\n{{output}}"

    return {
        "name": name,
        "schedule_id": schedule_id,
        "condition_type": condition_type,
        "condition_value": condition_value,
        "action": action,
        "agent_name": agent_name,
        "prompt_template": prompt_template if action == "invoke_agent" else None,
        "enabled": bool(merged.get("enabled", True)),
    }


@router.get("/intelligence/schedules")
def list_intelligence_schedules(namespace: str = "default", user=Depends(verify_token)):
    """List all collection schedules."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        rows = (
            ses.query(IntelligenceScheduleRow)
            .filter_by(namespace=namespace)
            .order_by(IntelligenceScheduleRow.created_at.desc())
            .all()
        )
        items = [r.to_dict() for r in rows]
    return {"schedules": items, "total": len(items)}


@router.post("/intelligence/schedules")
def create_intelligence_schedule(body: dict[str, Any] = Body(...), namespace: str = "default", user=Depends(verify_token)):
    """Create a recurring collection schedule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    config = _normalize_schedule_configuration(body, namespace=namespace)
    sid = str(uuid.uuid4())[:8]
    from croniter import croniter as _croniter
    nxt = _croniter(config["cron"], datetime.now(UTC)).get_next(datetime)
    row = IntelligenceScheduleRow(
        id=sid,
        namespace=namespace,
        name=config["name"],
        cron=config["cron"],
        collector_id=config["collector_id"],
        builtin=config["builtin"],
        script=config["script"],
        script_type=config["script_type"],
        timeout=config["timeout"],
        agent_name=config["agent_name"],
        enabled=config["enabled"],
        created_by=user.get("sub", "unknown") if isinstance(user, dict) else "unknown",
        next_run=nxt,
    )
    with db_session() as ses:
        ses.add(row)
        ses.flush()
        result = row.to_dict()
    safe_record_audit(
        action="intelligence.schedule.create",
        principal=user,
        resource_kind="intelligence-schedule",
        resource_name=sid,
        resource_namespace=namespace,
        detail={"collector_id": config["collector_id"], "builtin": config["builtin"]},
    )
    return result


@router.put("/intelligence/schedules/{schedule_id}")
def update_intelligence_schedule(
    schedule_id: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Update a collection schedule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    with db_session() as ses:
        row = ses.query(IntelligenceScheduleRow).filter_by(id=schedule_id, namespace=namespace).first()
        if not row:
            raise HTTPException(status_code=404, detail="Schedule not found")
        config = _normalize_schedule_configuration(body, namespace=namespace, current=row.to_dict())
        row.name = config["name"]
        row.cron = config["cron"]
        row.collector_id = config["collector_id"]
        row.builtin = config["builtin"]
        row.script = config["script"]
        row.script_type = config["script_type"]
        row.timeout = config["timeout"]
        row.agent_name = config["agent_name"]
        row.enabled = config["enabled"]
        try:
            from croniter import croniter

            row.next_run = croniter(config["cron"], datetime.now(UTC)).get_next(datetime)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}") from exc
        result = row.to_dict()
    safe_record_audit(
        action="intelligence.schedule.update",
        principal=user,
        resource_kind="intelligence-schedule",
        resource_name=schedule_id,
        resource_namespace=namespace,
        detail={"collector_id": result.get("collector_id"), "builtin": result.get("builtin")},
    )
    return result


@router.delete("/intelligence/schedules/{schedule_id}")
def delete_intelligence_schedule(schedule_id: str, namespace: str = "default", user=Depends(verify_token)):
    """Delete a collection schedule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    with db_session() as ses:
        row = ses.query(IntelligenceScheduleRow).filter_by(id=schedule_id, namespace=namespace).first()
        if not row:
            raise HTTPException(status_code=404, detail="Schedule not found")
        ses.delete(row)
    safe_record_audit(
        action="intelligence.schedule.delete",
        principal=user,
        resource_kind="intelligence-schedule",
        resource_name=schedule_id,
        resource_namespace=namespace,
    )
    return {"status": "deleted", "id": schedule_id, "namespace": namespace}


@router.get("/intelligence/alerts")
def list_intelligence_alerts(agent_name: str | None = None, namespace: str = "default", user=Depends(verify_token)):
    """List alert rules, optionally filtered by agent_name."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        q = ses.query(IntelligenceAlertRow).filter_by(namespace=namespace)
        if agent_name:
            q = q.filter_by(agent_name=agent_name)
        rows = q.order_by(IntelligenceAlertRow.created_at.desc()).all()
        items = [r.to_dict() for r in rows]
    return {"alerts": items, "total": len(items)}


@router.post("/intelligence/alerts")
def create_intelligence_alert(body: dict[str, Any] = Body(...), namespace: str = "default", user=Depends(verify_token)):
    """Create an alert rule on collection output."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    config = _normalize_alert_configuration(body, namespace=namespace)
    aid = str(uuid.uuid4())[:8]
    row = IntelligenceAlertRow(
        id=aid,
        namespace=namespace,
        name=config["name"],
        schedule_id=config["schedule_id"],
        condition_type=config["condition_type"],
        condition_value=config["condition_value"],
        action=config["action"],
        agent_name=config["agent_name"],
        prompt_template=config["prompt_template"],
        enabled=config["enabled"],
        created_by=user.get("sub", "unknown") if isinstance(user, dict) else "unknown",
    )
    with db_session() as ses:
        ses.add(row)
        ses.flush()
        result = row.to_dict()
    safe_record_audit(
        action="intelligence.alert.create",
        principal=user,
        resource_kind="intelligence-alert",
        resource_name=aid,
        resource_namespace=namespace,
        detail={"schedule_id": config["schedule_id"], "action": config["action"]},
    )
    return result


@router.put("/intelligence/alerts/{alert_id}")
def update_intelligence_alert(
    alert_id: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Update an alert rule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    with db_session() as ses:
        row = ses.query(IntelligenceAlertRow).filter_by(id=alert_id, namespace=namespace).first()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        config = _normalize_alert_configuration(body, namespace=namespace, current=row.to_dict())
        row.name = config["name"]
        row.schedule_id = config["schedule_id"]
        row.condition_type = config["condition_type"]
        row.condition_value = config["condition_value"]
        row.action = config["action"]
        row.agent_name = config["agent_name"]
        row.prompt_template = config["prompt_template"]
        row.enabled = config["enabled"]
        result = row.to_dict()
    safe_record_audit(
        action="intelligence.alert.update",
        principal=user,
        resource_kind="intelligence-alert",
        resource_name=alert_id,
        resource_namespace=namespace,
        detail={"schedule_id": result.get("schedule_id"), "action": result.get("action")},
    )
    return result


@router.delete("/intelligence/alerts/{alert_id}")
def delete_intelligence_alert(alert_id: str, namespace: str = "default", user=Depends(verify_token)):
    """Delete an alert rule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    with db_session() as ses:
        row = ses.query(IntelligenceAlertRow).filter_by(id=alert_id, namespace=namespace).first()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        ses.delete(row)
    safe_record_audit(
        action="intelligence.alert.delete",
        principal=user,
        resource_kind="intelligence-alert",
        resource_name=alert_id,
        resource_namespace=namespace,
    )
    return {"status": "deleted", "id": alert_id, "namespace": namespace}


@router.get("/intelligence/alerts/history")
def list_alert_history(limit: int = 50, namespace: str = "default", user=Depends(verify_token)):
    """Get recent alert trigger history."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        rows = (
            ses.query(AlertHistoryRow)
            .filter_by(namespace=namespace)
            .order_by(AlertHistoryRow.triggered_at.desc())
            .limit(min(limit, 500))
            .all()
        )
        items = [r.to_dict() for r in rows]
    return {"history": items, "total": len(items)}


@router.post("/intelligence/prompt-context")
async def get_intelligence_prompt_context(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """
    Fetch the latest intelligence output formatted as a prompt context string.
    Optionally runs a fresh collection if no recent tasks exist.
    """
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    collector_id = str(body.get("collector_id") or "all").strip() or "all"
    payload = _normalize_collection_payload(body)
    # Try to find a recent matching task
    matching = [
        task
        for task in _list_namespaced_tasks(namespace)
        if _task_matches_request(task, collector_id, payload)
    ][:1]
    if matching:
        task = matching[0]
    else:
        # Run a fresh collection
        targets = _resolve_collection_targets(namespace, collector_id)
        results: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT, trust_env=False) as client:
            for cid, info in targets.items():
                try:
                    resp = await client.post(
                        f"{info['url']}/collect",
                        headers={"Authorization": f"Bearer {info.get('token', '')}"},
                        json=payload,
                    )
                    resp.raise_for_status()
                    results[cid] = resp.json()
                except Exception as e:
                    results[cid] = {"status": "error", "error": str(e)}
        tid = str(uuid.uuid4())[:8]
        task = _build_intelligence_task_record(
            namespace,
            task_id=tid,
            collector_id=collector_id,
            payload=payload,
            results=results,
            submitted_by=str(user.get("sub") or "prompt-context") if isinstance(user, dict) else "prompt-context",
        )
        with _tasks_lock:
            _collection_tasks[tid] = task
        _enforce_collection_tasks_cap()
        _persist_task(task)
        safe_record_audit(
            action="intelligence.prompt-context.collect",
            principal=user,
            resource_kind="intelligence-task",
            resource_name=tid,
            resource_namespace=namespace,
            detail={"collector_id": collector_id, "builtin": payload.get("builtin")},
        )
    # Format as prompt context
    parts = [f"## Cluster Intelligence ({payload.get('builtin') or 'custom script'})"]
    parts.append(f"Collected at: {task.get('submitted_at', 'unknown')}")
    parts.append("")
    for cid, result in task.get("results", {}).items():
        parts.append(f"### Collector: {cid}")
        if result.get("status") == "completed":
            stdout = result.get("stdout", "").strip()
            if stdout:
                parts.append(f"```\n{stdout[:8000]}\n```")
            else:
                parts.append("*(no output)*")
        else:
            parts.append(f"Status: {result.get('status', 'unknown')}")
            if result.get("error"):
                parts.append(f"Error: {result['error']}")
        parts.append("")
    return {
        "context": "\n".join(parts),
        "task_id": task.get("task_id"),
        "collector_id": collector_id,
        "namespace": namespace,
    }


# ─── Background intelligence scheduler ───────────────────────────────────

def _evaluate_alert_condition(alert: dict[str, Any], result: dict[str, Any]) -> bool:
    """Check whether a collection result triggers the alert condition."""
    ctype = alert.get("condition_type", "")
    cvalue = str(alert.get("condition_value", ""))
    stdout = result.get("stdout", "")
    if ctype == "contains":
        return cvalue in stdout
    if ctype == "not_contains":
        return cvalue not in stdout
    if ctype == "exit_code":
        try:
            return result.get("exit_code") == int(cvalue)
        except (ValueError, TypeError):
            return False
    if ctype == "regex":
        try:
            return bool(re.search(cvalue, stdout))
        except re.error:
            return False
    return False


async def _run_scheduled_collection(schedule: dict[str, Any]) -> dict[str, Any] | None:
    """Execute a collection for a schedule entry and return the task record."""
    namespace = _normalize_intelligence_namespace(schedule.get("namespace"))
    collector_id = schedule.get("collector_id", "all")
    payload: dict[str, Any] = {"timeout": schedule.get("timeout", 30)}
    if schedule.get("builtin"):
        payload["builtin"] = schedule["builtin"]
    elif schedule.get("script"):
        payload["script"] = schedule["script"]
        payload["type"] = schedule.get("script_type", "bash")
    else:
        return None
    try:
        targets = _resolve_collection_targets(namespace, collector_id)
    except HTTPException:
        return None
    results: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT, trust_env=False) as client:
        for cid, info in targets.items():
            try:
                resp = await client.post(
                    f"{info['url']}/collect",
                    headers={"Authorization": f"Bearer {info.get('token', '')}"},
                    json=payload,
                )
                resp.raise_for_status()
                results[cid] = resp.json()
            except Exception as e:
                results[cid] = {"status": "error", "error": str(e)}
    tid = str(uuid.uuid4())[:8]
    task = _build_intelligence_task_record(
        namespace,
        task_id=tid,
        collector_id=collector_id,
        payload=payload,
        results=results,
        submitted_by=f"schedule:{schedule.get('id', 'unknown')}",
    )
    with _tasks_lock:
        _collection_tasks[tid] = task
    _enforce_collection_tasks_cap()
    _persist_task(task)
    return task


async def _fire_alert(alert_dict: dict[str, Any], task: dict[str, Any], matching_output: str):
    """Process a fired alert — log to history (DB) and optionally invoke an agent."""
    namespace = _normalize_intelligence_namespace(alert_dict.get("namespace"))
    now = datetime.now(UTC)
    snippet = matching_output[:500] if matching_output else ""
    hid = str(uuid.uuid4())[:8]
    history_entry = AlertHistoryRow(
        id=hid,
        namespace=namespace,
        alert_id=alert_dict["id"],
        alert_name=alert_dict["name"],
        triggered_at=now,
        condition_matched=f"{alert_dict['condition_type']}:{alert_dict['condition_value']}",
        action_taken=alert_dict.get("action", "notify"),
        task_id=task.get("task_id"),
        snippet=snippet,
    )
    if alert_dict.get("action") == "invoke_agent" and alert_dict.get("agent_name"):
        agent_name = alert_dict["agent_name"]
        template = alert_dict.get("prompt_template", "Intelligence alert:\n\n{{output}}")
        prompt = template.replace("{{output}}", matching_output[:4000])
        try:
            # Direct in-process call to agent runtime — avoids HTTP round-trip,
            # hardcoded port, and fake auth token.
            runtime_url = agent_runtime_url(agent_name, namespace)
            request_payload = {"prompt": prompt, "autonomous": True}
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                resp = await client.post(
                    f"{runtime_url}/invoke",
                    json=request_payload,
                    headers=runtime_auth_headers({"x-request-id": str(uuid.uuid4())}),
                )
                history_entry.agent_invoked = agent_name
                history_entry.invoke_status = resp.status_code
        except Exception as exc:
            history_entry.agent_invoked = agent_name
            history_entry.invoke_error = str(exc)
            logger.warning("Alert auto-invoke failed for agent %s: %s", agent_name, exc)
    with db_session() as ses:
        # Update alert row
        alert_row = ses.query(IntelligenceAlertRow).filter_by(id=alert_dict["id"], namespace=namespace).first()
        if alert_row:
            alert_row.last_triggered = now
            alert_row.trigger_count = (alert_row.trigger_count or 0) + 1
        ses.add(history_entry)
        # Trim old history
        total = ses.query(AlertHistoryRow).filter_by(namespace=namespace).count()
        if total > _ALERT_HISTORY_CAP:
            oldest = (
                ses.query(AlertHistoryRow)
                .filter_by(namespace=namespace)
                .order_by(AlertHistoryRow.triggered_at.asc())
                .limit(total - _ALERT_HISTORY_CAP)
                .all()
            )
            for old in oldest:
                ses.delete(old)
    logger.info("Alert '%s' triggered (task %s)", alert_dict["name"], task.get("task_id"))


async def _intelligence_scheduler_loop():
    """Background loop that polls schedules every 30s and fires due collections."""
    logger.info("Intelligence scheduler started.")
    while not _SHUTDOWN.is_set():
        try:
            await asyncio.sleep(30)
            now = datetime.now(UTC)
            # Load schedules from DB
            with db_session() as ses:
                schedules = ses.query(IntelligenceScheduleRow).filter_by(enabled=True).all()
                sched_dicts = [r.to_dict() for r in schedules]
            for sched in sched_dicts:
                next_run_str = sched.get("next_run")
                if not next_run_str:
                    continue
                try:
                    next_run = datetime.fromisoformat(next_run_str)
                    if next_run.tzinfo is None:
                        next_run = next_run.replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    continue
                if now < next_run:
                    continue
                sid = sched["id"]
                schedule_namespace = _normalize_intelligence_namespace(sched.get("namespace"))
                # Re-check enabled right before execution (may have been toggled since loop start)
                with db_session() as ses:
                    still_enabled = ses.query(IntelligenceScheduleRow).filter_by(
                        id=sid,
                        namespace=schedule_namespace,
                        enabled=True,
                    ).first()
                if not still_enabled:
                    logger.info("Schedule '%s' (id=%s) was disabled since loop start, skipping.", sched.get("name"), sid)
                    continue
                logger.info("Scheduled collection '%s' (id=%s) is due.", sched.get("name"), sid)
                task = await _run_scheduled_collection(sched)
                # Update schedule row in DB
                try:
                    from croniter import croniter
                    nxt = croniter(sched["cron"], now).get_next(datetime)
                except Exception:
                    nxt = None
                with db_session() as ses:
                    row = ses.query(IntelligenceScheduleRow).filter_by(id=sid, namespace=schedule_namespace).first()
                    if row:
                        row.last_run = now
                        row.next_run = nxt
                if not task:
                    continue
                # Load alerts from DB and evaluate
                with db_session() as ses:
                    alerts = ses.query(IntelligenceAlertRow).filter_by(enabled=True, namespace=schedule_namespace).all()
                    alert_dicts = [a.to_dict() for a in alerts]
                for alert in alert_dicts:
                    linked_schedule = alert.get("schedule_id")
                    if linked_schedule and linked_schedule != sid:
                        continue
                    for _cid, result in task.get("results", {}).items():
                        if _evaluate_alert_condition(alert, result):
                            await _fire_alert(alert, task, result.get("stdout", ""))
                            break
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in intelligence scheduler loop")
    logger.info("Intelligence scheduler stopped.")
