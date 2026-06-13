"""YFinanceIntradayProvider against a mocked Yahoo chart API (respx) — no real network."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import respx

from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.providers import yfinance_intraday_provider as yi
from backend.data_ingestion.providers.yfinance_intraday_provider import (
    YFinanceIntradayProvider,
    _range_for,
)

pytestmark = pytest.mark.unit

_T0 = int(dt.datetime(2026, 6, 12, 13, 30, tzinfo=dt.timezone.utc).timestamp())
_T1 = _T0 + 300  # next 5-minute bar


def _chart_payload() -> dict:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [_T0, _T1],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.0, 10.5],
                                "high": [11.0, 10.8],
                                "low": [9.5, 10.1],
                                "close": [10.5, 10.2],
                                "volume": [1000, 800],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(yi.asyncio, "sleep", _noop)
    monkeypatch.setenv("YFINANCE_THROTTLE_MS", "0")


def _route(respx_mock: respx.MockRouter, symbol: str):
    return respx_mock.get(url__regex=rf".*/chart/{symbol}(\?.*)?$")


@pytest.mark.parametrize(
    ("lookback", "token"),
    [(1, "1d"), (5, "5d"), (10, "1mo"), (45, "3mo"), (999, "3mo")],
)
def test_range_for_maps_lookback_to_token(lookback: int, token: str) -> None:
    assert _range_for(lookback) == token


async def test_happy_path_keeps_true_intraday_timestamps(respx_mock: respx.MockRouter) -> None:
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(200, json=_chart_payload()))
    out = await YFinanceIntradayProvider().fetch_intraday_bars(
        ["AAPL"], interval="5m", lookback_days=5
    )
    bars = out["AAPL"]
    assert len(bars) == 2
    assert bars[0].ts == dt.datetime(2026, 6, 12, 13, 30, tzinfo=dt.timezone.utc)
    assert bars[1].ts == dt.datetime(2026, 6, 12, 13, 35, tzinfo=dt.timezone.utc)
    assert bars[0].close == Decimal("10.5")
    assert not hasattr(bars[0], "adj_close")


async def test_partial_nulls_are_skipped(respx_mock: respx.MockRouter) -> None:
    payload = _chart_payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [10.5, None]
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(200, json=payload))
    out = await YFinanceIntradayProvider().fetch_intraday_bars(
        ["AAPL"], interval="5m", lookback_days=5
    )
    assert len(out["AAPL"]) == 1  # the None-close bar is dropped


async def test_all_empty_raises_provider_error(respx_mock: respx.MockRouter) -> None:
    _route(respx_mock, "AAPL").mock(
        return_value=httpx.Response(200, json={"chart": {"result": [], "error": None}})
    )
    with pytest.raises(ProviderError):
        await YFinanceIntradayProvider().fetch_intraday_bars(
            ["AAPL"], interval="5m", lookback_days=5
        )
