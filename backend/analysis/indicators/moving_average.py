"""Moving-average trend indicators (placeholder — real math, configurable params).

``compute`` returns the raw moving average aligned to the input index (NaN where the
window is not yet full). The 0–100 sub-score is the close's signed percentage distance
above the average, squashed through a logistic so it is bounded and centred at 50 when
price sits on the average. ``period`` and ``sensitivity`` come from config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.analysis.indicators.base import Indicator, logistic_0_100

if TYPE_CHECKING:
    from pandas import DataFrame, Series

_SIGNAL_ID = "ma_trend"


class _MovingAverage(Indicator):
    def __init__(self, period: int, sensitivity: float) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.signal_id = _SIGNAL_ID
        self.required_periods = period
        self._period = period
        self._sensitivity = sensitivity

    def _ma(self, close: Series) -> Series:  # noqa: D401 - subclass hook
        raise NotImplementedError

    def compute(self, df: DataFrame) -> Series:
        close = df["close"].astype(float)
        if not self.has_enough(df):
            return close * float("nan")
        return self._ma(close)

    def latest_score(self, df: DataFrame) -> float | None:
        if not self.has_enough(df):
            return None
        close = df["close"].astype(float)
        ma = self._ma(close).dropna()
        if ma.empty:
            return None
        last_close = float(close.iloc[-1])
        last_ma = float(ma.iloc[-1])
        if last_ma == 0.0:
            return None
        distance = last_close / last_ma - 1.0
        return logistic_0_100(self._sensitivity * distance)


class SimpleMovingAverage(_MovingAverage):
    def _ma(self, close: Series) -> Series:
        return close.rolling(window=self._period).mean()


class ExponentialMovingAverage(_MovingAverage):
    def _ma(self, close: Series) -> Series:
        return close.ewm(span=self._period, adjust=False, min_periods=self._period).mean()
