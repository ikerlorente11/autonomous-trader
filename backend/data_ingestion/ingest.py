"""Ingestion orchestrator — the scheduler's entry point.

Wires the pieces together: pick a provider (``MARKET_DATA_PROVIDER``), fetch, validate,
and upsert idempotently. Auto-fallback is single-hop: if the primary raises
``ProviderError`` the secondary is tried exactly once, then the failure is logged and
re-raised. Writes use ``INSERT ... ON CONFLICT (symbol, ts) DO UPDATE`` so re-running
the same day overwrites rather than duplicates — the idempotency the brief requires.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Mapping, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.contracts import OHLCVBar
from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.protocols import MarketDataProvider
from backend.data_ingestion.providers.twelve_data_provider import TwelveDataProvider
from backend.data_ingestion.providers.yfinance_provider import YFinanceProvider
from backend.data_ingestion.validation import ValidationReport, validate_batch
from backend.db.models import MarketBar

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, type[MarketDataProvider]] = {
    "yfinance": YFinanceProvider,
    "twelve_data": TwelveDataProvider,
}
_DEFAULT_ORDER = ("yfinance", "twelve_data")


def _provider_order() -> list[str]:
    primary = os.environ.get("MARKET_DATA_PROVIDER", _DEFAULT_ORDER[0])
    if primary not in _PROVIDERS:
        raise ValueError(
            f"unknown MARKET_DATA_PROVIDER={primary!r}; known: {sorted(_PROVIDERS)}"
        )
    return [primary] + [name for name in _DEFAULT_ORDER if name != primary]


def make_provider(name: str) -> MarketDataProvider:
    return _PROVIDERS[name]()


async def fetch_with_fallback(
    symbols: Sequence[str], start: dt.date, end: dt.date
) -> Mapping[str, list[OHLCVBar]]:
    """Try primary then (once) secondary. Re-raise if both fail."""
    last_error: ProviderError | None = None
    for name in _provider_order():
        provider = make_provider(name)
        try:
            return await provider.fetch_daily_bars(symbols, start, end)
        except ProviderError as exc:
            logger.warning("provider %s failed: %s", name, exc)
            last_error = exc
    assert last_error is not None
    logger.error("all market-data providers failed for %d symbols", len(symbols))
    raise last_error


async def upsert_bars(session: AsyncSession, bars: Sequence[OHLCVBar]) -> int:
    """Idempotent write of OHLCV bars; returns the number of rows sent."""
    if not bars:
        return 0
    rows = [
        {
            "symbol": b.symbol,
            "ts": b.ts,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "adj_close": b.adj_close,
        }
        for b in bars
    ]
    stmt = insert(MarketBar).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[MarketBar.symbol, MarketBar.ts],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "adj_close": stmt.excluded.adj_close,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def ingest_daily_bars(
    session: AsyncSession,
    symbols: Sequence[str],
    start: dt.date,
    end: dt.date,
) -> ValidationReport:
    """Full path: fetch (with fallback) → validate → upsert. Returns the QA report."""
    batch = await fetch_with_fallback(symbols, start, end)
    report = validate_batch(batch, symbols, start, end)
    if report.anomalies:
        logger.warning("flagged %d price anomalies", len(report.anomalies))
    if report.empty_symbols:
        logger.warning("no data for symbols: %s", ", ".join(report.empty_symbols))
    flat = [bar for rows in batch.values() for bar in rows]
    written = await upsert_bars(session, flat)
    await session.commit()
    logger.info("upserted %d bars across %d symbols", written, len(batch))
    return report
