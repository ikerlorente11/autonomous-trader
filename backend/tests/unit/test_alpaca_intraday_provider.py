"""AlpacaIntradayProvider against a mocked Alpaca Market Data v2 API (respx)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import respx

from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.providers import alpaca_intraday_provider as ap
from backend.data_ingestion.providers.alpaca_intraday_provider import (
    AlpacaIntradayProvider,
)

pytestmark = pytest.mark.unit

_BARS_RE = r"https://data\.alpaca\.markets/v2/stocks/bars(\?.*)?$"


def _bar(ts: str, close: float) -> dict:
    return {"t": ts, "o": close, "h": close, "l": close, "c": close, "v": 1000}


@pytest.fixture(autouse=True)
def _creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(ap.asyncio, "sleep", _noop)


def test_configured_requires_both_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    assert AlpacaIntradayProvider().configured() is True
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    assert AlpacaIntradayProvider().configured() is False


async def test_happy_path_parses_bars(respx_mock: respx.MockRouter) -> None:
    payload = {
        "bars": {"AAPL": [_bar("2026-06-12T13:30:00Z", 10.5), _bar("2026-06-12T13:35:00Z", 10.2)]},
        "next_page_token": None,
    }
    respx_mock.get(url__regex=_BARS_RE).mock(return_value=httpx.Response(200, json=payload))
    out = await AlpacaIntradayProvider().fetch_intraday_bars(
        ["AAPL"], interval="5m", lookback_days=5
    )
    bars = out["AAPL"]
    assert len(bars) == 2
    assert bars[0].ts == dt.datetime(2026, 6, 12, 13, 30, tzinfo=dt.timezone.utc)
    assert bars[0].close == Decimal("10.5")


async def test_follows_pagination(respx_mock: respx.MockRouter) -> None:
    page1 = {"bars": {"AAPL": [_bar("2026-06-12T13:30:00Z", 10.0)]}, "next_page_token": "tok"}
    page2 = {"bars": {"AAPL": [_bar("2026-06-12T13:35:00Z", 11.0)]}, "next_page_token": None}
    respx_mock.get(url__regex=_BARS_RE).mock(
        side_effect=[httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
    )
    out = await AlpacaIntradayProvider().fetch_intraday_bars(
        ["AAPL"], interval="5m", lookback_days=5
    )
    assert [b.close for b in out["AAPL"]] == [Decimal("10.0"), Decimal("11.0")]


async def test_unconfigured_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    with pytest.raises(ProviderError):
        await AlpacaIntradayProvider().fetch_intraday_bars(
            ["AAPL"], interval="5m", lookback_days=5
        )


async def test_all_empty_raises(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(url__regex=_BARS_RE).mock(
        return_value=httpx.Response(200, json={"bars": {}, "next_page_token": None})
    )
    with pytest.raises(ProviderError):
        await AlpacaIntradayProvider().fetch_intraday_bars(
            ["AAPL"], interval="5m", lookback_days=5
        )


async def test_unsupported_interval_raises() -> None:
    with pytest.raises(ProviderError):
        await AlpacaIntradayProvider().fetch_intraday_bars(
            ["AAPL"], interval="3m", lookback_days=5
        )
