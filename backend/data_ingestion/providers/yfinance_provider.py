"""Primary OHLCV source — yfinance.

Implements ``MarketDataProvider``. ``yfinance`` is synchronous and network-bound, so
every call is offloaded with ``asyncio.to_thread`` to honour the async protocol
without blocking the event loop. One batched ``yf.download`` covers the whole symbol
list (one HTTP round trip on the Pi, not N). Output is normalised to UTC ``OHLCVBar``
DTOs; correctness checks live in ``validation`` and run downstream in ``ingest``.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

import pandas as pd
import yfinance as yf

from backend.contracts import OHLCVBar
from backend.data_ingestion.errors import ProviderError

_NAME = "yfinance"
_REQUIRED = ("Open", "High", "Low", "Close", "Adj Close", "Volume")


def _to_decimal(value: object) -> Decimal | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_utc(index_value: pd.Timestamp) -> dt.datetime:
    ts = index_value.to_pydatetime()
    if ts.tzinfo is None:
        return ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc)


def _frame_for_symbol(raw: pd.DataFrame, symbol: str, multi: bool) -> pd.DataFrame | None:
    if multi:
        if symbol not in raw.columns.get_level_values(0):
            return None
        return raw[symbol]
    return raw


def _rows_to_bars(symbol: str, frame: pd.DataFrame) -> list[OHLCVBar]:
    if not set(_REQUIRED).issubset(frame.columns):
        return []
    bars: list[OHLCVBar] = []
    for index_value, row in frame.iterrows():
        close = _to_decimal(row["Close"])
        open_ = _to_decimal(row["Open"])
        high = _to_decimal(row["High"])
        low = _to_decimal(row["Low"])
        volume = row["Volume"]
        if None in (open_, high, low, close) or pd.isna(volume):
            continue
        adj = _to_decimal(row["Adj Close"]) or close
        bars.append(
            OHLCVBar(
                symbol=symbol,
                ts=_to_utc(index_value),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=int(volume),
                adj_close=adj,
            )
        )
    return bars


class YFinanceProvider:
    """``MarketDataProvider`` backed by yfinance (batched, thread-offloaded)."""

    name = _NAME

    async def fetch_daily_bars(
        self, symbols: Sequence[str], start: dt.date, end: dt.date
    ) -> Mapping[str, list[OHLCVBar]]:
        if not symbols:
            return {}
        tickers = list(dict.fromkeys(symbols))
        raw = await asyncio.to_thread(self._download, tickers, start, end)
        if raw is None or raw.empty:
            raise ProviderError(
                f"yfinance returned no data for {len(tickers)} symbols "
                f"({start.isoformat()}..{end.isoformat()})",
                provider=_NAME,
            )
        multi = isinstance(raw.columns, pd.MultiIndex)
        out: dict[str, list[OHLCVBar]] = {}
        for symbol in tickers:
            frame = _frame_for_symbol(raw, symbol, multi)
            out[symbol] = [] if frame is None else _rows_to_bars(symbol, frame)
        return out

    async def fetch_latest_price(
        self, symbols: Sequence[str]
    ) -> Mapping[str, Decimal]:
        end = dt.date.today() + dt.timedelta(days=1)
        start = end - dt.timedelta(days=7)
        bars = await self.fetch_daily_bars(symbols, start, end)
        return {
            symbol: rows[-1].close
            for symbol, rows in bars.items()
            if rows
        }

    async def get_available_symbols(self) -> list[str]:
        return []

    @staticmethod
    def _download(
        tickers: list[str], start: dt.date, end: dt.date
    ) -> pd.DataFrame | None:
        try:
            return yf.download(
                tickers=tickers,
                start=start.isoformat(),
                end=(end + dt.timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                group_by="ticker",
                progress=False,
                threads=False,
            )
        except Exception as exc:  # noqa: BLE001 — opaque yfinance/network failures
            raise ProviderError(f"yfinance download failed: {exc}", provider=_NAME) from exc
