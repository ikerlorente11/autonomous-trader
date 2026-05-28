"""Momentum indicator: RSI (placeholder — real math via ``ta``, configurable params).

RSI is natively bounded 0–100, so its sub-score is the raw value (the base
``latest_score`` passthrough). ``overbought`` / ``oversold`` are carried for downstream
regime logic (synthesis §3) but are not applied to the score here — thresholds are
config, and the regime layer that consumes them is a later phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ta.momentum import RSIIndicator

from backend.analysis.indicators.base import Indicator

if TYPE_CHECKING:
    from pandas import DataFrame, Series


class RelativeStrengthIndex(Indicator):
    def __init__(self, period: int, overbought: float, oversold: float) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.signal_id = "rsi"
        self.required_periods = period + 1
        self._period = period
        self.overbought = overbought
        self.oversold = oversold

    def compute(self, df: DataFrame) -> Series:
        close = df["close"].astype(float)
        if not self.has_enough(df):
            return close * float("nan")
        return RSIIndicator(close=close, window=self._period, fillna=False).rsi()
