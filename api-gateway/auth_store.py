"""Local auth and persistence helpers for the API gateway."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from urllib.parse import quote_plus

from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

logger = logging.getLogger("api-gateway.auth-store")

Base = declarative_base()
PASSWORD_CONTEXT = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

ROLE_PRIORITY = {"viewer": 1, "operator": 2, "admin": 3}
DEFAULT_ALLOWED_NAMESPACES = ["default"]
LOGIN_RATE_LIMIT_ATTEMPTS = max(int(os.getenv("AUTH_LOGIN_RATE_LIMIT_ATTEMPTS", "5")), 1)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(int(os.getenv("AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")), 1)
ACCOUNT_LOCKOUT_THRESHOLD = max(int(os.getenv("AUTH_ACCOUNT_LOCKOUT_THRESHOLD", "10")), 1)
ACCOUNT_LOCKOUT_MINUTES = max(int(os.getenv("AUTH_ACCOUNT_LOCKOUT_MINUTES", "15")), 1)

_LOGIN_RATE_LIMIT_LOCK = threading.Lock()
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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

    sqlite_path = os.getenv("DATABASE_SQLITE_PATH", "/tmp/ai-agent-sandbox-gateway.db").strip()
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


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_sub = Column(String(255), nullable=True)
    actor_username = Column(String(128), nullable=True)
    auth_provider = Column(String(64), nullable=True)
    action = Column(String(128), nullable=False, index=True)
    resource_kind = Column(String(64), nullable=True)
    resource_name = Column(String(128), nullable=True)
    resource_namespace = Column(String(128), nullable=True)
    detail_json = Column(JSON, nullable=True)
    ip_address = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)


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


def init_database() -> None:
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


def hash_password(password: str) -> str:
    return PASSWORD_CONTEXT.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return PASSWORD_CONTEXT.verify(password, password_hash)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
        "allowed_namespaces": normalize_namespaces(user.allowed_namespaces),
        "auth_provider": user.auth_provider,
        "is_active": bool(user.is_active),
        "created_at": ensure_utc(user.created_at).isoformat() if user.created_at else None,
        "updated_at": ensure_utc(user.updated_at).isoformat() if user.updated_at else None,
        "last_login_at": ensure_utc(user.last_login_at).isoformat() if user.last_login_at else None,
    }


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
    username = os.getenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "").strip().lower()
    password = os.getenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    if not username or not password:
        return
    if get_user_by_username(username) is not None:
        return

    email = os.getenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "").strip() or None
    display_name = os.getenv("AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME", "Platform Admin").strip() or "Platform Admin"
    allowed_namespaces = normalize_namespaces(os.getenv("AUTH_BOOTSTRAP_ADMIN_NAMESPACES", "*")) or ["*"]

    try:
        create_local_user(
            username=username,
            password=password,
            email=email,
            display_name=display_name,
            role="admin",
            allowed_namespaces=allowed_namespaces,
        )
        logger.info("Bootstrapped local admin account '%s'.", username)
    except ValueError:
        logger.info("Bootstrap admin account '%s' already exists.", username)


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
            "Password must be at least 8 characters and include an uppercase letter, "
            "a lowercase letter, and a digit."
        )
    if role not in ROLE_PRIORITY:
        raise ValueError(f"Unsupported role '{role}'.")
    validated_email = validate_email(email)

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
            allowed_namespaces=normalize_namespaces(allowed_namespaces) or DEFAULT_ALLOWED_NAMESPACES,
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
    normalized_namespaces = normalize_namespaces(allowed_namespaces)
    with db_session() as session:
        user = session.query(User).filter(User.auth_provider == auth_provider, User.external_id == external_id).one_or_none()
        if user is None:
            user = session.query(User).filter(User.username == normalized_username).one_or_none()

        if user is None:
            user = User(
                username=normalized_username,
                email=email,
                display_name=display_name or normalized_username,
                password_hash=None,
                role=role if role in ROLE_PRIORITY else "viewer",
                allowed_namespaces=normalized_namespaces or DEFAULT_ALLOWED_NAMESPACES,
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
        if role is not None:
            if role not in ROLE_PRIORITY:
                raise ValueError(f"Unsupported role '{role}'.")
            user.role = role
        if display_name is not None:
            user.display_name = display_name.strip() or user.display_name
        if is_active is not None:
            user.is_active = bool(is_active)
        if allowed_namespaces is not None:
            user.allowed_namespaces = normalize_namespaces(allowed_namespaces)
        user.updated_at = utc_now()
        session.flush()
        session.refresh(user)
        return serialize_user(user)


def change_user_password(user_id: int, current_password: str, new_password: str) -> dict[str, Any]:
    if not password_meets_policy(new_password):
        raise ValueError(
            "Password must be at least 8 characters and include an uppercase letter, "
            "a lowercase letter, and a digit."
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


def record_failed_login(username: str) -> None:
    normalized_username = username.strip().lower()
    if not normalized_username:
        return
    with db_session() as session:
        user = session.query(User).filter(User.username == normalized_username).one_or_none()
        if user is None:
            return
        user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= ACCOUNT_LOCKOUT_THRESHOLD:
            user.locked_until = utc_now() + timedelta(minutes=ACCOUNT_LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
        user.updated_at = utc_now()


def reset_failed_logins(user_id: int) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = utc_now()
        user.updated_at = utc_now()


def get_active_user_context(user_id: int) -> dict[str, Any] | None:
    with db_session() as session:
        user = session.get(User, user_id)
        if user is None or not user.is_active or is_user_locked(user):
            return None
        return serialize_user(user)


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
    with db_session() as session:
        record = session.get(UserSession, session_id)
        if record is None or record.revoked_at is not None:
            return
        record.revoked_at = utc_now()
        record.last_used_at = utc_now()


def revoke_refresh_token(refresh_token: str) -> None:
    session_id, _separator, _secret = refresh_token.partition(".")
    revoke_session(session_id)


def is_session_active(session_id: str, *, user_id: int | None = None) -> bool:
    if not session_id:
        return False
    with db_session() as session:
        record = session.get(UserSession, session_id)
        expires_at = ensure_utc(record.expires_at) if record is not None else None
        if record is None or record.revoked_at is not None or expires_at is None or expires_at <= utc_now():
            return False
        if user_id is not None and int(record.user_id) != int(user_id):
            return False
        return True


def verify_refresh_session(refresh_token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    session_id, separator, _secret = refresh_token.partition(".")
    if not session_id or not separator:
        raise ValueError("Refresh token format is invalid.")

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
    now = time.time()
    with _LOGIN_RATE_LIMIT_LOCK:
        attempts = [item for item in _LOGIN_ATTEMPTS.get(key, []) if now - item <= LOGIN_RATE_LIMIT_WINDOW_SECONDS]
        _LOGIN_ATTEMPTS[key] = attempts
        return len(attempts) >= LOGIN_RATE_LIMIT_ATTEMPTS


def note_login_attempt(key: str, *, success: bool) -> None:
    with _LOGIN_RATE_LIMIT_LOCK:
        if success:
            _LOGIN_ATTEMPTS.pop(key, None)
            return
        attempts = _LOGIN_ATTEMPTS.setdefault(key, [])
        attempts.append(time.time())


def record_audit_log(
    *,
    action: str,
    actor_sub: str | None,
    actor_username: str | None,
    auth_provider: str | None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    resource_namespace: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    with db_session() as session:
        session.add(
            AuditLog(
                actor_sub=actor_sub,
                actor_username=actor_username,
                auth_provider=auth_provider,
                action=action,
                resource_kind=resource_kind,
                resource_name=resource_name,
                resource_namespace=resource_namespace,
                detail_json=detail or None,
                ip_address=ip_address,
            )
        )
