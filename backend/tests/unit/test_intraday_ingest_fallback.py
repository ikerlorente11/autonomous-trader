"""fetch_intraday_with_fallback — per-symbol fallback, unconfigured skip, no DB/network.

Mirrors the daily fallback contract: a later provider is asked only for the symbols the
previous one left empty, and a provider whose key is absent (``configured()`` False) is
dropped from the chain rather than raising."""

from __future__ import annotations

import pytest

from backend.data_ingestion import intraday_ingest
from backend.data_ingestion.errors import ProviderError, RateLimitError

pytestmark = pytest.mark.unit

BAR = ["bar"]  # any truthy bars list; the orchestrator only checks truthiness


class FakeIntradayProvider:
    def __init__(self, name: str, behaviour, *, configured: bool = True) -> None:
        self.name = name
        self.behaviour = behaviour
        self._configured = configured
        self.calls: list[list[str]] = []

    def configured(self) -> bool:
        return self._configured

    async def fetch_intraday_bars(self, symbols, *, interval, lookback_days):
        self.calls.append(list(symbols))
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return {s: (BAR if s in self.behaviour else []) for s in symbols}


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch):
    def _wire(*providers: FakeIntradayProvider):
        monkeypatch.setattr(intraday_ingest, "_provider_chain", lambda: list(providers))
        return providers

    return _wire


async def _fetch(symbols):
    return await intraday_ingest.fetch_intraday_with_fallback(
        symbols, interval="5m", lookback_days=5
    )


async def test_secondary_only_gets_the_gaps(wire) -> None:
    primary = FakeIntradayProvider("yf", {"A", "B"})
    secondary = FakeIntradayProvider("td", {"C", "D"})
    wire(primary, secondary)
    out = await _fetch(["A", "B", "C", "D"])
    assert secondary.calls == [["C", "D"]]
    assert {s for s, v in out.items() if v} == {"A", "B", "C", "D"}


async def test_primary_total_failure_secondary_gets_all(wire) -> None:
    primary = FakeIntradayProvider("yf", ProviderError("yahoo 429"))
    secondary = FakeIntradayProvider("td", {"A", "B", "C"})
    wire(primary, secondary)
    out = await _fetch(["A", "B", "C"])
    assert secondary.calls == [["A", "B", "C"]]
    assert {s for s, v in out.items() if v} == {"A", "B", "C"}


async def test_unconfigured_provider_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    # _provider_chain itself filters on configured(); assert that contract directly.
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    chain = intraday_ingest._provider_chain()
    names = {p.name for p in chain}
    assert "yfinance_intraday" in names
    assert "twelve_data_intraday" not in names  # no key → dropped


async def test_both_fail_reraises_last_error(wire) -> None:
    wire(
        FakeIntradayProvider("yf", ProviderError("yahoo")),
        FakeIntradayProvider("td", RateLimitError("twelve_data per-minute")),
    )
    with pytest.raises(RateLimitError):
        await _fetch(["A", "B"])
