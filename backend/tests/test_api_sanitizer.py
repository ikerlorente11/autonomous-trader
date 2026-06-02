"""Tests for the SafeJSONResponse non-finite-float sanitizer.

``backend.api.main`` builds the async engine at import (needs DATABASE_URL) but
never connects, so a dummy URL set before import is enough to reach the pure
``_replace_non_finite`` helper without a database.
"""

from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")

from backend.api.main import _replace_non_finite  # noqa: E402


def test_finite_float_unchanged() -> None:
    assert _replace_non_finite(1.5) == 1.5


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_becomes_none(bad: float) -> None:
    assert _replace_non_finite(bad) is None


def test_nested_dict_and_list() -> None:
    payload = {
        "returns": {"alpha": float("nan"), "total": 0.12},
        "risk": [float("inf"), 1.0, {"calmar": float("-inf")}],
        "name": "AAA",
        "count": 3,
    }
    out = _replace_non_finite(payload)
    assert out == {
        "returns": {"alpha": None, "total": 0.12},
        "risk": [None, 1.0, {"calmar": None}],
        "name": "AAA",
        "count": 3,
    }


def test_tuple_becomes_list() -> None:
    assert _replace_non_finite((1.0, float("nan"))) == [1.0, None]


def test_non_numeric_types_passthrough() -> None:
    assert _replace_non_finite("str") == "str"
    assert _replace_non_finite(None) is None
    assert _replace_non_finite(7) == 7
    # bool/int are left as-is (not floats).
    assert _replace_non_finite(True) is True


def test_does_not_mutate_input() -> None:
    payload = {"a": float("nan")}
    _replace_non_finite(payload)
    assert math.isnan(payload["a"])
