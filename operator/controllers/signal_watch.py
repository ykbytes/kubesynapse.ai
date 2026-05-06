"""Run Intelligence Layer — Deterministic Signal Watch Controller.

Periodically scans the runtime_run_events table for anomalies and creates
ObservationReport CRs. Uses deterministic SQL/rule checks — no LLM involved
in detection. LLM system agents are only invoked for explanation/escalation.

Anomaly checks:
1. High failure rate — >30% of steps failed in recent runs
2. Error spike — >=3 errors in a 15-minute window for same agent
3. Cost outlier — single run cost >3x namespace average
4. Token spike — run tokens >3x rolling average for agent
5. Stuck run — running for >2x typical duration

Schedule: every 60 seconds (configurable via SIGNAL_WATCH_INTERVAL_SEC)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

logger = logging.getLogger("operator.signal-watch")

GROUP = "kubesynapse.ai"
VERSION = "v1alpha1"
REPORT_PLURAL = "observationreports"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WATCH_INTERVAL_SEC = int(os.getenv("SIGNAL_WATCH_INTERVAL_SEC", "60"))
ANOMALY_WINDOW_MINUTES = int(os.getenv("SIGNAL_WATCH_WINDOW_MINUTES", "15"))
FAILURE_RATE_THRESHOLD = float(os.getenv("SIGNAL_WATCH_FAILURE_RATE", "0.3"))
ERROR_COUNT_THRESHOLD = int(os.getenv("SIGNAL_WATCH_ERROR_COUNT", "3"))
COST_MULTIPLIER_THRESHOLD = float(os.getenv("SIGNAL_WATCH_COST_MULTIPLIER", "3.0"))
TOKEN_MULTIPLIER_THRESHOLD = float(os.getenv("SIGNAL_WATCH_TOKEN_MULTIPLIER", "3.0"))
STUCK_RUN_MULTIPLIER = float(os.getenv("SIGNAL_WATCH_STUCK_MULTIPLIER", "2.0"))
SYSTEM_AGENT_NAMESPACE = os.getenv("SIGNAL_WATCH_SYSTEM_NS", "kubesynapse-system")

# ---------------------------------------------------------------------------
# Database access (reuse auth_store connection)
# ---------------------------------------------------------------------------

_db_engine = None


def _get_db_engine():
    global _db_engine
    if _db_engine is None:
        try:
            from auth_store import ENGINE as _AUTH_ENGINE
            _db_engine = _AUTH_ENGINE
        except ImportError:
            logger.warning("auth_store not available; signal watch disabled")
    return _db_engine


def _query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute a raw SQL query and return rows as dicts."""
    engine = _get_db_engine()
    if engine is None:
        return []
    with engine.connect() as conn:
        result = conn.execute(kopf.text(sql), params)
        columns = result.keys()
        return [dict(zip(columns, row)) for row in result]


# ---------------------------------------------------------------------------
# Anomaly detection queries
# ---------------------------------------------------------------------------

def _check_high_failure_rate() -> list[dict[str, Any]]:
    """Find runs where >30% of steps failed in the recent window."""
    cutoff = (datetime.now(UTC) - timedelta(minutes=ANOMALY_WINDOW_MINUTES)).isoformat()
    sql = """
        SELECT
            we.namespace,
            we.workflow_name,
            we.id AS execution_id,
            we.status,
            we.total_steps,
            we.failed_steps,
            ROUND(CAST(we.failed_steps AS FLOAT) / NULLIF(we.total_steps, 0), 2) AS failure_rate,
            we.started_at
        FROM workflow_executions we
        WHERE we.started_at >= :cutoff
          AND we.total_steps > 0
          AND CAST(we.failed_steps AS FLOAT) / NULLIF(we.total_steps, 0) >= :threshold
        ORDER BY failure_rate DESC
        LIMIT 20
    """
    return _query(sql, {"cutoff": cutoff, "threshold": FAILURE_RATE_THRESHOLD})


