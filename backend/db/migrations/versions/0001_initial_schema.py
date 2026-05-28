"""initial schema: tables, hypertables, indexes, compression

Revision ID: 0001
Revises:
Create Date: 2026-05-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRICE = sa.Numeric(18, 6)
MONEY = sa.Numeric(18, 2)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # ----------------------------------------------------------------- #
    # Hypertables
    # ----------------------------------------------------------------- #
    op.create_table(
        "market_bars",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", PRICE, nullable=False),
        sa.Column("high", PRICE, nullable=False),
        sa.Column("low", PRICE, nullable=False),
        sa.Column("close", PRICE, nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("adj_close", PRICE, nullable=False),
        sa.PrimaryKeyConstraint("symbol", "ts", name="pk_market_bars"),
    )
    op.execute(
        "SELECT create_hypertable('market_bars', 'ts', "
        "chunk_time_interval => INTERVAL '1 month')"
    )

    op.create_table(
        "signal_values",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_id", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(18, 8), nullable=False),
        sa.Column("data_completeness", sa.Numeric(5, 4), nullable=True),
        sa.PrimaryKeyConstraint("symbol", "ts", "signal_id", name="pk_signal_values"),
    )
    op.execute(
        "SELECT create_hypertable('signal_values', 'ts', "
        "chunk_time_interval => INTERVAL '1 month')"
    )
    op.create_index(
        "ix_signal_values_symbol_signal_ts",
        "signal_values",
        ["symbol", "signal_id", "ts"],
    )

    op.create_table(
        "macro_series",
        sa.Column("series_id", sa.String(32), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("release_ts", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("series_id", "ts", name="pk_macro_series"),
    )
    op.execute(
        "SELECT create_hypertable('macro_series', 'ts', "
        "chunk_time_interval => INTERVAL '1 year')"
    )

    op.create_table(
        "portfolio_nav",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("equity", MONEY, nullable=False),
        sa.Column("total", MONEY, nullable=False),
        sa.Column("benchmark_value", MONEY, nullable=True),
        sa.PrimaryKeyConstraint("ts", name="pk_portfolio_nav"),
    )
    op.execute(
        "SELECT create_hypertable('portfolio_nav', 'ts', "
        "chunk_time_interval => INTERVAL '1 month')"
    )

    # ----------------------------------------------------------------- #
    # Portfolio / trading
    # ----------------------------------------------------------------- #
    op.create_table(
        "portfolio_positions",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("qty", sa.Numeric(18, 6), nullable=False),
        sa.Column("avg_cost", PRICE, nullable=False),
        sa.Column("current_price", PRICE, nullable=True),
        sa.Column("unrealized_pnl", MONEY, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("symbol", name="pk_portfolio_positions"),
    )

    op.create_table(
        "trade_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("qty", sa.Numeric(18, 6), nullable=False),
        sa.Column("price", PRICE, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("strategy_version", sa.String(64), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_trade_orders"),
    )
    op.execute("CREATE INDEX ix_trade_orders_ts ON trade_orders (ts DESC)")

    op.create_table(
        "algorithm_signals",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Numeric(10, 4), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("indicator_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("realized_return", sa.Numeric(12, 6), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.PrimaryKeyConstraint("symbol", "ts", name="pk_algorithm_signals"),
    )
    op.execute(
        "SELECT create_hypertable('algorithm_signals', 'ts', "
        "chunk_time_interval => INTERVAL '1 month')"
    )
    op.execute(
        "CREATE INDEX ix_algorithm_signals_ts_score "
        "ON algorithm_signals (ts, score DESC)"
    )

    op.create_table(
        "watchlist",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("sector", sa.String(64), nullable=True),
        sa.Column("asset_class", sa.String(32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("symbol", name="pk_watchlist"),
    )

    op.create_table(
        "experiment_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_experiment_runs"),
    )

    # ----------------------------------------------------------------- #
    # Ingestion
    # ----------------------------------------------------------------- #
    op.create_table(
        "fundamentals_quarterly",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("line_items", postgresql.JSONB(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "symbol", "period_end", name="pk_fundamentals_quarterly"
        ),
    )

    op.create_table(
        "earnings_calendar",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("time_of_day", sa.String(8), nullable=True),
        sa.Column(
            "confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.PrimaryKeyConstraint("symbol", "report_date", name="pk_earnings_calendar"),
    )
    op.create_index(
        "ix_earnings_calendar_report_date", "earnings_calendar", ["report_date"]
    )

    op.create_table(
        "earnings_estimates",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("eps_estimate", sa.Numeric(12, 4), nullable=True),
        sa.Column("eps_actual", sa.Numeric(12, 4), nullable=True),
        sa.Column("sue", sa.Numeric(12, 4), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("symbol", "period_end", name="pk_earnings_estimates"),
    )

    op.create_table(
        "analyst_estimates",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("mean_rating", sa.Numeric(6, 3), nullable=True),
        sa.Column("up_count", sa.Integer(), nullable=True),
        sa.Column("down_count", sa.Integer(), nullable=True),
        sa.Column("target_mean", PRICE, nullable=True),
        sa.PrimaryKeyConstraint("symbol", "as_of", name="pk_analyst_estimates"),
    )

    op.create_table(
        "insider_transactions",
        sa.Column("accession_no", sa.String(32), nullable=False),
        sa.Column("txn_seq", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("insider_role", sa.String(64), nullable=True),
        sa.Column("txn_type", sa.String(16), nullable=True),
        sa.Column("shares", sa.Numeric(18, 4), nullable=True),
        sa.Column("price", PRICE, nullable=True),
        sa.Column("filed_ts", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "accession_no", "txn_seq", name="pk_insider_transactions"
        ),
    )
    op.create_index(
        "ix_insider_symbol_filed", "insider_transactions", ["symbol", "filed_ts"]
    )

    op.create_table(
        "sec_filings",
        sa.Column("accession_no", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("form_type", sa.String(16), nullable=False),
        sa.Column("item_codes", postgresql.JSONB(), nullable=True),
        sa.Column("filed_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("polarity", sa.Numeric(6, 3), nullable=True),
        sa.PrimaryKeyConstraint("accession_no", name="pk_sec_filings"),
    )
    op.create_index("ix_sec_filings_symbol_filed", "sec_filings", ["symbol", "filed_ts"])

    op.create_table(
        "news_sentiment",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("article_count", sa.Integer(), nullable=False),
        sa.Column("mean_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("score_zscore", sa.Numeric(8, 4), nullable=True),
        sa.PrimaryKeyConstraint("symbol", "ts", name="pk_news_sentiment"),
    )

    op.create_table(
        "market_sentiment",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vix", sa.Numeric(8, 4), nullable=True),
        sa.Column("vix_term_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("put_call", sa.Numeric(8, 4), nullable=True),
        sa.Column("breadth_rsp_spy", sa.Numeric(8, 4), nullable=True),
        sa.Column("fear_greed", sa.Numeric(8, 4), nullable=True),
        sa.PrimaryKeyConstraint("ts", name="pk_market_sentiment"),
    )

    op.create_table(
        "short_interest",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("short_shares", sa.BigInteger(), nullable=True),
        sa.Column("days_to_cover", sa.Numeric(10, 4), nullable=True),
        sa.PrimaryKeyConstraint(
            "symbol", "settlement_date", name="pk_short_interest"
        ),
    )

    # ----------------------------------------------------------------- #
    # Compression — only market_bars has multi-year history worth compressing
    # ----------------------------------------------------------------- #
    op.execute(
        "ALTER TABLE market_bars SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'symbol', "
        "timescaledb.compress_orderby = 'ts DESC')"
    )
    op.execute("SELECT add_compression_policy('market_bars', INTERVAL '180 days')")


def downgrade() -> None:
    op.execute("SELECT remove_compression_policy('market_bars', if_exists => true)")
    for table in (
        "short_interest",
        "market_sentiment",
        "news_sentiment",
        "sec_filings",
        "insider_transactions",
        "analyst_estimates",
        "earnings_estimates",
        "earnings_calendar",
        "fundamentals_quarterly",
        "experiment_runs",
        "watchlist",
        "algorithm_signals",
        "trade_orders",
        "portfolio_positions",
        "portfolio_nav",
        "macro_series",
        "signal_values",
        "market_bars",
    ):
        op.drop_table(table)
