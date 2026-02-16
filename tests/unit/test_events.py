"""Tests for tle.util.events.

Event, Listener, EventSystem, ListenerSpec, decorators.
"""

import asyncio

import pytest

from tle.util.events import (
    ContestListRefresh,
    Event,
    EventSystem,
    Listener,
    ListenerNotRegistered,
    ListenerSpec,
    RatingChangesUpdate,
    listener,
    listener_spec,
)

# --- Event types ---


class TestEvent:
    def test_contest_list_refresh_stores_contests(self):
        contests = [1, 2, 3]
        event = ContestListRefresh(contests)
        assert event.contests == [1, 2, 3]

    def test_rating_changes_update_stores_data(self):
        event = RatingChangesUpdate(contest='c', rating_changes=['r1'])
        assert event.contest == 'c'
        assert event.rating_changes == ['r1']

    def test_base_event_instantiates(self):
        e = Event()
        assert isinstance(e, Event)


# --- Listener ---


class TestListener:
    def test_requires_coroutine(self):
        def sync_func(event):
            pass

        with pytest.raises(TypeError, match='coroutine'):
            Listener('test', ContestListRefresh, sync_func)

    def test_equality_by_event_cls_and_func(self):
        async def handler(event):
            pass

        a = Listener('a', ContestListRefresh, handler)
        b = Listener('b', ContestListRefresh, handler)
        assert a == b

    def test_inequality_different_func(self):
        async def handler1(event):
            pass

        async def handler2(event):
            pass

        a = Listener('a', ContestListRefresh, handler1)
        b = Listener('b', ContestListRefresh, handler2)
        assert a != b

    def test_inequality_different_event_cls(self):
        async def handler(event):
            pass

        a = Listener('a', ContestListRefresh, handler)
        b = Listener('b', RatingChangesUpdate, handler)
        assert a != b

    def test_hash_by_event_cls_and_func(self):
        async def handler(event):
            pass

        a = Listener('a', ContestListRefresh, handler)
        b = Listener('b', ContestListRefresh, handler)
        assert hash(a) == hash(b)

    async def test_trigger_calls_func(self):
        called_with = []

        async def handler(event):
            called_with.append(event)

        lst = Listener('test', ContestListRefresh, handler)
        event = ContestListRefresh([1])
        lst.trigger(event)
        await asyncio.sleep(0.05)
        assert len(called_with) == 1
        assert called_with[0] is event

    async def test_trigger_with_lock(self):
        call_order = []

        async def handler(event):
            call_order.append('start')
            await asyncio.sleep(0.02)
            call_order.append('end')

        lst = Listener('test', ContestListRefresh, handler, with_lock=True)
        lst.trigger(ContestListRefresh([1]))
        lst.trigger(ContestListRefresh([2]))
        await asyncio.sleep(0.1)
        # With lock, the second call should start after the first ends
        assert call_order == ['start', 'end', 'start', 'end']

    async def test_exception_swallowed(self):
        async def bad_handler(event):
            raise ValueError('boom')

        lst = Listener('test', ContestListRefresh, bad_handler)
        lst.trigger(ContestListRefresh([1]))
        await asyncio.sleep(0.05)
        # Should not raise — exception is logged and swallowed


# --- EventSystem ---


