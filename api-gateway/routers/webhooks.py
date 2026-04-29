"""Webhook receivers and workflow trigger endpoints."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import uuid
from typing import Any

from _core import (
    WebhookReceiverInfo,
    WebhookReceiverRequest,
    WebhookReceiverUpdateRequest,
    WebhookInvocationInfo,
    WorkflowTriggerInfo,
    WorkflowTriggerRequest,
    WorkflowTriggerUpdateRequest,
    TriggerExecutionInfo,
    count_recent_webhook_invocations,
    create_webhook_receiver,
    create_workflow_trigger,
    delete_webhook_receiver,
    delete_workflow_trigger,
    get_webhook_receiver,
    get_workflow_trigger,
    list_webhook_invocations,
    list_webhook_receivers,
    list_workflow_triggers,
    list_trigger_executions,
    record_webhook_invocation,
    record_trigger_execution,
    update_webhook_receiver,
    update_workflow_trigger,
    logger,
)
from auth_middleware import (
    ensure_namespace_access,
    ensure_role,
    verify_token,
    verify_webhook_signature,
)
from webhook_security import (
    check_webhook_rate_limit,
    read_limited_body,
    resolve_trusted_client_ip,
    sanitize_webhook_payload,
    verify_webhook_timestamp,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["webhooks"])

# ---------------------------------------------------------------------------
# Webhook Receiver CRUD
# ---------------------------------------------------------------------------

@router.get("/webhooks", response_model=list[WebhookReceiverInfo])
def list_webhooks(namespace: str = "default", user=Depends(verify_token)):
    ensure_role(user, "viewer")
    ensure_namespace_access(user, namespace)
    rows = list_webhook_receivers(namespace)
    return [WebhookReceiverInfo.model_validate(r) for r in rows]


@router.post("/webhooks", status_code=201, response_model=WebhookReceiverInfo)
def create_webhook(body: WebhookReceiverRequest, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    row = create_webhook_receiver(
        namespace=namespace,
        name=body.name,
        secret_ref=body.secret_ref,
        ip_allowlist=body.ip_allowlist or [],
        rate_limit=body.rate_limit or 60,
        max_payload_bytes=body.max_payload_bytes or 1048576,
        enabled=body.enabled if body.enabled is not None else True,
    )
    return WebhookReceiverInfo.model_validate(row)


@router.get("/webhooks/{name}", response_model=WebhookReceiverInfo)
def get_webhook(name: str, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    row = get_webhook_receiver(namespace, name)
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")
    return WebhookReceiverInfo.model_validate(row)


@router.put("/webhooks/{name}", response_model=WebhookReceiverInfo)
def update_webhook(name: str, body: WebhookReceiverUpdateRequest, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    existing = get_webhook_receiver(namespace, name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")
    row = update_webhook_receiver(
        namespace=namespace,
        name=name,
        secret_ref=body.secret_ref,
        ip_allowlist=body.ip_allowlist,
        rate_limit=body.rate_limit,
        max_payload_bytes=body.max_payload_bytes,
        enabled=body.enabled,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")
    return WebhookReceiverInfo.model_validate(row)


@router.delete("/webhooks/{name}", status_code=204)
def delete_webhook(name: str, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    deleted = delete_webhook_receiver(namespace, name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")
    return None

# ---------------------------------------------------------------------------
# Webhook Invoke (PUBLIC endpoint)
# ---------------------------------------------------------------------------

@router.post("/webhooks/{name}/invoke")
async def invoke_webhook(
    name: str,
    raw_request: Request,
    namespace: str = "default",
    x_KUBESYNAPSE_signature: str | None = Header(default=None, alias="X-kubesynapse-Signature"),
    x_KUBESYNAPSE_timestamp: str | None = Header(default=None, alias="X-kubesynapse-Timestamp"),
):
    """Public endpoint for external webhook calls. No auth token required.

    Security controls applied:
    - HMAC-SHA256 signature verification (timing-safe via compare_digest)
    - Replay attack prevention via X-kubesynapse-Timestamp
    - In-memory + DB rate limiting (defense in depth)
    - Payload size limits (DoS protection)
    - IP allowlisting (defense in depth)
    - Payload sanitization (removes NoSQL injection keys)
    """
    invocation_id = str(uuid.uuid4())

    # Load webhook config
    wh = get_webhook_receiver(namespace, name)
    if wh is None:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")
    if not wh.get("enabled", True):
        raise HTTPException(status_code=403, detail="Webhook receiver is disabled")

    # Read payload with hard absolute limit to prevent memory DoS.
    # The webhook-specific max_payload_bytes is enforced here.
    max_bytes = int(wh.get("max_payload_bytes", 1048576))
    absolute_max = min(max_bytes, 16_777_216)  # 16 MiB absolute ceiling
    try:
        raw_body = await read_limited_body(raw_request, absolute_max + 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to read request body") from exc
    if len(raw_body) > max_bytes:
        raise HTTPException(status_code=413, detail="Payload exceeds maximum size")

    # HMAC signature verification
    signature_verified = False
    secret_ref = str(wh.get("secret_ref", "")).strip()
    if secret_ref:
        secret = _resolve_webhook_secret(secret_ref)
        if secret:
            if not x_KUBESYNAPSE_signature:
                raise HTTPException(status_code=401, detail="Missing X-kubesynapse-Signature header")
            if not verify_webhook_signature(raw_body, x_KUBESYNAPSE_signature, secret):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
            signature_verified = True
            # Prevent replay attacks once signature is valid
            verify_webhook_timestamp(x_KUBESYNAPSE_timestamp)
        else:
            logger.warning("Webhook %s/%s references secret_ref '%s' but secret could not be resolved", namespace, name, secret_ref)

    # IP allowlist check
    client_ip = resolve_trusted_client_ip(raw_request)
    ip_allowlist = wh.get("ip_allowlist") or []
    if ip_allowlist:
        if not _ip_matches_allowlist(client_ip, ip_allowlist):
            raise HTTPException(status_code=403, detail="IP not allowed")

    # Rate limiting: in-memory first (prevents race-condition bypass), then DB
    rate_limit = int(wh.get("rate_limit", 60))
    check_webhook_rate_limit(f"{namespace}/{name}", rate_limit)
    recent_count = count_recent_webhook_invocations(namespace, name, 60)
    if recent_count >= rate_limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Try to parse JSON body for logging/triggering
    parsed_payload: dict[str, Any] | None = None
    try:
        parsed_payload = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        parsed_payload = None

    # SECURITY: Sanitize payload to remove potentially dangerous keys
    sanitized_payload = sanitize_webhook_payload(parsed_payload) if isinstance(parsed_payload, dict) else parsed_payload

    # Record invocation
    record_webhook_invocation(
        namespace=namespace,
        webhook_name=name,
        event_id=invocation_id,
        source_ip=client_ip,
        signature_valid=signature_verified,
        payload_size=len(raw_body),
        payload_snippet=json.dumps(sanitized_payload, ensure_ascii=False, default=str)[:1024] if sanitized_payload is not None else None,
        headers_json={
            "x-kubesynapse-signature-present": bool(x_KUBESYNAPSE_signature),
            "x-kubesynapse-timestamp-present": bool(x_KUBESYNAPSE_timestamp),
        },
    )

    # Dispatch matching triggers (placeholder for now)
    matched_trigger_count = _dispatch_matching_triggers(name, namespace, sanitized_payload)

    return JSONResponse(
        content={
            "status": "received",
            "invocation_id": invocation_id,
            "matched_triggers": matched_trigger_count,
        },
        status_code=200,
    )

# ---------------------------------------------------------------------------
# Webhook Invocation History
# ---------------------------------------------------------------------------

@router.get("/webhooks/{name}/history", response_model=list[WebhookInvocationInfo])
def get_webhook_history(name: str, namespace: str = "default", limit: int = 50, user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    rows = list_webhook_invocations(name, namespace, limit=min(limit, 200))
    return [WebhookInvocationInfo.model_validate(r) for r in rows]

# ---------------------------------------------------------------------------
# Workflow Trigger CRUD
# ---------------------------------------------------------------------------

@router.get("/workflow-triggers", response_model=list[WorkflowTriggerInfo])
def list_triggers(namespace: str = "default", user=Depends(verify_token)):
    ensure_role(user, "viewer")
    ensure_namespace_access(user, namespace)
    rows = list_workflow_triggers(namespace)
    return [WorkflowTriggerInfo.model_validate(r) for r in rows]


@router.post("/workflow-triggers", status_code=201, response_model=WorkflowTriggerInfo)
def create_trigger(body: WorkflowTriggerRequest, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    row = create_workflow_trigger(
        namespace=namespace,
        name=body.name,
        source_ref=body.source_ref,
        source_kind=body.source_kind or "WebhookReceiver",
        event_filter=body.event_filter,
        workflow_ref=body.workflow_ref,
        payload_mapping=body.payload_mapping,
        max_retries=body.max_retries or 0,
        backoff_seconds=body.backoff_seconds or 60,
        enabled=body.enabled if body.enabled is not None else True,
    )
    return WorkflowTriggerInfo.model_validate(row)


@router.get("/workflow-triggers/{name}", response_model=WorkflowTriggerInfo)
def get_trigger(name: str, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    row = get_workflow_trigger(namespace, name)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow trigger not found")
    return WorkflowTriggerInfo.model_validate(row)


@router.put("/workflow-triggers/{name}", response_model=WorkflowTriggerInfo)
def update_trigger(name: str, body: WorkflowTriggerUpdateRequest, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    existing = get_workflow_trigger(namespace, name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Workflow trigger not found")
    row = update_workflow_trigger(
        namespace=namespace,
        name=name,
        source_ref=body.source_ref,
        source_kind=body.source_kind,
        event_filter=body.event_filter,
        workflow_ref=body.workflow_ref,
        payload_mapping=body.payload_mapping,
        max_retries=body.max_retries,
        backoff_seconds=body.backoff_seconds,
        enabled=body.enabled,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow trigger not found")
    return WorkflowTriggerInfo.model_validate(row)


@router.delete("/workflow-triggers/{name}", status_code=204)
def delete_trigger(name: str, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    deleted = delete_workflow_trigger(namespace, name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow trigger not found")
    return None

# ---------------------------------------------------------------------------
# Trigger Execution History
# ---------------------------------------------------------------------------

@router.get("/workflow-triggers/{name}/history", response_model=list[TriggerExecutionInfo])
def get_trigger_history(name: str, namespace: str = "default", limit: int = 50, user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    rows = list_trigger_executions(name, namespace, limit=min(limit, 200))
    return [TriggerExecutionInfo.model_validate(r) for r in rows]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or direct connection.

    DEPRECATED: Use resolve_trusted_client_ip from webhook_security instead.
    Kept for backward compatibility.
    """
    return resolve_trusted_client_ip(request)


