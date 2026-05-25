"""Local auth and persistence helpers for the API gateway."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

from passlib.context import CryptContext
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

logger = logging.getLogger("api-gateway.auth-store")

_AUTH_STORAGE_ERRORS = (OperationalError, ProgrammingError)

Base = declarative_base()
PASSWORD_CONTEXT = CryptContext(schemes=["argon2", "pbkdf2_sha256"], deprecated="auto")

ROLE_PRIORITY = {"viewer": 1, "operator": 2, "admin": 3}
DEFAULT_ALLOWED_NAMESPACES = ["default"]
LOGIN_RATE_LIMIT_ATTEMPTS = max(int(os.getenv("AUTH_LOGIN_RATE_LIMIT_ATTEMPTS", "5")), 1)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(int(os.getenv("AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")), 1)
ACCOUNT_LOCKOUT_THRESHOLD = max(int(os.getenv("AUTH_ACCOUNT_LOCKOUT_THRESHOLD", "10")), 1)
ACCOUNT_LOCKOUT_MINUTES = max(int(os.getenv("AUTH_ACCOUNT_LOCKOUT_MINUTES", "15")), 1)
LOGIN_EXPONENTIAL_BACKOFF_BASE_SECONDS = max(int(os.getenv("AUTH_LOGIN_EXPONENTIAL_BACKOFF_BASE", "2")), 1)
LOGIN_EXPONENTIAL_BACKOFF_MAX_SECONDS = max(int(os.getenv("AUTH_LOGIN_EXPONENTIAL_BACKOFF_MAX", "3600")), 1)
PASSWORD_RESET_TOKEN_TTL_MINUTES = max(int(os.getenv("AUTH_PASSWORD_RESET_TTL_MINUTES", "60")), 5)

_LOGIN_RATE_LIMIT_LOCK = threading.Lock()
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_CONSECUTIVE_FAILURES: dict[str, int] = {}
_LOGIN_LAST_ATTEMPT: dict[str, float] = {}
_DEFAULT_INTELLIGENCE_NAMESPACE = "default"
_INTELLIGENCE_NAMESPACE_TABLES = (
    "intelligence_collectors",
    "intelligence_tasks",
    "intelligence_schedules",
    "intelligence_alerts",
    "alert_history",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_clone(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _build_database_url() -> str:
    direct = os.getenv("DATABASE_URL", "").strip()
    if direct:
        return direct

    host = os.getenv("DATABASE_HOST", "").strip()
    if host:
        driver = os.getenv("DATABASE_DRIVER", "postgresql+psycopg").strip() or "postgresql+psycopg"
        port = int(os.getenv("DATABASE_PORT", "5432").strip() or "5432")
        username = os.getenv("DATABASE_USER", "kubesynapse").strip() or "kubesynapse"
        password = os.getenv("DATABASE_PASSWORD", "").strip()
        database_name = os.getenv("DATABASE_NAME", "kubesynapse").strip() or "kubesynapse"
        if password:
            return f"{driver}://{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database_name)}"
        return f"{driver}://{quote_plus(username)}@{host}:{port}/{quote_plus(database_name)}"

    import tempfile
    sqlite_path = os.getenv("DATABASE_SQLITE_PATH", f"{tempfile.gettempdir()}/kubesynapse-gateway.db").strip()
    if sqlite_path.startswith("sqlite:///"):
        return sqlite_path
    if sqlite_path == ":memory:":
        return "sqlite:///:memory:"
    if sqlite_path.startswith("/"):
        return f"sqlite:///{sqlite_path}"
    return f"sqlite:///{sqlite_path}"


DATABASE_URL = _build_database_url()

# Connection pool tuning for production PostgreSQL
# SQLite uses NullPool by default (no connection pooling needed)
_engine_kwargs: dict[str, Any] = {
    "future": True,
    "pool_pre_ping": True,
}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL production pool settings
    _engine_kwargs["pool_size"] = max(int(os.getenv("DB_POOL_SIZE", "10")), 2)
    _engine_kwargs["max_overflow"] = max(int(os.getenv("DB_MAX_OVERFLOW", "20")), 0)
    _engine_kwargs["pool_recycle"] = max(int(os.getenv("DB_POOL_RECYCLE", "1800")), 300)
    _engine_kwargs["pool_timeout"] = max(float(os.getenv("DB_POOL_TIMEOUT", "30")), 5.0)
    _engine_kwargs["connect_args"] = {
        "options": f"-c statement_timeout={max(int(os.getenv('DB_STATEMENT_TIMEOUT_MS', '30000')), 5000)}ms",
    }

ENGINE = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("auth_provider", "external_id", name="uq_users_provider_external"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(128), nullable=False, unique=True, index=True)
    email = Column(String(320), nullable=True, unique=True)
    display_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(32), nullable=False, default="viewer")
    allowed_namespaces = Column(JSON, nullable=False, default=list)
    auth_provider = Column(String(64), nullable=False, default="local")
    external_id = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token_hash = Column(String(128), nullable=False)
    auth_provider = Column(String(64), nullable=False, default="local")
    ip_address = Column(String(128), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_used_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="sessions")


class McpConnectionRow(Base):
    __tablename__ = "mcp_connections"
    __table_args__ = (UniqueConstraint("namespace", "slug", name="uq_mcp_connections_namespace_slug"),)

    id = Column(String(64), primary_key=True)
    namespace = Column(String(128), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    slug = Column(String(128), nullable=False)
    server_id = Column(String(128), nullable=False, index=True)
    transport = Column(String(32), nullable=False)
    auth_type = Column(String(64), nullable=False, default="none")
    config_json = Column(JSON, nullable=False, default=dict)
    credential_metadata_json = Column(JSON, nullable=False, default=list)
    secret_name = Column(String(253), nullable=True)
    validation_status = Column(String(32), nullable=False, default="draft")
    validation_message = Column(String(1024), nullable=True)
    validation_detail_json = Column(JSON, nullable=True)
    last_validated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_sub = Column(String(255), nullable=True)
    actor_username = Column(String(128), nullable=True)
    actor_type = Column(String(32), nullable=True, index=True)  # user, operator, system, a2a
    auth_provider = Column(String(64), nullable=True)
    action = Column(String(128), nullable=False, index=True)
    resource_kind = Column(String(64), nullable=True, index=True)
    resource_name = Column(String(128), nullable=True)
    resource_namespace = Column(String(128), nullable=True)
    detail_json = Column(JSON, nullable=True)
    ip_address = Column(String(128), nullable=True)
    request_id = Column(String(128), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    agent_name = Column(String(128), nullable=False, index=True)
    namespace = Column(String(128), nullable=False, index=True)
    user_id = Column(String(255), nullable=True, index=True)
    model = Column(String(128), nullable=True, index=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=True)
    session_id = Column(String(128), nullable=True)
    request_id = Column(String(128), nullable=True)


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


class MemoryRecord(Base):
    __tablename__ = "memory_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(128), nullable=False, index=True)
    agent_name = Column(String(128), nullable=False, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    memory_type = Column(String(32), nullable=False, index=True)
    topic = Column(String(128), nullable=True)
    content_hash = Column(String(64), nullable=False, index=True, default="")
    content = Column(String, nullable=False, default="")
    detail_json = Column(JSON, nullable=True)
    username = Column(String(128), nullable=True)
    promoted = Column(Boolean, nullable=False, default=False, index=True)
    score = Column(Float, nullable=False, default=0.0, index=True)
    promote_reason = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)


MEMORY_RETENTION_PER_SESSION = max(int(os.getenv("MEMORY_RETENTION_PER_SESSION", "25")), 1)


def _memory_content_hash(memory_type: str, topic: str, content: str) -> str:
    payload = f"{memory_type}\n{topic}\n{content}".encode("utf-8", "ignore")
    return hashlib.sha256(payload).hexdigest()


def _prune_memory_records(
    session: Session,
    namespace: str,
    agent_name: str,
    session_id: str | None,
    *,
    retention_limit: int = MEMORY_RETENTION_PER_SESSION,
) -> None:
    rows = (
        session.query(MemoryRecord)
        .filter(
            MemoryRecord.namespace == namespace,
            MemoryRecord.agent_name == agent_name,
            MemoryRecord.session_id == session_id,
            MemoryRecord.promoted.is_(False),
        )
        .order_by(MemoryRecord.created_at.desc(), MemoryRecord.id.desc())
        .all()
    )
    for stale in rows[retention_limit:]:
        session.delete(stale)


def _memory_score(
    memory_type: str, topic: str, content: str, detail_json: dict[str, Any] | None
) -> tuple[float, str | None]:
    score = 0.0
    reason: str | None = None
    content_len = len(content)

    # Penalize boilerplate / generic greeting content
    _lower = content.lower().strip()
    _boilerplate = (
        "i have no persistent memor",
        "how can i help",
        "hi! how can i",
        "hello! how can i",
        "i'm opencode, an open source",
        "i don't have any memories",
    )
    if any(_lower.startswith(bp) for bp in _boilerplate):
        return round(score, 2), None  # 0.0 — never auto-promote

    if memory_type == "procedural":
        score += 2.5
    elif memory_type == "episodic":
        score += 1.0

    if topic in {"response-summary", "assistant-summary", "repo-convention", "workflow-outcome"}:
        score += 1.5
    if 24 <= content_len <= 220:
        score += 1.0
    if isinstance(detail_json, dict):
        if isinstance(detail_json.get("names"), list) and len(detail_json.get("names") or []) >= 2:
            score += 0.75
        if isinstance(detail_json.get("count"), int) and int(detail_json.get("count") or 0) >= 2:
            score += 0.75

    if score >= 4.0:
        reason = "high-signal-memory"
    return round(score, 2), reason


def _summarize_chat_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    total_messages = len(messages)
    tool_names = sorted(
        {
            str(item.get("tool_name") or item.get("toolName") or "").strip()
            for item in messages
            if isinstance(item, dict) and str(item.get("tool_name") or item.get("toolName") or "").strip()
        }
    )
    last_user_message = ""
    last_assistant_message = ""
    for item in reversed(messages):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if not last_assistant_message and role == "assistant" and content:
            last_assistant_message = content[:280]
        if not last_user_message and role == "user" and content:
            last_user_message = content[:280]
        if last_user_message and last_assistant_message:
            break
    return {
        "message_count": total_messages,
        "tool_names": tool_names,
        "last_user_message": last_user_message,
        "last_assistant_message": last_assistant_message,
        "memory_candidates": {
            "episodic": [{"type": "tool-usage", "names": tool_names}] if tool_names else [],
            "procedural": [{"type": "assistant-summary", "text": last_assistant_message}]
            if last_assistant_message
            else [],
        },
    }


def record_memory_items(
    namespace: str,
    agent_name: str,
    *,
    session_id: str | None = None,
    username: str | None = None,
    summary: dict[str, Any] | None = None,
    session: Session | None = None,
    auto_promote: bool = False,
) -> int:
    """Persist derived memory candidates for a chat session summary."""
    if not isinstance(summary, dict):
        return 0

    memory_candidates = summary.get("memory_candidates") if isinstance(summary.get("memory_candidates"), dict) else {}
    inserted = 0
    if session is not None:
        for memory_type in ("episodic", "procedural"):
            entries = memory_candidates.get(memory_type)
            if not isinstance(entries, list):
                continue

            # Prepare all items first to enable batched lookup (eliminates N+1)
            items_to_process: list[tuple[dict[str, Any], str, str, str, float, str | None]] = []
            for item in entries:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("text") or ", ".join(item.get("names") or []) or "").strip()
                if not content:
                    continue
                topic = str(item.get("type") or "note").strip() or "note"
                content_hash = _memory_content_hash(memory_type, topic, content)
                score, promote_reason = _memory_score(
                    memory_type, topic, content, item if isinstance(item, dict) else None
                )
                items_to_process.append((item, content, topic, content_hash, score, promote_reason))

            if not items_to_process:
                continue

            # Single batched query for all records (eliminates N+1)
            content_hashes = [t[3] for t in items_to_process]
            existing_records = (
                session.query(MemoryRecord)
                .filter(
                    MemoryRecord.namespace == namespace,
                    MemoryRecord.agent_name == agent_name,
                    MemoryRecord.session_id == session_id,
                    MemoryRecord.memory_type == memory_type,
                    MemoryRecord.content_hash.in_(content_hashes),
                )
                .all()
            )
            existing_by_hash: dict[str, MemoryRecord] = {
                r.content_hash: r for r in existing_records if r.content_hash
            }

            for item, content, topic, content_hash, score, promote_reason in items_to_process:
                existing = existing_by_hash.get(content_hash)
                if existing is not None:
                    existing.detail_json = item
                    existing.username = username or existing.username
                    existing.created_at = utc_now()
                    existing.score = score
                    if auto_promote and promote_reason:
                        existing.promoted = True
                        existing.promote_reason = promote_reason
                    inserted += 1
                    continue
                session.add(
                    MemoryRecord(
                        namespace=namespace,
                        agent_name=agent_name,
                        session_id=session_id,
                        memory_type=memory_type,
                        topic=topic,
                        content_hash=content_hash,
                        content=content,
                        detail_json=item,
                        username=username,
                        score=score,
                        promoted=bool(auto_promote and promote_reason),
                        promote_reason=promote_reason if auto_promote and promote_reason else None,
                    )
                )
                inserted += 1
        _prune_memory_records(session, namespace, agent_name, session_id)
        return inserted

    with db_session() as owned_session:
        return record_memory_items(
            namespace,
            agent_name,
            session_id=session_id,
            username=username,
            summary=summary,
            session=owned_session,
            auto_promote=auto_promote,
        )


def record_runtime_memory(
    namespace: str,
    agent_name: str,
    *,
    session_id: str | None = None,
    username: str | None = None,
    metadata: dict[str, Any] | None = None,
    auto_promote: bool = False,
) -> int:
    """Persist runtime-emitted memory metadata from invoke responses."""
    if not isinstance(metadata, dict):
        return 0
    memory = metadata.get("memory")
    if not isinstance(memory, dict):
        return 0
    return record_memory_items(
        namespace,
        agent_name,
        session_id=session_id,
        username=username,
        summary={"memory_candidates": memory},
        auto_promote=auto_promote,
    )


def record_workflow_outcome_memory(
    namespace: str,
    agent_name: str,
    workflow_name: str,
    *,
    run_id: str | None = None,
    phase: str,
    summary: dict[str, Any] | None = None,
    username: str | None = None,
) -> int:
    memory_candidates: dict[str, list[dict[str, Any]]] = {"episodic": [], "procedural": []}
    normalized_summary = summary if isinstance(summary, dict) else {}
    completed_steps = normalized_summary.get("completedSteps")
    failed_steps = normalized_summary.get("failedSteps")
    total_steps = normalized_summary.get("totalSteps")

    memory_candidates["episodic"].append(
        {
            "type": "workflow-outcome",
            "text": f"Workflow '{workflow_name}' finished with phase '{phase}'.",
            "workflow": workflow_name,
            "phase": phase,
            "count": int(completed_steps or 0),
        }
    )
    if phase == "completed":
        memory_candidates["procedural"].append(
            {
                "type": "workflow-success",
                "text": (
                    f"Workflow '{workflow_name}' completed successfully"
                    f" after {int(completed_steps or 0)}/{int(total_steps or completed_steps or 0)} steps."
                ),
                "workflow": workflow_name,
            }
        )
    elif phase == "failed":
        memory_candidates["procedural"].append(
            {
                "type": "workflow-failure",
                "text": f"Workflow '{workflow_name}' failed after {int(failed_steps or 0)} failed step(s).",
                "workflow": workflow_name,
            }
        )

    return record_memory_items(
        namespace,
        agent_name,
        session_id=run_id,
        username=username,
        summary={"memory_candidates": memory_candidates},
        auto_promote=(phase == "completed"),
    )


def apply_memory_feedback(
    namespace: str,
    agent_name: str,
    *,
    session_id: str | None = None,
    success: bool,
) -> int:
    delta = 1.0 if success else -1.0
    updated = 0
    with db_session() as session:
        q = session.query(MemoryRecord).filter(
            MemoryRecord.namespace == namespace,
            MemoryRecord.agent_name == agent_name,
        )
        if session_id:
            q = q.filter(MemoryRecord.session_id == session_id)
        rows = q.order_by(MemoryRecord.created_at.desc()).limit(12).all()
        for record in rows:
            record.score = max(float(record.score or 0.0) + delta, 0.0)
            updated += 1
    return updated


def list_memory_records(
    namespace: str,
    agent_name: str,
    *,
    username: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with db_session() as session:
        q = session.query(MemoryRecord).filter(
            MemoryRecord.namespace == namespace,
            MemoryRecord.agent_name == agent_name,
        )
        if username:
            q = q.filter((MemoryRecord.username == username) | (MemoryRecord.username.is_(None)))
        if session_id:
            q = q.filter(MemoryRecord.session_id == session_id)
        rows = q.order_by(MemoryRecord.created_at.desc()).limit(min(max(limit, 1), 200)).all()
        return [
            {
                "id": r.id,
                "namespace": r.namespace,
                "agent_name": r.agent_name,
                "session_id": r.session_id,
                "memory_type": r.memory_type,
                "topic": r.topic,
                "promoted": bool(r.promoted),
                "score": float(r.score or 0.0),
                "promote_reason": r.promote_reason,
                "content": r.content,
                "detail_json": r.detail_json,
                "username": r.username,
                "created_at": ensure_utc(r.created_at).isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def list_promoted_memory_records(
    namespace: str,
    agent_name: str,
    *,
    username: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return promoted memories, falling back to high-score unpromoted records."""
    try:
        with db_session() as session:
            # Primary: promoted records
            q = session.query(MemoryRecord).filter(
                MemoryRecord.namespace == namespace,
                MemoryRecord.agent_name == agent_name,
                MemoryRecord.promoted.is_(True),
            )
            if username:
                q = q.filter((MemoryRecord.username == username) | (MemoryRecord.username.is_(None)))
            rows = (
                q.order_by(MemoryRecord.created_at.desc(), MemoryRecord.id.desc()).limit(min(max(limit, 1), 20)).all()
            )

            # Fallback: if no promoted records, use high-score unpromoted ones
            if not rows:
                fallback_q = session.query(MemoryRecord).filter(
                    MemoryRecord.namespace == namespace,
                    MemoryRecord.agent_name == agent_name,
                    MemoryRecord.score >= 3.5,
                )
                if username:
                    fallback_q = fallback_q.filter(
                        (MemoryRecord.username == username) | (MemoryRecord.username.is_(None))
                    )
                rows = (
                    fallback_q.order_by(MemoryRecord.score.desc(), MemoryRecord.created_at.desc())
                    .limit(min(max(limit, 1), 20))
                    .all()
                )
                if rows:
                    logger.info(
                        "Memory fallback: no promoted records for %s/%s, using %d high-score records",
                        namespace, agent_name, len(rows),
                    )

            return [
                {
                    "id": r.id,
                    "namespace": r.namespace,
                    "agent_name": r.agent_name,
                    "session_id": r.session_id,
                    "memory_type": r.memory_type,
                    "topic": r.topic,
                    "promoted": bool(r.promoted),
                    "score": float(r.score or 0.0),
                    "promote_reason": r.promote_reason,
                    "content": r.content,
                    "detail_json": r.detail_json,
                    "username": r.username,
                    "created_at": ensure_utc(r.created_at).isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except Exception as exc:
        logger.warning("Unable to list promoted memory records for %s/%s: %s", namespace, agent_name, exc)
        return []


def set_memory_record_promoted(record_id: int, promoted: bool, *, username: str | None = None) -> dict[str, Any] | None:
    with db_session() as session:
        record = session.query(MemoryRecord).filter(MemoryRecord.id == record_id).one_or_none()
        if record is None:
            return None
        if username and record.username and record.username != username:
            return None
        record.promoted = bool(promoted)
        return {
            "id": record.id,
            "namespace": record.namespace,
            "agent_name": record.agent_name,
            "session_id": record.session_id,
            "memory_type": record.memory_type,
            "topic": record.topic,
            "promoted": bool(record.promoted),
            "score": float(record.score or 0.0),
            "promote_reason": record.promote_reason,
            "content": record.content,
            "detail_json": record.detail_json,
            "username": record.username,
            "created_at": ensure_utc(record.created_at).isoformat() if record.created_at else None,
        }


def update_memory_record(
    record_id: int,
    *,
    promoted: bool | None = None,
    topic: str | None = None,
    content: str | None = None,
    username: str | None = None,
) -> dict[str, Any] | None:
    with db_session() as session:
        record = session.query(MemoryRecord).filter(MemoryRecord.id == record_id).one_or_none()
        if record is None:
            return None
        if username and record.username and record.username != username:
            return None
        if promoted is not None:
            record.promoted = bool(promoted)
        if topic is not None:
            normalized_topic = str(topic).strip() or record.topic or "note"
            record.topic = normalized_topic
        if content is not None:
            normalized_content = str(content).strip()
            if not normalized_content:
                return None
            record.content = normalized_content
        record.content_hash = _memory_content_hash(
            record.memory_type, str(record.topic or "note"), str(record.content or "")
        )
        return {
            "id": record.id,
            "namespace": record.namespace,
            "agent_name": record.agent_name,
            "session_id": record.session_id,
            "memory_type": record.memory_type,
            "topic": record.topic,
            "promoted": bool(record.promoted),
            "score": float(record.score or 0.0),
            "promote_reason": record.promote_reason,
            "content": record.content,
            "detail_json": record.detail_json,
            "username": record.username,
            "created_at": ensure_utc(record.created_at).isoformat() if record.created_at else None,
        }


def delete_memory_record(record_id: int, *, username: str | None = None) -> bool:
    with db_session() as session:
        record = session.query(MemoryRecord).filter(MemoryRecord.id == record_id).one_or_none()
        if record is None:
            return False
        if username and record.username and record.username != username:
            return False
        session.delete(record)
        return True


class WorkflowRunHistory(Base):
    __tablename__ = "workflow_run_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_name = Column(String(256), nullable=False, index=True)
    namespace = Column(String(256), nullable=False, default="default")
    run_id = Column(String(128), nullable=True, index=True)
    phase = Column(String(64), nullable=False, default="pending")
    total_steps = Column(Integer, nullable=True)
    completed_steps = Column(Integer, nullable=True)
    failed_steps = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    triggered_by = Column(String(256), nullable=True)
    input_text = Column(String, nullable=True)
    summary_json = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


# ─── Observatory execution trace persistence ─────────────────────────────


class ExecutionTraceRow(Base):
    """Unified execution traces for the Observatory panel."""
    __tablename__ = "execution_traces"

    id = Column(String(128), primary_key=True)
    workflow_name = Column(String(256), nullable=False, index=True)
    namespace = Column(String(256), nullable=False, default="default", index=True)
    agent_name = Column(String(256), nullable=True, index=True)
    run_id = Column(String(128), nullable=True, index=True)
    status = Column(String(64), nullable=False, default="running", index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    input_preview = Column(String(2000), nullable=True)
    output_preview = Column(String(2000), nullable=True)
    step_count = Column(Integer, nullable=False, default=0)
    llm_call_count = Column(Integer, nullable=False, default=0)
    tool_call_count = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    total_cost_usd = Column(Float, nullable=True)
    steps_json = Column(JSON, nullable=True)
    llm_calls_json = Column(JSON, nullable=True)
    tool_calls_json = Column(JSON, nullable=True)
    events_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


# ─── Intelligence persistence models ─────────────────────────────────────


class IntelligenceCollectorRow(Base):
    __tablename__ = "intelligence_collectors"

    id = Column(String(128), primary_key=True)
    namespace = Column(String(256), nullable=False, default=_DEFAULT_INTELLIGENCE_NAMESPACE, index=True)
    name = Column(String(256), nullable=False)
    url = Column(String(1024), nullable=False, unique=True)
    token_hash = Column(String(128), nullable=False)
    encrypted_token = Column(String(4096), nullable=True)
    cluster = Column(String(256), nullable=False, default="unknown")
    tags = Column(JSON, nullable=False, default=list)
    registered_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    registered_by = Column(String(256), nullable=False, default="unknown")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "name": self.name,
            "url": self.url,
            "cluster": self.cluster,
            "tags": self.tags or [],
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
            "registered_by": self.registered_by,
        }


class IntelligenceTaskRow(Base):
    __tablename__ = "intelligence_tasks"

    task_id = Column(String(16), primary_key=True)
    namespace = Column(String(256), nullable=False, default=_DEFAULT_INTELLIGENCE_NAMESPACE, index=True)
    collector_id = Column(String(128), nullable=False, default="all")
    payload = Column(JSON, nullable=False, default=dict)
    results = Column(JSON, nullable=False, default=dict)
    submitted_by = Column(String(256), nullable=False, default="unknown")
    submitted_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    total = Column(Integer, nullable=False, default=0)
    completed = Column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "namespace": self.namespace,
            "collector_id": self.collector_id,
            "payload": self.payload or {},
            "results": self.results or {},
            "submitted_by": self.submitted_by,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "total": self.total,
            "completed": self.completed,
        }


class IntelligenceScheduleRow(Base):
    __tablename__ = "intelligence_schedules"

    id = Column(String(16), primary_key=True)
    namespace = Column(String(256), nullable=False, default=_DEFAULT_INTELLIGENCE_NAMESPACE, index=True)
    name = Column(String(256), nullable=False)
    cron = Column(String(128), nullable=False)
    collector_id = Column(String(128), nullable=False, default="all")
    builtin = Column(String(128), nullable=True)
    script = Column(String, nullable=True)
    script_type = Column(String(16), nullable=False, default="bash")
    timeout = Column(Integer, nullable=False, default=30)
    agent_name = Column(String(256), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(256), nullable=False, default="unknown")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_run = Column(DateTime(timezone=True), nullable=True)
    next_run = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "namespace": self.namespace, "name": self.name, "cron": self.cron,
            "collector_id": self.collector_id, "builtin": self.builtin,
            "script": self.script, "script_type": self.script_type,
            "timeout": self.timeout, "agent_name": self.agent_name,
            "enabled": self.enabled, "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
        }


