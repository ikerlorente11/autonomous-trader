"""PaperBroker — the only BrokerAdapter implementation in Phase 1.

Simulates instant fills against the latest stored close with a configurable
slippage model. It conforms to the sacred async ``BrokerAdapter`` Protocol
(``backend/trading/broker_adapter.py``): every method is ``async`` because the
whole stack is async SQLAlchemy and the real-broker swap target is network-bound.

Cash is never stored: it is reconstructed from the append-only cash-movement and
``trade_orders`` ledgers for this broker's ``portfolio_id`` (see ``compute_cash``).
The caller owns the transaction — PaperBroker flushes its writes but does not commit.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

from sqlalchemy import insert as sa_insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.contracts import (
    Order,
    OrderSide,
    OrderState,
    OrderStatus,
    Position,
)
from backend.data_ingestion.calendar import nth_prior_trading_day
from backend.db.models import PortfolioPosition, TradeOrder
from backend.db.queries.market_queries import (
    get_first_bar_from,
    get_latest_bars,
    get_latest_intraday_bars,
)
from backend.db.queries.portfolio_queries import (
    compute_cash,
    get_open_positions,
    get_position,
)

# Order types the seam understands. "market" fills against the latest stored price;
# "market_on_open" is accepted now and filled at the next session's OPEN — the first
# price actually obtainable after a pre-market decision. Filling at the last close (as
# every daily order did until 2026-08-31) means trading at a price that had already
# happened when the signal was computed, and it is systematically ~0.08% favourable on
# entries. See docs/diagnostics/08-revision-2026-08.md §6.1.
MARKET_ON_OPEN = "market_on_open"
# A pending order this many sessions old is cancelled rather than filled at a price
# that no longer has anything to do with the decision that produced it.
_DEFAULT_PENDING_EXPIRY_SESSIONS = 3

_DEFAULT_SLIPPAGE_PCT = Decimal("0.001")
_DEFAULT_COMMISSION_PCT = Decimal("0")
_DEFAULT_COMMISSION_PER_ORDER = Decimal("0")


def _pending_expiry_sessions() -> int:
    raw = os.environ.get("PENDING_ORDER_EXPIRY_SESSIONS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_PENDING_EXPIRY_SESSIONS
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_PENDING_EXPIRY_SESSIONS


def _decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return Decimal(raw)


class PaperBroker:
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
        # Microtrading prices off intraday_bars; daily off market_bars. A constructor
        # arg (like portfolio_id), NOT part of place_order — the BrokerAdapter seam is
        # unchanged. Default False keeps the daily path byte-for-byte identical.
        self._intraday = intraday
        self._slippage_pct = _decimal_env("SLIPPAGE_PCT", _DEFAULT_SLIPPAGE_PCT)
        # P10: a commission model so churn has a visible cost in the A/B. Global (env),
        # not per-version: a trade cost is a market reality every version pays equally.
        # Defaults of 0 leave cash/NAV byte-for-byte unchanged until configured.
        self._commission_pct = _decimal_env("COMMISSION_PCT", _DEFAULT_COMMISSION_PCT)
        self._commission_per_order = _decimal_env(
            "COMMISSION_PER_ORDER", _DEFAULT_COMMISSION_PER_ORDER
        )

    async def _latest_closes(self, symbols: list[str]) -> dict[str, Decimal]:
        if not symbols:
            return {}
        fetch = get_latest_intraday_bars if self._intraday else get_latest_bars
        return {bar.symbol: bar.close for bar in await fetch(self._session, symbols)}

    async def _latest_close(self, symbol: str) -> Decimal | None:
        return (await self._latest_closes([symbol])).get(symbol)

    def _commission_for(self, qty: Decimal, fill_price: Decimal) -> Decimal:
        return qty * fill_price * self._commission_pct + self._commission_per_order

    async def _write_order(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        price: Decimal | None,
        status: OrderState,
        reason: str,
        ts: dt.datetime,
        commission: Decimal | None = None,
    ) -> Order:
        stmt = (
            sa_insert(TradeOrder)
            .values(
                portfolio_id=self._portfolio_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                commission=commission,
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
            commission=commission,
            status=status,
            reason=reason,
            strategy_version=self._strategy_version,
            ts=ts,
        )

    async def _apply_buy(self, symbol: str, qty: Decimal, fill_price: Decimal) -> None:
        existing = await get_position(self._session, self._portfolio_id, symbol)
        if existing is None:
            self._session.add(
                PortfolioPosition(
                    portfolio_id=self._portfolio_id,
                    symbol=symbol,
                    qty=qty,
                    avg_cost=fill_price,
                )
            )
            return
        if existing.qty <= 0:
            # Re-entry into a flat row is a fresh position: the previous trip's
            # high-water mark must not seed the new trailing stop, or the stop fires
            # on the first tick (the old peak is, by construction, above the price
            # that triggered the previous stop-out).
            existing.qty = qty
            existing.avg_cost = fill_price
            existing.high_water_mark = None
            return
        new_qty = existing.qty + qty
        existing.avg_cost = (
            (existing.qty * existing.avg_cost) + (qty * fill_price)
        ) / new_qty
        existing.qty = new_qty

    async def _apply_sell(self, symbol: str, qty: Decimal) -> None:
        existing = await get_position(self._session, self._portfolio_id, symbol)
        if existing is None:
            return
        existing.qty = existing.qty - qty
        if existing.qty <= 0:
            # Flat: clear the stale mark so a closed row doesn't carry a phantom
            # unrealized P&L into direct/analytics reads (diagnostics P8). The app
            # already filters qty != 0, so NAV/equity were correct; this fixes the
            # raw column for anyone summing it without the filter.
            existing.unrealized_pnl = Decimal(0)
            # And drop the peak for the same reason _apply_buy resets it: a closed
            # trip's high-water mark is history, not state for the next entry.
            existing.high_water_mark = None

    async def place_order(
        self, symbol: str, side: str, qty: Decimal, order_type: str
    ) -> Order:
        ts = dt.datetime.now(dt.timezone.utc)
        qty_dec = qty
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

        if order_type == MARKET_ON_OPEN:
            # Accepted, not filled: the fill price is the next session's open, which
            # does not exist yet at 08:00 UTC. Cash and positions move at settlement.
            return await self._write_order(
                symbol, side, qty_dec, None, OrderState.PENDING,
                "queued for the next open", ts,
            )

        market_price = await self._latest_close(symbol)
        if market_price is None or market_price <= 0:
            return await self._write_order(
                symbol, side, qty_dec, None, OrderState.REJECTED,
                "no market price available", ts,
            )

        if side_enum is OrderSide.SELL:
            # Row-locked read: a concurrent seller (another job/process) holds the
            # lock until commit, so this check sees the settled qty, never a stale
            # snapshot — duplicate sells reject instead of minting phantom cash.
            position = await get_position(
                self._session, self._portfolio_id, symbol, for_update=True
            )
            held = position.qty if position else Decimal(0)
            if held < qty_dec:
                return await self._write_order(
                    symbol, side, qty_dec, None, OrderState.REJECTED,
                    f"insufficient shares to sell ({held} < {qty_dec})", ts,
                )

        direction = Decimal(1) if side_enum is OrderSide.BUY else Decimal(-1)
        fill_price = market_price * (Decimal(1) + direction * self._slippage_pct)
        commission = self._commission_for(qty_dec, fill_price)

        if side_enum is OrderSide.BUY:
            # A real broker (the seam's swap target) rejects an unfunded buy; the
            # paper double must too, or slippage/commission overshoot drives the
            # reconstructed cash ledger negative.
            cash = await self.get_cash()
            cost = qty_dec * fill_price + commission
            if cost > cash:
                return await self._write_order(
                    symbol, side, qty_dec, None, OrderState.REJECTED,
                    f"insufficient cash ({cash:.2f} < {cost:.2f})", ts,
                )

        order = await self._write_order(
            symbol, side, qty_dec, fill_price, OrderState.FILLED, "paper fill", ts,
            commission=commission,
        )
        if side_enum is OrderSide.BUY:
            await self._apply_buy(symbol, qty_dec, fill_price)
        else:
            await self._apply_sell(symbol, qty_dec)
        await self._session.flush()
        return order

    async def get_positions(self) -> list[Position]:
        rows = await get_open_positions(self._session, self._portfolio_id)
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

    async def get_cash(self) -> Decimal:
        return await compute_cash(self._session, self._portfolio_id)

    async def get_account_balance(self) -> Decimal:
        cash = await self.get_cash()
        positions = await get_open_positions(self._session, self._portfolio_id)
        symbols = [p.symbol for p in positions]
        prices = await self._latest_closes(symbols)
        equity = sum(
            (p.qty * prices.get(p.symbol, p.avg_cost) for p in positions),
            Decimal(0),
        )
        return cash + equity

    async def settle_open_orders(self, asof: dt.datetime) -> int:
        """Fill pending market-on-open orders at their session's open. Returns fills.

        Runs after the bars land, so the open of the session the order was queued for
        finally exists. Every guard from the immediate path applies again at settlement
        — the price moved, and a protective stop may have already sold the shares a
        pending signal-exit was going to sell."""
        pending = (
            await self._session.scalars(
                select(TradeOrder)
                .where(
                    TradeOrder.portfolio_id == self._portfolio_id,
                    TradeOrder.status == OrderState.PENDING.value,
                )
                # Sells first: they free the cash the buys of the same batch need.
                .order_by((TradeOrder.side == "buy"), TradeOrder.ts)
            )
        ).all()

        filled = 0
        for order in pending:
            bar = await get_first_bar_from(self._session, order.symbol, order.ts.date())
            if bar is None or bar.open is None or bar.open <= 0:
                if self._is_expired(order, asof):
                    order.status = OrderState.CANCELLED.value
                    order.reason = "expired: no open price within the fill window"
                continue

            side_enum = OrderSide(order.side)
            direction = Decimal(1) if side_enum is OrderSide.BUY else Decimal(-1)
            fill_price = bar.open * (Decimal(1) + direction * self._slippage_pct)
            commission = self._commission_for(order.qty, fill_price)

            if side_enum is OrderSide.SELL:
                position = await get_position(
                    self._session, self._portfolio_id, order.symbol, for_update=True
                )
                held = position.qty if position else Decimal(0)
                if held < order.qty:
                    order.status = OrderState.REJECTED.value
                    order.reason = f"insufficient shares to sell ({held} < {order.qty})"
                    continue
            else:
                cash = await self.get_cash()
                cost = order.qty * fill_price + commission
                if cost > cash:
                    order.status = OrderState.REJECTED.value
                    order.reason = f"insufficient cash ({cash:.2f} < {cost:.2f})"
                    continue

            order.price = fill_price
            order.commission = commission
            order.status = OrderState.FILLED.value
            order.reason = f"market-on-open fill @ {bar.ts.date().isoformat()}"
            if side_enum is OrderSide.BUY:
                await self._apply_buy(order.symbol, order.qty, fill_price)
            else:
                await self._apply_sell(order.symbol, order.qty)
            await self._session.flush()
            filled += 1

        await self._session.flush()
        return filled

    def _is_expired(self, order: TradeOrder, asof: dt.datetime) -> bool:
        cutoff = nth_prior_trading_day(asof.date(), _pending_expiry_sessions())
        return cutoff is not None and order.ts.date() < cutoff

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
