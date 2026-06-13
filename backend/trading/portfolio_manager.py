"""PortfolioManager — orchestrates analysis output into broker actions.

Depends only on the ``BrokerAdapter`` Protocol (injected by the factory), never on
a concrete broker — the sacred seam. It reads market state and writes NAV/position
marks through the DB query layer (services communicate through the DB, CLAUDE.md).
The caller owns the transaction (the scheduler job commits once per batch).
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analysis.config import StrategyConfig
from backend.contracts import AccountBalance, Order, RankedSymbol, SignalAction
from backend.db.models import PortfolioNav
from backend.db.queries.market_queries import (
    get_close_after,
    get_close_asof,
    get_latest_bars,
    get_latest_intraday_bars,
)
from backend.db.queries.portfolio_queries import (
    compute_cash,
    get_first_nav,
    get_open_positions,
    get_recently_sold_symbols,
)
from backend.trading.broker_adapter import BrokerAdapter
from backend.trading.risk_manager import make_risk_manager

_BENCHMARK_SYMBOL = os.environ.get("BENCHMARK_SYMBOL", "SPY")


class PortfolioManager:
    def __init__(
        self,
        broker: BrokerAdapter,
        session: AsyncSession,
        portfolio_id: int,
        config: StrategyConfig | None = None,
        *,
        intraday: bool = False,
    ) -> None:
        self._broker = broker
        self._session = session
        self._portfolio_id = portfolio_id
        self._config = config
        # Microtrading marks/sizes off intraday_bars; daily off market_bars. The
        # benchmark line stays daily (SPY daily close) regardless. Default False keeps
        # the daily path unchanged.
        self._intraday = intraday

    async def _latest_prices(self, symbols: Sequence[str]) -> dict[str, Decimal]:
        if not symbols:
            return {}
        fetch = get_latest_intraday_bars if self._intraday else get_latest_bars
        return {bar.symbol: bar.close for bar in await fetch(self._session, symbols)}

    async def _account_balance(self) -> AccountBalance:
        # Cash, equity and total all come from the broker — never the DB ledger directly
        # — so the balance reconciles for any adapter, including the in-memory MockRealBroker.
        total = await self._broker.get_account_balance()
        cash = await self._broker.get_cash()
        equity = total - cash
        return AccountBalance(cash=cash, equity=equity, total=total)

    @staticmethod
    def _mark(position, prices: dict[str, Decimal]) -> Decimal:
        # Mark to the latest bar; if absent, fall back to the last persisted current_price,
        # only then to avg_cost. Falling straight to avg_cost would silently freeze a
        # stale position at break-even and hide the missing-price gap (CR3).
        price = prices.get(position.symbol)
        if price is not None:
            return price
        if position.current_price is not None:
            return position.current_price
        return position.avg_cost

    async def execute_signals(
        self, signals: Sequence[RankedSymbol]
    ) -> list[Order]:
        open_positions = await get_open_positions(self._session, self._portfolio_id)
        held = {p.symbol: p for p in open_positions}
        orders: list[Order] = []

        # Exits first: a held name whose score has decayed to a SELL is liquidated
        # in full. Doing this before sizing buys frees the freed cash for entries
        # (the broker flushes each fill, so the balance read below sees it).
        for signal in signals:
            if signal.score.action is not SignalAction.SELL:
                continue
            position = held.get(signal.score.symbol)
            if position is None:
                continue
            order = await self._broker.place_order(
                position.symbol, "sell", position.qty, "market"
            )
            orders.append(order)

        # Entries: size the buy candidates against current cash.
        buys = [s for s in signals if s.score.action is SignalAction.BUY]
        buys = await self._filter_entries(buys, held)
        if buys:
            prices = await self._latest_prices([s.score.symbol for s in buys])
            balance = await self._account_balance()
            risk = make_risk_manager(prices, open_position_count=len(open_positions))
            sizes = risk.size_positions(buys, balance)
            for symbol, qty in sizes.items():
                order = await self._broker.place_order(symbol, "buy", qty, "market")
                orders.append(order)

        return orders

    async def _filter_entries(
        self, buys: list[RankedSymbol], held: dict[str, object]
    ) -> list[RankedSymbol]:
        """Apply per-version entry guards (no-op when no config / defaults):
        - P6: drop names already held unless pyramiding is allowed.
        - P2: drop names sold within the re-entry cooldown window (anti-whipsaw)."""
        if self._config is None or not buys:
            return buys
        trading = self._config.trading
        allow_pyramiding = (
            True if trading.allow_pyramiding is None else trading.allow_pyramiding
        )
        if not allow_pyramiding:
            buys = [s for s in buys if s.score.symbol not in held]
        cooldown_days = trading.stop_reentry_cooldown_days
        if cooldown_days and cooldown_days > 0 and buys:
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cooldown_days)
            blocked = await get_recently_sold_symbols(
                self._session, self._portfolio_id, since
            )
            buys = [s for s in buys if s.score.symbol not in blocked]
        return buys

    async def update_positions(self) -> tuple[int, list[str]]:
        """Refresh marks. Returns (updated_count, stale_symbols) — stale symbols have
        no fresh bar and keep their last mark; the caller can surface the gap."""
        positions = await get_open_positions(self._session, self._portfolio_id)
        if not positions:
            return 0, []
        prices = await self._latest_prices([p.symbol for p in positions])
        now = dt.datetime.now(dt.timezone.utc)
        updated = 0
        stale: list[str] = []
        for position in positions:
            price = prices.get(position.symbol)
            if price is None:
                stale.append(position.symbol)
                continue
            position.current_price = price
            position.unrealized_pnl = (price - position.avg_cost) * position.qty
            position.updated_at = now
            updated += 1
        await self._session.flush()
        return updated, stale

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
            (p.qty * self._mark(p, prices) for p in positions),
            Decimal(0),
        )
        total = cash + equity
        benchmark = await self._benchmark_value(as_of, total)
        row = {
            "portfolio_id": self._portfolio_id,
            "ts": as_of,
            "cash": cash,
            "equity": equity,
            "total": total,
            "benchmark_value": benchmark,
        }
        stmt = insert(PortfolioNav).values(row)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PortfolioNav.portfolio_id, PortfolioNav.ts],
            set_={
                "cash": cash,
                "equity": equity,
                "total": total,
                "benchmark_value": benchmark,
            },
        )
        await self._session.execute(stmt)
        return PortfolioNav(
            portfolio_id=self._portfolio_id,
            ts=as_of,
            cash=cash,
            equity=equity,
            total=total,
            benchmark_value=benchmark,
        )

    async def _benchmark_value(
        self, as_of: dt.datetime, total: Decimal
    ) -> Decimal | None:
        """A buy-and-hold benchmark line, rebased so it starts at the portfolio's first
        NAV. Value = first_nav.total · (benchmark_close_now / benchmark_close_at_start).
        Return-based, so alpha/beta are correct; on the first snapshot it equals NAV so
        the two curves start together. None when the benchmark has no stored bar."""
        now_bar = await get_close_asof(self._session, _BENCHMARK_SYMBOL, as_of)
        if now_bar is None or now_bar.close <= 0:
            return None
        first_nav = await get_first_nav(self._session, self._portfolio_id)
        if first_nav is None:
            return total
        # P9: anchor on the first real benchmark bar at/after inception (not the latest
        # one at/before it), so rebasing is stable even if the first NAV predates a bar.
        start_bar = await get_close_after(
            self._session, _BENCHMARK_SYMBOL, first_nav.ts
        )
        if start_bar is None or start_bar.close <= 0:
            return total
        return first_nav.total * (now_bar.close / start_bar.close)
