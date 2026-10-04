"""Formative-loop policy values (spec.md §8.4) until the Phase 3 resolver replaces these.

Each value is a course-scope `policy_settings` row when one is current and valid, else the
vendor default. No other scope is consulted.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from engine.logging_config import get_logger

log = get_logger(__name__)

ReleaseMode = Literal["auto", "instructor_release"]

RELEASE_MODE_KEY = "feedback.release_mode"
WEAKNESS_WINDOW_KEY = "feedback.weakness_window"
SHOW_SCORES_KEY = "feedback.show_scores_on_drafts"

DEFAULT_RELEASE_MODE: ReleaseMode = "instructor_release"
DEFAULT_WEAKNESS_WINDOW = 3
WEAKNESS_WINDOW_RANGE = (2, 10)
DEFAULT_SHOW_SCORES = True


class CourseSettings(Protocol):
    async def course_setting(self, course_id: str, key: str) -> tuple[bool, Any]: ...


async def _course_value(settings: CourseSettings, course_id: str | None, key: str
                        ) -> tuple[bool, Any]:
    if not course_id:
        return False, None
    return await settings.course_setting(course_id, key)


async def release_mode(settings: CourseSettings, course_id: str | None) -> ReleaseMode:
    found, value = await _course_value(settings, course_id, RELEASE_MODE_KEY)
    if found and value in ("auto", "instructor_release"):
        return value  # type: ignore[no-any-return]
    if found:
        log.warning("policy_value_invalid", key=RELEASE_MODE_KEY, course_id=course_id)
    return DEFAULT_RELEASE_MODE


async def weakness_window(settings: CourseSettings, course_id: str | None) -> int:
    found, value = await _course_value(settings, course_id, WEAKNESS_WINDOW_KEY)
    low, high = WEAKNESS_WINDOW_RANGE
    if found and isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
        return value
    if found:
        log.warning("policy_value_invalid", key=WEAKNESS_WINDOW_KEY, course_id=course_id)
    return DEFAULT_WEAKNESS_WINDOW


async def show_scores_on_drafts(settings: CourseSettings, course_id: str | None) -> bool:
    found, value = await _course_value(settings, course_id, SHOW_SCORES_KEY)
    if found and isinstance(value, bool):
        return value
    if found:
        log.warning("policy_value_invalid", key=SHOW_SCORES_KEY, course_id=course_id)
    return DEFAULT_SHOW_SCORES
