"""FRED provider parsing — pure helpers, no network."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.data_ingestion.providers.fred_provider import (
    FredProvider,
    _observations_to_series,
    _parse_date,
    _to_decimal,
)

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc


def test_to_decimal_treats_dot_and_blank_as_missing() -> None:
    assert _to_decimal(".") is None
    assert _to_decimal("") is None
    assert _to_decimal(None) is None
    assert _to_decimal("garbage") is None
    assert _to_decimal("4.25") == Decimal("4.25")


def test_parse_date_midnight_utc_and_rejects_bad() -> None:
    assert _parse_date("2026-05-29") == dt.datetime(2026, 5, 29, tzinfo=UTC)
    assert _parse_date("not-a-date") is None
    assert _parse_date(20260529) is None


def test_observations_drop_missing_values() -> None:
    payload = {
        "observations": [
            {"date": "2026-05-27", "value": "0.40"},
            {"date": "2026-05-28", "value": "."},  # missing -> dropped
            {"date": "bad", "value": "0.50"},  # bad date -> dropped
            {"date": "2026-05-29", "value": "0.45"},
        ]
    }
    series = _observations_to_series(payload)
    assert series == [
        (dt.datetime(2026, 5, 27, tzinfo=UTC), Decimal("0.40")),
        (dt.datetime(2026, 5, 29, tzinfo=UTC), Decimal("0.45")),
    ]


def test_observations_empty_payload() -> None:
    assert _observations_to_series({}) == []


def test_is_configured_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert FredProvider.is_configured() is False
    monkeypatch.setenv("FRED_API_KEY", "abc")
    assert FredProvider.is_configured() is True
