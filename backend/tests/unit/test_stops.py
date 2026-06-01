"""Trailing-stop arithmetic, ATR distance and VIX regime — pure, no I/O."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.trading.stops import (
    evaluate_trailing_stop,
    regime_adjustment,
    stop_distance,
    trailing_stop_pct,
)

pytestmark = pytest.mark.unit

PCT = Decimal("0.08")
D = Decimal


# ---- percentage trailing stop ----


def test_hard_floor_from_cost_when_never_rose() -> None:
    hwm, hit = evaluate_trailing_stop(D("100"), None, D("92"), pct=PCT)
    assert hwm == D("100") and hit is True


def test_small_dip_within_band_does_not_trigger() -> None:
    hwm, hit = evaluate_trailing_stop(D("100"), None, D("95"), pct=PCT)
    assert hwm == D("100") and hit is False


def test_high_water_mark_ratchets_up() -> None:
    hwm, hit = evaluate_trailing_stop(D("100"), D("120"), D("130"), pct=PCT)
    assert hwm == D("130") and hit is False


def test_trailing_locks_in_gains_after_run_up() -> None:
    hwm, hit = evaluate_trailing_stop(D("100"), D("130"), D("119"), pct=PCT)
    assert hwm == D("130") and hit is True  # 119 <= 130*0.92 = 119.6


# ---- ATR-based distance ----


def test_atr_distance_overrides_pct_when_available() -> None:
    # peak 100, ATR 2, multiple 2.5 -> distance 5 -> threshold 95
    dist = stop_distance(D("100"), pct=PCT, atr=D("2"), atr_multiple=D("2.5"))
    assert dist == D("5.0")


def test_atr_stop_triggers_where_pct_would_not() -> None:
    # ATR distance 5 (threshold 95) triggers at 94; pct 8% (threshold 92) would not.
    _, hit_atr = evaluate_trailing_stop(D("100"), None, D("94"), pct=PCT, atr=D("2"), atr_multiple=D("2.5"))
    _, hit_pct = evaluate_trailing_stop(D("100"), None, D("94"), pct=PCT)
    assert hit_atr is True and hit_pct is False


def test_zero_atr_multiple_falls_back_to_pct() -> None:
    dist = stop_distance(D("100"), pct=PCT, atr=D("2"), atr_multiple=D("0"))
    assert dist == D("8.00")  # 100 * 0.08


# ---- regime tightening / panic hold ----


def test_regime_calm_no_change() -> None:
    factor, panic = regime_adjustment(D("15"), tighten_above=D("30"), panic_above=D("40"), tighten_factor=D("0.6"))
    assert factor == D("1") and panic is False


def test_regime_stress_tightens() -> None:
    factor, panic = regime_adjustment(D("33"), tighten_above=D("30"), panic_above=D("40"), tighten_factor=D("0.6"))
    assert factor == D("0.6") and panic is False


def test_regime_panic_holds() -> None:
    factor, panic = regime_adjustment(D("45"), tighten_above=D("30"), panic_above=D("40"), tighten_factor=D("0.6"))
    assert panic is True


def test_regime_unknown_vix_no_change() -> None:
    factor, panic = regime_adjustment(None, tighten_above=D("30"), panic_above=D("40"), tighten_factor=D("0.6"))
    assert factor == D("1") and panic is False


def test_tighten_factor_makes_stop_trigger_sooner() -> None:
    # peak 100, pct 8% -> distance 8 (thr 92). Tighten 0.6 -> distance 4.8 (thr 95.2).
    _, normal = evaluate_trailing_stop(D("100"), None, D("94"), pct=PCT)
    _, tight = evaluate_trailing_stop(D("100"), None, D("94"), pct=PCT, distance_factor=D("0.6"))
    assert normal is False and tight is True


def test_config_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRAILING_STOP_PCT", raising=False)
    assert trailing_stop_pct() == D("0.08")
    monkeypatch.setenv("TRAILING_STOP_PCT", "0.05")
    assert trailing_stop_pct() == D("0.05")
