"""BrokerAdapter selection — the sacred env-only swap point.

``PortfolioManager`` never imports a concrete broker; it receives a
``BrokerAdapter`` from this factory. Switching adapters is a ``BROKER_ADAPTER`` env
change — no business-logic changes (CLAUDE.md). Phase 1 ships ``paper`` (DB-backed
simulation) and ``mock_real`` (in-memory swap-test double); a real broker is Phase 2.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession

from backend.trading.broker_adapter import BrokerAdapter
from backend.trading.mock_real_broker import MockRealBroker
from backend.trading.paper_broker import PaperBroker

_DEFAULT_ADAPTER = "paper"
_REGISTRY: dict[str, type] = {"paper": PaperBroker, "mock_real": MockRealBroker}


def make_broker(
    session: AsyncSession, *, strategy_version: str | None = None
) -> BrokerAdapter:
    name = os.environ.get("BROKER_ADAPTER", _DEFAULT_ADAPTER)
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"unknown BROKER_ADAPTER={name!r}; registered: {sorted(_REGISTRY)}"
        ) from None
    return cls(session, strategy_version=strategy_version)
