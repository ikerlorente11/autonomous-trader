"""Primary OHLCV source — Yahoo Finance chart API.

Implements ``MarketDataProvider``. The ``yfinance`` library's crumb/timezone
preflight calls are reliably 429'd from datacenter/WSL IPs, so this talks to the
public chart endpoint (``/v8/finance/chart``) directly over ``httpx`` with a browser
``User-Agent`` — the one request shape Yahoo still serves anonymously. Each symbol is
one async round trip; output is normalised to midnight-UTC ``OHLCVBar`` DTOs keyed by
session date (idempotent upsert). Correctness checks live in ``validation`` and run
downstream in ``ingest``.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

import httpx

from backend.contracts import OHLCVBar
from backend.data_ingestion.errors import ProviderError

_NAME = "yfinance"
_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(30.0)


def _to_decimal(value: object) -> Decimal | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _session_midnight_utc(epoch: int) -> dt.datetime:
    date = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).date()
    return dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc)


def _result_to_bars(symbol: str, result: dict) -> list[OHLCVBar]:
    timestamps = result.get("timestamp") or []
    quote_block = (result.get("indicators", {}).get("quote") or [{}])[0]
    adj_block = (result.get("indicators", {}).get("adjclose") or [{}])[0]
    opens = quote_block.get("open") or []
    highs = quote_block.get("high") or []
    lows = quote_block.get("low") or []
    closes = quote_block.get("close") or []
    volumes = quote_block.get("volume") or []
    adj_closes = adj_block.get("adjclose") or []

    bars: list[OHLCVBar] = []
    for i, epoch in enumerate(timestamps):
        open_ = _to_decimal(opens[i] if i < len(opens) else None)
        high = _to_decimal(highs[i] if i < len(highs) else None)
        low = _to_decimal(lows[i] if i < len(lows) else None)
        close = _to_decimal(closes[i] if i < len(closes) else None)
        volume = volumes[i] if i < len(volumes) else None
        if None in (open_, high, low, close) or volume is None:
            continue
        adj = _to_decimal(adj_closes[i] if i < len(adj_closes) else None) or close
        bars.append(
            OHLCVBar(
                symbol=symbol,
                ts=_session_midnight_utc(epoch),
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
    """``MarketDataProvider`` backed by the Yahoo chart API (httpx, browser UA)."""

    name = _NAME

    async def fetch_daily_bars(
        self, symbols: Sequence[str], start: dt.date, end: dt.date
    ) -> Mapping[str, list[OHLCVBar]]:
        if not symbols:
            return {}
        tickers = list(dict.fromkeys(symbols))
        period1 = int(dt.datetime(start.year, start.month, start.day, tzinfo=dt.timezone.utc).timestamp())
        period2 = int(
            (dt.datetime(end.year, end.month, end.day, tzinfo=dt.timezone.utc)
             + dt.timedelta(days=1)).timestamp()
        )
        out: dict[str, list[OHLCVBar]] = {}
        errors: list[str] = []
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            for symbol in tickers:
                try:
                    out[symbol] = await self._fetch_one(client, symbol, period1, period2)
                except ProviderError as exc:
                    out[symbol] = []
                    errors.append(str(exc))

        if all(not rows for rows in out.values()):
            detail = errors[0] if errors else "no data"
            raise ProviderError(
                f"Yahoo chart API returned no data for {len(tickers)} symbols "
                f"({start.isoformat()}..{end.isoformat()}): {detail}",
                provider=_NAME,
            )
        return out

    async def fetch_latest_price(
        self, symbols: Sequence[str]
    ) -> Mapping[str, Decimal]:
        end = dt.date.today() + dt.timedelta(days=1)
        start = end - dt.timedelta(days=7)
        bars = await self.fetch_daily_bars(symbols, start, end)
        return {symbol: rows[-1].close for symbol, rows in bars.items() if rows}

    async def fetch_live_prices(
        self, symbols: Sequence[str]
    ) -> Mapping[str, Decimal]:
        """Near-real-time last price per symbol (display only, not persisted)."""
        if not symbols:
            return {}
        tickers = list(dict.fromkeys(symbols))
        out: dict[str, Decimal] = {}
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            for symbol in tickers:
                try:
                    price = await self._fetch_last_price(client, symbol)
                except ProviderError:
                    continue
                if price is not None:
                    out[symbol] = price
        return out

    @staticmethod
    async def _fetch_last_price(
        client: httpx.AsyncClient, symbol: str
    ) -> Decimal | None:
        url = _CHART_URL.format(symbol=symbol)
        params = {"range": "1d", "interval": "1m"}
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"live fetch failed for {symbol}: {exc}", provider=_NAME) from exc
        results = (payload.get("chart") or {}).get("result") or []
        if not results:
            return None
        result = results[0]
        price = _to_decimal((result.get("meta") or {}).get("regularMarketPrice"))
        if price is not None:
            return price
        closes = ((result.get("indicators", {}).get("quote") or [{}])[0]).get("close") or []
        for close in reversed(closes):
            value = _to_decimal(close)
            if value is not None:
                return value
        return None

    async def get_available_symbols(self) -> list[str]:
        return []

    @staticmethod
    async def _fetch_one(
        client: httpx.AsyncClient, symbol: str, period1: int, period2: int
    ) -> list[OHLCVBar]:
        url = _CHART_URL.format(symbol=symbol)
        params = {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "div,splits",
        }
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"chart fetch failed for {symbol}: {exc}", provider=_NAME) from exc

        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise ProviderError(f"chart error for {symbol}: {chart['error']}", provider=_NAME)
        results = chart.get("result") or []
        if not results:
            return []
        return _result_to_bars(symbol, results[0])
