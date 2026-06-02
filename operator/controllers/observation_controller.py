"""AIOps Observability reconciler — ObservationTarget, ObservationPolicy,
ObservationReport, and ConnectorPlugin handlers.

Watches the four observability CRDs and reconciles status.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

logger = logging.getLogger("operator.controllers.observation")

GROUP = "kubesynapse.ai"
VERSION = "v1alpha1"
REPORT_PLURAL = "observationreports"
POLICY_PLURAL = "observationpolicies"
CONNECTOR_PLURAL = "connectorplugins"


def _patch_status_with_retry(plural: str, namespace: str, name: str, status: dict[str, Any]) -> None:
    """Patch CRD status with optimistic-concurrency retry on 409.

    Silently ignores 404 (resource may have been deleted during reconciliation).
    """
    from services.k8s import patch_custom_status

    try:
        patch_custom_status(plural, namespace, name, status)
    except ApiException as exc:
        if exc.status == 404:
            logger.debug("Status patch 404 for %s/%s/%s — resource deleted.", plural, namespace, name)
            return
        raise


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_namespaced_ref(raw_ref: str | None) -> tuple[str | None, str | None]:
    value = str(raw_ref or "").strip()
    if not value:
        return None, None
    if "/" not in value:
        return None, value
    ref_namespace, ref_name = value.split("/", 1)
    return ref_namespace.strip() or None, ref_name.strip() or None


def _get_demo_mode(meta: dict[str, Any], spec: dict[str, Any]) -> str:
    raw_mode = _get_raw_demo_mode(meta, spec)
    if raw_mode is None:
        return "healthy"
    mode = raw_mode
    if mode == "firing":
        return "critical"
    if mode in {"healthy", "warning", "critical", "failed"}:
        return mode
    return "healthy"


def _get_raw_demo_mode(meta: dict[str, Any], spec: dict[str, Any]) -> str | None:
    annotations = meta.get("annotations") or {}
    labels = spec.get("labels") or {}
    raw_mode = (
        annotations.get("observability.kubesynapse.ai/demo-mode")
        or labels.get("demoMode")
        or labels.get("demo-mode")
    )
    if raw_mode is None:
        return None
    mode = str(raw_mode).strip().lower()
    return mode or None


def _is_demo_target(meta: dict[str, Any], spec: dict[str, Any]) -> bool:
    return _get_raw_demo_mode(meta, spec) is not None


def _metric_seed(name: str) -> int:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _select_metric_name(policy_spec: dict[str, Any], target_name: str) -> str:
    metrics = ((policy_spec.get("anomalyDetection") or {}).get("metrics") or [])
    if metrics:
        first_metric = metrics[0]
        if isinstance(first_metric, str) and first_metric.strip():
            return first_metric.strip()
    return f"{target_name.replace('-', '_')}_health_signal"


def _build_findings(
    *,
    target_name: str,
    target_type: str,
    metric_name: str,
    algorithm: str,
    demo_mode: str,
) -> list[dict[str, Any]]:
    now = _now_iso()
    if demo_mode == "healthy":
        return []

    base_findings = [
        {
            "id": f"{target_name}-latency",
            "severity": "warning" if demo_mode == "warning" else "critical",
            "metric": metric_name,
            "algorithm": algorithm,
            "timestamp": now,
            "value": 4.2 if demo_mode == "warning" else 9.7,
            "expected": 1.1,
            "deviation": 2.4 if demo_mode == "warning" else 5.1,
            "description": (
                f"Synthetic {demo_mode} finding for {target_name}. "
                f"This target uses the {target_type} connector path and is intentionally configured "
                "to show what a surfaced anomaly looks like in the dashboard."
            ),
            "recommendation": (
                "Open the report in the Observability workspace, inspect the finding details, and then "
                "switch the target annotation 'observability.kubesynapse.ai/demo-mode' back to 'healthy' "
                "when you no longer want the demo alert to fire."
            ),
        }
    ]
    if demo_mode in {"critical", "failed"}:
        base_findings.append(
            {
                "id": f"{target_name}-availability",
                "severity": "critical",
                "metric": f"{target_name.replace('-', '_')}_availability",
                "algorithm": "demo-rule",
                "timestamp": now,
                "value": 0,
                "expected": 1,
                "deviation": 1,
                "description": (
                    f"Availability check for {target_name} is also marked unhealthy so the policy shows multiple findings, "
                    "which makes the overall purpose of targets, policies, and reports easier to understand in one pass."
                ),
                "recommendation": (
                    "Treat this as the policy output layer: in a real implementation the connector would collect data, "
                    "the policy would evaluate it, and this report would capture the result."
                ),
            }
        )
    return base_findings


def _build_report_status(
    *,
    target_name: str,
    target_spec: dict[str, Any],
    target_status: dict[str, Any],
    policy_spec: dict[str, Any],
    demo_mode: str | None,
) -> dict[str, Any]:
    if demo_mode is None:
        return _build_live_report_status(target_name=target_name, target_status=target_status)

    algorithm = ((policy_spec.get("anomalyDetection") or {}).get("algorithm") or "demo-evaluator")
    metric_name = _select_metric_name(policy_spec, target_name)
    findings = _build_findings(
        target_name=target_name,
        target_type=str(target_spec.get("targetType") or "custom"),
        metric_name=metric_name,
        algorithm=str(algorithm),
        demo_mode=demo_mode,
    )
    health_score = {
        "healthy": 96,
        "warning": 74,
        "critical": 38,
        "failed": 18,
    }.get(demo_mode, 96)
    summary = {
        "healthy": (
            f"{target_name} is currently healthy. The connector is collecting telemetry, the policy is attached, "
            "and this report exists so you can see where future anomalies would appear."
        ),
        "warning": (
            f"{target_name} is intentionally simulating a warning scenario. The report demonstrates how a policy turns "
            "observed signals into a finding before the situation becomes critical."
        ),
        "critical": (
            f"{target_name} is intentionally simulating a firing alert. This is the visible outcome of the observability flow: "
            "target defines what to watch, connector defines how to collect, policy defines evaluation rules, and the report carries the result."
        ),
        "failed": (
            f"{target_name} is intentionally simulating a hard failure so you can inspect a worst-case report with multiple critical findings."
        ),
    }.get(demo_mode, "Observability report generated.")

    return {
        "phase": "Complete",
        "healthScore": health_score,
        "findingsCount": len(findings),
        "lastEvaluated": _now_iso(),
        "findings": findings,
        "summary": summary,
        "sourcePhase": target_status.get("phase", "Pending"),
    }


def _build_live_report_status(*, target_name: str, target_status: dict[str, Any]) -> dict[str, Any]:
    phase = str(target_status.get("phase") or "Pending")
    connector_health = str(target_status.get("connectorHealth") or "Unknown")
    metrics_collected = int(target_status.get("metricsCollected") or 0)
    last_scrape_time = str(target_status.get("lastScrapeTime") or "").strip()
    last_scrape_error = str(target_status.get("lastScrapeError") or "").strip()

    summary = {
        "Pending": (
            f"{target_name} is waiting for connector-backed scrape data. No successful scrape has been reported yet."
        ),
        "Active": (
            f"{target_name} is active based on connector-reported health and scrape state. "
            f"Latest projection includes {metrics_collected} collected metrics."
        ),
        "Degraded": (
            f"{target_name} is degraded because the connector reported partial health or scrape errors."
        ),
        "Failed": (
            f"{target_name} is failed because the connector is unavailable or no usable scrape state could be projected."
        ),
    }.get(phase, f"{target_name} has connector-backed status projection information available.")
    if last_scrape_time:
        summary += f" Last scrape timestamp: {last_scrape_time}."
    if last_scrape_error:
        summary += f" Last scrape error: {last_scrape_error}."

    return {
        "phase": "Complete",
        "healthScore": {
            "Pending": 60,
            "Active": 96,
            "Degraded": 42,
            "Failed": 18,
        }.get(phase, 60),
        "findingsCount": 0,
        "lastEvaluated": _now_iso(),
        "findings": [],
        "summary": summary,
        "sourcePhase": phase,
        "connectorHealth": connector_health,
    }


def _ensure_report_for_target(
    *,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    logger: logging.Logger,
) -> None:
    custom_api = kubernetes.client.CustomObjectsApi()
    report_name = f"{name}-report"
    policy_ref = str(spec.get("policyRef") or "").strip()
    policy_namespace, policy_name = _parse_namespaced_ref(policy_ref)
    resolved_policy_namespace = policy_namespace or namespace
    policy_spec: dict[str, Any] = {}
    if policy_name:
        try:
            policy = custom_api.get_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=resolved_policy_namespace,
                plural=POLICY_PLURAL,
                name=policy_name,
            )
            policy_spec = policy.get("spec") or {}
        except ApiException as exc:
            if exc.status != 404:
                raise

    demo_mode = _get_demo_mode(meta, spec) if _is_demo_target(meta, spec) else None
    report_spec = {
        "targetRef": name,
        "policyRef": policy_ref or None,
        "reportType": "anomaly" if demo_mode not in {None, "healthy"} else "health-check",
    }
    target_uid = str(meta.get("uid") or "")
    report_body = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "ObservationReport",
        "metadata": {
            "name": report_name,
            "namespace": namespace,
            "labels": {
                "kubesynapse.ai/managed-by": "observation-controller",
                "kubesynapse.ai/observation-target": name,
            },
            "ownerReferences": [
                {
                    "apiVersion": f"{GROUP}/{VERSION}",
                    "kind": "ObservationTarget",
                    "name": name,
                    "uid": target_uid,
                    "controller": True,
                    "blockOwnerDeletion": False,
                }
            ] if target_uid else [],
        },
        "spec": report_spec,
    }

    try:
        custom_api.create_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=namespace,
            plural=REPORT_PLURAL,
            body=report_body,
        )
        logger.info("ObservationReport %s/%s created for target %s", namespace, report_name, name)
    except ApiException as exc:
        if exc.status == 409:
            custom_api.patch_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=namespace,
                plural=REPORT_PLURAL,
                name=report_name,
                body={"spec": report_spec},
            )
        else:
            raise

    report_status = _build_report_status(
        target_name=name,
        target_spec=spec,
        target_status=status,
        policy_spec=policy_spec,
        demo_mode=demo_mode,
    )
    _patch_status_with_retry(
        REPORT_PLURAL,
        namespace,
        report_name,
        report_status,
    )


def _reconcile_policy_status(namespace: str, policy_ref: str | None) -> None:
    policy_namespace, policy_name = _parse_namespaced_ref(policy_ref)
    if not policy_name:
        return

    resolved_policy_namespace = policy_namespace or namespace
    custom_api = kubernetes.client.CustomObjectsApi()
    try:
        reports = custom_api.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=namespace,
            plural=REPORT_PLURAL,
        ).get("items", [])
    except ApiException:
        return

    matching_reports = [
        item for item in reports
        if str((item.get("spec") or {}).get("policyRef") or "") == str(policy_ref or policy_name)
    ]
    active_alerts = sum(int((item.get("status") or {}).get("findingsCount", 0)) for item in matching_reports)
    last_evaluated = None
    for item in matching_reports:
        candidate = (item.get("status") or {}).get("lastEvaluated")
        if candidate and (last_evaluated is None or str(candidate) > str(last_evaluated)):
            last_evaluated = candidate

    _patch_status_with_retry(
        POLICY_PLURAL,
        resolved_policy_namespace,
        policy_name,
        {
            "activeAlerts": active_alerts,
            "lastEvaluated": last_evaluated or _now_iso(),
        },
    )


def _normalize_ready_state(raw_ready: Any) -> str:
    value = str(raw_ready or "Unknown").strip().lower()
    if value in {"true", "ready", "healthy"}:
        return "True"
    if value in {"false", "unhealthy", "failed", "error"}:
        return "False"
    return "Unknown"


def _extract_connector_version(spec: dict[str, Any]) -> str:
    image = str((spec or {}).get("image") or "")
    return image.rsplit(":", 1)[1] if ":" in image else "unknown"


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _get_connector_status_snapshot(namespace: str, connector_ref: str | None) -> dict[str, Any]:
    connector_namespace, connector_name = _parse_namespaced_ref(connector_ref)
    resolved_namespace = connector_namespace or namespace
    name = str(connector_name or "").strip()
    if not name:
        return {
            "exists": False,
            "ready": "Unknown",
            "metricsCollected": 0,
            "findingCount": 0,
            "lastHealthCheck": None,
            "lastScrapeTime": None,
            "lastScrapeError": "connectorRef is required for live ObservationTarget reconciliation.",
        }

    custom_api = kubernetes.client.CustomObjectsApi()
    try:
        connector = custom_api.get_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=resolved_namespace,
            plural=CONNECTOR_PLURAL,
            name=name,
        )
    except ApiException as exc:
        if exc.status == 404:
            return {
                "exists": False,
                "ready": "Unknown",
                "metricsCollected": 0,
                "findingCount": 0,
                "lastHealthCheck": None,
                "lastScrapeTime": None,
                "lastScrapeError": f"ConnectorPlugin {resolved_namespace}/{name} was not found.",
            }
        raise

    connector_status = connector.get("status") or {}
    return {
        "exists": True,
        "ready": _normalize_ready_state(connector_status.get("ready")),
        "metricsCollected": _to_int(connector_status.get("metricsCollected")),
        "findingCount": _to_int(connector_status.get("findingCount")),
        "lastHealthCheck": connector_status.get("lastHealthCheck"),
        "lastScrapeTime": connector_status.get("lastScrapeTime") or connector_status.get("lastHealthCheck"),
        "lastScrapeError": connector_status.get("lastScrapeError"),
    }


def _connector_health_from_ready(ready: str) -> str:
    return {
        "True": "Healthy",
        "False": "Unhealthy",
    }.get(ready, "Unknown")


def _build_demo_target_status(*, meta: dict[str, Any], spec: dict[str, Any], name: str) -> dict[str, Any]:
    demo_mode = _get_demo_mode(meta, spec)
    phase = "Active"
    connector_health = "Healthy"
    if demo_mode in {"warning", "critical"}:
        phase = "Degraded"
    elif demo_mode == "failed":
        phase = "Failed"
        connector_health = "Unhealthy"

    return {
        "phase": phase,
        "connectorHealth": connector_health,
        "lastScrapeTime": _now_iso(),
        "lastScrapeError": "",
        "metricsCollected": 12 + (_metric_seed(name) % 5),
    }


def _build_live_target_status(*, namespace: str, spec: dict[str, Any]) -> dict[str, Any]:
    connector_snapshot = _get_connector_status_snapshot(namespace, spec.get("connectorRef"))
    ready = str(connector_snapshot.get("ready") or "Unknown")
    connector_health = _connector_health_from_ready(ready)
    last_scrape_time = connector_snapshot.get("lastScrapeTime")
    last_scrape_error = str(connector_snapshot.get("lastScrapeError") or "").strip()

    phase = "Pending"
    if not connector_snapshot.get("exists") or ready == "False":
        phase = "Failed"
    elif ready == "True" and last_scrape_error:
        phase = "Degraded"
    elif ready == "True" and last_scrape_time:
        phase = "Active"
    elif last_scrape_error:
        phase = "Failed"

    projected = {
        "phase": phase,
        "connectorHealth": connector_health,
        "metricsCollected": _to_int(connector_snapshot.get("metricsCollected")),
        "lastScrapeError": last_scrape_error,
    }
    if last_scrape_time:
        projected["lastScrapeTime"] = last_scrape_time
    return projected


# ---------------------------------------------------------------------------
# ObservationTarget handlers
# ---------------------------------------------------------------------------

@kopf.on.create("kubesynapse.ai", "v1alpha1", "observationtargets")  # type: ignore[arg-type]
def create_observation_target(
    spec: dict[str, Any], name: str, namespace: str, patch: kopf.Patch,
    logger: logging.Logger, **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    logger.info("ObservationTarget %s/%s created (type=%s, connector=%s)",
                namespace, name, spec.get("targetType"), spec.get("connectorRef"))
    patch.status["phase"] = "Pending"
    patch.status["metricsCollected"] = 0
    patch.status["connectorHealth"] = "Unknown"
    return {"message": f"ObservationTarget {name} accepted, awaiting connector readiness."}


@kopf.on.update("kubesynapse.ai", "v1alpha1", "observationtargets")  # type: ignore[arg-type]
def update_observation_target(
    spec: dict[str, Any], name: str, namespace: str, patch: kopf.Patch,
    logger: logging.Logger, **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    logger.info("ObservationTarget %s/%s updated", namespace, name)
    return {"message": f"ObservationTarget {name} spec updated."}


@kopf.on.delete("kubesynapse.ai", "v1alpha1", "observationtargets")  # type: ignore[arg-type]
def delete_observation_target(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any,
) -> None:
    del kwargs
    logger.info("ObservationTarget %s/%s deleted", namespace, name)


# ---------------------------------------------------------------------------
# ObservationPolicy handlers
# ---------------------------------------------------------------------------

@kopf.on.create("kubesynapse.ai", "v1alpha1", "observationpolicies")  # type: ignore[arg-type]
def create_observation_policy(
    spec: dict[str, Any], name: str, namespace: str, patch: kopf.Patch,
    logger: logging.Logger, **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    anomaly = spec.get("anomalyDetection", {})
    logger.info("ObservationPolicy %s/%s created (anomaly=%s, algorithm=%s)",
                namespace, name, anomaly.get("enabled", False), anomaly.get("algorithm", "ensemble"))
    patch.status["activeAlerts"] = 0
    return {"message": f"ObservationPolicy {name} accepted."}


@kopf.on.update("kubesynapse.ai", "v1alpha1", "observationpolicies")  # type: ignore[arg-type]
def update_observation_policy(
    spec: dict[str, Any], name: str, namespace: str,
    logger: logging.Logger, **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    logger.info("ObservationPolicy %s/%s updated", namespace, name)
    return {"message": f"ObservationPolicy {name} spec updated."}


@kopf.on.delete("kubesynapse.ai", "v1alpha1", "observationpolicies")  # type: ignore[arg-type]
def delete_observation_policy(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any,
) -> None:
    del kwargs
    logger.info("ObservationPolicy %s/%s deleted", namespace, name)


# ---------------------------------------------------------------------------
# ObservationReport handlers
# ---------------------------------------------------------------------------

@kopf.on.create("kubesynapse.ai", "v1alpha1", "observationreports")  # type: ignore[arg-type]
def create_observation_report(
    spec: dict[str, Any], name: str, namespace: str, patch: kopf.Patch,
    logger: logging.Logger, **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    logger.info("ObservationReport %s/%s created (target=%s, type=%s)",
                namespace, name, spec.get("targetRef"), spec.get("reportType"))
    patch.status["phase"] = "Pending"
    patch.status["healthScore"] = None
    patch.status["findingsCount"] = 0
    patch.status["findings"] = []
    return {"message": f"ObservationReport {name} accepted, awaiting evaluation."}


@kopf.on.update("kubesynapse.ai", "v1alpha1", "observationreports")  # type: ignore[arg-type]
def update_observation_report(
    spec: dict[str, Any], name: str, namespace: str,
    logger: logging.Logger, **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    logger.info("ObservationReport %s/%s updated", namespace, name)
    return {"message": f"ObservationReport {name} spec updated."}


@kopf.on.delete("kubesynapse.ai", "v1alpha1", "observationreports")  # type: ignore[arg-type]
def delete_observation_report(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any,
) -> None:
    del kwargs
    logger.info("ObservationReport %s/%s deleted", namespace, name)


# ---------------------------------------------------------------------------
# ConnectorPlugin handlers
# ---------------------------------------------------------------------------

@kopf.on.create("kubesynapse.ai", "v1alpha1", "connectorplugins")  # type: ignore[arg-type]
def create_connector_plugin(
    spec: dict[str, Any], name: str, namespace: str, patch: kopf.Patch,
    logger: logging.Logger, **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    logger.info("ConnectorPlugin %s/%s created (image=%s, protocol=%s)",
                namespace, name, spec.get("image"), spec.get("protocol"))
    patch.status["ready"] = "Unknown"
    patch.status["version"] = _extract_connector_version(spec)
    patch.status["metricsCollected"] = 0
    patch.status["findingCount"] = 0
    return {"message": f"ConnectorPlugin {name} accepted, awaiting health check."}


@kopf.on.update("kubesynapse.ai", "v1alpha1", "connectorplugins")  # type: ignore[arg-type]
def update_connector_plugin(
    spec: dict[str, Any], name: str, namespace: str, patch: kopf.Patch,
    logger: logging.Logger, **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    logger.info("ConnectorPlugin %s/%s updated", namespace, name)
    patch.status["version"] = _extract_connector_version(spec)
    return {"message": f"ConnectorPlugin {name} spec updated."}


@kopf.on.delete("kubesynapse.ai", "v1alpha1", "connectorplugins")  # type: ignore[arg-type]
def delete_connector_plugin(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any,
) -> None:
    del kwargs
    logger.info("ConnectorPlugin %s/%s deleted", namespace, name)


# ---------------------------------------------------------------------------
# Periodic timer — target scrape status reconciler
# ---------------------------------------------------------------------------

@kopf.timer("kubesynapse.ai", "v1alpha1", "observationtargets", interval=60)  # type: ignore[arg-type]
def reconcile_target_status(
    spec: dict[str, Any], status: dict[str, Any], meta: dict[str, Any], name: str, namespace: str,
    patch: kopf.Patch, logger: logging.Logger, **kwargs: Any,
) -> None:
    """Periodic reconciliation of ObservationTarget status.

    In production this would query the connector sidecar health endpoint
    and update scrape statistics. For now it transitions Pending → Active.
    """
    del kwargs
    try:
        if _is_demo_target(meta, spec):
            projected_status = _build_demo_target_status(meta=meta, spec=spec, name=name)
            demo_mode = _get_demo_mode(meta, spec)
        else:
            projected_status = _build_live_target_status(namespace=namespace, spec=spec)
            demo_mode = None

        for key, value in projected_status.items():
            patch.status[key] = value

        _ensure_report_for_target(
            name=name,
            namespace=namespace,
            spec=spec,
            status={
                **status,
                **projected_status,
            },
            meta=meta,
            logger=logger,
        )
        _reconcile_policy_status(namespace, spec.get("policyRef"))
        logger.info(
            "ObservationTarget %s/%s reconciled (mode=%s, phase=%s)",
            namespace,
            name,
            demo_mode or "live",
            projected_status.get("phase"),
        )
    except kubernetes.client.ApiException as exc:
        logger.warning("ObservationTarget %s/%s reconciliation failed: %s", namespace, name, exc)