class IntelligenceAlertRow(Base):
    __tablename__ = "intelligence_alerts"

    id = Column(String(16), primary_key=True)
    namespace = Column(String(256), nullable=False, default=_DEFAULT_INTELLIGENCE_NAMESPACE, index=True)
    name = Column(String(256), nullable=False)
    schedule_id = Column(String(16), nullable=True)
    condition_type = Column(String(32), nullable=False)
    condition_value = Column(String(1024), nullable=False, default="")
    action = Column(String(32), nullable=False, default="notify")
    agent_name = Column(String(256), nullable=True)
    prompt_template = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(256), nullable=False, default="unknown")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_triggered = Column(DateTime(timezone=True), nullable=True)
    trigger_count = Column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "namespace": self.namespace, "name": self.name, "schedule_id": self.schedule_id,
            "condition_type": self.condition_type, "condition_value": self.condition_value,
            "action": self.action, "agent_name": self.agent_name,
            "prompt_template": self.prompt_template, "enabled": self.enabled,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_triggered": self.last_triggered.isoformat() if self.last_triggered else None,
            "trigger_count": self.trigger_count,
        }


class AlertHistoryRow(Base):
    __tablename__ = "alert_history"

    id = Column(String(16), primary_key=True)
    namespace = Column(String(256), nullable=False, default=_DEFAULT_INTELLIGENCE_NAMESPACE, index=True)
    alert_id = Column(String(16), nullable=False, index=True)
    alert_name = Column(String(256), nullable=False)
    triggered_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    condition_matched = Column(String(512), nullable=False, default="")
    action_taken = Column(String(32), nullable=False, default="notify")
    agent_invoked = Column(String(256), nullable=True)
    invoke_status = Column(Integer, nullable=True)
    invoke_error = Column(String, nullable=True)
    task_id = Column(String(16), nullable=True)
    snippet = Column(String(1024), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "namespace": self.namespace, "alert_id": self.alert_id, "alert_name": self.alert_name,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "condition_matched": self.condition_matched, "action_taken": self.action_taken,
            "agent_invoked": self.agent_invoked, "invoke_status": self.invoke_status,
            "invoke_error": self.invoke_error, "task_id": self.task_id, "snippet": self.snippet,
        }


