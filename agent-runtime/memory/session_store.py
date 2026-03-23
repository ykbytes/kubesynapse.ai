from __future__ import annotations

from abc import ABC, abstractmethod
import os
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Iterable

from .session_state import SessionStateSnapshot, utc_now


class SessionStore(ABC):
    @abstractmethod
    def save(self, snapshot: SessionStateSnapshot) -> SessionStateSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get(self, session_id: str) -> SessionStateSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def list_active(self) -> list[SessionStateSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def delete_expired(self) -> int:
        raise NotImplementedError

    def close(self) -> None:
        return None


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._items: dict[str, SessionStateSnapshot] = {}

    def save(self, snapshot: SessionStateSnapshot) -> SessionStateSnapshot:
        existing = self._items.get(snapshot.session_id)
        if existing is not None:
            snapshot.created_at = existing.created_at
        snapshot.updated_at = utc_now()
        self._items[snapshot.session_id] = snapshot.model_copy(deep=True)
        return snapshot

    def get(self, session_id: str) -> SessionStateSnapshot | None:
        snapshot = self._items.get(session_id)
        if snapshot is None:
            return None
        return snapshot.model_copy(deep=True)

    def list_active(self) -> list[SessionStateSnapshot]:
        now = utc_now()
        return [
            item.model_copy(deep=True)
            for item in self._items.values()
            if item.expires_at is None or item.expires_at > now
        ]

    def delete_expired(self) -> int:
        now = utc_now()
        expired = [key for key, value in self._items.items() if value.expires_at is not None and value.expires_at <= now]
        for key in expired:
            self._items.pop(key, None)
        return len(expired)


class SqliteSessionStore(SessionStore):
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._connection = self._connect(db_path)
        self._setup()

    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        resolved = Path(db_path)
        if resolved.parent and str(resolved.parent) not in {"", "."}:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(resolved), check_same_thread=False)

    def _setup(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_sessions_expires_at ON agent_sessions (expires_at)"
            )

    def _load_many(self, rows: Iterable[sqlite3.Row]) -> list[SessionStateSnapshot]:
        snapshots: list[SessionStateSnapshot] = []
        for row in rows:
            payload_json = row[0]
            snapshots.append(SessionStateSnapshot.model_validate_json(payload_json))
        return snapshots

    def save(self, snapshot: SessionStateSnapshot) -> SessionStateSnapshot:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM agent_sessions WHERE session_id = ?",
                (snapshot.session_id,),
            ).fetchone()
            if row is not None:
                existing = SessionStateSnapshot.model_validate_json(row[0])
                snapshot.created_at = existing.created_at
            snapshot.updated_at = utc_now()
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO agent_sessions (session_id, thread_id, status, payload_json, created_at, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        thread_id = excluded.thread_id,
                        status = excluded.status,
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at
                    """,
                    (
                        snapshot.session_id,
                        snapshot.thread_id,
                        snapshot.status,
                        snapshot.model_dump_json(),
                        snapshot.created_at.isoformat(),
                        snapshot.updated_at.isoformat(),
                        snapshot.expires_at.isoformat() if snapshot.expires_at is not None else None,
                    ),
                )
        return snapshot

    def get(self, session_id: str) -> SessionStateSnapshot | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM agent_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionStateSnapshot.model_validate_json(row[0])

    def list_active(self) -> list[SessionStateSnapshot]:
        now = utc_now().isoformat()
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload_json
                FROM agent_sessions
                WHERE expires_at IS NULL OR expires_at > ?
                ORDER BY updated_at DESC
                """,
                (now,),
            ).fetchall()
        return self._load_many(rows)

    def delete_expired(self) -> int:
        now = utc_now().isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM agent_sessions WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            )
            return int(cursor.rowcount or 0)

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def create_session_store() -> SessionStore | None:
    backend = os.getenv("AGENT_SESSION_STORE_BACKEND", "sqlite").strip().lower()
    if backend in {"", "disabled", "none", "off"}:
        return None
    if backend == "memory":
        return InMemorySessionStore()

    db_path = os.getenv("AGENT_SESSION_STORE_PATH", "/app/state/session_state.sqlite").strip() or "/app/state/session_state.sqlite"
    return SqliteSessionStore(db_path)