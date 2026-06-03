"""run_analysis macro-regime observation: records the regime signal_value without
altering the composite score (it is not fed to the scorer)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from backend.analysis.engine import DefaultAnalysisEngine
from backend.analysis.signals.macro.regime import MACRO_REGIME_SIGNAL_ID
from backend.data_ingestion.macro_ingest import upsert_macro_series
from backend.db.models import AlgorithmSignal, SignalValue
from backend.db.queries.market_queries import get_bars_range
from backend.db.session import async_session
from backend.scheduler import jobs
from backend.tests import factories as f

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc
_SYMBOL = "AAPL"
_CLOSES = [100.0 + i * 0.5 for i in range(60)]


@pytest.fixture(autouse=True)
def _trading_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)


async def _seed_bars_and_watchlist() -> None:
    start = dt.date.today() - dt.timedelta(days=70)
    async with async_session() as s:
        await f.seed_watchlist(s, _SYMBOL)
        await f.seed_bars(s, _SYMBOL, closes=_CLOSES, start=start)
        await s.commit()


async def _seed_macro(asof: dt.datetime) -> None:
    ts = asof - dt.timedelta(days=1)
    async with async_session() as s:
        await upsert_macro_series(s, "T10Y2Y", [(ts, Decimal("1.0"))])
        await upsert_macro_series(s, "VIXCLS", [(ts, Decimal("12.0"))])
        await upsert_macro_series(s, "BAMLH0A0HYM2", [(ts, Decimal("2.5"))])
        await s.commit()


async def _algo_score() -> Decimal | None:
    async with async_session() as s:
        return await s.scalar(
            sa.select(AlgorithmSignal.score).where(AlgorithmSignal.symbol == _SYMBOL)
        )


async def _expected_score(asof: dt.datetime) -> Decimal:
    start = asof - dt.timedelta(days=jobs._ANALYSIS_LOOKBACK_DAYS)
    async with async_session() as s:
        rows = await get_bars_range(s, _SYMBOL, start, asof)
    frame = jobs._bars_to_frame(rows)
    return DefaultAnalysisEngine().score_symbol(_SYMBOL, frame, asof).score


async def test_records_regime_signal_without_changing_score(clean_db) -> None:
    asof = jobs._today_utc_midnight()
    await _seed_bars_and_watchlist()
    await _seed_macro(asof)
    expected = await _expected_score(asof)

    await jobs.run_analysis()

    async with async_session() as s:
        regime_value = await s.scalar(
            sa.select(SignalValue.value).where(
                SignalValue.symbol == _SYMBOL,
                SignalValue.signal_id == MACRO_REGIME_SIGNAL_ID,
            )
        )
    assert regime_value is not None
    assert float(regime_value) == pytest.approx(100.0)  # risk_on inputs -> 100
    # The regime is observed, not scored: the composite equals the engine output.
    assert await _algo_score() == expected


async def test_no_macro_data_records_no_regime_signal(clean_db) -> None:
    await _seed_bars_and_watchlist()  # no macro_series seeded

    await jobs.run_analysis()

    async with async_session() as s:
        n = await s.scalar(
            sa.select(sa.func.count())
            .select_from(SignalValue)
            .where(SignalValue.signal_id == MACRO_REGIME_SIGNAL_ID)
        )
    assert n == 0
    assert await _algo_score() is not None  # analysis still produced a score
