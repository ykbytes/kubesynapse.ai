"""add claim & dispatch lineage columns to trigger_executions

Revision ID: a1b2c3d4e5f6
Revises: 19419a64c499
Create Date: 2026-06-03 23:30:00.000000

Adds claimed_by, claim_source, claimed_at, dispatch_path, workflow_run_id,
workflow_generation, job_name, session_id, and operator_instance so that
trigger executions track full lifecycle from creation → claim → dispatch → completion.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '19419a64c499'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Claim ownership columns
    op.add_column(
        'trigger_executions',
        sa.Column('claimed_by', sa.String(length=128), nullable=True),
    )
    op.add_column(
        'trigger_executions',
        sa.Column('claim_source', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'trigger_executions',
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Dispatch path tracking
    op.add_column(
        'trigger_executions',
        sa.Column('dispatch_path', sa.String(length=32), nullable=True),
    )

    # Downstream lineage columns
    op.add_column(
        'trigger_executions',
        sa.Column('workflow_run_id', sa.String(length=128), nullable=True),
    )
    op.add_column(
        'trigger_executions',
        sa.Column('workflow_generation', sa.Integer(), nullable=True),
    )
    op.add_column(
        'trigger_executions',
        sa.Column('job_name', sa.String(length=256), nullable=True),
    )
    op.add_column(
        'trigger_executions',
        sa.Column('session_id', sa.String(length=128), nullable=True),
    )
    op.add_column(
        'trigger_executions',
        sa.Column('operator_instance', sa.String(length=128), nullable=True),
    )

    # Deduplication index — prevents duplicate executions for same trigger+event
    op.create_index(
        'ix_trigger_executions_dedup',
        'trigger_executions',
        ['trigger_namespace', 'trigger_name', 'event_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_trigger_executions_dedup', table_name='trigger_executions')
    op.drop_column('trigger_executions', 'operator_instance')
    op.drop_column('trigger_executions', 'session_id')
    op.drop_column('trigger_executions', 'job_name')
    op.drop_column('trigger_executions', 'workflow_generation')
    op.drop_column('trigger_executions', 'workflow_run_id')
    op.drop_column('trigger_executions', 'dispatch_path')
    op.drop_column('trigger_executions', 'claimed_at')
    op.drop_column('trigger_executions', 'claim_source')
    op.drop_column('trigger_executions', 'claimed_by')
