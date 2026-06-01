"""Ingestion orchestrator — the scheduler's entry point.

Wires the pieces together: pick a provider (``MARKET_DATA_PROVIDER``), fetch, validate,
and upsert idempotently. Auto-fallback is per-symbol: the secondary is asked only for
the symbols the primary left empty (or all of them if the primary raised), so a partial
primary outage doesn't dump the whole watchlist onto the metered fallback. Writes use
``INSERT ... ON CONFLICT (symbol, ts) DO UPDATE`` so re-running the same day overwrites
rather than duplicates — the idempotency the brief requires.
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

# asyncpg caps a statement at 32767 bind params; at 8 columns/row, chunk the
# multi-row upsert well below that so large backfills don't overflow.
_UPSERT_CHUNK_ROWS = 1000

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
    """Primary first; the secondary only covers the symbols the primary left empty.

    Per-symbol (not all-or-nothing) so a partial yfinance outage hands the metered
    Twelve Data fallback just the gaps — not the whole watchlist — keeping its free
    credits intact. Re-raise only if nothing at all came back."""
    requested = list(dict.fromkeys(symbols))
    out: dict[str, list[OHLCVBar]] = {}
    remaining = requested
    last_error: ProviderError | None = None
    for name in _provider_order():
        if not remaining:
            break
        provider = make_provider(name)
        try:
            fetched = await provider.fetch_daily_bars(remaining, start, end)
        except ProviderError as exc:
            logger.warning("provider %s failed: %s", name, exc)
            last_error = exc
            continue
        for symbol, bars in fetched.items():
            if bars:
                out[symbol] = bars
        remaining = [s for s in remaining if not out.get(s)]
    if not out and last_error is not None:
        logger.error("all market-data providers failed for %d symbols", len(requested))
        raise last_error
    if remaining:
        logger.warning("no data for %d symbols after fallback: %s",
                       len(remaining), ", ".join(remaining))
    for symbol in requested:
        out.setdefault(symbol, [])
    return out


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
    for start in range(0, len(rows), _UPSERT_CHUNK_ROWS):
        chunk = rows[start : start + _UPSERT_CHUNK_ROWS]
        stmt = insert(MarketBar).values(chunk)
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
