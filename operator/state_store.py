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
