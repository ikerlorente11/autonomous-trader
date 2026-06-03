"""FP&A period P&L and symbol/sector attribution — pure math (reporting §1.2–1.3)."""

from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd
import pytest

from backend.analysis.performance.metrics import (
    UNCLASSIFIED_SECTOR,
    attribution_by_sector,
    attribution_by_symbol,
    period_pnl,
    period_start,
)

pytestmark = pytest.mark.unit

# Wednesday 2026-06-17: WTD Monday = 2026-06-15, MTD = 2026-06-01, YTD = 2026-01-01.
ASOF = pd.Timestamp("2026-06-17")


def _nav(rows: Sequence[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {"ts": pd.to_datetime([d for d, _ in rows]), "total": [v for _, v in rows]}
    )


_SERIES = _nav(
    [
        ("2025-12-31", 1000.0),  # prior year-end  -> YTD / inception baseline
        ("2026-05-29", 1100.0),  # prior month-end -> MTD baseline
        ("2026-06-12", 1200.0),  # Friday pre-WTD  -> WTD baseline
        ("2026-06-16", 1250.0),
        ("2026-06-17", 1300.0),  # asof / end
    ]
)


def test_period_start_boundaries() -> None:
    assert period_start(ASOF, "wtd") == pd.Timestamp("2026-06-15")
    assert period_start(ASOF, "mtd") == pd.Timestamp("2026-06-01")
    assert period_start(ASOF, "ytd") == pd.Timestamp("2026-01-01")
    assert period_start(ASOF, "inception") is None


def test_period_start_rejects_unknown_period() -> None:
    with pytest.raises(ValueError):
        period_start(ASOF, "qtd")


def test_wtd_uses_last_close_before_monday() -> None:
    p = period_pnl(_SERIES, "wtd", ASOF)
    assert p.start_value == pytest.approx(1200.0)
    assert p.end_value == pytest.approx(1300.0)
    assert p.pnl == pytest.approx(100.0)
    assert p.return_pct == pytest.approx(1300 / 1200 - 1)


def test_mtd_uses_prior_month_end() -> None:
    p = period_pnl(_SERIES, "mtd", ASOF)
    assert p.start_value == pytest.approx(1100.0)
    assert p.pnl == pytest.approx(200.0)


def test_ytd_uses_prior_year_end() -> None:
    p = period_pnl(_SERIES, "ytd", ASOF)
    assert p.start_value == pytest.approx(1000.0)
    assert p.pnl == pytest.approx(300.0)
    assert p.return_pct == pytest.approx(0.30)


def test_inception_anchors_on_first_nav() -> None:
    p = period_pnl(_SERIES, "inception", ASOF)
    assert p.start_value == pytest.approx(1000.0)
    assert p.start_ts == pd.Timestamp("2025-12-31")


def test_ytd_falls_back_to_inception_in_first_year() -> None:
    series = _nav([("2026-06-12", 1200.0), ("2026-06-17", 1300.0)])
    p = period_pnl(series, "ytd", ASOF)
    assert p.start_value == pytest.approx(1200.0)  # no prior-year NAV -> first row


def test_empty_series_is_flat_and_nan() -> None:
    p = period_pnl(_nav([]), "mtd", ASOF)
    assert p.pnl == 0.0
    assert p.start_ts is None and p.end_ts is None
    assert math.isnan(p.return_pct)


def test_zero_baseline_return_is_nan() -> None:
    series = _nav([("2025-12-31", 0.0), ("2026-06-17", 1300.0)])
    p = period_pnl(series, "ytd", ASOF)
    assert math.isnan(p.return_pct)
    assert p.pnl == pytest.approx(1300.0)


def test_tz_aware_nav_and_asof_compare_cleanly() -> None:
    series = _SERIES.copy()
    series["ts"] = series["ts"].dt.tz_localize("UTC")
    p = period_pnl(series, "mtd", pd.Timestamp("2026-06-17", tz="UTC"))
    assert p.start_value == pytest.approx(1100.0)


# --------------------------------------------------------------------------- #
# Attribution
# --------------------------------------------------------------------------- #
def _trips(rows: Sequence[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [s for s, _, _ in rows],
            "exit_ts": pd.to_datetime([d for _, d, _ in rows]),
            "pnl": [p for _, _, p in rows],
        }
    )


def test_symbol_attribution_windows_realized_and_adds_unrealized() -> None:
    trips = _trips(
        [
            ("AAPL", "2026-06-16", 50.0),
            ("AAPL", "2026-05-20", 30.0),  # before MTD window -> excluded
            ("MSFT", "2026-06-10", -20.0),
        ]
    )
    attr = attribution_by_symbol(
        trips,
        {"AAPL": 10.0, "GOOG": 5.0},
        start=period_start(ASOF, "mtd"),
        end=ASOF,
    )
    by_symbol = {a.symbol: a for a in attr}
    assert by_symbol["AAPL"].realized_pnl == pytest.approx(50.0)
    assert by_symbol["AAPL"].total_pnl == pytest.approx(60.0)
    assert by_symbol["MSFT"].total_pnl == pytest.approx(-20.0)
    assert by_symbol["GOOG"].total_pnl == pytest.approx(5.0)
    assert [a.symbol for a in attr] == ["AAPL", "GOOG", "MSFT"]  # best -> worst
    assert sum(a.contribution_pct for a in attr) == pytest.approx(100.0)


def test_symbol_attribution_flat_total_has_nan_contribution() -> None:
    trips = _trips([("AAPL", "2026-06-16", 10.0), ("MSFT", "2026-06-16", -10.0)])
    attr = attribution_by_symbol(trips, start=period_start(ASOF, "mtd"), end=ASOF)
    assert all(math.isnan(a.contribution_pct) for a in attr)


def test_sector_attribution_groups_and_buckets_unmapped() -> None:
    symbol_attr = attribution_by_symbol(
        _trips([("AAPL", "2026-06-16", 50.0), ("MSFT", "2026-06-10", -20.0)]),
        {"GOOG": 5.0},
        start=period_start(ASOF, "mtd"),
        end=ASOF,
    )
    sectors = attribution_by_sector(symbol_attr, {"AAPL": "Tech", "MSFT": "Tech"})
    by_sector = {s.sector: s for s in sectors}
    assert by_sector["Tech"].total_pnl == pytest.approx(30.0)
    assert by_sector[UNCLASSIFIED_SECTOR].total_pnl == pytest.approx(5.0)
    assert sum(s.contribution_pct for s in sectors) == pytest.approx(100.0)
