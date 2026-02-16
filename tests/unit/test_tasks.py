"""Tests for tle.util.tasks.

Waiter, ExceptionHandler, Task, TaskSpec, decorators.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tle.util.events import ContestListRefresh
from tle.util.tasks import (
    ExceptionHandler,
    Task,
    TaskAlreadyRunning,
    TaskSpec,
    Waiter,
    WaiterRequired,
    task,
    task_spec,
)

# --- Waiter ---


class TestWaiter:
    def test_fixed_delay_creation(self):
        w = Waiter.fixed_delay(5.0)
        assert w.run_first is False
        assert w.needs_instance is False

    def test_fixed_delay_run_first(self):
        w = Waiter.fixed_delay(5.0, run_first=True)
        assert w.run_first is True

    async def test_fixed_delay_wait_returns_delay(self):
        w = Waiter.fixed_delay(0.01)
        result = await w.wait()
        assert result == 0.01

    @patch('tle.util.tasks.cf_common')
    def test_for_event_creation(self, mock_cf_common):
        w = Waiter.for_event(ContestListRefresh)
        assert w.run_first is True
        assert w.needs_instance is False

    @patch('tle.util.tasks.cf_common')
    async def test_for_event_wait_delegates(self, mock_cf_common):
        mock_event = ContestListRefresh([1, 2])
        mock_cf_common.event_sys.wait_for = AsyncMock(return_value=mock_event)
        w = Waiter.for_event(ContestListRefresh)
        result = await w.wait()
        assert result is mock_event
        mock_cf_common.event_sys.wait_for.assert_awaited_once_with(ContestListRefresh)

    def test_requires_coroutine(self):
        def sync_func():
            pass

        with pytest.raises(TypeError, match='coroutine'):
            Waiter(sync_func)

    async def test_wait_with_instance(self):
        results = []

        async def wait_func(instance):
            results.append(instance)
            return 'done'

        w = Waiter(wait_func, needs_instance=True)
        result = await w.wait(instance='my_instance')
        assert result == 'done'
        assert results == ['my_instance']


# --- ExceptionHandler ---


class TestExceptionHandler:
    def test_requires_coroutine(self):
        def sync_func(ex):
            pass

        with pytest.raises(TypeError, match='coroutine'):
            ExceptionHandler(sync_func)

    async def test_handle_calls_func(self):
        handled = []

        async def handler(ex):
            handled.append(ex)

        eh = ExceptionHandler(handler)
        err = ValueError('test')
        await eh.handle(err)
        assert handled == [err]

    async def test_handle_with_instance(self):
        handled = []

        async def handler(instance, ex):
            handled.append((instance, ex))

        eh = ExceptionHandler(handler, needs_instance=True)
        err = ValueError('test')
        await eh.handle(err, instance='obj')
        assert handled == [('obj', err)]


# --- Task ---


class TestTask:
    def test_requires_coroutine(self):
        def sync_func(arg):
            pass

        with pytest.raises(TypeError, match='coroutine'):
            Task('test', sync_func, None)

    def test_not_running_initially(self):
        async def func(arg):
            pass

        t = Task('test', func, None)
        assert t.running is False

    def test_start_without_waiter_raises(self):
        async def func(arg):
            pass

        t = Task('test', func, None)
        with pytest.raises(WaiterRequired):
            t.start()

    async def test_start_and_stop_lifecycle(self):
        call_count = 0

        async def func(arg):
            nonlocal call_count
            call_count += 1

        w = Waiter.fixed_delay(0.01)
        t = Task('test', func, w)
        try:
            t.start()
            assert t.running is True
            await asyncio.sleep(0.05)
            assert call_count >= 1
        finally:
            await t.stop()
        # After stop, wait for cancellation to propagate
        await asyncio.sleep(0.01)
        assert t.running is False

    async def test_start_already_running_raises(self):
        async def func(arg):
            pass

        w = Waiter.fixed_delay(0.1)
        t = Task('test', func, w)
        try:
            t.start()
            with pytest.raises(TaskAlreadyRunning):
                t.start()
        finally:
            await t.stop()

    async def test_manual_trigger_with_arg(self):
        received = []

        async def func(arg):
            received.append(arg)

        t = Task('test', func, None)
        await t.manual_trigger(arg='hello')
        assert received == ['hello']

    async def test_manual_trigger_none_default(self):
        received = []

        async def func(arg):
            received.append(arg)

        t = Task('test', func, None)
        await t.manual_trigger()
        assert received == [None]

    async def test_exception_handler_called_on_error(self):
        errors = []

        async def func(arg):
            raise ValueError('boom')

        async def handle_ex(ex):
            errors.append(str(ex))

        eh = ExceptionHandler(handle_ex)
        t = Task('test', func, None, exception_handler=eh)
        await t.manual_trigger()
        assert errors == ['boom']

    async def test_func_called_with_instance(self):
        received = []

        async def func(self, arg):
            received.append((self, arg))

        t = Task('test', func, None, instance='my_obj')
        await t.manual_trigger(arg='data')
        assert received == [('my_obj', 'data')]

    async def test_waiter_run_first_ordering(self):
        order = []

        async def func(arg):
            order.append(f'func:{arg}')

        w = Waiter.fixed_delay(0.01, run_first=True)
        t = Task('test', func, w)
        try:
            t.start()
            await asyncio.sleep(0.05)
            # With run_first=True, the waiter runs before the first func call
            # so first func call receives the waiter result (0.01)
            assert len(order) >= 1
            assert order[0] == 'func:0.01'
        finally:
            await t.stop()

    def test_waiter_decorator(self):
        async def func(arg):
            pass

        t = Task('test', func, None)

        @t.waiter()
        async def my_waiter():
            return 42

        assert t._waiter is not None
        assert isinstance(t._waiter, Waiter)

    def test_exception_handler_decorator(self):
        async def func(arg):
            pass

        t = Task('test', func, None)

        @t.exception_handler()
        async def my_handler(ex):
            pass

        assert t._exception_handler is not None
        assert isinstance(t._exception_handler, ExceptionHandler)

    async def test_running_false_after_stop(self):
        async def func(arg):
            pass

        w = Waiter.fixed_delay(0.1)
        t = Task('test', func, w)
        try:
            t.start()
            assert t.running is True
        finally:
            await t.stop()
        await asyncio.sleep(0.01)
        assert t.running is False


# --- TaskSpec ---


class TestTaskSpec:
    def test_requires_coroutine(self):
        def sync_func(self, arg):
            pass

        with pytest.raises(TypeError, match='coroutine'):
            TaskSpec('test', sync_func)

    def test_descriptor_returns_self_from_class(self):
        async def func(self, arg):
            pass

        spec = TaskSpec('test', func)

        class MyClass:
            my_task = spec

        assert MyClass.my_task is spec

    def test_creates_task_from_instance(self):
        async def func(self, arg):
            pass

        spec = TaskSpec('test', func, waiter=Waiter.fixed_delay(1.0))

        class MyClass:
            my_task = spec

        obj = MyClass()
        result = obj.my_task
        assert isinstance(result, Task)
        assert result.name == 'test'
        assert result.instance is obj

    def test_caches_per_instance(self):
        async def func(self, arg):
            pass

        spec = TaskSpec('test', func)

        class MyClass:
            my_task = spec

        obj = MyClass()
        assert obj.my_task is obj.my_task

    def test_different_instances_get_different_tasks(self):
        async def func(self, arg):
            pass

        spec = TaskSpec('test', func)

        class MyClass:
            my_task = spec

        a = MyClass()
        b = MyClass()
        assert a.my_task is not b.my_task

    def test_waiter_decorator(self):
        async def func(self, arg):
            pass

        spec = TaskSpec('test', func)

        @spec.waiter()
        async def my_waiter(self):
            return 42

        assert spec._waiter is not None

    def test_exception_handler_decorator(self):
        async def func(self, arg):
            pass

        spec = TaskSpec('test', func)

        @spec.exception_handler()
        async def my_handler(self, ex):
            pass

        assert spec._exception_handler is not None


# --- Decorators ---


class TestDecorators:
    def test_task_creates_task(self):
        @task(name='test', waiter=Waiter.fixed_delay(1.0))
        async def my_task(arg):
            pass

        assert isinstance(my_task, Task)
        assert my_task.name == 'test'
        assert my_task.instance is None

    def test_task_spec_creates_task_spec(self):
        @task_spec(name='test')
        async def my_task(self, arg):
            pass

        assert isinstance(my_task, TaskSpec)
        assert my_task.name == 'test'
