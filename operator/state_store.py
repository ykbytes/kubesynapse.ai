"""Database-backed mirrors for workflow and eval execution state."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import sysconfig
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import quote_plus


def _ensure_stdlib_operator_module() -> None:
    current = sys.modules.get("operator")
    if current is not None and hasattr(current, "attrgetter"):
        return

    stdlib_path = sysconfig.get_path("stdlib")
    if not stdlib_path:
        return

    operator_path = Path(stdlib_path) / "operator.py"
    if not operator_path.is_file():
        return

    spec = importlib.util.spec_from_file_location("operator", operator_path)
    if spec is None or spec.loader is None:
        return

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["operator"] = module


_ensure_stdlib_operator_module()

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, UniqueConstraint, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger("operator.state-store")

Base = declarative_base()
STATE_DB_ENABLED = os.getenv("STATE_DB_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_database_url() -> str:
    direct = os.getenv("DATABASE_URL", "").strip()
    if direct:
        return direct

    host = os.getenv("DATABASE_HOST", "").strip()
    if host:
        driver = os.getenv("DATABASE_DRIVER", "postgresql+psycopg").strip() or "postgresql+psycopg"
        port = int(os.getenv("DATABASE_PORT", "5432").strip() or "5432")
        username = os.getenv("DATABASE_USER", "ai_agent_sandbox").strip() or "ai_agent_sandbox"
        password = os.getenv("DATABASE_PASSWORD", "").strip()
        database_name = os.getenv("DATABASE_NAME", "ai_agent_sandbox").strip() or "ai_agent_sandbox"
        if password:
            return (
                f"{driver}://{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database_name)}"
            )
        return f"{driver}://{quote_plus(username)}@{host}:{port}/{quote_plus(database_name)}"

    sqlite_path = os.getenv("DATABASE_SQLITE_PATH", "/tmp/ai-agent-sandbox-operator.db").strip()
    if sqlite_path.startswith("sqlite:///"):
        return sqlite_path
    if sqlite_path == ":memory:":
        return "sqlite:///:memory:"
    if sqlite_path.startswith("/"):
        return f"sqlite:///{sqlite_path}"
    return f"sqlite:///{sqlite_path}"


DATABASE_URL = _build_database_url()
ENGINE = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (UniqueConstraint("namespace", "resource_name", "run_id", name="uq_workflow_runs_identity"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(128), nullable=False, index=True)
    resource_name = Column(String(128), nullable=False, index=True)
    generation = Column(Integer, nullable=False)
    run_id = Column(String(128), nullable=False, index=True)
    phase = Column(String(64), nullable=False, index=True)
    spec_json = Column(JSON, nullable=True)
    status_json = Column(JSON, nullable=True)
    summary_json = Column(JSON, nullable=True)
    step_results_json = Column(JSON, nullable=True)
    step_states_json = Column(JSON, nullable=True)
    artifact_path = Column(String(512), nullable=True)
    journal_path = Column(String(512), nullable=True)
    worker_job_name = Column(String(128), nullable=True)
    pending_approval_name = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (UniqueConstraint("namespace", "resource_name", "run_id", name="uq_eval_runs_identity"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(128), nullable=False, index=True)
    resource_name = Column(String(128), nullable=False, index=True)
    generation = Column(Integer, nullable=False)
    run_id = Column(String(128), nullable=False, index=True)
    phase = Column(String(64), nullable=False, index=True)
    passed = Column(Boolean, nullable=True)
    spec_json = Column(JSON, nullable=True)
    status_json = Column(JSON, nullable=True)
    summary_json = Column(JSON, nullable=True)
    artifact_path = Column(String(512), nullable=True)
    worker_job_name = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)


def _json_clone(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _completed_timestamp(phase: str, status: dict[str, Any]) -> datetime | None:
    summary = status.get("summary", {}) or {}
    for key in ("completedAt", "failedAt"):
        candidate = summary.get(key) or status.get(key)
        if isinstance(candidate, str) and candidate:
            normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    if phase in {"completed", "failed"}:
        return utc_now()
    return None


def init_database() -> None:
    if not STATE_DB_ENABLED:
        logger.info("State database mirroring is disabled.")
        return
    Base.metadata.create_all(bind=ENGINE)


@contextmanager
def db_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def safe_record_workflow_state(
    *,
    namespace: str,
    resource_name: str,
    generation: int,
    run_id: str,
    phase: str,
    spec: dict[str, Any],
    status: dict[str, Any],
) -> None:
    if not STATE_DB_ENABLED or not run_id:
        return
    try:
        with db_session() as session:
            record = (
                session.query(WorkflowRun)
                .filter(
                    WorkflowRun.namespace == namespace,
                    WorkflowRun.resource_name == resource_name,
                    WorkflowRun.run_id == run_id,
                )
                .one_or_none()
            )
            if record is None:
                record = WorkflowRun(namespace=namespace, resource_name=resource_name, run_id=run_id, generation=generation)
                session.add(record)

            artifact_ref = status.get("artifactRef", {}) or {}
            journal_ref = status.get("journalRef", {}) or {}
            worker_job = status.get("workerJob", {}) or {}
            pending_approval = status.get("pendingApproval", {}) or {}

            record.generation = generation
            record.phase = phase
            record.spec_json = _json_clone(spec)
            record.status_json = _json_clone(status)
            record.summary_json = _json_clone(status.get("summary", {}) or {})
            record.step_results_json = _json_clone(status.get("stepResults", {}) or {})
            record.step_states_json = _json_clone(status.get("stepStates", {}) or {})
            record.artifact_path = str(artifact_ref.get("path") or "").strip() or None
            record.journal_path = str(journal_ref.get("path") or artifact_ref.get("journalPath") or "").strip() or None
            record.worker_job_name = str(worker_job.get("name") or "").strip() or None
            record.pending_approval_name = str(pending_approval.get("name") or "").strip() or None
            record.completed_at = _completed_timestamp(phase, status)
            record.updated_at = utc_now()
    except Exception:
        logger.exception("Failed to mirror workflow state for %s/%s run %s.", namespace, resource_name, run_id)


def safe_record_eval_state(
    *,
    namespace: str,
    resource_name: str,
    generation: int,
    run_id: str,
    phase: str,
    passed: bool | None,
    spec: dict[str, Any],
    status: dict[str, Any],
) -> None:
    if not STATE_DB_ENABLED or not run_id:
        return
    try:
        with db_session() as session:
            record = (
                session.query(EvalRun)
                .filter(
                    EvalRun.namespace == namespace,
                    EvalRun.resource_name == resource_name,
                    EvalRun.run_id == run_id,
                )
                .one_or_none()
            )
            if record is None:
                record = EvalRun(namespace=namespace, resource_name=resource_name, run_id=run_id, generation=generation)
                session.add(record)

            artifact_ref = status.get("artifactRef", {}) or {}
            worker_job = status.get("workerJob", {}) or {}

            record.generation = generation
            record.phase = phase
            record.passed = passed
            record.spec_json = _json_clone(spec)
            record.status_json = _json_clone(status)
            record.summary_json = _json_clone(status.get("summary", {}) or {})
            record.artifact_path = str(artifact_ref.get("path") or "").strip() or None
            record.worker_job_name = str(worker_job.get("name") or "").strip() or None
            record.completed_at = _completed_timestamp(phase, status)
            record.updated_at = utc_now()
    except Exception:
        logger.exception("Failed to mirror eval state for %s/%s run %s.", namespace, resource_name, run_id)
