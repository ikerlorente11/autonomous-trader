"""Tests for forward-return signal settlement.

``settle_due_signals`` is DB-bound, but its decision logic is pure. We monkeypatch
the three query functions it imported into its own module namespace with async
fakes and pass a sentinel session (never touched), so we exercise the real
buy/sell-correctness logic without a database. Horizon parsing is covered directly.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest

from backend.analysis.performance import settle


# --------------------------------------------------------------------------- #
# _horizon_days
# --------------------------------------------------------------------------- #
def test_horizon_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNAL_EVAL_HORIZON_DAYS", raising=False)
    assert settle._horizon_days() == 5


def test_horizon_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_EVAL_HORIZON_DAYS", "10")
    assert settle._horizon_days() == 10


def test_horizon_clamps_to_minimum_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_EVAL_HORIZON_DAYS", "0")
    assert settle._horizon_days() == 1


def test_horizon_invalid_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_EVAL_HORIZON_DAYS", "not-a-number")
    assert settle._horizon_days() == 5


# --------------------------------------------------------------------------- #
# settle_due_signals decision logic (faked query layer)
# --------------------------------------------------------------------------- #
def _bar(close: float) -> SimpleNamespace:
    return SimpleNamespace(close=close)


def _signal(action: str, symbol: str = "AAA") -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        ts=dt.datetime(2026, 1, 1),
        action=action,
        realized_return=None,
        outcome=None,
    )


def _patch_queries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    signals: list[SimpleNamespace],
    entry_close: float | None,
    exit_close: float | None,
) -> dict[str, Any]:
    flushed = {"count": 0}

    async def fake_unsettled(session: Any, cutoff: Any, *a: Any, **k: Any):
        return signals

    async def fake_asof(session: Any, symbol: str, asof: Any):
        return None if entry_close is None else _bar(entry_close)

    async def fake_after(session: Any, symbol: str, asof: Any):
        return None if exit_close is None else _bar(exit_close)

    async def fake_flush() -> None:
        flushed["count"] += 1

    monkeypatch.setattr(settle, "get_unsettled_signals", fake_unsettled)
    monkeypatch.setattr(settle, "get_close_asof", fake_asof)
    monkeypatch.setattr(settle, "get_close_after", fake_after)
    return flushed


class _FakeSession:
    def __init__(self, flush_marker: dict[str, Any]) -> None:
        self._marker = flush_marker

    async def flush(self) -> None:
        self._marker["count"] += 1


async def test_buy_correct_when_forward_return_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sig = _signal("buy")
    marker = _patch_queries(
        monkeypatch, signals=[sig], entry_close=100.0, exit_close=110.0
    )
    n = await settle.settle_due_signals(_FakeSession(marker), dt.datetime(2026, 1, 20))
    assert n == 1
    assert sig.realized_return == pytest.approx(0.10)
    assert sig.outcome == "correct"


async def test_buy_incorrect_when_forward_return_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sig = _signal("buy")
    marker = _patch_queries(
        monkeypatch, signals=[sig], entry_close=100.0, exit_close=90.0
    )
    await settle.settle_due_signals(_FakeSession(marker), dt.datetime(2026, 1, 20))
    assert sig.outcome == "incorrect"


async def test_sell_correct_when_forward_return_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sig = _signal("sell")
    marker = _patch_queries(
        monkeypatch, signals=[sig], entry_close=100.0, exit_close=90.0
    )
    await settle.settle_due_signals(_FakeSession(marker), dt.datetime(2026, 1, 20))
    assert sig.outcome == "correct"


async def test_sell_incorrect_when_forward_return_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sig = _signal("sell")
    marker = _patch_queries(
        monkeypatch, signals=[sig], entry_close=100.0, exit_close=110.0
    )
    await settle.settle_due_signals(_FakeSession(marker), dt.datetime(2026, 1, 20))
    assert sig.outcome == "incorrect"


async def test_missing_bars_skip_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    sig = _signal("buy")
    marker = _patch_queries(
        monkeypatch, signals=[sig], entry_close=None, exit_close=110.0
    )
    n = await settle.settle_due_signals(_FakeSession(marker), dt.datetime(2026, 1, 20))
    assert n == 0
    assert sig.outcome is None


async def test_nonpositive_entry_close_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    sig = _signal("buy")
    marker = _patch_queries(
        monkeypatch, signals=[sig], entry_close=0.0, exit_close=110.0
    )
    n = await settle.settle_due_signals(_FakeSession(marker), dt.datetime(2026, 1, 20))
    assert n == 0
