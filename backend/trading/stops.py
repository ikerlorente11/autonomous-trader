"""Trailing-stop arithmetic + volatility/regime adjustments — pure, no I/O.

The intraday protective-sell job owns the DB and the broker; this module only does the
maths so it is trivially testable.

Stop distance below the high-water mark is, in order of preference:
- **ATR-based** (``atr × atr_multiple``) when a raw ATR is available — a volatility-adaptive
  stop (wider for choppy names, tighter for calm ones), which is what the research calls for;
- **percentage** (``peak × pct``) as the fallback when ATR can't be computed.

A market-stress *regime* (from VIX) then scales that distance: tighten (smaller distance →
exit sooner) above a stress threshold, but **hold** (suspend protective selling) in outright
panic, because extreme VIX is historically near the bottom — don't sell the capitulation.
"""

from __future__ import annotations

import os
from decimal import Decimal

_DEFAULT_TRAILING_STOP_PCT = Decimal("0.08")
_DEFAULT_ATR_STOP_MULTIPLE = Decimal("2.5")
_DEFAULT_VIX_TIGHTEN_ABOVE = Decimal("30")
_DEFAULT_VIX_PANIC_ABOVE = Decimal("40")
_DEFAULT_STOP_TIGHTEN_FACTOR = Decimal("0.6")


def _decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return Decimal(raw)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def trailing_stop_pct() -> Decimal:
    return _decimal_env("TRAILING_STOP_PCT", _DEFAULT_TRAILING_STOP_PCT)


def atr_stop_multiple() -> Decimal:
    """ATR multiplier for the stop distance; 0 disables ATR (always use pct)."""
    return _decimal_env("STOP_ATR_MULTIPLE", _DEFAULT_ATR_STOP_MULTIPLE)


def regime_enabled() -> bool:
    return _bool_env("STOP_REGIME_ENABLED", True)


def vix_tighten_above() -> Decimal:
    return _decimal_env("VIX_TIGHTEN_ABOVE", _DEFAULT_VIX_TIGHTEN_ABOVE)


def vix_panic_above() -> Decimal:
    return _decimal_env("VIX_PANIC_ABOVE", _DEFAULT_VIX_PANIC_ABOVE)


def stop_tighten_factor() -> Decimal:
    return _decimal_env("STOP_TIGHTEN_FACTOR", _DEFAULT_STOP_TIGHTEN_FACTOR)


def vix_panic_hold() -> bool:
    """In outright panic, hold instead of selling into the capitulation (research §4.2)."""
    return _bool_env("VIX_PANIC_HOLD", True)


def regime_adjustment(
    vix: Decimal | None,
    *,
    tighten_above: Decimal,
    panic_above: Decimal,
    tighten_factor: Decimal,
) -> tuple[Decimal, bool]:
    """Map a VIX reading to ``(distance_factor, panic_hold)``.

    - VIX unknown or calm → ``(1, False)`` (normal stop).
    - VIX ≥ tighten_above (stress) → ``(tighten_factor, False)`` (exit sooner).
    - VIX ≥ panic_above → ``(1, True)`` (suspend selling — don't sell the bottom).
    """
    if vix is None:
        return Decimal(1), False
    if vix >= panic_above:
        return Decimal(1), True
    if vix >= tighten_above:
        return tighten_factor, False
    return Decimal(1), False


def stop_distance(
    peak: Decimal,
    *,
    pct: Decimal,
    atr: Decimal | None = None,
    atr_multiple: Decimal | None = None,
    distance_factor: Decimal = Decimal(1),
    min_distance_pct: Decimal = Decimal(0),
) -> Decimal:
    """Price distance below ``peak`` that triggers the stop (ATR-based if available).

    ``min_distance_pct`` (P3) is a floor as a fraction of ``peak``: it stops calm names
    (tiny ATR) from being knocked out by ordinary 1–2% noise. 0 disables the floor.
    """
    if atr is not None and atr_multiple is not None and atr_multiple > 0:
        base = atr_multiple * atr
    else:
        base = peak * pct
    base = base * distance_factor
    floor = peak * min_distance_pct
    return max(base, floor)


def evaluate_trailing_stop(
    avg_cost: Decimal,
    high_water_mark: Decimal | None,
    live_price: Decimal,
    *,
    pct: Decimal,
    atr: Decimal | None = None,
    atr_multiple: Decimal | None = None,
    distance_factor: Decimal = Decimal(1),
    min_distance_pct: Decimal = Decimal(0),
) -> tuple[Decimal, bool]:
    """Return ``(new_high_water_mark, triggered)``.

    ``new_high_water_mark`` ratchets up to the live price (seeded from ``avg_cost``),
    never down. ``triggered`` is True when ``live_price <= peak - stop_distance``.
    """
    peak = max(high_water_mark if high_water_mark is not None else avg_cost, live_price)
    distance = stop_distance(
        peak,
        pct=pct,
        atr=atr,
        atr_multiple=atr_multiple,
        distance_factor=distance_factor,
        min_distance_pct=min_distance_pct,
    )
    return peak, live_price <= peak - distance
