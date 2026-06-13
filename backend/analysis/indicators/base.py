"""Indicator base contract.

Every concrete indicator implements ``compute(df) -> Series``: it takes a single
symbol's OHLCV DataFrame and returns a per-date Series. Indicators must fail
gracefully — if there are fewer than ``required_periods`` rows, ``compute`` returns
an all-NaN Series of the input length rather than raising, so one short symbol never
breaks a universe-wide run.

``latest_score(df)`` collapses the series into the newest bar's 0–100 sub-score the
composite scorer consumes (``None`` when there is not enough data). The default takes
the last finite value clipped to [0, 100]; indicators whose raw output is not already
a 0–100 quantity (moving averages, ATR) override it. No weights or thresholds live
here — those are config (``config/strategy.yaml``).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandas import DataFrame, Series


class Indicator(ABC):
    """Base class for a single computed signal over one symbol's bars."""

    signal_id: str
    required_periods: int

    @property
    def name(self) -> str:
        return self.signal_id

    def has_enough(self, df: DataFrame) -> bool:
        return len(df) >= self.required_periods

    @abstractmethod
    def compute(self, df: DataFrame) -> Series:
        """Return a per-date Series; all-NaN if fewer than ``required_periods`` rows."""
        raise NotImplementedError

    def latest_score(self, df: DataFrame) -> float | None:
        """Newest bar's 0–100 sub-score, or ``None`` if data is insufficient."""
        finite = self.compute(df).dropna()
        if finite.empty:
            return None
        return clip_0_100(float(finite.iloc[-1]))


def clip_0_100(value: float) -> float:
    return max(0.0, min(100.0, value))


def logistic_0_100(z: float) -> float:
    """Map any real ``z`` to (0, 100), centred at 50 when ``z == 0``.

    Numerically stable: extreme inputs saturate to 0/100 instead of overflowing
    ``math.exp`` (a data glitch must degrade a score, never crash a run)."""
    if z >= 0:
        return 100.0 / (1.0 + math.exp(-min(z, 700.0)))
    ez = math.exp(max(z, -700.0))
    return 100.0 * ez / (1.0 + ez)
