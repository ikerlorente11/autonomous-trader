from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    AlgorithmSignal,
    CashMovement,
    Portfolio,
    PortfolioNav,
    PortfolioPosition,
    TradeOrder,
    Watchlist,
)


async def get_open_positions(
    session: AsyncSession, portfolio_id: int
) -> Sequence[PortfolioPosition]:
    """Current non-zero positions with unrealized P&L for one portfolio."""
    stmt: Select[tuple[PortfolioPosition]] = (
        select(PortfolioPosition)
        .where(
            PortfolioPosition.portfolio_id == portfolio_id,
            PortfolioPosition.qty != 0,
        )
        .order_by(PortfolioPosition.symbol)
    )
    return (await session.scalars(stmt)).all()


async def get_nav_history(
    session: AsyncSession, portfolio_id: int, start: dt.datetime, end: dt.datetime
) -> Sequence[PortfolioNav]:
    """Portfolio NAV (and benchmark) over a time range for the equity curve."""
    stmt: Select[tuple[PortfolioNav]] = (
        select(PortfolioNav)
        .where(
            PortfolioNav.portfolio_id == portfolio_id,
            PortfolioNav.ts >= start,
            PortfolioNav.ts <= end,
        )
        .order_by(PortfolioNav.ts)
    )
    return (await session.scalars(stmt)).all()


async def get_filtered_orders(
    session: AsyncSession,
    portfolio_id: int,
    *,
    symbol: str | None = None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    limit: int = 50,
) -> Sequence[TradeOrder]:
    """Trade orders with optional symbol / date-range filters (trades table)."""
    stmt: Select[tuple[TradeOrder]] = select(TradeOrder).where(
        TradeOrder.portfolio_id == portfolio_id
    )
    if symbol is not None:
        stmt = stmt.where(TradeOrder.symbol == symbol)
    if start is not None:
        stmt = stmt.where(TradeOrder.ts >= start)
    if end is not None:
        stmt = stmt.where(TradeOrder.ts <= end)
    stmt = stmt.order_by(TradeOrder.ts.desc()).limit(limit)
    return (await session.scalars(stmt)).all()


async def get_filled_orders(
    session: AsyncSession, portfolio_id: int
) -> Sequence[TradeOrder]:
    """All filled orders ascending — the closed-trip / round-trip ledger input."""
    stmt: Select[tuple[TradeOrder]] = (
        select(TradeOrder)
        .where(
            TradeOrder.portfolio_id == portfolio_id,
            func.lower(TradeOrder.status) == "filled",
        )
        .order_by(TradeOrder.ts)
    )
    return (await session.scalars(stmt)).all()


async def get_position(
    session: AsyncSession, portfolio_id: int, symbol: str
) -> PortfolioPosition | None:
    """Single position row by (portfolio, symbol) (broker upsert read)."""
    return await session.get(PortfolioPosition, (portfolio_id, symbol))


async def compute_cash(session: AsyncSession, portfolio_id: int) -> Decimal:
    """Cash = Σ deposits − Σ withdrawals − Σ(buy price·qty) + Σ(sell price·qty).

    Cash is a pure function of the append-only cash-movement and order ledgers for
    one portfolio, so it never needs a mutable cash row and is reconstructable after
    any restart.
    """
    contributed = await compute_contributed_capital(session, portfolio_id)
    flow = func.coalesce(
        func.sum(
            case(
                (func.lower(TradeOrder.side) == "buy", TradeOrder.price * TradeOrder.qty),
                else_=-(TradeOrder.price * TradeOrder.qty),
            )
        ),
        0,
    )
    stmt = select(flow).where(
        TradeOrder.portfolio_id == portfolio_id,
        func.lower(TradeOrder.status) == "filled",
    )
    spent = (await session.scalar(stmt)) or Decimal(0)
    return contributed - Decimal(spent)


async def compute_contributed_capital(
    session: AsyncSession, portfolio_id: int
) -> Decimal:
    """Net capital the operator put in: Σ deposits − Σ withdrawals.

    The denominator for true return (adding/removing money is not profit).
    """
    net = func.coalesce(
        func.sum(
            case(
                (CashMovement.kind == "deposit", CashMovement.amount),
                else_=-CashMovement.amount,
            )
        ),
        0,
    )
    stmt = select(net).where(CashMovement.portfolio_id == portfolio_id)
    return Decimal((await session.scalar(stmt)) or 0)


