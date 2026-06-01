"""Primary OHLCV source — Yahoo Finance chart API.

Implements ``MarketDataProvider``. The ``yfinance`` library's crumb/timezone
preflight calls are reliably 429'd from datacenter/WSL IPs, so this talks to the
public chart endpoint (``/v8/finance/chart``) directly over ``httpx`` with a browser
``User-Agent`` — the one request shape Yahoo still serves anonymously. Each symbol is
one async round trip; output is normalised to midnight-UTC ``OHLCVBar`` DTOs keyed by
session date (idempotent upsert). Correctness checks live in ``validation`` and run
downstream in ``ingest``.

Yahoo still rate-limits flagged IPs even with a browser UA, so each request retries
on 429/5xx with exponential backoff (honouring ``Retry-After``) and rotates through a
small UA pool, and symbols are paced by ``YFINANCE_THROTTLE_MS``. The point is to keep
the *primary* healthy so the metered Twelve Data fallback stays a rare event.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import os
import random
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

import httpx

from backend.contracts import OHLCVBar
from backend.data_ingestion.errors import ProviderError

_NAME = "yfinance"
_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
)
_USER_AGENT = _USER_AGENTS[0]
_TIMEOUT = httpx.Timeout(30.0)
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _max_retries() -> int:
    return int(os.environ.get("YFINANCE_MAX_RETRIES", "3"))


def _throttle_seconds() -> float:
    return int(os.environ.get("YFINANCE_THROTTLE_MS", "250")) / 1000.0


def _retry_after(resp: httpx.Response, default: float) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


def _to_decimal(value: object) -> Decimal | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _session_midnight_utc(epoch: int) -> dt.datetime:
    # Key a daily bar by its UTC calendar date. For US-session daily bars (the watchlist
    # universe) the bar epoch falls mid-UTC-day, so this equals the session date and
    # matches Twelve Data's date-string parsing — both providers upsert on the same
    # (symbol, ts), keeping the fallback idempotent. Revisit if non-US symbols are added.
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
        throttle = _throttle_seconds()
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            for idx, symbol in enumerate(tickers):
                if idx and throttle > 0:
                    await asyncio.sleep(throttle)
                try:
                    out[symbol] = await self._fetch_one(
                        client, symbol, period1, period2, ua_index=idx
                    )
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
        throttle = _throttle_seconds()
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            for idx, symbol in enumerate(tickers):
                if idx and throttle > 0:
                    await asyncio.sleep(throttle)
                try:
                    price = await self._fetch_last_price(client, symbol, ua_index=idx)
                except ProviderError:
                    continue
                if price is not None:
                    out[symbol] = price
        return out

    @staticmethod
    async def _fetch_last_price(
        client: httpx.AsyncClient, symbol: str, *, ua_index: int = 0
    ) -> Decimal | None:
        url = _CHART_URL.format(symbol=symbol)
        params = {"range": "1d", "interval": "1m"}
        retries = _max_retries()
        delay = 1.0
        for attempt in range(retries + 1):
            headers = {"User-Agent": _USER_AGENTS[(ua_index + attempt) % len(_USER_AGENTS)]}
            try:
                resp = await client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                if attempt == retries:
                    raise ProviderError(
                        f"live fetch failed for {symbol}: {exc}", provider=_NAME
                    ) from exc
                await asyncio.sleep(delay + random.uniform(0, 0.25))
                delay *= 2
                continue
            if resp.status_code in _RETRY_STATUSES:
                if attempt == retries:
                    raise ProviderError(
                        f"live fetch failed for {symbol}: HTTP {resp.status_code}",
                        provider=_NAME,
                    )
                await asyncio.sleep(_retry_after(resp, delay) + random.uniform(0, 0.25))
                delay *= 2
                continue
            try:
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderError(
                    f"live fetch failed for {symbol}: {exc}", provider=_NAME
                ) from exc
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
        return None

    async def get_available_symbols(self) -> list[str]:
        return []

    @staticmethod
    async def _fetch_one(
        client: httpx.AsyncClient,
        symbol: str,
        period1: int,
        period2: int,
        *,
        ua_index: int = 0,
    ) -> list[OHLCVBar]:
        url = _CHART_URL.format(symbol=symbol)
        params = {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "div,splits",
        }
        retries = _max_retries()
        delay = 1.0
        last_detail = "no response"
        for attempt in range(retries + 1):
            headers = {"User-Agent": _USER_AGENTS[(ua_index + attempt) % len(_USER_AGENTS)]}
            try:
                resp = await client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_detail = f"transport error: {exc}"
                if attempt == retries:
                    raise ProviderError(
                        f"chart fetch failed for {symbol}: {exc}", provider=_NAME
                    ) from exc
                await asyncio.sleep(delay + random.uniform(0, 0.25))
                delay *= 2
                continue

            if resp.status_code in _RETRY_STATUSES:
                last_detail = f"HTTP {resp.status_code}"
                if attempt == retries:
                    raise ProviderError(
                        f"chart fetch failed for {symbol}: HTTP {resp.status_code}",
                        provider=_NAME,
                    )
                await asyncio.sleep(_retry_after(resp, delay) + random.uniform(0, 0.25))
                delay *= 2
                continue

            try:
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderError(
                    f"chart fetch failed for {symbol}: {exc}", provider=_NAME
                ) from exc

            chart = payload.get("chart") or {}
            if chart.get("error"):
                raise ProviderError(
                    f"chart error for {symbol}: {chart['error']}", provider=_NAME
                )
            results = chart.get("result") or []
            if not results:
                return []
            return _result_to_bars(symbol, results[0])

        raise ProviderError(
            f"chart fetch failed for {symbol}: {last_detail}", provider=_NAME
        )
