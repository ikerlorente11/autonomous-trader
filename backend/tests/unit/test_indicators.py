"""Technical indicators — pure pandas math; graceful on short data."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import pytest

from backend.analysis.indicators.momentum import PriceMomentum, RelativeStrengthIndex
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


def test_rsi_mean_reversion_inverts_passthrough() -> None:
    # P4: same bars, opposite sub-scores. mean_reversion = 100 - passthrough.
    bars = _df([10, 11, 12, 13, 14, 15, 16, 15, 14, 13, 12, 13, 14, 15, 16, 17])
    passthrough = RelativeStrengthIndex(period=14, overbought=70, oversold=30).latest_score(bars)
    contrarian = RelativeStrengthIndex(
        period=14, overbought=70, oversold=30, mode="mean_reversion"
    ).latest_score(bars)
    assert passthrough is not None and contrarian is not None
    assert contrarian == pytest.approx(100.0 - passthrough)


def test_ma_trend_extension_cap_limits_upside_score() -> None:
    # P5: a name far above its MA scores lower when capped than uncapped.
    bars = _df([10, 10, 10, 10, 10, 10, 10, 10, 10, 20])  # last close way above MA
    uncapped = ExponentialMovingAverage(period=5, sensitivity=20.0).latest_score(bars)
    capped = ExponentialMovingAverage(
        period=5, sensitivity=20.0, extension_cap=0.02
    ).latest_score(bars)
    assert uncapped is not None and capped is not None
    assert capped < uncapped


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


def test_price_momentum_uptrend_above_50_downtrend_below() -> None:
    up = PriceMomentum(period=3, skip=1, sensitivity=5.0).latest_score(_df([10, 11, 12, 13, 14, 15]))
    down = PriceMomentum(period=3, skip=1, sensitivity=5.0).latest_score(_df([15, 14, 13, 12, 11, 10]))
    assert up is not None and up > 50.0
    assert down is not None and down < 50.0


def test_price_momentum_skip_ignores_recent_bars() -> None:
    # period=2, skip=2: the score reads close[-3]/close[-5] — a crash in the final
    # two bars (the skipped reversal window) must not move it.
    calm = PriceMomentum(period=2, skip=2, sensitivity=5.0).latest_score(_df([10, 10, 12, 14, 14, 14]))
    crash = PriceMomentum(period=2, skip=2, sensitivity=5.0).latest_score(_df([10, 10, 12, 14, 5, 4]))
    assert calm is not None and crash is not None
    assert crash == pytest.approx(calm)


def test_price_momentum_short_data_none() -> None:
    pm = PriceMomentum(period=126, skip=21, sensitivity=5.0)
    assert pm.latest_score(_df([10.0] * 100)) is None


def test_atr_score_bounded_and_short_data_none() -> None:
    atr = AverageTrueRangeIndicator(period=2, sensitivity=50.0)
    score = atr.latest_score(_df([10, 12, 11, 13, 9]))
    assert score is not None and 0.0 <= score <= 100.0
    assert atr.latest_score(_df([10, 11])) is None  # needs period+1 rows
