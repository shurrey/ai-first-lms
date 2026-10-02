"""In-process job scheduler (spec.md §10.4) on APScheduler's asyncio scheduler.

Each job runs on an interval with `max_instances=1` and `coalesce=True`; a job must still be
safe to run twice, because several orchestrator processes may share one database.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from engine.jobs.outcome_linker import PgOutcomeLinker
from engine.logging_config import get_logger
from engine.telemetry import get_tracer

log = get_logger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return value


@dataclass(frozen=True)
class SchedulerSettings:
    enabled: bool = True
    measure_window_days: int = 14
    outcome_linker_interval_minutes: int = 15

    @classmethod
    def from_env(cls) -> SchedulerSettings:
        """Raises ValueError on a malformed value rather than falling back to the default."""
        raw = os.environ.get("SCHEDULER_ENABLED", "true").strip().lower()
        if raw not in _TRUTHY | _FALSY:
            raise ValueError(f"SCHEDULER_ENABLED must be true or false, got {raw!r}")
        return cls(
            enabled=raw in _TRUTHY,
            measure_window_days=_positive_int("MEASURE_WINDOW_DAYS", 14),
            outcome_linker_interval_minutes=_positive_int("OUTCOME_LINKER_INTERVAL_MINUTES", 15),
        )


@dataclass(frozen=True)
class Job:
    name: str
    interval: timedelta
    run: Callable[[datetime], Awaitable[Any]]  # receives the run's `now`


def build_jobs(pool: asyncpg.Pool, settings: SchedulerSettings) -> list[Job]:
    """Every scheduled job. Later phases add theirs here (spec.md §10.4)."""
    linker = PgOutcomeLinker(pool, window=timedelta(days=settings.measure_window_days))
    return [
        Job("outcome_linker", timedelta(minutes=settings.outcome_linker_interval_minutes),
            linker.run),
    ]


async def run_job(job: Job, clock: Clock = utc_now) -> None:
    """Logs a failure at ERROR and returns, so one bad run does not stop the schedule."""
    with get_tracer().start_as_current_span(f"job.{job.name}"):
        try:
            await job.run(clock())
        except Exception:
            log.error("scheduled_job_failed", job=job.name, exc_info=True)


class JobScheduler:
    def __init__(self, jobs: list[Job], clock: Clock = utc_now) -> None:
        self._jobs = jobs
        self._clock = clock
        self._scheduler: AsyncIOScheduler | None = None

    @property
    def job_names(self) -> list[str]:
        return [job.name for job in self._jobs]

    @property
    def running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    def start(self) -> None:
        """Must be called from inside the running event loop. Each job first runs one
        interval after start."""
        scheduler = AsyncIOScheduler(timezone=UTC)
        for job in self._jobs:
            scheduler.add_job(run_job, "interval", args=[job, self._clock], id=job.name,
                              seconds=job.interval.total_seconds(), max_instances=1,
                              coalesce=True, replace_existing=True)
        scheduler.start()
        self._scheduler = scheduler
        log.info("scheduler_started", jobs=self.job_names)

    def shutdown(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("scheduler_stopped")
        self._scheduler = None
