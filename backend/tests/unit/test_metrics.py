"""NAV-based performance metrics — pure pandas/numpy math."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import pytest

from backend.analysis.performance.metrics import (
    cagr,
    calmar_ratio,
    max_drawdown,
    sharpe_ratio,
    total_return,
)

pytestmark = pytest.mark.unit


def _nav(values: Sequence[float], *, dates: Sequence[str] | None = None) -> pd.DataFrame:
    if dates is not None:
        ts = pd.to_datetime(list(dates))
    else:
        ts = pd.date_range("2025-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"ts": ts, "total": list(values)})


def test_total_return_absolute_and_pct() -> None:
    tr = total_return(_nav([100, 150]))
    assert tr.absolute == pytest.approx(50.0)
    assert tr.pct == pytest.approx(0.5)


def test_total_return_degenerate_series_is_nan_pct() -> None:
    tr = total_return(_nav([100]))
    assert tr.pct != tr.pct  # NaN


def test_cagr_one_year_growth() -> None:
    nav = _nav([100, 121], dates=["2025-01-01", "2026-01-01"])
    assert cagr(nav) == pytest.approx(0.21, abs=2e-3)  # ~21% over ~1y


def test_max_drawdown_peak_to_trough_and_recovery() -> None:
    dd = max_drawdown(_nav([100, 120, 80, 130]))
    assert dd.max_drawdown == pytest.approx(-1 / 3, abs=1e-6)  # 80/120 - 1
    assert dd.recovery_ts is not None  # 130 >= prior peak 120
    assert dd.peak_ts is not None and dd.trough_ts is not None


def test_max_drawdown_monotonic_rise_has_no_drawdown() -> None:
    dd = max_drawdown(_nav([100, 110, 120, 130]))
    assert dd.max_drawdown == 0.0
    assert dd.trough_ts is None


def test_sharpe_is_finite_and_positive_for_net_gains() -> None:
    sr = sharpe_ratio(_nav([100, 101, 103, 102, 105, 107]), risk_free_rate=0.0)
    assert sr == sr and sr > 0  # finite (not NaN) and positive


def test_calmar_positive_when_growth_positive_and_drawdown_present() -> None:
    nav = _nav([100, 120, 80, 130], dates=["2025-01-01", "2025-06-01", "2025-09-01", "2026-01-01"])
    assert calmar_ratio(nav) > 0
