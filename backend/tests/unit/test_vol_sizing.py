"""Equal-risk (vol-targeted) sizing in FixedFractionalRiskManager."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.contracts import AccountBalance, RankedSymbol, SignalAction, SymbolScore
from backend.trading.risk_manager import FixedFractionalRiskManager

pytestmark = pytest.mark.unit

import datetime as dt

_ASOF = dt.datetime(2026, 5, 29, tzinfo=dt.timezone.utc)


def _candidate(symbol: str, rank: int = 1) -> RankedSymbol:
    return RankedSymbol(
        rank=rank,
        score=SymbolScore(
            symbol=symbol, ts=_ASOF, score=Decimal("80"),
            action=SignalAction.BUY, data_completeness=Decimal("1"),
        ),
    )


def _balance(total: float) -> AccountBalance:
    t = Decimal(str(total))
    return AccountBalance(cash=t, equity=Decimal(0), total=t)


def test_vol_target_sizes_by_stop_distance() -> None:
    # risk = 1% of 10_000 = 100 EUR; stop distance = ATR 2 x 2.5 = 5 -> qty = 20.
    risk = FixedFractionalRiskManager(
        {"AAA": Decimal("50")},
        max_position_pct=Decimal("0.20"),  # ceiling far away
        min_cash_pct=Decimal("0"),
        vol_target_pct=Decimal("0.01"),
        atr_by_symbol={"AAA": Decimal("2")},
        stop_atr_multiple=Decimal("2.5"),
    )
    sizes = risk.size_positions([_candidate("AAA")], _balance(10_000))
    assert sizes["AAA"] == Decimal("20.000000")


def test_calm_name_sizes_bigger_than_volatile_one() -> None:
    risk = FixedFractionalRiskManager(
        {"CALM": Decimal("100"), "WILD": Decimal("100")},
        max_position_pct=Decimal("0.50"),
        min_cash_pct=Decimal("0"),
        vol_target_pct=Decimal("0.01"),
        atr_by_symbol={"CALM": Decimal("1"), "WILD": Decimal("5")},
        stop_atr_multiple=Decimal("2.5"),
    )
    sizes = risk.size_positions(
        [_candidate("CALM", 1), _candidate("WILD", 2)], _balance(10_000)
    )
    assert sizes["CALM"] == sizes["WILD"] * 5  # same euro risk, 5x the units


def test_max_position_pct_stays_the_ceiling() -> None:
    # Tiny ATR would size huge; the notional ceiling must cap it.
    risk = FixedFractionalRiskManager(
        {"AAA": Decimal("100")},
        max_position_pct=Decimal("0.05"),
        min_cash_pct=Decimal("0"),
        vol_target_pct=Decimal("0.01"),
        atr_by_symbol={"AAA": Decimal("0.01")},
        stop_atr_multiple=Decimal("2.5"),
    )
    sizes = risk.size_positions([_candidate("AAA")], _balance(10_000))
    assert sizes["AAA"] == Decimal("5.000000")  # 5% of 10k / 100 = 5 shares


def test_missing_atr_falls_back_to_fixed_fractional() -> None:
    risk = FixedFractionalRiskManager(
        {"AAA": Decimal("100")},
        max_position_pct=Decimal("0.05"),
        min_cash_pct=Decimal("0"),
        vol_target_pct=Decimal("0.01"),
        atr_by_symbol={},  # no ATR available
        stop_atr_multiple=Decimal("2.5"),
    )
    sizes = risk.size_positions([_candidate("AAA")], _balance(10_000))
    assert sizes["AAA"] == Decimal("5.000000")  # plain fixed-fractional


def test_vol_target_off_is_byte_for_byte_fixed_fractional() -> None:
    kwargs = dict(
        max_position_pct=Decimal("0.05"),
        min_cash_pct=Decimal("0"),
    )
    plain = FixedFractionalRiskManager({"AAA": Decimal("100")}, **kwargs)
    with_atr = FixedFractionalRiskManager(
        {"AAA": Decimal("100")},
        **kwargs,
        atr_by_symbol={"AAA": Decimal("2")},
        stop_atr_multiple=Decimal("2.5"),  # but no vol_target_pct
    )
    balance = _balance(10_000)
    assert plain.size_positions([_candidate("AAA")], balance) == with_atr.size_positions(
        [_candidate("AAA")], balance
    )
