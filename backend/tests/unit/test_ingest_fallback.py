"""fetch_with_fallback orchestration — per-symbol fallback, no DB, no network.

The secondary provider must only be asked for the symbols the primary left empty.
This is the behaviour that keeps the metered Twelve Data quota intact."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.data_ingestion import ingest
from backend.data_ingestion.errors import ProviderError, RateLimitError

pytestmark = pytest.mark.unit

START = dt.date(2026, 5, 28)
END = dt.date(2026, 5, 29)
BAR = ["bar"]  # any truthy "bars" list; fetch_with_fallback only checks truthiness


class FakeProvider:
    def __init__(self, behaviour) -> None:
        self.behaviour = behaviour
        self.calls: list[list[str]] = []

    async def fetch_daily_bars(self, symbols, start, end):
        self.calls.append(list(symbols))
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return {s: (BAR if s in self.behaviour else []) for s in symbols}


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch):
    def _wire(primary, secondary) -> dict[str, FakeProvider]:
        fakes = {"yfinance": FakeProvider(primary), "twelve_data": FakeProvider(secondary)}
        monkeypatch.setattr(ingest, "make_provider", lambda name: fakes[name])
        return fakes

    return _wire


async def test_primary_partial_secondary_only_gets_gaps(wire) -> None:
    fakes = wire(primary={"A", "B"}, secondary={"C", "D"})
    out = await ingest.fetch_with_fallback(["A", "B", "C", "D"], START, END)
    assert fakes["twelve_data"].calls == [["C", "D"]]  # only the gaps
    assert {s for s, v in out.items() if v} == {"A", "B", "C", "D"}


async def test_primary_total_failure_secondary_gets_all(wire) -> None:
    fakes = wire(primary=ProviderError("yahoo 429"), secondary={"A", "B", "C"})
    out = await ingest.fetch_with_fallback(["A", "B", "C"], START, END)
    assert fakes["twelve_data"].calls == [["A", "B", "C"]]
    assert {s for s, v in out.items() if v} == {"A", "B", "C"}


async def test_both_fail_reraises_last_error(wire) -> None:
    wire(primary=ProviderError("yahoo"), secondary=RateLimitError("twelve_data per-minute"))
    with pytest.raises(RateLimitError):
        await ingest.fetch_with_fallback(["A"], START, END)


async def test_degraded_keeps_missing_symbol_as_empty(wire) -> None:
    wire(primary={"A"}, secondary={"B"})  # C filled by nobody
    out = await ingest.fetch_with_fallback(["A", "B", "C"], START, END)
    assert {s for s, v in out.items() if v} == {"A", "B"}
    assert out["C"] == []


async def test_primary_complete_secondary_never_called(wire) -> None:
    fakes = wire(primary={"A", "B", "C"}, secondary={})
    await ingest.fetch_with_fallback(["A", "B", "C"], START, END)
    assert fakes["twelve_data"].calls == []  # zero fallback credits spent
