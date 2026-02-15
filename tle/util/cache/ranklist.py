import logging
import time

from tle.util import codeforces_api as cf, codeforces_common as cf_common, events, tasks
from tle.util.cache._common import CacheError, _is_blacklisted, getUsersEffectiveRating
from tle.util.ranklist import Ranklist


class RanklistCacheError(CacheError):
    pass


class RanklistNotMonitored(RanklistCacheError):
    def __init__(self, contest):
        super().__init__(f'The ranklist for `{contest.name}` is not being monitored')
        self.contest = contest


class RanklistCache:
    _RELOAD_DELAY = 2 * 60

    def __init__(self, cache_master):
        self.cache_master = cache_master
        self.monitored_contests = []
        self.ranklist_by_contest = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        self._update_task.start()

    def get_ranklist(self, contest, show_official):
        if show_official or contest.id not in self.ranklist_by_contest:
            raise RanklistNotMonitored(contest)
        return self.ranklist_by_contest[contest.id]

    @tasks.task_spec(
        name='RanklistCacheUpdate',
        waiter=tasks.Waiter.for_event(events.ContestListRefresh),
    )
    async def _update_task(self, _):
        contests_by_phase = self.cache_master.contest_cache.contests_by_phase
        running_contests = contests_by_phase['_RUNNING']

        rating_cache = self.cache_master.rating_changes_cache
        finished_contests = [
            contest
            for contest in contests_by_phase['FINISHED']
            if not _is_blacklisted(contest)
            and await rating_cache.is_newly_finished_without_rating_changes(contest)
        ]

        to_monitor = running_contests + finished_contests
        cur_ids = {contest.id for contest in self.monitored_contests}
        new_ids = {contest.id for contest in to_monitor}
        if new_ids != cur_ids:
            await self._monitor_task.stop()
            if to_monitor:
                self.monitored_contests = to_monitor
                self._monitor_task.start()
            else:
                self.ranklist_by_contest = {}

    @tasks.task_spec(
        name='RanklistCacheUpdate.MonitorActiveContests',
        waiter=tasks.Waiter.fixed_delay(_RELOAD_DELAY),
    )
    async def _monitor_task(self, _):
        cache = self.cache_master.rating_changes_cache
        self.monitored_contests = [
            contest
            for contest in self.monitored_contests
            if not _is_blacklisted(contest)
            and (
                contest.phase != 'FINISHED'
                or await cache.is_newly_finished_without_rating_changes(contest)
            )
        ]

        if not self.monitored_contests:
            self.ranklist_by_contest = {}
            self.logger.info('No more active contests for which to monitor ranklists.')
            await self._monitor_task.stop()
            return

        ranklist_by_contest = await self._fetch(self.monitored_contests)
        for contest_id, ranklist in ranklist_by_contest.items():
            self.ranklist_by_contest[contest_id] = ranklist

    @staticmethod
    async def _get_contest_details(contest_id, show_unofficial):
        contest, problems, standings = await cf.contest.standings(
            contest_id=contest_id, show_unofficial=show_unofficial
        )

        standings = [
            row
            for row in standings
            if row.party.participantType
            in ('CONTESTANT', 'OUT_OF_COMPETITION', 'VIRTUAL')
        ]

        return contest, problems, standings

    async def _get_ranklist_with_fetched_changes(self, contest_id, show_unofficial):
        contest, problems, standings = await self._get_contest_details(
            contest_id, show_unofficial
        )
        now = time.time()

        is_rated = False
        try:
            changes = await cf.contest.ratingChanges(contest_id=contest_id)
            is_rated = len(changes) > 0
        except cf.RatingChangesUnavailableError:
            pass

        ranklist = None
        if is_rated:
            ranklist = Ranklist(contest, problems, standings, now, is_rated=is_rated)
            delta_by_handle = {
                change.handle: change.newRating - change.oldRating for change in changes
            }
            ranklist.set_deltas(delta_by_handle)

        return ranklist

    async def _get_ranklist_with_predicted_changes(self, contest_id, show_unofficial):
        contest, problems, standings = await self._get_contest_details(
            contest_id, show_unofficial
        )
        now = time.time()

        standings_official = None
        if not show_unofficial:
            standings_official = standings
        else:
            _, _, standings_official = await cf.contest.standings(contest_id=contest_id)

        has_teams = any(row.party.teamId is not None for row in standings_official)
        if cf_common.is_nonstandard_contest(contest) or has_teams:
            ranklist = Ranklist(contest, problems, standings, now, is_rated=False)
        else:
            current_rating = await getUsersEffectiveRating(activeOnly=False)
            current_rating = {
                row.party.members[0].handle: current_rating.get(
                    row.party.members[0].handle, 1500
                )
                for row in standings_official
            }
            if 'Educational' in contest.name:
                current_rating = {
                    handle: rating
                    for handle, rating in current_rating.items()
                    if rating < 2100
                }
            ranklist = Ranklist(contest, problems, standings, now, is_rated=True)
            ranklist.predict(current_rating)
        return ranklist

    async def generate_ranklist(
        self,
        contest_id,
        *,
        fetch_changes=False,
        predict_changes=False,
        show_unofficial=True,
    ):
        assert fetch_changes ^ predict_changes

        ranklist = None
        if fetch_changes:
            ranklist = await self._get_ranklist_with_fetched_changes(
                contest_id, show_unofficial
            )
        if ranklist is None:
            ranklist = await self._get_ranklist_with_predicted_changes(
                contest_id, show_unofficial
            )

        if not show_unofficial and 'Educational' in ranklist.contest.name:
            ranklist.remove_unofficial_contestants()

        return ranklist

    async def generate_vc_ranklist(self, contest_id, handle_to_member_id):
        handles = list(handle_to_member_id.keys())
        contest, problems, standings = await cf.contest.standings(
            contest_id=contest_id, show_unofficial=True
        )
        standings = [
            row
            for row in standings
            if row.party.participantType == 'CONTESTANT'
            or row.party.members[0].handle in handles
        ]
        standings.sort(key=lambda row: row.rank)
        standings = [row._replace(rank=i + 1) for i, row in enumerate(standings)]
        now = time.time()
        rating_changes = await cf.contest.ratingChanges(contest_id=contest_id)
        current_official_rating = {
            rating_change.handle: rating_change.oldRating
            for rating_change in rating_changes
        }

        handles = [
            row.party.members[0].handle
            for row in standings
            if row.party.members[0].handle in handles
            and row.party.participantType == 'VIRTUAL'
        ]
        current_vc_rating = {
            handle: await cf_common.user_db.get_vc_rating(
                handle_to_member_id.get(handle)
            )
            for handle in handles
        }
        ranklist = Ranklist(contest, problems, standings, now, is_rated=True)
        delta_by_handle = {}
        for handle in handles:
            mixed_ratings = current_official_rating.copy()
            mixed_ratings[handle] = current_vc_rating.get(handle)
            ranklist.predict(mixed_ratings)
            delta_by_handle[handle] = ranklist.delta_by_handle.get(handle, 0)

        ranklist.delta_by_handle = delta_by_handle
        return ranklist

    async def _fetch(self, contests):
        ranklist_by_contest = {}
        for contest in contests:
            try:
                ranklist = await self.generate_ranklist(
                    contest.id, predict_changes=True
                )
                ranklist_by_contest[contest.id] = ranklist
                self.logger.info(f'Ranklist fetched for contest {contest.id}')
            except cf.CodeforcesApiError as er:
                self.logger.warning(
                    f'Ranklist fetch failed for contest {contest.id}. {er!r}'
                )

        return ranklist_by_contest
