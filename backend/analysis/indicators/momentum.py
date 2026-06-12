"""Momentum indicators: RSI and N-bar price momentum (configurable params).

RSI is natively bounded 0–100, so its sub-score is the raw value (the base
``latest_score`` passthrough). ``overbought`` / ``oversold`` are carried for downstream
regime logic (synthesis §3) but are not applied to the score here — thresholds are
config, and the regime layer that consumes them is a later phase.

``PriceMomentum`` is the 12-1-style return: close ``skip`` bars ago over close
``skip + period`` bars ago, minus one (synthesis §3.1). Skipping the most recent
bars sidesteps the short-term reversal effect; with cross-sectional rank
normalization (P7) its percentile IS relative-universe momentum.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ta.momentum import RSIIndicator

from backend.analysis.indicators.base import Indicator, logistic_0_100

if TYPE_CHECKING:
    from pandas import DataFrame, Series


class RelativeStrengthIndex(Indicator):
    def __init__(
        self,
        period: int,
        overbought: float,
        oversold: float,
        mode: str = "passthrough",
    ) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.signal_id = "rsi"
        self.required_periods = period + 1
        self._period = period
        self.overbought = overbought
        self.oversold = oversold
        self._mode = mode

    def compute(self, df: DataFrame) -> Series:
        close = df["close"].astype(float)
        if not self.has_enough(df):
            return close * float("nan")
        return RSIIndicator(close=close, window=self._period, fillna=False).rsi()

    def latest_score(self, df: DataFrame) -> float | None:
        # P4: in mean_reversion mode the sub-score inverts (oversold -> high score) so
        # the scorer favours pullbacks instead of buying overbought strength.
        raw = super().latest_score(df)
        if raw is None or self._mode != "mean_reversion":
            return raw
        return 100.0 - raw


class PriceMomentum(Indicator):
    """Return over ``period`` bars ending ``skip`` bars ago, logistic-squashed."""

    def __init__(self, period: int, skip: int, sensitivity: float) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        if skip < 0:
            raise ValueError("skip must be >= 0")
        self.signal_id = "momentum"
        self.required_periods = period + skip + 1
        self._period = period
        self._skip = skip
        self._sensitivity = sensitivity

    def compute(self, df: DataFrame) -> Series:
        close = df["close"].astype(float)
        if not self.has_enough(df):
            return close * float("nan")
        ref = close.shift(self._skip)
        return ref / ref.shift(self._period) - 1.0

    def latest_score(self, df: DataFrame) -> float | None:
        finite = self.compute(df).dropna()
        if finite.empty:
            return None
        return logistic_0_100(self._sensitivity * float(finite.iloc[-1]))
