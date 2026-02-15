import asyncio
import logging
import time
from collections import defaultdict

from tle.util import codeforces_api as cf, codeforces_common as cf_common, tasks
from tle.util.cache._common import CacheError
from tle.util.cache.contest import ContestNotFound


class ProblemsetCacheError(CacheError):
    pass


class ProblemsetNotCached(ProblemsetCacheError):
    def __init__(self, contest_id):
        super().__init__(f'Problemset for contest with id {contest_id} not cached.')


class ProblemsetCache:
    _MONITOR_PERIOD_SINCE_CONTEST_END = 14 * 24 * 60 * 60
    _RELOAD_DELAY = 60 * 60

    def __init__(self, cache_master):
        self.problems = []
        self.problem_to_contests = defaultdict(list)
        self.cache_master = cache_master
        self.update_lock = asyncio.Lock()
        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        if await self.cache_master.conn.problemset_empty():
            self.logger.warning(
                'Problemset cache on disk is empty.'
                ' This must be populated manually before use.'
            )
        self._update_task.start()

    async def update_for_contest(self, contest_id):
        """Update problemset for a particular contest. Intended for manual trigger."""
        async with self.update_lock:
            contest = self.cache_master.contest_cache.get_contest(contest_id)
            problemset, _ = await self._fetch_problemsets([contest], force_fetch=True)
            await self.cache_master.conn.clear_problemset(contest_id)
            await self._save_problems(problemset)
            return len(problemset)

    async def update_for_all(self):
        """Update problemsets for all finished contests. Intended for manual trigger."""
        async with self.update_lock:
            contests = self.cache_master.contest_cache.contests_by_phase['FINISHED']
            problemsets, _ = await self._fetch_problemsets(contests, force_fetch=True)
            await self.cache_master.conn.clear_problemset()
            await self._save_problems(problemsets)
            return len(problemsets)

    @tasks.task_spec(
        name='ProblemsetCacheUpdate', waiter=tasks.Waiter.fixed_delay(_RELOAD_DELAY)
    )
    async def _update_task(self, _):
        async with self.update_lock:
            contests = self.cache_master.contest_cache.contests_by_phase['FINISHED']
            new_problems, updated_problems = await self._fetch_problemsets(contests)
            await self._save_problems(new_problems + updated_problems)
            await self._update_from_disk()
            self.logger.info(
                f'{len(new_problems)} new problems saved and'
                f' {len(updated_problems)} saved problems updated.'
            )

    async def _fetch_problemsets(self, contests, *, force_fetch=False):
        new_contest_ids = []
        contests_to_refetch = []
        if force_fetch:
            new_contest_ids = [contest.id for contest in contests]
        else:
            now = time.time()
            for contest in contests:
                if now > contest.end_time + self._MONITOR_PERIOD_SINCE_CONTEST_END:
                    continue
                problemset = await self.cache_master.conn.fetch_problemset(contest.id)
                if not problemset:
                    new_contest_ids.append(contest.id)
                    continue
                rated_problem_idx = {
                    prob.index for prob in problemset if prob.rating is not None
                }
                if len(rated_problem_idx) < len(problemset):
                    contests_to_refetch.append((contest.id, rated_problem_idx))

        new_problems, updated_problems = [], []
        for contest_id in new_contest_ids:
            new_problems += await self._fetch_for_contest(contest_id)
        for contest_id, rated_problem_idx in contests_to_refetch:
            updated_problems += [
                prob
                for prob in await self._fetch_for_contest(contest_id)
                if prob.rating is not None and prob.index not in rated_problem_idx
            ]

        return new_problems, updated_problems

    async def _fetch_for_contest(self, contest_id):
        try:
            _, problemset, _ = await cf.contest.standings(
                contest_id=contest_id, from_=1, count=1
            )
        except cf.CodeforcesApiError as er:
            self.logger.warning(
                f'Problemset fetch failed for contest {contest_id}. {er!r}'
            )
            problemset = []
        return problemset

    async def _save_problems(self, problems):
        rc = await self.cache_master.conn.cache_problemset(problems)
        self.logger.info(f'Saved {rc} problems to database.')

    async def get_problemset(self, contest_id):
        problemset = await self.cache_master.conn.fetch_problemset(contest_id)
        if not problemset:
            raise ProblemsetNotCached(contest_id)
        return problemset

    async def _update_from_disk(self):
        self.problems = await self.cache_master.conn.fetch_problems2()
        self.problem_to_contests = defaultdict(list)
        for problem in self.problems:
            try:
                contest = cf_common.cf_cache.contest_cache.get_contest(
                    problem.contestId
                )
                problem_id = (problem.name, contest.startTimeSeconds)
                self.problem_to_contests[problem_id].append(contest.id)
            except ContestNotFound:
                pass
