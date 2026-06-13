"""portfolios.kind — daily-swing vs microtrading discriminator (M2)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOT NULL with server_default 'daily': every existing portfolio becomes 'daily',
    # so the daily pipeline (which now filters to kind='daily') keeps trading exactly
    # the same set. Micro portfolios are created at runtime with kind='micro' and are
    # traded only by the future intraday jobs — never by the daily pipeline.
    op.add_column(
        "portfolios",
        sa.Column(
            "kind",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'daily'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("portfolios", "kind")
