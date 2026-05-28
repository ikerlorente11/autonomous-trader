"""job_runs — per-job lifecycle records for the system-health panel

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job", sa.String(48), nullable=False),
        sa.Column("run_id", sa.String(48), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_job_runs"),
    )
    op.create_index(
        "ix_job_runs_job_started",
        "job_runs",
        ["job", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_job_runs_job_started", table_name="job_runs")
    op.drop_table("job_runs")
