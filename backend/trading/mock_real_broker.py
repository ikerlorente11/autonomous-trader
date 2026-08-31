"""MockRealBroker — the in-memory BrokerAdapter swap-test double.

Exists so the Reality Checker's sacred-seam test passes: ``BROKER_ADAPTER=mock_real``
selects this adapter with zero business-logic changes, proving ``PortfolioManager``
is decoupled from any concrete broker. Unlike ``PaperBroker`` (which persists to the
``trade_orders`` ledger), this keeps account state in memory and writes nothing to the
DB. It is a test double, NOT a real broker integration — real broker API calls are
Phase 2. Fills use the latest stored close, as a market order would.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.contracts import Order, OrderSide, OrderState, OrderStatus, Position
from backend.db.queries.market_queries import get_latest_bars

_DEFAULT_STARTING_CASH = Decimal("500")


class MockRealBroker:
    def __init__(
        self,
        session: AsyncSession,
        portfolio_id: int,
        *,
        strategy_version: str | None = None,
        intraday: bool = False,
    ) -> None:
        self._session = session
        self._portfolio_id = portfolio_id
        self._strategy_version = strategy_version
        # Accepted for a uniform factory signature; the in-memory double doesn't price
        # off bar tables, so intraday vs daily is a no-op here.
        self._intraday = intraday
        raw = os.environ.get("STARTING_CASH")
        self._cash = Decimal(raw) if raw and raw.strip() else _DEFAULT_STARTING_CASH
        self._qty: dict[str, Decimal] = {}
        self._avg_cost: dict[str, Decimal] = {}
        self._orders: list[Order] = []

    async def _latest_close(self, symbol: str) -> Decimal | None:
        bars = await get_latest_bars(self._session, [symbol])
        return bars[0].close if bars else None

    async def place_order(
        self, symbol: str, side: str, qty: Decimal, order_type: str
    ) -> Order:
        ts = dt.datetime.now(dt.timezone.utc)
        qty_dec = qty
        side_enum = OrderSide(side)
        order_id = len(self._orders) + 1

        def _record(status: OrderState, price: Decimal | None, reason: str) -> Order:
            order = Order(
                id=order_id,
                symbol=symbol,
                side=side_enum,
                qty=qty_dec,
                price=price,
                status=status,
                reason=reason,
                strategy_version=self._strategy_version,
                ts=ts,
            )
            self._orders.append(order)
            return order

        if qty_dec <= 0:
            return _record(OrderState.REJECTED, None, "non-positive quantity")

        price = await self._latest_close(symbol)
        if price is None or price <= 0:
            return _record(OrderState.REJECTED, None, "no market price available")

        held = self._qty.get(symbol, Decimal(0))
        if side_enum is OrderSide.SELL and held < qty_dec:
            return _record(
                OrderState.REJECTED, None,
                f"insufficient shares to sell ({held} < {qty_dec})",
            )

        if side_enum is OrderSide.BUY:
            new_qty = held + qty_dec
            self._avg_cost[symbol] = (
                held * self._avg_cost.get(symbol, Decimal(0)) + qty_dec * price
            ) / new_qty
            self._qty[symbol] = new_qty
            self._cash -= qty_dec * price
        else:
            self._qty[symbol] = held - qty_dec
            self._cash += qty_dec * price

        return _record(OrderState.FILLED, price, "mock_real fill")

    async def get_positions(self) -> list[Position]:
        out: list[Position] = []
        for symbol, qty in self._qty.items():
            if qty == 0:
                continue
            price = await self._latest_close(symbol)
            avg = self._avg_cost.get(symbol, Decimal(0))
            out.append(
                Position(
                    symbol=symbol,
                    qty=qty,
                    avg_cost=avg,
                    current_price=price,
                    unrealized_pnl=(price - avg) * qty if price is not None else None,
                )
            )
        return out

    async def get_cash(self) -> Decimal:
        return self._cash

    async def get_account_balance(self) -> Decimal:
        equity = Decimal(0)
        for symbol, qty in self._qty.items():
            if qty == 0:
                continue
            price = await self._latest_close(symbol)
            equity += qty * (price if price is not None else self._avg_cost.get(symbol, Decimal(0)))
        return self._cash + equity

    async def settle_open_orders(self, asof: dt.datetime) -> int:
        """Nothing to settle: this double fills on placement, like a real venue would
        for a market order. Present so the daily job calls one method for any adapter."""
        return 0

    async def get_order_status(self, order_id: str) -> OrderStatus:
        idx = int(order_id) - 1
        if idx < 0 or idx >= len(self._orders):
            return OrderStatus(
                order_id=order_id, status=OrderState.REJECTED, filled_qty=Decimal(0)
            )
        order = self._orders[idx]
        filled = order.qty if order.status is OrderState.FILLED else Decimal(0)
        return OrderStatus(
            order_id=order_id,
            status=order.status,
            filled_qty=filled,
            avg_fill_price=order.price if order.status is OrderState.FILLED else None,
        )