# ─── Webhook & Trigger persistence models ──────────────────────────────────


class WebhookReceiverRow(Base):
    __tablename__ = "webhook_receivers"
    __table_args__ = (UniqueConstraint("namespace", "name", name="uq_webhook_receivers_namespace_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(128), nullable=False, index=True)
    name = Column(String(128), nullable=False, index=True)
    secret_ref = Column(String(253), nullable=False)
    ip_allowlist = Column(JSON, nullable=False, default=list)
    rate_limit = Column(Integer, nullable=False, default=60)
    max_payload_bytes = Column(Integer, nullable=False, default=1048576)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "name": self.name,
            "secret_ref": self.secret_ref,
            "ip_allowlist": self.ip_allowlist or [],
            "rate_limit": self.rate_limit,
            "max_payload_bytes": self.max_payload_bytes,
            "enabled": self.enabled,
            "created_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
            "updated_at": ensure_utc(self.updated_at).isoformat() if self.updated_at else None,
        }


class WebhookInvocationRow(Base):
    __tablename__ = "webhook_invocations"
    __table_args__ = (
        Index("ix_webhook_invocations_ns_name_created", "namespace", "webhook_name", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(128), nullable=False, index=True)
    webhook_name = Column(String(128), nullable=False, index=True)
    event_id = Column(String(128), nullable=False, unique=True, index=True)
    source_ip = Column(String(128), nullable=True)
    signature_valid = Column(Boolean, nullable=False, default=False)
    payload_size = Column(Integer, nullable=False, default=0)
    payload_snippet = Column(String(1024), nullable=True)
    headers_json = Column(JSON, nullable=True)
    matched_triggers = Column(JSON, nullable=False, default=list)
    error_message = Column(String(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    def to_dict(self) -> dict[str, Any]:
        matched = self.matched_triggers or []
        return {
            "id": self.id,
            "namespace": self.namespace,
            "webhook_name": self.webhook_name,
            "event_id": self.event_id,
            "invocation_id": self.event_id,
            "source_ip": self.source_ip,
            "signature_valid": self.signature_valid,
            "signature_verified": self.signature_valid,
            "payload_size": self.payload_size,
            "payload_snippet": self.payload_snippet,
            "headers_json": self.headers_json,
            "matched_triggers": len(matched),
            "matched_trigger_names": matched,
            "error_message": self.error_message,
            "created_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
            "received_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
            "status": "received" if not self.error_message else "failed",
        }


class WorkflowTriggerRow(Base):
    __tablename__ = "workflow_triggers"
    __table_args__ = (UniqueConstraint("namespace", "name", name="uq_workflow_triggers_namespace_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(128), nullable=False, index=True)
    name = Column(String(128), nullable=False, index=True)
    source_kind = Column(String(64), nullable=False, default="WebhookReceiver")
    source_name = Column(String(128), nullable=False)
    event_filter_json = Column(JSON, nullable=True)
    target_workflow_name = Column(String(128), nullable=False)
    target_workflow_namespace = Column(String(128), nullable=False, default="default")
    payload_mapping_json = Column(JSON, nullable=False, default=dict)
    retry_max_retries = Column(Integer, nullable=False, default=3)
    retry_backoff_seconds = Column(Integer, nullable=False, default=60)
    notifications_on_success = Column(JSON, nullable=False, default=list)
    notifications_on_failure = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "name": self.name,
            "source_kind": self.source_kind,
            "source_name": self.source_name,
            "source_ref": self.source_name,
            "event_filter": self.event_filter_json,
            "target_workflow_name": self.target_workflow_name,
            "target_workflow_namespace": self.target_workflow_namespace,
            "workflow_ref": {
                "name": self.target_workflow_name,
                "namespace": self.target_workflow_namespace,
            },
            "payload_mapping": self.payload_mapping_json or {},
            "retry_max_retries": self.retry_max_retries,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "max_retries": self.retry_max_retries,
            "backoff_seconds": self.retry_backoff_seconds,
            "notifications_on_success": self.notifications_on_success or [],
            "notifications_on_failure": self.notifications_on_failure or [],
            "enabled": self.enabled,
            "created_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
            "updated_at": ensure_utc(self.updated_at).isoformat() if self.updated_at else None,
        }


class TriggerExecutionRow(Base):
    __tablename__ = "trigger_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger_namespace = Column(String(128), nullable=False, index=True)
    trigger_name = Column(String(128), nullable=False, index=True)
    webhook_name = Column(String(128), nullable=False, default="")
    event_id = Column(String(128), nullable=False, index=True)
    workflow_name = Column(String(128), nullable=False)
    workflow_namespace = Column(String(128), nullable=False)
    payload_json = Column(JSON, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    error_message = Column(String(1024), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "namespace": self.trigger_namespace,
            "trigger_namespace": self.trigger_namespace,
            "trigger_name": self.trigger_name,
            "event_id": self.event_id,
            "webhook_name": self.webhook_name,
            "workflow_name": self.workflow_name,
            "workflow_namespace": self.workflow_namespace,
            "payload_json": self.payload_json,
            "status": self.status,
            "error_message": self.error_message,
            "attempt_count": self.attempt_count,
            "created_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
            "executed_at": ensure_utc(self.created_at).isoformat() if self.created_at else None,
            "updated_at": ensure_utc(self.updated_at).isoformat() if self.updated_at else None,
            "completed_at": ensure_utc(self.completed_at).isoformat() if self.completed_at else None,
            "workflow_run_id": None,
        }


# Schema version tracking for migration integrity checks
_SCHEMA_VERSION = 1  # Increment when schema changes require migration


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


def _verify_schema_version() -> None:
    """Verify the database schema version matches the expected version.

    If the schema_version table does not exist or the version is outdated,
    this function logs a warning. In production, this should be enforced
    by proper Alembic migrations.
    """
    try:
        with ENGINE.begin() as connection:
            inspector = inspect(connection)
            if "schema_version" not in inspector.get_table_names():
                # First boot — seed the version
                connection.execute(
                    text("INSERT INTO schema_version (id, version, updated_at) VALUES (1, :version, NOW())")
                    .bindparams(version=_SCHEMA_VERSION)
                )
                logger.info("Initialized schema_version at %d", _SCHEMA_VERSION)
                return

            result = connection.execute(text("SELECT version FROM schema_version WHERE id = 1"))
            row = result.fetchone()
            if row is None:
                connection.execute(
                    text("INSERT INTO schema_version (id, version, updated_at) VALUES (1, :version, NOW())")
                    .bindparams(version=_SCHEMA_VERSION)
                )
                logger.info("Initialized schema_version at %d", _SCHEMA_VERSION)
                return

            current_version = row[0]
            if current_version < _SCHEMA_VERSION:
                logger.warning(
                    "Schema version mismatch: database=%d, expected=%d. "
                    "Run migrations before starting the application.",
                    current_version,
                    _SCHEMA_VERSION,
                )
            elif current_version > _SCHEMA_VERSION:
                logger.warning(
                    "Schema version ahead of application: database=%d, expected=%d. "
                    "Application may be outdated.",
                    current_version,
                    _SCHEMA_VERSION,
                )
    except Exception as exc:
        logger.warning("Schema version check failed (non-fatal): %s", exc)


def _ensure_intelligence_namespace_columns() -> None:
    with ENGINE.begin() as connection:
        inspector = inspect(connection)
        for table_name in _INTELLIGENCE_NAMESPACE_TABLES:
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "namespace" not in columns:
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN namespace VARCHAR(256) NOT NULL DEFAULT '{_DEFAULT_INTELLIGENCE_NAMESPACE}'"
                    )
                )
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_namespace ON {table_name} (namespace)"))


def _ensure_intelligence_collector_secret_columns() -> None:
    with ENGINE.begin() as connection:
        inspector = inspect(connection)
        if "intelligence_collectors" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("intelligence_collectors")}
        if "encrypted_token" not in columns:
            connection.execute(text("ALTER TABLE intelligence_collectors ADD COLUMN encrypted_token VARCHAR(4096)"))


def _compile_type_sql(column_type: Any, dialect: Any) -> str:
    return str(column_type.compile(dialect=dialect))


def _ensure_workflow_run_archive_columns() -> None:
    with ENGINE.begin() as connection:
        inspector = inspect(connection)
        if "workflow_runs" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
        archive_source_type = _compile_type_sql(String(64), connection.dialect)
        archive_truncated_type = _compile_type_sql(Boolean(), connection.dialect)
        archive_captured_at_type = _compile_type_sql(DateTime(timezone=True), connection.dialect)
        if "log_archive_text" not in columns:
            connection.execute(text("ALTER TABLE workflow_runs ADD COLUMN log_archive_text TEXT"))
        if "log_archive_source" not in columns:
            connection.execute(text(f"ALTER TABLE workflow_runs ADD COLUMN log_archive_source {archive_source_type}"))
        if "log_archive_truncated" not in columns:
            connection.execute(
                text(
                    f"ALTER TABLE workflow_runs ADD COLUMN log_archive_truncated {archive_truncated_type} NOT NULL DEFAULT FALSE"
                )
            )
        if "log_archive_captured_at" not in columns:
            connection.execute(
                text(f"ALTER TABLE workflow_runs ADD COLUMN log_archive_captured_at {archive_captured_at_type}")
            )


def _ensure_password_reset_token_table() -> None:
    with ENGINE.begin() as connection:
        inspector = inspect(connection)
        if "password_reset_tokens" not in inspector.get_table_names():
            Base.metadata.create_all(bind=ENGINE, tables=[PasswordResetToken.__table__])
            logger.info("Created password_reset_tokens table")


def _ensure_webhook_trigger_tables() -> None:
    with ENGINE.begin() as connection:
        inspector = inspect(connection)
        tables = inspector.get_table_names()
        new_tables = [
            WebhookReceiverRow.__table__,
            WebhookInvocationRow.__table__,
            WorkflowTriggerRow.__table__,
            TriggerExecutionRow.__table__,
        ]
        for table in new_tables:
            if table.name not in tables:
                Base.metadata.create_all(bind=ENGINE, tables=[table])
                logger.info("Created table %s", table.name)
        if "trigger_executions" in tables:
            columns = {column["name"] for column in inspector.get_columns("trigger_executions")}
            if "webhook_name" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE trigger_executions ADD COLUMN webhook_name VARCHAR(128) NOT NULL DEFAULT ''"
                )
                logger.info("Added webhook_name column to trigger_executions")


def init_database() -> None:
    # Preferred: Alembic migrations (production-ready, versioned schema changes)
    try:
        from migration_runner import run_migrations
        run_migrations()
    except ImportError:
        # Fallback: create_all() for environments without Alembic installed
        Base.metadata.create_all(bind=ENGINE)
    _ensure_intelligence_collector_secret_columns()
    _ensure_intelligence_namespace_columns()
    _ensure_workflow_run_archive_columns()
    _ensure_password_reset_token_table()
    _ensure_webhook_trigger_tables()
    _verify_schema_version()


def auth_storage_ready(*, require_sessions: bool = False) -> bool:
    """Return True when the auth tables needed for browser sessions exist."""
    required_tables = {User.__tablename__}
    if require_sessions:
        required_tables.add(UserSession.__tablename__)

    try:
        with ENGINE.connect() as connection:
            existing_tables = set(inspect(connection).get_table_names())
    except _AUTH_STORAGE_ERRORS:
        logger.exception("Unable to inspect auth storage state.")
        return False

    missing_tables = sorted(required_tables.difference(existing_tables))
    if missing_tables:
        logger.debug("Auth storage missing required tables: %s", ", ".join(missing_tables))
        return False
    return True


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


def normalize_namespaces(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = []
    return sorted(set(items))


def normalize_allowed_namespaces_for_role(
    role: str,
    allowed_namespaces: Any,
    *,
    default_namespaces: list[str] | None = None,
) -> list[str]:
    normalized_role = role if role in ROLE_PRIORITY else "viewer"
    if normalized_role == "admin":
        return ["*"]

    normalized = [namespace for namespace in normalize_namespaces(allowed_namespaces) if namespace != "*"]
    if normalized:
        return normalized
    if default_namespaces is None:
        return []
    return [namespace for namespace in normalize_namespaces(default_namespaces) if namespace != "*"]


def hash_password(password: str) -> str:
    return PASSWORD_CONTEXT.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return PASSWORD_CONTEXT.verify(password, password_hash)


def hash_refresh_token(token: str) -> str:
    # HMAC-SHA256 with JWT secret as key — prevents length-extension and rainbow-table attacks
    import os as _os
    _secret = _os.environ.get("JWT_SECRET", "kubesynapse-fallback-hmac-key").encode("utf-8")
    return hashlib.sha256(_secret + token.encode("utf-8")).hexdigest()


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def validate_email(email: str | None) -> str | None:
    """Return the trimmed email if valid, or raise ValueError."""
    if email is None:
        return None
    email = email.strip()
    if not email:
        return None
    if not _EMAIL_RE.match(email) or len(email) > 320:
        raise ValueError("Email address is not valid.")
    return email


def password_meets_policy(password: str) -> bool:
    if len(password) < 8:
        return False
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_upper and has_lower and has_digit


def serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "allowed_namespaces": normalize_allowed_namespaces_for_role(user.role, user.allowed_namespaces),
        "auth_provider": user.auth_provider,
        "is_active": bool(user.is_active),
        "created_at": ensure_utc(user.created_at).isoformat() if user.created_at else None,
        "updated_at": ensure_utc(user.updated_at).isoformat() if user.updated_at else None,
        "last_login_at": ensure_utc(user.last_login_at).isoformat() if user.last_login_at else None,
    }


_MCP_CONNECTION_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_mcp_connection_name(name: str) -> str:
    lowered = str(name or "").strip().lower()
    slug = _MCP_CONNECTION_SLUG_RE.sub("-", lowered).strip("-")
    return slug[:128] if slug else "mcp-connection"


def serialize_mcp_connection(row: McpConnectionRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "namespace": row.namespace,
        "name": row.name,
        "slug": row.slug,
        "server_id": row.server_id,
        "transport": row.transport,
        "auth_type": row.auth_type,
        "config": _json_clone(row.config_json) or {},
        "credential_metadata": _json_clone(row.credential_metadata_json) or [],
        "secret_name": row.secret_name,
        "validation": {
            "status": row.validation_status,
            "message": row.validation_message,
            "detail": _json_clone(row.validation_detail_json),
            "last_validated_at": ensure_utc(row.last_validated_at).isoformat() if row.last_validated_at else None,
        },
        "created_at": ensure_utc(row.created_at).isoformat() if row.created_at else None,
        "updated_at": ensure_utc(row.updated_at).isoformat() if row.updated_at else None,
    }


def list_mcp_connections(namespace: str) -> list[dict[str, Any]]:
    normalized_namespace = str(namespace or "default").strip() or "default"
    with db_session() as session:
        rows = (
            session.query(McpConnectionRow)
            .filter(McpConnectionRow.namespace == normalized_namespace)
            .order_by(McpConnectionRow.name.asc(), McpConnectionRow.created_at.asc())
            .all()
        )
        return [serialize_mcp_connection(row) for row in rows]


def get_mcp_connection(namespace: str, connection_id: str) -> dict[str, Any] | None:
    normalized_namespace = str(namespace or "default").strip() or "default"
    normalized_id = str(connection_id or "").strip()
    if not normalized_id:
        return None
    with db_session() as session:
        row = (
            session.query(McpConnectionRow)
            .filter(McpConnectionRow.namespace == normalized_namespace, McpConnectionRow.id == normalized_id)
            .one_or_none()
        )
        return serialize_mcp_connection(row) if row is not None else None


def get_mcp_connection_rows_by_ids(namespace: str, connection_ids: list[str]) -> list[McpConnectionRow]:
    normalized_namespace = str(namespace or "default").strip() or "default"
    normalized_ids = [str(item).strip() for item in connection_ids if str(item).strip()]
    if not normalized_ids:
        return []
    with db_session() as session:
        rows = (
            session.query(McpConnectionRow)
            .filter(McpConnectionRow.namespace == normalized_namespace, McpConnectionRow.id.in_(normalized_ids))
            .all()
        )
        by_id = {row.id: row for row in rows}
        return [by_id[item_id] for item_id in normalized_ids if item_id in by_id]


def create_mcp_connection(
    *,
    namespace: str,
    name: str,
    server_id: str,
    transport: str,
    auth_type: str,
    config: dict[str, Any] | None = None,
    credential_metadata: list[dict[str, Any]] | None = None,
    secret_name: str | None = None,
    validation_status: str = "draft",
    validation_message: str | None = None,
    validation_detail: dict[str, Any] | None = None,
    last_validated_at: datetime | None = None,
) -> dict[str, Any]:
    normalized_namespace = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    normalized_server_id = str(server_id or "").strip()
    normalized_transport = str(transport or "").strip().lower() or "remote"
    normalized_auth_type = str(auth_type or "").strip().lower() or "none"
    if not normalized_name:
        raise ValueError("Connection name is required.")
    if not normalized_server_id:
        raise ValueError("Connection server_id is required.")

    row = McpConnectionRow(
        id=uuid.uuid4().hex,
        namespace=normalized_namespace,
        name=normalized_name,
        slug=slugify_mcp_connection_name(normalized_name),
        server_id=normalized_server_id,
        transport=normalized_transport,
        auth_type=normalized_auth_type,
        config_json=_json_clone(config) or {},
        credential_metadata_json=_json_clone(credential_metadata) or [],
        secret_name=str(secret_name or "").strip() or None,
        validation_status=str(validation_status or "draft").strip() or "draft",
        validation_message=str(validation_message or "").strip() or None,
        validation_detail_json=_json_clone(validation_detail),
        last_validated_at=ensure_utc(last_validated_at),
    )
    with db_session() as session:
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(f"An MCP connection named '{normalized_name}' already exists in namespace '{normalized_namespace}'.") from exc
        session.refresh(row)
        return serialize_mcp_connection(row)


def update_mcp_connection(
    namespace: str,
    connection_id: str,
    *,
    name: str | None = None,
    transport: str | None = None,
    auth_type: str | None = None,
    config: dict[str, Any] | None = None,
    credential_metadata: list[dict[str, Any]] | None = None,
    secret_name: str | None = None,
    validation_status: str | None = None,
    validation_message: str | None = None,
    validation_detail: dict[str, Any] | None = None,
    last_validated_at: datetime | None = None,
) -> dict[str, Any]:
    normalized_namespace = str(namespace or "default").strip() or "default"
    normalized_id = str(connection_id or "").strip()
    if not normalized_id:
        raise ValueError("Connection id is required.")

    with db_session() as session:
        row = (
            session.query(McpConnectionRow)
            .filter(McpConnectionRow.namespace == normalized_namespace, McpConnectionRow.id == normalized_id)
            .one_or_none()
        )
        if row is None:
            raise ValueError(f"MCP connection '{normalized_id}' was not found.")

        if name is not None:
            normalized_name = str(name).strip()
            if not normalized_name:
                raise ValueError("Connection name is required.")
            row.name = normalized_name
            row.slug = slugify_mcp_connection_name(normalized_name)
        if transport is not None:
            row.transport = str(transport or row.transport).strip().lower() or row.transport
        if auth_type is not None:
            row.auth_type = str(auth_type or row.auth_type).strip().lower() or row.auth_type
        if config is not None:
            row.config_json = _json_clone(config) or {}
        if credential_metadata is not None:
            row.credential_metadata_json = _json_clone(credential_metadata) or []
        if secret_name is not None:
            row.secret_name = str(secret_name).strip() or None
        if validation_status is not None:
            row.validation_status = str(validation_status or "draft").strip() or "draft"
        if validation_message is not None:
            row.validation_message = str(validation_message).strip() or None
        if validation_detail is not None:
            row.validation_detail_json = _json_clone(validation_detail)
        if last_validated_at is not None:
            row.last_validated_at = ensure_utc(last_validated_at)
        row.updated_at = utc_now()

        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(
                f"An MCP connection named '{row.name}' already exists in namespace '{normalized_namespace}'."
            ) from exc
        session.refresh(row)
        return serialize_mcp_connection(row)


def delete_mcp_connection(namespace: str, connection_id: str) -> bool:
    normalized_namespace = str(namespace or "default").strip() or "default"
    normalized_id = str(connection_id or "").strip()
    if not normalized_id:
        return False
    with db_session() as session:
        deleted = (
            session.query(McpConnectionRow)
            .filter(McpConnectionRow.namespace == normalized_namespace, McpConnectionRow.id == normalized_id)
            .delete()
        )
        return bool(deleted)


def count_users() -> int:
    with db_session() as session:
        return int(session.query(User).count())


def get_user_by_id(user_id: int) -> User | None:
    with db_session() as session:
        return session.get(User, user_id)


def get_user_by_username(username: str) -> User | None:
    normalized_username = username.strip().lower()
    if not normalized_username:
        return None
    with db_session() as session:
        return session.query(User).filter(User.username == normalized_username).one_or_none()


def list_users() -> list[dict[str, Any]]:
    with db_session() as session:
        items = session.query(User).order_by(User.username.asc()).all()
        return [serialize_user(item) for item in items]


def ensure_bootstrap_admin() -> None:
    """Create the bootstrap admin account, bypassing password policy."""
    username = os.getenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "").strip().lower()
    password = os.getenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    if not username or not password:
        return

    existing = get_user_by_username(username)
    if existing is not None:
        # Ensure the bootstrap user always has admin role
        if str(existing.role) != "admin":
            with db_session() as session:
                user = session.get(User, existing.id)
                if user is not None:
                    user.role = "admin"  # type: ignore[assignment]
                    logger.info("Promoted bootstrap account '%s' to admin role.", username)
        return

    email = os.getenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "").strip() or None
    display_name = os.getenv("AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME", "Platform Admin").strip() or "Platform Admin"
    allowed_namespaces = normalize_namespaces(os.getenv("AUTH_BOOTSTRAP_ADMIN_NAMESPACES", "*")) or ["*"]

    # Bypass password policy for bootstrap — the admin password is set by the
    # deployer via env/secret and may not satisfy interactive-user complexity
    # rules (e.g. short-lived development bootstrap passwords).
    validated_email = validate_email(email)
    try:
        with db_session() as session:
            user = User(
                username=username,
                email=validated_email,
                display_name=display_name or username,
                password_hash=hash_password(password),
                role="admin",
                allowed_namespaces=normalize_allowed_namespaces_for_role(
                    "admin",
                    allowed_namespaces,
                    default_namespaces=DEFAULT_ALLOWED_NAMESPACES,
                ),
                auth_provider="local",
                is_active=True,
            )
            session.add(user)
            session.flush()
        logger.info("Bootstrapped local admin account '%s'.", username)
    except (IntegrityError, ValueError) as exc:
        logger.info("Bootstrap admin account '%s' already exists (%s).", username, exc)


