"""PaperBroker — the only BrokerAdapter implementation in Phase 1.

Simulates instant fills against the latest stored close with a configurable
slippage model. It conforms to the sacred ``BrokerAdapter`` Protocol
(``backend/trading/broker_adapter.py``); the only deliberate divergence is that
its methods are ``async`` — the whole stack is async SQLAlchemy and a real broker
adapter (the env-only swap target) is network-bound and would be async too. The
sync Protocol shape is left untouched; ``runtime_checkable`` isinstance still
passes (it checks attribute presence, not coroutine-ness).

Cash is never stored: it is reconstructed from the append-only ``trade_orders``
ledger (see ``compute_cash_from_ledger``). The caller owns the transaction —
PaperBroker flushes its writes but does not commit.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

from sqlalchemy import insert as sa_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.contracts import (
    Order,
    OrderSide,
    OrderState,
    OrderStatus,
    Position,
)
from backend.db.models import PortfolioPosition, TradeOrder
from backend.db.queries.market_queries import get_latest_bars
from backend.db.queries.portfolio_queries import (
    compute_cash_from_ledger,
    get_open_positions,
    get_position,
)

_DEFAULT_STARTING_CASH = Decimal("100000")
_DEFAULT_SLIPPAGE_PCT = Decimal("0.001")


def _decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return Decimal(raw)


class PaperBroker:
    def __init__(
        self,
        session: AsyncSession,
        *,
        strategy_version: str | None = None,
    ) -> None:
        self._session = session
        self._strategy_version = strategy_version
        self._starting_cash = _decimal_env("STARTING_CASH", _DEFAULT_STARTING_CASH)
        self._slippage_pct = _decimal_env("SLIPPAGE_PCT", _DEFAULT_SLIPPAGE_PCT)

    async def _latest_close(self, symbol: str) -> Decimal | None:
        bars = await get_latest_bars(self._session, [symbol])
        return bars[0].close if bars else None

    async def _write_order(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        price: Decimal | None,
        status: OrderState,
        reason: str,
        ts: dt.datetime,
    ) -> Order:
        stmt = (
            sa_insert(TradeOrder)
            .values(
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                status=status.value,
                reason=reason,
                strategy_version=self._strategy_version,
                ts=ts,
            )
            .returning(TradeOrder.id)
        )
        order_id = await self._session.scalar(stmt)
        return Order(
            id=order_id,
            symbol=symbol,
            side=OrderSide(side),
            qty=qty,
            price=price,
            status=status,
            reason=reason,
            strategy_version=self._strategy_version,
            ts=ts,
        )

    async def _apply_buy(self, symbol: str, qty: Decimal, fill_price: Decimal) -> None:
        existing = await get_position(self._session, symbol)
        if existing is None:
            self._session.add(
                PortfolioPosition(symbol=symbol, qty=qty, avg_cost=fill_price)
            )
            return
        new_qty = existing.qty + qty
        existing.avg_cost = (
            (existing.qty * existing.avg_cost) + (qty * fill_price)
        ) / new_qty
        existing.qty = new_qty

    async def _apply_sell(self, symbol: str, qty: Decimal) -> None:
        existing = await get_position(self._session, symbol)
        if existing is None:
            return
        existing.qty = existing.qty - qty

    async def place_order(
        self, symbol: str, side: str, qty: int, order_type: str
    ) -> Order:
        ts = dt.datetime.now(dt.timezone.utc)
        qty_dec = Decimal(qty)
        try:
            side_enum = OrderSide(side)
        except ValueError:
            return await self._write_order(
                symbol, side, qty_dec, None, OrderState.REJECTED,
                f"invalid side: {side!r}", ts,
            )

        if qty_dec <= 0:
            return await self._write_order(
                symbol, side, qty_dec, None, OrderState.REJECTED,
                "non-positive quantity", ts,
            )

        market_price = await self._latest_close(symbol)
        if market_price is None or market_price <= 0:
            return await self._write_order(
                symbol, side, qty_dec, None, OrderState.REJECTED,
                "no market price available", ts,
            )

        if side_enum is OrderSide.SELL:
            position = await get_position(self._session, symbol)
            held = position.qty if position else Decimal(0)
            if held < qty_dec:
                return await self._write_order(
                    symbol, side, qty_dec, None, OrderState.REJECTED,
                    f"insufficient shares to sell ({held} < {qty_dec})", ts,
                )

        direction = Decimal(1) if side_enum is OrderSide.BUY else Decimal(-1)
        fill_price = market_price * (Decimal(1) + direction * self._slippage_pct)

        order = await self._write_order(
            symbol, side, qty_dec, fill_price, OrderState.FILLED, "paper fill", ts,
        )
        if side_enum is OrderSide.BUY:
            await self._apply_buy(symbol, qty_dec, fill_price)
        else:
            await self._apply_sell(symbol, qty_dec)
        await self._session.flush()
        return order

    async def get_positions(self) -> list[Position]:
        rows = await get_open_positions(self._session)
        return [
            Position(
                symbol=r.symbol,
                qty=r.qty,
                avg_cost=r.avg_cost,
                current_price=r.current_price,
                unrealized_pnl=r.unrealized_pnl,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def get_account_balance(self) -> Decimal:
        cash = await compute_cash_from_ledger(self._session, self._starting_cash)
        positions = await get_open_positions(self._session)
        symbols = [p.symbol for p in positions]
        prices: dict[str, Decimal] = {}
        if symbols:
            for bar in await get_latest_bars(self._session, symbols):
                prices[bar.symbol] = bar.close
        equity = sum(
            (p.qty * prices.get(p.symbol, p.avg_cost) for p in positions),
            Decimal(0),
        )
        return cash + equity

    async def get_order_status(self, order_id: str) -> OrderStatus:
        order = await self._session.get(TradeOrder, int(order_id))
        if order is None:
            return OrderStatus(
                order_id=order_id, status=OrderState.REJECTED, filled_qty=Decimal(0)
            )
        status = OrderState(order.status)
        filled = order.qty if status is OrderState.FILLED else Decimal(0)
        return OrderStatus(
            order_id=order_id,
            status=status,
            filled_qty=filled,
            avg_fill_price=order.price if status is OrderState.FILLED else None,
        )
