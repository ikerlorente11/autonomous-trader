"""Macro regime classifier — pure 0–100 blend + label."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.analysis.signals.macro.regime import (
    REGIME_CAUTION,
    REGIME_RISK_OFF,
    REGIME_RISK_ON,
    REGIME_UNKNOWN,
    classify_from_macro,
    classify_regime,
)

pytestmark = pytest.mark.unit


def test_risk_on_when_curve_positive_vix_low_credit_tight() -> None:
    r = classify_regime(curve=1.0, vix=12.0, credit=2.5)
    assert r.regime == REGIME_RISK_ON
    assert r.score == pytest.approx(100.0)
    assert set(r.factors) == {"curve", "vix", "credit"}


def test_risk_off_when_curve_inverted_vix_high_credit_wide() -> None:
    r = classify_regime(curve=-1.0, vix=35.0, credit=7.0)
    assert r.regime == REGIME_RISK_OFF
    assert r.score == pytest.approx(0.0)


def test_caution_in_the_middle_band() -> None:
    r = classify_regime(curve=0.0, vix=22.5, credit=4.5)
    assert r.regime == REGIME_CAUTION
    assert r.score == pytest.approx(50.0)


def test_missing_factors_are_dropped_not_imputed() -> None:
    r = classify_regime(curve=None, vix=12.0, credit=None)
    assert r.factors == {"vix": pytest.approx(100.0)}
    assert r.regime == REGIME_RISK_ON


def test_no_inputs_is_unknown_with_none_score() -> None:
    r = classify_regime(curve=None, vix=None, credit=None)
    assert r.regime == REGIME_UNKNOWN
    assert r.score is None


def test_classify_from_macro_maps_series_ids() -> None:
    latest = {
        "T10Y2Y": Decimal("1.0"),
        "VIXCLS": Decimal("12"),
        "BAMLH0A0HYM2": Decimal("2.5"),
    }
    assert classify_from_macro(latest).regime == REGIME_RISK_ON
    assert classify_from_macro({"VIXCLS": Decimal("35")}).regime == REGIME_RISK_OFF


def test_env_thresholds_override_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGIME_RISK_ON_MIN", "200")  # unreachable -> never risk_on
    r = classify_regime(curve=1.0, vix=12.0, credit=2.5)
    assert r.score == pytest.approx(100.0)
    assert r.regime == REGIME_CAUTION
