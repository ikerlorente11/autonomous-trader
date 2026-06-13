"""Test data builders. Pure DTO builders here; DB-row seeders live alongside the
integration tests that use them."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from backend.contracts import (
    AccountBalance,
    IndicatorResult,
    OHLCVBar,
    RankedSymbol,
    SignalAction,
    SymbolScore,
)

UTC = dt.timezone.utc


def bar(
    symbol: str = "AAPL",
    *,
    ts: dt.datetime | None = None,
    close: float = 100.0,
    volume: int = 1_000_000,
) -> OHLCVBar:
    when = ts or dt.datetime(2026, 5, 29, tzinfo=UTC)
    c = Decimal(str(close))
    return OHLCVBar(
        symbol=symbol,
        ts=when,
        open=c,
        high=c,
        low=c,
        close=c,
        volume=volume,
        adj_close=c,
    )


def bar_series(
    symbol: str = "AAPL",
    *,
    closes: Sequence[float],
    start: dt.date = dt.date(2026, 1, 1),
) -> list[OHLCVBar]:
    """One bar per calendar day from ``start`` (test fixture; gaps don't matter)."""
    return [
        bar(symbol, ts=dt.datetime(start.year, start.month, start.day, tzinfo=UTC) + dt.timedelta(days=i), close=c)
        for i, c in enumerate(closes)
    ]


def indicator(signal_id: str, value: float, *, symbol: str = "AAPL") -> IndicatorResult:
    return IndicatorResult(
        symbol=symbol,
        ts=dt.datetime(2026, 5, 29, tzinfo=UTC),
        signal_id=signal_id,
        value=Decimal(str(value)),
    )


def symbol_score(
    symbol: str,
    score: float,
    *,
    action: SignalAction = SignalAction.BUY,
    completeness: float | None = 1.0,
) -> SymbolScore:
    return SymbolScore(
        symbol=symbol,
        ts=dt.datetime(2026, 5, 29, tzinfo=UTC),
        score=Decimal(str(score)),
        action=action,
        data_completeness=None if completeness is None else Decimal(str(completeness)),
    )


def ranked(symbol: str, score: float, *, rank: int = 1) -> RankedSymbol:
    return RankedSymbol(rank=rank, score=symbol_score(symbol, score))


def balance(cash: float, *, equity: float = 0.0) -> AccountBalance:
    return AccountBalance(
        cash=Decimal(str(cash)),
        equity=Decimal(str(equity)),
        total=Decimal(str(cash + equity)),
    )


# --------------------------------------------------------------------------- #
# DB-row seeders (used by integration tests; caller's transaction owns commit)
# --------------------------------------------------------------------------- #
async def seed_portfolio(
    session, *, name: str = "Test", deposit: float = 10_000.0, kind: str = "daily"
) -> int:
    from backend.db.queries.portfolio_queries import create_portfolio

    p = await create_portfolio(session, name, Decimal(str(deposit)), kind=kind)
    await session.flush()
    return p.id


async def seed_intraday_bars(
    session, symbol: str, *, closes: Sequence[float], start: dt.datetime, step_min: int = 5
) -> None:
    """One intraday bar per ``step_min`` minutes from ``start`` (micro test fixture)."""
    from backend.contracts import IntradayBar
    from backend.data_ingestion.intraday_ingest import upsert_intraday_bars

    bars = []
    for i, c in enumerate(closes):
        price = Decimal(str(c))
        bars.append(
            IntradayBar(
                symbol=symbol,
                ts=start + dt.timedelta(minutes=step_min * i),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1000,
            )
        )
    await upsert_intraday_bars(session, bars)


async def seed_bars(session, symbol: str, *, closes: Sequence[float], start: dt.date = dt.date(2026, 5, 1)) -> None:
    from backend.data_ingestion.ingest import upsert_bars

    await upsert_bars(session, bar_series(symbol, closes=closes, start=start))


async def seed_latest_bar(session, symbol: str, *, close: float, ts: dt.datetime | None = None) -> None:
    from backend.data_ingestion.ingest import upsert_bars

    await upsert_bars(session, [bar(symbol, ts=ts, close=close)])


async def seed_watchlist(session, *symbols: str) -> None:
    from backend.db.queries.portfolio_queries import upsert_watchlist_symbol

    for s in symbols:
        await upsert_watchlist_symbol(session, s)


async def seed_position(
    session,
    portfolio_id: int,
    symbol: str,
    *,
    qty: float,
    avg_cost: float,
    high_water_mark: float | None = None,
) -> None:
    from backend.db.models import PortfolioPosition

    session.add(
        PortfolioPosition(
            portfolio_id=portfolio_id,
            symbol=symbol,
            qty=Decimal(str(qty)),
            avg_cost=Decimal(str(avg_cost)),
            high_water_mark=None if high_water_mark is None else Decimal(str(high_water_mark)),
        )
    )
    await session.flush()
