from __future__ import annotations

__all__ = ["Event", "EventBind", "OrEvent"]

# python
from asyncio import FIRST_COMPLETED
from asyncio import Future
from asyncio import create_task
from asyncio import wait
from functools import wraps
from typing import Any
from typing import Callable
from typing import Coroutine
from typing import Generator
from typing import Generic
from typing import Self
from typing import TypeVar
from weakref import WeakSet
from weakref import ref

_T = TypeVar("_T")
_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")


class EventBind(Generic[_T]):
    _callback: Callable[[_T], Coroutine[Any, Any, None]] | None

    def __init__(
        self,
        callback: Callable[[_T], Coroutine[Any, Any, None]]
        | ref[Callable[[_T], Coroutine[Any, Any, None]]],
    ):
        if isinstance(callback, ref):

            @wraps(callback)
            async def weak_callback(data: _T) -> Any:
                strong_callback = callback()
                if strong_callback is None:
                    return
                return await strong_callback(data)

            self._callback = weak_callback
        else:
            self._callback = callback

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any, **kwargs: Any) -> None:
        self.close()

    def close(self) -> None:
        self._callback = None


class Event(Generic[_T]):
    _future: Future[_T] | None = None

    def __init__(self) -> None:
        self._binds: WeakSet[EventBind[_T]] = WeakSet()

    def __await__(self) -> Generator[Any, None, _T]:
        return self._get_future().__await__()

    def __call__(self, data: _T) -> None:
        if self._future is not None:
            self._future.set_result(data)
            self._future = None

        closed_binds: set[EventBind[_T]] = set()
        for bind in self._binds:
            if bind._callback is None:
                closed_binds.add(bind)
            else:
                create_task(bind._callback(data))
        self._binds -= closed_binds

    def __or__(self: Event[_T1], other: Event[_T2]) -> OrEvent[_T1 | _T2]:
        return OrEvent(self, other)

    def _get_future(self) -> Future[_T]:
        if self._future is None:
            self._future = Future()
        return self._future

    def then(
        self,
        callback: Callable[[_T], Coroutine[Any, Any, None]]
        | ref[Callable[[_T], Coroutine[Any, Any, None]]],
    ) -> EventBind[_T]:
        event_bind = EventBind(callback)
        self._binds.add(event_bind)
        return event_bind


class OrEvent(Generic[_T]):
    _future: Future[_T] | None = None

    def __init__(self, *events: Event):
        self._events = events

    def __await__(self) -> Generator[Any, None, tuple[Event, _T]]:
        return self._await().__await__()

    def __or__(self: OrEvent[_T1], other: Event[_T2]) -> OrEvent[_T1 | _T2]:
        return OrEvent(*self._events, other)

    async def _await(self) -> tuple[Event, _T]:
        future_event = {e._get_future(): e for e in self._events}
        done, _ = await wait(future_event.keys(), return_when=FIRST_COMPLETED)
        for first in done:
            return future_event[first], await first
        assert False
