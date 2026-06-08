"""Incident lifecycle controller — Kopf handler for AgentIncident CRD.

Responsibilities:
- Watch AgentIncident CRD creation/updates
- Auto-acknowledge if spec.autoAcknowledge is true
- Trigger assignedAgent workflow when status transitions to diagnosing
- Manage escalation timers per severity
- Sync internal status updates to CRD status.timeline
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
import requests

logger = logging.getLogger("operator.incident_controller")

# ---------------------------------------------------------------------------
# Gateway API client
# ---------------------------------------------------------------------------

GATEWAY_URL = os.getenv("API_GATEWAY_INTERNAL_URL", "http://kubesynapse-api-gateway:8080")
GATEWAY_TOKEN = os.getenv("API_GATEWAY_SHARED_TOKEN", "")
_INCIDENT_CONTROLLER_ENABLED = os.getenv("INCIDENT_CONTROLLER_ENABLED", "true").lower() in {"1", "true"}

# ---------------------------------------------------------------------------
# Escalation timers
# ---------------------------------------------------------------------------

_ESCALATION_TIMERS: dict[str, threading.Timer] = {}
_ESCALATION_LOCK = threading.Lock()

SEVERITY_ESCALATION_MINUTES: dict[str, int] = {
    "critical": 15,
    "warning": 30,
    "info": 60,
}


def _gateway_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if GATEWAY_TOKEN:
        headers["Authorization"] = f"Bearer {GATEWAY_TOKEN}"
    return headers


def _gateway_url(path: str) -> str:
    return f"{GATEWAY_URL.rstrip('/')}{path}"


def _call_gateway(method: str, path: str, json_body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Call the gateway API and return the JSON response or None on failure.

    Retries transient errors (5xx, connection errors) with exponential backoff.
    Permanent errors (4xx) are not retried.
    """
    import time as _time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            url = _gateway_url(path)
            if method == "GET":
                resp = requests.get(url, headers=_gateway_headers(), timeout=10)
            elif method == "PUT":
                resp = requests.put(url, headers=_gateway_headers(), json=json_body, timeout=10)
            elif method == "POST":
                resp = requests.post(url, headers=_gateway_headers(), json=json_body, timeout=10)
            elif method == "PATCH":
                resp = requests.patch(url, headers=_gateway_headers(), json=json_body, timeout=10)
            else:
                logger.warning("Unsupported HTTP method: %s", method)
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                logger.warning("Gateway API permanent error: %s %s — %s", method, path, e)
                return None
            if attempt < max_retries - 1:
                backoff = 2 ** attempt
                logger.warning(
                    "Gateway API transient error: %s %s — retrying in %ds (%d/%d)",
                    method, path, backoff, attempt + 1, max_retries,
                )
                _time.sleep(backoff)
                continue
            logger.warning("Gateway API call failed after %d retries: %s %s — %s", max_retries, method, path, e)
            return None
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < max_retries - 1:
                backoff = 2 ** attempt
                logger.warning(
                    "Gateway API network error: %s %s — retrying in %ds (%d/%d)",
                    method, path, backoff, attempt + 1, max_retries,
                )
                _time.sleep(backoff)
                continue
            logger.warning("Gateway API network error after %d retries: %s %s — %s", max_retries, method, path, e)
            return None


# ---------------------------------------------------------------------------
# Escalation timer management
# ---------------------------------------------------------------------------


def _timer_key(namespace: str, name: str) -> str:
    return f"{namespace}/{name}"


def _escalate_incident(namespace: str, name: str) -> None:
    """Called by the escalation timer — transition incident to escalated."""
    logger.warning("Escalating incident %s/%s — timeout reached", namespace, name)
    _call_gateway(
        "POST",
        f"/api/v1/incidents/{name}/escalate?namespace={namespace}",
        {"message": "Auto-escalated due to escalation timeout"},
    )


