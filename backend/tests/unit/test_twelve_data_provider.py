"""TwelveDataProvider against a mocked Twelve Data API (respx)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import respx

from backend.data_ingestion.errors import ProviderError, RateLimitError
from backend.data_ingestion.providers import twelve_data_provider as td
from backend.data_ingestion.providers.twelve_data_provider import TwelveDataProvider

pytestmark = pytest.mark.unit

START = dt.date(2026, 5, 28)
END = dt.date(2026, 5, 29)
_URL = r"https://api\.twelvedata\.com/time_series.*"


def _values_block() -> dict:
    return {"values": [{"datetime": "2026-05-29", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "1000"}]}


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(td.asyncio, "sleep", _noop)
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")


async def test_single_symbol_unpacks_values(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(url__regex=_URL).mock(return_value=httpx.Response(200, json=_values_block()))
    out = await TwelveDataProvider().fetch_daily_bars(["AAPL"], START, END)
    assert out["AAPL"][0].close == Decimal("10.5")


async def test_multi_symbol_unpacks_per_symbol_nodes(respx_mock: respx.MockRouter) -> None:
    payload = {"AAPL": _values_block(), "MSFT": {"status": "error", "message": "no data"}}
    respx_mock.get(url__regex=_URL).mock(return_value=httpx.Response(200, json=payload))
    out = await TwelveDataProvider().fetch_daily_bars(["AAPL", "MSFT"], START, END)
    assert len(out["AAPL"]) == 1 and out["MSFT"] == []


async def test_credit_pacing_sleeps_between_batches(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[float] = []

    async def _record(seconds: float, *_a, **_k) -> None:
        calls.append(seconds)

    monkeypatch.setattr(td.asyncio, "sleep", _record)
    monkeypatch.setenv("TWELVE_DATA_BATCH", "1")          # one symbol per request -> 2 requests
    monkeypatch.setenv("TWELVE_DATA_CREDITS_PER_MIN", "8")
    respx_mock.get(url__regex=_URL).mock(return_value=httpx.Response(200, json=_values_block()))
    await TwelveDataProvider().fetch_daily_bars(["AAPL", "MSFT"], START, END)
    assert calls == [1 / 8 * 60.0]  # paced once, by the previous chunk's 1 credit


async def test_http_429_classified_as_per_minute(respx_mock: respx.MockRouter) -> None:
    body = {"code": 429, "message": "You have run out of API credits for the current minute"}
    respx_mock.get(url__regex=_URL).mock(return_value=httpx.Response(429, json=body))
    with pytest.raises(RateLimitError) as exc:
        await TwelveDataProvider().fetch_daily_bars(["AAPL"], START, END)
    assert "per-minute" in str(exc.value)


async def test_json_body_429_classified_as_daily(respx_mock: respx.MockRouter) -> None:
    body = {"status": "error", "code": 429, "message": "API credit limit reached for the day"}
    respx_mock.get(url__regex=_URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(RateLimitError) as exc:
        await TwelveDataProvider().fetch_daily_bars(["AAPL"], START, END)
    assert "daily" in str(exc.value)


async def test_api_error_non_429_raises_provider_error(respx_mock: respx.MockRouter) -> None:
    body = {"status": "error", "code": 400, "message": "bad symbol"}
    respx_mock.get(url__regex=_URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(ProviderError) as exc:
        await TwelveDataProvider().fetch_daily_bars(["AAPL"], START, END)
    assert "bad symbol" in str(exc.value)


async def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        await TwelveDataProvider().fetch_daily_bars(["AAPL"], START, END)