def _ip_matches_allowlist(client_ip: str, allowlist: list[str]) -> bool:
    """Check if client_ip matches any CIDR in the allowlist."""
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for cidr in allowlist:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _resolve_webhook_secret(secret_ref: str) -> str | None:
    """Resolve a webhook secret from a Kubernetes Secret reference.
    
    Format: namespace/secret-name#key (e.g., 'default/webhook-secrets#hmac-key')
    Falls back to looking in environment variable if no Kubernetes API available.
    """
    if not secret_ref or not secret_ref.strip():
        return None

    # Try K8s Secret format: namespace/name#key
    if "/" in secret_ref:
        parts = secret_ref.split("/", 1)
        ns = parts[0].strip()
        rest = parts[1]
        if "#" in rest:
            name_part, key = rest.split("#", 1)
            name = name_part.strip()
            key = key.strip()
            try:
                from _core import kubernetes
                v1 = kubernetes.client.CoreV1Api()
                secret = v1.read_namespaced_secret(name=name, namespace=ns)
                if secret.data and key in secret.data:
                    import base64
                    return base64.b64decode(secret.data[key]).decode("utf-8")
            except Exception:
                pass

    # Fallback: environment variable reference
    env_var_name = secret_ref.replace("-", "_").replace(" ", "_").upper()
    import os
    return os.environ.get(env_var_name)

    return None


