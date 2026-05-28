"""Data-provider Protocols (the source-swap seam).

Every external data source implements one of these. Analysis logic never imports a
concrete provider — swapping yfinance for Twelve Data, or Finnhub for an RSS
fallback, never touches scoring. ``MarketDataProvider`` is the OHLCV backbone the
brief requires; the synthesis doc (§6) calls for further shapes, so the additional
sub-protocols below cover fundamentals, macro, news, filings and sentiment. All I/O
methods are ``async`` (align with the SQLAlchemy async convention) and accept symbol
*lists* so a 50-symbol watchlist is one batched call, not 50 round trips, on the Pi.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from backend.contracts import OHLCVBar


@runtime_checkable
class MarketDataProvider(Protocol):
    """OHLCV bars — the Tier-1 backbone (yfinance primary, Twelve Data fallback)."""

    async def fetch_daily_bars(
        self, symbols: Sequence[str], start: dt.date, end: dt.date
    ) -> Mapping[str, list[OHLCVBar]]: ...

    async def fetch_latest_price(
        self, symbols: Sequence[str]
    ) -> Mapping[str, Decimal]: ...

    async def get_available_symbols(self) -> list[str]: ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    """Point-in-time quarterly statements + earnings dates/estimates."""

    async def fetch_quarterly_statements(
        self, symbols: Sequence[str]
    ) -> Mapping[str, list[dict[str, float]]]: ...

    async def fetch_earnings_calendar(
        self, symbols: Sequence[str]
    ) -> Mapping[str, list[dt.date]]: ...


@runtime_checkable
class MacroProvider(Protocol):
    """FRED-style macro series (rates, curve, inflation, LEI, claims)."""

    async def fetch_series(
        self, series_ids: Sequence[str], start: dt.date, end: dt.date
    ) -> Mapping[str, list[tuple[dt.datetime, Decimal]]]: ...


@runtime_checkable
class NewsProvider(Protocol):
    """Pre-scored news sentiment aggregated per symbol per day."""

    async def fetch_news_sentiment(
        self, symbols: Sequence[str], since: dt.datetime
    ) -> Mapping[str, list[dict[str, float]]]: ...


@runtime_checkable
class FilingsProvider(Protocol):
    """SEC EDGAR events: Form 4 insider transactions and 8-K material events."""

    async def fetch_filings(
        self, symbols: Sequence[str], since: dt.datetime
    ) -> Mapping[str, list[dict[str, object]]]: ...


@runtime_checkable
class SentimentProvider(Protocol):
    """Market-wide gauges (VIX, put/call, breadth) — not per-symbol."""

    async def fetch_market_sentiment(
        self, asof: dt.date
    ) -> dict[str, Decimal]: ...
