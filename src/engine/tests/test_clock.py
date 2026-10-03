"""common.clock and the engine's data windows honoring LMS_AS_OF."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from common import clock
from engine.api.measurement import time_range
from engine.jobs.scheduler import utc_now


def test_unset_means_the_real_time(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LMS_AS_OF", raising=False)

    assert clock.as_of() is None
    assert abs(clock.now() - datetime.now(UTC)) < timedelta(seconds=5)


def test_blank_means_the_real_time(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LMS_AS_OF", "  ")

    assert clock.as_of() is None


def test_a_date_means_midnight_utc(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LMS_AS_OF", "2026-09-15")

    assert clock.now() == datetime(2026, 9, 15, tzinfo=UTC)


def test_a_naive_timestamp_is_utc_and_an_offset_is_kept(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LMS_AS_OF", "2026-09-15T13:30:00")
    assert clock.now() == datetime(2026, 9, 15, 13, 30, tzinfo=UTC)

    monkeypatch.setenv("LMS_AS_OF", "2026-09-15T13:30:00+02:00")
    assert clock.now() == datetime(2026, 9, 15, 11, 30, tzinfo=UTC)


def test_a_malformed_value_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LMS_AS_OF", "next tuesday")

    with pytest.raises(ValueError, match="LMS_AS_OF"):
        clock.now()


def test_measurement_window_defaults_to_the_as_of_instant(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LMS_AS_OF", "2026-09-15")

    _, stop = time_range(None, None)

    assert stop == datetime(2026, 9, 15, tzinfo=UTC)


def test_scheduled_jobs_run_at_the_as_of_instant(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LMS_AS_OF", "2026-09-15")

    assert utc_now() == datetime(2026, 9, 15, tzinfo=UTC)
