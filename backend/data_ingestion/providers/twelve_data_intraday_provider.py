"""Fallback intraday source — Twelve Data ``/time_series`` at intraday intervals.

Implements ``IntradayMarketDataProvider``. Reuses the daily provider's credential,
redaction and parsing helpers; only the request shape changes (``interval=5min`` and
``outputsize`` instead of a date range). Free tier is metered (~8 credits/min, ~800/day,
one credit per symbol), so this is asked only for the symbols the keyless yfinance
primary left empty. Absent ``TWELVE_DATA_API_KEY`` → ``configured()`` is False and the
chain skips it (degrade, don't fail)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence

import httpx

from backend.contracts import IntradayBar
from backend.data_ingestion.errors import ProviderError, RateLimitError
from backend.data_ingestion.providers.twelve_data_provider import (
    _BASE_URL,
    _MAX_RETRIES,
    _classify_429,
    _parse_datetime,
    _redact,
    _to_decimal,
)

_NAME = "twelve_data_intraday"
_INTERVAL_MAP = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h"}
# Twelve Data caps a single time_series response; stay under it. ~78 5-min bars/session.
_MAX_OUTPUTSIZE = 5000
_BARS_PER_DAY = 80


def _td_interval(interval: str) -> str:
    mapped = _INTERVAL_MAP.get(interval)
    if mapped is None:
        raise ProviderError(
            f"unsupported intraday interval {interval!r} for {_NAME}", provider=_NAME
        )
    return mapped


def _values_to_intraday(symbol: str, values: list[dict[str, str]]) -> list[IntradayBar]:
    bars: list[IntradayBar] = []
    for v in values:
        open_ = _to_decimal(v.get("open"))
        high = _to_decimal(v.get("high"))
        low = _to_decimal(v.get("low"))
        close = _to_decimal(v.get("close"))
        if None in (open_, high, low, close):
            continue
        volume = v.get("volume")
        bars.append(
            IntradayBar(
                symbol=symbol,
                ts=_parse_datetime(v["datetime"]),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=int(float(volume)) if volume else 0,
            )
        )
    bars.sort(key=lambda b: b.ts)
    return bars


class TwelveDataIntradayProvider:
    """``IntradayMarketDataProvider`` backed by Twelve Data (free-tier aware)."""

    name = _NAME

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def configured(self) -> bool:
        return bool(os.environ.get("TWELVE_DATA_API_KEY"))

    async def fetch_intraday_bars(
        self, symbols: Sequence[str], *, interval: str, lookback_days: int
    ) -> Mapping[str, list[IntradayBar]]:
        if not symbols:
            return {}
        key = os.environ.get("TWELVE_DATA_API_KEY")
        if not key:
            raise ProviderError("TWELVE_DATA_API_KEY is not set", provider=_NAME)
        tickers = list(dict.fromkeys(symbols))
        td_interval = _td_interval(interval)
        outputsize = min(_MAX_OUTPUTSIZE, max(1, lookback_days) * _BARS_PER_DAY)
        out: dict[str, list[IntradayBar]] = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for symbol in tickers:
                payload = await self._request(client, symbol, td_interval, outputsize, key)
                values = payload.get("values")
                out[symbol] = (
                    _values_to_intraday(symbol, values) if isinstance(values, list) else []
                )
        if all(not rows for rows in out.values()):
            raise ProviderError(
                f"twelve_data intraday returned no data for {len(tickers)} symbols",
                provider=_NAME,
            )
        return out

    async def _request(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        td_interval: str,
        outputsize: int,
        key: str,
    ) -> dict[str, object]:
        params = {
            "symbol": symbol,
            "interval": td_interval,
            "apikey": key,
            "format": "JSON",
            "outputsize": str(outputsize),
        }
        delay = 1.0
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.get(_BASE_URL, params=params)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", delay))
                    if attempt == _MAX_RETRIES - 1:
                        raise RateLimitError(
                            f"twelve_data {_classify_429('')}",
                            provider=_NAME,
                            retry_after=retry_after,
                        )
                    await asyncio.sleep(retry_after)
                    delay *= 2
                    continue
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"twelve_data intraday request failed: {_redact(str(exc), key)}",
                    provider=_NAME,
                ) from None
            data = resp.json()
            if data.get("status") == "error":
                if data.get("code") == 429 and attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise ProviderError(
                    f"twelve_data intraday API error: {data.get('message', 'unknown')}",
                    provider=_NAME,
                )
            return data
        raise ProviderError("twelve_data intraday retries exhausted", provider=_NAME)
