"""Macro source — FRED (Federal Reserve Economic Data) observations API.

Implements ``MacroProvider``. One async round trip per series against the public
``/fred/series/observations`` endpoint over ``httpx``; output is a list of
``(midnight-UTC ts, Decimal value)`` per series for idempotent upsert into
``macro_series``. Missing observations (FRED encodes them as ``"."``) are dropped.

The ``FRED_API_KEY`` is required and read from the environment only — never logged.
Error messages carry the series id and HTTP status, never the request params, so the
key cannot leak into logs (CLAUDE.md: no secrets in logs).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import random
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

import httpx

from backend.data_ingestion.errors import ProviderError

_NAME = "fred"
_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
_TIMEOUT = httpx.Timeout(30.0)
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise ProviderError("FRED_API_KEY is not set", provider=_NAME)
    return key


def _max_retries() -> int:
    return int(os.environ.get("FRED_MAX_RETRIES", "3"))


def _throttle_seconds() -> float:
    return int(os.environ.get("FRED_THROTTLE_MS", "250")) / 1000.0


def _retry_after(resp: httpx.Response, default: float) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


def _to_decimal(value: object) -> Decimal | None:
    # FRED encodes a missing observation as the string ".".
    if value is None or value == "" or value == ".":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_date(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        d = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)


def _observations_to_series(payload: dict) -> list[tuple[dt.datetime, Decimal]]:
    out: list[tuple[dt.datetime, Decimal]] = []
    for row in payload.get("observations") or []:
        ts = _parse_date(row.get("date"))
        value = _to_decimal(row.get("value"))
        if ts is None or value is None:
            continue
        out.append((ts, value))
    return out


class FredProvider:
    """``MacroProvider`` backed by the FRED observations API (httpx)."""

    name = _NAME

    @staticmethod
    def is_configured() -> bool:
        return bool(os.environ.get("FRED_API_KEY", "").strip())

    async def fetch_series(
        self, series_ids: Sequence[str], start: dt.date, end: dt.date
    ) -> Mapping[str, list[tuple[dt.datetime, Decimal]]]:
        if not series_ids:
            return {}
        key = _api_key()
        ids = list(dict.fromkeys(series_ids))
        out: dict[str, list[tuple[dt.datetime, Decimal]]] = {}
        throttle = _throttle_seconds()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for idx, series_id in enumerate(ids):
                if idx and throttle > 0:
                    await asyncio.sleep(throttle)
                out[series_id] = await self._fetch_one(client, series_id, key, start, end)
        return out

    @staticmethod
    async def _fetch_one(
        client: httpx.AsyncClient,
        series_id: str,
        api_key: str,
        start: dt.date,
        end: dt.date,
    ) -> list[tuple[dt.datetime, Decimal]]:
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        retries = _max_retries()
        delay = 1.0
        last_detail = "no response"
        for attempt in range(retries + 1):
            try:
                resp = await client.get(_BASE_URL, params=params)
            except httpx.HTTPError as exc:
                last_detail = f"transport error: {exc}"
                if attempt == retries:
                    raise ProviderError(
                        f"FRED fetch failed for {series_id}: {exc}", provider=_NAME
                    ) from exc
                await asyncio.sleep(delay + random.uniform(0, 0.25))
                delay *= 2
                continue

            if resp.status_code in _RETRY_STATUSES:
                last_detail = f"HTTP {resp.status_code}"
                if attempt == retries:
                    raise ProviderError(
                        f"FRED fetch failed for {series_id}: HTTP {resp.status_code}",
                        provider=_NAME,
                    )
                await asyncio.sleep(_retry_after(resp, delay) + random.uniform(0, 0.25))
                delay *= 2
                continue

            try:
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                # raise_for_status echoes the request URL (with the api_key) in its
                # message; substitute our own so the key never reaches a log.
                raise ProviderError(
                    f"FRED fetch failed for {series_id}: HTTP {resp.status_code}",
                    provider=_NAME,
                ) from exc
            return _observations_to_series(payload)

        raise ProviderError(
            f"FRED fetch failed for {series_id}: {last_detail}", provider=_NAME
        )