def _dispatch_matching_triggers(webhook_name: str, namespace: str, payload: dict[str, Any] | None) -> int:
    """Find and dispatch matching workflow triggers for a webhook event.
    
    For now this is a placeholder that logs and returns 0.
    Full implementation requires integration with the operator for actual workflow launching.
    """
    if not payload:
        return 0

    matched = 0
    try:
        triggers = list_workflow_triggers(namespace)
        for trigger in triggers:
            if not trigger.get("enabled", True):
                continue
            if trigger.get("source_kind") != "WebhookReceiver":
                continue
            if trigger.get("source_ref") != webhook_name:
                continue

            event_filter = trigger.get("event_filter") or {}
            if not _matches_event_filter(payload, event_filter):
                continue

            # Record trigger execution (will launch workflow in future operator integration)
            record_trigger_execution(
                trigger_name=str(trigger.get("name")),
                trigger_namespace=namespace,
                webhook_name=webhook_name,
                event_payload=payload,
                status="dispatched",
            )
            matched += 1
            logger.info(
                "Webhook trigger matched: %s/%s → workflow %s",
                namespace, trigger.get("name"), trigger.get("workflow_ref"),
            )
    except Exception as exc:
        logger.warning("Error dispatching webhook triggers for %s/%s: %s", namespace, webhook_name, exc)

    return matched


def _matches_event_filter(payload: dict[str, Any], event_filter: dict[str, Any]) -> bool:
    """Check if a payload matches an event filter specification.
    
    Supports simple key-value matching. For JSONPath, uses basic dot-notation traversal.
    """
    conditions = event_filter.get("conditions") or []
    if not conditions:
        # No conditions = match everything
        return True

    for condition in conditions:
        field = condition.get("field", "")
        operator = condition.get("operator", "equals")
        expected = condition.get("value")

        # Navigate dot-notation: "pull_request.number" → payload["pull_request"]["number"]
        value = payload
        for part in field.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break

        if operator == "equals":
            if str(value) != str(expected):
                return False
        elif operator == "not_equals":
            if str(value) == str(expected):
                return False
        elif operator == "contains":
            if expected not in str(value or ""):
                return False
        elif operator == "exists":
            if value is None:
                return False
        elif operator == "regex":
            import re
            if not re.search(str(expected), str(value or "")):
                return False

    return True
