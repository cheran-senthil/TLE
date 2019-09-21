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
        super().__init__(f'Task `{name}` is already running')


class Waiter:
    def __init__(self, coro, *, run_first=False, needs_self=True):
        """`run_first` denotes whether this waiter should be run before the task's `coro` when
        run for the first time. `needs_self` indicates whether a self argument is required by
        the `coro`.
        """
        self.coro = coro
        self.run_first = run_first
        self.needs_self = needs_self

    async def wait(self, self_arg=None):
        if self.needs_self:
            return await self.coro(self_arg)
        else:
            return await self.coro()

    @staticmethod
    def constant_delay(delay, run_first=False):
        """Returns a waiter that always waits for the given time (in seconds) and returns the
        time waited.
        """
        async def wait_coro():
            await asyncio.sleep(delay)
            return delay
        return Waiter(wait_coro, run_first=run_first, needs_self=False)

    @staticmethod
    def for_event(event, run_first=True):
        """Returns a waiter that waits for the given event and returns the result of that
        event.
        """
        async def wait_coro():
            return await cf_common.event_sys.wait_for(event)
        return Waiter(wait_coro, run_first=run_first, needs_self=False)


class ExceptionHandler:
    def __init__(self, coro, *, needs_self=True):
        """`needs_self` indicates whether a self argument is required by the `coro`."""
        self.coro = coro
        self.needs_self = needs_self

    async def handle(self, exception, self_arg=None):
        if self.needs_self:
            await self.coro(self_arg, exception)
        else:
            await self.coro(exception)


class Task:
    """A task that repeats until stopped. A task must have a name, a coroutine `coro` to execute
    periodically and another coroutine `waiter` to wait on between calls to `coro`. The return
    value of `waiter` is passed to `coro` in the next call. An optional coroutine
    `exception_handler` may be provided to which exceptions will be reported.
    """

    def __init__(self, name, coro, waiter, exception_handler=None, *, needs_self=True):
        """`needs_self` indicates whether a self argument is required by the `coro`."""
        self.name = name
        self.coro = coro
        self._waiter = waiter
        self._exception_handler = exception_handler
        self.needs_self = needs_self
        self.asyncio_task = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def waiter(self, run_first=False, needs_self=None):
        """Returns a decorator that sets the decorated coroutine as the waiter for this Task."""
        if needs_self is None:
            # If not specified, default to self's value.
            needs_self = self.needs_self

        def deco(coro):
            self._waiter = Waiter(coro, run_first=run_first, needs_self=needs_self)
            return coro
        return deco

    def exception_handler(self, needs_self=None):
        """Returns a decorator that sets the decorated coroutine as the exception handler for
        this Task.
        """
        if needs_self is None:
            # If not specified, default to self's value.
            needs_self = self.needs_self

        def deco(coro):
            self._exception_handler = ExceptionHandler(coro, needs_self=needs_self)
            return coro
        return deco

    @property
    def running(self):
        return self.asyncio_task is not None and not self.asyncio_task.done()

    def start(self, self_arg=None):
        """Starts up the task."""
        if self._waiter is None:
            raise WaiterRequired(self.name)
        if self.running:
            raise TaskAlreadyRunning(self.name)
        self.logger.info(f'Starting up task `{self.name}`')
        self.asyncio_task = asyncio.create_task(self._task(self_arg))

    async def manual_trigger(self, self_arg=None, arg=None):
        """Manually triggers the `coro` with the optionally provided `arg`, which defaults to
        `None`.
        """
        self.logger.info(f'Manually triggering task `{self.name}.')
        await self._execute_coro(self_arg, arg)

    def stop(self):
        """Stops the task, interrupting the currently running coroutines."""
        if self.running:
            self.logger.info(f'Stopping task `{self.name}`')
            self.asyncio_task.cancel()

    async def _task(self, self_arg):
        arg = None
        if self._waiter.run_first:
            arg = await self._waiter.wait(self_arg)
        while True:
            await self._execute_coro(self_arg, arg)
            arg = await self._waiter.wait(self_arg)

    async def _execute_coro(self, self_arg, arg):
        try:
            if self.needs_self:
                await self.coro(self_arg, arg)
            else:
                await self.coro(arg)
        except Exception as ex:
            self.logger.warning(f'Exception in task `{self.name}`, ignoring.', exc_info=True)
            if self._exception_handler is not None:
                await self._exception_handler.handle(ex, self_arg)


def task(*, name, waiter=None, exception_handler=None, needs_self=True):
    """Returns a decorator that creates a `Task` with the given options."""
    def deco(coro):
        return Task(name, coro, waiter, exception_handler, needs_self=needs_self)
    return deco
