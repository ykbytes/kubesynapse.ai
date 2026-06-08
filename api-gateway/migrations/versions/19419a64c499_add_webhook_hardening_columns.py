"""add webhook hardening columns

Revision ID: 19419a64c499
Revises: 4c1e9f7b2a30
Create Date: 2026-06-03 12:00:00.000000

Adds provider, api_key_enabled, max_concurrent, response_timeout_seconds,
payload_schema, and additional_secrets to webhook_receivers;
adds target_kind, target_agent_name, target_agent_namespace to
workflow_triggers; adds target_kind, agent_name, agent_namespace to
trigger_executions and makes workflow_name/workflow_namespace nullable
so the table supports both workflow and agent targets.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19419a64c499'
down_revision: Union[str, None] = '4c1e9f7b2a30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # webhook_receivers — provider, auth, concurrency, schema
    op.add_column(
        'webhook_receivers',
        sa.Column('additional_secrets', sa.JSON(), nullable=False, server_default='{}'),
    )
    op.add_column(
        'webhook_receivers',
        sa.Column('provider', sa.String(length=32), nullable=False, server_default='generic'),
    )
    op.add_column(
        'webhook_receivers',
        sa.Column('api_key_enabled', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column(
        'webhook_receivers',
        sa.Column('max_concurrent', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'webhook_receivers',
        sa.Column('response_timeout_seconds', sa.Integer(), nullable=False, server_default='30'),
    )
    op.add_column(
        'webhook_receivers',
        sa.Column('payload_schema', sa.JSON(), nullable=True),
    )

    # workflow_triggers — target-kind support (workflow vs agent)
    op.add_column(
        'workflow_triggers',
        sa.Column('target_kind', sa.String(length=16), nullable=False, server_default='workflow'),
    )
    op.add_column(
        'workflow_triggers',
        sa.Column('target_agent_name', sa.String(length=128), nullable=True),
    )
    op.add_column(
        'workflow_triggers',
        sa.Column('target_agent_namespace', sa.String(length=128), nullable=True),
    )

    # trigger_executions — target-kind support
    op.add_column(
        'trigger_executions',
        sa.Column('target_kind', sa.String(length=16), nullable=False, server_default='workflow'),
    )
    op.add_column(
        'trigger_executions',
        sa.Column('agent_name', sa.String(length=128), nullable=True),
    )
    op.add_column(
        'trigger_executions',
        sa.Column('agent_namespace', sa.String(length=128), nullable=True),
    )

    # Make workflow_name / workflow_namespace nullable (agent targets won't populate them)
    op.alter_column(
        'trigger_executions',
        'workflow_name',
        existing_type=sa.String(length=128),
        nullable=True,
    )
    op.alter_column(
        'trigger_executions',
        'workflow_namespace',
        existing_type=sa.String(length=128),
        nullable=True,
    )


def downgrade() -> None:
    # Revert workflow_name / workflow_namespace back to NOT NULL
    op.alter_column(
        'trigger_executions',
        'workflow_namespace',
        existing_type=sa.String(length=128),
        nullable=False,
    )
    op.alter_column(
        'trigger_executions',
        'workflow_name',
        existing_type=sa.String(length=128),
        nullable=False,
    )

    # trigger_executions
    op.drop_column('trigger_executions', 'agent_namespace')
    op.drop_column('trigger_executions', 'agent_name')
    op.drop_column('trigger_executions', 'target_kind')

    # workflow_triggers
    op.drop_column('workflow_triggers', 'target_agent_namespace')
    op.drop_column('workflow_triggers', 'target_agent_name')
    op.drop_column('workflow_triggers', 'target_kind')

    # webhook_receivers
    op.drop_column('webhook_receivers', 'payload_schema')
    op.drop_column('webhook_receivers', 'response_timeout_seconds')
    op.drop_column('webhook_receivers', 'max_concurrent')
    op.drop_column('webhook_receivers', 'api_key_enabled')
    op.drop_column('webhook_receivers', 'provider')
    op.drop_column('webhook_receivers', 'additional_secrets')