def _check_error_spikes() -> list[dict[str, Any]]:
    """Find agents with >=3 errors in the recent window."""
    cutoff = (datetime.now(UTC) - timedelta(minutes=ANOMALY_WINDOW_MINUTES)).isoformat()
    sql = """
        SELECT
            re.namespace,
            re.agent_name,
            re.runtime_kind,
            COUNT(*) AS error_count,
            MIN(re.created_at) AS first_error,
            MAX(re.created_at) AS last_error,
            ARRAY_AGG(DISTINCT re.execution_id) AS affected_executions
        FROM runtime_run_events re
        WHERE re.created_at >= :cutoff
          AND re.severity = 'error'
        GROUP BY re.namespace, re.agent_name, re.runtime_kind
        HAVING COUNT(*) >= :threshold
        ORDER BY error_count DESC
        LIMIT 20
    """
    return _query(sql, {"cutoff": cutoff, "threshold": ERROR_COUNT_THRESHOLD})


def _check_cost_outliers() -> list[dict[str, Any]]:
    """Find runs where cost >3x the namespace average."""
    cutoff = (datetime.now(UTC) - timedelta(minutes=ANOMALY_WINDOW_MINUTES * 4)).isoformat()
    sql = """
        WITH namespace_avg AS (
            SELECT
                namespace,
                AVG(cost_usd) AS avg_cost
            FROM workflow_executions
            WHERE started_at >= :cutoff
              AND cost_usd IS NOT NULL
              AND cost_usd > 0
            GROUP BY namespace
        )
        SELECT
            we.namespace,
            we.workflow_name,
            we.id AS execution_id,
            we.cost_usd,
            na.avg_cost,
            ROUND(we.cost_usd / NULLIF(na.avg_cost, 0), 2) AS cost_multiplier,
            we.started_at
        FROM workflow_executions we
        JOIN namespace_avg na ON we.namespace = na.namespace
        WHERE we.started_at >= :cutoff
          AND we.cost_usd IS NOT NULL
          AND we.cost_usd > 0
          AND we.cost_usd / NULLIF(na.avg_cost, 0) >= :multiplier
        ORDER BY cost_multiplier DESC
        LIMIT 20
    """
    return _query(sql, {"cutoff": cutoff, "multiplier": COST_MULTIPLIER_THRESHOLD})


def _check_token_spikes() -> list[dict[str, Any]]:
    """Find runs where tokens >3x the agent's rolling average."""
    cutoff = (datetime.now(UTC) - timedelta(minutes=ANOMALY_WINDOW_MINUTES * 4)).isoformat()
    sql = """
        WITH agent_avg AS (
            SELECT
                namespace,
                agent_name,
                AVG(total_tokens) AS avg_tokens
            FROM workflow_executions
            WHERE started_at >= :cutoff
              AND total_tokens IS NOT NULL
              AND total_tokens > 0
            GROUP BY namespace, agent_name
        )
        SELECT
            we.namespace,
            we.agent_name,
            we.id AS execution_id,
            we.total_tokens,
            aa.avg_tokens,
            ROUND(we.total_tokens::FLOAT / NULLIF(aa.avg_tokens, 0), 2) AS token_multiplier,
            we.started_at
        FROM workflow_executions we
        JOIN agent_avg aa ON we.namespace = aa.namespace AND we.agent_name = aa.agent_name
        WHERE we.started_at >= :cutoff
          AND we.total_tokens IS NOT NULL
          AND we.total_tokens > 0
          AND we.total_tokens::FLOAT / NULLIF(aa.avg_tokens, 0) >= :multiplier
        ORDER BY token_multiplier DESC
        LIMIT 20
    """
    return _query(sql, {"cutoff": cutoff, "multiplier": TOKEN_MULTIPLIER_THRESHOLD})


