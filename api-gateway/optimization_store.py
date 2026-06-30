"""Persistence helpers for workflow optimization studies.

The optimization lab uses the same gateway database as auth and trace storage,
but keeps its own small SQLAlchemy metadata so it can be initialized on demand
without touching the larger auth model graph.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, inspect, or_, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import declarative_base

from auth_store import ENGINE as _AUTH_ENGINE
from auth_store import db_session, ensure_utc, utc_now

logger = logging.getLogger("api-gateway.optimization-store")

Base = declarative_base()
_OPTIMIZATION_TABLES = (
    "optimization_studies",
    "optimization_candidates",
    "optimization_trials",
)
_SCHEMA_ERRORS = (OperationalError, ProgrammingError)


def _json_clone(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _compile_type_sql(column_type: Any, dialect: Any) -> str:
    return str(column_type.compile(dialect=dialect))


class OptimizationStudyRow(Base):
    __tablename__ = "optimization_studies"

    id = Column(String(64), primary_key=True)
    namespace = Column(String(128), nullable=False, index=True)
    workflow_name = Column(String(256), nullable=False, index=True)
    optimizer_agent_name = Column(String(256), nullable=True)
    status = Column(String(64), nullable=False, default="baseline_ready", index=True)
    objective = Column(String(2048), nullable=True)
    baseline_execution_ids = Column(JSON, nullable=False, default=list)
    baseline_metrics = Column(JSON, nullable=False, default=dict)
    opportunities = Column(JSON, nullable=False, default=list)
    source_manifests = Column(JSON, nullable=False, default=dict)
    proof_gate = Column(JSON, nullable=False, default=dict)
    dataset_redaction_state = Column(String(64), nullable=False, default="redacted")
    created_by = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "workflow_name": self.workflow_name,
            "optimizer_agent_name": self.optimizer_agent_name,
            "status": self.status,
            "objective": self.objective,
            "baseline_execution_ids": _json_clone(self.baseline_execution_ids) or [],
            "baseline_metrics": _json_clone(self.baseline_metrics) or {},
            "opportunities": _json_clone(self.opportunities) or [],
            "source_manifests": _json_clone(self.source_manifests) or {},
            "proof_gate": _json_clone(self.proof_gate) or {},
            "dataset_redaction_state": self.dataset_redaction_state,
            "created_by": self.created_by,
            "created_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
            "updated_at": ensure_utc(self.updated_at).isoformat() if self.updated_at else None,
        }


class OptimizationCandidateRow(Base):
    __tablename__ = "optimization_candidates"

    id = Column(String(64), primary_key=True)
    study_id = Column(String(64), ForeignKey("optimization_studies.id", ondelete="CASCADE"), nullable=False, index=True)
    namespace = Column(String(128), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    candidate_workflow_name = Column(String(256), nullable=False, index=True)
    status = Column(String(64), nullable=False, default="draft", index=True)
    approval_status = Column(String(64), nullable=False, default="pending", index=True)
    manifest_bundle = Column(JSON, nullable=False, default=list)
    manifest_diff = Column(JSON, nullable=False, default=dict)
    optimizer_output = Column(String, nullable=True)
    optimizer_trace = Column(JSON, nullable=False, default=dict)
    validation_results = Column(JSON, nullable=False, default=dict)
    expected_savings = Column(JSON, nullable=False, default=dict)
    tags = Column(JSON, nullable=False, default=list)
    lifecycle_state = Column(String(32), nullable=False, default="active", index=True)
    created_by = Column(String(256), nullable=True)
    approved_by = Column(String(256), nullable=True)
    approval_reason = Column(String(1024), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(String(256), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "study_id": self.study_id,
            "namespace": self.namespace,
            "name": self.name,
            "candidate_workflow_name": self.candidate_workflow_name,
            "status": self.status,
            "approval_status": self.approval_status,
            "manifest_bundle": _json_clone(self.manifest_bundle) or [],
            "manifest_diff": _json_clone(self.manifest_diff) or {},
            "optimizer_output": self.optimizer_output,
            "optimizer_trace": _json_clone(self.optimizer_trace) or {},
            "validation_results": _json_clone(self.validation_results) or {},
            "expected_savings": _json_clone(self.expected_savings) or {},
            "tags": _json_clone(self.tags) or [],
            "lifecycle_state": self.lifecycle_state or "active",
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "approval_reason": self.approval_reason,
            "approved_at": ensure_utc(self.approved_at).isoformat() if self.approved_at else None,
            "applied_at": ensure_utc(self.applied_at).isoformat() if self.applied_at else None,
            "archived_by": self.archived_by,
            "archived_at": ensure_utc(self.archived_at).isoformat() if self.archived_at else None,
            "created_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
            "updated_at": ensure_utc(self.updated_at).isoformat() if self.updated_at else None,
        }


class OptimizationTrialRow(Base):
    __tablename__ = "optimization_trials"

    id = Column(String(64), primary_key=True)
    study_id = Column(String(64), ForeignKey("optimization_studies.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id = Column(String(64), ForeignKey("optimization_candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    baseline_execution_id = Column(String(128), nullable=False, index=True)
    result_execution_id = Column(String(128), nullable=True, index=True)
    status = Column(String(64), nullable=False, default="recorded", index=True)
    quality_status = Column(String(64), nullable=False, default="needs_review")
    metrics_delta = Column(JSON, nullable=False, default=dict)
    notes = Column(String(2048), nullable=True)
    created_by = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "study_id": self.study_id,
            "candidate_id": self.candidate_id,
            "baseline_execution_id": self.baseline_execution_id,
            "result_execution_id": self.result_execution_id,
            "status": self.status,
            "quality_status": self.quality_status,
            "metrics_delta": _json_clone(self.metrics_delta) or {},
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
        }


def init_optimization_database() -> None:
    Base.metadata.create_all(bind=_AUTH_ENGINE)
    _ensure_optimization_schema()
    logger.info("Optimization database initialized")


def ensure_optimization_database() -> None:
    try:
        with _AUTH_ENGINE.connect() as connection:
            existing = set(inspect(connection).get_table_names())
    except _SCHEMA_ERRORS:
        logger.exception("Failed to inspect optimization database state")
        raise
    if set(_OPTIMIZATION_TABLES).issubset(existing):
        _ensure_optimization_schema()
        return
    init_optimization_database()


def _ensure_optimization_schema() -> None:
    """Apply lightweight additive migrations for existing gateway databases."""
    with _AUTH_ENGINE.begin() as connection:
        inspector = inspect(connection)
        if "optimization_studies" not in inspector.get_table_names():
            return

        study_columns = {str(column.get("name") or "") for column in inspector.get_columns("optimization_studies")}
        if "proof_gate" not in study_columns:
            proof_gate_type = _compile_type_sql(JSON(), connection.dialect)
            connection.execute(text(f"ALTER TABLE optimization_studies ADD COLUMN proof_gate {proof_gate_type}"))
            connection.execute(
                text("UPDATE optimization_studies SET proof_gate = :proof_gate WHERE proof_gate IS NULL"),
                {"proof_gate": json.dumps({"mode": "hybrid", "requires_approval": True})},
            )
            logger.info("Added optimization_studies.proof_gate column")

        if "optimization_candidates" not in inspector.get_table_names():
            return
        candidate_columns = {
            str(column.get("name") or "")
            for column in inspector.get_columns("optimization_candidates")
        }
        if "optimizer_trace" not in candidate_columns:
            optimizer_trace_type = _compile_type_sql(JSON(), connection.dialect)
            connection.execute(
                text(f"ALTER TABLE optimization_candidates ADD COLUMN optimizer_trace {optimizer_trace_type}")
            )
            connection.execute(
                text("UPDATE optimization_candidates SET optimizer_trace = :optimizer_trace WHERE optimizer_trace IS NULL"),
                {"optimizer_trace": json.dumps({})},
            )
            logger.info("Added optimization_candidates.optimizer_trace column")
        if "tags" not in candidate_columns:
            tags_type = _compile_type_sql(JSON(), connection.dialect)
            connection.execute(text(f"ALTER TABLE optimization_candidates ADD COLUMN tags {tags_type}"))
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text("UPDATE optimization_candidates SET tags = CAST(:tags AS JSON) WHERE tags IS NULL"),
                    {"tags": json.dumps([])},
                )
            else:
                connection.execute(
                    text("UPDATE optimization_candidates SET tags = :tags WHERE tags IS NULL"),
                    {"tags": json.dumps([])},
                )
            logger.info("Added optimization_candidates.tags column")
        if "lifecycle_state" not in candidate_columns:
            connection.execute(
                text(
                    "ALTER TABLE optimization_candidates "
                    "ADD COLUMN lifecycle_state VARCHAR(32) NOT NULL DEFAULT 'active'"
                )
            )
            logger.info("Added optimization_candidates.lifecycle_state column")
        if "archived_by" not in candidate_columns:
            connection.execute(
                text("ALTER TABLE optimization_candidates ADD COLUMN archived_by VARCHAR(256)")
            )
            logger.info("Added optimization_candidates.archived_by column")
        if "archived_at" not in candidate_columns:
            archived_at_type = _compile_type_sql(DateTime(timezone=True), connection.dialect)
            connection.execute(
                text(f"ALTER TABLE optimization_candidates ADD COLUMN archived_at {archived_at_type}")
            )
            logger.info("Added optimization_candidates.archived_at column")


def create_study(
    *,
    namespace: str,
    workflow_name: str,
    optimizer_agent_name: str | None,
    objective: str | None,
    baseline_execution_ids: list[str],
    baseline_metrics: dict[str, Any],
    opportunities: list[dict[str, Any]],
    source_manifests: dict[str, Any],
    created_by: str | None,
    proof_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_optimization_database()
    row = OptimizationStudyRow(
        id=f"opt-{uuid.uuid4().hex[:16]}",
        namespace=namespace,
        workflow_name=workflow_name,
        optimizer_agent_name=optimizer_agent_name,
        status="baseline_ready",
        objective=objective,
        baseline_execution_ids=baseline_execution_ids,
        baseline_metrics=baseline_metrics,
        opportunities=opportunities,
        source_manifests=source_manifests,
        proof_gate=proof_gate or {"mode": "hybrid", "requires_approval": True},
        dataset_redaction_state="redacted",
        created_by=created_by,
    )
    with db_session() as session:
        session.add(row)
        session.flush()
        return row.to_dict()


def get_study(study_id: str) -> dict[str, Any] | None:
    ensure_optimization_database()
    with db_session() as session:
        row = session.query(OptimizationStudyRow).filter_by(id=study_id).one_or_none()
        return row.to_dict() if row else None


def list_studies(
    *,
    namespace: str | None = None,
    workflow_name: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ensure_optimization_database()
    with db_session() as session:
        query = session.query(OptimizationStudyRow)
        if namespace:
            query = query.filter_by(namespace=namespace)
        if workflow_name:
            query = query.filter_by(workflow_name=workflow_name)
        rows = (
            query.order_by(OptimizationStudyRow.created_at.desc())
            .offset(max(offset, 0))
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [row.to_dict() for row in rows]


def create_candidate(
    *,
    study_id: str,
    namespace: str,
    name: str,
    candidate_workflow_name: str,
    manifest_bundle: list[dict[str, Any]],
    manifest_diff: dict[str, Any],
    optimizer_output: str | None,
    optimizer_trace: dict[str, Any] | None,
    validation_results: dict[str, Any],
    expected_savings: dict[str, Any],
    created_by: str | None,
) -> dict[str, Any]:
    ensure_optimization_database()
    row = OptimizationCandidateRow(
        id=f"cand-{uuid.uuid4().hex[:16]}",
        study_id=study_id,
        namespace=namespace,
        name=name,
        candidate_workflow_name=candidate_workflow_name,
        status="validated" if validation_results.get("valid") else "invalid",
        approval_status="pending",
        manifest_bundle=manifest_bundle,
        manifest_diff=manifest_diff,
        optimizer_output=optimizer_output,
        optimizer_trace=optimizer_trace or {},
        validation_results=validation_results,
        expected_savings=expected_savings,
        tags=[],
        lifecycle_state="active",
        created_by=created_by,
    )
    with db_session() as session:
        session.add(row)
        session.flush()
        return row.to_dict()


def get_candidate(candidate_id: str) -> dict[str, Any] | None:
    ensure_optimization_database()
    with db_session() as session:
        row = session.query(OptimizationCandidateRow).filter_by(id=candidate_id).one_or_none()
        return row.to_dict() if row else None


def list_candidates(study_id: str) -> list[dict[str, Any]]:
    ensure_optimization_database()
    with db_session() as session:
        rows = (
            session.query(OptimizationCandidateRow)
            .filter_by(study_id=study_id)
            .order_by(OptimizationCandidateRow.created_at.asc())
            .all()
        )
        return [row.to_dict() for row in rows]


def list_candidate_registry(
    *,
    namespace: str,
    workflow_name: str | None = None,
    status: str | None = None,
    approval_status: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ensure_optimization_database()
    with db_session() as session:
        query = (
            session.query(OptimizationCandidateRow, OptimizationStudyRow)
            .join(OptimizationStudyRow, OptimizationStudyRow.id == OptimizationCandidateRow.study_id)
            .filter(OptimizationCandidateRow.namespace == namespace)
        )
        if workflow_name:
            query = query.filter(OptimizationStudyRow.workflow_name == workflow_name)
        if status:
            query = query.filter(OptimizationCandidateRow.status == status)
        if approval_status:
            query = query.filter(OptimizationCandidateRow.approval_status == approval_status)
        if not include_archived:
            query = query.filter(OptimizationCandidateRow.lifecycle_state == "active")
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    OptimizationCandidateRow.name.ilike(pattern),
                    OptimizationCandidateRow.candidate_workflow_name.ilike(pattern),
                    OptimizationCandidateRow.id.ilike(pattern),
                )
            )
        rows = query.order_by(OptimizationCandidateRow.created_at.desc()).all()
        items: list[dict[str, Any]] = []
        normalized_tag = tag.strip().lower() if tag else ""
        for candidate_row, study_row in rows:
            candidate = candidate_row.to_dict()
            if normalized_tag and normalized_tag not in {
                str(item).strip().lower() for item in candidate.get("tags") or []
            }:
                continue
            candidate["workflow_name"] = study_row.workflow_name
            candidate["baseline_execution_count"] = len(study_row.baseline_execution_ids or [])
            candidate["study_status"] = study_row.status
            candidate["study_created_at"] = (
                ensure_utc(study_row.created_at).isoformat() if study_row.created_at else None
            )
            candidate["trial_count"] = (
                session.query(OptimizationTrialRow)
                .filter_by(candidate_id=candidate_row.id)
                .count()
            )
            items.append(candidate)
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, 200))
        return items[safe_offset : safe_offset + safe_limit]


def update_candidate_tags(candidate_id: str, tags: list[str]) -> dict[str, Any] | None:
    ensure_optimization_database()
    with db_session() as session:
        row = session.query(OptimizationCandidateRow).filter_by(id=candidate_id).one_or_none()
        if row is None:
            return None
        row.tags = _json_clone(tags) or []
        row.updated_at = utc_now()
        session.flush()
        return row.to_dict()


def archive_candidate(candidate_id: str, *, archived_by: str | None) -> dict[str, Any] | None:
    ensure_optimization_database()
    with db_session() as session:
        row = session.query(OptimizationCandidateRow).filter_by(id=candidate_id).one_or_none()
        if row is None:
            return None
        row.lifecycle_state = "archived"
        row.archived_by = archived_by
        row.archived_at = utc_now()
        row.updated_at = utc_now()
        session.flush()
        return row.to_dict()


def decide_candidate(
    *,
    candidate_id: str,
    decision: str,
    reason: str | None,
    approved_by: str | None,
) -> dict[str, Any] | None:
    ensure_optimization_database()
    with db_session() as session:
        row = session.query(OptimizationCandidateRow).filter_by(id=candidate_id).one_or_none()
        if row is None:
            return None
        row.approval_status = decision
        row.status = "approved" if decision == "approved" else "rejected"
        row.approval_reason = reason
        row.approved_by = approved_by
        row.approved_at = utc_now()
        session.flush()
        return row.to_dict()


def mark_candidate_applied(candidate_id: str) -> dict[str, Any] | None:
    ensure_optimization_database()
    with db_session() as session:
        row = session.query(OptimizationCandidateRow).filter_by(id=candidate_id).one_or_none()
        if row is None:
            return None
        row.status = "applied"
        row.applied_at = utc_now()
        session.flush()
        return row.to_dict()


def promote_candidate(
    *,
    candidate_id: str,
    promoted_by: str | None,
    reason: str | None,
    roi: dict[str, Any],
) -> dict[str, Any] | None:
    ensure_optimization_database()
    with db_session() as session:
        candidate = session.query(OptimizationCandidateRow).filter_by(id=candidate_id).one_or_none()
        if candidate is None:
            return None
        study = session.query(OptimizationStudyRow).filter_by(id=candidate.study_id).one_or_none()
        if study is None:
            return None
        expected_savings = _json_clone(candidate.expected_savings) or {}
        expected_savings["promotion"] = {
            "promoted_by": promoted_by,
            "reason": reason,
            "roi": _json_clone(roi),
            "promoted_at": utc_now().isoformat(),
        }
        candidate.expected_savings = expected_savings
        candidate.status = "promoted"
        study.status = "promoted"
        session.flush()
        return {"candidate": candidate.to_dict(), "study": study.to_dict(), "promotion": expected_savings["promotion"]}


def create_trial(
    *,
    study_id: str,
    candidate_id: str,
    baseline_execution_id: str,
    result_execution_id: str | None,
    quality_status: str,
    metrics_delta: dict[str, Any],
    notes: str | None,
    created_by: str | None,
) -> dict[str, Any]:
    ensure_optimization_database()
    row = OptimizationTrialRow(
        id=f"trial-{uuid.uuid4().hex[:16]}",
        study_id=study_id,
        candidate_id=candidate_id,
        baseline_execution_id=baseline_execution_id,
        result_execution_id=result_execution_id,
        status="recorded" if result_execution_id else "pending",
        quality_status=quality_status,
        metrics_delta=metrics_delta,
        notes=notes,
        created_by=created_by,
    )
    with db_session() as session:
        session.add(row)
        session.flush()
        return row.to_dict()


def update_trial_result(
    *,
    trial_id: str,
    result_execution_id: str | None,
    quality_status: str,
    metrics_delta: dict[str, Any],
    notes: str | None = None,
) -> dict[str, Any] | None:
    ensure_optimization_database()
    with db_session() as session:
        row = session.query(OptimizationTrialRow).filter_by(id=trial_id).one_or_none()
        if row is None:
            return None
        row.result_execution_id = result_execution_id
        row.quality_status = quality_status
        row.metrics_delta = _json_clone(metrics_delta) or {}
        if notes is not None:
            row.notes = notes
        row.status = "recorded" if result_execution_id else row.status
        session.flush()
        return row.to_dict()


def list_trials(study_id: str, candidate_id: str | None = None) -> list[dict[str, Any]]:
    ensure_optimization_database()
    with db_session() as session:
        query = session.query(OptimizationTrialRow).filter_by(study_id=study_id)
        if candidate_id:
            query = query.filter_by(candidate_id=candidate_id)
        rows = query.order_by(OptimizationTrialRow.created_at.asc()).all()
        return [row.to_dict() for row in rows]
