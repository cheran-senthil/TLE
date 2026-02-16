import logging
import time
from typing import TYPE_CHECKING, Any

from tle.util import (
    codeforces_api as cf,
    codeforces_common as cf_common,
    events,
    paginator,
    tasks,
)
from tle.util.cache._common import _CONTESTS_PER_BATCH_IN_CACHE_UPDATES, _is_blacklisted

if TYPE_CHECKING:
    from tle.util.cache.cache_system import CacheSystem


class RatingChangesCache:
    _RATED_DELAY = 36 * 60 * 60
    _RELOAD_DELAY = 10 * 60

    def __init__(self, cache_master: 'CacheSystem') -> None:
        self.cache_master = cache_master
        self.monitored_contests: list[cf.Contest] = []
        self.handle_rating_cache: dict[str, int] = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self) -> None:
        await self._refresh_handle_cache()
        if not self.handle_rating_cache:
            self.logger.warning(
                'Rating changes cache on disk is empty.'
                ' This must be populated manually before use.'
            )
        assert isinstance(self._update_task, tasks.Task)
        self._update_task.start()

    async def fetch_contest(self, contest_id: int) -> int:
        """Fetch rating changes for a specific contest.

        Intended for manual trigger.
        """
        contest = self.cache_master.contest_cache.contest_by_id[contest_id]
        changes = await self._fetch([contest])
        await self.cache_master.conn.clear_rating_changes(contest_id=contest_id)
        await self._save_changes(changes)
        return len(changes)

    async def fetch_all_contests(self) -> int:
        """Fetch rating changes for all contests.

        Intended for manual trigger.
        """
        await self.cache_master.conn.clear_rating_changes()
        return await self.fetch_missing_contests()

    async def fetch_missing_contests(self) -> int:
        """Fetch rating changes for contests which are not saved in database.

        Intended for manual trigger.
        """
        contests = self.cache_master.contest_cache.contests_by_phase['FINISHED']
        contests = [
            contest
            for contest in contests
            if not await self.has_rating_changes_saved(contest.id)
        ]
        total_changes = 0
        for contests_chunk in paginator.chunkify(
            contests, _CONTESTS_PER_BATCH_IN_CACHE_UPDATES
        ):
            contests_chunk = await self._fetch(list(contests_chunk))
            await self._save_changes(contests_chunk)
            total_changes += len(contests_chunk)
        return total_changes

    async def is_newly_finished_without_rating_changes(
        self, contest: cf.Contest
    ) -> bool:
        now = time.time()
        return (
            contest.phase == 'FINISHED'
            and contest.end_time is not None
            and now - contest.end_time < self._RATED_DELAY
            and not await self.has_rating_changes_saved(contest.id)
        )

    @tasks.task_spec(
        name='RatingChangesCacheUpdate',
        waiter=tasks.Waiter.for_event(events.ContestListRefresh),
    )
    async def _update_task(self, _: Any) -> None:
        to_monitor = [
            contest
            for contest in self.cache_master.contest_cache.contests_by_phase['FINISHED']
            if await self.is_newly_finished_without_rating_changes(contest)
            and not _is_blacklisted(contest)
        ]

        cur_ids = {contest.id for contest in self.monitored_contests}
        new_ids = {contest.id for contest in to_monitor}
        if new_ids != cur_ids:
            assert isinstance(self._monitor_task, tasks.Task)
            await self._monitor_task.stop()
            if to_monitor:
                self.monitored_contests = to_monitor
                self._monitor_task.start()
            else:
                self.monitored_contests = []

    @tasks.task_spec(
        name='RatingChangesCacheUpdate.MonitorNewlyFinishedContests',
        waiter=tasks.Waiter.fixed_delay(_RELOAD_DELAY),
    )
    async def _monitor_task(self, _: Any) -> None:
        self.monitored_contests = [
            contest
            for contest in self.monitored_contests
            if await self.is_newly_finished_without_rating_changes(contest)
            and not _is_blacklisted(contest)
        ]

        if not self.monitored_contests:
            self.logger.info(
                'Rated changes fetched for contests that were being monitored.'
            )
            assert isinstance(self._monitor_task, tasks.Task)
            await self._monitor_task.stop()
            return

        contest_changes_pairs = await self._fetch(self.monitored_contests)
        contest_changes_pairs.sort(key=lambda pair: pair[1][0].ratingUpdateTimeSeconds)
        await self._save_changes(contest_changes_pairs)
        for contest, changes in contest_changes_pairs:
            cf_common.event_sys.dispatch(
                events.RatingChangesUpdate, contest=contest, rating_changes=changes
            )

    async def _fetch(
        self, contests: list[cf.Contest]
    ) -> list[tuple[cf.Contest, list[cf.RatingChange]]]:
        all_changes = []
        for contest in contests:
            try:
                changes = await cf.contest.ratingChanges(contest_id=contest.id)
                self.logger.info(
                    f'{len(changes)} rating changes fetched for contest {contest.id}'
                )
                if changes:
                    all_changes.append((contest, changes))
            except cf.CodeforcesApiError as er:
                self.logger.warning(
                    f'Fetch rating changes failed for contest {contest.id},'
                    f' ignoring. {er!r}'
                )
                pass
        return all_changes

    async def _save_changes(
        self, contest_changes_pairs: list[tuple[cf.Contest, list[cf.RatingChange]]]
    ) -> None:
        flattened = [
            change for _, changes in contest_changes_pairs for change in changes
        ]
        if not flattened:
            return
        rc = await self.cache_master.conn.save_rating_changes(flattened)
        self.logger.info(f'Saved {rc} changes to database.')
        await self._refresh_handle_cache()

    async def _refresh_handle_cache(self) -> None:
        self.handle_rating_cache = (
            await self.cache_master.conn.get_latest_rating_by_handle()
        )
        self.logger.info(f'Ratings for {len(self.handle_rating_cache)} handles cached')

    async def get_users_with_more_than_n_contests(
        self, time_cutoff: int, n: int
    ) -> list[str]:
        return await self.cache_master.conn.get_users_with_more_than_n_contests(
            time_cutoff, n
        )

    async def get_rating_changes_for_contest(
        self, contest_id: int
    ) -> list[cf.RatingChange]:
        return await self.cache_master.conn.get_rating_changes_for_contest(contest_id)

    async def has_rating_changes_saved(self, contest_id: int) -> bool:
        return await self.cache_master.conn.has_rating_changes_saved(contest_id)

    async def get_rating_changes_for_handle(self, handle: str) -> list[cf.RatingChange]:
        return await self.cache_master.conn.get_rating_changes_for_handle(handle)

    def get_current_rating(
        self, handle: str, default_if_absent: bool = False
    ) -> int | None:
        return self.handle_rating_cache.get(
            handle, cf.DEFAULT_RATING if default_if_absent else None
        )

    def get_all_ratings(self) -> list[int]:
        return list(self.handle_rating_cache.values())
