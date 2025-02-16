__all__ = ["auto_bind", "Event", "EventBind", "on", "OrEvent"]

from asyncio import FIRST_COMPLETED
from asyncio import Future
from asyncio import create_task
from asyncio import wait
from functools import wraps
from types import MethodType
from typing import Any
from typing import Callable
from typing import Concatenate
from typing import Coroutine
from typing import Generator
from typing import Generic
from typing import Self
from typing import TypeVar
from typing import overload
from weakref import WeakMethod
from weakref import WeakSet
from weakref import ref

_C = TypeVar("_C", bound=type)
_T = TypeVar("_T")
_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")


class EventBind[T, **P]:
    _callback: Callable[Concatenate[T, P], Coroutine[Any, Any, None]] | None

    def __init__(
        self,
        callback: Callable[Concatenate[T, P], Coroutine[Any, Any, None]]
        | ref[Callable[Concatenate[T, P], Coroutine[Any, Any, None]]],
        *args: P.args,
        **kwargs: P.kwargs,
    ):
        self._args = args
        self._kwargs = kwargs

        if isinstance(callback, ref):

            @wraps(callback)
            async def weak_callback(data: T, *args: P.args, **kwargs: P.kwargs) -> Any:
                strong_callback = callback()
                if strong_callback is None:
                    return
                return await strong_callback(data, *args, **kwargs)

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
        self._binds: WeakSet[EventBind[_T, Any]] = WeakSet()

    def __await__(self) -> Generator[Any, None, _T]:
        return self._get_future().__await__()

    def __call__(self, data: _T) -> None:
        if self._future is not None:
            self._future.set_result(data)
            self._future = None

        closed_binds: set[EventBind[_T, Any]] = set()
        for bind in self._binds:
            if bind._callback is None:
                closed_binds.add(bind)
            else:
                create_task(bind._callback(data, *bind._args, **bind._kwargs))
        self._binds -= closed_binds

    def __or__(self: "Event[_T1]", other: "Event[_T2]") -> "OrEvent[_T1 | _T2]":
        return OrEvent(self, other)

    def _get_future(self) -> Future[_T]:
        if self._future is None:
            self._future = Future()
        return self._future

    def then[**P](
        self,
        callback: Callable[Concatenate[_T, P], Coroutine[Any, Any, None]]
        | ref[Callable[Concatenate[_T, P], Coroutine[Any, Any, None]]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> EventBind[_T, P]:
        event_bind = EventBind(callback, *args, **kwargs)
        self._binds.add(event_bind)
        return event_bind


class OrEvent(Generic[_T]):
    _future: Future[_T] | None = None

    def __init__(self, *events: Event):
        self._events = events

    def __await__(self) -> Generator[Any, None, tuple[Event, _T]]:
        return self._await().__await__()

    def __or__(self: "OrEvent[_T1]", other: Event[_T2]) -> "OrEvent[_T1 | _T2]":
        return OrEvent(*self._events, other)

    async def _await(self) -> tuple[Event, _T]:
        future_event = {e._get_future(): e for e in self._events}
        done, _ = await wait(future_event.keys(), return_when=FIRST_COMPLETED)
        for first in done:
            return future_event[first], await first
        assert False


class on(Generic[_C, _T]):
    @overload
    def __init__(self, *, event: Event[_T]) -> None: ...

    @overload
    def __init__(self, *, get_event: Callable[[_C], Event[_T]]) -> None: ...

    def __init__(
        self, *, event: Event[_T] | None = None, get_event: Callable[[_C], Event[_T]] | None = None
    ):
        if event is None and get_event is None:
            raise TypeError("event or get_event must be supplied")
        if event is not None and get_event is not None:
            raise TypeError("event or get_event must be supplied, but not both")
        self._event = event
        self._get_event = get_event

    def __call__(
        self, f: Callable[[_C, _T], Coroutine[Any, Any, None]]
    ) -> Callable[[_C, _T], Coroutine[Any, Any, None]]:
        return _OnEventThen(self, f)


class _OnEventThen(Generic[_C, _T]):
    def __init__(self, _on: on[_C, _T], method: Callable[[_C, _T], Coroutine[Any, Any, None]]):
        self._owner = None
        self._on = _on
        self._method = method

    async def __call__(self, instance: _C, event: _T) -> Any:
        return await self._method(instance, event)

    def __set_name__(self, owner, name):
        try:
            on_event_then = owner.__eevent_on_event_then__
        except AttributeError:
            on_event_then = owner.__eevent_on_event_then__ = set()
        self._owner = owner
        on_event_then.add(self)
        setattr(owner, name, self._method)


def auto_bind(cls: _C) -> _C:
    try:
        on_event_then = cls.__eevent_on_event_then__  # type: ignore
    except AttributeError:
        return cls
    on_event_then = {oet for oet in on_event_then if oet._owner is cls}

    original_init = cls.__init__

    @wraps(original_init)
    def wrapped_init(self: _C, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        try:
            auto_binds = self.__eevent_auto_binds__  # type: ignore
        except AttributeError:
            auto_binds = self.__eevent_auto_binds__ = []
        for oet in on_event_then:
            event = oet._on._event
            if event is None:
                event = oet._on._get_event(self)
            auto_binds.append(event.then(WeakMethod(MethodType(oet._method, self))))

    cls.__init__ = wrapped_init  # type: ignore

    return cls
