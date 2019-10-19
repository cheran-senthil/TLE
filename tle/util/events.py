import asyncio


class Event:
    """Base class for events."""
    pass


class ContestListRefresh(Event):
    def __init__(self, contests):
        self.contests = contests


class EventSystem:
    """Rudimentary event system."""

    def __init__(self):
        self.futures_by_event = {}

    async def wait_for(self, event_cls, *, timeout=None):
        future = asyncio.get_running_loop().create_future()
        futures = self.futures_by_event.setdefault(event_cls, [])
        futures.append(future)
        return await asyncio.wait_for(future, timeout)

    def dispatch(self, event_cls, *args, **kwargs):
        event = event_cls(*args, **kwargs)
        futures = self.futures_by_event.pop(event_cls, [])
        for future in futures:
            if not future.done():
                future.set_result(event)