def _cancel_escalation_timer(namespace: str, name: str) -> None:
    """Cancel a running escalation timer for an incident."""
    key = _timer_key(namespace, name)
    with _ESCALATION_LOCK:
        timer = _ESCALATION_TIMERS.pop(key, None)
        if timer:
            timer.cancel()
            logger.info("Cancelled escalation timer for %s", key)


def _schedule_escalation_timer(namespace: str, name: str, severity: str) -> None:
    """Schedule an escalation timer for an incident based on severity."""
    key = _timer_key(namespace, name)
    timeout_minutes = SEVERITY_ESCALATION_MINUTES.get(severity, 30)
    _cancel_escalation_timer(namespace, name)
    timer = threading.Timer(timeout_minutes * 60, _escalate_incident, args=[namespace, name])
    timer.daemon = True
    with _ESCALATION_LOCK:
        _ESCALATION_TIMERS[key] = timer
    timer.start()
    logger.info(
        "Scheduled escalation timer for %s in %d minutes",
        key,
        timeout_minutes,
    )


# ---------------------------------------------------------------------------
# CRD <-> Gateway sync
# ---------------------------------------------------------------------------


def _sync_incident_to_gateway(incident_spec: dict[str, Any], namespace: str, name: str) -> dict[str, Any] | None:
    """Create or update the incident in the gateway's PostgreSQL.

    Uses ``PUT`` for idempotent upsert so that concurrent create+update
    Kopf event handling does not produce duplicate gateway rows.
    """
    severity = incident_spec.get("severity", "warning")
    timeout_minutes = incident_spec.get("escalation_timeout_minutes", SEVERITY_ESCALATION_MINUTES.get(severity, 30))
    workflow_ref = incident_spec.get("workflowRef", {})

    body = {
        "name": name,
        "title": incident_spec.get("title", name),
        "description": incident_spec.get("description", ""),
        "severity": severity,
        "source": incident_spec.get("source", "manual"),
        "labels": incident_spec.get("labels", {}),
        "annotations": incident_spec.get("annotations", {}),
        "assigned_agent": incident_spec.get("assignedAgent"),
        "escalation_timeout_minutes": timeout_minutes,
        "auto_acknowledge": incident_spec.get("autoAcknowledge", True),
        "workflow_ref": {"name": workflow_ref.get("name"), "namespace": workflow_ref.get("namespace")} if workflow_ref else None,
    }

    return _call_gateway("PUT", f"/api/v1/incidents/{name}?namespace={namespace}", body)


def _sync_incident_status_to_crd(body: dict[str, Any], namespace: str, name: str) -> None:
    """Update the CRD status with the current incident state from the gateway."""
    api = kubernetes.client.CustomObjectsApi()
    try:
        status = {
            "timeline": body.get("timeline", []),
            "workflowRunId": body.get("workflow_run_id"),
            "observedGeneration": None,  # Set by Kopf
        }
        api.patch_namespaced_custom_object_status(
            group="kubesynapse.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="agentincidents",
            name=name,
            body={"status": status},
        )
    except kubernetes.client.exceptions.ApiException as e:
        logger.warning("Failed to patch incident CRD status for %s/%s: %s", namespace, name, e)


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------


@kopf.on.create("kubesynapse.ai", "v1alpha1", "agentincidents")
def incident_created(spec: dict[str, Any], namespace: str, name: str, **_kwargs: Any) -> dict[str, Any]:
    """Handle AgentIncident CRD creation."""
    if not _INCIDENT_CONTROLLER_ENABLED:
        logger.info("Incident controller disabled — skipping %s/%s", namespace, name)
        return {}

    logger.info("Incident created: %s/%s (severity=%s)", namespace, name, spec.get("severity", "?"))

    # Sync to gateway
    result = _sync_incident_to_gateway(spec, namespace, name)
    if not result:
        logger.warning("Failed to sync incident %s/%s to gateway", namespace, name)
        return {}

    # Auto-acknowledge if configured
    if spec.get("autoAcknowledge", True):
        ack_result = _call_gateway(
            "PATCH",
            f"/api/v1/incidents/{name}?namespace={namespace}",
            {"status": "acknowledged", "message": "Auto-acknowledged by incident controller"},
        )
        if ack_result:
            result = ack_result
            logger.info("Auto-acknowledged incident %s/%s", namespace, name)
            _schedule_escalation_timer(namespace, name, spec.get("severity", "warning"))

    # Sync CRD status
    _sync_incident_status_to_crd(result, namespace, name)

    return {"incident": result}


