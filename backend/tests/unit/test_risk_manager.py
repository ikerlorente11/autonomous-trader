"""FixedFractionalRiskManager position sizing — pure math, no I/O."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.tests.factories import balance, ranked
from backend.trading.risk_manager import FixedFractionalRiskManager

pytestmark = pytest.mark.unit


def _mgr(prices: dict[str, float], **kw) -> FixedFractionalRiskManager:
    return FixedFractionalRiskManager(
        {k: Decimal(str(v)) for k, v in prices.items()}, **kw
    )


def test_position_is_max_pct_of_portfolio_value() -> None:
    mgr = _mgr({"AAPL": 100}, max_position_pct=Decimal("0.05"), min_cash_pct=Decimal("0"))
    sizes = mgr.size_positions([ranked("AAPL", 90)], balance(10_000, equity=0))
    # 5% of 10_000 = 500 ; at 100/share = 5 shares
    assert sizes["AAPL"] == Decimal("5.000000")


def test_max_open_positions_caps_count() -> None:
    mgr = _mgr(
        {"A": 10, "B": 10, "C": 10},
        max_position_pct=Decimal("0.05"),
        min_cash_pct=Decimal("0"),
        max_open_positions=2,
    )
    sizes = mgr.size_positions(
        [ranked("A", 90, rank=1), ranked("B", 80, rank=2), ranked("C", 70, rank=3)],
        balance(10_000),
    )
    assert set(sizes) == {"A", "B"}  # lowest ranks win, third dropped


def test_open_position_count_reduces_slots() -> None:
    mgr = _mgr(
        {"A": 10, "B": 10},
        max_position_pct=Decimal("0.05"),
        min_cash_pct=Decimal("0"),
        max_open_positions=2,
        open_position_count=1,
    )
    sizes = mgr.size_positions([ranked("A", 90, rank=1), ranked("B", 80, rank=2)], balance(10_000))
    assert set(sizes) == {"A"}  # only 1 slot free


def test_min_cash_reserve_limits_spend() -> None:
    # total 1000, reserve 90% -> investable 100; one 5%-of-1000=50$ position fits, cash caps spend
    mgr = _mgr(
        {"A": 10, "B": 10},
        max_position_pct=Decimal("0.05"),
        min_cash_pct=Decimal("0.90"),
        max_open_positions=10,
    )
    sizes = mgr.size_positions([ranked("A", 90, rank=1), ranked("B", 80, rank=2)], balance(1000))
    spent = sum(Decimal("10") * q for q in sizes.values())
    assert spent <= Decimal("100")


def test_fractional_vs_integer_quantity() -> None:
    frac = _mgr({"BRK": 333}, max_position_pct=Decimal("0.05"), min_cash_pct=Decimal("0"), allow_fractional=True)
    whole = _mgr({"BRK": 333}, max_position_pct=Decimal("0.05"), min_cash_pct=Decimal("0"), allow_fractional=False)
    qf = frac.size_positions([ranked("BRK", 90)], balance(10_000))["BRK"]
    # 500 / 333 = 1.501501...
    assert qf == Decimal("1.501501")
    qw = whole.size_positions([ranked("BRK", 90)], balance(10_000))["BRK"]
    assert qw == Decimal("1")


def test_dust_below_min_position_is_skipped() -> None:
    # 5% of 10 = 0.5 €, below MIN_POSITION_EUR=1 -> no position
    mgr = _mgr({"A": 10}, max_position_pct=Decimal("0.05"), min_position_eur=Decimal("1"), min_cash_pct=Decimal("0"))
    sizes = mgr.size_positions([ranked("A", 90)], balance(10))
    assert sizes == {}


def test_unknown_or_nonpositive_price_yields_zero() -> None:
    mgr = _mgr({"A": 0}, min_cash_pct=Decimal("0"))
    assert mgr.compute_position_size("A", Decimal("90"), Decimal("10000")) == Decimal("0")
    assert mgr.compute_position_size("MISSING", Decimal("90"), Decimal("10000")) == Decimal("0")


def test_min_cash_reserve_holds_after_cash_is_partly_spent() -> None:
    # Day 2+: cash 300 of total 1000 with a 20% reserve -> only 100 is spendable.
    # The old min(cash, investable) degenerated to plain `cash` here and spent the
    # reserve to zero over successive runs.
    mgr = _mgr(
        {"A": 10},
        max_position_pct=Decimal("0.05"),
        min_cash_pct=Decimal("0.20"),
        max_open_positions=10,
    )
    sizes = mgr.size_positions([ranked("A", 90)], balance(300, equity=700))
    assert sizes["A"] == Decimal("5.000000")  # 5% of 1000 = 50 <= spendable 100


def test_min_cash_reserve_blocks_spend_at_reserve_floor() -> None:
    # Cash exactly at the reserve: nothing is spendable, no order sized.
    mgr = _mgr(
        {"A": 10},
        max_position_pct=Decimal("0.05"),
        min_cash_pct=Decimal("0.20"),
        max_open_positions=10,
    )
    sizes = mgr.size_positions([ranked("A", 90)], balance(200, equity=800))
    assert sizes == {}
