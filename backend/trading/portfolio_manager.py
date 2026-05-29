"""PortfolioManager — orchestrates analysis output into broker actions.

Depends only on the ``BrokerAdapter`` Protocol (injected by the factory), never on
a concrete broker — the sacred seam. It reads market state and writes NAV/position
marks through the DB query layer (services communicate through the DB, CLAUDE.md).
The caller owns the transaction (the scheduler job commits once per batch).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.contracts import AccountBalance, Order, RankedSymbol, SignalAction
from backend.db.models import PortfolioNav
from backend.db.queries.market_queries import get_latest_bars
from backend.db.queries.portfolio_queries import (
    compute_cash,
    get_open_positions,
)
from backend.trading.broker_adapter import BrokerAdapter
from backend.trading.risk_manager import make_risk_manager


class PortfolioManager:
    def __init__(
        self, broker: BrokerAdapter, session: AsyncSession, portfolio_id: int
    ) -> None:
        self._broker = broker
        self._session = session
        self._portfolio_id = portfolio_id

    async def _latest_prices(self, symbols: Sequence[str]) -> dict[str, Decimal]:
        if not symbols:
            return {}
        bars = await get_latest_bars(self._session, symbols)
        return {bar.symbol: bar.close for bar in bars}

    async def _account_balance(self) -> AccountBalance:
        total = await self._broker.get_account_balance()
        cash = await compute_cash(self._session, self._portfolio_id)
        equity = total - cash
        return AccountBalance(cash=cash, equity=equity, total=total)

    async def execute_signals(
        self, signals: Sequence[RankedSymbol]
    ) -> list[Order]:
        buys = [s for s in signals if s.score.action is SignalAction.BUY]
        if not buys:
            return []
        prices = await self._latest_prices([s.score.symbol for s in buys])
        open_positions = await get_open_positions(self._session, self._portfolio_id)
        balance = await self._account_balance()
        risk = make_risk_manager(prices, open_position_count=len(open_positions))
        sizes = risk.size_positions(buys, balance)
        orders: list[Order] = []
        for symbol, qty in sizes.items():
            order = await self._broker.place_order(symbol, "buy", qty, "market")
            orders.append(order)
        return orders

    async def update_positions(self) -> int:
        positions = await get_open_positions(self._session, self._portfolio_id)
        if not positions:
            return 0
        prices = await self._latest_prices([p.symbol for p in positions])
        now = dt.datetime.now(dt.timezone.utc)
        updated = 0
        for position in positions:
            price = prices.get(position.symbol)
            if price is None:
                continue
            position.current_price = price
            position.unrealized_pnl = (price - position.avg_cost) * position.qty
            position.updated_at = now
            updated += 1
        await self._session.flush()
        return updated

    async def snapshot_nav(
        self, ts: dt.datetime | None = None
    ) -> PortfolioNav:
        as_of = ts or dt.datetime.now(dt.timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cash = await compute_cash(self._session, self._portfolio_id)
        positions = await get_open_positions(self._session, self._portfolio_id)
        prices = await self._latest_prices([p.symbol for p in positions])
        equity = sum(
            (p.qty * prices.get(p.symbol, p.avg_cost) for p in positions),
            Decimal(0),
        )
        total = cash + equity
        row = {
            "portfolio_id": self._portfolio_id,
            "ts": as_of,
            "cash": cash,
            "equity": equity,
            "total": total,
        }
        stmt = insert(PortfolioNav).values(row)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PortfolioNav.portfolio_id, PortfolioNav.ts],
            set_={"cash": cash, "equity": equity, "total": total},
        )
        await self._session.execute(stmt)
        return PortfolioNav(
            portfolio_id=self._portfolio_id,
            ts=as_of,
            cash=cash,
            equity=equity,
            total=total,
        )
