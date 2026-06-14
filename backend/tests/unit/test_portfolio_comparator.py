"""PortfolioComparator orchestration + verdict logic — DB helpers monkeypatched."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.experiments.comparator import (
    ComparisonVerdict,
    PortfolioComparator,
    PortfolioStats,
)

pytestmark = pytest.mark.unit


def _stats(pid: int, label: str) -> PortfolioStats:
    return PortfolioStats(
        portfolio_id=pid, name=f"p{pid}", strategy_label=label, n_days=30,
        total_return=0.1, cagr=0.1, sharpe=1.0, max_drawdown=-0.05,
        final_nav=110.0, contributed=100.0,
    )


def _comparator(monkeypatch, ret_a, ret_b):
    comp = PortfolioComparator(None)  # type: ignore[arg-type]

    async def fake_stats(pid):
        return _stats(pid, "v1" if pid == 1 else "v4")

    async def fake_paired(a_id, b_id):
        return ret_a, ret_b

    monkeypatch.setattr(comp, "_stats", fake_stats)
    monkeypatch.setattr(comp, "_paired_returns", fake_paired)
    return comp


async def test_insufficient_evidence_below_min_paired(monkeypatch) -> None:
    comp = _comparator(monkeypatch, [0.01] * 5, [0.0] * 5)
    result = await comp.compare_portfolios(1, 2)
    assert result is not None
    assert result.verdict is ComparisonVerdict.INSUFFICIENT_EVIDENCE
    assert result.paired_days == 5
    assert any("paired sessions" in n for n in result.notes)


async def test_a_better_when_returns_significantly_higher(monkeypatch) -> None:
    comp = _comparator(monkeypatch, [0.01] * 30, [-0.01] * 30)
    result = await comp.compare_portfolios(1, 2)
    assert result is not None
    assert result.verdict is ComparisonVerdict.A_BETTER
    assert result.returns_significance.significant
    assert result.returns_significance.statistic > 0


async def test_b_better_when_returns_significantly_lower(monkeypatch) -> None:
    comp = _comparator(monkeypatch, [-0.01] * 30, [0.01] * 30)
    result = await comp.compare_portfolios(1, 2)
    assert result is not None
    assert result.verdict is ComparisonVerdict.B_BETTER


async def test_no_significant_difference_for_identical_series(monkeypatch) -> None:
    series = [0.01, -0.01] * 15
    comp = _comparator(monkeypatch, list(series), list(series))
    result = await comp.compare_portfolios(1, 2)
    assert result is not None
    assert result.verdict is ComparisonVerdict.NO_SIGNIFICANT_DIFFERENCE
    assert not result.returns_significance.significant


async def test_missing_portfolio_returns_none(monkeypatch) -> None:
    comp = PortfolioComparator(None)  # type: ignore[arg-type]

    async def none_stats(pid):
        return None

    monkeypatch.setattr(comp, "_stats", none_stats)
    assert await comp.compare_portfolios(1, 999) is None


async def test_paired_returns_align_on_common_dates(monkeypatch) -> None:
    # A spans Mon-Fri, B spans Wed-following Tue; daily returns overlap on the inner days.
    comp = PortfolioComparator(None)  # type: ignore[arg-type]
    idx_a = pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC")
    idx_b = pd.date_range("2026-06-03", periods=5, freq="D", tz="UTC")
    frame_a = pd.DataFrame({"ts": idx_a, "total": [100, 101, 102, 103, 104]})
    frame_b = pd.DataFrame({"ts": idx_b, "total": [200, 198, 202, 205, 203]})

    async def fake_nav(pid):
        return frame_a if pid == 1 else frame_b

    monkeypatch.setattr(comp, "_nav_frame", fake_nav)
    ra, rb = await comp._paired_returns(1, 2)
    # returns exist on 06-02..06-05 for A and 06-04..06-07 for B -> overlap 06-04, 06-05
    assert len(ra) == len(rb) == 2
