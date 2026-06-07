"""Router for incident lifecycle — CRUD, Alertmanager webhook, status transitions."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from auth_store import (
    add_incident_timeline_event,
    api_rate_limit_key,
    api_rate_limited,
    create_incident,
    get_incident,
    get_incident_by_fingerprint,
    list_incidents,
    normalize_namespaces,
    update_incident_status,
    upsert_incident,
)
from auth_middleware import ensure_namespace_access, request_client_ip, verify_token
from webhook_security import verify_provider_signature

router = APIRouter(tags=["incidents"])

_ALERTMANAGER_WEBHOOK_SECRET = os.getenv("ALERTMANAGER_WEBHOOK_SECRET", "").strip()
_INCIDENT_RATE_LIMIT_PER_MINUTE = max(int(os.getenv("INCIDENT_API_RATE_LIMIT_PER_MINUTE", "60")), 1)


def _ns(namespace: str | None = None) -> str:
    return (namespace or "default").strip() or "default"


def _incident_to_response(inc: dict[str, Any]) -> dict[str, Any]:
    """Enrich incident dict with hypermedia-style fields."""
    inc.setdefault("timeline", [])
    return inc


def _incident_rate_key(request: Request, user: dict[str, Any] | None = None) -> str:
    identifier = request_client_ip(request) or str((user or {}).get("sub") or "anonymous")
    return api_rate_limit_key("incidents", identifier)


def _enforce_incident_rate_limit(request: Request, user: dict[str, Any] | None = None) -> None:
    rate_key = _incident_rate_key(request, user)
    if api_rate_limited(rate_key, max_per_minute=_INCIDENT_RATE_LIMIT_PER_MINUTE):
        raise HTTPException(status_code=429, detail="Too many incident API requests. Please retry shortly.")


def _authorized_incident_namespaces(user: dict[str, Any]) -> list[str] | None:
    if str(user.get("role") or "viewer") == "admin":
        return None
    allowed = normalize_namespaces(user.get("allowed_namespaces") or [])
    return allowed or []


def _filter_incidents_for_user(items: list[dict[str, Any]], user: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = _authorized_incident_namespaces(user)
    if allowed is None or "*" in allowed:
        return items
    allowed_set = set(allowed)
    return [item for item in items if str(item.get("namespace") or "default") in allowed_set]


async def _verify_alertmanager_signature(request: Request) -> None:
    if not _ALERTMANAGER_WEBHOOK_SECRET:
        return
    signature = request.headers.get("x-alertmanager-signature", "").strip()
    if not signature:
        raise HTTPException(status_code=401, detail="Missing alertmanager signature")
    raw_body = await request.body()
    if not verify_provider_signature("generic", raw_body, signature, _ALERTMANAGER_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid alertmanager signature")


@router.get("/incidents")
async def api_list_incidents(
    request: Request,
    namespace: str | None = Query(None),
    status: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """List incidents with optional filters."""
    _enforce_incident_rate_limit(request, user)
    if namespace:
        ensure_namespace_access(user, namespace)
    try:
        results = list_incidents(
            namespace=namespace,
            status=status,
            severity=severity,
            limit=limit,
            offset=offset,
        )
        results = _filter_incidents_for_user(results, user)
        return {"incidents": [_incident_to_response(r) for r in results], "total": len(results)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid incident list filters") from exc


@router.get("/incidents/{name}")
async def api_get_incident(
    request: Request,
    name: str,
    namespace: str | None = Query(None),
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Get a single incident by name."""
    _enforce_incident_rate_limit(request, user)
    ensure_namespace_access(user, _ns(namespace))
    try:
        inc = get_incident(namespace=_ns(namespace), name=name)
        return _incident_to_response(inc)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Incident not found") from exc


