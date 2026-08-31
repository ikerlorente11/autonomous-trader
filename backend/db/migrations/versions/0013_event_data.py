"""event data — earnings_events table + point-in-time columns on insider_transactions

Thesis A (docs/research/13-eventos-pead-insider-datos.md §5): backtestable history
for PEAD and Form 4 signals. Plain tables, not hypertables — event-driven volume is
tiny (10^3-10^4 rows) and the natural keys give idempotent upserts.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "earnings_events",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("fiscal_period_end", sa.Date(), nullable=False),
        sa.Column("announce_date", sa.Date(), nullable=False),
        # 'bmo' | 'amc' | 'dmh' | 'unknown' — resolves WHEN the surprise was tradable.
        sa.Column("announce_session", sa.String(8), nullable=False, server_default="unknown"),
        # First session open at which the signal is actionable (lookahead guard §3.2).
        sa.Column("available_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eps_estimate", sa.Numeric(12, 4), nullable=True),
        sa.Column("eps_actual", sa.Numeric(12, 4), nullable=True),
        sa.Column("surprise_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "fiscal_period_end", name="pk_earnings_events"),
    )
    op.create_index(
        "ix_earnings_events_symbol_available",
        "earnings_events",
        ["symbol", "available_ts"],
    )

    # insider_transactions predates the design (0001, always empty): extend in place.
    op.add_column("insider_transactions", sa.Column("issuer_cik", sa.String(16), nullable=True))
    op.add_column("insider_transactions", sa.Column("transaction_date", sa.Date(), nullable=True))
    op.add_column(
        "insider_transactions",
        sa.Column("acceptance_ts", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "insider_transactions", sa.Column("shares_after", sa.Numeric(18, 4), nullable=True)
    )
    op.add_column(
        "insider_transactions",
        sa.Column("is_amendment", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("insider_transactions", sa.Column("source", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("insider_transactions", "source")
    op.drop_column("insider_transactions", "is_amendment")
    op.drop_column("insider_transactions", "shares_after")
    op.drop_column("insider_transactions", "acceptance_ts")
    op.drop_column("insider_transactions", "transaction_date")
    op.drop_column("insider_transactions", "issuer_cik")
    op.drop_index("ix_earnings_events_symbol_available", table_name="earnings_events")
    op.drop_table("earnings_events")