@kopf.on.update("kubesynapse.ai", "v1alpha1", "agentincidents")
def incident_updated(
    spec: dict[str, Any],
    status: dict[str, Any] | None,
    namespace: str,
    name: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Handle AgentIncident CRD updates."""
    if not _INCIDENT_CONTROLLER_ENABLED:
        return {}

    logger.info("Incident updated: %s/%s", namespace, name)

    # Sync to gateway
    result = _sync_incident_to_gateway(spec, namespace, name)
    if result:
        _sync_incident_status_to_crd(result, namespace, name)

    return {"incident": result or {}}


@kopf.on.delete("kubesynapse.ai", "v1alpha1", "agentincidents")
def incident_deleted(namespace: str, name: str, **_kwargs: Any) -> None:
    """Clean up escalation timers on incident deletion."""
    _cancel_escalation_timer(namespace, name)
    logger.info("Incident deleted: %s/%s — escalation timer cleaned up", namespace, name)


# ---------------------------------------------------------------------------
# Timer-based: periodic reconciliation of unresolved incidents
# ---------------------------------------------------------------------------


@kopf.timer("kubesynapse.ai", "v1alpha1", "agentincidents", interval=60.0, initial_delay=30.0)
def reconcile_incidents(
    spec: dict[str, Any],
    namespace: str,
    name: str,
    **_kwargs: Any,
) -> dict[str, Any] | None:
    """Periodic reconciliation of each incident.

    - Sync status from CRD to gateway
    - Check if escalation timeout has expired
    - Trigger assigned agent workflow if in diagnosing state
    """
    if not _INCIDENT_CONTROLLER_ENABLED:
        return None

    current_status = spec.get("status", "firing")
    severity = spec.get("severity", "warning")

    # Sync spec to gateway (idempotent)
    result = _sync_incident_to_gateway(spec, namespace, name)
    if not result:
        return None

    # Check if we need to trigger the assigned agent workflow
    if current_status == "diagnosing" and spec.get("assignedAgent"):
        workflow_ref = spec.get("workflowRef", {})
        if workflow_ref.get("name"):
            # Trigger the workflow via the gateway
            wf_name = workflow_ref["name"]
            wf_ns = workflow_ref.get("namespace", namespace)
            trigger_result = _call_gateway(
                "POST",
                f"/api/v1/workflows/{wf_name}/trigger?namespace={wf_ns}",
                {"incident": name, "incident_namespace": namespace},
            )
            if trigger_result:
                run_id = trigger_result.get("workflow_run_id") or trigger_result.get("run_id")
                if run_id:
                    _call_gateway(
                        "PATCH",
                        f"/api/v1/incidents/{name}?namespace={namespace}",
                        {"workflow_run_id": run_id},
                    )
                    logger.info("Triggered workflow %s/%s for incident %s/%s (run=%s)", wf_ns, wf_name, namespace, name, run_id)

    # Sync CRD status
    _sync_incident_status_to_crd(result, namespace, name)

    return result


# ---------------------------------------------------------------------------
# Cleanup on shutdown
# ---------------------------------------------------------------------------


def cancel_all_timers() -> None:
    """Cancel all escalation timers on operator shutdown."""
    with _ESCALATION_LOCK:
        for key, timer in list(_ESCALATION_TIMERS.items()):
            timer.cancel()
            logger.info("Cancelled escalation timer for %s", key)
        _ESCALATION_TIMERS.clear()
