"""portfolio_positions.high_water_mark — peak price since entry for the trailing stop

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no backfill: the intraday protective-sell job initializes it lazily
    # to max(avg_cost, live_price) on the first check, so open positions need nothing.
    op.add_column(
        "portfolio_positions",
        sa.Column("high_water_mark", sa.Numeric(18, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("portfolio_positions", "high_water_mark")
