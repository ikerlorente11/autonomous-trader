"""portfolios.strategy_label — per-portfolio strategy version for A/B testing

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: NULL means "base config" (config/strategy.yaml). A non-null value is a
    # label resolving to config/strategies/<label>.yaml, deep-merged onto the base.
    # The daily engine trades each portfolio under its own version.
    op.add_column(
        "portfolios",
        sa.Column("strategy_label", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("portfolios", "strategy_label")
