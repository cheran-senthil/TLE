import asyncio
import logging
from collections.abc import Callable
from typing import Any

from discord.ext import commands

import tle.util.codeforces_common as cf_common
from tle.util.events import Event


class TaskError(commands.CommandError):
    pass


class WaiterRequired(TaskError):
    def __init__(self, name: str) -> None:
        super().__init__(f'No waiter set for task `{name}`')


class TaskAlreadyRunning(TaskError):
    def __init__(self, name: str) -> None:
        super().__init__(f'Attempt to start task `{name}` which is already running')


def _ensure_coroutine_func(func: Callable[..., Any]) -> None:
    if not asyncio.iscoroutinefunction(func):
        raise TypeError('The decorated function must be a coroutine function.')


class Waiter:
    def __init__(
        self,
        func: Callable[..., Any],
        *,
        run_first: bool = False,
        needs_instance: bool = False,
    ) -> None:
        """Initializes a waiter with the given coroutine function `func`.

        `run_first` indicates whether this waiter should be run before the task's `func`
        when run for the first time. `needs_instance` indicates whether a self argument
        is required by the `func`.
        """
        _ensure_coroutine_func(func)
        self.func = func
        self.run_first = run_first
        self.needs_instance = needs_instance

    async def wait(self, instance: Any = None) -> Any:
        if self.needs_instance:
            return await self.func(instance)
        else:
            return await self.func()

    @staticmethod
    def fixed_delay(delay: float, run_first: bool = False) -> 'Waiter':
        """Returns a waiter that always waits for a fixed time.

        `delay` is in seconds and the waiter returns the time waited.
        """

        async def wait_func() -> float:
            await asyncio.sleep(delay)
            return delay

        return Waiter(wait_func, run_first=run_first)

    @staticmethod
    def for_event(event_cls: type[Event], run_first: bool = True) -> 'Waiter':
        """Returns a waiter that waits for the given event.

        The waiter returns the result of the event.
        """

        async def wait_func() -> Event:
            return await cf_common.event_sys.wait_for(event_cls)

        return Waiter(wait_func, run_first=run_first)


class ExceptionHandler:
    def __init__(
        self, func: Callable[..., Any], *, needs_instance: bool = False
    ) -> None:
        """Initializes an exception handler with the given coroutine function `func`.

        `needs_instance` indicates whether a self argument is required by the `func`.
        """
        _ensure_coroutine_func(func)
        self.func = func
        self.needs_instance = needs_instance

    async def handle(self, exception: Exception, instance: Any = None) -> None:
        if self.needs_instance:
            await self.func(instance, exception)
        else:
            await self.func(exception)


class Task:
    """A task that repeats until stopped.

    A task must have a name, a coroutine function `func` to execute
    periodically and another coroutine function `waiter` to wait on between
    calls to `func`. The return value of `waiter` is passed to `func` in the
    next call. An optional coroutine function `exception_handler` may be
    provided to which exceptions will be reported.
    """

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        waiter: Waiter | None,
        exception_handler: ExceptionHandler | None = None,
        *,
        instance: Any = None,
    ) -> None:
        """`instance`, if present, is passed as the first argument to `func`."""
        _ensure_coroutine_func(func)
        self.name = name
        self.func = func
        self._waiter = waiter
        self._exception_handler = exception_handler
        self.instance = instance
        self.asyncio_task: asyncio.Task[None] | None = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def waiter(
        self, run_first: bool = False
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator that sets the coroutine as the waiter for this Task."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._waiter = Waiter(func, run_first=run_first)
            return func

        return decorator

    def exception_handler(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator that sets the function as the exception handler for this Task."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._exception_handler = ExceptionHandler(func)
            return func

        return decorator

    @property
    def running(self) -> bool:
        return self.asyncio_task is not None and not self.asyncio_task.done()

    def start(self) -> None:
        """Starts up the task."""
        if self._waiter is None:
            raise WaiterRequired(self.name)
        if self.running:
            raise TaskAlreadyRunning(self.name)
        self.logger.info(f'Starting up task `{self.name}`.')
        self.asyncio_task = asyncio.create_task(self._task())

    async def manual_trigger(self, arg: Any = None) -> None:
        """Manually triggers the `func` with the optionally provided `arg`."""
        self.logger.info(f'Manually triggering task `{self.name}`.')
        await self._execute_func(arg)

    async def stop(self) -> None:
        """Stops the task, interrupting the currently running coroutines."""
        if self.running and self.asyncio_task is not None:
            self.logger.info(f'Stopping task `{self.name}`.')
            self.asyncio_task.cancel()
            await asyncio.sleep(
                0
            )  # To ensure cancellation if called from within the task itself.

    async def _task(self) -> None:
        assert self._waiter is not None
        arg = None
        if self._waiter.run_first:
            arg = await self._waiter.wait(self.instance)
        while True:
            await self._execute_func(arg)
            arg = await self._waiter.wait(self.instance)

    async def _execute_func(self, arg: Any) -> None:
        try:
            if self.instance is not None:
                await self.func(self.instance, arg)
            else:
                await self.func(arg)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            self.logger.warning(
                f'Exception in task `{self.name}`, ignoring.', exc_info=True
            )
            if self._exception_handler is not None:
                await self._exception_handler.handle(ex, self.instance)


class TaskSpec:
    """A descriptor intended to be an interface between an instance and its tasks.

    It creates the expected task when `__get__` is called from an instance for
    the first time. No two task specs in the same class should have the same
    name.
    """

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        waiter: Waiter | None = None,
        exception_handler: ExceptionHandler | None = None,
    ) -> None:
        _ensure_coroutine_func(func)
        self.name = name
        self.func = func
        self._waiter = waiter
        self._exception_handler = exception_handler

    def waiter(
        self, run_first: bool = False, needs_instance: bool = True
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator that sets the coroutine as the waiter for this TaskSpec."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._waiter = Waiter(
                func, run_first=run_first, needs_instance=needs_instance
            )
            return func

        return decorator

    def exception_handler(
        self, needs_instance: bool = True
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator that sets the coroutine as the exception handler for this TaskSpec."""  # noqa: E501

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._exception_handler = ExceptionHandler(
                func, needs_instance=needs_instance
            )
            return func

        return decorator

    def __get__(self, instance: Any, owner: type) -> 'TaskSpec | Task':
        if instance is None:
            return self
        try:
            tasks: dict[str, Task] = instance.___tasks___
        except AttributeError:
            tasks = instance.___tasks___ = {}
        if self.name not in tasks:
            tasks[self.name] = Task(
                self.name,
                self.func,
                self._waiter,
                self._exception_handler,
                instance=instance,
            )
        return tasks[self.name]


def task(
    *,
    name: str,
    waiter: Waiter | None = None,
    exception_handler: ExceptionHandler | None = None,
) -> Callable[[Callable[..., Any]], Task]:
    """Returns a decorator that creates a `Task` with the given options."""

    def decorator(func: Callable[..., Any]) -> Task:
        return Task(name, func, waiter, exception_handler, instance=None)

    return decorator


def task_spec(
    *,
    name: str,
    waiter: Waiter | None = None,
    exception_handler: ExceptionHandler | None = None,
) -> Callable[[Callable[..., Any]], TaskSpec]:
    """Decorator that creates a `TaskSpec` descriptor with the given options."""

    def decorator(func: Callable[..., Any]) -> TaskSpec:
        return TaskSpec(name, func, waiter, exception_handler)

    return decorator