@router.post("/incidents")
async def api_create_incident(
    request: Request,
    body: dict[str, Any] = Body(...),
    namespace: str | None = Query(None),
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Create a new incident manually."""
    _enforce_incident_rate_limit(request, user)
    ns = _ns(body.get("namespace") or namespace)
    ensure_namespace_access(user, ns, "operator")
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Field 'name' is required")

    try:
        inc = create_incident(
            namespace=ns,
            name=name,
            title=body.get("title", name),
            severity=body.get("severity", "warning"),
            source="manual",
            description=body.get("description", ""),
            labels=body.get("labels"),
            annotations=body.get("annotations"),
            assigned_agent=body.get("assigned_agent"),
            escalation_timeout_minutes=body.get("escalation_timeout_minutes", 15),
            auto_acknowledge=body.get("auto_acknowledge", True),
            workflow_ref_name=body.get("workflow_ref", {}).get("name") if body.get("workflow_ref") else None,
            workflow_ref_namespace=body.get("workflow_ref", {}).get("namespace") if body.get("workflow_ref") else None,
        )
        return _incident_to_response(inc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid incident payload") from exc


@router.put("/incidents/{name}")
async def api_upsert_incident(
    request: Request,
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str | None = Query(None),
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Create or update an incident by name — idempotent upsert."""
    _enforce_incident_rate_limit(request, user)
    ns = _ns(body.get("namespace") or namespace)
    ensure_namespace_access(user, ns, "operator")
    if not name.strip():
        raise HTTPException(status_code=400, detail="Field 'name' is required")

    try:
        inc = upsert_incident(
            namespace=ns,
            name=name.strip(),
            title=body.get("title", name),
            severity=body.get("severity", "warning"),
            source=body.get("source", "manual"),
            description=body.get("description", ""),
            labels=body.get("labels"),
            annotations=body.get("annotations"),
            assigned_agent=body.get("assigned_agent"),
            escalation_timeout_minutes=body.get("escalation_timeout_minutes", 15),
            auto_acknowledge=body.get("auto_acknowledge", True),
            alertmanager_fingerprint=body.get("alertmanager_fingerprint"),
            workflow_ref_name=body.get("workflow_ref", {}).get("name") if body.get("workflow_ref") else None,
            workflow_ref_namespace=body.get("workflow_ref", {}).get("namespace") if body.get("workflow_ref") else None,
        )
        return _incident_to_response(inc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid incident payload") from exc


@router.patch("/incidents/{name}")
async def api_update_incident(
    request: Request,
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str | None = Query(None),
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Update incident status or metadata."""
    _enforce_incident_rate_limit(request, user)
    ns = _ns(body.get("namespace") or namespace)
    ensure_namespace_access(user, ns, "operator")
    target_status = body.get("status", "")
    if target_status:
        try:
            inc = update_incident_status(
                namespace=ns,
                name=name,
                status=target_status,
                message=body.get("message", ""),
                workflow_run_id=body.get("workflow_run_id"),
            )
            return _incident_to_response(inc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid incident status update") from exc

    # No status change — just add a timeline event if message provided
    if body.get("message"):
        try:
            inc = add_incident_timeline_event(
                namespace=ns,
                name=name,
                event=body.get("event", "note"),
                message=body["message"],
            )
            return _incident_to_response(inc)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Incident not found") from exc

    # Return current state
    try:
        inc = get_incident(namespace=ns, name=name)
        return _incident_to_response(inc)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Incident not found") from exc


@router.post("/incidents/{name}/escalate")
async def api_escalate_incident(
    request: Request,
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str | None = Query(None),
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Manually escalate an incident."""
    _enforce_incident_rate_limit(request, user)
    ns = _ns(body.get("namespace") or namespace)
    ensure_namespace_access(user, ns, "operator")
    try:
        inc = update_incident_status(
            namespace=ns,
            name=name,
            status="escalated",
            message=body.get("message", "Manually escalated"),
        )
        return _incident_to_response(inc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Incident could not be escalated") from exc


@router.get("/incidents/{name}/timeline")
async def api_incident_timeline(
    request: Request,
    name: str,
    namespace: str | None = Query(None),
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Get the timeline for an incident."""
    _enforce_incident_rate_limit(request, user)
    ensure_namespace_access(user, _ns(namespace))
    try:
        inc = get_incident(namespace=_ns(namespace), name=name)
        return {"timeline": inc.get("timeline", [])}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Incident not found") from exc


# ---------------------------------------------------------------------------
# Alertmanager webhook handler
# ---------------------------------------------------------------------------

ALERTMANAGER_SEVERITY_MAP = {
    "critical": "critical",
    "warning": "warning",
    "info": "info",
    "error": "critical",
    "debug": "info",
    "none": "info",
}


def _alertmanager_payload_to_incidents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse Alertmanager v4 webhook payload and yield incident records.

    Alertmanager v4 format:
    {
      "version": "4",
      "groupKey": "...",
      "truncatedAlerts": 0,
      "status": "firing" | "resolved",
      "receiver": "...",
      "groupLabels": {...},
      "commonLabels": {...},
      "commonAnnotations": {...},
      "alerts": [
        {
          "status": "firing" | "resolved",
          "labels": {...},
          "annotations": {...},
          "startsAt": "...",
          "endsAt": "...",
          "generatorURL": "...",
          "fingerprint": "..."
        }
      ]
    }
    """
    incidents: list[dict[str, Any]] = []
    common_labels = payload.get("commonLabels", {}) or {}
    common_annotations = payload.get("commonAnnotations", {}) or {}
    alerts = payload.get("alerts", []) or []

    for alert in alerts:
        labels = alert.get("labels", {}) or {}
        annotations = alert.get("annotations", {}) or {}
        fingerprint = alert.get("fingerprint", "") or ""
        alertname = labels.get("alertname", "unknown")
        severity_label = labels.get("severity", "warning")
        severity = ALERTMANAGER_SEVERITY_MAP.get(severity_label, "warning")
        alert_status = alert.get("status", "firing")

        title = annotations.get("summary", "") or f"Alert: {alertname}"
        description = annotations.get("description", "") or ""

        merged_labels = {**common_labels, **labels}
        merged_annotations = {**common_annotations, **annotations}

        incident_name = f"alert-{alertname}-{fingerprint[:12]}" if fingerprint else f"alert-{alertname}"

        incidents.append({
            "name": incident_name,
            "title": title,
            "severity": severity,
            "source": "alertmanager",
            "description": description,
            "labels": merged_labels,
            "annotations": merged_annotations,
            "alertmanager_fingerprint": fingerprint or None,
            "auto_acknowledge": True,
            "escalation_timeout_minutes": {
                "critical": 15,
                "warning": 30,
                "info": 60,
            }.get(severity, 30),
            "_alert_status": alert_status,
        })

    return incidents


@router.post("/webhooks/alertmanager")
async def api_alertmanager_webhook(
    request: Request,
    namespace: str | None = Query(None),
    _: None = Depends(_verify_alertmanager_signature),
) -> dict[str, Any]:
    """Receive Alertmanager v4 webhook payload and create/update incidents."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    ns = _ns(namespace)
    incidents = _alertmanager_payload_to_incidents(payload)
    results: list[dict[str, Any]] = []

    for inc_data in incidents:
        alert_status = inc_data.pop("_alert_status", "firing")
        fingerprint = inc_data.get("alertmanager_fingerprint")

        # Check for existing incident by fingerprint
        existing = None
        if fingerprint:
            existing = get_incident_by_fingerprint(fingerprint)

        if existing and existing.get("status") in ("resolved", "closed"):
            # Already handled — skip
            if alert_status == "firing":
                # Re-firing a resolved alert — create new
                pass
            else:
                continue

        if existing:
            # Update existing incident
            if alert_status == "resolved":
                try:
                    result = update_incident_status(
                        namespace=ns,
                        name=existing["name"],
                        status="resolved",
                        message=inc_data.get("annotations", {}).get("summary", "Alert resolved via Alertmanager"),
                    )
                    results.append(result)
                except ValueError:
                    pass
            else:
                # Update labels/annotations, add timeline event
                try:
                    result = add_incident_timeline_event(
                        namespace=ns,
                        name=existing["name"],
                        event=alert_status,
                        message=f"Alert {alert_status}: {inc_data.get('title', '')}",
                    )
                    results.append(result)
                except ValueError:
                    pass
        else:
            # Create new incident
            try:
                result = create_incident(
                    namespace=ns,
                    **{k: v for k, v in inc_data.items() if k != "namespace"},
                )
                results.append(result)
            except ValueError:
                pass

            if alert_status == "resolved":
                # Created already resolved — set status
                try:
                    result = update_incident_status(
                        namespace=ns,
                        name=inc_data["name"],
                        status="resolved",
                        message="Alert already resolved at creation time",
                    )
                    if result:
                        results[-1] = result
                except ValueError:
                    pass

    return {"incidents": results, "total": len(results)}
