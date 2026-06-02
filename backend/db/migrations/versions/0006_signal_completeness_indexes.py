"""algorithm_signals.data_completeness, widen strategy_version, add hot-path indexes

- Adds ``algorithm_signals.data_completeness`` so the ranker's low-coverage gate can be
  applied after signals are reloaded from the DB (it was computed but never persisted).
- Widens ``algorithm_signals.strategy_version`` 48 -> 64 to match ``trade_orders`` (a
  version that fit one table could be truncated/rejected by the other).
- Adds a partial index for the filled-order reads (cash, round-trips, idempotency guard)
  and a ``job_runs(started_at DESC)`` index for the recent-runs health query.
- Re-materializes ``weekly_performance`` on databases that ran 0005 before its
  WITH-NO-DATA cagg was backfilled (heals existing installs).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "algorithm_signals",
        sa.Column("data_completeness", sa.Numeric(5, 4), nullable=True),
    )
    op.alter_column(
        "algorithm_signals",
        "strategy_version",
        type_=sa.String(64),
        existing_type=sa.String(48),
        existing_nullable=True,
    )
    op.create_index(
        "ix_trade_orders_filled",
        "trade_orders",
        ["portfolio_id", "ts"],
        postgresql_where=sa.text("lower(status) = 'filled'"),
    )
    op.create_index("ix_job_runs_started", "job_runs", [sa.text("started_at DESC")])

    # Heal installs that applied 0005 before it backfilled the cagg.
    with op.get_context().autocommit_block():
        op.execute(
            "CALL refresh_continuous_aggregate('weekly_performance', NULL, NULL)"
        )


def downgrade() -> None:
    op.drop_index("ix_job_runs_started", table_name="job_runs")
    op.drop_index("ix_trade_orders_filled", table_name="trade_orders")
    op.alter_column(
        "algorithm_signals",
        "strategy_version",
        type_=sa.String(48),
        existing_type=sa.String(64),
        existing_nullable=True,
    )
    op.drop_column("algorithm_signals", "data_completeness")