async def count_filled_orders_since(
    session: AsyncSession, portfolio_id: int, since: dt.datetime
) -> int:
    """How many *filled* orders this portfolio wrote at/after ``since`` (idempotency
    guard). Rejected orders are excluded: a run that only produced rejections (e.g. no
    price yet, all-HOLD) must be retryable, not locked out for the day (H2)."""
    stmt = (
        select(func.count())
        .select_from(TradeOrder)
        .where(
            TradeOrder.portfolio_id == portfolio_id,
            TradeOrder.ts >= since,
            func.lower(TradeOrder.status) == "filled",
        )
    )
    return int((await session.scalar(stmt)) or 0)


async def get_latest_nav(
    session: AsyncSession, portfolio_id: int
) -> PortfolioNav | None:
    """Most recent NAV snapshot for one portfolio, if any."""
    stmt = (
        select(PortfolioNav)
        .where(PortfolioNav.portfolio_id == portfolio_id)
        .order_by(PortfolioNav.ts.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def get_first_nav(
    session: AsyncSession, portfolio_id: int
) -> PortfolioNav | None:
    """Earliest NAV snapshot for one portfolio — the benchmark rebasing anchor."""
    stmt = (
        select(PortfolioNav)
        .where(PortfolioNav.portfolio_id == portfolio_id)
        .order_by(PortfolioNav.ts)
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def get_top_ranked_signals(
    session: AsyncSession, asof_date: dt.datetime, limit: int = 20
) -> Sequence[AlgorithmSignal]:
    """Highest-scoring algorithm signals at a given timestamp (buy candidates)."""
    stmt: Select[tuple[AlgorithmSignal]] = (
        select(AlgorithmSignal)
        .where(AlgorithmSignal.ts == asof_date)
        .order_by(AlgorithmSignal.score.desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def get_latest_analysis_ts(session: AsyncSession) -> dt.datetime | None:
    """Timestamp of the most recent analysis run (max algorithm_signals.ts)."""
    stmt = select(func.max(AlgorithmSignal.ts))
    return await session.scalar(stmt)


async def get_unsettled_signals(
    session: AsyncSession, cutoff: dt.datetime, limit: int = 2000
) -> Sequence[AlgorithmSignal]:
    """Actionable signals old enough to evaluate but not yet settled (outcome IS NULL,
    ts <= cutoff). The forward-return settle step fills realized_return / outcome."""
    stmt: Select[tuple[AlgorithmSignal]] = (
        select(AlgorithmSignal)
        .where(
            AlgorithmSignal.ts <= cutoff,
            AlgorithmSignal.outcome.is_(None),
            func.lower(AlgorithmSignal.action).in_(("buy", "sell")),
        )
        .order_by(AlgorithmSignal.ts)
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def get_settled_signals(
    session: AsyncSession, *, actionable: tuple[str, ...] = ("buy", "sell")
) -> Sequence[AlgorithmSignal]:
    """Signals with a recorded outcome — input to the signal-accuracy report."""
    stmt: Select[tuple[AlgorithmSignal]] = (
        select(AlgorithmSignal)
        .where(
            AlgorithmSignal.outcome.is_not(None),
            func.lower(AlgorithmSignal.action).in_(actionable),
        )
        .order_by(AlgorithmSignal.ts)
    )
    return (await session.scalars(stmt)).all()


async def get_active_watchlist(session: AsyncSession) -> Sequence[Watchlist]:
    """Active watchlist symbols with sector / asset-class metadata."""
    stmt: Select[tuple[Watchlist]] = (
        select(Watchlist)
        .where(Watchlist.active.is_(True))
        .order_by(Watchlist.symbol)
    )
    return (await session.scalars(stmt)).all()


async def upsert_watchlist_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    sector: str | None = None,
    asset_class: str | None = None,
) -> Watchlist:
    """Add a symbol to the watchlist (or re-activate it). Provided metadata
    overwrites; omitted metadata is preserved on an existing row. Caller commits."""
    existing = await session.get(Watchlist, symbol)
    if existing is None:
        entry = Watchlist(
            symbol=symbol, sector=sector, asset_class=asset_class, active=True
        )
        session.add(entry)
        await session.flush()
        return entry
    existing.active = True
    if sector is not None:
        existing.sector = sector
    if asset_class is not None:
        existing.asset_class = asset_class
    await session.flush()
    return existing


async def deactivate_watchlist_symbol(session: AsyncSession, symbol: str) -> bool:
    """Soft-remove a symbol (set inactive). Returns False if it was not present."""
    existing = await session.get(Watchlist, symbol)
    if existing is None:
        return False
    existing.active = False
    await session.flush()
    return True


# --------------------------------------------------------------------------- #
# Portfolios + cash movements
# --------------------------------------------------------------------------- #
async def list_portfolios(
    session: AsyncSession, *, active_only: bool = False
) -> Sequence[Portfolio]:
    """All portfolios, ordered by id (creation order)."""
    stmt: Select[tuple[Portfolio]] = select(Portfolio).order_by(Portfolio.id)
    if active_only:
        stmt = stmt.where(Portfolio.active.is_(True))
    return (await session.scalars(stmt)).all()


async def get_portfolio(
    session: AsyncSession, portfolio_id: int
) -> Portfolio | None:
    return await session.get(Portfolio, portfolio_id)


async def get_portfolio_for_update(
    session: AsyncSession, portfolio_id: int
) -> Portfolio | None:
    """Lock the portfolio row (``FOR UPDATE``) so a cash-balance check and the movement
    it authorizes are serialized — two concurrent withdrawals can't both pass the check."""
    stmt = select(Portfolio).where(Portfolio.id == portfolio_id).with_for_update()
    return (await session.scalars(stmt)).one_or_none()


async def count_portfolios(session: AsyncSession) -> int:
    return int((await session.scalar(select(func.count()).select_from(Portfolio))) or 0)


async def resolve_default_portfolio_id(session: AsyncSession) -> int | None:
    """The portfolio used when a request omits ``portfolio_id`` — first active by id."""
    stmt = (
        select(Portfolio.id)
        .where(Portfolio.active.is_(True))
        .order_by(Portfolio.id)
        .limit(1)
    )
    return await session.scalar(stmt)


async def create_portfolio(
    session: AsyncSession, name: str, initial_deposit: Decimal
) -> Portfolio:
    """Create a portfolio and, if positive, seed its budget as the first deposit.
    Caller commits."""
    portfolio = Portfolio(name=name, active=True)
    session.add(portfolio)
    await session.flush()
    if initial_deposit > 0:
        await add_cash_movement(
            session, portfolio.id, "deposit", initial_deposit, note="Initial budget"
        )
    return portfolio


async def rename_portfolio(
    session: AsyncSession, portfolio_id: int, name: str
) -> Portfolio | None:
    portfolio = await session.get(Portfolio, portfolio_id)
    if portfolio is None:
        return None
    portfolio.name = name
    await session.flush()
    return portfolio


async def set_portfolio_strategy_label(
    session: AsyncSession, portfolio_id: int, label: str | None
) -> Portfolio | None:
    """Set which strategy version a portfolio trades (None = base config). Caller commits."""
    portfolio = await session.get(Portfolio, portfolio_id)
    if portfolio is None:
        return None
    portfolio.strategy_label = label
    await session.flush()
    return portfolio


async def delete_portfolio(session: AsyncSession, portfolio_id: int) -> bool:
    """Hard-delete a portfolio; FK cascade removes its trades/positions/NAV/movements.
    Returns False if it does not exist. Caller enforces the last-portfolio guard."""
    portfolio = await session.get(Portfolio, portfolio_id)
    if portfolio is None:
        return False
    await session.delete(portfolio)
    await session.flush()
    return True


async def add_cash_movement(
    session: AsyncSession,
    portfolio_id: int,
    kind: str,
    amount: Decimal,
    *,
    note: str | None = None,
) -> CashMovement:
    """Append a deposit/withdrawal. Caller commits."""
    movement = CashMovement(
        portfolio_id=portfolio_id,
        kind=kind,
        amount=amount,
        ts=dt.datetime.now(dt.timezone.utc),
        note=note,
    )
    session.add(movement)
    await session.flush()
    return movement


async def get_cash_movements(
    session: AsyncSession, portfolio_id: int, limit: int = 100
) -> Sequence[CashMovement]:
    stmt: Select[tuple[CashMovement]] = (
        select(CashMovement)
        .where(CashMovement.portfolio_id == portfolio_id)
        .order_by(CashMovement.ts.desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()
