"""Fundamentals source — Finnhub financials-reported API.

Implements ``FundamentalsProvider``. One async round trip per symbol against the
documented ``/stock/financials-reported`` endpoint (free tier) over ``httpx``; each
quarterly report's income/balance/cash-flow sections are mapped to a small set of
canonical line items via US-GAAP concept tags. Output is a per-symbol list of
``{"period_end": epoch, "revenue": ..., ...}`` for idempotent upsert.

The ``FINNHUB_API_KEY`` is required and read from env only — never logged.

NOTE (needs live verification): the concept→line-item mapping below uses the common
US-GAAP tags, but filers vary (different revenue tags, IFRS, restatements). The map is
deliberately explicit so it can be tuned once validated against real filings; missing
line items are simply omitted (the signals degrade gracefully).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import os
import random
from collections.abc import Mapping, Sequence

import httpx

from backend.data_ingestion.errors import ProviderError

_NAME = "finnhub"
_URL = "https://finnhub.io/api/v1/stock/financials-reported"
_TIMEOUT = httpx.Timeout(30.0)
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Canonical line item -> ordered candidate US-GAAP concept tags (first match wins).
_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap_Revenues",
        "us-gaap_SalesRevenueNet",
    ),
    "net_income": ("us-gaap_NetIncomeLoss", "us-gaap_ProfitLoss"),
    "gross_profit": ("us-gaap_GrossProfit",),
    "equity": (
        "us-gaap_StockholdersEquity",
        "us-gaap_StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "operating_cash_flow": (
        "us-gaap_NetCashProvidedByUsedInOperatingActivities",
        "us-gaap_NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": ("us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",),
}


def _api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        raise ProviderError("FINNHUB_API_KEY is not set", provider=_NAME)
    return key


def _max_retries() -> int:
    return int(os.environ.get("FINNHUB_MAX_RETRIES", "3"))


def _throttle_seconds() -> float:
    return int(os.environ.get("FINNHUB_THROTTLE_MS", "250")) / 1000.0


def _retry_after(resp: httpx.Response, default: float) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return None if math.isnan(value) else float(value)


def _end_date_epoch(entry: dict) -> float | None:
    raw = entry.get("endDate")
    if not isinstance(raw, str):
        return None
    try:
        date = dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None
    return float(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp())


def _scan(sections: Sequence[object], concepts: tuple[str, ...]) -> float | None:
    for section in sections:
        if not isinstance(section, list):
            continue
        for item in section:
            if isinstance(item, dict) and item.get("concept") in concepts:
                value = _num(item.get("value"))
                if value is not None:
                    return value
    return None


def _parse_report(report: object) -> dict[str, float]:
    if not isinstance(report, dict):
        return {}
    sections = [report.get("ic"), report.get("bs"), report.get("cf")]
    out: dict[str, float] = {}
    for key, concepts in _CONCEPTS.items():
        value = _scan(sections, concepts)
        if value is not None:
            out[key] = value
    if "operating_cash_flow" in out and "capex" in out:
        out["free_cash_flow"] = out["operating_cash_flow"] - out["capex"]
    return out


def _parse_statements(payload: object) -> list[dict[str, float]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    out: list[dict[str, float]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        period_end = _end_date_epoch(entry)
        if period_end is None:
            continue
        items = _parse_report(entry.get("report"))
        if not items:
            continue  # nothing usable extracted from this report
        items["period_end"] = period_end
        out.append(items)
    return out


class FinnhubFundamentalsProvider:
    """``FundamentalsProvider`` backed by Finnhub financials-reported (httpx)."""

    name = _NAME

    @staticmethod
    def is_configured() -> bool:
        return bool(os.environ.get("FINNHUB_API_KEY", "").strip())

    async def fetch_quarterly_statements(
        self, symbols: Sequence[str]
    ) -> Mapping[str, list[dict[str, float]]]:
        if not symbols:
            return {}
        key = _api_key()
        tickers = list(dict.fromkeys(symbols))
        out: dict[str, list[dict[str, float]]] = {}
        throttle = _throttle_seconds()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for idx, symbol in enumerate(tickers):
                if idx and throttle > 0:
                    await asyncio.sleep(throttle)
                out[symbol] = await self._fetch_one(client, symbol, key)
        return out

    async def fetch_earnings_calendar(
        self, symbols: Sequence[str]
    ) -> Mapping[str, list[dt.date]]:
        # Deferred: the earnings calendar is a separate (often premium) endpoint and
        # is not needed by the current fundamental signals. Returns empty for now.
        return {symbol: [] for symbol in symbols}

    @staticmethod
    async def _fetch_one(
        client: httpx.AsyncClient, symbol: str, api_key: str
    ) -> list[dict[str, float]]:
        params = {"symbol": symbol, "freq": "quarterly", "token": api_key}
        retries = _max_retries()
        delay = 1.0
        last_detail = "no response"
        for attempt in range(retries + 1):
            try:
                resp = await client.get(_URL, params=params)
            except httpx.HTTPError as exc:
                last_detail = f"transport error: {exc}"
                if attempt == retries:
                    raise ProviderError(
                        f"Finnhub fundamentals fetch failed for {symbol}: {exc}",
                        provider=_NAME,
                    ) from exc
                await asyncio.sleep(delay + random.uniform(0, 0.25))
                delay *= 2
                continue

            if resp.status_code in _RETRY_STATUSES:
                last_detail = f"HTTP {resp.status_code}"
                if attempt == retries:
                    raise ProviderError(
                        f"Finnhub fundamentals fetch failed for {symbol}: HTTP {resp.status_code}",
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
                    f"Finnhub fundamentals fetch failed for {symbol}: HTTP {resp.status_code}",
                    provider=_NAME,
                ) from exc
            return _parse_statements(payload)

        raise ProviderError(
            f"Finnhub fundamentals fetch failed for {symbol}: {last_detail}",
            provider=_NAME,
        )
