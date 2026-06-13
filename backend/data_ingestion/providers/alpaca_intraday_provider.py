"""Tier-2 intraday source — Alpaca Market Data v2 (free IEX feed).

Implements ``IntradayMarketDataProvider``. The research's recommended fallback between
the keyless yfinance primary and the metered Twelve Data stopgap: a real multi-year
intraday history over an ARM-friendly REST API. The free plan serves the **IEX** feed
only (~2-3% of consolidated volume) — fine for liquid day-trading names, and it doubles
as Phase-2 broker groundwork. Talks to ``data.alpaca.markets/v2/stocks/bars`` over httpx
(no SDK dependency, to stay light on the Pi); credentials via ``ALPACA_API_KEY_ID`` /
``ALPACA_API_SECRET_KEY``. Absent keys → ``configured()`` False and the chain skips it.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import random
from collections.abc import Mapping, Sequence

import httpx

from backend.contracts import IntradayBar
from backend.data_ingestion.errors import ProviderError, RateLimitError
from backend.data_ingestion.providers.yfinance_provider import _to_decimal

_NAME = "alpaca_intraday"
_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
_INTERVAL_MAP = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour"}
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_MAX_PAGES = 20  # defensive bound on pagination for a short lookback window
_PAGE_LIMIT = 10000


def _credentials() -> tuple[str | None, str | None]:
    return (
        os.environ.get("ALPACA_API_KEY_ID"),
        os.environ.get("ALPACA_API_SECRET_KEY"),
    )


def _feed() -> str:
    return os.environ.get("ALPACA_FEED", "iex")


def _timeframe(interval: str) -> str:
    mapped = _INTERVAL_MAP.get(interval)
    if mapped is None:
        raise ProviderError(
            f"unsupported intraday interval {interval!r} for {_NAME}", provider=_NAME
        )
    return mapped


def _parse_ts(raw: str) -> dt.datetime:
    # Alpaca returns RFC3339 in UTC, e.g. "2026-06-12T13:30:00Z".
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def _bar_from_payload(symbol: str, row: dict) -> IntradayBar | None:
    open_ = _to_decimal(row.get("o"))
    high = _to_decimal(row.get("h"))
    low = _to_decimal(row.get("l"))
    close = _to_decimal(row.get("c"))
    volume = row.get("v")
    raw_ts = row.get("t")
    if None in (open_, high, low, close) or volume is None or not raw_ts:
        return None
    return IntradayBar(
        symbol=symbol,
        ts=_parse_ts(raw_ts),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=int(volume),
    )


class AlpacaIntradayProvider:
    """``IntradayMarketDataProvider`` backed by Alpaca Market Data v2 (free IEX feed)."""

    name = _NAME

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def configured(self) -> bool:
        key, secret = _credentials()
        return bool(key and secret)

    async def fetch_intraday_bars(
        self, symbols: Sequence[str], *, interval: str, lookback_days: int
    ) -> Mapping[str, list[IntradayBar]]:
        if not symbols:
            return {}
        key, secret = _credentials()
        if not (key and secret):
            raise ProviderError("ALPACA credentials are not set", provider=_NAME)
        tickers = list(dict.fromkeys(symbols))
        timeframe = _timeframe(interval)
        start = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(1, lookback_days))
        ).replace(microsecond=0)
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        out: dict[str, list[IntradayBar]] = {s: [] for s in tickers}
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            page_token: str | None = None
            for _ in range(_MAX_PAGES):
                payload = await self._request(
                    client, tickers, timeframe, start, page_token
                )
                bars_by_symbol = payload.get("bars") or {}
                for symbol, rows in bars_by_symbol.items():
                    for row in rows:
                        bar = _bar_from_payload(symbol, row)
                        if bar is not None:
                            out.setdefault(symbol, []).append(bar)
                page_token = payload.get("next_page_token")
                if not page_token:
                    break
        for symbol in out:
            out[symbol].sort(key=lambda b: b.ts)
        if all(not rows for rows in out.values()):
            raise ProviderError(
                f"alpaca returned no data for {len(tickers)} symbols "
                f"(timeframe={timeframe}, feed={_feed()})",
                provider=_NAME,
            )
        return out

    async def _request(
        self,
        client: httpx.AsyncClient,
        symbols: Sequence[str],
        timeframe: str,
        start: dt.datetime,
        page_token: str | None,
    ) -> dict[str, object]:
        params: dict[str, str] = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.isoformat(),
            "limit": str(_PAGE_LIMIT),
            "feed": _feed(),
            "adjustment": "raw",
        }
        if page_token:
            params["page_token"] = page_token
        delay = 1.0
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.get(_BARS_URL, params=params)
            except httpx.HTTPError as exc:
                if attempt == _MAX_RETRIES:
                    raise ProviderError(
                        f"alpaca request failed: {exc}", provider=_NAME
                    ) from None
                await asyncio.sleep(delay + random.uniform(0, 0.25))
                delay *= 2
                continue
            if resp.status_code in _RETRY_STATUSES:
                if attempt == _MAX_RETRIES:
                    if resp.status_code == 429:
                        raise RateLimitError(
                            "alpaca rate limit hit", provider=_NAME
                        )
                    raise ProviderError(
                        f"alpaca HTTP {resp.status_code}", provider=_NAME
                    )
                retry_after = float(resp.headers.get("Retry-After", delay))
                await asyncio.sleep(retry_after + random.uniform(0, 0.25))
                delay *= 2
                continue
            try:
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderError(
                    f"alpaca response error: {exc}", provider=_NAME
                ) from None
        raise ProviderError("alpaca retries exhausted", provider=_NAME)
