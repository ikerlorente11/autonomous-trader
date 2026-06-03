"""News ingestion orchestrator — the news job's entry point.

Mirrors the macro/OHLCV ingest modules: pick a news provider (``NEWS_DATA_PROVIDER``),
fetch a per-symbol daily article count over a recent window, and upsert idempotently
into ``news_sentiment`` via ``INSERT ... ON CONFLICT (symbol, ts) DO UPDATE``. This
slice ingests news *flow* (article counts); ``mean_score`` / ``score_zscore`` are left
for a later polarity source.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data_ingestion.protocols import NewsProvider
from backend.data_ingestion.providers.finnhub_news_provider import FinnhubNewsProvider
from backend.db.models import NewsSentiment

logger = logging.getLogger(__name__)

_UPSERT_CHUNK_ROWS = 1000

_NEWS_PROVIDERS: dict[str, type[NewsProvider]] = {"finnhub": FinnhubNewsProvider}
_DEFAULT_PROVIDER = "finnhub"
_DEFAULT_LOOKBACK_DAYS = 7  # incremental; the upsert overwrites, so re-fetching is free


def news_lookback_days() -> int:
    raw = os.environ.get("NEWS_LOOKBACK_DAYS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_LOOKBACK_DAYS
    return int(raw)


def _provider_name() -> str:
    name = os.environ.get("NEWS_DATA_PROVIDER", _DEFAULT_PROVIDER)
    if name not in _NEWS_PROVIDERS:
        raise ValueError(
            f"unknown NEWS_DATA_PROVIDER={name!r}; known: {sorted(_NEWS_PROVIDERS)}"
        )
    return name


def make_news_provider(name: str | None = None) -> NewsProvider:
    return _NEWS_PROVIDERS[name or _provider_name()]()


def news_data_configured() -> bool:
    """Whether the selected news provider has the credentials it needs to run."""
    provider = _NEWS_PROVIDERS[_provider_name()]
    is_configured = getattr(provider, "is_configured", None)
    return bool(is_configured()) if callable(is_configured) else True


def _to_row(symbol: str, entry: dict[str, float]) -> dict[str, object]:
    ts = dt.datetime.fromtimestamp(int(entry["ts"]), dt.timezone.utc)
    return {"symbol": symbol, "ts": ts, "article_count": int(entry["article_count"])}


async def upsert_news_sentiment(
    session: AsyncSession, symbol: str, entries: Sequence[dict[str, float]]
) -> int:
    """Idempotent write of per-day article counts for one symbol; rows sent."""
    if not entries:
        return 0
    rows = [_to_row(symbol, e) for e in entries]
    for start in range(0, len(rows), _UPSERT_CHUNK_ROWS):
        chunk = rows[start : start + _UPSERT_CHUNK_ROWS]
        stmt = insert(NewsSentiment).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[NewsSentiment.symbol, NewsSentiment.ts],
            set_={"article_count": stmt.excluded.article_count},
        )
        await session.execute(stmt)
    return len(rows)


async def ingest_news_sentiment(
    session: AsyncSession, symbols: Sequence[str], since: dt.datetime
) -> dict[str, int]:
    """Full path: fetch (selected provider) → upsert per symbol. Returns rows/symbol."""
    provider = make_news_provider()
    fetched = await provider.fetch_news_sentiment(symbols, since)
    written: dict[str, int] = {}
    for symbol in symbols:
        written[symbol] = await upsert_news_sentiment(
            session, symbol, fetched.get(symbol, [])
        )
    await session.commit()
    logger.info(
        "upserted %d news rows across %d symbols",
        sum(written.values()),
        len(written),
    )
    return written
