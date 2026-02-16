import asyncio
import logging
from collections.abc import Callable
from typing import Any

from discord.ext import commands

from tle.util import codeforces_api as cf

# Event types


class Event:
    """Base class for events."""

    pass


class ContestListRefresh(Event):
    def __init__(self, contests: list[cf.Contest]) -> None:
        self.contests = contests


class RatingChangesUpdate(Event):
    def __init__(
        self, *, contest: cf.Contest, rating_changes: list[cf.RatingChange]
    ) -> None:
        self.contest = contest
        self.rating_changes = rating_changes


# Event errors


class EventError(commands.CommandError):
    pass


class ListenerNotRegistered(EventError):
    def __init__(self, listener: 'Listener') -> None:
        super().__init__(
            f'Listener {listener.name} is not registered for event'
            f' {listener.event_cls.__name__}.'
        )


# Event system


class EventSystem:
    """Rudimentary event system."""

    def __init__(self) -> None:
        self.listeners_by_event: dict[type[Event], set[Listener]] = {}
        self.futures_by_event: dict[type[Event], list[asyncio.Future[Event]]] = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    def add_listener(self, listener: 'Listener') -> None:
        listeners = self.listeners_by_event.setdefault(listener.event_cls, set())
        listeners.add(listener)

    def remove_listener(self, listener: 'Listener') -> None:
        try:
            self.listeners_by_event[listener.event_cls].remove(listener)
        except KeyError:
            raise ListenerNotRegistered(listener)

    async def wait_for(
        self, event_cls: type[Event], *, timeout: float | None = None
    ) -> Event:
        future = asyncio.get_running_loop().create_future()
        futures = self.futures_by_event.setdefault(event_cls, [])
        futures.append(future)
        return await asyncio.wait_for(future, timeout)

    def dispatch(self, event_cls: type[Event], *args: Any, **kwargs: Any) -> None:
        self.logger.info(f'Dispatching event `{event_cls.__name__}`')
        event = event_cls(*args, **kwargs)
        for listener in self.listeners_by_event.get(event_cls, []):
            listener.trigger(event)
        futures = self.futures_by_event.pop(event_cls, [])
        for future in futures:
            if not future.done():
                future.set_result(event)


# Listener


def _ensure_coroutine_func(func: Callable[..., Any]) -> None:
    if not asyncio.iscoroutinefunction(func):
        raise TypeError('The listener function must be a coroutine function.')


class Listener:
    """A listener for a particular event.

    A listener must have a name, the event it should listen to and a coroutine
    function `func` that is called when the event is dispatched.
    """

    def __init__(
        self,
        name: str,
        event_cls: type[Event],
        func: Callable[..., Any],
        *,
        with_lock: bool = False,
    ) -> None:
        """Initialize the listener.

        `with_lock` controls whether execution of `func` should be guarded by
        an asyncio.Lock.
        """
        _ensure_coroutine_func(func)
        self.name = name
        self.event_cls = event_cls
        self.func = func
        self.lock = asyncio.Lock() if with_lock else None
        self.logger = logging.getLogger(self.__class__.__name__)

    def trigger(self, event: Event) -> None:
        asyncio.create_task(self._trigger(event))

    async def _trigger(self, event: Event) -> None:
        try:
            if self.lock:
                async with self.lock:
                    await self.func(event)
            else:
                await self.func(event)
        except asyncio.CancelledError:
            raise
        except:
            self.logger.exception(f'Exception in listener `{self.name}`.')

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Listener) and (self.event_cls, self.func) == (
            other.event_cls,
            other.func,
        )

    def __hash__(self) -> int:
        return hash((self.event_cls, self.func))


class ListenerSpec:
    """A descriptor intended to be an interface between an instance and its listeners.

    It creates the expected listener when `__get__` is called from an instance
    for the first time. No two listener specs in the same class should have the
    same name.
    """

    def __init__(
        self,
        name: str,
        event_cls: type[Event],
        func: Callable[..., Any],
        *,
        with_lock: bool = False,
    ) -> None:
        """Initialize the listener spec.

        `with_lock` controls whether execution of `func` should be guarded by
        an asyncio.Lock.
        """
        _ensure_coroutine_func(func)
        self.name = name
        self.event_cls = event_cls
        self.func = func
        self.with_lock = with_lock

    def __get__(self, instance: Any, owner: type) -> 'ListenerSpec | Listener':
        if instance is None:
            return self
        try:
            listeners: dict[str, Listener] = instance.___listeners___
        except AttributeError:
            listeners = instance.___listeners___ = {}
        if self.name not in listeners:
            # In Python <=3.7 iscoroutinefunction returns False for async
            # functions wrapped by functools.partial.
            # TODO: Use functools.partial when we move to Python 3.8.
            async def wrapper(event: Event) -> None:
                await self.func(instance, event)

            listeners[self.name] = Listener(
                self.name, self.event_cls, wrapper, with_lock=self.with_lock
            )
        return listeners[self.name]


def listener(
    *, name: str, event_cls: type[Event], with_lock: bool = False
) -> Callable[[Callable[..., Any]], Listener]:
    """Returns a decorator that creates a `Listener` with the given options."""

    def decorator(func: Callable[..., Any]) -> Listener:
        return Listener(name, event_cls, func, with_lock=with_lock)

    return decorator


def listener_spec(
    *, name: str, event_cls: type[Event], with_lock: bool = False
) -> Callable[[Callable[..., Any]], ListenerSpec]:
    """Returns a decorator that creates a `ListenerSpec` with the given options."""

    def decorator(func: Callable[..., Any]) -> ListenerSpec:
        return ListenerSpec(name, event_cls, func, with_lock=with_lock)

    return decorator
