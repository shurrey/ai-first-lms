"""Fire-and-forget tasks held in `app.state.background_tasks` so they are not collected."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


def spawn(tasks: set[asyncio.Task[Any]], coro: Coroutine[Any, Any, Any], *, name: str
          ) -> asyncio.Task[Any]:
    """Start `coro`, hold it in `tasks` until done, and log an exception it ends with."""
    task = asyncio.create_task(coro, name=name)
    tasks.add(task)
    task.add_done_callback(lambda t: _finished(tasks, t))
    return task


def _finished(tasks: set[asyncio.Task[Any]], task: asyncio.Task[Any]) -> None:
    tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background task %s failed", task.get_name(), exc_info=exc)