def _check_stuck_runs() -> list[dict[str, Any]]:
    """Find runs that have been running >2x typical duration."""
    cutoff = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
    sql = """
        WITH typical_duration AS (
            SELECT
                namespace,
                workflow_name,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) AS median_ms
            FROM workflow_executions
            WHERE status = 'completed'
              AND duration_ms IS NOT NULL
              AND duration_ms > 0
            GROUP BY namespace, workflow_name
        )
        SELECT
            we.namespace,
            we.workflow_name,
            we.id AS execution_id,
            we.duration_ms AS current_duration,
            td.median_ms,
            ROUND(we.duration_ms::FLOAT / NULLIF(td.median_ms, 0), 2) AS duration_multiplier,
            we.started_at
        FROM workflow_executions we
        JOIN typical_duration td ON we.namespace = td.namespace AND we.workflow_name = td.workflow_name
        WHERE we.status = 'running'
          AND we.started_at >= :cutoff
          AND we.duration_ms IS NOT NULL
          AND we.duration_ms > 0
          AND we.duration_ms::FLOAT / NULLIF(td.median_ms, 0) >= :multiplier
        ORDER BY duration_multiplier DESC
        LIMIT 20
    """
    return _query(sql, {"cutoff": cutoff, "multiplier": STUCK_RUN_MULTIPLIER})


# ---------------------------------------------------------------------------
# ObservationReport creation
# ---------------------------------------------------------------------------

def _create_observation_report(
    namespace: str,
    name: str,
    anomaly_type: str,
    severity: str,
    title: str,
    description: str,
    details: dict[str, Any],
    affected_executions: list[str] | None = None,
) -> None:
    """Create an ObservationReport CR for a detected anomaly."""
    report_name = f"signal-{anomaly_type}-{int(time.time())}-{name[:8]}"
    report_name = report_name[:253].lower().replace("_", "-")

    body = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "ObservationReport",
        "metadata": {
            "name": report_name,
            "namespace": namespace,
            "labels": {
                "kubesynapse.ai/anomaly-type": anomaly_type,
                "kubesynapse.ai/severity": severity,
                "kubesynapse.ai/source": "signal-watch",
            },
        },
        "spec": {
            "targetRef": {
                "kind": "WorkflowExecution",
                "name": name,
                "namespace": namespace,
            },
            "anomalyType": anomaly_type,
            "severity": severity,
            "title": title,
            "description": description,
            "details": details,
            "detectedAt": datetime.now(UTC).isoformat(),
            "status": "new",
        },
    }

    if affected_executions:
        body["spec"]["affectedExecutions"] = affected_executions[:10]

    try:
        kubernetes.client.CustomObjectsApi().create_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=namespace,
            plural=REPORT_PLURAL,
            body=body,
        )
        logger.info(
            "Created ObservationReport %s/%s (type=%s, severity=%s)",
            namespace, report_name, anomaly_type, severity,
        )
    except ApiException as exc:
        if exc.status == 409:
            logger.debug("ObservationReport %s/%s already exists", namespace, report_name)
        else:
            logger.warning("Failed to create ObservationReport: %s", exc)


def _severity_from_rate(rate: float, thresholds: tuple[float, float, float]) -> str:
    """Map a numeric rate to severity level."""
    low, medium, high = thresholds
    if rate >= high:
        return "critical"
    if rate >= medium:
        return "high"
    if rate >= low:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Periodic timer (kopf timer)
# ---------------------------------------------------------------------------

