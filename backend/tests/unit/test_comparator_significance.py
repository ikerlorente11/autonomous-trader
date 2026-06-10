"""ExperimentComparator significance tests — pure numpy/stat math, no DB."""

from __future__ import annotations

import math

import pytest

from backend.experiments.comparator import (
    ExperimentComparator,
    _fisher_exact_two_sided,
    _norm_cdf,
    _norm_ppf,
)

pytestmark = pytest.mark.unit

ALPHA = 0.05


@pytest.fixture(scope="module")
def comparator() -> ExperimentComparator:
    return ExperimentComparator(None)  # methods under test never touch the session


# --------------------------------------------------------------------------- #
# Numeric helpers
# --------------------------------------------------------------------------- #
def test_norm_cdf_midpoint() -> None:
    assert _norm_cdf(0.0) == pytest.approx(0.5)


def test_norm_ppf_inverts_cdf() -> None:
    assert _norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-4)
    assert _norm_ppf(_norm_cdf(0.7)) == pytest.approx(0.7, abs=1e-6)


def test_norm_ppf_out_of_range_is_nan() -> None:
    assert math.isnan(_norm_ppf(0.0))
    assert math.isnan(_norm_ppf(1.0))


# --------------------------------------------------------------------------- #
# Bootstrap returns
# --------------------------------------------------------------------------- #
def test_returns_identical_samples_not_significant(comparator) -> None:
    series = [0.01, -0.02, 0.015, 0.0, -0.005, 0.008]
    res = comparator._significance_returns(series, series, ALPHA)
    assert res.significant is False
    assert res.p_value > 0.5
    assert res.statistic == pytest.approx(0.0)
    assert res.ci_low <= 0.0 <= res.ci_high


def test_returns_separated_samples_significant(comparator) -> None:
    high = [0.05, 0.06, 0.055, 0.052, 0.058, 0.051, 0.049, 0.06]
    low = [-0.05, -0.04, -0.045, -0.052, -0.048, -0.051, -0.06, -0.041]
    res = comparator._significance_returns(high, low, ALPHA)
    assert res.significant is True
    assert res.p_value < ALPHA
    assert res.statistic > 0.0


def test_returns_is_deterministic(comparator) -> None:
    a = [0.01, 0.02, -0.01, 0.03, -0.02, 0.015]
    b = [0.0, -0.01, 0.005, -0.02, 0.01, -0.005]
    first = comparator._significance_returns(a, b, ALPHA)
    second = comparator._significance_returns(a, b, ALPHA)
    assert first == second


def test_returns_insufficient_sample_is_nan(comparator) -> None:
    res = comparator._significance_returns([0.01], [0.01, 0.02], ALPHA)
    assert res.significant is False
    assert math.isnan(res.p_value)


# --------------------------------------------------------------------------- #
# Jobson-Korkie / Memmel Sharpe
# --------------------------------------------------------------------------- #
def test_sharpe_identical_series_is_degenerate(comparator) -> None:
    # Identical series → rho=1 and equal Sharpes collapse the Memmel variance to
    # zero, so the test statistic is undefined: NaN is the honest result.
    series = [0.01, -0.02, 0.015, 0.0, -0.005, 0.008, 0.012, -0.011]
    res = comparator._significance_sharpe(series, series, ALPHA)
    assert res.significant is False
    assert math.isnan(res.p_value)


def test_sharpe_separated_series_significant(comparator) -> None:
    strong = [0.02, 0.018, 0.022, 0.019, 0.021, 0.020, 0.0195, 0.0205] * 4
    weak = [0.001, -0.001, 0.002, -0.002, 0.0, 0.001, -0.0015, 0.0005] * 4
    res = comparator._significance_sharpe(strong, weak, ALPHA)
    assert res.significant is True
    assert res.p_value < ALPHA
    assert res.statistic > 0.0


def test_sharpe_mismatched_lengths_raises(comparator) -> None:
    with pytest.raises(ValueError, match="paired equal-length"):
        comparator._significance_sharpe([0.01, 0.02], [0.01], ALPHA)


def test_sharpe_zero_variance_is_nan(comparator) -> None:
    res = comparator._significance_sharpe([0.01, 0.01, 0.01], [0.0, 0.01, -0.01], ALPHA)
    assert res.significant is False
    assert math.isnan(res.p_value)


# --------------------------------------------------------------------------- #
# Two-proportion / Fisher
# --------------------------------------------------------------------------- #
def test_proportion_equal_rates_not_significant(comparator) -> None:
    res = comparator._significance_proportion(50, 100, 52, 100, ALPHA)
    assert res.significant is False
    assert res.p_value > ALPHA


def test_proportion_large_gap_significant(comparator) -> None:
    res = comparator._significance_proportion(60, 100, 40, 100, ALPHA)
    assert res.significant is True
    assert res.p_value == pytest.approx(0.004678, abs=1e-4)
    assert res.statistic == pytest.approx(2.828427, abs=1e-4)
    assert res.ci_low < res.ci_high


def test_proportion_low_counts_use_fisher(comparator) -> None:
    res = comparator._significance_proportion(4, 5, 0, 5, ALPHA)
    assert res.p_value == pytest.approx(0.047619, abs=1e-4)
    assert res.significant is True
    assert math.isnan(res.ci_low) and math.isnan(res.ci_high)


def test_proportion_empty_group_is_nan(comparator) -> None:
    res = comparator._significance_proportion(0, 0, 3, 10, ALPHA)
    assert res.significant is False
    assert math.isnan(res.p_value)


def test_fisher_symmetric_balanced_table() -> None:
    p = _fisher_exact_two_sided(3, 6, 3, 6)
    assert p == pytest.approx(1.0)
