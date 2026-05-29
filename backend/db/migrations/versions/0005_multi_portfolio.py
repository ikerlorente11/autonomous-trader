"""multi-portfolio: portfolios + cash_movements, scope trading tables by portfolio

Adds a first-class portfolio entity so the system holds several portfolios, each
with its own budget (modelled as deposit/withdrawal cash movements), positions,
trades and NAV. The single implicit portfolio becomes the seeded ``Cartera 500``;
a second ``Cartera 100K`` is seeded too (both editable afterwards via the API).

The riskiest step is ``portfolio_nav``: it is a TimescaleDB hypertable with a
continuous aggregate (``weekly_performance``) on top. Caggs cannot be altered, so
we drop it, change the hypertable PK to ``(portfolio_id, ts)``, then recreate the
cagg grouped by ``portfolio_id``. ``ts`` stays in the PK (hypertables require the
partition column in every unique index).

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(18, 2)

_SCOPED_TABLES = ("trade_orders", "portfolio_positions", "portfolio_nav")

# weekly_performance recreated with portfolio_id so it never aggregates across
# portfolios. Same columns as 0002, plus the portfolio_id group key.
WEEKLY_PERFORMANCE_V2 = """
CREATE MATERIALIZED VIEW weekly_performance
WITH (timescaledb.continuous) AS
SELECT portfolio_id,
       time_bucket(INTERVAL '7 days', ts) AS bucket,
       first(total, ts)           AS open_total,
       last(total, ts)            AS close_total,
       first(cash, ts)            AS open_cash,
       last(cash, ts)             AS close_cash,
       first(equity, ts)          AS open_equity,
       last(equity, ts)           AS close_equity,
       last(benchmark_value, ts)  AS close_benchmark
FROM portfolio_nav
GROUP BY portfolio_id, bucket
WITH NO DATA
"""

WEEKLY_PERFORMANCE_V1 = """
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

_WEEKLY_POLICY = (
    "SELECT add_continuous_aggregate_policy('weekly_performance', "
    "start_offset => INTERVAL '90 days', "
    "end_offset => INTERVAL '1 day', "
    "schedule_interval => INTERVAL '7 days')"
)


def upgrade() -> None:
    # Drop the dependent cagg before touching the base hypertable's PK.
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS weekly_performance")

    op.create_table(
        "portfolios",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_portfolios"),
        sa.UniqueConstraint("name", name="uq_portfolios_name"),
    )

    op.create_table(
        "cash_movements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_cash_movements"),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name="fk_cash_movements_portfolio",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("amount > 0", name="ck_cash_movements_amount_positive"),
        sa.CheckConstraint(
            "kind IN ('deposit', 'withdrawal')", name="ck_cash_movements_kind"
        ),
    )
    op.create_index(
        "ix_cash_movements_portfolio_ts", "cash_movements", ["portfolio_id", "ts"]
    )

    # Seed the two starting portfolios and their initial budgets.
    op.execute(
        "INSERT INTO portfolios (name, active, created_at) "
        "VALUES ('Cartera 500', true, now()), ('Cartera 100K', true, now())"
    )
    op.execute(
        "INSERT INTO cash_movements (portfolio_id, kind, amount, ts, note) "
        "SELECT id, 'deposit', 500, now(), 'Initial budget' "
        "FROM portfolios WHERE name = 'Cartera 500'"
    )
    op.execute(
        "INSERT INTO cash_movements (portfolio_id, kind, amount, ts, note) "
        "SELECT id, 'deposit', 100000, now(), 'Initial budget' "
        "FROM portfolios WHERE name = 'Cartera 100K'"
    )

    # Add portfolio_id (nullable), backfill existing rows to Cartera 500, lock NOT NULL.
    for table in _SCOPED_TABLES:
        op.add_column(table, sa.Column("portfolio_id", sa.BigInteger(), nullable=True))
        op.execute(
            f"UPDATE {table} SET portfolio_id = "
            "(SELECT id FROM portfolios WHERE name = 'Cartera 500') "
            "WHERE portfolio_id IS NULL"
        )
        op.alter_column(table, "portfolio_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_portfolio",
            table,
            "portfolios",
            ["portfolio_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # Re-key the per-portfolio tables.
    op.drop_constraint("pk_portfolio_positions", "portfolio_positions", type_="primary")
    op.create_primary_key(
        "pk_portfolio_positions", "portfolio_positions", ["portfolio_id", "symbol"]
    )
    op.drop_constraint("pk_portfolio_nav", "portfolio_nav", type_="primary")
    op.create_primary_key("pk_portfolio_nav", "portfolio_nav", ["portfolio_id", "ts"])
    op.create_index(
        "ix_trade_orders_portfolio_ts", "trade_orders", ["portfolio_id", "ts"]
    )

    # Recreate the cagg grouped by portfolio_id.
    with op.get_context().autocommit_block():
        op.execute(WEEKLY_PERFORMANCE_V2)
        op.execute(_WEEKLY_POLICY)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS weekly_performance")

    op.drop_index("ix_trade_orders_portfolio_ts", table_name="trade_orders")
    op.drop_constraint("pk_portfolio_nav", "portfolio_nav", type_="primary")
    op.create_primary_key("pk_portfolio_nav", "portfolio_nav", ["ts"])
    op.drop_constraint("pk_portfolio_positions", "portfolio_positions", type_="primary")
    op.create_primary_key("pk_portfolio_positions", "portfolio_positions", ["symbol"])

    for table in _SCOPED_TABLES:
        op.drop_constraint(f"fk_{table}_portfolio", table, type_="foreignkey")
        op.drop_column(table, "portfolio_id")

    op.drop_index("ix_cash_movements_portfolio_ts", table_name="cash_movements")
    op.drop_table("cash_movements")
    op.drop_table("portfolios")

    with op.get_context().autocommit_block():
        op.execute(WEEKLY_PERFORMANCE_V1)
        op.execute(_WEEKLY_POLICY)
