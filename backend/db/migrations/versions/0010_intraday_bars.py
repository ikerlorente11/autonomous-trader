"""intraday_bars — intraday OHLCV hypertable for the microtrading section (M1)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRICE = sa.Numeric(18, 6)


def upgrade() -> None:
    # Separate from market_bars: different cadence (5m vs daily), no adj_close, and a
    # short retention window so 5m bars on ~15 symbols don't grow unbounded on the Pi.
    op.create_table(
        "intraday_bars",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", PRICE, nullable=False),
        sa.Column("high", PRICE, nullable=False),
        sa.Column("low", PRICE, nullable=False),
        sa.Column("close", PRICE, nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "ts", name="pk_intraday_bars"),
    )
    # 1-day chunks: intraday volume is high and we drop old chunks, so small chunks keep
    # retention cheap (whole-chunk drops, no row-by-row deletes).
    op.execute(
        "SELECT create_hypertable('intraday_bars', 'ts', "
        "chunk_time_interval => INTERVAL '1 day')"
    )
    op.execute(
        "ALTER TABLE intraday_bars SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'symbol', "
        "timescaledb.compress_orderby = 'ts DESC')"
    )
    op.execute("SELECT add_compression_policy('intraday_bars', INTERVAL '7 days')")
    # Bound disk: forward-test history is what we keep; 120 days spans a calibration
    # window without letting 5m bars accumulate forever (owner can lengthen later).
    op.execute("SELECT add_retention_policy('intraday_bars', INTERVAL '120 days')")


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('intraday_bars', if_exists => true)")
    op.execute("SELECT remove_compression_policy('intraday_bars', if_exists => true)")
    op.drop_table("intraday_bars")
