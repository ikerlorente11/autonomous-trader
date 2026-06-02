"""Fallback OHLCV source — Twelve Data.

Implements the same ``MarketDataProvider`` protocol as the yfinance provider so the
orchestrator can swap them without touching analysis. Built for the free tier:
symbols are comma-batched into a single ``/time_series`` call (fewer of the 800
daily requests), and HTTP 429 / quota responses raise ``RateLimitError`` and are
retried with exponential backoff before giving up. The API key comes from
``TWELVE_DATA_API_KEY``; the batch size from ``TWELVE_DATA_BATCH`` (default 8).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

import httpx

from backend.contracts import OHLCVBar
from backend.data_ingestion.errors import ProviderError, RateLimitError

_NAME = "twelve_data"
_BASE_URL = "https://api.twelvedata.com/time_series"
_MAX_RETRIES = 3


def _api_key() -> str:
    key = os.environ.get("TWELVE_DATA_API_KEY")
    if not key:
        raise ProviderError("TWELVE_DATA_API_KEY is not set", provider=_NAME)
    return key


def _redact(text: str, key: str) -> str:
    """Strip the API key out of any string before it can reach a log/DB/response.

    httpx exception messages (and any URL echo) embed the full request URL, which
    carries ``apikey=<secret>`` in the query string."""
    return text.replace(key, "***") if key else text


def _batch_size() -> int:
    return int(os.environ.get("TWELVE_DATA_BATCH", "8"))


def _to_decimal(value: object) -> Decimal | None:
    try:
        if value is None:
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_datetime(raw: str) -> dt.datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if " " in raw else "%Y-%m-%d"
    return dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)


def _values_to_bars(symbol: str, values: list[dict[str, str]]) -> list[OHLCVBar]:
    bars: list[OHLCVBar] = []
    for v in values:
        open_ = _to_decimal(v.get("open"))
        high = _to_decimal(v.get("high"))
        low = _to_decimal(v.get("low"))
        close = _to_decimal(v.get("close"))
        if None in (open_, high, low, close):
            continue
        volume = v.get("volume")
        bars.append(
            OHLCVBar(
                symbol=symbol,
                ts=_parse_datetime(v["datetime"]),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=int(float(volume)) if volume else 0,
                adj_close=close,
            )
        )
    bars.sort(key=lambda b: b.ts)
    return bars


class TwelveDataProvider:
    """``MarketDataProvider`` backed by Twelve Data (free-tier aware)."""

    name = _NAME

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def fetch_daily_bars(
        self, symbols: Sequence[str], start: dt.date, end: dt.date
    ) -> Mapping[str, list[OHLCVBar]]:
        if not symbols:
            return {}
        tickers = list(dict.fromkeys(symbols))
        key = _api_key()
        size = _batch_size()
        out: dict[str, list[OHLCVBar]] = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for i in range(0, len(tickers), size):
                chunk = tickers[i : i + size]
                payload = await self._request(client, chunk, start, end, key)
                out.update(self._unpack(chunk, payload))
        return out

    async def fetch_latest_price(
        self, symbols: Sequence[str]
    ) -> Mapping[str, Decimal]:
        end = dt.date.today()
        start = end - dt.timedelta(days=7)
        bars = await self.fetch_daily_bars(symbols, start, end)
        return {symbol: rows[-1].close for symbol, rows in bars.items() if rows}

    async def get_available_symbols(self) -> list[str]:
        return []

    async def _request(
        self,
        client: httpx.AsyncClient,
        chunk: Sequence[str],
        start: dt.date,
        end: dt.date,
        key: str,
    ) -> dict[str, object]:
        params = {
            "symbol": ",".join(chunk),
            "interval": "1day",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "apikey": key,
            "format": "JSON",
            "outputsize": "5000",
        }
        delay = 1.0
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.get(_BASE_URL, params=params)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", delay))
                    if attempt == _MAX_RETRIES - 1:
                        raise RateLimitError(
                            "twelve_data rate limit exhausted",
                            provider=_NAME,
                            retry_after=retry_after,
                        )
                    await asyncio.sleep(retry_after)
                    delay *= 2
                    continue
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                # `from None`: httpx exceptions embed the apikey-bearing URL; do not
                # let the original chain leak it into tracebacks/logs.
                raise ProviderError(
                    f"twelve_data request failed: {_redact(str(exc), key)}",
                    provider=_NAME,
                ) from None
            data = resp.json()
            self._raise_on_api_error(data, delay, attempt)
            if self._is_rate_limited(data):
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return data
        raise ProviderError("twelve_data retries exhausted", provider=_NAME)

    @staticmethod
    def _is_rate_limited(data: dict[str, object]) -> bool:
        return data.get("status") == "error" and data.get("code") == 429

    def _raise_on_api_error(self, data: dict[str, object], delay: float, attempt: int) -> None:
        if data.get("status") == "error" and data.get("code") != 429:
            raise ProviderError(
                f"twelve_data API error: {data.get('message', 'unknown')}",
                provider=_NAME,
            )
        if self._is_rate_limited(data) and attempt == _MAX_RETRIES - 1:
            raise RateLimitError(
                "twelve_data rate limit exhausted", provider=_NAME, retry_after=delay
            )

    @staticmethod
    def _unpack(
        chunk: Sequence[str], payload: dict[str, object]
    ) -> dict[str, list[OHLCVBar]]:
        out: dict[str, list[OHLCVBar]] = {}
        if "values" in payload:  # single-symbol response shape
            symbol = chunk[0]
            out[symbol] = _values_to_bars(symbol, payload["values"])  # type: ignore[arg-type]
            return out
        for symbol in chunk:
            node = payload.get(symbol)
            if isinstance(node, dict) and node.get("status") != "error":
                values = node.get("values", [])
                out[symbol] = _values_to_bars(symbol, values)  # type: ignore[arg-type]
            else:
                out[symbol] = []
        return out
