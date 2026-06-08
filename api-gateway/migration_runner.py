"""Alembic migration runner for the API gateway.

Provides ``run_migrations()`` — called during gateway startup instead
of the previous ``Base.metadata.create_all()`` pattern.  Uses the same
DATABASE_URL as auth_store so it works in all environments (PostgreSQL,
SQLite, memory).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("api-gateway.migrations")


def run_migrations(base=None, engine=None) -> None:
    """Apply all pending Alembic migrations to the gateway database.

    This replaces the old ``Base.metadata.create_all(bind=ENGINE)`` pattern.
    On first boot, Alembic creates the ``alembic_version`` table and applies
    all migrations.  On subsequent boots, only new migrations are applied.

    In SQLite / :memory: environments where Alembic cannot connect,
    falls back to ``create_all()``.

    ``base`` and ``engine`` should be provided by the caller to ensure tables
    are created on the correct database connection.  When omitted they default
    to importing from ``auth_store`` (production path).
    """
    if base is None or engine is None:
        from auth_store import Base as _base, ENGINE as _engine
        base = _base
        engine = _engine

    db_url = os.getenv("DATABASE_URL", "").strip()

    # --- In-memory SQLite: use create_all (no persistent migrations) ---
    if db_url == "sqlite:///:memory:" or (
        db_url.startswith("sqlite") and ":memory:" in db_url
    ):
        logger.info("SQLite in-memory detected — using create_all() fallback.")
        base.metadata.create_all(bind=engine)
        return

    # --- SQLite file: run Alembic (supports persistent migrations) ---
    if db_url.startswith("sqlite") and not db_url.startswith("sqlite:///:memory:"):
        logger.info("Running Alembic migrations against SQLite file.")
        try:
            from alembic.config import Config
            from alembic import command
            from pathlib import Path
            migrations_dir = Path(__file__).resolve().parent / "migrations"
            alembic_cfg = Config()
            alembic_cfg.set_main_option("script_location", str(migrations_dir))
            alembic_cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migrations complete (SQLite).")
            return
        except Exception:
            logger.warning("Alembic failed on SQLite — falling back to create_all().", exc_info=True)
            base.metadata.create_all(bind=engine)
            return

    # --- PostgreSQL: run Alembic (production path) ---
    try:
        from auth_store import DATABASE_URL
        from alembic.config import Config
        from alembic import command
        from pathlib import Path
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", str(migrations_dir))
        alembic_cfg.set_main_option("sqlalchemy.url", db_url or DATABASE_URL)
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations applied successfully.")
    except ImportError:
        logger.warning(
            "Alembic not installed — falling back to create_all(). "
            "Install with: pip install alembic"
        )
        base.metadata.create_all(bind=engine)
    except Exception:
        logger.exception("Alembic migration failed — falling back to create_all().")
        base.metadata.create_all(bind=engine)
