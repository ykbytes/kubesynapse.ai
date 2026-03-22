"""Initial baseline schema

Revision ID: 001_initial
Revises: None
Create Date: 2026-03-22
"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("namespace", sa.String(128), nullable=False, index=True),
        sa.Column("resource_name", sa.String(128), nullable=False, index=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False, index=True),
        sa.Column("phase", sa.String(64), nullable=False, index=True),
        sa.Column("spec_json", sa.JSON(), nullable=True),
        sa.Column("status_json", sa.JSON(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("step_results_json", sa.JSON(), nullable=True),
        sa.Column("step_states_json", sa.JSON(), nullable=True),
        sa.Column("artifact_path", sa.String(512), nullable=True),
        sa.Column("journal_path", sa.String(512), nullable=True),
        sa.Column("worker_job_name", sa.String(128), nullable=True),
        sa.Column("pending_approval_name", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("namespace", "resource_name", "run_id", name="uq_workflow_runs_identity"),
    )

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("namespace", sa.String(128), nullable=False, index=True),
        sa.Column("resource_name", sa.String(128), nullable=False, index=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False, index=True),
        sa.Column("phase", sa.String(64), nullable=False, index=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("spec_json", sa.JSON(), nullable=True),
        sa.Column("status_json", sa.JSON(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("cases_json", sa.JSON(), nullable=True),
        sa.Column("artifact_path", sa.String(512), nullable=True),
        sa.Column("worker_job_name", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("namespace", "resource_name", "run_id", name="uq_eval_runs_identity"),
    )


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("workflow_runs")
