"""Thesis A backfills — pure parsing/window logic, no network, no DB."""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


insider = _load("backfill_insider")
earnings = _load("backfill_earnings")


def test_quarter_range_crosses_year_boundaries() -> None:
    assert insider._quarters("2023q3", "2024q2") == ["2023q3", "2023q4", "2024q1", "2024q2"]


def test_latest_published_quarter_is_the_previous_complete_one() -> None:
    assert insider._latest_published_quarter(dt.date(2026, 8, 31)) == "2026q2"
    assert insider._latest_published_quarter(dt.date(2026, 1, 15)) == "2025q4"


def test_sec_date_format_parses() -> None:
    assert insider._parse_date("31-MAY-2023") == dt.date(2023, 5, 31)
    assert insider._parse_date("2023-05-31") == dt.date(2023, 5, 31)
    assert insider._parse_date("") is None


def _mini_bulk_zip(tmp_path: Path) -> str:
    def tsv(header: list[str], rows: list[list[str]]) -> str:
        return "\n".join("\t".join(r) for r in [header, *rows]) + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SUBMISSION.tsv",
            tsv(
                ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK",
                 "ISSUERTRADINGSYMBOL"],
                [
                    ["ACC-1", "02-JUN-2023", "4", "0000320193", "AAPL"],
                    ["ACC-2", "05-JUN-2023", "4/A", "0000320193", "AAPL"],
                    ["ACC-3", "05-JUN-2023", "4", "0009999999", "ZZZZ"],  # not watchlist
                    ["ACC-4", "06-JUN-2023", "3", "0000320193", "AAPL"],  # not a Form 4
                ],
            ),
        )
        zf.writestr(
            "REPORTINGOWNER.tsv",
            tsv(
                ["ACCESSION_NUMBER", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"],
                [["ACC-1", "Officer", "CFO"], ["ACC-2", "Director", ""]],
            ),
        )
        zf.writestr(
            "NONDERIV_TRANS.tsv",
            tsv(
                ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "TRANS_DATE", "TRANS_CODE",
                 "TRANS_SHARES", "TRANS_PRICEPERSHARE", "SHRS_OWND_FOLWNG_TRANS"],
                [
                    ["ACC-1", "902", "01-JUN-2023", "S", "10.0", "185.5", "990.0"],
                    ["ACC-1", "901", "01-JUN-2023", "P", "100.0", "185.0", "1000.0"],
                    ["ACC-2", "903", "02-JUN-2023", "P", "50.0", "", "500.0"],
                    ["ACC-3", "904", "02-JUN-2023", "P", "1.0", "1.0", "1.0"],
                ],
            ),
        )
    path = tmp_path / "mini_form345.zip"
    path.write_bytes(buf.getvalue())
    return str(path)


def test_bulk_quarter_parses_filters_and_orders(tmp_path: Path) -> None:
    rows = insider._rows_for_quarter(_mini_bulk_zip(tmp_path), {"AAPL"})
    by_key = {(r["accession_no"], r["txn_seq"]): r for r in rows}
    # ZZZZ (not watchlist) and the Form 3 are gone; 2 filings, 3 transactions survive.
    assert set(by_key) == {("ACC-1", 0), ("ACC-1", 1), ("ACC-2", 0)}
    # Seq follows the surrogate-key order (901 -> seq 0), deterministically.
    assert by_key[("ACC-1", 0)]["txn_type"] == "P"
    assert by_key[("ACC-1", 0)]["shares"] == Decimal("100.0")
    assert by_key[("ACC-1", 1)]["txn_type"] == "S"
    assert by_key[("ACC-1", 0)]["insider_role"] == "Officer, CFO"
    assert by_key[("ACC-1", 0)]["filed_ts"].date() == dt.date(2023, 6, 2)
    assert by_key[("ACC-2", 0)]["is_amendment"] is True
    assert by_key[("ACC-2", 0)]["price"] is None


_AV_PAYLOAD = {
    "quarterlyEarnings": [
        {"fiscalDateEnding": "2026-06-30", "reportedDate": "2026-07-22",
         "reportedEPS": "2.93", "estimatedEPS": "2.90", "surprisePercentage": "1.03",
         "reportTime": "post-market"},
        {"fiscalDateEnding": "2026-03-31", "reportedDate": "2026-04-22",
         "reportedEPS": "1.91", "estimatedEPS": "None", "surprisePercentage": "None",
         "reportTime": "pre-market"},
        {"fiscalDateEnding": "2026-09-30", "reportedDate": "2026-10-21",
         "reportedEPS": "None", "estimatedEPS": "3.00", "reportTime": "post-market"},
        {"fiscalDateEnding": "2022-12-31", "reportedDate": "2023-01-25",
         "reportedEPS": "1.00", "estimatedEPS": "1.00", "reportTime": "pre-market"},
    ]
}


def test_av_rows_map_sessions_and_availability() -> None:
    rows = earnings._rows_from_av("IBM", _AV_PAYLOAD, since=dt.date(2023, 2, 1))
    by_period = {r["fiscal_period_end"]: r for r in rows}
    # The unreported placeholder and the pre-`since` quarter are dropped.
    assert set(by_period) == {dt.date(2026, 6, 30), dt.date(2026, 3, 31)}
    amc = by_period[dt.date(2026, 6, 30)]
    assert amc["announce_session"] == "amc"
    # amc -> only actionable the NEXT session (lookahead guard).
    assert amc["available_ts"].date() == dt.date(2026, 7, 23)
    bmo = by_period[dt.date(2026, 3, 31)]
    assert bmo["announce_session"] == "bmo"
    assert bmo["available_ts"].date() == dt.date(2026, 4, 22)
    assert bmo["eps_estimate"] is None  # 'None' string -> NULL, not a crash
