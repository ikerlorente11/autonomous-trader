"""RiskManager — fixed-fractional position sizing.

Turns ranked buy candidates into target share quantities. All sizing parameters
are env-configurable (CLAUDE.md: no hardcoded values). Prices are injected at
construction so the sizing methods keep the brief's signatures
(``compute_position_size(symbol, score, portfolio_value)`` and
``size_positions(candidates, balance)``) without a DB dependency — the
PortfolioManager fetches latest prices and builds the manager per execution.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, Decimal
from typing import Protocol, runtime_checkable

from backend.contracts import AccountBalance, RankedSymbol

_DEFAULT_MAX_POSITION_PCT = Decimal("0.05")
_DEFAULT_MAX_OPEN_POSITIONS = 10
_DEFAULT_MIN_CASH_PCT = Decimal("0.20")


@runtime_checkable
class RiskManager(Protocol):
    def size_positions(
        self, candidates: Sequence[RankedSymbol], balance: AccountBalance
    ) -> dict[str, Decimal]: ...


def _decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return Decimal(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


class FixedFractionalRiskManager:
    """Invest ``MAX_POSITION_PCT`` of portfolio value per symbol, capped by
    ``MAX_OPEN_POSITIONS`` and a ``MIN_CASH_PCT`` dry-powder reserve."""

    def __init__(
        self,
        prices: Mapping[str, Decimal],
        *,
        max_position_pct: Decimal | None = None,
        max_open_positions: int | None = None,
        min_cash_pct: Decimal | None = None,
        open_position_count: int = 0,
    ) -> None:
        self._prices = prices
        self._max_position_pct = (
            max_position_pct
            if max_position_pct is not None
            else _decimal_env("MAX_POSITION_PCT", _DEFAULT_MAX_POSITION_PCT)
        )
        self._max_open_positions = (
            max_open_positions
            if max_open_positions is not None
            else _int_env("MAX_OPEN_POSITIONS", _DEFAULT_MAX_OPEN_POSITIONS)
        )
        self._min_cash_pct = (
            min_cash_pct
            if min_cash_pct is not None
            else _decimal_env("MIN_CASH_PCT", _DEFAULT_MIN_CASH_PCT)
        )
        self._open_position_count = open_position_count

    def compute_position_size(
        self, symbol: str, score: Decimal, portfolio_value: Decimal
    ) -> Decimal:
        price = self._prices.get(symbol)
        if price is None or price <= 0:
            return Decimal(0)
        target_dollars = portfolio_value * self._max_position_pct
        qty = (target_dollars / price).to_integral_value(rounding=ROUND_DOWN)
        return qty if qty > 0 else Decimal(0)

    def size_positions(
        self, candidates: Sequence[RankedSymbol], balance: AccountBalance
    ) -> dict[str, Decimal]:
        investable = balance.total * (Decimal(1) - self._min_cash_pct)
        spendable = min(balance.cash, investable)
        slots = self._max_open_positions - self._open_position_count
        sizes: dict[str, Decimal] = {}
        for candidate in sorted(candidates, key=lambda c: c.rank):
            if slots <= 0:
                break
            symbol = candidate.score.symbol
            qty = self.compute_position_size(symbol, candidate.score.score, balance.total)
            if qty <= 0:
                continue
            price = self._prices[symbol]
            cost = price * qty
            if cost > spendable:
                continue
            sizes[symbol] = qty
            spendable -= cost
            slots -= 1
        return sizes


def make_risk_manager(
    prices: Mapping[str, Decimal], *, open_position_count: int = 0
) -> FixedFractionalRiskManager:
    return FixedFractionalRiskManager(prices, open_position_count=open_position_count)
