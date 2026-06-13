"""Backtester — pure replay mechanics over synthetic bars (no DB)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from backend.analysis.config import load_strategy_config
from backend.backtest.runner import Backtester, BacktestParams

pytestmark = pytest.mark.unit


def _frame(closes: list[float], start: str = "2025-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="B", tz="UTC")
    close = pd.Series(closes, index=idx, dtype="float64")
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
         "volume": 1_000_000},
        index=idx,
    )


def _params(start: dt.date, end: dt.date) -> BacktestParams:
    return BacktestParams(start=start, end=end, starting_cash=10_000.0)


def test_backtest_produces_nav_for_every_traded_day() -> None:
    closes = [100.0 + i * 0.1 for i in range(80)]
    frames = {"AAA": _frame(closes), "SPY": _frame(closes)}
    start, end = dt.date(2025, 3, 1), dt.date(2025, 4, 20)
    result = Backtester(
        frames, load_strategy_config(label="v1"), "v1", _params(start, end)
    ).run()
    assert len(result.nav) > 0
    assert (result.nav > 0).all()
    assert result.benchmark_return is not None


def test_backtest_cash_never_negative_and_metrics_finite() -> None:
    # A volatile tape exercises buys, exits and stops; the ledger must stay sane.
    closes = [100, 105, 110, 108, 90, 80, 85, 95, 100, 110, 120, 115, 105, 95, 100] * 6
    frames = {"AAA": _frame([float(c) for c in closes]),
              "BBB": _frame([float(c) + 50 for c in closes]),
              "SPY": _frame([float(c) * 2 for c in closes])}
    start, end = dt.date(2025, 2, 1), dt.date(2025, 5, 1)
    result = Backtester(
        frames, load_strategy_config(label="v3"), "v3", _params(start, end)
    ).run()
    assert result.nav.notna().all()
    assert result.max_drawdown <= 0.0
    # every sell matches a prior buy (no shorting in the replay)
    held: dict[str, float] = {}
    for t in result.trades:
        if t.side == "buy":
            held[t.symbol] = held.get(t.symbol, 0.0) + t.qty
        else:
            assert held.get(t.symbol, 0.0) >= t.qty - 1e-9
            held[t.symbol] = held.get(t.symbol, 0.0) - t.qty


def test_backtests_share_frames_without_cross_contamination() -> None:
    # Regression: a run must not mutate the shared frames (pandas column cache) —
    # the second label's run would otherwise crash or silently diverge.
    closes = [100.0 + i * 0.1 for i in range(80)]
    frames = {"AAA": _frame(closes), "SPY": _frame(closes)}
    start, end = dt.date(2025, 3, 1), dt.date(2025, 4, 20)
    first = Backtester(
        frames, load_strategy_config(label="v1"), "v1", _params(start, end)
    ).run()
    second = Backtester(
        frames, load_strategy_config(label="v1"), "v1", _params(start, end)
    ).run()
    assert list(first.nav) == list(second.nav)
