"""run_analysis fundamental-signal observation: records revenue/earnings
acceleration + quality as signal_values without altering the composite score."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from backend.analysis.engine import DefaultAnalysisEngine
from backend.analysis.signals.fundamental.signals import (
    EARNINGS_ACCEL_SIGNAL_ID,
    QUALITY_SIGNAL_ID,
    REVENUE_ACCEL_SIGNAL_ID,
)
from backend.db.models import AlgorithmSignal, FundamentalsQuarterly, SignalValue
from backend.db.queries.market_queries import get_bars_range
from backend.db.session import async_session
from backend.scheduler import jobs
from backend.tests import factories as f

pytestmark = pytest.mark.integration

_SYMBOL = "AAPL"
_CLOSES = [100.0 + i * 0.5 for i in range(60)]
_PERIOD_ENDS = [
    dt.date(2024, 3, 31),
    dt.date(2024, 6, 30),
    dt.date(2024, 9, 30),
    dt.date(2024, 12, 31),
    dt.date(2025, 3, 31),
    dt.date(2025, 6, 30),
]
_REVENUE = [100, 110, 120, 130, 150, 180]
_NET_INCOME = [10, 11, 12, 13, 16, 20]
_EQUITY = [100, 105, 110, 115, 120, 130]
_GROSS_PROFIT = [50, 56, 62, 68, 80, 100]
_FCF = [5, 6, 7, 8, 10, 14]


@pytest.fixture(autouse=True)
def _trading_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)


async def _seed() -> None:
    start = dt.date.today() - dt.timedelta(days=70)
    async with async_session() as s:
        await f.seed_watchlist(s, _SYMBOL)
        await f.seed_bars(s, _SYMBOL, closes=_CLOSES, start=start)
        for i, period_end in enumerate(_PERIOD_ENDS):
            s.add(
                FundamentalsQuarterly(
                    symbol=_SYMBOL,
                    period_end=period_end,
                    line_items={
                        "revenue": _REVENUE[i],
                        "net_income": _NET_INCOME[i],
                        "equity": _EQUITY[i],
                        "gross_profit": _GROSS_PROFIT[i],
                        "free_cash_flow": _FCF[i],
                    },
                )
            )
        await s.commit()


async def _expected_score(asof: dt.datetime) -> Decimal:
    start = asof - dt.timedelta(days=jobs._ANALYSIS_LOOKBACK_DAYS)
    async with async_session() as s:
        rows = await get_bars_range(s, _SYMBOL, start, asof)
    frame = jobs._bars_to_frame(rows)
    return DefaultAnalysisEngine().score_symbol(_SYMBOL, frame, asof).score


async def test_records_fundamental_signals_without_changing_score(clean_db) -> None:
    asof = jobs._today_utc_midnight()
    await _seed()
    expected = await _expected_score(asof)

    await jobs.run_analysis()

    async with async_session() as s:
        recorded = set(
            (
                await s.scalars(
                    sa.select(SignalValue.signal_id).where(SignalValue.symbol == _SYMBOL)
                )
            ).all()
        )
        score = await s.scalar(
            sa.select(AlgorithmSignal.score).where(AlgorithmSignal.symbol == _SYMBOL)
        )
    assert {REVENUE_ACCEL_SIGNAL_ID, EARNINGS_ACCEL_SIGNAL_ID, QUALITY_SIGNAL_ID} <= recorded
    # Observation: fundamentals recorded but not scored -> composite equals engine output.
    assert score == expected
