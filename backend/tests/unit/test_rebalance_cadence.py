"""v11 — monthly rebalance cadence gate and the per-version sizing envelope."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from backend.analysis.config import RankerConfig, load_strategy_config
from backend.analysis.engine import DefaultAnalysisEngine
from backend.contracts import SignalAction
from backend.trading.portfolio_manager import PortfolioManager

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc


def _frame(closes: list[float], end: str) -> pd.DataFrame:
    idx = pd.date_range(end=end, periods=len(closes), freq="B", tz="UTC")
    c = pd.Series(closes, index=idx, dtype="float64")
    return pd.DataFrame(
        {"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1_000_000},
        index=idx,
    )


def _monthly_engine() -> DefaultAnalysisEngine:
    base = load_strategy_config()
    cfg = base.model_copy(
        update={
            "ranker": RankerConfig(
                min_score_to_act=base.ranker.min_score_to_act,
                min_score_to_exit=base.ranker.min_score_to_exit,
                min_data_completeness=base.ranker.min_data_completeness,
                market_filter=None,
                rebalance_cadence="monthly",
            )
        }
    )
    return DefaultAnalysisEngine(cfg)


_UP = [100.0] * 30 + [101, 103, 105, 108, 112]  # strong name -> BUY
_DOWN = [200.0 - 3 * i for i in range(35)]  # collapsing name -> SELL


def test_off_day_holds_everything() -> None:
    # Bars end 2024-06-20; asof 2024-06-21 is the SAME month -> not a rebalance day.
    frames = {"AAA": _frame(_UP, "2024-06-20"), "BBB": _frame(_DOWN, "2024-06-20")}
    asof = dt.datetime(2024, 6, 21, tzinfo=UTC)
    _, gated = _monthly_engine().score_universe(frames, asof)
    assert all(s.action is SignalAction.HOLD for s in gated)
    assert any("rebalance cadence" in (s.reason or "") for s in gated)


def test_first_session_of_month_acts() -> None:
    # Bars end 2024-06-28 (June's last session); asof 2024-07-01 -> rebalance day.
    frames = {"AAA": _frame(_UP, "2024-06-28"), "BBB": _frame(_DOWN, "2024-06-28")}
    asof = dt.datetime(2024, 7, 1, tzinfo=UTC)
    _, scores = _monthly_engine().score_universe(frames, asof)
    actions = {s.symbol: s.action for s in scores}
    assert actions["AAA"] is SignalAction.BUY
    # Same frames, same engine: only the calendar position changed vs the off-day test.


def test_none_cadence_is_daily_behaviour() -> None:
    frames = {"AAA": _frame(_UP, "2024-06-20"), "BBB": _frame(_DOWN, "2024-06-20")}
    asof = dt.datetime(2024, 6, 21, tzinfo=UTC)
    _, plain = DefaultAnalysisEngine(load_strategy_config()).score_universe(frames, asof)
    assert any(s.action is not SignalAction.HOLD for s in plain)
    assert all("rebalance cadence" not in (s.reason or "") for s in plain)


def test_v11_overlay_loads_and_sets_the_new_knobs() -> None:
    cfg = load_strategy_config(label="v11")
    assert cfg.ranker.rebalance_cadence == "monthly"
    assert cfg.scoring.rank_normalize is True
    assert cfg.scoring.weights["momentum"] == 1.0
    assert sum(v for k, v in cfg.scoring.weights.items() if k != "momentum") == 0.0
    assert cfg.indicators.momentum is not None and cfg.indicators.momentum.period == 231
    assert cfg.trading.max_position_pct == pytest.approx(0.11)
    assert cfg.trading.min_cash_pct == pytest.approx(0.05)
    assert cfg.trading.max_open_positions == 8


def test_envelope_kwargs_come_from_the_version_config() -> None:
    cfg = load_strategy_config(label="v11")
    manager = PortfolioManager(None, None, portfolio_id=1, config=cfg)  # type: ignore[arg-type]
    kwargs = manager._envelope_kwargs()
    assert float(kwargs["max_position_pct"]) == pytest.approx(0.11)  # type: ignore[arg-type]
    assert float(kwargs["min_cash_pct"]) == pytest.approx(0.05)  # type: ignore[arg-type]
    assert kwargs["max_open_positions"] == 8


def test_envelope_empty_without_config_overrides() -> None:
    manager = PortfolioManager(None, None, portfolio_id=1, config=load_strategy_config())  # type: ignore[arg-type]
    assert manager._envelope_kwargs() == {}
