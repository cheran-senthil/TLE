from contextlib import contextmanager
from functools import lru_cache

import logging
import json
import time

from tle.util import codeforces_api as cf
from tle.util import handle_conn

logger = logging.getLogger(__name__)


@contextmanager
def suppress(*exceptions):
    assert all(issubclass(ex, BaseException) for ex in exceptions)
    try:
        yield
    except exceptions as ex:
        logger.info(f'Ignoring exception {ex!r}')


class CacheSystem:
    # """
    #     Explanation: a pair of 'problems' returned from cf api may
    #     be the same (div 1 vs div 2). we pick one of them and call
    #     it 'base_problem' which will be used below:
    # """
    """
        ^ for now, we won't pick problems with the same name the user has solved
        there isn't a good way to do this with the current API
    """

    def __init__(self, conn=None):
        self.conn = conn
        self.contest_dict = None    # id => Contest
        self.contest_last_cache = None
        self.problems_last_cache = None
        self.problem_dict = None    # name => problem
        self.problem_start = None   # id => start_time
        # self.problems = None
        # self.base_problems = None
        # this dict looks up a problem identifier and returns that of the base problem
        # self.problem_to_base = None
        self.logger = logging.getLogger(self.__class__.__name__)

    async def get_contests(self, duration: int):
        """Return contests (dict) fetched within last `duration` seconds if available, else fetch now and return."""
        now = time.time()
        if self.contest_last_cache is None or self.contest_dict is None or now - self.contest_last_cache > duration:
            await self.cache_contests()
        return self.contest_dict

    async def get_problems(self, duration: int):
        """Return problems (dict) fetched within last `duration` seconds or refetch"""
        now = time.time()
        if self.problems_last_cache is None or self.problem_dict is None or now - self.problems_last_cache > duration:
            await self.cache_problems()
        return self.problem_dict

    async def force_update(self):
        # cache_problems will now always call cache_contests because we need the contest information
        # as recent as problem information in order to match contestId
        await self.cache_problems()

    def try_disk(self):
        with suppress(handle_conn.DatabaseDisabledError):
            contests = self.conn.fetch_contests()
            problem_res = self.conn.fetch_problems()
            if not contests or not problem_res:
                # Could not load from disk
                return
            self.contest_dict = {c.id: c for c in contests}
            self.problem_dict = {
                problem.name: problem
                for problem, start_time in problem_res
            }
            self.problem_start = {
                problem.contest_identifier: start_time
                for problem, start_time in problem_res
            }

    async def cache_contests(self):
        try:
            contests = await cf.contest.list()
        except cf.CodeforcesApiError as e:
            self.logger.warning(f'Error caching contests, {e}')
            return
        self.contest_dict = {
            c.id : c
            for c in contests
        }
        self.contest_last_cache = time.time()
        self.logger.info(f'{len(self.contest_dict)} contests cached')
        with suppress(handle_conn.DatabaseDisabledError):
            rc = self.conn.cache_contests(contests)
            self.logger.info(f'{rc} contests stored in database')

    async def cache_problems(self):
        await self.cache_contests()
        try:
            problems, _ = await cf.problemset.problems()
        except cf.CodeforcesApiError as e:
            self.logger.warning(f'Error caching problems, {e}')
            return
        banned_tags = ['*special']
        self.problem_dict = {
            prob.name : prob    # this will discard some valid problems
            for prob in problems
            if prob.has_metadata() and not prob.tag_matches(banned_tags)
        }
        self.problem_start = {
            prob.contest_identifier : self.contest_dict[prob.contestId].startTimeSeconds
            for prob in self.problem_dict.values()
        }
        self.problems_last_cache = time.time()
        self.logger.info(f'{len(self.problem_dict)} problems cached')
        with suppress(handle_conn.DatabaseDisabledError):
            rc = self.conn.cache_problems([
                (
                    prob.name, prob.contestId, prob.index,
                    self.contest_dict[prob.contestId].startTimeSeconds,
                    prob.rating, prob.type, json.dumps(prob.tags)
                )
                for prob in self.problem_dict.values()
            ])
            self.logger.info(f'{rc} problems stored in database')

    # this handle all the (rating, solved) pair and caching
    async def get_rating_solved(self, handle: str, time_out: int):
        cached = self._user_rating_solved(handle)
        stamp, rating, solved = cached
        with suppress(handle_conn.DatabaseDisabledError):
            if stamp is None:
                # Try from disk first
                stamp, rating, solved = await self._retrieve_rating_solved(handle)
        if stamp is None or time.time() - stamp > time_out: # fetch from cf
            stamp, trating, tsolved = await self._fetch_rating_solved(handle)
            if trating is not None: rating = trating
            if tsolved is not None: solved = tsolved
            cached[:] = stamp, rating, solved
        return rating, solved

    @lru_cache(maxsize=15)
    def _user_rating_solved(self, handle: str):
        # this works. it will actually return a reference
        # the cache is for repeated requests and maxsize limits RAM usage
        return [None, None, None]

    async def _fetch_rating_solved(self, handle: str): # fetch from cf api
        try:
            info = await cf.user.info(handles=[handle])
            subs = await cf.user.status(handle=handle)
            info = info[0]
            solved = [sub.problem for sub in subs if sub.verdict == 'OK']
            solved = { prob.name for prob in solved if prob.has_metadata() }
            stamp = time.time()
            self.conn.cache_cfuser_full(info + (json.dumps(list(solved)), stamp))
            return stamp, info.rating, solved
        except cf.CodeforcesApiError as e:
            self.logger.error(e)
        return [None, None, None]

    async def _retrieve_rating_solved(self, handle: str): # retrieve from disk
        res = self.conn.fetch_rating_solved(handle)
        if res and all(r is not None for r in res):
            return res[0], res[1], set(json.loads(res[2]))
        return [None, None, None]
