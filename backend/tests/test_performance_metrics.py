"""Unit tests for the pure performance-metric math.

Hand-built small frames with arithmetically-known expectations. ``ts`` columns
use plain dates so date-based horizons (holding_days, drawdown_days) are exact.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backend.analysis.performance import metrics as m


# --------------------------------------------------------------------------- #
# build_round_trips
# --------------------------------------------------------------------------- #
def _orders(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_round_trip_single_pair_pnl_and_return() -> None:
    orders = _orders(
        [
            {"symbol": "AAA", "side": "buy", "qty": 10, "price": 100, "ts": "2026-01-01"},
            {"symbol": "AAA", "side": "sell", "qty": 10, "price": 110, "ts": "2026-01-11"},
        ]
    )
    trips = m.build_round_trips(orders)
    assert len(trips) == 1
    row = trips.iloc[0]
    assert row["pnl"] == pytest.approx(100.0)  # (110-100)*10
    assert row["return_pct"] == pytest.approx(0.10)
    assert row["holding_days"] == 10


def test_round_trip_fifo_partial_matching() -> None:
    orders = _orders(
        [
            {"symbol": "AAA", "side": "buy", "qty": 10, "price": 100, "ts": "2026-01-01"},
            {"symbol": "AAA", "side": "buy", "qty": 10, "price": 120, "ts": "2026-01-02"},
            {"symbol": "AAA", "side": "sell", "qty": 15, "price": 130, "ts": "2026-01-05"},
        ]
    )
    trips = m.build_round_trips(orders).sort_values("entry_price").reset_index(drop=True)
    assert len(trips) == 2
    # FIFO: first 10 from the 100 lot, then 5 from the 120 lot.
    first, second = trips.iloc[0], trips.iloc[1]
    assert first["qty"] == 10 and first["entry_price"] == 100
    assert first["pnl"] == pytest.approx(300.0)  # (130-100)*10
    assert second["qty"] == 5 and second["entry_price"] == 120
    assert second["pnl"] == pytest.approx(50.0)  # (130-120)*5


def test_round_trip_oversell_ignored_no_short() -> None:
    orders = _orders(
        [
            {"symbol": "AAA", "side": "buy", "qty": 5, "price": 100, "ts": "2026-01-01"},
            {"symbol": "AAA", "side": "sell", "qty": 20, "price": 110, "ts": "2026-01-05"},
        ]
    )
    trips = m.build_round_trips(orders)
    # Only the 5 open shares close; the extra 15 sell qty is dropped.
    assert len(trips) == 1
    assert trips.iloc[0]["qty"] == 5


def test_round_trip_only_filled_rows_used() -> None:
    orders = _orders(
        [
            {"symbol": "AAA", "side": "buy", "qty": 10, "price": 100, "ts": "2026-01-01", "status": "filled"},
            {"symbol": "AAA", "side": "sell", "qty": 10, "price": 110, "ts": "2026-01-05", "status": "rejected"},
        ]
    )
    trips = m.build_round_trips(orders)
    assert trips.empty  # the sell was rejected, so the lot stays open


def test_round_trip_empty_input() -> None:
    trips = m.build_round_trips(pd.DataFrame())
    assert trips.empty
    assert list(trips.columns) == [
        "symbol", "entry_ts", "exit_ts", "qty", "entry_price",
        "exit_price", "pnl", "return_pct", "holding_days",
    ]


# --------------------------------------------------------------------------- #
# win_rate / profit_factor
# --------------------------------------------------------------------------- #
def _trips(pnls: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"pnl": pnls})


def test_win_rate() -> None:
    assert m.win_rate(_trips([10, -5, 20, -1])) == pytest.approx(0.5)


def test_win_rate_empty_is_nan() -> None:
    assert math.isnan(m.win_rate(_trips([])))


def test_profit_factor_normal() -> None:
    # gross_profit 30, gross_loss 10 -> 3.0
    assert m.profit_factor(_trips([10, 20, -10])) == pytest.approx(3.0)


def test_profit_factor_no_losses_is_inf() -> None:
    assert m.profit_factor(_trips([10, 20])) == float("inf")


def test_profit_factor_no_trades_is_nan() -> None:
    assert math.isnan(m.profit_factor(_trips([])))


def test_profit_factor_only_zero_pnl_is_nan() -> None:
    # gross_loss == 0 and gross_profit == 0 -> nan, not inf.
    assert math.isnan(m.profit_factor(_trips([0.0, 0.0])))


# --------------------------------------------------------------------------- #
# sharpe / sortino
# --------------------------------------------------------------------------- #
def _nav(values: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.DataFrame({"ts": idx, "total": values})


def test_sharpe_flat_nav_is_nan() -> None:
    # Flat NAV -> all daily returns are exactly 0 -> std 0 -> nan.
    nav = _nav([100.0, 100.0, 100.0, 100.0])
    assert math.isnan(m.sharpe_ratio(nav, risk_free_rate=0.0))


def test_sharpe_positive_for_rising_volatile_series() -> None:
    nav = _nav([100, 102, 101, 105, 104, 108])
    s = m.sharpe_ratio(nav, risk_free_rate=0.0)
    assert s > 0


def test_sortino_ge_sharpe_when_downside_smaller() -> None:
    nav = _nav([100, 105, 103, 110, 108, 115])
    sharpe = m.sharpe_ratio(nav, risk_free_rate=0.0)
    sortino = m.sortino_ratio(nav, risk_free_rate=0.0)
    # Downside deviation <= total deviation, so sortino >= sharpe here.
    assert sortino >= sharpe


def test_sharpe_insufficient_data_is_nan() -> None:
    assert math.isnan(m.sharpe_ratio(_nav([100])))


# --------------------------------------------------------------------------- #
# max_drawdown
# --------------------------------------------------------------------------- #
def test_max_drawdown_value_and_recovery() -> None:
    # peak 120 -> trough 90 -> recovers to 120.
    nav = _nav([100, 120, 90, 110, 120])
    dd = m.max_drawdown(nav)
    assert dd.max_drawdown == pytest.approx(90 / 120 - 1.0)  # -0.25
    assert dd.recovery_ts is not None
    assert dd.drawdown_days is not None and dd.drawdown_days > 0


def test_max_drawdown_monotonic_rise_is_zero() -> None:
    dd = m.max_drawdown(_nav([100, 110, 120, 130]))
    assert dd.max_drawdown == 0.0
    assert dd.recovery_ts is None


def test_max_drawdown_unrecovered_has_none_recovery() -> None:
    nav = _nav([100, 120, 80])  # never climbs back to 120
    dd = m.max_drawdown(nav)
    assert dd.max_drawdown == pytest.approx(80 / 120 - 1.0)
    assert dd.recovery_ts is None
    assert dd.recovery_days is None


# --------------------------------------------------------------------------- #
# cagr / total_return
# --------------------------------------------------------------------------- #
def test_total_return() -> None:
    tr = m.total_return(_nav([100, 150]))
    assert tr.absolute == pytest.approx(50.0)
    assert tr.pct == pytest.approx(0.5)


def test_cagr_one_year_double() -> None:
    # Exactly one year apart, value doubles -> ~100% CAGR.
    nav = pd.DataFrame(
        {"ts": ["2025-01-01", "2026-01-01"], "total": [100.0, 200.0]}
    )
    assert m.cagr(nav) == pytest.approx(1.0, rel=1e-3)


def test_cagr_insufficient_data_is_nan() -> None:
    assert math.isnan(m.cagr(_nav([100])))
