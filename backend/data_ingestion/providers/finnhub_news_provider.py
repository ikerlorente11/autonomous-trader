"""News source — Finnhub company-news API.

Implements ``NewsProvider``. One async round trip per symbol against the documented
``/company-news`` endpoint over ``httpx``; headlines are aggregated into a daily
article count per symbol (the free tier carries no polarity score, so ``mean_score``
is left for a future polarity source — this slice ingests news *flow*). Output is a
list of ``{"ts": epoch_seconds, "article_count": n}`` per symbol for idempotent upsert.

The ``FINNHUB_API_KEY`` is required and read from the environment only — never logged.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import random
from collections.abc import Mapping, Sequence

import httpx

from backend.data_ingestion.errors import ProviderError

logger = logging.getLogger(__name__)

_NAME = "finnhub"
_NEWS_URL = "https://finnhub.io/api/v1/company-news"
_TIMEOUT = httpx.Timeout(30.0)
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        raise ProviderError("FINNHUB_API_KEY is not set", provider=_NAME)
    return key


def _max_retries() -> int:
    return int(os.environ.get("FINNHUB_MAX_RETRIES", "3"))


def _throttle_seconds() -> float:
    # Free tier allows 60 calls/min; 1100 ms ≈ 55/min keeps a full watchlist pass
    # under the rolling window (250 ms = 240/min saturated it and starved the tail
    # of the list with 429s no exponential backoff could recover from).
    return int(os.environ.get("FINNHUB_THROTTLE_MS", "1100")) / 1000.0


def _retry_after(resp: httpx.Response, default: float) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


def _day_epoch_utc(epoch: object) -> int | None:
    if not isinstance(epoch, (int, float)) or isinstance(epoch, bool):
        return None
    date = dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc).date()
    return int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp())


def _counts_by_day(articles: object) -> dict[int, int]:
    counts: dict[int, int] = {}
    if not isinstance(articles, list):
        return counts
    for article in articles:
        if not isinstance(article, dict):
            continue
        day = _day_epoch_utc(article.get("datetime"))
        if day is None:
            continue
        counts[day] = counts.get(day, 0) + 1
    return counts


class FinnhubNewsProvider:
    """``NewsProvider`` backed by the Finnhub company-news API (httpx)."""

    name = _NAME

    @staticmethod
    def is_configured() -> bool:
        return bool(os.environ.get("FINNHUB_API_KEY", "").strip())

    async def fetch_news_sentiment(
        self, symbols: Sequence[str], since: dt.datetime
    ) -> Mapping[str, list[dict[str, float]]]:
        if not symbols:
            return {}
        key = _api_key()
        tickers = list(dict.fromkeys(symbols))
        out: dict[str, list[dict[str, float]]] = {}
        failed: list[str] = []
        throttle = _throttle_seconds()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for idx, symbol in enumerate(tickers):
                if idx and throttle > 0:
                    await asyncio.sleep(throttle)
                # One exhausted symbol must not discard every symbol already
                # fetched — the whole batch used to be thrown away on the first
                # tail-of-list 429, freezing the table for weeks.
                try:
                    out[symbol] = await self._fetch_one(client, symbol, key, since)
                except ProviderError as exc:
                    failed.append(symbol)
                    logger.warning("skipping news for %s: %s", symbol, exc)
        if failed and not out:
            raise ProviderError(
                f"Finnhub news fetch failed for all {len(failed)} symbols",
                provider=_NAME,
            )
        return out

    @staticmethod
    async def _fetch_one(
        client: httpx.AsyncClient, symbol: str, api_key: str, since: dt.datetime
    ) -> list[dict[str, float]]:
        params = {
            "symbol": symbol,
            "from": since.date().isoformat(),
            "to": dt.date.today().isoformat(),
            "token": api_key,
        }
        retries = _max_retries()
        delay = 1.0
        last_detail = "no response"
        for attempt in range(retries + 1):
            try:
                resp = await client.get(_NEWS_URL, params=params)
            except httpx.HTTPError as exc:
                last_detail = f"transport error: {exc}"
                if attempt == retries:
                    raise ProviderError(
                        f"Finnhub news fetch failed for {symbol}: {exc}", provider=_NAME
                    ) from exc
                await asyncio.sleep(delay + random.uniform(0, 0.25))
                delay *= 2
                continue

            if resp.status_code in _RETRY_STATUSES:
                last_detail = f"HTTP {resp.status_code}"
                if attempt == retries:
                    raise ProviderError(
                        f"Finnhub news fetch failed for {symbol}: HTTP {resp.status_code}",
                        provider=_NAME,
                    )
                await asyncio.sleep(_retry_after(resp, delay) + random.uniform(0, 0.25))
                delay *= 2
                continue

            try:
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                # raise_for_status echoes the request URL (with the token) in its
                # message; substitute our own so the token never reaches a log.
                raise ProviderError(
                    f"Finnhub news fetch failed for {symbol}: HTTP {resp.status_code}",
                    provider=_NAME,
                ) from exc
            return [
                {"ts": float(day_epoch), "article_count": float(count)}
                for day_epoch, count in sorted(_counts_by_day(payload).items())
            ]

        raise ProviderError(
            f"Finnhub news fetch failed for {symbol}: {last_detail}", provider=_NAME
        )
