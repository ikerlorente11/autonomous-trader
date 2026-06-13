"""Intraday ingestion orchestrator — the microtrading data path (M1).

Mirrors ``ingest.py`` but for the ``intraday_bars`` hypertable: a keyless yfinance
primary, then metered fallbacks asked ONLY for the symbols the primary left empty, so
a partial primary outage never dumps the whole sub-universe onto a metered free tier.
Providers whose key is absent are skipped via ``configured()`` (degrade, don't fail).
Writes use ``INSERT ... ON CONFLICT (symbol, ts) DO UPDATE`` so re-polling the same
session overwrites rather than duplicates — the idempotency the brief requires.

The chain is a list: adding Alpaca's free IEX feed (the research's recommended Tier-2,
needs an account/key) is one ``IntradayMarketDataProvider`` entry, no caller changes.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.contracts import IntradayBar
from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.protocols import IntradayMarketDataProvider
from backend.data_ingestion.providers.alpaca_intraday_provider import (
    AlpacaIntradayProvider,
)
from backend.data_ingestion.providers.twelve_data_intraday_provider import (
    TwelveDataIntradayProvider,
)
from backend.data_ingestion.providers.yfinance_intraday_provider import (
    YFinanceIntradayProvider,
)
from backend.db.models import IntradayBar as IntradayBarRow

logger = logging.getLogger(__name__)

# asyncpg caps a statement at 32767 bind params; at 7 columns/row, chunk well below it.
_UPSERT_CHUNK_ROWS = 1000

_DEFAULT_INTERVAL = "5m"
_DEFAULT_LOOKBACK_DAYS = 5
_DEFAULT_MAX_SYMBOLS = 15


def micro_bar_interval() -> str:
    return os.environ.get("MICRO_BAR_INTERVAL", _DEFAULT_INTERVAL)


def micro_lookback_days() -> int:
    try:
        return max(1, int(os.environ.get("MICRO_INTRADAY_LOOKBACK_DAYS", "")))
    except ValueError:
        return _DEFAULT_LOOKBACK_DAYS


def micro_max_symbols() -> int:
    """Cap the polled sub-universe so free-tier credits and Pi I/O stay in budget."""
    try:
        return max(1, int(os.environ.get("MICRO_INTRADAY_MAX_SYMBOLS", "")))
    except ValueError:
        return _DEFAULT_MAX_SYMBOLS


def _provider_chain() -> list[IntradayMarketDataProvider]:
    """Primary first, then fallbacks; unconfigured providers are dropped, not raised.

    Order (research §data): keyless yfinance → Alpaca free IEX feed (needs a key, real
    multi-year history) → metered Twelve Data stopgap."""
    chain: list[IntradayMarketDataProvider] = [
        YFinanceIntradayProvider(),
        AlpacaIntradayProvider(),
        TwelveDataIntradayProvider(),
    ]
    return [p for p in chain if p.configured()]


async def fetch_intraday_with_fallback(
    symbols: Sequence[str], *, interval: str, lookback_days: int
) -> Mapping[str, list[IntradayBar]]:
    """Each provider covers only the symbols the previous one left empty."""
    requested = list(dict.fromkeys(symbols))
    out: dict[str, list[IntradayBar]] = {}
    remaining = requested
    last_error: ProviderError | None = None
    for provider in _provider_chain():
        if not remaining:
            break
        try:
            fetched = await provider.fetch_intraday_bars(
                remaining, interval=interval, lookback_days=lookback_days
            )
        except ProviderError as exc:
            logger.warning("intraday provider %s failed: %s", provider.name, exc)
            last_error = exc
            continue
        for symbol, bars in fetched.items():
            if bars:
                out[symbol] = bars
        remaining = [s for s in remaining if not out.get(s)]
    if not out and last_error is not None:
        logger.error("all intraday providers failed for %d symbols", len(requested))
        raise last_error
    if remaining:
        logger.warning(
            "no intraday data for %d symbols after fallback: %s",
            len(remaining),
            ", ".join(remaining),
        )
    for symbol in requested:
        out.setdefault(symbol, [])
    return out


async def upsert_intraday_bars(
    session: AsyncSession, bars: Sequence[IntradayBar]
) -> int:
    """Idempotent write of intraday bars; returns the number of rows sent."""
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
        }
        for b in bars
    ]
    for start in range(0, len(rows), _UPSERT_CHUNK_ROWS):
        chunk = rows[start : start + _UPSERT_CHUNK_ROWS]
        stmt = insert(IntradayBarRow).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[IntradayBarRow.symbol, IntradayBarRow.ts],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        await session.execute(stmt)
    return len(rows)


async def ingest_intraday_bars(
    session: AsyncSession,
    symbols: Sequence[str],
    *,
    interval: str,
    lookback_days: int,
) -> dict[str, int]:
    """Full path: fetch (with fallback) → upsert. Returns rows-written per symbol.

    Caller commits. No validation layer yet (daily-bar QA assumes session-level bars);
    intraday QA is a later increment — for now garbage-in is bounded by the providers'
    own None-filtering in ``_result_to_intraday`` / ``_values_to_intraday``."""
    batch = await fetch_intraday_with_fallback(
        symbols, interval=interval, lookback_days=lookback_days
    )
    written: dict[str, int] = {}
    for symbol, bars in batch.items():
        written[symbol] = await upsert_intraday_bars(session, bars)
    return written
