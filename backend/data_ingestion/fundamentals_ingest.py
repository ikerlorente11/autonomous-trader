"""Fundamentals ingestion orchestrator — the fundamentals job's entry point.

Mirrors the macro/news ingest modules: pick a provider (``FUNDAMENTALS_DATA_PROVIDER``),
fetch per-symbol quarterly statements, and upsert idempotently into
``fundamentals_quarterly`` via ``INSERT ... ON CONFLICT (symbol, period_end) DO UPDATE``.
The canonical line items land in the JSONB ``line_items`` column the fundamental signals
read (revenue, net_income, gross_profit, equity, free_cash_flow).
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data_ingestion.protocols import FundamentalsProvider
from backend.data_ingestion.providers.finnhub_fundamentals_provider import (
    FinnhubFundamentalsProvider,
)
from backend.db.models import FundamentalsQuarterly

logger = logging.getLogger(__name__)

_FUNDAMENTALS_PROVIDERS: dict[str, type[FundamentalsProvider]] = {
    "finnhub": FinnhubFundamentalsProvider,
}
_DEFAULT_PROVIDER = "finnhub"


def _provider_name() -> str:
    name = os.environ.get("FUNDAMENTALS_DATA_PROVIDER", _DEFAULT_PROVIDER)
    if name not in _FUNDAMENTALS_PROVIDERS:
        raise ValueError(
            f"unknown FUNDAMENTALS_DATA_PROVIDER={name!r}; "
            f"known: {sorted(_FUNDAMENTALS_PROVIDERS)}"
        )
    return name


def make_fundamentals_provider(name: str | None = None) -> FundamentalsProvider:
    return _FUNDAMENTALS_PROVIDERS[name or _provider_name()]()


def fundamentals_data_configured() -> bool:
    """Whether the selected fundamentals provider has the credentials it needs."""
    provider = _FUNDAMENTALS_PROVIDERS[_provider_name()]
    is_configured = getattr(provider, "is_configured", None)
    return bool(is_configured()) if callable(is_configured) else True


def _to_row(symbol: str, statement: dict[str, float], now: dt.datetime) -> dict[str, object]:
    period_end = dt.datetime.fromtimestamp(
        int(statement["period_end"]), dt.timezone.utc
    ).date()
    line_items = {k: v for k, v in statement.items() if k != "period_end"}
    return {
        "symbol": symbol,
        "period_end": period_end,
        "line_items": line_items,
        "as_of": now,
    }


async def upsert_fundamentals_quarterly(
    session: AsyncSession, symbol: str, statements: Sequence[dict[str, float]]
) -> int:
    """Idempotent write of quarterly statements for one symbol; rows sent.

    A provider may return several reports for the same ``period_end`` (e.g. a 10-Q and
    a later 10-K/amendment). Postgres rejects an ``ON CONFLICT`` batch with duplicate
    constrained values, so collapse to one row per ``period_end``, keeping the most
    complete (most line items)."""
    if not statements:
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    deduped: dict[dt.date, dict[str, object]] = {}
    for statement in statements:
        if "period_end" not in statement:
            continue
        row = _to_row(symbol, statement, now)
        existing = deduped.get(row["period_end"])
        if existing is None or len(row["line_items"]) > len(existing["line_items"]):
            deduped[row["period_end"]] = row
    rows = list(deduped.values())
    if not rows:
        return 0
    stmt = insert(FundamentalsQuarterly).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[FundamentalsQuarterly.symbol, FundamentalsQuarterly.period_end],
        set_={"line_items": stmt.excluded.line_items, "as_of": stmt.excluded.as_of},
    )
    await session.execute(stmt)
    return len(rows)


async def ingest_fundamentals(
    session: AsyncSession, symbols: Sequence[str]
) -> dict[str, int]:
    """Full path: fetch (selected provider) → upsert per symbol. Returns rows/symbol."""
    provider = make_fundamentals_provider()
    fetched = await provider.fetch_quarterly_statements(symbols)
    written: dict[str, int] = {}
    for symbol in symbols:
        written[symbol] = await upsert_fundamentals_quarterly(
            session, symbol, fetched.get(symbol, [])
        )
    await session.commit()
    logger.info(
        "upserted %d fundamentals rows across %d symbols",
        sum(written.values()),
        len(written),
    )
    return written
