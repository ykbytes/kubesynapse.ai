"""Database-backed mirrors for workflow and eval execution state."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import sysconfig
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger("operator.state-store")

Base = declarative_base()
STATE_DB_ENABLED = os.getenv("STATE_DB_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def utc_now() -> datetime:
    return datetime.now(UTC)


def _build_database_url() -> str:
    direct = os.getenv("DATABASE_URL", "").strip()
    if direct:
        return direct

    host = os.getenv("DATABASE_HOST", "").strip()
    if host:
        _ALLOWED_DRIVERS = {
            "postgresql+psycopg", "postgresql+psycopg2", "postgresql+asyncpg",
            "postgresql", "postgres",
            "mysql+pymysql", "mysql+mysqlconnector",
            "sqlite",
        }
        driver = os.getenv("DATABASE_DRIVER", "postgresql+psycopg").strip() or "postgresql+psycopg"
        if driver not in _ALLOWED_DRIVERS:
            raise ValueError(
                f"Unsupported DATABASE_DRIVER '{driver}'. Allowed: {sorted(_ALLOWED_DRIVERS)}"
            )
        port = int(os.getenv("DATABASE_PORT", "5432").strip() or "5432")
        username = os.getenv("DATABASE_USER", "kubesynapse").strip() or "kubesynapse"
        password = os.getenv("DATABASE_PASSWORD", "").strip()
        database_name = os.getenv("DATABASE_NAME", "kubesynapse").strip() or "kubesynapse"
        if password:
            return (
                f"{driver}://{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database_name)}"
            )
        return f"{driver}://{quote_plus(username)}@{host}:{port}/{quote_plus(database_name)}"

    import tempfile
    sqlite_path = os.getenv("DATABASE_SQLITE_PATH", f"{tempfile.gettempdir()}/kubesynapse-operator.db").strip()
    if sqlite_path.startswith("sqlite:///"):
        return sqlite_path
    if sqlite_path == ":memory:":
        return "sqlite:///:memory:"
    if sqlite_path.startswith("/"):
        return f"sqlite:///{sqlite_path}"
    return f"sqlite:///{sqlite_path}"


DATABASE_URL = _build_database_url()

# §6.2 — Connection pooling configuration
_is_sqlite = DATABASE_URL.startswith("sqlite")
_pool_kwargs: dict[str, Any] = {}
if not _is_sqlite:
    _pool_kwargs = {
        "pool_size": int(os.getenv("DATABASE_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DATABASE_MAX_OVERFLOW", "20")),
        "pool_timeout": int(os.getenv("DATABASE_POOL_TIMEOUT", "30")),
        "pool_recycle": int(os.getenv("DATABASE_POOL_RECYCLE", "1800")),
    }

ENGINE = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    **_pool_kwargs,
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
    log_archive_text = Column(String, nullable=True)
    log_archive_source = Column(String(64), nullable=True)
    log_archive_truncated = Column(Boolean, nullable=False, default=False)
    log_archive_captured_at = Column(DateTime(timezone=True), nullable=True)
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


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (UniqueConstraint("session_id", name="uq_agent_sessions_identity"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=False, index=True)
    thread_id = Column(String(128), nullable=False, index=True)
    status = Column(String(64), nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    token_usage_json = Column(JSON, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


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
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
    if phase in {"completed", "failed"}:
        return utc_now()
    return None


def init_database() -> None:
    """Run Alembic migrations to create or upgrade the database schema."""
    if not STATE_DB_ENABLED:
        logger.info("State database mirroring is disabled.")
        return

    alembic_ini = Path(__file__).resolve().parent / "alembic.ini"
    if alembic_ini.is_file():
        try:
            from alembic import command as alembic_command
            from alembic.config import Config as AlembicConfig

            cfg = AlembicConfig(str(alembic_ini))
            cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
            alembic_command.upgrade(cfg, "head")
            logger.info("Database schema is up to date (via Alembic).")
            return
        except Exception:
            logger.warning("Alembic migration failed, falling back to create_all().", exc_info=True)

    Base.metadata.create_all(bind=ENGINE)
    logger.info("Database schema is up to date (via create_all).")


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


# ---------------------------------------------------------------------------
# §2.6 — Idempotency: runId uniqueness check
# ---------------------------------------------------------------------------

def check_workflow_run_conflict(namespace: str, resource_name: str, generation: int, run_id: str) -> str | None:
    """Return conflicting run_id if another run is active for this workflow+generation."""
    if not STATE_DB_ENABLED:
        return None
    try:
        with db_session() as session:
            record = (
                session.query(WorkflowRun)
                .filter(
                    WorkflowRun.namespace == namespace,
                    WorkflowRun.resource_name == resource_name,
                    WorkflowRun.generation == generation,
                    WorkflowRun.phase.in_(["queued", "running"]),
                    WorkflowRun.run_id != run_id,
                )
                .first()
            )
            if record is not None:
                return str(record.run_id)
    except Exception:
        logger.exception("Failed to check workflow run conflict for %s/%s gen %d.", namespace, resource_name, generation)
    return None


def check_eval_run_conflict(namespace: str, resource_name: str, generation: int, run_id: str) -> str | None:
    """Return conflicting run_id if another eval run is active for this eval+generation."""
    if not STATE_DB_ENABLED:
        return None
    try:
        with db_session() as session:
            record = (
                session.query(EvalRun)
                .filter(
                    EvalRun.namespace == namespace,
                    EvalRun.resource_name == resource_name,
                    EvalRun.generation == generation,
                    EvalRun.phase.in_(["queued", "running"]),
                    EvalRun.run_id != run_id,
                )
                .first()
            )
            if record is not None:
                return str(record.run_id)
    except Exception:
        logger.exception("Failed to check eval run conflict for %s/%s gen %d.", namespace, resource_name, generation)
    return None


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
            superseded_at = utc_now()
            stale_records = (
                session.query(WorkflowRun)
                .filter(
                    WorkflowRun.namespace == namespace,
                    WorkflowRun.resource_name == resource_name,
                    WorkflowRun.generation == generation,
                    WorkflowRun.run_id != run_id,
                    WorkflowRun.phase.in_(["queued", "running"]),
                )
                .all()
            )
            for stale_record in stale_records:
                stale_status = _json_clone(stale_record.status_json)
                if not isinstance(stale_status, dict):
                    stale_status = {}
                stale_summary = _json_clone(stale_record.summary_json)
                if not isinstance(stale_summary, dict):
                    stale_summary = {}
                stale_record.phase = "cancelled"
                stale_status["phase"] = "cancelled"
                stale_summary.setdefault("error", f"Superseded by run {run_id}")
                stale_summary["cancelledAt"] = superseded_at.isoformat()
                stale_record.status_json = stale_status
                stale_record.summary_json = stale_summary
                stale_record.completed_at = superseded_at
                stale_record.updated_at = superseded_at

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
            superseded_at = utc_now()
            stale_records = (
                session.query(EvalRun)
                .filter(
                    EvalRun.namespace == namespace,
                    EvalRun.resource_name == resource_name,
                    EvalRun.generation == generation,
                    EvalRun.run_id != run_id,
                    EvalRun.phase.in_(["queued", "running"]),
                )
                .all()
            )
            for stale_record in stale_records:
                stale_status = _json_clone(stale_record.status_json)
                if not isinstance(stale_status, dict):
                    stale_status = {}
                stale_summary = _json_clone(stale_record.summary_json)
                if not isinstance(stale_summary, dict):
                    stale_summary = {}
                stale_record.phase = "cancelled"
                stale_status["phase"] = "cancelled"
                stale_summary.setdefault("error", f"Superseded by run {run_id}")
                stale_summary["cancelledAt"] = superseded_at.isoformat()
                stale_record.status_json = stale_status
                stale_record.summary_json = stale_summary
                stale_record.completed_at = superseded_at
                stale_record.updated_at = superseded_at

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


def record_workflow_log_archive(
    *,
    namespace: str,
    resource_name: str,
    run_id: str,
    log_text: str,
    source: str,
    truncated: bool = False,
    captured_at: datetime | None = None,
) -> None:
    if not STATE_DB_ENABLED or not run_id:
        return

    archive_timestamp = captured_at or utc_now()
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
                logger.debug(
                    "Skipping workflow log archive for %s/%s run %s because the mirrored run row does not exist yet.",
                    namespace,
                    resource_name,
                    run_id,
                )
                return

            record.log_archive_text = log_text
            record.log_archive_source = source[:64] if source else None
            record.log_archive_truncated = bool(truncated)
            record.log_archive_captured_at = archive_timestamp
            record.updated_at = utc_now()
    except Exception:
        logger.exception("Failed to persist workflow log archive for %s/%s run %s.", namespace, resource_name, run_id)


def safe_record_agent_session(snapshot: dict[str, Any]) -> None:
    if not STATE_DB_ENABLED:
        return
    session_id = str(snapshot.get("session_id") or "").strip()
    thread_id = str(snapshot.get("thread_id") or "").strip()
    if not session_id or not thread_id:
        return
    try:
        with db_session() as session:
            record = session.query(AgentSession).filter(AgentSession.session_id == session_id).one_or_none()
            if record is None:
                record = AgentSession(session_id=session_id, thread_id=thread_id, status="active", payload_json={})
                session.add(record)

            token_usage = snapshot.get("token_usage") if isinstance(snapshot.get("token_usage"), dict) else None
            expires_at_raw = snapshot.get("expires_at")
            expires_at = None
            if isinstance(expires_at_raw, str) and expires_at_raw:
                normalized = expires_at_raw[:-1] + "+00:00" if expires_at_raw.endswith("Z") else expires_at_raw
                try:
                    expires_at = datetime.fromisoformat(normalized)
                except ValueError:
                    expires_at = None

            record.thread_id = thread_id
            record.status = str(snapshot.get("status") or "active").strip() or "active"
            record.payload_json = _json_clone(snapshot) or {}
            record.token_usage_json = _json_clone(token_usage)
            record.expires_at = expires_at
            record.updated_at = utc_now()
    except Exception:
        logger.exception("Failed to mirror agent session %s.", session_id)


def get_agent_session(session_id: str) -> dict[str, Any] | None:
    if not STATE_DB_ENABLED:
        return None
    try:
        with db_session() as session:
            record = session.query(AgentSession).filter(AgentSession.session_id == session_id).one_or_none()
            if record is None:
                return None
            return {
                "session_id": record.session_id,
                "thread_id": record.thread_id,
                "status": record.status,
                "payload": _json_clone(record.payload_json) or {},
                "token_usage": _json_clone(record.token_usage_json),
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            }
    except Exception:
        logger.exception("Failed to fetch agent session %s.", session_id)
        return None


# ── Chat Session Persistence ──


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (UniqueConstraint("namespace", "agent_name", "session_id", name="uq_chat_sessions_identity"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(128), nullable=False, index=True)
    agent_name = Column(String(128), nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    title = Column(String(256), nullable=False, default="Untitled")
    username = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=False, index=True)
    message_id = Column(String(128), nullable=False, unique=True)
    role = Column(String(32), nullable=False)
    content = Column(String, nullable=False, default="")
    status = Column(String(32), nullable=False, default="complete")
    tool_name = Column(String(128), nullable=True)
    tool_node = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


def list_chat_sessions(namespace: str, agent_name: str, username: str | None = None) -> list[dict[str, Any]]:
    """Return all chat sessions for a given agent, most recent first."""
    if not STATE_DB_ENABLED:
        return []
    try:
        with db_session() as session:
            q = session.query(ChatSession).filter(
                ChatSession.namespace == namespace,
                ChatSession.agent_name == agent_name,
            )
            if username:
                q = q.filter(ChatSession.username == username)
            rows = q.order_by(ChatSession.updated_at.desc()).all()
            return [
                {
                    "session_id": r.session_id,
                    "title": r.title,
                    "agent_name": r.agent_name,
                    "namespace": r.namespace,
                    "username": r.username,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
    except Exception:
        logger.exception("Failed to list chat sessions for %s/%s.", namespace, agent_name)
        return []


def create_chat_session(
    namespace: str, agent_name: str, session_id: str, title: str = "Untitled", username: str | None = None,
) -> dict[str, Any]:
    """Create a new chat session record."""
    with db_session() as session:
        record = ChatSession(
            namespace=namespace, agent_name=agent_name, session_id=session_id, title=title, username=username,
        )
        session.add(record)
        session.flush()
        return {
            "session_id": record.session_id,
            "title": record.title,
            "agent_name": record.agent_name,
            "namespace": record.namespace,
            "username": record.username,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }


def get_chat_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Return all messages for a session, ordered by creation time."""
    if not STATE_DB_ENABLED:
        return []
    try:
        with db_session() as session:
            rows = (
                session.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
                .all()
            )
            return [
                {
                    "message_id": r.message_id,
                    "role": r.role,
                    "content": r.content,
                    "status": r.status,
                    "tool_name": r.tool_name,
                    "tool_node": r.tool_node,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except Exception:
        logger.exception("Failed to get messages for session %s.", session_id)
        return []


def save_chat_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    """Replace all messages for a session (full snapshot save)."""
    if not STATE_DB_ENABLED:
        return
    try:
        with db_session() as session:
            session.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
            for msg in messages:
                record = ChatMessage(
                    session_id=session_id,
                    message_id=msg.get("message_id") or msg.get("id", ""),
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    status=msg.get("status", "complete"),
                    tool_name=msg.get("tool_name") or msg.get("toolName"),
                    tool_node=msg.get("tool_node") or msg.get("toolNode"),
                )
                session.add(record)
            # Update the session's updated_at timestamp
            chat_session = session.query(ChatSession).filter(ChatSession.session_id == session_id).one_or_none()
            if chat_session:
                chat_session.updated_at = utc_now()
    except Exception:
        logger.exception("Failed to save messages for session %s.", session_id)


def update_chat_session_title(session_id: str, title: str) -> dict[str, Any] | None:
    """Update a session's title."""
    if not STATE_DB_ENABLED:
        return None
    try:
        with db_session() as session:
            record = session.query(ChatSession).filter(ChatSession.session_id == session_id).one_or_none()
            if record is None:
                return None
            record.title = title
            record.updated_at = utc_now()
            return {
                "session_id": record.session_id,
                "title": record.title,
                "agent_name": record.agent_name,
                "namespace": record.namespace,
                "username": record.username,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            }
    except Exception:
        logger.exception("Failed to update title for session %s.", session_id)
        return None


def delete_chat_session(session_id: str) -> bool:
    """Delete a chat session and its messages."""
    if not STATE_DB_ENABLED:
        return False
    try:
        with db_session() as session:
            session.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
            deleted = session.query(ChatSession).filter(ChatSession.session_id == session_id).delete()
            return deleted > 0
    except Exception:
        logger.exception("Failed to delete session %s.", session_id)
        return False
