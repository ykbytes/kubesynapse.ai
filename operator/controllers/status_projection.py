"""Status projection controller — mirrors CRD status to PostgreSQL.

§2.5 of the road-to-prod plan: CRD status is authoritative for K8s
consumers; PostgreSQL is the derived store for the API gateway, UI,
and historical queries.  This controller watches `.status.phase`
changes on AgentWorkflow and AgentEval CRDs and projects the current
state into the database, replacing the previous dual-write pattern.
"""

from __future__ import annotations

import logging
from typing import Any

import kopf

from state_store import safe_record_eval_state, safe_record_workflow_state

logger = logging.getLogger("operator.controllers.status_projection")


@kopf.on.field("sandbox.enterprise.ai", "v1alpha1", "agentworkflows", field="status.phase")  # type: ignore[arg-type]
def project_workflow_status(
    old: str | None,
    new: str | None,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Mirror workflow CRD status to PostgreSQL whenever phase changes."""
    del kwargs
    if not new:
        return
    generation = int((meta or {}).get("generation", 1))
    run_id = str((status or {}).get("runId") or "")
    if not run_id:
        return
    safe_record_workflow_state(
        namespace=namespace,
        resource_name=name,
        generation=generation,
        run_id=run_id,
        phase=new,
        spec=spec or {},
        status=status or {},
    )
    logger.debug(
        "Projected workflow '%s/%s' phase %s → %s (run=%s).",
        namespace, name, old, new, run_id,
    )


@kopf.on.field("sandbox.enterprise.ai", "v1alpha1", "agentevals", field="status.phase")  # type: ignore[arg-type]
def project_eval_status(
    old: str | None,
    new: str | None,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Mirror eval CRD status to PostgreSQL whenever phase changes."""
    del kwargs
    if not new:
        return
    generation = int((meta or {}).get("generation", 1))
    run_id = str((status or {}).get("runId") or "")
    if not run_id:
        return
    passed_field = (status or {}).get("passed")
    passed: bool | None = None
    if passed_field is not None:
        passed = bool(passed_field)
    safe_record_eval_state(
        namespace=namespace,
        resource_name=name,
        generation=generation,
        run_id=run_id,
        phase=new,
        passed=passed,
        spec=spec or {},
        status=status or {},
    )
    logger.debug(
        "Projected eval '%s/%s' phase %s → %s (run=%s).",
        namespace, name, old, new, run_id,
    )
