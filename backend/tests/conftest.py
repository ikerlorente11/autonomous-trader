"""Shared fixtures for the pure-unit backend suite.

No live database: every test here exercises side-effect-free units or fakes the
DB session/query layer via monkeypatch. The ``strategy_config`` fixture builds a
``StrategyConfig`` directly (no YAML/env dependency) so scorer/ranker tests have
deterministic, well-known thresholds.
"""

from __future__ import annotations

import pytest

from backend.analysis.config import (
    AtrParams,
    IndicatorParams,
    MaTrendParams,
    RankerConfig,
    RsiParams,
    ScoringConfig,
    StrategyConfig,
)


@pytest.fixture
def strategy_config() -> StrategyConfig:
    return StrategyConfig(
        version="test",
        ranker=RankerConfig(
            min_score_to_act=60.0,
            min_score_to_exit=45.0,
            min_data_completeness=0.5,
        ),
        scoring=ScoringConfig(
            score_min=0.0,
            score_max=100.0,
            weights={"rsi": 0.50, "ma_trend": 0.30, "atr": 0.20},
        ),
        indicators=IndicatorParams(
            ma_trend=MaTrendParams(kind="ema", period=20, sensitivity=20.0),
            rsi=RsiParams(period=14, overbought=70.0, oversold=30.0),
            atr=AtrParams(period=14, sensitivity=50.0),
        ),
    )
