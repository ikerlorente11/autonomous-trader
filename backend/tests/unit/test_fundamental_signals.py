"""Fundamental signals — acceleration + quality composite (pure)."""

from __future__ import annotations

import pytest

from backend.analysis.signals.fundamental.signals import (
    EARNINGS_ACCEL_SIGNAL_ID,
    QUALITY_SIGNAL_ID,
    REVENUE_ACCEL_SIGNAL_ID,
    acceleration_score,
    compute_fundamental_signals,
    quality_score,
)

pytestmark = pytest.mark.unit


def _q(**kw: float) -> dict[str, float]:
    return dict(kw)


def test_acceleration_positive_when_growth_speeds_up() -> None:
    # 6 quarters: YoY(q4)=0.5, YoY(q5)=0.636 -> accel > 0 -> score > 50.
    s = acceleration_score([100, 110, 120, 130, 150, 180])
    assert s is not None and s > 50.0


def test_acceleration_negative_when_growth_decelerates() -> None:
    s = acceleration_score([100, 110, 200, 130, 210, 132])  # YoY drops q4->q5
    assert s is not None and s < 50.0


def test_acceleration_needs_two_yoy_points() -> None:
    assert acceleration_score([100, 110, 120, 130, 150]) is None  # only 5 quarters
    assert acceleration_score([]) is None


def test_acceleration_skips_zero_or_missing_base() -> None:
    # Bases (index 0,1) are 0/None -> those YoY points dropped, leaving < 2.
    assert acceleration_score([0, None, 120, 130, 150, 180]) is None


def test_quality_blends_available_components() -> None:
    q = quality_score([_q(net_income=20, equity=100, gross_profit=60, revenue=100, free_cash_flow=15)])
    # ROE 20%->100, GM 60%->100, FCF/eq 15%->100 ; mean 100.
    assert q == pytest.approx(100.0)


def test_quality_drops_missing_components() -> None:
    q = quality_score([_q(net_income=10, equity=100)])  # only ROE 10% -> 50
    assert q == pytest.approx(50.0)


def test_quality_none_when_nothing_computable() -> None:
    assert quality_score([_q(revenue=100)]) is None  # no margin (no gross_profit), no roe/fcf
    assert quality_score([]) is None


def test_compute_returns_only_available_signals() -> None:
    quarters = [
        _q(revenue=100, net_income=10, equity=100, gross_profit=50, free_cash_flow=5),
        _q(revenue=110, net_income=11, equity=105, gross_profit=56, free_cash_flow=6),
        _q(revenue=120, net_income=12, equity=110, gross_profit=62, free_cash_flow=7),
        _q(revenue=130, net_income=13, equity=115, gross_profit=68, free_cash_flow=8),
        _q(revenue=150, net_income=16, equity=120, gross_profit=80, free_cash_flow=10),
        _q(revenue=180, net_income=20, equity=130, gross_profit=100, free_cash_flow=14),
    ]
    out = compute_fundamental_signals(quarters)
    assert set(out) == {REVENUE_ACCEL_SIGNAL_ID, EARNINGS_ACCEL_SIGNAL_ID, QUALITY_SIGNAL_ID}
    assert all(0.0 <= v <= 100.0 for v in out.values())


def test_compute_omits_acceleration_with_short_history() -> None:
    quarters = [_q(revenue=100, net_income=10, equity=100, gross_profit=50)]
    out = compute_fundamental_signals(quarters)
    assert REVENUE_ACCEL_SIGNAL_ID not in out
    assert QUALITY_SIGNAL_ID in out  # quality only needs the latest quarter
