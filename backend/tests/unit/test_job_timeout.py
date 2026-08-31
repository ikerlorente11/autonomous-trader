"""Per-job wall-clock cap — a job that hangs must end as a recorded failure.

Regression for 2026-08-31: Finnhub 503'd every symbol, each burning its retries
against a server-sent Retry-After, and fetch_news_sentiment crawled for hours with
the manual pipeline queued behind it. Nothing was broken enough to fail, so nothing
ever ended."""

from __future__ import annotations

import asyncio

import pytest

from backend.scheduler import jobs

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch):
    """_job_context records to the DB in its finally; this suite is DB-free."""
    recorded: list = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def add(self, row):
            recorded.append(row)

        async def commit(self):
            pass

    monkeypatch.setattr(jobs, "async_session", lambda: _Session())
    return recorded


def test_default_limit_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOB_TIMEOUT_SECONDS", raising=False)
    assert jobs._job_timeout_seconds("run_analysis") == jobs._DEFAULT_JOB_TIMEOUT_SECONDS


def test_per_job_override_beats_the_global(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("JOB_TIMEOUT_SECONDS_FETCH_NEWS_SENTIMENT", "900")
    assert jobs._job_timeout_seconds("fetch_news_sentiment") == 900
    assert jobs._job_timeout_seconds("run_analysis") == 60


def test_bad_value_falls_through_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_TIMEOUT_SECONDS", "not-a-number")
    assert jobs._job_timeout_seconds("run_analysis") == jobs._DEFAULT_JOB_TIMEOUT_SECONDS


async def test_a_hanging_job_is_cut_and_recorded_failed(
    monkeypatch: pytest.MonkeyPatch, _no_db: list
) -> None:
    # The suite runs with the operator's .env, which carries a per-job override for
    # exactly this job; the global setting below must not be shadowed by it.
    monkeypatch.delenv("JOB_TIMEOUT_SECONDS_FETCH_NEWS_SENTIMENT", raising=False)
    monkeypatch.setenv("JOB_TIMEOUT_SECONDS", "1")

    async with jobs._job_context("fetch_news_sentiment") as outcome:
        outcome.status = "success"
        await asyncio.sleep(5)  # the Finnhub crawl that never ends
        outcome.detail = {"never": "reached"}

    assert outcome.status == "failed"
    assert _no_db[-1].status == "failed"
    assert "wall-clock" in _no_db[-1].error


async def test_a_normal_job_is_untouched(monkeypatch: pytest.MonkeyPatch, _no_db: list) -> None:
    monkeypatch.setenv("JOB_TIMEOUT_SECONDS", "30")

    async with jobs._job_context("run_analysis") as outcome:
        outcome.detail = {"symbols_scored": 3}

    assert outcome.status == "success"
    assert _no_db[-1].status == "success"
    assert _no_db[-1].error is None


async def test_zero_disables_the_cap(monkeypatch: pytest.MonkeyPatch, _no_db: list) -> None:
    monkeypatch.setenv("JOB_TIMEOUT_SECONDS", "0")

    async with jobs._job_context("run_analysis") as outcome:
        await asyncio.sleep(0.05)

    assert outcome.status == "success"
