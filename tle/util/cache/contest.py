import asyncio
import logging
import time

from tle.util import codeforces_api as cf, codeforces_common as cf_common, events, tasks
from tle.util.cache._common import CacheError


class ContestCacheError(CacheError):
    pass


class ContestNotFound(ContestCacheError):
    def __init__(self, contest_id):
        super().__init__(f'Contest with id `{contest_id}` not found')
        self.contest_id = contest_id


class ContestCache:
    _NORMAL_CONTEST_RELOAD_DELAY = 30 * 60
    _EXCEPTION_CONTEST_RELOAD_DELAY = 5 * 60
    _ACTIVE_CONTEST_RELOAD_DELAY = 5 * 60
    _ACTIVATE_BEFORE = 20 * 60

    _RUNNING_PHASES = ('CODING', 'PENDING_SYSTEM_TEST', 'SYSTEM_TEST')

    def __init__(self, cache_master):
        self.cache_master = cache_master

        self.contests = []
        self.contest_by_id = {}
        self.contests_by_phase = {phase: [] for phase in cf.Contest.PHASES}
        self.contests_by_phase['_RUNNING'] = []
        self.contests_last_cache = 0

        self.reload_lock = asyncio.Lock()
        self.reload_exception = None
        self.next_delay = None

        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        await self._try_disk()
        self._update_task.start()

    async def reload_now(self):
        """Force a reload. If currently reloading it will wait until done."""
        reloading = self.reload_lock.locked()
        if reloading:
            async with self.reload_lock:
                pass
        else:
            await self._update_task.manual_trigger()

        if self.reload_exception:
            raise self.reload_exception

    def get_contest(self, contest_id):
        try:
            return self.contest_by_id[contest_id]
        except KeyError:
            raise ContestNotFound(contest_id)

    async def get_problemset(self, contest_id):
        return await self.cache_master.conn.get_problemset_from_contest(contest_id)

    def get_contests_in_phase(self, phase):
        return self.contests_by_phase[phase]

    async def _try_disk(self):
        async with self.reload_lock:
            contests = await self.cache_master.conn.fetch_contests()
            if not contests:
                self.logger.info('Contest cache on disk is empty.')
                return
            await self._update(contests, from_api=False)

    @tasks.task_spec(name='ContestCacheUpdate')
    async def _update_task(self, _):
        async with self.reload_lock:
            self.next_delay = await self._reload_contests()
        self.reload_exception = None

    @_update_task.waiter()
    async def _update_task_waiter(self):
        await asyncio.sleep(self.next_delay)

    @_update_task.exception_handler()
    async def _update_task_exception_handler(self, ex):
        self.reload_exception = ex
        self.next_delay = self._EXCEPTION_CONTEST_RELOAD_DELAY

    async def _reload_contests(self):
        contests = await cf.contest.to_list()
        delay = await self._update(contests)
        return delay

    async def _update(self, contests, from_api=True):
        self.logger.info(
            f'{len(contests)} contests fetched from {"API" if from_api else "disk"}'
        )
        contests.sort(key=lambda contest: (contest.startTimeSeconds, contest.id))

        if from_api:
            rc = await self.cache_master.conn.cache_contests(contests)
            self.logger.info(f'{rc} contests stored in database')

        contests_by_phase = {phase: [] for phase in cf.Contest.PHASES}
        contests_by_phase['_RUNNING'] = []
        contest_by_id = {}
        for contest in contests:
            contests_by_phase[contest.phase].append(contest)
            contest_by_id[contest.id] = contest
            if contest.phase in self._RUNNING_PHASES:
                contests_by_phase['_RUNNING'].append(contest)

        now = time.time()
        delay = self._NORMAL_CONTEST_RELOAD_DELAY

        for contest in contests_by_phase['BEFORE']:
            at = contest.startTimeSeconds - self._ACTIVATE_BEFORE
            if at > now:
                delay = min(delay, at - now)
            else:
                delay = min(
                    contest.startTimeSeconds - now, self._ACTIVE_CONTEST_RELOAD_DELAY
                )

        if contests_by_phase['_RUNNING']:
            delay = min(delay, self._ACTIVE_CONTEST_RELOAD_DELAY)

        self.contests = contests
        self.contests_by_phase = contests_by_phase
        self.contest_by_id = contest_by_id
        self.contests_last_cache = time.time()

        cf_common.event_sys.dispatch(events.ContestListRefresh, self.contests.copy())

        return delay
