"""Technical indicators — pure pandas math; graceful on short data."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import pytest

from backend.analysis.indicators.momentum import RelativeStrengthIndex
from backend.analysis.indicators.moving_average import (
    ExponentialMovingAverage,
    SimpleMovingAverage,
)
from backend.analysis.indicators.volatility import AverageTrueRangeIndicator

pytestmark = pytest.mark.unit


def _df(closes: Sequence[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=idx, dtype="float64")
    return pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 1_000_000},
        index=idx,
    )


def test_sma_compute_length_and_last_value() -> None:
    sma = SimpleMovingAverage(period=3, sensitivity=10.0)
    out = sma.compute(_df([10, 11, 12, 13, 14]))
    assert len(out) == 5
    assert out.iloc[-1] == pytest.approx(13.0)  # mean(12,13,14)


def test_sma_short_data_is_all_nan_and_score_none() -> None:
    sma = SimpleMovingAverage(period=3, sensitivity=10.0)
    short = _df([10, 11])
    assert sma.compute(short).isna().all()
    assert sma.latest_score(short) is None


def test_ma_score_above_50_when_price_above_average() -> None:
    sma = SimpleMovingAverage(period=3, sensitivity=10.0)
    score = sma.latest_score(_df([10, 11, 12, 13, 20]))  # last close well above MA
    assert score is not None and 50.0 < score <= 100.0


def test_ema_score_bounded() -> None:
    ema = ExponentialMovingAverage(period=3, sensitivity=10.0)
    score = ema.latest_score(_df([10, 11, 12, 13, 14]))
    assert score is not None and 0.0 <= score <= 100.0


def test_rsi_uptrend_scores_high_and_is_bounded() -> None:
    rsi = RelativeStrengthIndex(period=2, overbought=70, oversold=30)
    score = rsi.latest_score(_df([10, 11, 12, 13, 14, 15]))
    assert score is not None and 50.0 < score <= 100.0


def test_rsi_short_data_score_none() -> None:
    rsi = RelativeStrengthIndex(period=14, overbought=70, oversold=30)
    assert rsi.latest_score(_df([10, 11, 12])) is None


def test_atr_score_bounded_and_short_data_none() -> None:
    atr = AverageTrueRangeIndicator(period=2, sensitivity=50.0)
    score = atr.latest_score(_df([10, 12, 11, 13, 9]))
    assert score is not None and 0.0 <= score <= 100.0
    assert atr.latest_score(_df([10, 11])) is None  # needs period+1 rows
