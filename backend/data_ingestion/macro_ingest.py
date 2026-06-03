"""Macro ingestion orchestrator — the macro job's entry point.

Mirrors the OHLCV ``ingest`` module for a different shape: pick a macro provider
(``MACRO_DATA_PROVIDER``), fetch a configurable set of FRED series, and upsert
idempotently into ``macro_series`` via ``INSERT ... ON CONFLICT (series_id, ts) DO
UPDATE``. The series list and lookback are env-configurable (CLAUDE.md: no hardcoded
strategy values); the default basket is a Tier-1 macro-regime set from the synthesis
(yield curve, credit spread, rates, claims, inflation, unemployment, policy rate).
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data_ingestion.protocols import MacroProvider
from backend.data_ingestion.providers.fred_provider import FredProvider
from backend.db.models import MacroSeries

logger = logging.getLogger(__name__)

# asyncpg caps a statement at 32767 bind params; 4 columns/row -> chunk well below.
_UPSERT_CHUNK_ROWS = 1000

_MACRO_PROVIDERS: dict[str, type[MacroProvider]] = {"fred": FredProvider}
_DEFAULT_PROVIDER = "fred"

# Tier-1 macro-regime basket (synthesis §macro). Editable via FRED_SERIES.
_DEFAULT_SERIES = (
    "T10Y2Y",       # 10y–2y term spread (yield-curve inversion)
    "T10Y3M",       # 10y–3m term spread
    "BAMLH0A0HYM2",  # high-yield OAS (credit-stress proxy)
    "DGS10",        # 10y Treasury yield
    "DGS2",         # 2y Treasury yield
    "VIXCLS",       # CBOE VIX (FRED daily)
    "ICSA",         # initial jobless claims
    "CPIAUCSL",     # CPI (all urban, SA)
    "UNRATE",       # unemployment rate
    "FEDFUNDS",     # effective federal funds rate
)
_DEFAULT_LOOKBACK_DAYS = 800  # macro is slow-moving; a long window is cheap (1 row/day)


def macro_series_ids() -> list[str]:
    raw = os.environ.get("FRED_SERIES", "").strip()
    if not raw:
        return list(_DEFAULT_SERIES)
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def macro_lookback_days() -> int:
    raw = os.environ.get("FRED_LOOKBACK_DAYS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_LOOKBACK_DAYS
    return int(raw)


def _provider_name() -> str:
    name = os.environ.get("MACRO_DATA_PROVIDER", _DEFAULT_PROVIDER)
    if name not in _MACRO_PROVIDERS:
        raise ValueError(
            f"unknown MACRO_DATA_PROVIDER={name!r}; known: {sorted(_MACRO_PROVIDERS)}"
        )
    return name


def make_macro_provider(name: str | None = None) -> MacroProvider:
    return _MACRO_PROVIDERS[name or _provider_name()]()


def macro_data_configured() -> bool:
    """Whether the selected macro provider has the credentials it needs to run.

    Lets the job skip cleanly (no_api_key) instead of recording a hard failure when
    an optional provider key is absent."""
    name = _provider_name()
    provider = _MACRO_PROVIDERS[name]
    is_configured = getattr(provider, "is_configured", None)
    return bool(is_configured()) if callable(is_configured) else True


async def upsert_macro_series(
    session: AsyncSession,
    series_id: str,
    observations: Sequence[tuple[dt.datetime, Decimal]],
) -> int:
    """Idempotent write of one macro series; returns the number of rows sent."""
    if not observations:
        return 0
    rows = [
        {"series_id": series_id, "ts": ts, "value": value, "release_ts": None}
        for ts, value in observations
    ]
    for start in range(0, len(rows), _UPSERT_CHUNK_ROWS):
        chunk = rows[start : start + _UPSERT_CHUNK_ROWS]
        stmt = insert(MacroSeries).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[MacroSeries.series_id, MacroSeries.ts],
            set_={"value": stmt.excluded.value, "release_ts": stmt.excluded.release_ts},
        )
        await session.execute(stmt)
    return len(rows)


async def ingest_macro_series(
    session: AsyncSession,
    series_ids: Sequence[str],
    start: dt.date,
    end: dt.date,
) -> dict[str, int]:
    """Full path: fetch (selected provider) → upsert per series. Returns rows/series."""
    provider = make_macro_provider()
    fetched = await provider.fetch_series(series_ids, start, end)
    written: dict[str, int] = {}
    for series_id in series_ids:
        written[series_id] = await upsert_macro_series(
            session, series_id, fetched.get(series_id, [])
        )
    await session.commit()
    logger.info(
        "upserted %d macro rows across %d series",
        sum(written.values()),
        len(written),
    )
    return written
