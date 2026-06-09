"""Webhook receivers and workflow trigger endpoints."""
from __future__ import annotations

import ipaddress
import json
import time as time_module
import uuid
from typing import Any

from _core import (
    NATS_URL,
    TriggerExecutionInfo,
    WebhookInvocationInfo,
    WebhookReceiverInfo,
    WebhookReceiverRequest,
    WebhookReceiverUpdateRequest,
    WorkflowTriggerInfo,
    WorkflowTriggerRequest,
    WorkflowTriggerUpdateRequest,
    claim_trigger_execution,
    count_recent_webhook_invocations,
    create_webhook_receiver,
    create_workflow_trigger,
    delete_webhook_receiver,
    delete_workflow_trigger,
    get_webhook_receiver,
    get_workflow_trigger,
    list_trigger_executions,
    list_webhook_invocations,
    list_webhook_receivers,
    list_workflow_triggers,
    logger,
    record_trigger_execution,
    record_webhook_invocation,
    update_trigger_execution_status,
    update_webhook_invocation_matched_triggers,
    update_webhook_receiver,
    update_workflow_trigger,
)
from auth_middleware import (
    ensure_namespace_access,
    ensure_role,
    verify_token,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from webhook_security import (
    check_webhook_concurrency,
    check_webhook_rate_limit,
    read_limited_body,
    release_webhook_concurrency,
    resolve_trusted_client_ip,
    resolve_webhook_secret_with_key_id,
    sanitize_webhook_payload,
    validate_payload_against_schema,
    verify_provider_signature,
    verify_webhook_api_key,
    verify_webhook_timestamp,
)

router = APIRouter(tags=["webhooks"])

# Prometheus metrics (lazy-imported)
_webhook_invocations_total: Any = None
_webhook_rate_limit_rejections: Any = None
_webhook_signature_failures: Any = None
_webhook_dispatch_latency: Any = None


def _get_metric(name: str, doc: str, labelnames: tuple[str, ...] = ("namespace", "name")):
    global _webhook_invocations_total, _webhook_rate_limit_rejections, _webhook_signature_failures, _webhook_dispatch_latency
    try:
        from prometheus_client import Counter, Histogram
        if name == "webhook_invocations_total":
            if _webhook_invocations_total is None:
                _webhook_invocations_total = Counter("webhook_invocations_total", doc, labelnames)
            return _webhook_invocations_total
        if name == "webhook_rate_limit_rejections_total":
            if _webhook_rate_limit_rejections is None:
                _webhook_rate_limit_rejections = Counter("webhook_rate_limit_rejections_total", doc, labelnames)
            return _webhook_rate_limit_rejections
        if name == "webhook_signature_failures_total":
            if _webhook_signature_failures is None:
                _webhook_signature_failures = Counter("webhook_signature_failures_total", doc, labelnames)
            return _webhook_signature_failures
        if name == "webhook_dispatch_latency_seconds":
            if _webhook_dispatch_latency is None:
                _webhook_dispatch_latency = Histogram("webhook_dispatch_latency_seconds", doc, labelnames)
            return _webhook_dispatch_latency
    except Exception:
        return None


def _trigger_source_ref(body: WorkflowTriggerRequest | WorkflowTriggerUpdateRequest) -> str | None:
    return getattr(body, "source_ref", None) or getattr(body, "source_name", None)


def _trigger_target_refs(
    body: WorkflowTriggerRequest | WorkflowTriggerUpdateRequest,
    namespace: str,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract target workflow and agent refs from a trigger request.

    Returns (workflow_name, workflow_namespace, agent_name, agent_namespace).
    """
    workflow_ref = getattr(body, "workflow_ref", None) or {}
    agent_ref = getattr(body, "agent_ref", None) or {}
    workflow_name = str(workflow_ref.get("name") or getattr(body, "target_workflow_name", "") or "").strip() or None
    workflow_namespace = (
        str(workflow_ref.get("namespace") or getattr(body, "target_workflow_namespace", "") or namespace).strip()
        or namespace
    ) if workflow_name else None
    agent_name = str(agent_ref.get("name") or "").strip() or None
    agent_namespace = (
        str(agent_ref.get("namespace") or "").strip() or namespace
    ) if agent_name else None
    return workflow_name, workflow_namespace, agent_name, agent_namespace


# ---------------------------------------------------------------------------
# Webhook Receiver CRUD
# ---------------------------------------------------------------------------


@router.get("/namespaces/{namespace}/webhooks", response_model=list[WebhookReceiverInfo])
@router.get("/webhooks", response_model=list[WebhookReceiverInfo])
def list_webhooks(namespace: str = "default", user=Depends(verify_token)):
    ensure_role(user, "viewer")
    ensure_namespace_access(user, namespace)
    rows = list_webhook_receivers(namespace)
    return [WebhookReceiverInfo.model_validate(r) for r in rows]


@router.post("/namespaces/{namespace}/webhooks", status_code=201, response_model=WebhookReceiverInfo)
@router.post("/webhooks", status_code=201, response_model=WebhookReceiverInfo)
def create_webhook(body: WebhookReceiverRequest, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    row = create_webhook_receiver(
        namespace=namespace,
        name=body.name,
        secret_ref=body.secret_ref,
        additional_secrets=body.additional_secrets,
        provider=body.provider,
        api_key_enabled=body.api_key_enabled,
        ip_allowlist=body.ip_allowlist or [],
        rate_limit=body.rate_limit or 60,
        max_concurrent=body.max_concurrent or 0,
        max_payload_bytes=body.max_payload_bytes or 1048576,
        response_timeout_seconds=body.response_timeout_seconds or 30,
        payload_schema=body.payload_schema,
        enabled=body.enabled if body.enabled is not None else True,
    )
    return WebhookReceiverInfo.model_validate(row)


@router.get("/namespaces/{namespace}/webhooks/{name}", response_model=WebhookReceiverInfo)
@router.get("/webhooks/{name}", response_model=WebhookReceiverInfo)
def get_webhook(name: str, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    row = get_webhook_receiver(namespace, name)
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")
    return WebhookReceiverInfo.model_validate(row)


@router.put("/namespaces/{namespace}/webhooks/{name}", response_model=WebhookReceiverInfo)
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
        additional_secrets=body.additional_secrets,
        provider=body.provider,
        api_key_enabled=body.api_key_enabled,
        ip_allowlist=body.ip_allowlist,
        rate_limit=body.rate_limit,
        max_concurrent=body.max_concurrent,
        max_payload_bytes=body.max_payload_bytes,
        response_timeout_seconds=body.response_timeout_seconds,
        payload_schema=body.payload_schema,
        enabled=body.enabled,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")
    return WebhookReceiverInfo.model_validate(row)


@router.delete("/namespaces/{namespace}/webhooks/{name}", status_code=204)
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


@router.post("/namespaces/{namespace}/webhooks/{name}/invoke")
@router.post("/webhooks/{name}/invoke")
async def invoke_webhook(
    name: str,
    raw_request: Request,
    namespace: str = "default",
    dry_run: bool = Query(default=False),
    x_kubesynapse_signature: str | None = Header(default=None, alias="x-kubesynapse-signature"),
    x_kubesynapse_timestamp: str | None = Header(default=None, alias="x-kubesynapse-timestamp"),
    x_kubesynapse_key_id: str | None = Header(default=None, alias="x-kubesynapse-key-id"),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
    x_hub_signature_256: str | None = Header(default=None, alias="x-hub-signature-256"),
    x_slack_signature: str | None = Header(default=None, alias="x-slack-signature"),
    x_slack_request_timestamp: str | None = Header(default=None, alias="x-slack-request-timestamp"),
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
    x_pd_signature: str | None = Header(default=None, alias="x-pd-signature"),
):
    """Public endpoint for external webhook calls. No auth token required.

    Security controls applied:
    - Provider-specific signature verification (GitHub, Slack, Stripe, PagerDuty, or generic HMAC)
    - API key authentication (optional, per-webhook config)
    - Key rotation support via X-kubesynapse-Key-Id header
    - Replay attack prevention via timestamp
    - Redis-backed + DB rate limiting (defense in depth)
    - Concurrent invocation limits
    - Payload size limits (DoS protection)
    - IP allowlisting (defense in depth)
    - JSON Schema payload validation
    - Payload sanitization (removes NoSQL injection keys)
    - Dry-run mode for testing without dispatch
    """
    start_time = time_module.monotonic()
    invocation_id = str(uuid.uuid4())

    # Load webhook config
    wh = get_webhook_receiver(namespace, name)
    if wh is None:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")
    if not wh.get("enabled", True):
        raise HTTPException(status_code=403, detail="Webhook receiver is disabled")

    # Read payload with hard absolute limit to prevent memory DoS.
    max_bytes = int(wh.get("max_payload_bytes", 1048576))
    absolute_max = min(max_bytes, 16_777_216)  # 16 MiB absolute ceiling
    try:
        raw_body = await read_limited_body(raw_request, absolute_max + 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to read request body") from exc
    if len(raw_body) > max_bytes:
        raise HTTPException(status_code=413, detail="Payload exceeds maximum size")

    # Parse JSON payload
    parsed_payload: dict[str, Any] | None = None
    try:
        parsed_payload = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        parsed_payload = None

    # Determine the provider and collect provider-specific headers
    provider = str(wh.get("provider", "generic")).strip().lower()
    provider_signature: str | None = None
    provider_timestamp: str | None = None

    if provider == "github":
        provider_signature = x_hub_signature_256
    elif provider == "slack":
        provider_signature = x_slack_signature
        provider_timestamp = x_slack_request_timestamp
    elif provider == "stripe":
        provider_signature = stripe_signature
    elif provider == "pagerduty":
        provider_signature = x_pd_signature
    else:
        provider_signature = x_kubesynapse_signature

    # Resolve secret with key-id support for rotation
    provider_secret: str | None = None
    resolved_key_id: str | None = None
    additional_secrets = wh.get("additional_secrets") or {}

    if provider_signature:
        if x_kubesynapse_key_id and provider == "generic":
            secret, resolved_key_id = resolve_webhook_secret_with_key_id(
                str(wh.get("secret_ref", "")),
                additional_secrets,
                x_kubesynapse_key_id,
            )
            if secret:
                provider_secret = secret
        else:
            provider_secret = _resolve_webhook_secret(str(wh.get("secret_ref", ""))) or str(wh.get("secret_ref", ""))

    # Signature verification
    signature_verified = False
    if provider_secret and provider_signature:
        kwargs: dict[str, Any] = {}
        if provider_timestamp:
            kwargs["timestamp"] = provider_timestamp
        if verify_provider_signature(provider, raw_body, provider_signature, provider_secret, **kwargs):
            signature_verified = True
            # Replay protection: generic uses our own timestamp header;
            # slack validates its own timestamp inline in _verify_slack_signature;
            # stripe validates its own t= timestamp inside _verify_stripe_signature.
            if provider == "generic":
                verify_webhook_timestamp(x_kubesynapse_timestamp)
        else:
            metric = _get_metric("webhook_signature_failures_total", "Total webhook signature failures")
            if metric:
                metric.labels(namespace=namespace, name=name).inc()
            raise HTTPException(status_code=401, detail=f"Invalid webhook signature for provider '{provider}'")
    elif provider_signature:
        raise HTTPException(status_code=401, detail=f"Missing valid webhook signature for provider '{provider}'")

    # Optional API key auth
    api_key_enabled = wh.get("api_key_enabled", False)
    if api_key_enabled and not signature_verified:
        api_key_secret = _resolve_webhook_secret(str(wh.get("secret_ref", ""))) or str(wh.get("secret_ref", ""))
        if api_key_secret:
            if not verify_webhook_api_key(x_api_key, api_key_secret):
                raise HTTPException(status_code=401, detail="Invalid API key")
            signature_verified = True

    # IP allowlist check
    client_ip = resolve_trusted_client_ip(raw_request)
    ip_allowlist = wh.get("ip_allowlist") or []
    if ip_allowlist:
        if not _ip_matches_allowlist(client_ip, ip_allowlist):
            raise HTTPException(status_code=403, detail="IP not allowed")

    # Rate limiting: Redis-backed then DB
    rate_limit = int(wh.get("rate_limit", 60))
    try:
        check_webhook_rate_limit(f"{namespace}/{name}", rate_limit)
    except HTTPException:
        metric = _get_metric("webhook_rate_limit_rejections_total", "Total webhook rate limit rejections")
        if metric:
            metric.labels(namespace=namespace, name=name).inc()
        raise

    # DB-level rate limit check
    recent_count = count_recent_webhook_invocations(namespace, name, 60)
    if recent_count >= rate_limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Concurrent invocation limit
    max_concurrent = int(wh.get("max_concurrent", 0))
    if max_concurrent > 0:
        check_webhook_concurrency(f"{namespace}/{name}", max_concurrent)

    try:
        # Payload schema validation
        payload_schema = wh.get("payload_schema")
        if payload_schema and isinstance(parsed_payload, dict):
            schema_errors = validate_payload_against_schema(parsed_payload, payload_schema)
            if schema_errors:
                raise HTTPException(status_code=400, detail=f"Payload validation failed: {'; '.join(schema_errors)}")

        # SECURITY: Sanitize payload to remove potentially dangerous keys
        sanitized_payload = sanitize_webhook_payload(parsed_payload) if isinstance(parsed_payload, dict) else parsed_payload

        # Dry-run: validate but don't dispatch
        if dry_run:
            return JSONResponse(
                content={
                    "status": "dry_run",
                    "invocation_id": invocation_id,
                    "provider": provider,
                    "signature_verified": signature_verified,
                    "ip_allowed": not ip_allowlist or _ip_matches_allowlist(client_ip, ip_allowlist),
                    "rate_allowed": True,
                    "payload_valid": True,
                    "matched_triggers": _count_matching_triggers(name, namespace, sanitized_payload),
                    "dry_run": True,
                },
                status_code=200,
            )

        # Record invocation
        recorded_invocation = record_webhook_invocation(
            namespace=namespace,
            webhook_name=name,
            event_id=invocation_id,
            source_ip=client_ip,
            signature_valid=signature_verified,
            payload_size=len(raw_body),
            payload_snippet=json.dumps(sanitized_payload, ensure_ascii=False, default=str)[:1024] if sanitized_payload is not None else None,
            headers_json={
                "provider": provider,
                "key-id": x_kubesynapse_key_id,
                "signature-present": bool(provider_signature),
                "timestamp-present": bool(x_kubesynapse_timestamp),
            },
        )

        # Find matching triggers and dispatch (async via NATS or direct)
        matched_triggers = _dispatch_matching_triggers(name, namespace, invocation_id, sanitized_payload)
        update_webhook_invocation_matched_triggers(int(recorded_invocation["id"]), matched_triggers)

        # Record dispatch latency
        elapsed = time_module.monotonic() - start_time
        metric = _get_metric("webhook_dispatch_latency_seconds", "Webhook dispatch latency in seconds")
        if metric:
            metric.labels(namespace=namespace, name=name).observe(elapsed)

        # Increment invocation counter
        metric = _get_metric("webhook_invocations_total", "Total webhook invocations")
        if metric:
            metric.labels(namespace=namespace, name=name).inc()

        return JSONResponse(
            content={
                "status": "received",
                "invocation_id": invocation_id,
                "matched_triggers": len(matched_triggers),
                "provider": provider,
            },
            status_code=202,  # Accepted — dispatched asynchronously
        )
    finally:
        if max_concurrent > 0:
            release_webhook_concurrency(f"{namespace}/{name}")


# ---------------------------------------------------------------------------
# Webhook Invocation History
# ---------------------------------------------------------------------------


@router.get("/namespaces/{namespace}/webhooks/{name}/history", response_model=list[WebhookInvocationInfo])
@router.get("/webhooks/{name}/history", response_model=list[WebhookInvocationInfo])
def get_webhook_history(name: str, namespace: str = "default", limit: int = 50, user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    rows = list_webhook_invocations(namespace, name, limit=min(limit, 200))
    return [WebhookInvocationInfo.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Webhook SSE Event Stream
# ---------------------------------------------------------------------------


@router.get("/namespaces/{namespace}/webhooks/events/stream")
@router.get("/webhooks/events/stream")
async def stream_webhook_events(namespace: str = "default", user=Depends(verify_token)):
    """SSE stream of real-time webhook invocation events."""
    ensure_namespace_access(user, namespace)
    from _core import sse_event

    async def event_generator():
        last_id = 0
        while True:
            try:
                rows = list_webhook_invocations(namespace, "", limit=50)
                for row in reversed(rows):
                    row_id = int(row.get("id", 0))
                    if row_id > last_id:
                        last_id = row_id
                        yield sse_event("webhook.invocation", row)
                import asyncio
                await asyncio.sleep(2)
            except Exception:
                import asyncio
                await asyncio.sleep(5)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Workflow Trigger CRUD
# ---------------------------------------------------------------------------


@router.get("/namespaces/{namespace}/workflow-triggers", response_model=list[WorkflowTriggerInfo])
@router.get("/workflow-triggers", response_model=list[WorkflowTriggerInfo])
def list_triggers(namespace: str = "default", user=Depends(verify_token)):
    ensure_role(user, "viewer")
    ensure_namespace_access(user, namespace)
    rows = list_workflow_triggers(namespace)
    return [WorkflowTriggerInfo.model_validate(r) for r in rows]


@router.post("/namespaces/{namespace}/workflow-triggers", status_code=201, response_model=WorkflowTriggerInfo)
@router.post("/workflow-triggers", status_code=201, response_model=WorkflowTriggerInfo)
def create_trigger(body: WorkflowTriggerRequest, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    source_ref = _trigger_source_ref(body)
    workflow_name, workflow_namespace, agent_name, agent_namespace = _trigger_target_refs(body, namespace)
    target_kind = "agent" if agent_name else "workflow"
    try:
        row = create_workflow_trigger(
            namespace=namespace,
            name=body.name,
            source_name=source_ref or "",
            source_kind=body.source_kind or "WebhookReceiver",
            target_kind=target_kind,
            event_filter=body.event_filter,
            target_workflow_name=workflow_name,
            target_workflow_namespace=workflow_namespace,
            target_agent_name=agent_name,
            target_agent_namespace=agent_namespace,
            payload_mapping=body.payload_mapping,
            retry_max_retries=body.max_retries,
            retry_backoff_seconds=body.backoff_seconds,
            notifications_on_success=body.notifications_on_success,
            notifications_on_failure=body.notifications_on_failure,
            enabled=body.enabled if body.enabled is not None else True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkflowTriggerInfo.model_validate(row)


@router.get("/namespaces/{namespace}/workflow-triggers/{name}", response_model=WorkflowTriggerInfo)
@router.get("/workflow-triggers/{name}", response_model=WorkflowTriggerInfo)
def get_trigger(name: str, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    row = get_workflow_trigger(namespace, name)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow trigger not found")
    return WorkflowTriggerInfo.model_validate(row)


@router.put("/namespaces/{namespace}/workflow-triggers/{name}", response_model=WorkflowTriggerInfo)
@router.put("/workflow-triggers/{name}", response_model=WorkflowTriggerInfo)
def update_trigger(name: str, body: WorkflowTriggerUpdateRequest, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace, "operator")
    existing = get_workflow_trigger(namespace, name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Workflow trigger not found")
    source_ref = _trigger_source_ref(body)
    workflow_name, workflow_namespace, agent_name, agent_namespace = _trigger_target_refs(body, namespace)
    if getattr(body, "workflow_ref", None) is None and getattr(body, "agent_ref", None) is None:
        if getattr(body, "target_workflow_name", None) is None and getattr(body, "target_agent_name", None) is None:
            workflow_name = None
            workflow_namespace = None
            agent_name = None
            agent_namespace = None
    try:
        row = update_workflow_trigger(
            namespace=namespace,
            name=name,
            source_name=source_ref,
            source_kind=body.source_kind,
            event_filter=body.event_filter,
            target_workflow_name=workflow_name,
            target_workflow_namespace=workflow_namespace,
            target_agent_name=agent_name,
            target_agent_namespace=agent_namespace,
            payload_mapping=body.payload_mapping,
            retry_max_retries=body.max_retries,
            retry_backoff_seconds=body.backoff_seconds,
            notifications_on_success=body.notifications_on_success,
            notifications_on_failure=body.notifications_on_failure,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow trigger not found")
    return WorkflowTriggerInfo.model_validate(row)


@router.delete("/namespaces/{namespace}/workflow-triggers/{name}", status_code=204)
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


@router.get("/namespaces/{namespace}/workflow-triggers/{name}/history", response_model=list[TriggerExecutionInfo])
@router.get("/workflow-triggers/{name}/history", response_model=list[TriggerExecutionInfo])
def get_trigger_history(name: str, namespace: str = "default", limit: int = 50, user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    rows = list_trigger_executions(namespace, name, limit=min(limit, 200))
    return [TriggerExecutionInfo.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Dead Letter Queue
# ---------------------------------------------------------------------------


@router.get("/namespaces/{namespace}/webhooks/{name}/dead-letter", response_model=list[TriggerExecutionInfo])
@router.get("/webhooks/{name}/dead-letter", response_model=list[TriggerExecutionInfo])
def get_webhook_dead_letter(name: str, namespace: str = "default", limit: int = 50, user=Depends(verify_token)):
    """List dead-letter trigger executions for a webhook."""
    ensure_namespace_access(user, namespace, "operator")
    rows = list_trigger_executions(namespace, name, limit=min(limit, 200))
    dead_letter = [r for r in rows if r.get("status") in ("dead_letter", "failed")]
    return [TriggerExecutionInfo.model_validate(r) for r in dead_letter]


@router.post("/namespaces/{namespace}/webhooks/dead-letter/{execution_id}/replay", status_code=202)
@router.post("/webhooks/dead-letter/{execution_id}/replay", status_code=202)
async def replay_dead_letter(
    execution_id: int,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Replay a dead-letter trigger execution."""
    ensure_namespace_access(user, namespace, "operator")

    # Find the execution
    from _core import get_db_session
    from auth_store import TriggerExecutionRow

    with get_db_session() as session:
        row = session.query(TriggerExecutionRow).filter(TriggerExecutionRow.id == execution_id).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Trigger execution not found")
        if row.status not in ("dead_letter", "failed"):
            raise HTTPException(status_code=400, detail=f"Cannot replay execution with status '{row.status}'")

        # Reset status to pending for the operator to claim and dispatch
        row.status = "pending"
        row.attempt_count = 0
        row.error_message = None
        row.claimed_by = None
        row.claim_source = None
        row.claimed_at = None
        row.dispatch_path = None

    return JSONResponse(
        content={"status": "replay_queued", "execution_id": execution_id},
        status_code=202,
    )


# ---------------------------------------------------------------------------
# Dispatched Execution Status (used by operator)
# ---------------------------------------------------------------------------


@router.patch("/namespaces/{namespace}/webhooks/dispatched/{execution_id}/status")
@router.patch("/webhooks/dispatched/{execution_id}/status")
def update_dispatched_execution_status(
    execution_id: int,
    body: dict[str, Any],
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Update the status and lineage of a trigger execution (called by the operator).

    The operator uses this to report execution outcomes: processing, completed,
    failed, or dead_letter. It can also attach lineage metadata (workflow_run_id,
    job_name, session_id, etc.) that links the execution to its downstream
    resources for traceability in the UI.
    """
    ensure_namespace_access(user, namespace, "operator")

    status = str(body.get("status") or "").strip()
    if not status:
        raise HTTPException(status_code=422, detail="status is required")

    error_message = str(body.get("error_message") or "").strip() or None
    attempt_count = body.get("attempt_count")

    try:
        result = update_trigger_execution_status(
            execution_id=execution_id,
            status=status,
            error_message=error_message,
            attempt_count=int(attempt_count) if attempt_count is not None else None,
            workflow_run_id=str(body.get("workflow_run_id") or "").strip() or None,
            workflow_generation=body.get("workflow_generation"),
            job_name=str(body.get("job_name") or "").strip() or None,
            session_id=str(body.get("session_id") or "").strip() or None,
            operator_instance=str(body.get("operator_instance") or "").strip() or None,
            dispatch_path=str(body.get("dispatch_path") or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Trigger execution not found")

    return JSONResponse(content={"status": "updated", "execution": result})


@router.post("/namespaces/{namespace}/webhooks/dispatched/{execution_id}/claim")
@router.post("/webhooks/dispatched/{execution_id}/claim")
def claim_trigger_execution_endpoint(
    execution_id: int,
    body: dict[str, Any],
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Atomically claim a trigger execution for dispatch.

    Only succeeds if the execution is still pending. Sets claimed_by,
    claim_source, and transitions status to queued. The operator calls
    this before launching any workflow job or agent invocation to prevent
    duplicate dispatch from NATS + timer or two operator pods.
    """
    ensure_namespace_access(user, namespace, "operator")
    claimed_by = str(body.get("claimed_by") or "operator").strip()[:128]
    claim_source = str(body.get("claim_source") or "nats").strip()[:32]

    result = claim_trigger_execution(
        execution_id=execution_id,
        claimed_by=claimed_by,
        claim_source=claim_source,
    )
    if result is None:
        return JSONResponse(
            content={"claimed": False, "reason": "not_claimable"},
            status_code=409,
        )
    return JSONResponse(content={"claimed": True, "execution": result})


@router.get("/namespaces/{namespace}/webhooks/dispatched/pending", response_model=list[TriggerExecutionInfo])
@router.get("/webhooks/dispatched/pending", response_model=list[TriggerExecutionInfo])
def get_pending_dispatched_executions(
    namespace: str = "default",
    limit: int = 50,
    user=Depends(verify_token),
):
    """List claimable pending trigger executions (used by operator timer fallback).

    Only returns executions that are still in a claimable (pending) state.
    The operator should claim each one via the claim endpoint before dispatching.
    """
    ensure_namespace_access(user, namespace, "operator")
    from _core import db_session as get_db_session
    from auth_store import TriggerExecutionRow, _CLAIMABLE_STATES

    with get_db_session() as session:
        rows = (
            session.query(TriggerExecutionRow)
            .filter(
                TriggerExecutionRow.trigger_namespace == namespace,
                TriggerExecutionRow.status.in_(list(_CLAIMABLE_STATES)),
            )
            .order_by(TriggerExecutionRow.created_at.asc())
            .limit(min(limit, 200))
            .all()
        )
        return [TriggerExecutionInfo.model_validate(r.to_dict()) for r in rows]


# ---------------------------------------------------------------------------
# Webhook Secret Generation
# ---------------------------------------------------------------------------


@router.post("/namespaces/{namespace}/webhooks/{name}/generate-secret")
@router.post("/webhooks/{name}/generate-secret")
def generate_webhook_secret(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Generate a new HMAC secret for a webhook receiver.

    Returns the generated secret and the K8s Secret YAML to apply.
    """
    ensure_namespace_access(user, namespace, "operator")
    existing = get_webhook_receiver(namespace, name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Webhook receiver not found")

    import secrets

    new_secret = secrets.token_hex(32)  # 256-bit HMAC key

    return JSONResponse(content={
        "secret": new_secret,
        "secret_ref_hint": f"{namespace}/wh-{name}-secret#hmac-key",
        "k8s_secret_yaml": (
            f"apiVersion: v1\nkind: Secret\nmetadata:\n"
            f"  name: wh-{name}-secret\n  namespace: {namespace}\n"
            f"type: Opaque\n"
            f"stringData:\n"
            f"  hmac-key: {new_secret}\n"
        ),
    })


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
            except Exception:
                pass

    env_var_name = secret_ref.replace("-", "_").replace(" ", "_").upper()
    import os
    return os.environ.get(env_var_name)


def _count_matching_triggers(
    webhook_name: str,
    namespace: str,
    payload: dict[str, Any] | None,
) -> int:
    """Count matching triggers without dispatching (used for dry-run)."""
    if not payload:
        return 0
    count = 0
    try:
        triggers = list_workflow_triggers(namespace)
        for trigger in triggers:
            if not trigger.get("enabled", True):
                continue
            if trigger.get("source_kind") != "WebhookReceiver":
                continue
            if trigger.get("source_ref") != webhook_name and trigger.get("source_name") != webhook_name:
                continue
            event_filter = trigger.get("event_filter") or {}
            if _matches_event_filter(payload, event_filter):
                count += 1
    except Exception:
        pass
    return count


def _dispatch_matching_triggers(
    webhook_name: str,
    namespace: str,
    invocation_id: str,
    payload: dict[str, Any] | None,
) -> list[str]:
    """Find and dispatch matching workflow triggers for a webhook event.

    Matching triggers are recorded in the shared DB; the operator dispatch loop
    claims those rows and launches the workflow jobs or agent invocations.
    """
    if not payload:
        return []

    matched: list[str] = []
    try:
        triggers = list_workflow_triggers(namespace)
        for trigger in triggers:
            if not trigger.get("enabled", True):
                continue
            if trigger.get("source_kind") != "WebhookReceiver":
                continue
            if trigger.get("source_ref") != webhook_name and trigger.get("source_name") != webhook_name:
                continue

            event_filter = trigger.get("event_filter") or {}
            if not _matches_event_filter(payload, event_filter):
                continue

            # Determine target kind and refs
            target_kind = str(trigger.get("target_kind") or "workflow").strip()
            workflow_ref = trigger.get("workflow_ref") or {}
            agent_ref = trigger.get("agent_ref") or {}

            workflow_name = str(workflow_ref.get("name") or trigger.get("target_workflow_name") or "").strip()
            workflow_namespace = (
                str(workflow_ref.get("namespace") or trigger.get("target_workflow_namespace") or namespace).strip()
                or namespace
            )
            agent_name = str(agent_ref.get("name") or "").strip()
            agent_namespace = (
                str(agent_ref.get("namespace") or "").strip() or namespace
            )

            if target_kind == "workflow" and not workflow_name:
                logger.warning(
                    "Webhook trigger %s/%s has no target workflow name; skipping.",
                    namespace,
                    trigger.get("name"),
                )
                continue

            if target_kind == "agent" and not agent_name:
                logger.warning(
                    "Webhook trigger %s/%s has no target agent name; skipping.",
                    namespace,
                    trigger.get("name"),
                )
                continue

            execution = record_trigger_execution(
                trigger_namespace=namespace,
                trigger_name=str(trigger.get("name") or "").strip(),
                webhook_name=webhook_name,
                event_id=invocation_id,
                target_kind=target_kind,
                workflow_name=workflow_name,
                workflow_namespace=workflow_namespace,
                agent_name=agent_name,
                agent_namespace=agent_namespace,
                payload_json=payload,
                status="pending",
            )
            matched.append(str(trigger.get("name") or "").strip())
            logger.info(
                "Webhook trigger matched: %s/%s → %s %s/%s (execution %s)",
                namespace, trigger.get("name"), target_kind,
                workflow_namespace if target_kind == "workflow" else agent_namespace,
                workflow_name if target_kind == "workflow" else agent_name,
                execution.get("id"),
            )

            # Publish to NATS for immediate dispatch with full execution data
            _publish_nats_event(execution, invocation_id, namespace, trigger.get("name"), target_kind)

    except Exception as exc:
        logger.warning("Error dispatching webhook triggers for %s/%s: %s", namespace, webhook_name, exc)

    return matched


def _publish_nats_event(
    execution: dict[str, Any],
    invocation_id: str,
    namespace: str,
    trigger_name: str | None,
    target_kind: str | None,
) -> None:
    """Publish a webhook dispatch event to NATS for immediate operator processing.

    Carries full execution metadata so the operator can claim and dispatch
    without a DB lookup. The operator must claim the execution before dispatching.
    """
    if not NATS_URL:
        return
    try:
        import asyncio
        import nats

        async def _publish():
            try:
                nc = await nats.connect(NATS_URL, connect_timeout=1)
                await nc.publish(
                    "kubesynapse.webhook.dispatch",
                    json.dumps({
                        "invocation_id": invocation_id,
                        "namespace": namespace,
                        "trigger_name": trigger_name,
                        "target_kind": target_kind,
                        "execution_id": execution.get("id"),
                        "workflow_name": execution.get("workflow_name"),
                        "workflow_namespace": execution.get("workflow_namespace"),
                        "agent_name": execution.get("agent_name"),
                        "agent_namespace": execution.get("agent_namespace"),
                        "payload": execution.get("payload_json"),
                        "event_id": execution.get("event_id"),
                        "webhook_name": execution.get("webhook_name"),
                    }).encode(),
                )
                await nc.close()
            except Exception:
                pass

        asyncio.create_task(_publish())
    except Exception:
        pass  # NATS is best-effort; the operator timer will pick up missed events


def _matches_event_filter(payload: dict[str, Any], event_filter: dict[str, Any]) -> bool:
    """Check if a payload matches an event filter specification.

    Supports simple key-value matching. For JSONPath, uses basic dot-notation traversal.
    """
    conditions = event_filter.get("conditions") or []
    if not conditions and event_filter:
        for field, raw_value in event_filter.items():
            if field == "conditions":
                continue
            if isinstance(raw_value, dict) and raw_value:
                operator, expected = next(iter(raw_value.items()))
                conditions.append({"field": field, "operator": operator, "value": expected})
            else:
                conditions.append({"field": field, "operator": "equals", "value": raw_value})
    if not conditions:
        return True

    for condition in conditions:
        field = condition.get("field", "")
        operator = condition.get("operator", "equals")
        expected = condition.get("value")

        # Navigate dot-notation
        value: Any = payload
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
        elif operator == "not_exists":
            if value is not None:
                return False
        elif operator == "gt":
            try:
                if not (float(value) > float(expected)):
                    return False
            except (TypeError, ValueError):
                return False
        elif operator == "gte":
            try:
                if not (float(value) >= float(expected)):
                    return False
            except (TypeError, ValueError):
                return False
        elif operator == "lt":
            try:
                if not (float(value) < float(expected)):
                    return False
            except (TypeError, ValueError):
                return False
        elif operator == "lte":
            try:
                if not (float(value) <= float(expected)):
                    return False
            except (TypeError, ValueError):
                return False
        elif operator == "in":
            if isinstance(expected, list):
                if value not in expected:
                    return False
            else:
                return False
        elif operator == "regex":
            import re
            if not re.search(str(expected), str(value or "")):
                return False
        elif operator == "and":
            if isinstance(expected, list):
                for sub_cond in expected:
                    if not _matches_single_condition(payload, sub_cond):
                        return False
        elif operator == "or":
            if isinstance(expected, list):
                or_match = any(_matches_single_condition(payload, sub_cond) for sub_cond in expected)
                if not or_match:
                    return False

    return True


def _matches_single_condition(payload: dict[str, Any], condition: dict[str, Any]) -> bool:
    """Evaluate a single filter condition against a payload."""
    wrapped = {"conditions": [condition]}
    return _matches_event_filter(payload, wrapped)
