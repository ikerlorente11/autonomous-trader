"""The BrokerAdapter seam (sacred — see CLAUDE.md).

``PortfolioManager`` depends only on this Protocol, never on a concrete broker.
Switching paper -> real trading is a ``BROKER_ADAPTER`` env change, no code change.
The interface signature is fixed by CLAUDE.md and must not be modified.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from backend.contracts import Order, OrderStatus, Position

__all__ = ["BrokerAdapter", "Order", "Position", "OrderStatus"]


@runtime_checkable
class BrokerAdapter(Protocol):
    def place_order(
        self, symbol: str, side: str, qty: int, order_type: str
    ) -> Order: ...

    def get_positions(self) -> list[Position]: ...

    def get_account_balance(self) -> Decimal: ...

    def get_order_status(self, order_id: str) -> OrderStatus: ...
