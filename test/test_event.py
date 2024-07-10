# eevent
from eevent import Event

# pytest
import pytest

# python
import asyncio
import weakref


@pytest.mark.parametrize("data", [1, None])
def test_event_call_and_future(event_loop, data):
    event = Event()
    future = event._get_future()
    assert not future.done()
    event(data)
    assert future.result() is data
    assert event._get_future() is not future


def test_event_await(event_loop):
    event = Event()

    async def _trigger_event():
        await asyncio.sleep(1)
        event(True)

    result = None

    async def _await_event():
        nonlocal result
        t = event_loop.create_task(_trigger_event())
        result = await event

    event_loop.run_until_complete(_await_event())
    assert result


def test_then(event_loop):
    event = Event()

    results = []

    async def _count(data):
        results.append(data)

    bind = event.then(_count)

    async def _main():
        event(1)
        event(2)
        assert not results
        bind.close()
        event(3)
        await asyncio.sleep(0)

    event_loop.run_until_complete(_main())
    assert results == [1, 2]


def test_then_weakref(event_loop):
    event = Event()

    results = []

    async def _count(data):
        results.append(data)
        del scope["count"]

    scope = {"count": _count}
    bind = event.then(weakref.ref(_count))
    del _count

    async def _main():
        event(1)
        event(2)
        event(3)
        await asyncio.sleep(0)

    event_loop.run_until_complete(_main())
    assert results == [1]


def test_then_weakmethod(event_loop):
    event = Event()

    results = []

    class X:
        def __init__(self):
            self.bind = event.then(weakref.WeakMethod(self._count))

        async def _count(self, data):
            results.append(data)
            del scope["x"]

    scope = {"x": X()}

    async def _main():
        event(1)
        event(2)
        event(3)
        await asyncio.sleep(0)

    event_loop.run_until_complete(_main())
    assert results == [1]


def test_then_context(event_loop):
    event = Event()

    results = []

    async def _count(data):
        results.append(data)

    bind = event.then(_count)

    async def _main():
        with bind:
            event(1)
            event(2)
            assert not results
        event(3)
        await asyncio.sleep(0)

    event_loop.run_until_complete(_main())
    assert results == [1, 2]


def test_or(event_loop):
    event_1 = Event()
    event_2 = Event()
    event_3 = Event()

    async def _await_event():
        t = event_loop.call_soon(event_1, 1)
        assert await (event_1 | event_2) == (event_1, 1)

        t = event_loop.call_soon(event_2, 2)
        assert await (event_1 | event_2) == (event_2, 2)

        t = event_loop.call_soon(event_2, 5)
        t2 = event_loop.call_later(0.1, event_1, 6)
        assert await (event_1 | event_2) == (event_2, 5)
        assert await event_1 == 6

        t = event_loop.call_soon(event_3, 3)
        t2 = event_loop.call_later(0.1, event_2, 4)
        assert await (event_1 | event_2) == (event_2, 4)

        t = event_loop.call_soon(event_1, 1)
        assert await (event_1 | event_2 | event_3) == (event_1, 1)

        t = event_loop.call_soon(event_2, 2)
        assert await (event_1 | event_2 | event_3) == (event_2, 2)

        t = event_loop.call_soon(event_3, 3)
        assert await (event_1 | event_2 | event_3) == (event_3, 3)

    event_loop.run_until_complete(_await_event())
