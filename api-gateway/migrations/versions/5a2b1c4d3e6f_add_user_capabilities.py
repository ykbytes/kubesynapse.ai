"""add user capabilities

Revision ID: 5a2b1c4d3e6f
Revises: 19419a64c499
Create Date: 2026-06-14 12:00:00.000000

Adds a JSON `capabilities` column on `users` so admins can grant
least-privilege per-user flags (e.g. `runtime:logs`) without changing
the user's role. The column defaults to an empty object so existing
roles continue to behave as before.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a2b1c4d3e6f'
down_revision: Union[str, None] = '19419a64c499'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('capabilities', sa.JSON(), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('users', 'capabilities')
