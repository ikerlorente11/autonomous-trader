"""Volatility indicator: ATR (placeholder — real math via ``ta``, configurable params).

``compute`` returns raw ATR in price units (NaN until the window fills). The sub-score
maps ATR-as-percent-of-close through a logistic so it is bounded 0–100. Whether high
volatility should raise or lower a symbol's rank is a *strategy* decision (config/regime
layer, later phase); this placeholder only provides the bounded, configurable signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ta.volatility import AverageTrueRange

from backend.analysis.indicators.base import Indicator, logistic_0_100

if TYPE_CHECKING:
    from pandas import DataFrame, Series


class AverageTrueRangeIndicator(Indicator):
    def __init__(self, period: int, sensitivity: float) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.signal_id = "atr"
        self.required_periods = period + 1
        self._period = period
        self._sensitivity = sensitivity

    def _atr(self, df: DataFrame) -> Series:
        return AverageTrueRange(
            high=df["high"].astype(float),
            low=df["low"].astype(float),
            close=df["close"].astype(float),
            window=self._period,
            fillna=False,
        ).average_true_range()

    def compute(self, df: DataFrame) -> Series:
        if not self.has_enough(df):
            return df["close"].astype(float) * float("nan")
        return self._atr(df)

    def latest_score(self, df: DataFrame) -> float | None:
        if not self.has_enough(df):
            return None
        atr = self._atr(df).dropna()
        if atr.empty:
            return None
        last_close = float(df["close"].astype(float).iloc[-1])
        if last_close == 0.0:
            return None
        atr_pct = float(atr.iloc[-1]) / last_close
        return logistic_0_100(self._sensitivity * atr_pct)
