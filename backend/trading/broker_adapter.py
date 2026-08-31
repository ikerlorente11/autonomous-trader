"""The BrokerAdapter seam (sacred — see CLAUDE.md).

``PortfolioManager`` depends only on this Protocol, never on a concrete broker.
Switching paper -> real trading is a ``BROKER_ADAPTER`` env change, no code change.

The methods are ``async``: the whole stack is async (SQLAlchemy ``AsyncSession``)
and a real broker adapter — the env-only swap target — is network-bound, so the
interface is async-first. The async qualifier is the implementation reality every
adapter (PaperBroker, MockRealBroker, a future real broker) already shares. ``qty``
is ``Decimal`` (not ``int``) so the seam supports fractional shares — the only way a
small budget can take a position in a high-priced symbol; every adapter honours it.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Protocol, runtime_checkable

from backend.contracts import Order, OrderStatus, Position

__all__ = ["BrokerAdapter", "Order", "Position", "OrderStatus"]


@runtime_checkable
class BrokerAdapter(Protocol):
    async def place_order(
        self, symbol: str, side: str, qty: Decimal, order_type: str
    ) -> Order: ...

    async def get_positions(self) -> list[Position]: ...

    async def get_account_balance(self) -> Decimal: ...

    # Cash component of the balance, broker-authoritative. PortfolioManager builds its
    # AccountBalance (cash/equity/total) purely from broker calls — it must not reach
    # into the DB ledger directly, or an in-memory adapter (MockRealBroker) would report
    # a cash that doesn't reconcile with its own total.
    async def get_cash(self) -> Decimal: ...

    async def get_order_status(self, order_id: str) -> OrderStatus: ...

    # Settle whatever the adapter still owes: orders accepted but not yet filled.
    # A real venue does this itself and its adapter returns 0 (the fill shows up via
    # get_order_status); the paper doubles owe their own market-on-open fills, so they
    # do the work here. Keeping it on the seam means the daily job calls the same
    # method whatever adapter is wired — the env-only swap survives.
    async def settle_open_orders(self, asof: dt.datetime) -> int: ...