class TestEventSystem:
    async def test_add_and_dispatch_fires_listener(self):
        es = EventSystem()
        results = []

        async def handler(event):
            results.append(event.contests)

        lst = Listener('test', ContestListRefresh, handler)
        es.add_listener(lst)
        es.dispatch(ContestListRefresh, [1, 2])
        await asyncio.sleep(0.05)
        assert results == [[1, 2]]

    async def test_dispatch_no_listeners(self):
        es = EventSystem()
        # Should not raise
        es.dispatch(ContestListRefresh, [])

    async def test_dispatch_with_kwargs(self):
        es = EventSystem()
        results = []

        async def handler(event):
            results.append((event.contest, event.rating_changes))

        lst = Listener('test', RatingChangesUpdate, handler)
        es.add_listener(lst)
        es.dispatch(RatingChangesUpdate, contest='c1', rating_changes=['r1'])
        await asyncio.sleep(0.05)
        assert results == [('c1', ['r1'])]

    async def test_multiple_listeners(self):
        es = EventSystem()
        results = []

        async def handler1(event):
            results.append('h1')

        async def handler2(event):
            results.append('h2')

        es.add_listener(Listener('a', ContestListRefresh, handler1))
        es.add_listener(Listener('b', ContestListRefresh, handler2))
        es.dispatch(ContestListRefresh, [])
        await asyncio.sleep(0.05)
        assert sorted(results) == ['h1', 'h2']

    async def test_remove_listener(self):
        es = EventSystem()
        results = []

        async def handler(event):
            results.append(1)

        lst = Listener('test', ContestListRefresh, handler)
        es.add_listener(lst)
        es.remove_listener(lst)
        es.dispatch(ContestListRefresh, [])
        await asyncio.sleep(0.05)
        assert results == []

    def test_remove_unregistered_raises(self):
        es = EventSystem()

        async def handler(event):
            pass

        lst = Listener('test', ContestListRefresh, handler)
        with pytest.raises(ListenerNotRegistered):
            es.remove_listener(lst)

    async def test_wait_for_returns_event(self):
        es = EventSystem()

        async def dispatch_later():
            await asyncio.sleep(0.02)
            es.dispatch(ContestListRefresh, [42])

        asyncio.create_task(dispatch_later())
        event = await es.wait_for(ContestListRefresh, timeout=1.0)
        assert event.contests == [42]

    async def test_wait_for_timeout(self):
        es = EventSystem()
        with pytest.raises(asyncio.TimeoutError):
            await es.wait_for(ContestListRefresh, timeout=0.01)


# --- ListenerSpec ---


class TestListenerSpec:
    def test_descriptor_returns_self_from_class(self):
        async def handler(self, event):
            pass

        spec = ListenerSpec('test', ContestListRefresh, handler)

        class MyClass:
            my_listener = spec

        assert MyClass.my_listener is spec

    def test_creates_listener_from_instance(self):
        async def handler(self, event):
            pass

        spec = ListenerSpec('test', ContestListRefresh, handler)

        class MyClass:
            my_listener = spec

        obj = MyClass()
        result = obj.my_listener
        assert isinstance(result, Listener)
        assert result.name == 'test'
        assert result.event_cls is ContestListRefresh

    def test_caches_per_instance(self):
        async def handler(self, event):
            pass

        spec = ListenerSpec('test', ContestListRefresh, handler)

        class MyClass:
            my_listener = spec

        obj = MyClass()
        assert obj.my_listener is obj.my_listener

    def test_different_instances_get_different_listeners(self):
        async def handler(self, event):
            pass

        spec = ListenerSpec('test', ContestListRefresh, handler)

        class MyClass:
            my_listener = spec

        a = MyClass()
        b = MyClass()
        assert a.my_listener is not b.my_listener


# --- Decorators ---


class TestDecorators:
    def test_listener_creates_listener(self):
        @listener(name='test', event_cls=ContestListRefresh)
        async def handler(event):
            pass

        assert isinstance(handler, Listener)
        assert handler.name == 'test'
        assert handler.event_cls is ContestListRefresh

    def test_listener_spec_creates_listener_spec(self):
        @listener_spec(name='test', event_cls=ContestListRefresh)
        async def handler(self, event):
            pass

        assert isinstance(handler, ListenerSpec)
        assert handler.name == 'test'
        assert handler.event_cls is ContestListRefresh

    def test_listener_with_lock(self):
        @listener(name='test', event_cls=ContestListRefresh, with_lock=True)
        async def handler(event):
            pass

        assert handler.lock is not None

    def test_listener_without_lock(self):
        @listener(name='test', event_cls=ContestListRefresh, with_lock=False)
        async def handler(event):
            pass

        assert handler.lock is None
