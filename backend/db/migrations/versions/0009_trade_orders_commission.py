"""trade_orders.commission — per-order commission cost (P10)

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no backfill: existing fills carry NULL (= 0 commission). compute_cash
    # coalesces NULL to 0, so cash for historical portfolios is unchanged. New fills
    # store the modelled cost (COMMISSION_PCT / COMMISSION_PER_ORDER), which then drags
    # NAV without touching contributed capital — making churn visible in the A/B.
    op.add_column(
        "trade_orders",
        sa.Column("commission", sa.Numeric(18, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trade_orders", "commission")
