"""Finnhub fundamentals provider — pure concept-mapping parser, no network."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.data_ingestion.providers.finnhub_fundamentals_provider import (
    _end_date_epoch,
    _parse_report,
    _parse_statements,
)

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc


def _report() -> dict:
    return {
        "ic": [
            {"concept": "us-gaap_Revenues", "value": 180.0},
            {"concept": "us-gaap_NetIncomeLoss", "value": 20.0},
            {"concept": "us-gaap_GrossProfit", "value": 100.0},
        ],
        "bs": [{"concept": "us-gaap_StockholdersEquity", "value": 130.0}],
        "cf": [
            {"concept": "us-gaap_NetCashProvidedByUsedInOperatingActivities", "value": 30.0},
            {"concept": "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment", "value": 8.0},
        ],
    }


def test_parse_report_maps_concepts_and_derives_fcf() -> None:
    items = _parse_report(_report())
    assert items["revenue"] == 180.0
    assert items["net_income"] == 20.0
    assert items["gross_profit"] == 100.0
    assert items["equity"] == 130.0
    assert items["free_cash_flow"] == pytest.approx(22.0)  # 30 - 8


def test_parse_report_uses_candidate_fallback() -> None:
    report = {"ic": [{"concept": "us-gaap_SalesRevenueNet", "value": 150.0}]}
    assert _parse_report(report)["revenue"] == 150.0


def test_parse_report_omits_missing_and_handles_non_dict() -> None:
    assert _parse_report({"ic": [{"concept": "us-gaap_GrossProfit", "value": 9.0}]}) == {
        "gross_profit": 9.0
    }
    assert _parse_report("nope") == {}


def test_end_date_epoch_parses_and_rejects() -> None:
    expected = float(dt.datetime(2025, 6, 30, tzinfo=UTC).timestamp())
    assert _end_date_epoch({"endDate": "2025-06-30 00:00:00"}) == expected
    assert _end_date_epoch({"endDate": "bad"}) is None
    assert _end_date_epoch({}) is None


def test_parse_statements_skips_unusable_entries() -> None:
    payload = {
        "data": [
            {"endDate": "2025-06-30 00:00:00", "report": _report()},
            {"endDate": "2025-03-31", "report": {"ic": []}},  # nothing extracted -> skip
            {"report": _report()},  # no endDate -> skip
        ]
    }
    out = _parse_statements(payload)
    assert len(out) == 1
    assert out[0]["revenue"] == 180.0
    assert "period_end" in out[0]


def test_parse_statements_empty_payload() -> None:
    assert _parse_statements({}) == []
    assert _parse_statements("nope") == []
