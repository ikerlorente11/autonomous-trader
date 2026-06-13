"""Fundamental signals — earnings/revenue acceleration and a quality composite.

Pure math over quarterly ``line_items`` (the JSONB blob in ``fundamentals_quarterly``),
oldest → newest. Each signal returns a 0–100 sub-score or ``None`` when there isn't
enough data (dropped, never imputed — same rule as the composite scorer). Sensitivity
and caps are env-configurable, so no strategy values are hardcoded.

Expected ``line_items`` keys (populated by the fundamentals ingestion job, C3b):
``revenue``, ``net_income``, ``gross_profit``, ``equity``, ``free_cash_flow``.

Observation mode: these are recorded as ``signal_values`` but are NOT fed to the
composite scorer, so they change no trade until a deliberate activation (weights).
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence

REVENUE_ACCEL_SIGNAL_ID = "revenue_accel"
EARNINGS_ACCEL_SIGNAL_ID = "earnings_accel"
QUALITY_SIGNAL_ID = "quality"

_QUARTERS_PER_YEAR = 4


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return None if math.isnan(value) else float(value)


def _ratio(numerator: object, denominator: object) -> float | None:
    num, den = _num(numerator), _num(denominator)
    if num is None or den is None or den == 0:
        return None
    return num / den


def _score_up(x: float, low: float, high: float) -> float:
    if high <= low:
        return 50.0
    return max(0.0, min(100.0, (x - low) / (high - low) * 100.0))


def _yoy_growth(values: Sequence[float | None]) -> list[float]:
    """Year-over-year growth (quarter vs. the same quarter a year earlier)."""
    out: list[float] = []
    for i in range(_QUARTERS_PER_YEAR, len(values)):
        base, cur = values[i - _QUARTERS_PER_YEAR], values[i]
        if base is None or cur is None or base == 0:
            continue
        out.append((cur - base) / abs(base))
    return out


def acceleration_score(values: Sequence[float | None]) -> float | None:
    """0–100 logistic of the latest change in YoY growth (2nd-derivative proxy).

    Needs ≥2 YoY growth points (≈6 quarters of data); returns ``None`` otherwise."""
    yoy = _yoy_growth(values)
    if len(yoy) < 2:
        return None
    accel = yoy[-1] - yoy[-2]
    temp = _float_env("FUND_ACCEL_TEMP", 0.05)
    if temp <= 0:
        return 50.0
    # Numerically stable logistic: a huge swing (tiny YoY base) must saturate to
    # 0/100, not overflow math.exp (seen on real quarterly data in the backtester).
    z = accel / temp
    if z >= 0:
        return 100.0 / (1.0 + math.exp(-min(z, 700.0)))
    ez = math.exp(max(z, -700.0))
    return 100.0 * ez / (1.0 + ez)


def quality_score(quarters: Sequence[Mapping[str, object]]) -> float | None:
    """Quality composite from the latest quarter: ROE, gross margin, FCF-on-equity.

    Levels only (trend refinement deferred to activation). Mean of whichever
    components are computable; ``None`` if none are."""
    if not quarters:
        return None
    latest = quarters[-1]
    subs: list[float] = []
    roe = _ratio(latest.get("net_income"), latest.get("equity"))
    if roe is not None:
        subs.append(_score_up(roe, 0.0, _float_env("FUND_ROE_CAP", 0.20)))
    gross_margin = _ratio(latest.get("gross_profit"), latest.get("revenue"))
    if gross_margin is not None:
        subs.append(_score_up(gross_margin, 0.0, _float_env("FUND_GM_CAP", 0.60)))
    fcf_on_equity = _ratio(latest.get("free_cash_flow"), latest.get("equity"))
    if fcf_on_equity is not None:
        subs.append(_score_up(fcf_on_equity, 0.0, _float_env("FUND_FCF_CAP", 0.15)))
    if not subs:
        return None
    return sum(subs) / len(subs)


def compute_fundamental_signals(
    quarters: Sequence[Mapping[str, object]],
) -> dict[str, float]:
    """All fundamental sub-scores for one symbol's quarters (oldest → newest).

    Only signals with enough data are present in the result."""
    out: dict[str, float] = {}
    revenue = [_num(q.get("revenue")) for q in quarters]
    net_income = [_num(q.get("net_income")) for q in quarters]
    revenue_accel = acceleration_score(revenue)
    if revenue_accel is not None:
        out[REVENUE_ACCEL_SIGNAL_ID] = revenue_accel
    earnings_accel = acceleration_score(net_income)
    if earnings_accel is not None:
        out[EARNINGS_ACCEL_SIGNAL_ID] = earnings_accel
    quality = quality_score(quarters)
    if quality is not None:
        out[QUALITY_SIGNAL_ID] = quality
    return out
