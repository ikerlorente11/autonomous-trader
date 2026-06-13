"""Primary intraday source — Yahoo Finance chart API (5m/15m bars).

Implements ``IntradayMarketDataProvider``. Same anonymous ``/v8/finance/chart``
endpoint and hardening (browser UA pool, 429/5xx backoff, per-symbol throttle) as the
daily ``YFinanceProvider`` — the helpers are imported, not re-implemented — but driven
by Yahoo's intraday ``range``+``interval`` params instead of ``period1/period2``.

Yahoo only serves a short intraday window anonymously (≈60 days at 5m, ≈7 at 1m); the
job persists every poll so a real history grows forward. Bars keep their true intraday
UTC timestamp (not session-midnight) so a session has many rows per symbol.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import random
from collections.abc import Mapping, Sequence

import httpx

from backend.contracts import IntradayBar
from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.providers.yfinance_provider import (
    _CHART_URL,
    _RETRY_STATUSES,
    _TIMEOUT,
    _USER_AGENTS,
    _max_retries,
    _retry_after,
    _throttle_seconds,
    _to_decimal,
)

_NAME = "yfinance_intraday"
# Yahoo accepts a fixed set of intraday intervals; map lookback_days to the smallest
# range token that covers it (the API rejects arbitrary ranges with intraday intervals).
_RANGE_TOKENS: tuple[tuple[int, str], ...] = (
    (1, "1d"),
    (5, "5d"),
    (30, "1mo"),
    (60, "3mo"),
)


def _range_for(lookback_days: int) -> str:
    for days, token in _RANGE_TOKENS:
        if lookback_days <= days:
            return token
    return _RANGE_TOKENS[-1][1]


def _result_to_intraday(symbol: str, result: dict) -> list[IntradayBar]:
    timestamps = result.get("timestamp") or []
    quote_block = (result.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote_block.get("open") or []
    highs = quote_block.get("high") or []
    lows = quote_block.get("low") or []
    closes = quote_block.get("close") or []
    volumes = quote_block.get("volume") or []

    bars: list[IntradayBar] = []
    for i, epoch in enumerate(timestamps):
        open_ = _to_decimal(opens[i] if i < len(opens) else None)
        high = _to_decimal(highs[i] if i < len(highs) else None)
        low = _to_decimal(lows[i] if i < len(lows) else None)
        close = _to_decimal(closes[i] if i < len(closes) else None)
        volume = volumes[i] if i < len(volumes) else None
        if None in (open_, high, low, close) or volume is None:
            continue
        bars.append(
            IntradayBar(
                symbol=symbol,
                ts=dt.datetime.fromtimestamp(epoch, dt.timezone.utc),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=int(volume),
            )
        )
    return bars


class YFinanceIntradayProvider:
    """``IntradayMarketDataProvider`` backed by the Yahoo chart API (httpx, browser UA)."""

    name = _NAME

    def configured(self) -> bool:
        # Free, keyless — always available (subject to Yahoo rate limits at runtime).
        return True

    async def fetch_intraday_bars(
        self, symbols: Sequence[str], *, interval: str, lookback_days: int
    ) -> Mapping[str, list[IntradayBar]]:
        if not symbols:
            return {}
        tickers = list(dict.fromkeys(symbols))
        range_token = _range_for(lookback_days)
        out: dict[str, list[IntradayBar]] = {}
        errors: list[str] = []
        throttle = _throttle_seconds()
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENTS[0]}
        ) as client:
            for idx, symbol in enumerate(tickers):
                if idx and throttle > 0:
                    await asyncio.sleep(throttle)
                try:
                    out[symbol] = await self._fetch_one(
                        client, symbol, interval, range_token, ua_index=idx
                    )
                except ProviderError as exc:
                    out[symbol] = []
                    errors.append(str(exc))

        if all(not rows for rows in out.values()):
            detail = errors[0] if errors else "no data"
            raise ProviderError(
                f"Yahoo intraday returned no data for {len(tickers)} symbols "
                f"(interval={interval}): {detail}",
                provider=_NAME,
            )
        return out

    @staticmethod
    async def _fetch_one(
        client: httpx.AsyncClient,
        symbol: str,
        interval: str,
        range_token: str,
        *,
        ua_index: int = 0,
    ) -> list[IntradayBar]:
        url = _CHART_URL.format(symbol=symbol)
        params = {"range": range_token, "interval": interval}
        retries = _max_retries()
        delay = 1.0
        for attempt in range(retries + 1):
            headers = {"User-Agent": _USER_AGENTS[(ua_index + attempt) % len(_USER_AGENTS)]}
            try:
                resp = await client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                if attempt == retries:
                    raise ProviderError(
                        f"intraday fetch failed for {symbol}: {exc}", provider=_NAME
                    ) from exc
                await asyncio.sleep(delay + random.uniform(0, 0.25))
                delay *= 2
                continue
            if resp.status_code in _RETRY_STATUSES:
                if attempt == retries:
                    raise ProviderError(
                        f"intraday fetch failed for {symbol}: HTTP {resp.status_code}",
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
                    f"intraday fetch failed for {symbol}: {exc}", provider=_NAME
                ) from exc
            chart = payload.get("chart") or {}
            if chart.get("error"):
                raise ProviderError(
                    f"intraday error for {symbol}: {chart['error']}", provider=_NAME
                )
            results = chart.get("result") or []
            if not results:
                return []
            return _result_to_intraday(symbol, results[0])
        return []
