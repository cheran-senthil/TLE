import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from tle.util import codeforces_api as cf, tasks

if TYPE_CHECKING:
    from tle.util.cache.cache_system import CacheSystem


class ProblemCache:
    _RELOAD_INTERVAL = 6 * 60 * 60

    def __init__(self, cache_master: 'CacheSystem') -> None:
        self.cache_master = cache_master

        self.problems: list[cf.Problem] = []
        self.problem_by_name: dict[str, cf.Problem] = {}
        self.problems_last_cache: float = 0

        self.reload_lock = asyncio.Lock()
        self.reload_exception: Exception | None = None

        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self) -> None:
        await self._try_disk()
        assert isinstance(self._update_task, tasks.Task)
        self._update_task.start()

    async def reload_now(self) -> None:
        """Force a reload. If currently reloading it will wait until done."""
        reloading = self.reload_lock.locked()
        if reloading:
            async with self.reload_lock:
                pass
        else:
            assert isinstance(self._update_task, tasks.Task)
            await self._update_task.manual_trigger()

        if self.reload_exception:
            raise self.reload_exception

    async def _try_disk(self) -> None:
        async with self.reload_lock:
            problems = await self.cache_master.conn.fetch_problems()
            if not problems:
                self.logger.info('Problem cache on disk is empty.')
                return
            self.problems = problems
            self.problem_by_name = {problem.name: problem for problem in problems}
            self.logger.info(f'{len(self.problems)} problems fetched from disk')

    @tasks.task_spec(
        name='ProblemCacheUpdate', waiter=tasks.Waiter.fixed_delay(_RELOAD_INTERVAL)
    )
    async def _update_task(self, _: Any) -> None:
        async with self.reload_lock:
            await self._reload_problems()
        self.reload_exception = None

    @_update_task.exception_handler()
    async def _update_task_exception_handler(self, ex: Exception) -> None:
        self.reload_exception = ex

    async def _reload_problems(self) -> None:
        problems, _ = await cf.problemset.problems()
        await self._update(problems)

    async def _update(self, problems: list[cf.Problem]) -> None:
        self.logger.info(f'{len(problems)} problems fetched from API')
        contest_map: dict[int | None, Any] = {
            problem.contestId: self.cache_master.contest_cache.contest_by_id.get(
                problem.contestId  # type: ignore[arg-type]
            )
            for problem in problems
        }

        def keep(problem: cf.Problem) -> bool:
            return bool(contest_map[problem.contestId]) and problem.has_metadata()

        filtered_problems = list(filter(keep, problems))
        problem_by_name = {problem.name: problem for problem in filtered_problems}
        self.logger.info(f'Keeping {len(problem_by_name)} problems')

        self.problems = list(problem_by_name.values())
        self.problem_by_name = problem_by_name
        self.problems_last_cache = time.time()

        rc = await self.cache_master.conn.cache_problems(self.problems)
        self.logger.info(f'{rc} problems stored in database')
