"""add token breakdown columns

Revision ID: 4c1e9f7b2a30
Revises: f86efc4d2d16
Create Date: 2026-06-01 18:00:00.000000

Adds cache_read_tokens, cache_write_tokens, and reasoning_tokens columns to
``workflow_executions``, ``step_executions``, and ``llm_call_records`` so the
gateway can store the full per-call and per-step token breakdown (not just
prompt + completion). This enables the Execution Observatory to show cache
hit ratio, reasoning overhead, and a more accurate cost roll-up.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c1e9f7b2a30'
down_revision: Union[str, None] = 'f86efc4d2d16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'workflow_executions',
        sa.Column('cache_read_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'workflow_executions',
        sa.Column('cache_write_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'workflow_executions',
        sa.Column('reasoning_tokens', sa.Integer(), nullable=False, server_default='0'),
    )

    op.add_column(
        'step_executions',
        sa.Column('cache_read_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'step_executions',
        sa.Column('cache_write_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'step_executions',
        sa.Column('reasoning_tokens', sa.Integer(), nullable=False, server_default='0'),
    )

    op.add_column(
        'llm_call_records',
        sa.Column('cache_read_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'llm_call_records',
        sa.Column('cache_write_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'llm_call_records',
        sa.Column('reasoning_tokens', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('llm_call_records', 'reasoning_tokens')
    op.drop_column('llm_call_records', 'cache_write_tokens')
    op.drop_column('llm_call_records', 'cache_read_tokens')

    op.drop_column('step_executions', 'reasoning_tokens')
    op.drop_column('step_executions', 'cache_write_tokens')
    op.drop_column('step_executions', 'cache_read_tokens')

    op.drop_column('workflow_executions', 'reasoning_tokens')
    op.drop_column('workflow_executions', 'cache_write_tokens')
    op.drop_column('workflow_executions', 'cache_read_tokens')
