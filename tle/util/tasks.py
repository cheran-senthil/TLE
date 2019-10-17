import asyncio
import logging

from discord.ext import commands

import tle.util.codeforces_common as cf_common


class TaskError(commands.CommandError):
    pass


class WaiterRequired(TaskError):
    def __init__(self, name):
        super().__init__(f'No waiter set for task `{name}`')


class TaskAlreadyRunning(TaskError):
    def __init__(self, name):
        super().__init__(f'Attempt to start task `{name}` which is already running')


def _ensure_coroutine_func(func):
    if not asyncio.iscoroutinefunction(func):
        raise TypeError('The decorated function must be a coroutine function.')


class Waiter:
    def __init__(self, func, *, run_first=False, needs_instance=False):
        """`run_first` denotes whether this waiter should be run before the task's `func` when
        run for the first time. `needs_instance` indicates whether a self argument is required by
        the `func`.
        """
        _ensure_coroutine_func(func)
        self.func = func
        self.run_first = run_first
        self.needs_instance = needs_instance

    async def wait(self, instance=None):
        if self.needs_instance:
            return await self.func(instance)
        else:
            return await self.func()

    @staticmethod
    def fixed_delay(delay, run_first=False):
        """Returns a waiter that always waits for the given time (in seconds) and returns the
        time waited.
        """

        async def wait_func():
            await asyncio.sleep(delay)
            return delay

        return Waiter(wait_func, run_first=run_first)

    @staticmethod
    def for_event(event_cls, run_first=True):
        """Returns a waiter that waits for the given event and returns the result of that
        event.
        """

        async def wait_func():
            return await cf_common.event_sys.wait_for(event_cls)

        return Waiter(wait_func, run_first=run_first)


class ExceptionHandler:
    def __init__(self, func, *, needs_instance=False):
        """`needs_instance` indicates whether a self argument is required by the `func`."""
        _ensure_coroutine_func(func)
        self.func = func
        self.needs_instance = needs_instance

    async def handle(self, exception, instance=None):
        if self.needs_instance:
            await self.func(instance, exception)
        else:
            await self.func(exception)


class Task:
    """A task that repeats until stopped. A task must have a name, a coroutine function `func` to
    execute periodically and another coroutine function `waiter` to wait on between calls to `func`.
    The return value of `waiter` is passed to `func` in the next call. An optional coroutine
    function `exception_handler` may be provided to which exceptions will be reported.
    """

    def __init__(self, name, func, waiter, exception_handler=None, *, instance=None):
        """`instance`, if present, is passed as the first argument to `func`."""
        _ensure_coroutine_func(func)
        self.name = name
        self.func = func
        self._waiter = waiter
        self._exception_handler = exception_handler
        self.instance = instance
        self.asyncio_task = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def waiter(self, run_first=False):
        """Returns a decorator that sets the decorated coroutine function as the waiter for this
        Task.
        """

        def decorator(func):
            self._waiter = Waiter(func, run_first=run_first)
            return func

        return decorator

    def exception_handler(self):
        """Returns a decorator that sets the decorated coroutine function as the exception handler
        for this Task.
        """

        def decorator(func):
            self._exception_handler = ExceptionHandler(func)
            return func

        return decorator

    @property
    def running(self):
        return self.asyncio_task is not None and not self.asyncio_task.done()

    def start(self):
        """Starts up the task."""
        if self._waiter is None:
            raise WaiterRequired(self.name)
        if self.running:
            raise TaskAlreadyRunning(self.name)
        self.logger.info(f'Starting up task `{self.name}`.')
        self.asyncio_task = asyncio.create_task(self._task())

    async def manual_trigger(self, arg=None):
        """Manually triggers the `func` with the optionally provided `arg`, which defaults to
        `None`.
        """
        self.logger.info(f'Manually triggering task `{self.name}`.')
        await self._execute_func(arg)

    async def stop(self):
        """Stops the task, interrupting the currently running coroutines."""
        if self.running:
            self.logger.info(f'Stopping task `{self.name}`.')
            self.asyncio_task.cancel()
            await asyncio.sleep(0)  # To ensure cancellation if called from within the task itself.

    async def _task(self):
        arg = None
        if self._waiter.run_first:
            arg = await self._waiter.wait(self.instance)
        while True:
            await self._execute_func(arg)
            arg = await self._waiter.wait(self.instance)

    async def _execute_func(self, arg):
        try:
            if self.instance is not None:
                await self.func(self.instance, arg)
            else:
                await self.func(arg)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            self.logger.warning(f'Exception in task `{self.name}`, ignoring.', exc_info=True)
            if self._exception_handler is not None:
                await self._exception_handler.handle(ex, self.instance)


class TaskSpec:
    """A descriptor intended to be an interface between an instance and its tasks. It creates
    the expected task when `__get__` is called from an instance for the first time. No two task
    specs in the same class should have the same name."""

    def __init__(self, name, func, waiter=None, exception_handler=None):
        _ensure_coroutine_func(func)
        self.name = name
        self.func = func
        self._waiter = waiter
        self._exception_handler = exception_handler

    def waiter(self, run_first=False, needs_instance=True):
        """Returns a decorator that sets the decorated coroutine function as the waiter for this
        TaskSpec.
        """

        def decorator(func):
            self._waiter = Waiter(func, run_first=run_first, needs_instance=needs_instance)
            return func

        return decorator

    def exception_handler(self, needs_instance=True):
        """Returns a decorator that sets the decorated coroutine function as the exception handler
        for this TaskSpec.
        """

        def decorator(func):
            self._exception_handler = ExceptionHandler(func, needs_instance=needs_instance)
            return func

        return decorator

    def __get__(self, instance, owner):
        if instance is None:
            return self
        try:
            tasks = getattr(instance, '___tasks___')
        except AttributeError:
            tasks = instance.___tasks___ = {}
        if self.name not in tasks:
            tasks[self.name] = Task(self.name, self.func, self._waiter, self._exception_handler,
                                    instance=instance)
        return tasks[self.name]


def task(*, name, waiter=None, exception_handler=None):
    """Returns a decorator that creates a `Task` with the given options."""

    def decorator(func):
        return Task(name, func, waiter, exception_handler, instance=None)

    return decorator


def task_spec(*, name, waiter=None, exception_handler=None):
    """Returns a decorator that creates a `TaskSpec` descriptor with the given options."""

    def decorator(func):
        return TaskSpec(name, func, waiter, exception_handler)

    return decorator
