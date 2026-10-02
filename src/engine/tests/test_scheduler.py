from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from engine.jobs import scheduler as scheduler_module
from engine.jobs.scheduler import Job, JobScheduler, SchedulerSettings, build_jobs, run_job

FIXED = datetime(2026, 9, 1, tzinfo=UTC)


def test_settings_defaults(monkeypatch):
    for name in ("SCHEDULER_ENABLED", "MEASURE_WINDOW_DAYS", "OUTCOME_LINKER_INTERVAL_MINUTES"):
        monkeypatch.delenv(name, raising=False)
    assert SchedulerSettings.from_env() == SchedulerSettings(True, 14, 15)


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MEASURE_WINDOW_DAYS", "7")
    monkeypatch.setenv("OUTCOME_LINKER_INTERVAL_MINUTES", "1")
    assert SchedulerSettings.from_env() == SchedulerSettings(False, 7, 1)


@pytest.mark.parametrize(("name", "value"), [("SCHEDULER_ENABLED", "maybe"),
                                             ("MEASURE_WINDOW_DAYS", "0"),
                                             ("MEASURE_WINDOW_DAYS", "two"),
                                             ("OUTCOME_LINKER_INTERVAL_MINUTES", "-5")])
def test_settings_reject_malformed_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        SchedulerSettings.from_env()


def test_registry_holds_the_outcome_linker_at_its_interval():
    jobs = build_jobs(pool=object(), settings=SchedulerSettings(True, 14, 20))  # type: ignore[arg-type]
    assert [(j.name, j.interval) for j in jobs] == [("outcome_linker", timedelta(minutes=20))]


class _RecordingLog:
    def __init__(self) -> None:
        self.errors: list[tuple[str, dict]] = []

    def error(self, event: str, **kw) -> None:
        self.errors.append((event, kw))


async def test_run_job_passes_the_clock_and_logs_failures(monkeypatch):
    recorded = _RecordingLog()
    monkeypatch.setattr(scheduler_module, "log", recorded)
    seen: list[datetime] = []

    async def ok(now: datetime) -> None:
        seen.append(now)

    async def boom(now: datetime) -> None:
        raise RuntimeError("db down")

    await run_job(Job("ok", timedelta(minutes=1), ok), clock=lambda: FIXED)
    assert seen == [FIXED]
    await run_job(Job("boom", timedelta(minutes=1), boom), clock=lambda: FIXED)
    assert recorded.errors == [("scheduled_job_failed", {"job": "boom", "exc_info": True})]


async def test_scheduler_runs_jobs_on_their_interval_and_stops():
    ran = asyncio.Event()

    async def tick(now: datetime) -> None:
        ran.set()

    scheduler = JobScheduler([Job("tick", timedelta(seconds=0.05), tick)])
    scheduler.start()
    try:
        assert scheduler.running
        await asyncio.wait_for(ran.wait(), timeout=2)
    finally:
        scheduler.shutdown()
    assert not scheduler.running


async def test_app_lifespan_without_database_starts_no_scheduler(monkeypatch):
    from engine.app import create_app

    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.scheduler is None