def create_local_user(
    *,
    username: str,
    password: str,
    email: str | None,
    display_name: str | None,
    role: str = "viewer",
    allowed_namespaces: list[str] | None = None,
    auth_provider: str = "local",
    external_id: str | None = None,
) -> dict[str, Any]:
    normalized_username = username.strip().lower()
    if not normalized_username:
        raise ValueError("Username is required.")
    if not password_meets_policy(password):
        raise ValueError(
            "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, and a digit."
        )
    if role not in ROLE_PRIORITY:
        raise ValueError(f"Unsupported role '{role}'.")
    validated_email = validate_email(email)
    normalized_allowed_namespaces = normalize_allowed_namespaces_for_role(
        role,
        allowed_namespaces,
        default_namespaces=DEFAULT_ALLOWED_NAMESPACES,
    )

    with db_session() as session:
        if session.query(User).filter(User.username == normalized_username).one_or_none() is not None:
            raise ValueError(f"User '{normalized_username}' already exists.")
        if validated_email and session.query(User).filter(User.email == validated_email).one_or_none() is not None:
            raise ValueError(f"Email '{validated_email}' is already in use.")

        user = User(
            username=normalized_username,
            email=validated_email,
            display_name=display_name or normalized_username,
            password_hash=hash_password(password),
            role=role,
            allowed_namespaces=normalized_allowed_namespaces,
            auth_provider=auth_provider,
            external_id=external_id,
            is_active=True,
        )
        session.add(user)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            detail = str(exc).lower()
            if "username" in detail:
                raise ValueError(f"User '{normalized_username}' already exists.") from exc
            if "email" in detail:
                raise ValueError(f"Email '{validated_email}' is already in use.") from exc
            raise ValueError("A user with these details already exists.") from exc
        session.refresh(user)
        return serialize_user(user)


def upsert_external_user(
    *,
    username: str,
    email: str | None,
    display_name: str | None,
    auth_provider: str,
    external_id: str,
    role: str,
    allowed_namespaces: list[str] | None = None,
) -> dict[str, Any]:
    normalized_username = username.strip().lower()
    normalized_namespaces = normalize_allowed_namespaces_for_role(
        role,
        allowed_namespaces,
        default_namespaces=DEFAULT_ALLOWED_NAMESPACES,
    )
    with db_session() as session:
        user = (
            session.query(User)
            .filter(User.auth_provider == auth_provider, User.external_id == external_id)
            .one_or_none()
        )
        if user is None:
            user = session.query(User).filter(User.username == normalized_username).one_or_none()

        if user is None:
            user = User(
                username=normalized_username,
                email=email,
                display_name=display_name or normalized_username,
                password_hash=None,
                role=role if role in ROLE_PRIORITY else "viewer",
                allowed_namespaces=normalized_namespaces,
                auth_provider=auth_provider,
                external_id=external_id,
                is_active=True,
            )
            session.add(user)
        else:
            user.email = email or user.email
            user.display_name = display_name or user.display_name or normalized_username
            user.auth_provider = auth_provider
            user.external_id = external_id
            if role in ROLE_PRIORITY:
                user.role = role
            if normalized_namespaces:
                user.allowed_namespaces = normalized_namespaces
        session.flush()
        session.refresh(user)
        return serialize_user(user)


