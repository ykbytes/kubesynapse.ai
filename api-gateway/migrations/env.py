"""Alembic migration environment for the KubeSynapse API gateway.

Loads the database URL and SQLAlchemy models from auth_store.py so that
``alembic revision --autogenerate`` detects schema changes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Ensure the api-gateway package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth_store import Base, DATABASE_URL

target_metadata = Base.metadata


def get_url() -> str:
    """Resolve the database URL — prefer env var for containerized runs."""
    return os.getenv("DATABASE_URL", DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL without a live connection."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — uses the actual database connection."""
    url = get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