@kopf.timer(
    "aiagents",
    group=GROUP,
    version=VERSION,
    interval=WATCH_INTERVAL_SEC,
    labels={"kubesynapse.ai/system-agent": "true"},
)
@kopf.on.startup()
def signal_watch_timer(**kwargs: Any) -> None:
    """Run anomaly detection checks on schedule."""
    if kwargs.get("settings"):
        return  # startup only

    logger.debug("Signal watch: running anomaly detection checks")

    try:
        # 1. High failure rate
        failures = _check_high_failure_rate()
        for row in failures:
            severity = _severity_from_rate(
                row.get("failure_rate", 0),
                (0.3, 0.5, 0.7),
            )
            _create_observation_report(
                namespace=row["namespace"],
                name=row["workflow_name"],
                anomaly_type="high_failure_rate",
                severity=severity,
                title=f"High failure rate in {row['workflow_name']}",
                description=f"{row['failed_steps']}/{row['total_steps']} steps failed ({row['failure_rate']*100:.0f}%)",
                details={
                    "execution_id": row["execution_id"],
                    "total_steps": row["total_steps"],
                    "failed_steps": row["failed_steps"],
                    "failure_rate": row["failure_rate"],
                    "started_at": row["started_at"],
                },
                affected_executions=[row["execution_id"]],
            )

        # 2. Error spikes
        spikes = _check_error_spikes()
        for row in spikes:
            severity = _severity_from_rate(
                row.get("error_count", 0) / max(ERROR_COUNT_THRESHOLD, 1),
                (1.0, 2.0, 5.0),
            )
            affected = row.get("affected_executions") or []
            _create_observation_report(
                namespace=row["namespace"],
                name=row["agent_name"] or "unknown",
                anomaly_type="error_spike",
                severity=severity,
                title=f"Error spike in {row['agent_name']}",
                description=f"{row['error_count']} errors in {ANOMALY_WINDOW_MINUTES}m window",
                details={
                    "agent_name": row["agent_name"],
                    "runtime_kind": row["runtime_kind"],
                    "error_count": row["error_count"],
                    "first_error": row["first_error"],
                    "last_error": row["last_error"],
                },
                affected_executions=[str(e) for e in affected[:10]] if affected else None,
            )

        # 3. Cost outliers
        outliers = _check_cost_outliers()
        for row in outliers:
            severity = _severity_from_rate(
                row.get("cost_multiplier", 0),
                (3.0, 5.0, 10.0),
            )
            _create_observation_report(
                namespace=row["namespace"],
                name=row["workflow_name"],
                anomaly_type="cost_outlier",
                severity=severity,
                title=f"Cost outlier in {row['workflow_name']}",
                description=f"Cost ${row['cost_usd']:.2f} is {row['cost_multiplier']}x namespace avg ${row['avg_cost']:.2f}",
                details={
                    "execution_id": row["execution_id"],
                    "cost_usd": row["cost_usd"],
                    "avg_cost": row["avg_cost"],
                    "cost_multiplier": row["cost_multiplier"],
                    "started_at": row["started_at"],
                },
                affected_executions=[row["execution_id"]],
            )

        # 4. Token spikes
        token_spikes = _check_token_spikes()
        for row in token_spikes:
            severity = _severity_from_rate(
                row.get("token_multiplier", 0),
                (3.0, 5.0, 10.0),
            )
            _create_observation_report(
                namespace=row["namespace"],
                name=row["agent_name"] or "unknown",
                anomaly_type="token_spike",
                severity=severity,
                title=f"Token spike in {row['agent_name']}",
                description=f"{row['total_tokens']} tokens is {row['token_multiplier']}x agent avg {row['avg_tokens']:.0f}",
                details={
                    "execution_id": row["execution_id"],
                    "total_tokens": row["total_tokens"],
                    "avg_tokens": row["avg_tokens"],
                    "token_multiplier": row["token_multiplier"],
                    "started_at": row["started_at"],
                },
                affected_executions=[row["execution_id"]],
            )

        # 5. Stuck runs
        stuck = _check_stuck_runs()
        for row in stuck:
            severity = _severity_from_rate(
                row.get("duration_multiplier", 0),
                (2.0, 3.0, 5.0),
            )
            _create_observation_report(
                namespace=row["namespace"],
                name=row["workflow_name"],
                anomaly_type="stuck_run",
                severity=severity,
                title=f"Stuck run: {row['workflow_name']}",
                description=f"Running {row['current_duration']}ms ({row['duration_multiplier']}x median {row['median_ms']}ms)",
                details={
                    "execution_id": row["execution_id"],
                    "current_duration_ms": row["current_duration"],
                    "median_duration_ms": row["median_ms"],
                    "duration_multiplier": row["duration_multiplier"],
                    "started_at": row["started_at"],
                },
                affected_executions=[row["execution_id"]],
            )

        total = len(failures) + len(spikes) + len(outliers) + len(token_spikes) + len(stuck)
        if total > 0:
            logger.info("Signal watch: detected %d anomalies", total)

    except Exception:
        logger.warning("Signal watch: anomaly detection failed", exc_info=True)
