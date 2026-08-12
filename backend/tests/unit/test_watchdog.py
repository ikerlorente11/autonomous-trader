"""Scheduler watchdog — heartbeat/gap accounting (the exit path is os._exit)."""

from __future__ import annotations

import pytest

from backend.scheduler import watchdog

pytestmark = pytest.mark.unit


async def test_heartbeat_resets_the_gap() -> None:
    watchdog._last_beat -= 10_000  # simulate a long stall
    assert watchdog.gap_seconds() > 9_000
    await watchdog.heartbeat_job()
    assert watchdog.gap_seconds() < 5


def test_stall_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCHEDULER_WATCHDOG_STALL_SECONDS", raising=False)
    assert watchdog.stall_seconds() == 1800
    monkeypatch.setenv("SCHEDULER_WATCHDOG_STALL_SECONDS", "600")
    assert watchdog.stall_seconds() == 600


def test_scheduler_registers_heartbeat_and_preping_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5/t")
    from backend.scheduler.main import build_scheduler

    scheduler = build_scheduler()
    job = scheduler.get_job("watchdog_heartbeat", jobstore="memory")
    assert job is not None
    engine = scheduler._jobstores["default"].engine
    assert engine.pool._pre_ping is True
