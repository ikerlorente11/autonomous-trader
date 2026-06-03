"""Macro regime classifier — RISK_ON / CAUTION / RISK_OFF (synthesis §macro).

Pure: takes the latest macro readings (yield-curve spread, VIX, high-yield credit
spread) and returns a 0–100 regime score (100 = full risk-on) plus a label. Inputs
are optional; a missing factor is dropped and the score is the mean of those present
(never imputed to zero — same rule as the composite scorer). Thresholds and the source
series ids are env-configurable (mirroring backend/trading/stops.py), so this holds no
hardcoded strategy values.

Observation mode: the score is recorded as a ``signal_values`` row but is NOT wired
into the composite scorer, so it changes no trade. Activation (turning the regime into
a score multiplier) is a later, deliberate config change.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from decimal import Decimal
from typing import NamedTuple

MACRO_REGIME_SIGNAL_ID = "macro_regime"

REGIME_RISK_ON = "risk_on"
REGIME_CAUTION = "caution"
REGIME_RISK_OFF = "risk_off"
REGIME_UNKNOWN = "unknown"


class RegimeResult(NamedTuple):
    regime: str
    score: float | None  # 0–100, None when no factor is available
    factors: dict[str, float]  # per-factor 0–100 sub-scores actually used


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _str_env(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else default


# Source series (default to the FRED Tier-1 basket members).
def curve_series_id() -> str:
    return _str_env("REGIME_CURVE_SERIES", "T10Y2Y")


def vix_series_id() -> str:
    return _str_env("REGIME_VIX_SERIES", "VIXCLS")


def credit_series_id() -> str:
    return _str_env("REGIME_CREDIT_SERIES", "BAMLH0A0HYM2")


def regime_series_ids() -> list[str]:
    return [curve_series_id(), vix_series_id(), credit_series_id()]


def _score_up(x: float, low: float, high: float) -> float:
    """Higher ``x`` → higher (more risk-on) sub-score. Clamped to 0–100."""
    if high <= low:
        return 50.0
    return max(0.0, min(100.0, (x - low) / (high - low) * 100.0))


def _score_down(x: float, low: float, high: float) -> float:
    """Higher ``x`` → lower sub-score (``low`` = calm/100, ``high`` = stress/0)."""
    if high <= low:
        return 50.0
    return max(0.0, min(100.0, (1.0 - (x - low) / (high - low)) * 100.0))


def classify_regime(
    curve: float | None,
    vix: float | None,
    credit: float | None,
) -> RegimeResult:
    """Blend the available macro factors into a 0–100 risk-on score and a label."""
    factors: dict[str, float] = {}
    if curve is not None:
        factors["curve"] = _score_up(
            curve, _float_env("REGIME_CURVE_LOW", -0.5), _float_env("REGIME_CURVE_HIGH", 0.5)
        )
    if vix is not None:
        factors["vix"] = _score_down(
            vix, _float_env("REGIME_VIX_LOW", 15.0), _float_env("REGIME_VIX_HIGH", 30.0)
        )
    if credit is not None:
        factors["credit"] = _score_down(
            credit, _float_env("REGIME_CREDIT_LOW", 3.0), _float_env("REGIME_CREDIT_HIGH", 6.0)
        )
    if not factors:
        return RegimeResult(regime=REGIME_UNKNOWN, score=None, factors={})

    score = sum(factors.values()) / len(factors)
    if score >= _float_env("REGIME_RISK_ON_MIN", 60.0):
        regime = REGIME_RISK_ON
    elif score <= _float_env("REGIME_RISK_OFF_MAX", 35.0):
        regime = REGIME_RISK_OFF
    else:
        regime = REGIME_CAUTION
    return RegimeResult(regime=regime, score=score, factors=factors)


def classify_from_macro(latest: Mapping[str, Decimal]) -> RegimeResult:
    """Classify from a ``{series_id: latest_value}`` map (missing series → dropped)."""

    def value_of(series_id: str) -> float | None:
        v = latest.get(series_id)
        return float(v) if v is not None else None

    return classify_regime(
        value_of(curve_series_id()),
        value_of(vix_series_id()),
        value_of(credit_series_id()),
    )
