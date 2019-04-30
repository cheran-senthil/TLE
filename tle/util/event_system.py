import asyncio


class EventSystem:
    """Rudimentary event system."""

    def __init__(self):
        self.futures_by_event = {}

    async def wait_for(self, event_name, *, timeout=None):
        future = asyncio.get_running_loop().create_future()
        futures = self.futures_by_event.setdefault(event_name, [])
        futures.append(future)
        return await asyncio.wait_for(future, timeout)

    def dispatch(self, event_name, result):
        futures = self.futures_by_event.pop(event_name, [])
        for future in futures:
            if not future.cancelled():
                future.set_result(result)