def update_user_fields(
    user_id: int,
    *,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    allowed_namespaces: list[str] | None = None,
) -> dict[str, Any]:
    with db_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User id '{user_id}' was not found.")
        next_role = str(user.role or "viewer")
        if role is not None:
            if role not in ROLE_PRIORITY:
                raise ValueError(f"Unsupported role '{role}'.")
            user.role = role
            next_role = role
        if display_name is not None:
            user.display_name = display_name.strip() or user.display_name
        if is_active is not None:
            user.is_active = bool(is_active)
        if allowed_namespaces is not None:
            user.allowed_namespaces = normalize_allowed_namespaces_for_role(
                next_role,
                allowed_namespaces,
                default_namespaces=DEFAULT_ALLOWED_NAMESPACES,
            )
        elif role is not None:
            user.allowed_namespaces = normalize_allowed_namespaces_for_role(
                next_role,
                user.allowed_namespaces,
                default_namespaces=DEFAULT_ALLOWED_NAMESPACES,
            )
        user.updated_at = utc_now()
        session.flush()
        session.refresh(user)
        return serialize_user(user)


def delete_local_user(user_id: int) -> dict[str, Any]:
    """Delete a local user and their associated data.  Raises ValueError when the user was not found."""
    with db_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User id '{user_id}' was not found.")

        user_info = serialize_user(user)

        # Delete associated audit logs
        session.query(AuditLog).filter(AuditLog.actor_sub == str(user_id)).delete()

        # Delete chat sessions and messages owned by this user
        chat_sessions = session.query(ChatSession).filter(ChatSession.username == user.username).all()
        for cs in chat_sessions:
            session.query(ChatMessage).filter(ChatMessage.session_id == cs.session_id).delete()
            session.delete(cs)

        # Delete memory records owned by this user
        session.query(MemoryRecord).filter(MemoryRecord.username == user.username).delete()

        # Delete the user
        session.delete(user)
        session.commit()
        return user_info


def change_user_password(user_id: int, current_password: str, new_password: str) -> dict[str, Any]:
    if not password_meets_policy(new_password):
        raise ValueError(
            "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, and a digit."
        )
    with db_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("User was not found.")
        if not verify_password(current_password, user.password_hash):
            raise ValueError("Current password is invalid.")
        user.password_hash = hash_password(new_password)
        user.updated_at = utc_now()
        session.flush()
        session.refresh(user)
        return serialize_user(user)


def is_user_locked(user: User) -> bool:
    locked_until = ensure_utc(user.locked_until)
    return bool(locked_until and locked_until > utc_now())


def record_failed_login(username: str, *, ip_address: str | None = None) -> None:
    normalized_username = username.strip().lower()
    if not normalized_username:
        return
    with db_session() as session:
        user = session.query(User).filter(User.username == normalized_username).one_or_none()
        if user is None:
            # Audit even when user does not exist (prevents user enumeration via timing,
            # but still logs the attempt).
            record_audit_log(
                action="auth.login-failed",
                actor_sub=None,
                actor_username=normalized_username,
                auth_provider="local",
                detail={"reason": "user_not_found"},
                ip_address=ip_address,
            )
            return
        user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
        locked = False
        if user.failed_login_attempts >= ACCOUNT_LOCKOUT_THRESHOLD:
            user.locked_until = utc_now() + timedelta(minutes=ACCOUNT_LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
            locked = True
        user.updated_at = utc_now()
    record_audit_log(
        action="auth.login-failed",
        actor_sub=str(user.id) if user else None,
        actor_username=normalized_username,
        auth_provider=str(user.auth_provider) if user else "local",
        detail={"reason": "invalid_password", "account_locked": locked},
        ip_address=ip_address,
    )


def reset_failed_logins(user_id: int) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = utc_now()
        user.updated_at = utc_now()


# ── Password reset ──


def create_password_reset_token(user_id: int) -> str:
    """Generate a single-use, time-limited password reset token."""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utc_now() + timedelta(minutes=PASSWORD_RESET_TOKEN_TTL_MINUTES)
    with db_session() as session:
        # Invalidate any existing active tokens for this user
        session.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > utc_now(),
        ).update({"used_at": utc_now()})
        session.add(
            PasswordResetToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        session.flush()
    return token


def verify_password_reset_token(token: str) -> dict[str, Any] | None:
    """Return the user dict if the token is valid and unused, else None."""
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with db_session() as session:
        record = (
            session.query(PasswordResetToken)
            .filter(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > utc_now(),
            )
            .one_or_none()
        )
        if record is None:
            return None
        user = session.get(User, record.user_id)
        if user is None or not user.is_active:
            return None
        return serialize_user(user)


def consume_password_reset_token(token: str, new_password: str) -> dict[str, Any]:
    """Validate token, update password, and mark token consumed."""
    if not password_meets_policy(new_password):
        raise ValueError(
            "Password must be at least 8 characters and include an uppercase letter, a lowercase letter, and a digit."
        )
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db_session() as session:
        record = (
            session.query(PasswordResetToken)
            .filter(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > utc_now(),
            )
            .one_or_none()
        )
        if record is None:
            raise ValueError("Invalid or expired password reset token.")
        user = session.get(User, record.user_id)
        if user is None:
            raise ValueError("User not found.")
        if not user.is_active:
            raise ValueError("User account is inactive.")
        user.password_hash = hash_password(new_password)
        user.updated_at = utc_now()
        record.used_at = utc_now()
        session.flush()
        session.refresh(user)
        return serialize_user(user)


# ── Audit helpers ──


def audit_login_success(
    *,
    username: str,
    auth_provider: str,
    ip_address: str | None,
    user_id: int | None = None,
) -> None:
    record_audit_log(
        action="auth.login",
        actor_sub=str(user_id) if user_id else None,
        actor_username=username,
        auth_provider=auth_provider,
        detail={"success": True},
        ip_address=ip_address,
    )


def audit_login_failure(
    *,
    username: str,
    auth_provider: str,
    reason: str,
    ip_address: str | None,
) -> None:
    record_audit_log(
        action="auth.login-failed",
        actor_sub=None,
        actor_username=username,
        auth_provider=auth_provider,
        detail={"reason": reason},
        ip_address=ip_address,
    )


def get_active_user_context(user_id: int) -> dict[str, Any] | None:
    try:
        with db_session() as session:
            user = session.get(User, user_id)
            if user is None or not user.is_active or is_user_locked(user):
                return None
            return serialize_user(user)
    except _AUTH_STORAGE_ERRORS:
        return None


def create_session_for_user(
    user_id: int,
    *,
    auth_provider: str,
    ip_address: str | None,
    user_agent: str | None,
    ttl_seconds: int,
) -> tuple[dict[str, Any], str]:
    issued_at = utc_now()
    session_id = secrets.token_urlsafe(24)
    refresh_secret = secrets.token_urlsafe(48)
    refresh_token = f"{session_id}.{refresh_secret}"
    record = UserSession(
        id=session_id,
        user_id=user_id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        auth_provider=auth_provider,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:512] or None,
        created_at=issued_at,
        last_used_at=issued_at,
        expires_at=issued_at + timedelta(seconds=ttl_seconds),
    )
    with db_session() as session:
        session.add(record)
        session.flush()
    return {
        "id": record.id,
        "user_id": record.user_id,
        "auth_provider": record.auth_provider,
        "expires_at": ensure_utc(record.expires_at).isoformat(),
    }, refresh_token


def revoke_session(session_id: str) -> None:
    if not session_id:
        return
    try:
        with db_session() as session:
            record = session.get(UserSession, session_id)
            if record is None or record.revoked_at is not None:
                return
            record.revoked_at = utc_now()
            record.last_used_at = utc_now()
    except _AUTH_STORAGE_ERRORS:
        return


def revoke_refresh_token(refresh_token: str) -> None:
    session_id, _separator, _secret = refresh_token.partition(".")
    revoke_session(session_id)


# Grace period (seconds) after a session is revoked during which access tokens
# tied to it are still accepted.  This avoids a cascade of 401s when the refresh
# rotation revokes the old session while in-flight requests still carry the old
# access token.
_SESSION_REVOKE_GRACE_SECONDS = 30


def is_session_active(session_id: str, *, user_id: int | None = None) -> bool:
    if not session_id:
        return False
    try:
        with db_session() as session:
            record = session.get(UserSession, session_id)
            expires_at = ensure_utc(record.expires_at) if record is not None else None
            if record is None or expires_at is None or expires_at <= utc_now():
                return False
            if record.revoked_at is not None:
                revoked_at = ensure_utc(record.revoked_at)
                if revoked_at is None or utc_now() > revoked_at + timedelta(seconds=_SESSION_REVOKE_GRACE_SECONDS):
                    return False
            return not (user_id is not None and int(record.user_id) != int(user_id))
    except _AUTH_STORAGE_ERRORS:
        return False


