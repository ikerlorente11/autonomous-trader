"""continuous aggregates: weekly_performance, monthly_signal_accuracy

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEEKLY_PERFORMANCE = """
CREATE MATERIALIZED VIEW weekly_performance
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '7 days', ts) AS bucket,
       first(total, ts)           AS open_total,
       last(total, ts)            AS close_total,
       first(cash, ts)            AS open_cash,
       last(cash, ts)             AS close_cash,
       first(equity, ts)          AS open_equity,
       last(equity, ts)           AS close_equity,
       last(benchmark_value, ts)  AS close_benchmark
FROM portfolio_nav
GROUP BY bucket
WITH NO DATA
"""

MONTHLY_SIGNAL_ACCURACY = """
CREATE MATERIALIZED VIEW monthly_signal_accuracy
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '30 days', ts) AS bucket,
       count(*)                                            AS signal_count,
       avg(score)                                          AS avg_score,
       avg(CASE WHEN outcome = 'correct' THEN 1.0 ELSE 0.0 END)
           FILTER (WHERE outcome IS NOT NULL)              AS hit_rate
FROM algorithm_signals
GROUP BY bucket
WITH NO DATA
"""


def upgrade() -> None:
    # Continuous-aggregate DDL cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute(WEEKLY_PERFORMANCE)
        op.execute(
            "SELECT add_continuous_aggregate_policy('weekly_performance', "
            "start_offset => INTERVAL '90 days', "
            "end_offset => INTERVAL '1 day', "
            "schedule_interval => INTERVAL '7 days')"
        )
        op.execute(MONTHLY_SIGNAL_ACCURACY)
        op.execute(
            "SELECT add_continuous_aggregate_policy('monthly_signal_accuracy', "
            "start_offset => INTERVAL '180 days', "
            "end_offset => INTERVAL '1 day', "
            "schedule_interval => INTERVAL '30 days')"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS monthly_signal_accuracy")
        op.execute("DROP MATERIALIZED VIEW IF EXISTS weekly_performance")
