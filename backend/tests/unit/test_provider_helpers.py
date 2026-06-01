"""Pure helpers of the OHLCV providers — no DB, no network."""

from __future__ import annotations

import httpx
import pytest

from backend.data_ingestion.providers import twelve_data_provider as td
from backend.data_ingestion.providers import yfinance_provider as yf

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("message", "expected_fragment"),
    [
        ("You have run out of API credits for the current minute. 8 / 8 used", "per-minute"),
        ("You have reached the API calls limit for the day", "daily"),
        ("", "rate limit hit"),
        ("some unknown reason", "rate limit hit"),
    ],
)
def test_classify_429(message: str, expected_fragment: str) -> None:
    assert expected_fragment in td._classify_429(message)


def test_twelve_data_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWELVE_DATA_CREDITS_PER_MIN", raising=False)
    monkeypatch.delenv("TWELVE_DATA_BATCH", raising=False)
    assert td._credits_per_min() == 8
    assert td._batch_size() == 8


def test_twelve_data_config_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWELVE_DATA_CREDITS_PER_MIN", "30")
    monkeypatch.setenv("TWELVE_DATA_BATCH", "16")
    assert td._credits_per_min() == 30
    assert td._batch_size() == 16


def test_yfinance_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YFINANCE_MAX_RETRIES", raising=False)
    monkeypatch.delenv("YFINANCE_THROTTLE_MS", raising=False)
    assert yf._max_retries() == 3
    assert yf._throttle_seconds() == pytest.approx(0.25)


def test_yfinance_retry_statuses_and_ua_pool() -> None:
    assert yf._RETRY_STATUSES == frozenset({429, 500, 502, 503, 504})
    assert len(yf._USER_AGENTS) >= 2  # rotation needs >1


def test_retry_after_prefers_header() -> None:
    resp = httpx.Response(429, headers={"Retry-After": "7"})
    assert yf._retry_after(resp, default=1.0) == 7.0


def test_retry_after_falls_back_on_missing_or_garbage() -> None:
    assert yf._retry_after(httpx.Response(429), default=2.5) == 2.5
    bad = httpx.Response(429, headers={"Retry-After": "soon"})
    assert yf._retry_after(bad, default=2.5) == 2.5
