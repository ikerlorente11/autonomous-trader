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
_DEFAULT_ALLOW_FRACTIONAL = True
_DEFAULT_MIN_POSITION_EUR = Decimal("1")
# Fractional share precision — matches the Numeric(18, 6) qty columns.
_QTY_QUANTUM = Decimal("0.000001")


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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class FixedFractionalRiskManager:
    """Invest ``MAX_POSITION_PCT`` of portfolio value per symbol, capped by
    ``MAX_OPEN_POSITIONS`` and a ``MIN_CASH_PCT`` dry-powder reserve. With
    ``ALLOW_FRACTIONAL`` (default), sizing yields fractional shares so a small
    budget can still take a position in a high-priced symbol; orders whose target
    falls below ``MIN_POSITION_EUR`` are skipped as dust."""

    def __init__(
        self,
        prices: Mapping[str, Decimal],
        *,
        max_position_pct: Decimal | None = None,
        max_open_positions: int | None = None,
        min_cash_pct: Decimal | None = None,
        allow_fractional: bool | None = None,
        min_position_eur: Decimal | None = None,
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
        self._allow_fractional = (
            allow_fractional
            if allow_fractional is not None
            else _bool_env("ALLOW_FRACTIONAL", _DEFAULT_ALLOW_FRACTIONAL)
        )
        self._min_position_eur = (
            min_position_eur
            if min_position_eur is not None
            else _decimal_env("MIN_POSITION_EUR", _DEFAULT_MIN_POSITION_EUR)
        )
        self._open_position_count = open_position_count

    def compute_position_size(
        self, symbol: str, score: Decimal, portfolio_value: Decimal
    ) -> Decimal:
        price = self._prices.get(symbol)
        if price is None or price <= 0:
            return Decimal(0)
        target_dollars = portfolio_value * self._max_position_pct
        if target_dollars < self._min_position_eur:
            return Decimal(0)
        raw_qty = target_dollars / price
        qty = (
            raw_qty.quantize(_QTY_QUANTUM, rounding=ROUND_DOWN)
            if self._allow_fractional
            else raw_qty.to_integral_value(rounding=ROUND_DOWN)
        )
        return qty if qty > 0 else Decimal(0)

    def size_positions(
        self, candidates: Sequence[RankedSymbol], balance: AccountBalance
    ) -> dict[str, Decimal]:
        # The dry-powder reserve is MIN_CASH_PCT of *total*, held back from cash on
        # every run — not a one-shot cap on the first day's spend. min(cash,
        # investable) degenerated to plain `cash` as soon as cash dropped below the
        # investable fraction, silently spending the reserve to zero.
        reserve = balance.total * self._min_cash_pct
        spendable = max(Decimal(0), balance.cash - reserve)
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
