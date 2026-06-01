"""Regression: the metered fallback must receive only the symbols the primary missed.

Bug (2026-06-01): when yfinance failed for the whole watchlist the fallback dumped
*every* symbol onto Twelve Data (1 credit/symbol, ~8/min) → rate-limit exhaustion.
Fixed by making fetch_with_fallback per-symbol: the secondary is asked only for the
gaps the primary left empty."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.data_ingestion import ingest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

START = dt.date(2026, 5, 28)
END = dt.date(2026, 5, 29)
BAR = ["bar"]


class _Provider:
    def __init__(self, has: set[str]) -> None:
        self._has = has
        self.calls: list[list[str]] = []

    async def fetch_daily_bars(self, symbols, start, end):
        self.calls.append(list(symbols))
        return {s: (BAR if s in self._has else []) for s in symbols}


async def test_secondary_only_gets_the_gap_not_the_whole_watchlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = [f"S{i}" for i in range(28)]
    filled_by_primary = set(watchlist[:26])     # primary covers 26 of 28
    gap = watchlist[26:]                          # 2 left for the fallback

    primary = _Provider(filled_by_primary)
    secondary = _Provider(set(watchlist))         # could serve all, but must be asked few
    monkeypatch.setattr(
        ingest, "make_provider",
        lambda name: primary if name == "yfinance" else secondary,
    )

    await ingest.fetch_with_fallback(watchlist, START, END)

    assert secondary.calls == [gap], "fallback must receive only the 2 missing symbols"
    assert len(secondary.calls[0]) == 2  # not 28 — no rate-limit burst
