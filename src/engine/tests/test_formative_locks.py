import asyncio

from engine.formative.locks import KeyedLocks


async def test_a_key_is_dropped_once_no_task_holds_or_waits_on_it():
    locks = KeyedLocks()
    order: list[str] = []
    first_in = asyncio.Event()

    async def worker(name: str) -> None:
        async with locks.hold("emma"):
            order.append(f"{name}+")
            first_in.set()
            await asyncio.sleep(0)
            order.append(f"{name}-")

    a = asyncio.create_task(worker("a"))
    await first_in.wait()
    b = asyncio.create_task(worker("b"))
    await asyncio.sleep(0)
    assert len(locks) == 1
    await asyncio.gather(a, b)

    assert order == ["a+", "a-", "b+", "b-"]
    assert len(locks) == 0


async def test_the_key_is_released_when_the_body_raises():
    locks = KeyedLocks()
    try:
        async with locks.hold("k"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert len(locks) == 0