def verify_refresh_session(refresh_token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    session_id, separator, _secret = refresh_token.partition(".")
    if not session_id or not separator:
        raise ValueError("Refresh token format is invalid.")

    try:
        with db_session() as session:
            record = session.get(UserSession, session_id)
            if record is None:
                raise ValueError("Refresh session was not found.")
            if record.revoked_at is not None:
                raise ValueError("Refresh session has been revoked.")
            expires_at = ensure_utc(record.expires_at)
            if expires_at is None or expires_at <= utc_now():
                raise ValueError("Refresh session has expired.")
            if not secrets.compare_digest(record.refresh_token_hash, hash_refresh_token(refresh_token)):
                raise ValueError("Refresh token is invalid.")

            user = session.get(User, record.user_id)
            if user is None or not user.is_active or is_user_locked(user):
                raise ValueError("Refresh session user is unavailable.")

            record.last_used_at = utc_now()
            session.flush()
            return serialize_user(user), {
                "id": record.id,
                "user_id": record.user_id,
                "auth_provider": record.auth_provider,
                "expires_at": expires_at.isoformat(),
            }
    except _AUTH_STORAGE_ERRORS as exc:
        raise ValueError("Authentication session storage is unavailable.") from exc


def rotate_refresh_session(
    refresh_token: str,
    *,
    ip_address: str | None,
    user_agent: str | None,
    ttl_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    user, record = verify_refresh_session(refresh_token)
    revoke_session(str(record.get("id") or ""))
    new_record, new_refresh_token = create_session_for_user(
        int(user["id"]),
        auth_provider=str(record.get("auth_provider") or user.get("auth_provider") or "local"),
        ip_address=ip_address,
        user_agent=user_agent,
        ttl_seconds=ttl_seconds,
    )
    return user, new_record, new_refresh_token


def login_rate_limit_key(ip_address: str | None, username: str) -> str:
    return f"{ip_address or 'unknown'}:{username.strip().lower()}"


def login_rate_limited(key: str) -> bool:
    """Return True if the key is rate-limited (window limit or exponential backoff)."""
    now = time.time()
    with _LOGIN_RATE_LIMIT_LOCK:
        attempts = [item for item in _LOGIN_ATTEMPTS.get(key, []) if now - item <= LOGIN_RATE_LIMIT_WINDOW_SECONDS]
        _LOGIN_ATTEMPTS[key] = attempts
        if len(attempts) >= LOGIN_RATE_LIMIT_ATTEMPTS:
            return True
        # Exponential backoff after consecutive failures exceed the window threshold
        consecutive = _LOGIN_CONSECUTIVE_FAILURES.get(key, 0)
        if consecutive >= LOGIN_RATE_LIMIT_ATTEMPTS:
            backoff = min(
                LOGIN_EXPONENTIAL_BACKOFF_BASE_SECONDS * (2 ** (consecutive - LOGIN_RATE_LIMIT_ATTEMPTS)),
                LOGIN_EXPONENTIAL_BACKOFF_MAX_SECONDS,
            )
            last_attempt = _LOGIN_LAST_ATTEMPT.get(key, 0)
            if now - last_attempt < backoff:
                return True
        return False


def note_login_attempt(key: str, *, success: bool) -> None:
    with _LOGIN_RATE_LIMIT_LOCK:
        if success:
            _LOGIN_ATTEMPTS.pop(key, None)
            _LOGIN_CONSECUTIVE_FAILURES.pop(key, None)
            _LOGIN_LAST_ATTEMPT.pop(key, None)
            return
        attempts = _LOGIN_ATTEMPTS.setdefault(key, [])
        attempts.append(time.time())
        _LOGIN_LAST_ATTEMPT[key] = time.time()
        _LOGIN_CONSECUTIVE_FAILURES[key] = _LOGIN_CONSECUTIVE_FAILURES.get(key, 0) + 1


# ── API rate limiting ──

INVOKE_RATE_LIMIT_PER_MINUTE = max(int(os.getenv("API_INVOKE_RATE_LIMIT_PER_MINUTE", "60")), 1)
API_RATE_LIMIT_LOCK = threading.Lock()
_API_RATE_BUCKETS: dict[str, list[float]] = {}


def api_rate_limit_key(resource: str, identifier: str) -> str:
    """Build a rate-limit key for API resources.

    ``resource`` is the endpoint type (e.g. 'invoke', 'crud').
    ``identifier`` is a user or IP identifier.
    """
    return f"api:{resource}:{identifier}"


def api_rate_limited(key: str, *, max_per_minute: int | None = None) -> bool:
    """Return True when *key* has exceeded the rate limit.

    Uses a sliding-window check: if more than *max_per_minute* requests
    have been recorded in the last 60 seconds, the caller is rate-limited.
    """
    threshold = max_per_minute or INVOKE_RATE_LIMIT_PER_MINUTE
    now = time.time()
    window_start = now - 60.0
    with API_RATE_LIMIT_LOCK:
        bucket = _API_RATE_BUCKETS.setdefault(key, [])
        # Prune stale entries
        while bucket and bucket[0] < window_start:
            bucket.pop(0)
        bucket.append(now)
        return len(bucket) > threshold


def note_api_request(key: str) -> None:
    """Record an API request in the rate-limit bucket."""
    now = time.time()
    window_start = now - 60.0
    with API_RATE_LIMIT_LOCK:
        bucket = _API_RATE_BUCKETS.setdefault(key, [])
        while bucket and bucket[0] < window_start:
            bucket.pop(0)
        bucket.append(now)


def record_audit_log(
    *,
    action: str,
    actor_sub: str | None,
    actor_username: str | None,
    actor_type: str | None = "user",
    auth_provider: str | None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    resource_namespace: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    with db_session() as session:
        session.add(
            AuditLog(
                actor_sub=actor_sub,
                actor_username=actor_username,
                actor_type=actor_type,
                auth_provider=auth_provider,
                action=action,
                resource_kind=resource_kind,
                resource_name=resource_name,
                resource_namespace=resource_namespace,
                detail_json=detail or None,
                ip_address=ip_address,
                request_id=request_id,
            )
        )


AUDIT_RETENTION_DAYS = max(int(os.getenv("AUDIT_RETENTION_DAYS", "90")), 1)


def query_audit_logs(
    *,
    actor: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    namespace: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Query audit logs with optional filters. Returns {items, total}."""
    with db_session() as session:
        q = session.query(AuditLog)
        if actor:
            q = q.filter(AuditLog.actor_username == actor)
        if actor_type:
            q = q.filter(AuditLog.actor_type == actor_type)
        if action:
            q = q.filter(AuditLog.action == action)
        if resource_kind:
            q = q.filter(AuditLog.resource_kind == resource_kind)
        if resource_name:
            q = q.filter(AuditLog.resource_name == resource_name)
        if namespace:
            q = q.filter(AuditLog.resource_namespace == namespace)
        if from_date:
            q = q.filter(AuditLog.created_at >= from_date)
        if to_date:
            q = q.filter(AuditLog.created_at <= to_date)
        total = q.count()
        rows = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(min(limit, 500)).all()
        return {
            "items": [
                {
                    "id": r.id,
                    "timestamp": ensure_utc(r.created_at).isoformat() if r.created_at else None,
                    "actor": r.actor_username,
                    "actor_type": r.actor_type,
                    "action": r.action,
                    "resource_kind": r.resource_kind,
                    "resource_name": r.resource_name,
                    "namespace": r.resource_namespace,
                    "detail": r.detail_json,
                    "ip_address": r.ip_address,
                    "request_id": r.request_id,
                }
                for r in rows
            ],
            "total": total,
        }


def purge_old_audit_logs() -> int:
    """Delete audit records older than AUDIT_RETENTION_DAYS. Returns count deleted."""
    cutoff = utc_now() - timedelta(days=AUDIT_RETENTION_DAYS)
    with db_session() as session:
        count = session.query(AuditLog).filter(AuditLog.created_at < cutoff).delete()
        return count


# ── Token Usage Tracking ──

# Default model pricing (per 1K tokens). Override via MODEL_PRICING_JSON env var.
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"prompt_per_1k": 0.005, "completion_per_1k": 0.015},
    "gpt-4o-mini": {"prompt_per_1k": 0.00015, "completion_per_1k": 0.0006},
    "gpt-4-turbo": {"prompt_per_1k": 0.01, "completion_per_1k": 0.03},
    "gpt-4": {"prompt_per_1k": 0.03, "completion_per_1k": 0.06},
    "gpt-3.5-turbo": {"prompt_per_1k": 0.0005, "completion_per_1k": 0.0015},
    "claude-sonnet-4-20250514": {"prompt_per_1k": 0.003, "completion_per_1k": 0.015},
    "claude-3-5-haiku-20241022": {"prompt_per_1k": 0.001, "completion_per_1k": 0.005},
}

_pricing_override = os.getenv("MODEL_PRICING_JSON", "").strip()
MODEL_PRICING: dict[str, dict[str, float]] = json.loads(_pricing_override) if _pricing_override else _DEFAULT_PRICING


def estimate_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Estimate USD cost from token counts using the model pricing table."""
    if not model:
        return None
    pricing = MODEL_PRICING.get(model) or MODEL_PRICING.get(model.split("/")[-1])
    if not pricing:
        return None
    cost = (prompt_tokens / 1000) * pricing.get("prompt_per_1k", 0) + (completion_tokens / 1000) * pricing.get(
        "completion_per_1k", 0
    )
    return round(cost, 6)


def record_usage(
    *,
    agent_name: str,
    namespace: str,
    user_id: str | None = None,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    session_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """Record a single usage event."""
    cost = estimate_cost(model, prompt_tokens, completion_tokens)
    with db_session() as session:
        session.add(
            UsageRecord(
                agent_name=agent_name,
                namespace=namespace,
                user_id=user_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens if total_tokens else prompt_tokens + completion_tokens,
                estimated_cost_usd=cost,
                session_id=session_id,
                request_id=request_id,
            )
        )


def query_usage_summary(
    *,
    namespace: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    group_by: str = "agent",
) -> list[dict[str, Any]]:
    """Return aggregated usage. group_by: 'agent', 'model', 'user', 'day'."""
    with db_session() as session:
        if group_by == "model":
            group_col = UsageRecord.model
        elif group_by == "user":
            group_col = UsageRecord.user_id
        elif group_by == "day":
            group_col = func.date(UsageRecord.timestamp)
        else:
            group_col = UsageRecord.agent_name

        q = session.query(
            group_col.label("group_key"),
            func.sum(UsageRecord.prompt_tokens).label("prompt_tokens"),
            func.sum(UsageRecord.completion_tokens).label("completion_tokens"),
            func.sum(UsageRecord.total_tokens).label("total_tokens"),
            func.sum(UsageRecord.estimated_cost_usd).label("estimated_cost_usd"),
            func.count(UsageRecord.id).label("invocations"),
        )
        if namespace:
            q = q.filter(UsageRecord.namespace == namespace)
        if from_date:
            q = q.filter(UsageRecord.timestamp >= from_date)
        if to_date:
            q = q.filter(UsageRecord.timestamp <= to_date)
        q = q.group_by(group_col).order_by(func.sum(UsageRecord.total_tokens).desc())
        return [
            {
                "group": str(row.group_key or "unknown"),
                "prompt_tokens": int(row.prompt_tokens or 0),
                "completion_tokens": int(row.completion_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
                "estimated_cost_usd": round(float(row.estimated_cost_usd or 0), 4),
                "invocations": int(row.invocations or 0),
            }
            for row in q.all()
        ]


def query_usage_detail(
    *,
    namespace: str | None = None,
    agent_name: str | None = None,
    model: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return individual usage records, paginated."""
    with db_session() as session:
        q = session.query(UsageRecord)
        if namespace:
            q = q.filter(UsageRecord.namespace == namespace)
        if agent_name:
            q = q.filter(UsageRecord.agent_name == agent_name)
        if model:
            q = q.filter(UsageRecord.model == model)
        if from_date:
            q = q.filter(UsageRecord.timestamp >= from_date)
        if to_date:
            q = q.filter(UsageRecord.timestamp <= to_date)
        total = q.count()
        rows = q.order_by(UsageRecord.timestamp.desc()).offset(offset).limit(min(limit, 500)).all()
        return {
            "items": [
                {
                    "id": r.id,
                    "timestamp": ensure_utc(r.timestamp).isoformat() if r.timestamp else None,
                    "agent_name": r.agent_name,
                    "namespace": r.namespace,
                    "user_id": r.user_id,
                    "model": r.model,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "estimated_cost_usd": r.estimated_cost_usd,
                    "session_id": r.session_id,
                    "request_id": r.request_id,
                }
                for r in rows
            ],
            "total": total,
        }


# ── Chat Session Persistence ──


def list_chat_sessions(namespace: str, agent_name: str, username: str | None = None) -> list[dict[str, Any]]:
    """Return all chat sessions for a given agent, ordered most recent first."""
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
                "created_at": ensure_utc(r.created_at).isoformat() if r.created_at else None,
                "updated_at": ensure_utc(r.updated_at).isoformat() if r.updated_at else None,
                "summary": _summarize_chat_messages(get_chat_session_messages(r.session_id)),
            }
            for r in rows
        ]


def create_chat_session(
    namespace: str,
    agent_name: str,
    session_id: str,
    title: str = "Untitled",
    username: str | None = None,
) -> dict[str, Any]:
    """Create a new chat session record."""
    with db_session() as session:
        record = ChatSession(
            namespace=namespace,
            agent_name=agent_name,
            session_id=session_id,
            title=title,
            username=username,
        )
        session.add(record)
        session.flush()
        return {
            "session_id": record.session_id,
            "title": record.title,
            "agent_name": record.agent_name,
            "namespace": record.namespace,
            "username": record.username,
            "created_at": ensure_utc(record.created_at).isoformat() if record.created_at else None,
            "updated_at": ensure_utc(record.updated_at).isoformat() if record.updated_at else None,
        }


def get_chat_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Return all messages for a session, ordered by creation time."""
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
                "created_at": ensure_utc(r.created_at).isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def save_chat_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    """Replace all messages for a session (full snapshot save)."""
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
        chat_session = session.query(ChatSession).filter(ChatSession.session_id == session_id).one_or_none()
        if chat_session:
            chat_session.updated_at = utc_now()
            summary = _summarize_chat_messages(messages)
            record_memory_items(
                chat_session.namespace,
                chat_session.agent_name,
                session_id=chat_session.session_id,
                username=chat_session.username,
                summary=summary,
                session=session,
                auto_promote=True,
            )


def update_chat_session_title(session_id: str, title: str) -> dict[str, Any] | None:
    """Update a session's title."""
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
            "created_at": ensure_utc(record.created_at).isoformat() if record.created_at else None,
            "updated_at": ensure_utc(record.updated_at).isoformat() if record.updated_at else None,
        }


def delete_chat_session(session_id: str) -> bool:
    """Delete a chat session and its messages."""
    with db_session() as session:
        session.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
        deleted = session.query(ChatSession).filter(ChatSession.session_id == session_id).delete()
        return deleted > 0


# ── Workflow Run History ──


def record_workflow_run(
    *,
    workflow_name: str,
    namespace: str = "default",
    run_id: str | None = None,
    phase: str = "pending",
    total_steps: int | None = None,
    completed_steps: int | None = None,
    failed_steps: int | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    triggered_by: str | None = None,
    input_text: str | None = None,
    summary_json: str | None = None,
) -> dict[str, Any]:
    """Record or update a workflow run in history."""
    with db_session() as session:
        # Upsert by run_id if provided
        existing = None
        if run_id:
            existing = (
                session.query(WorkflowRunHistory)
                .filter(
                    WorkflowRunHistory.workflow_name == workflow_name,
                    WorkflowRunHistory.namespace == namespace,
                    WorkflowRunHistory.run_id == run_id,
                )
                .one_or_none()
            )
        if existing:
            existing.phase = phase
            if total_steps is not None:
                existing.total_steps = total_steps
            if completed_steps is not None:
                existing.completed_steps = completed_steps
            if failed_steps is not None:
                existing.failed_steps = failed_steps
            if started_at:
                existing.started_at = started_at
            if completed_at:
                existing.completed_at = completed_at
            if summary_json:
                existing.summary_json = summary_json
            record = existing
        else:
            record = WorkflowRunHistory(
                workflow_name=workflow_name,
                namespace=namespace,
                run_id=run_id,
                phase=phase,
                total_steps=total_steps,
                completed_steps=completed_steps,
                failed_steps=failed_steps,
                started_at=started_at,
                completed_at=completed_at,
                triggered_by=triggered_by,
                input_text=input_text,
                summary_json=summary_json,
            )
            session.add(record)
        session.flush()
        return {
            "id": record.id,
            "workflow_name": record.workflow_name,
            "namespace": record.namespace,
            "run_id": record.run_id,
            "phase": record.phase,
            "total_steps": record.total_steps,
            "completed_steps": record.completed_steps,
            "failed_steps": record.failed_steps,
            "started_at": ensure_utc(record.started_at).isoformat() if record.started_at else None,
            "completed_at": ensure_utc(record.completed_at).isoformat() if record.completed_at else None,
            "triggered_by": record.triggered_by,
            "input_text": record.input_text,
            "created_at": ensure_utc(record.created_at).isoformat() if record.created_at else None,
        }


def record_workflow_run_log_archive(
    *,
    workflow_name: str,
    namespace: str = "default",
    run_id: str,
    log_text: str,
    source: str,
    truncated: bool = False,
    captured_at: datetime | None = None,
) -> None:
    with db_session() as session:
        record = (
            session.query(WorkflowRun)
            .filter(
                WorkflowRun.namespace == namespace,
                WorkflowRun.resource_name == workflow_name,
                WorkflowRun.run_id == run_id,
            )
            .one_or_none()
        )
        if record is None:
            return
        record.log_archive_text = log_text
        record.log_archive_source = source[:64] if source else None
        record.log_archive_truncated = bool(truncated)
        record.log_archive_captured_at = captured_at or utc_now()
        record.updated_at = utc_now()


def get_workflow_run_trace(
    workflow_name: str,
    namespace: str = "default",
    run_id: str | None = None,
    *,
    history_id: int | None = None,
    include_logs: bool = False,
) -> dict[str, Any] | None:
    with db_session() as session:
        history_row: WorkflowRunHistory | None = None
        if run_id:
            history_row = (
                session.query(WorkflowRunHistory)
                .filter(
                    WorkflowRunHistory.workflow_name == workflow_name,
                    WorkflowRunHistory.namespace == namespace,
                    WorkflowRunHistory.run_id == run_id,
                )
                .order_by(WorkflowRunHistory.created_at.desc())
                .first()
            )
        elif history_id is not None:
            history_row = (
                session.query(WorkflowRunHistory)
                .filter(
                    WorkflowRunHistory.id == history_id,
                    WorkflowRunHistory.workflow_name == workflow_name,
                    WorkflowRunHistory.namespace == namespace,
                )
                .one_or_none()
            )
            if history_row is not None:
                run_id = history_row.run_id

        mirror_row: WorkflowRun | None = None
        if run_id:
            mirror_row = (
                session.query(WorkflowRun)
                .filter(
                    WorkflowRun.namespace == namespace,
                    WorkflowRun.resource_name == workflow_name,
                    WorkflowRun.run_id == run_id,
                )
                .one_or_none()
            )

        if history_row is None and mirror_row is None:
            return None

        created_at = ensure_utc(mirror_row.created_at).isoformat() if mirror_row and mirror_row.created_at else (
            ensure_utc(history_row.created_at).isoformat() if history_row and history_row.created_at else None
        )
        completed_at = ensure_utc(mirror_row.completed_at).isoformat() if mirror_row and mirror_row.completed_at else (
            ensure_utc(history_row.completed_at).isoformat() if history_row and history_row.completed_at else None
        )

        return {
            "workflow_name": workflow_name,
            "namespace": namespace,
            "history_id": history_row.id if history_row else None,
            "run_id": run_id,
            "generation": mirror_row.generation if mirror_row else None,
            "phase": mirror_row.phase if mirror_row else (history_row.phase if history_row else None),
            "spec": _json_clone(mirror_row.spec_json) if mirror_row else None,
            "status": _json_clone(mirror_row.status_json) if mirror_row else None,
            "summary": _json_clone(mirror_row.summary_json) if mirror_row else None,
            "step_results": _json_clone(mirror_row.step_results_json) if mirror_row else None,
            "step_states": _json_clone(mirror_row.step_states_json) if mirror_row else None,
            "artifact_path": mirror_row.artifact_path if mirror_row else None,
            "journal_path": mirror_row.journal_path if mirror_row else None,
            "worker_job_name": mirror_row.worker_job_name if mirror_row else None,
            "pending_approval_name": mirror_row.pending_approval_name if mirror_row else None,
            "triggered_by": history_row.triggered_by if history_row else None,
            "input_text": history_row.input_text if history_row else None,
            "created_at": created_at,
            "updated_at": ensure_utc(mirror_row.updated_at).isoformat() if mirror_row and mirror_row.updated_at else None,
            "completed_at": completed_at,
            "archived_log_available": bool(mirror_row and mirror_row.log_archive_text),
            "archived_log_source": mirror_row.log_archive_source if mirror_row else None,
            "archived_log_truncated": bool(mirror_row.log_archive_truncated) if mirror_row else False,
            "archived_log_captured_at": ensure_utc(mirror_row.log_archive_captured_at).isoformat() if mirror_row and mirror_row.log_archive_captured_at else None,
            **({"logs": mirror_row.log_archive_text if mirror_row else None} if include_logs else {}),
        }


def list_workflow_runs(
    workflow_name: str,
    namespace: str = "default",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent runs for a workflow, newest first."""
    with db_session() as session:
        rows = (
            session.query(WorkflowRunHistory)
            .filter(WorkflowRunHistory.workflow_name == workflow_name, WorkflowRunHistory.namespace == namespace)
            .order_by(WorkflowRunHistory.created_at.desc())
            .limit(min(limit, 100))
            .all()
        )

        mirror_by_run_id: dict[str, WorkflowRun] = {}
        run_ids = [str(row.run_id) for row in rows if row.run_id]
        if run_ids:
            mirror_rows = (
                session.query(WorkflowRun)
                .filter(
                    WorkflowRun.namespace == namespace,
                    WorkflowRun.resource_name == workflow_name,
                    WorkflowRun.run_id.in_(run_ids),
                )
                .all()
            )
            mirror_by_run_id = {str(row.run_id): row for row in mirror_rows if row.run_id}

        if not rows:
            mirror_rows = (
                session.query(WorkflowRun)
                .filter(
                    WorkflowRun.namespace == namespace,
                    WorkflowRun.resource_name == workflow_name,
                )
                .order_by(WorkflowRun.created_at.desc())
                .limit(min(limit, 100))
                .all()
            )
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "phase": row.phase,
                    "total_steps": (row.summary_json or {}).get("totalSteps") if isinstance(row.summary_json, dict) else None,
                    "completed_steps": (row.summary_json or {}).get("completedSteps") if isinstance(row.summary_json, dict) else None,
                    "failed_steps": (row.summary_json or {}).get("failedSteps") if isinstance(row.summary_json, dict) else None,
                    "started_at": None,
                    "completed_at": ensure_utc(row.completed_at).isoformat() if row.completed_at else None,
                    "triggered_by": None,
                    "input_text": (row.spec_json or {}).get("input") if isinstance(row.spec_json, dict) else None,
                    "created_at": ensure_utc(row.created_at).isoformat() if row.created_at else None,
                    "trace_available": True,
                    "archived_log_available": bool(row.log_archive_text),
                    "journal_available": bool(row.journal_path),
                }
                for row in mirror_rows
            ]

        return [
            {
                "id": r.id,
                "run_id": r.run_id,
                "phase": r.phase,
                "total_steps": r.total_steps,
                "completed_steps": r.completed_steps,
                "failed_steps": r.failed_steps,
                "started_at": ensure_utc(r.started_at).isoformat() if r.started_at else None,
                "completed_at": ensure_utc(r.completed_at).isoformat() if r.completed_at else None,
                "triggered_by": r.triggered_by,
                "input_text": r.input_text,
                "created_at": ensure_utc(r.created_at).isoformat() if r.created_at else None,
                "trace_available": bool(r.run_id and str(r.run_id) in mirror_by_run_id),
                "archived_log_available": bool(r.run_id and mirror_by_run_id.get(str(r.run_id)) and mirror_by_run_id[str(r.run_id)].log_archive_text),
                "journal_available": bool(r.run_id and mirror_by_run_id.get(str(r.run_id)) and mirror_by_run_id[str(r.run_id)].journal_path),
            }
            for r in rows
        ]


# ─── Observatory execution trace helpers ───────────────────────────────────


def _execution_trace_to_dict(row: ExecutionTraceRow) -> dict[str, Any]:
    steps = list(row.steps_json or [])
    llm_calls = row.llm_calls_json or []
    tool_calls = row.tool_calls_json or []
    llm_by_step: dict[str, list] = {}
    tool_by_step: dict[str, list] = {}
    for llm in llm_calls:
        sid = str(llm.get("step_id", ""))
        llm_by_step.setdefault(sid, []).append(llm)
    for tc in tool_calls:
        sid = str(tc.get("step_id", ""))
        tool_by_step.setdefault(sid, []).append(tc)
    for s in steps:
        sid = str(s.get("id", ""))
        s["llm_calls"] = llm_by_step.get(sid, [])
        s["tool_calls"] = tool_by_step.get(sid, [])
        if "step_index" not in s and "index" in s:
            s["step_index"] = s.get("index")
        if s.get("llm_calls"):
            s["prompt_tokens"] = sum(int(c.get("prompt_tokens", 0) or 0) for c in s["llm_calls"])
            s["completion_tokens"] = sum(int(c.get("completion_tokens", 0) or 0) for c in s["llm_calls"])
            s["tokens_used"] = s["prompt_tokens"] + s["completion_tokens"]
        if s.get("tool_calls") and s.get("tool_call_count") is None:
            s["tool_call_count"] = len(s["tool_calls"])
    return {
        "id": row.id,
        "workflow_name": row.workflow_name,
        "namespace": row.namespace,
        "agent_name": row.agent_name,
        "run_id": row.run_id,
        "status": row.status,
        "started_at": ensure_utc(row.started_at).isoformat() if row.started_at else None,
        "completed_at": ensure_utc(row.completed_at).isoformat() if row.completed_at else None,
        "duration_ms": row.duration_ms,
        "input_preview": row.input_preview,
        "output_preview": row.output_preview,
        "step_count": row.step_count or 0,
        "llm_call_count": row.llm_call_count or 0,
        "tool_call_count": row.tool_call_count or 0,
        "total_tokens": row.total_tokens or 0,
        "total_cost_usd": row.total_cost_usd,
        "steps": steps,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "events": row.events_json or [],
        "created_at": ensure_utc(row.created_at).isoformat() if row.created_at else None,
    }


def record_execution_trace(
    *,
    trace_id: str,
    workflow_name: str,
    namespace: str = "default",
    agent_name: str | None = None,
    run_id: str | None = None,
    status: str = "running",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    duration_ms: int | None = None,
    input_preview: str | None = None,
    output_preview: str | None = None,
    step_count: int = 0,
    llm_call_count: int = 0,
    tool_call_count: int = 0,
    total_tokens: int = 0,
    total_cost_usd: float | None = None,
    steps_json: list | None = None,
    llm_calls_json: list | None = None,
    tool_calls_json: list | None = None,
    events_json: list | None = None,
) -> dict[str, Any]:
    with db_session() as session:
        existing = session.query(ExecutionTraceRow).filter(ExecutionTraceRow.id == trace_id).one_or_none()
        if existing:
            existing.status = status
            if completed_at:
                existing.completed_at = completed_at
            if duration_ms is not None:
                existing.duration_ms = duration_ms
            if output_preview is not None:
                existing.output_preview = output_preview
            if step_count:
                existing.step_count = step_count
            if llm_call_count:
                existing.llm_call_count = llm_call_count
            if tool_call_count:
                existing.tool_call_count = tool_call_count
            if total_tokens:
                existing.total_tokens = total_tokens
            if total_cost_usd is not None:
                existing.total_cost_usd = total_cost_usd
            if steps_json is not None:
                existing.steps_json = steps_json
            if llm_calls_json is not None:
                existing.llm_calls_json = llm_calls_json
            if tool_calls_json is not None:
                existing.tool_calls_json = tool_calls_json
            if events_json is not None:
                existing.events_json = events_json
            record = existing
        else:
            record = ExecutionTraceRow(
                id=trace_id,
                workflow_name=workflow_name,
                namespace=namespace,
                agent_name=agent_name,
                run_id=run_id,
                status=status,
                started_at=started_at or utc_now(),
                completed_at=completed_at,
                duration_ms=duration_ms,
                input_preview=input_preview[:2000] if input_preview else None,
                output_preview=output_preview[:2000] if output_preview else None,
                step_count=step_count,
                llm_call_count=llm_call_count,
                tool_call_count=tool_call_count,
                total_tokens=total_tokens,
                total_cost_usd=total_cost_usd,
                steps_json=steps_json,
                llm_calls_json=llm_calls_json,
                tool_calls_json=tool_calls_json,
                events_json=events_json,
            )
            session.add(record)
        session.flush()
        return _execution_trace_to_dict(record)


def list_execution_traces(
    namespace: str = "default",
    *,
    workflow: str | None = None,
    agent: str | None = None,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    search: str | None = None,
    sort_by: str = "newest",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    with db_session() as session:
        query = session.query(ExecutionTraceRow).filter(ExecutionTraceRow.namespace == namespace)
        if workflow:
            query = query.filter(ExecutionTraceRow.workflow_name.ilike(f"%{workflow}%"))
        if agent:
            query = query.filter(ExecutionTraceRow.agent_name.ilike(f"%{agent}%"))
        if status:
            query = query.filter(ExecutionTraceRow.status == status)
        if from_date:
            try:
                from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
                query = query.filter(ExecutionTraceRow.started_at >= from_dt)
            except (ValueError, TypeError):
                pass
        if to_date:
            try:
                to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
                query = query.filter(ExecutionTraceRow.started_at <= to_dt)
            except (ValueError, TypeError):
                pass
        if search:
            query = query.filter(
                (ExecutionTraceRow.workflow_name.ilike(f"%{search}%"))
                | (ExecutionTraceRow.agent_name.ilike(f"%{search}%"))
                | (ExecutionTraceRow.run_id.ilike(f"%{search}%"))
            )
        total = query.count()
        if sort_by == "oldest":
            query = query.order_by(ExecutionTraceRow.started_at.asc())
        else:
            query = query.order_by(ExecutionTraceRow.started_at.desc().nullslast())
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        rows = query.offset(offset).limit(limit).all()
        return {
            "items": [_execution_trace_to_dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def get_execution_trace(trace_id: str) -> dict[str, Any] | None:
    with db_session() as session:
        row = session.query(ExecutionTraceRow).filter(ExecutionTraceRow.id == trace_id).one_or_none()
        if row is None and str(trace_id).startswith("wf-run-"):
            # Workflow run IDs may not have their own trace row; look up the
            # actual exec- trace record that shares the same run_id.
            row = (
                session.query(ExecutionTraceRow)
                .filter(
                    ExecutionTraceRow.run_id == trace_id,
                    ExecutionTraceRow.id.like("exec-%"),
                )
                .order_by(ExecutionTraceRow.started_at.desc().nullslast())
                .first()
            )
        if row is None:
            return None
        return _execution_trace_to_dict(row)


def delete_execution_trace(trace_id: str) -> bool:
    with db_session() as session:
        row = session.query(ExecutionTraceRow).filter(ExecutionTraceRow.id == trace_id).one_or_none()
        if row is None:
            return False
        session.delete(row)
        return True


# ─── Webhook & Trigger CRUD helpers ────────────────────────────────────────


def list_webhook_receivers(namespace: str) -> list[dict[str, Any]]:
    normalized = str(namespace or "default").strip() or "default"
    with db_session() as session:
        rows = (
            session.query(WebhookReceiverRow)
            .filter(WebhookReceiverRow.namespace == normalized)
            .order_by(WebhookReceiverRow.name.asc())
            .all()
        )
        return [row.to_dict() for row in rows]


def get_webhook_receiver(namespace: str, name: str) -> dict[str, Any] | None:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    if not normalized_name:
        return None
    with db_session() as session:
        row = (
            session.query(WebhookReceiverRow)
            .filter(WebhookReceiverRow.namespace == normalized_ns, WebhookReceiverRow.name == normalized_name)
            .one_or_none()
        )
        return row.to_dict() if row is not None else None


def create_webhook_receiver(
    namespace: str,
    name: str,
    secret_ref: str,
    ip_allowlist: list[str] | None = None,
    rate_limit: int = 60,
    max_payload_bytes: int = 1048576,
    enabled: bool = True,
) -> dict[str, Any]:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise ValueError("Webhook name is required.")
    if not secret_ref or not str(secret_ref).strip():
        raise ValueError("secret_ref is required.")
    row = WebhookReceiverRow(
        namespace=normalized_ns,
        name=normalized_name,
        secret_ref=str(secret_ref).strip(),
        ip_allowlist=list(ip_allowlist) if ip_allowlist else [],
        rate_limit=max(1, int(rate_limit or 60)),
        max_payload_bytes=max(1024, int(max_payload_bytes or 1048576)),
        enabled=bool(enabled),
    )
    with db_session() as session:
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise ValueError(f"Webhook '{name}' already exists in namespace '{namespace}'") from exc
        return row.to_dict()


def update_webhook_receiver(
    namespace: str,
    name: str,
    secret_ref: str | None = None,
    ip_allowlist: list[str] | None = None,
    rate_limit: int | None = None,
    max_payload_bytes: int | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    with db_session() as session:
        row = (
            session.query(WebhookReceiverRow)
            .filter(WebhookReceiverRow.namespace == normalized_ns, WebhookReceiverRow.name == normalized_name)
            .one_or_none()
        )
        if row is None:
            raise ValueError(f"Webhook '{name}' not found in namespace '{namespace}'")
        if secret_ref is not None:
            row.secret_ref = str(secret_ref).strip()
        if ip_allowlist is not None:
            row.ip_allowlist = list(ip_allowlist)
        if rate_limit is not None:
            row.rate_limit = max(1, int(rate_limit))
        if max_payload_bytes is not None:
            row.max_payload_bytes = max(1024, int(max_payload_bytes))
        if enabled is not None:
            row.enabled = bool(enabled)
        row.updated_at = utc_now()
        return row.to_dict()


def delete_webhook_receiver(namespace: str, name: str) -> bool:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    with db_session() as session:
        row = (
            session.query(WebhookReceiverRow)
            .filter(WebhookReceiverRow.namespace == normalized_ns, WebhookReceiverRow.name == normalized_name)
            .one_or_none()
        )
        if row is None:
            return False
        session.delete(row)
        return True


def record_webhook_invocation(
    namespace: str,
    webhook_name: str,
    event_id: str,
    source_ip: str | None = None,
    signature_valid: bool = False,
    payload_size: int = 0,
    payload_snippet: str | None = None,
    headers_json: dict[str, Any] | None = None,
    matched_triggers: list[str] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    normalized_ns = str(namespace or "default").strip() or "default"
    row = WebhookInvocationRow(
        namespace=normalized_ns,
        webhook_name=str(webhook_name or "").strip(),
        event_id=str(event_id or "").strip(),
        source_ip=source_ip,
        signature_valid=signature_valid,
        payload_size=int(payload_size or 0),
        payload_snippet=str(payload_snippet)[:1024] if payload_snippet is not None else None,
        headers_json=_json_clone(headers_json),
        matched_triggers=list(matched_triggers) if matched_triggers else [],
        error_message=error_message,
    )
    with db_session() as session:
        session.add(row)
        session.flush()
        return row.to_dict()


def count_recent_webhook_invocations(namespace: str, webhook_name: str, seconds: int = 60) -> int:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(webhook_name or "").strip()
    since = utc_now() - timedelta(seconds=max(1, int(seconds)))
    with db_session() as session:
        return (
            session.query(WebhookInvocationRow)
            .filter(
                WebhookInvocationRow.namespace == normalized_ns,
                WebhookInvocationRow.webhook_name == normalized_name,
                WebhookInvocationRow.created_at >= since,
            )
            .count()
        )


def update_webhook_invocation_matched_triggers(invocation_id: int, matched_triggers: list[str]) -> None:
    with db_session() as session:
        row = session.query(WebhookInvocationRow).filter(WebhookInvocationRow.id == invocation_id).one_or_none()
        if row is not None:
            row.matched_triggers = list(matched_triggers)


def list_webhook_invocations(
    namespace: str,
    webhook_name: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    normalized_ns = str(namespace or "default").strip() or "default"
    with db_session() as session:
        query = session.query(WebhookInvocationRow).filter(WebhookInvocationRow.namespace == normalized_ns)
        if webhook_name:
            query = query.filter(WebhookInvocationRow.webhook_name == str(webhook_name).strip())
        rows = (
            query.order_by(WebhookInvocationRow.created_at.desc())
            .limit(max(1, int(limit)))
            .offset(max(0, int(offset)))
            .all()
        )
        return [row.to_dict() for row in rows]


def list_workflow_triggers(namespace: str) -> list[dict[str, Any]]:
    normalized = str(namespace or "default").strip() or "default"
    with db_session() as session:
        rows = (
            session.query(WorkflowTriggerRow)
            .filter(WorkflowTriggerRow.namespace == normalized)
            .order_by(WorkflowTriggerRow.name.asc())
            .all()
        )
        trigger_names = [str(row.name) for row in rows]
        execution_counts: dict[str, int] = {}
        last_triggered: dict[str, str] = {}
        if trigger_names:
            execution_rows = (
                session.query(TriggerExecutionRow)
                .filter(
                    TriggerExecutionRow.trigger_namespace == normalized,
                    TriggerExecutionRow.trigger_name.in_(trigger_names),
                )
                .all()
            )
            for execution in execution_rows:
                trigger_name = str(execution.trigger_name)
                execution_counts[trigger_name] = execution_counts.get(trigger_name, 0) + 1
                created_at = ensure_utc(execution.created_at).isoformat() if execution.created_at else None
                if created_at and created_at > last_triggered.get(trigger_name, ""):
                    last_triggered[trigger_name] = created_at

        payloads: list[dict[str, Any]] = []
        for row in rows:
            payload = row.to_dict()
            payload["execution_count"] = execution_counts.get(str(row.name), 0)
            payload["last_triggered"] = last_triggered.get(str(row.name))
            payloads.append(payload)
        return payloads


def get_workflow_trigger(namespace: str, name: str) -> dict[str, Any] | None:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    if not normalized_name:
        return None
    with db_session() as session:
        row = (
            session.query(WorkflowTriggerRow)
            .filter(WorkflowTriggerRow.namespace == normalized_ns, WorkflowTriggerRow.name == normalized_name)
            .one_or_none()
        )
        if row is None:
            return None
        payload = row.to_dict()
        payload["execution_count"] = (
            session.query(TriggerExecutionRow)
            .filter(
                TriggerExecutionRow.trigger_namespace == normalized_ns,
                TriggerExecutionRow.trigger_name == normalized_name,
            )
            .count()
        )
        last_execution = (
            session.query(TriggerExecutionRow)
            .filter(
                TriggerExecutionRow.trigger_namespace == normalized_ns,
                TriggerExecutionRow.trigger_name == normalized_name,
            )
            .order_by(TriggerExecutionRow.created_at.desc())
            .first()
        )
        payload["last_triggered"] = (
            ensure_utc(last_execution.created_at).isoformat() if last_execution and last_execution.created_at else None
        )
        return payload


def create_workflow_trigger(
    namespace: str,
    name: str,
    source_kind: str = "WebhookReceiver",
    source_name: str = "",
    event_filter: dict[str, Any] | None = None,
    target_workflow_name: str = "",
    target_workflow_namespace: str = "default",
    payload_mapping: dict[str, str] | None = None,
    retry_max_retries: int = 3,
    retry_backoff_seconds: int = 60,
    notifications_on_success: list[str] | None = None,
    notifications_on_failure: list[str] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise ValueError("Trigger name is required.")
    if not source_name or not str(source_name).strip():
        raise ValueError("source_name is required.")
    if not target_workflow_name or not str(target_workflow_name).strip():
        raise ValueError("target_workflow_name is required.")
    row = WorkflowTriggerRow(
        namespace=normalized_ns,
        name=normalized_name,
        source_kind=str(source_kind or "WebhookReceiver").strip(),
        source_name=str(source_name).strip(),
        event_filter_json=_json_clone(event_filter),
        target_workflow_name=str(target_workflow_name).strip(),
        target_workflow_namespace=str(target_workflow_namespace or "default").strip(),
        payload_mapping_json=_json_clone(payload_mapping) or {},
        retry_max_retries=max(0, int(retry_max_retries or 0)),
        retry_backoff_seconds=max(0, int(60 if retry_backoff_seconds is None else retry_backoff_seconds)),
        notifications_on_success=list(notifications_on_success) if notifications_on_success else [],
        notifications_on_failure=list(notifications_on_failure) if notifications_on_failure else [],
        enabled=bool(enabled),
    )
    with db_session() as session:
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise ValueError(f"Trigger '{name}' already exists in namespace '{namespace}'") from exc
        return row.to_dict()


def update_workflow_trigger(
    namespace: str,
    name: str,
    source_kind: str | None = None,
    source_name: str | None = None,
    event_filter: dict[str, Any] | None = None,
    target_workflow_name: str | None = None,
    target_workflow_namespace: str | None = None,
    payload_mapping: dict[str, str] | None = None,
    retry_max_retries: int | None = None,
    retry_backoff_seconds: int | None = None,
    notifications_on_success: list[str] | None = None,
    notifications_on_failure: list[str] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    with db_session() as session:
        row = (
            session.query(WorkflowTriggerRow)
            .filter(WorkflowTriggerRow.namespace == normalized_ns, WorkflowTriggerRow.name == normalized_name)
            .one_or_none()
        )
        if row is None:
            raise ValueError(f"Trigger '{name}' not found in namespace '{namespace}'")
        if source_kind is not None:
            row.source_kind = str(source_kind).strip()
        if source_name is not None:
            row.source_name = str(source_name).strip()
        if event_filter is not None:
            row.event_filter_json = _json_clone(event_filter)
        if target_workflow_name is not None:
            row.target_workflow_name = str(target_workflow_name).strip()
        if target_workflow_namespace is not None:
            row.target_workflow_namespace = str(target_workflow_namespace).strip()
        if payload_mapping is not None:
            row.payload_mapping_json = _json_clone(payload_mapping) or {}
        if retry_max_retries is not None:
            row.retry_max_retries = max(0, int(retry_max_retries))
        if retry_backoff_seconds is not None:
            row.retry_backoff_seconds = max(0, int(retry_backoff_seconds))
        if notifications_on_success is not None:
            row.notifications_on_success = list(notifications_on_success)
        if notifications_on_failure is not None:
            row.notifications_on_failure = list(notifications_on_failure)
        if enabled is not None:
            row.enabled = bool(enabled)
        row.updated_at = utc_now()
        return row.to_dict()


def delete_workflow_trigger(namespace: str, name: str) -> bool:
    normalized_ns = str(namespace or "default").strip() or "default"
    normalized_name = str(name or "").strip()
    with db_session() as session:
        row = (
            session.query(WorkflowTriggerRow)
            .filter(WorkflowTriggerRow.namespace == normalized_ns, WorkflowTriggerRow.name == normalized_name)
            .one_or_none()
        )
        if row is None:
            return False
        session.delete(row)
        return True


def record_trigger_execution(
    trigger_namespace: str,
    trigger_name: str,
    webhook_name: str,
    event_id: str,
    workflow_name: str,
    workflow_namespace: str,
    payload_json: dict[str, Any] | None = None,
    status: str = "pending",
    error_message: str | None = None,
    attempt_count: int = 0,
) -> dict[str, Any]:
    normalized_ns = str(trigger_namespace or "default").strip() or "default"
    row = TriggerExecutionRow(
        trigger_namespace=normalized_ns,
        trigger_name=str(trigger_name or "").strip(),
        webhook_name=str(webhook_name or "").strip(),
        event_id=str(event_id or "").strip(),
        workflow_name=str(workflow_name or "").strip(),
        workflow_namespace=str(workflow_namespace or "default").strip(),
        payload_json=_json_clone(payload_json),
        status=str(status or "pending").strip(),
        error_message=error_message,
        attempt_count=max(0, int(attempt_count or 0)),
    )
    with db_session() as session:
        session.add(row)
        session.flush()
        return row.to_dict()


def list_trigger_executions(
    trigger_namespace: str,
    trigger_name: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    normalized_ns = str(trigger_namespace or "default").strip() or "default"
    with db_session() as session:
        query = session.query(TriggerExecutionRow).filter(TriggerExecutionRow.trigger_namespace == normalized_ns)
        if trigger_name:
            query = query.filter(TriggerExecutionRow.trigger_name == str(trigger_name).strip())
        rows = (
            query.order_by(TriggerExecutionRow.created_at.desc())
            .limit(max(1, int(limit)))
            .offset(max(0, int(offset)))
            .all()
        )
        return [row.to_dict() for row in rows]
