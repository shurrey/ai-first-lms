"""SessionStore / TurnStore as caches over `Persistence`, against an in-memory fake."""

from __future__ import annotations

import logging

import pytest

from engine.db import INTERRUPTED_MESSAGE, SessionStore, TurnStore
from engine.models.session import Session
from engine.models.turn import Turn
from engine.tests.persistence_fakes import FakePersistence


def _events(*names: str) -> list[dict]:
    return [{"event": n, "payload": {"text": n}} for n in names]


@pytest.fixture
def repo() -> FakePersistence:
    return FakePersistence()


async def _turn(store: TurnStore, status: str = "active") -> Turn:
    turn = Turn(session_id="s1", message="hello", status=status)
    await store.create(turn)
    return turn


async def test_events_get_contiguous_sequences_from_one(repo):
    store = TurnStore(repo)
    turn = await _turn(store)
    await store.add_events(turn.id, _events("reasoning", "plan"))
    await store.add_events(turn.id, _events("final"))

    events = await store.get_events(turn.id)
    assert [e["sequence"] for e in events] == [1, 2, 3]
    assert all(e["timestamp"] for e in events)


async def test_writes_go_through_to_the_repository(repo):
    store = TurnStore(repo)
    turn = await _turn(store)
    await store.add_events(turn.id, _events("reasoning", "final"))
    await store.update_status(turn.id, "completed")
    await store.record_usage(turn.id, 0.02, 120)

    assert repo.turns[turn.id]["status"] == "completed"
    assert (repo.turns[turn.id]["cost_usd"], repo.turns[turn.id]["tokens"]) == (0.02, 120)
    assert repo.events[turn.id] == await store.get_events(turn.id)


async def test_since_sequence_returns_only_later_events(repo):
    store = TurnStore(repo)
    turn = await _turn(store)
    await store.add_events(turn.id, _events("a", "b", "c", "d"))

    tail = await store.get_events(turn.id, since_sequence=2)
    assert [(e["sequence"], e["event"]) for e in tail] == [(3, "c"), (4, "d")]
    assert await store.get_events(turn.id, since_sequence=4) == []


async def test_cache_miss_reads_the_turn_and_events_from_the_repository(repo):
    first = TurnStore(repo)
    turn = await _turn(first)
    await first.add_events(turn.id, _events("reasoning", "plan", "final"))
    await first.update_status(turn.id, "completed")
    original = await first.get_events(turn.id)

    restarted = TurnStore(repo)
    loaded = await restarted.get(turn.id)

    assert loaded is not None and loaded.status == "completed"
    assert await restarted.get_events(turn.id, since_sequence=1) == original[1:]


async def test_replayed_sequences_and_timestamps_match_the_original(repo):
    first = TurnStore(repo)
    turn = await _turn(first)
    await first.add_events(turn.id, _events("a", "b"))
    await first.update_status(turn.id, "completed")

    replayed = await TurnStore(repo).get_events(turn.id)
    assert [(e["sequence"], e["timestamp"]) for e in replayed] == [
        (e["sequence"], e["timestamp"]) for e in await first.get_events(turn.id)]


async def test_unknown_turn_is_none_with_or_without_a_repository(repo):
    assert await TurnStore(repo).get("missing") is None
    assert await TurnStore().get("missing") is None


async def test_turn_still_running_in_the_database_is_closed_as_interrupted(repo):
    first = TurnStore(repo)
    turn = await _turn(first)
    await first.add_events(turn.id, _events("reasoning"))
    await first.update_status(turn.id, "awaiting_approval")

    restarted = TurnStore(repo)
    events = await restarted.get_events(turn.id)

    assert (await restarted.get(turn.id)).status == "error"
    assert [(e["sequence"], e["event"]) for e in events] == [(1, "reasoning"), (2, "error")]
    assert events[1]["payload"]["message"] == INTERRUPTED_MESSAGE
    assert repo.turns[turn.id]["status"] == "error"
    assert [e["sequence"] for e in repo.events[turn.id]] == [1, 2]


async def test_database_down_turn_runs_from_cache_and_logs_error(repo, caplog):
    repo.fail = True
    store = TurnStore(repo)
    with caplog.at_level(logging.ERROR, logger="engine.db"):
        turn = await _turn(store)
        await store.add_events(turn.id, _events("reasoning", "final"))
        await store.update_status(turn.id, "completed")

    assert [e["event"] for e in await store.get_events(turn.id)] == ["reasoning", "final"]
    assert (await store.get(turn.id)).status == "completed"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and turn.id in errors[0].getMessage()


async def test_turn_stops_writing_after_a_failed_write(repo):
    store = TurnStore(repo)
    turn = await _turn(store)
    await store.add_events(turn.id, _events("a"))
    repo.fail = True
    await store.add_events(turn.id, _events("b"))
    repo.fail = False
    await store.add_events(turn.id, _events("c"))

    assert [e["sequence"] for e in repo.events[turn.id]] == [1]
    assert [e["sequence"] for e in await store.get_events(turn.id)] == [1, 2, 3]


async def test_load_failure_is_logged_and_reported_as_missing(repo, caplog):
    turn = await _turn(TurnStore(repo))
    repo.fail = True
    with caplog.at_level(logging.ERROR, logger="engine.db"):
        assert await TurnStore(repo).get(turn.id) is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


async def test_session_store_reads_through_on_cache_miss(repo):
    session = Session(persona="student", person_id="p1", course_id="c1",
                      requester_name="Emma")
    await SessionStore(repo).create(session)

    loaded = await SessionStore(repo).get(session.id)
    assert loaded is not None
    assert (loaded.person_id, loaded.persona, loaded.course_id, loaded.requester_name) == (
        "p1", "student", "c1", "Emma")


async def test_session_store_survives_a_database_outage(repo, caplog):
    repo.fail = True
    store = SessionStore(repo)
    session = Session(persona="student", person_id="p1", course_id="c1")
    with caplog.at_level(logging.ERROR, logger="engine.db"):
        await store.create(session)
        assert await store.get(session.id) is session
        assert await store.get("other") is None
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 2
