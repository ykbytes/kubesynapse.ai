"""merge user capabilities and trigger claim lineage heads

Revision ID: c7d8e9f0a1b2
Revises: 5a2b1c4d3e6f, a1b2c3d4e5f6
Create Date: 2026-06-20 16:50:00.000000

This is a no-op merge revision. The two parent revisions touch independent
tables and can safely converge without extra schema work.
"""
from typing import Sequence, Union


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, tuple[str, str], None] = (
    "5a2b1c4d3e6f",
    "a1b2c3d4e5f6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
