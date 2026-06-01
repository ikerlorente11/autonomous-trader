"""YFinanceProvider against a mocked Yahoo chart API (respx) — no real network."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.providers import yfinance_provider as yf
from backend.data_ingestion.providers.yfinance_provider import YFinanceProvider

pytestmark = pytest.mark.unit

START = dt.date(2026, 5, 28)
END = dt.date(2026, 5, 29)
_EPOCH = int(dt.datetime(2026, 5, 29, tzinfo=dt.timezone.utc).timestamp())


def _chart_payload() -> dict:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [_EPOCH],
                    "indicators": {
                        "quote": [{"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [1000]}],
                        "adjclose": [{"adjclose": [10.5]}],
                    },
                }
            ],
            "error": None,
        }
    }


def _empty_payload() -> dict:
    return {"chart": {"result": [], "error": None}}


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # no real backoff/throttle waits
    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(yf.asyncio, "sleep", _noop)
    monkeypatch.setenv("YFINANCE_THROTTLE_MS", "0")


def _route(respx_mock: respx.MockRouter, symbol: str):
    return respx_mock.get(url__regex=rf".*/chart/{symbol}(\?.*)?$")


async def test_happy_path_returns_bars(respx_mock: respx.MockRouter) -> None:
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(200, json=_chart_payload()))
    out = await YFinanceProvider().fetch_daily_bars(["AAPL"], START, END)
    assert len(out["AAPL"]) == 1
    assert out["AAPL"][0].close == __import__("decimal").Decimal("10.5")


async def test_retries_on_429_then_succeeds(respx_mock: respx.MockRouter) -> None:
    route = _route(respx_mock, "AAPL")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json=_chart_payload()),
    ]
    out = await YFinanceProvider().fetch_daily_bars(["AAPL"], START, END)
    assert route.call_count == 2
    assert len(out["AAPL"]) == 1


async def test_retries_on_5xx_then_succeeds(respx_mock: respx.MockRouter) -> None:
    route = _route(respx_mock, "AAPL")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json=_chart_payload())]
    out = await YFinanceProvider().fetch_daily_bars(["AAPL"], START, END)
    assert route.call_count == 2 and len(out["AAPL"]) == 1


async def test_all_symbols_empty_raises_provider_error(respx_mock: respx.MockRouter) -> None:
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(200, json=_empty_payload()))
    with pytest.raises(ProviderError):
        await YFinanceProvider().fetch_daily_bars(["AAPL"], START, END)


async def test_partial_success_does_not_raise(respx_mock: respx.MockRouter) -> None:
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(200, json=_chart_payload()))
    _route(respx_mock, "MSFT").mock(return_value=httpx.Response(200, json=_empty_payload()))
    out = await YFinanceProvider().fetch_daily_bars(["AAPL", "MSFT"], START, END)
    assert len(out["AAPL"]) == 1
    assert out["MSFT"] == []


async def test_persistent_429_exhausts_retries_and_marks_symbol_empty(
    respx_mock: respx.MockRouter,
) -> None:
    # one symbol always 429 -> its fetch fails; as the only symbol, all-empty -> raises
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(429))
    with pytest.raises(ProviderError):
        await YFinanceProvider().fetch_daily_bars(["AAPL"], START, END)


def _live_payload(price: float) -> dict:
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price}}], "error": None}}


async def test_live_price_retries_on_429_then_succeeds(respx_mock: respx.MockRouter) -> None:
    from decimal import Decimal

    route = _route(respx_mock, "AAPL")
    route.side_effect = [httpx.Response(429), httpx.Response(200, json=_live_payload(123.45))]
    out = await YFinanceProvider().fetch_live_prices(["AAPL"])
    assert route.call_count == 2
    assert out["AAPL"] == Decimal("123.45")


async def test_live_price_swallows_persistent_failure(respx_mock: respx.MockRouter) -> None:
    # live feed is best-effort: a symbol that keeps 429-ing is just omitted, not raised
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(429))
    out = await YFinanceProvider().fetch_live_prices(["AAPL"])
    assert out == {}
