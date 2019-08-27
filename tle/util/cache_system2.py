import asyncio
import logging
import time
import shelve

from discord.ext import commands

from tle.util import codeforces_common as cf_common
from tle.util import codeforces_api as cf
from tle.util.ranklist import Ranklist

logger = logging.getLogger(__name__)


class CacheError(commands.CommandError):
    pass


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
        self.standings = {}
        self.contests_by_phase = {phase: [] for phase in cf.Contest.PHASES}
        self.contests_by_phase['_RUNNING'] = []
        self.contests_last_cache = 0

        self.reload_lock = asyncio.Lock()
        self.reload_exception = None

        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        await self._try_disk()
        asyncio.create_task(self._contest_updater_task())

    async def reload_now(self):
        """Force a reload. If currently reloading it will wait until done."""
        reloading = self.reload_lock.locked()
        if reloading:
            # Wait until reload complete.
            # To wait until lock is free, await acquire then release immediately.
            async with self.reload_lock:
                pass
        else:
            await self._pre_reload()

        if self.reload_exception:
            raise self.reload_exception

    def get_contest(self, contest_id):
        try:
            return self.contest_by_id[contest_id]
        except KeyError:
            raise ContestNotFound(contest_id)

    def get_standings(self, contest_id):
        return self.cache_master.conn.get_problemset_from_contest(contest_id)

    def get_contests_in_phase(self, phase):
        return self.contests_by_phase[phase]

    async def _try_disk(self):
        async with self.reload_lock:
            contests = self.cache_master.conn.fetch_contests()
            if not contests:
                # Load failed.
                return
            await self._update(contests, from_api=False)

    async def _contest_updater_task(self):
        self.logger.info('Running contest updater task')
        while True:
            delay = await self._pre_reload()
            await asyncio.sleep(delay)

    async def _pre_reload(self):
        try:
            async with self.reload_lock:
                delay = await self._reload_contests()
            self.reload_exception = None
        except Exception as ex:
            self.reload_exception = ex
            self.logger.warning('Exception in contest updater task, ignoring.', exc_info=True)
            delay = self._EXCEPTION_CONTEST_RELOAD_DELAY
        return delay

    async def _reload_contests(self):
        contests = await cf.contest.list()
        delay = await self._update(contests)
        return delay

    async def _update(self, contests, from_api=True):
        self.logger.info(f'{len(contests)} contests fetched from {"API" if from_api else "disk"}')
        contests.sort(key=lambda contest: (contest.startTimeSeconds, contest.id))

        if from_api:
            rc = self.cache_master.conn.cache_contests(contests)
            self.logger.info(f'{rc} contests stored in database')

        contests_by_phase = {phase: [] for phase in cf.Contest.PHASES}
        contests_by_phase['_RUNNING'] = []
        contest_by_id = {}
        standings_updated = [s[0] for s in self.cache_master.conn.check_all_cached_standings()]
        for contest in contests:
            contests_by_phase[contest.phase].append(contest)
            contest_by_id[contest.id] = contest
            if contest.phase in self._RUNNING_PHASES:
                contests_by_phase['_RUNNING'].append(contest)

            if contest.phase == 'FINISHED' and contest.id not in standings_updated:
                try:
                    t = await cf.contest.standings(contest_id=contest.id)
                    rc = self.cache_master.conn.save_standings(t[1])
                except cf.CodeforcesApiError:
                    pass

        now = time.time()
        delay = self._NORMAL_CONTEST_RELOAD_DELAY

        for contest in contests_by_phase['BEFORE']:
            at = contest.startTimeSeconds - self._ACTIVATE_BEFORE
            if at > now:
                # Reload at _ACTIVATE_BEFORE before contest to monitor contest delays.
                delay = min(delay, at - now)
            else:
                # The contest starts in <= _ACTIVATE_BEFORE.
                # Reload at contest start, or after _ACTIVE_CONTEST_RELOAD_DELAY, whichever comes first.
                delay = min(contest.startTimeSeconds - now, self._ACTIVE_CONTEST_RELOAD_DELAY)

        if contests_by_phase['_RUNNING']:
            # If any contest is running, reload at an increased rate to detect FINISHED
            delay = min(delay, self._ACTIVE_CONTEST_RELOAD_DELAY)

        self.contests = contests
        self.contests_by_phase = contests_by_phase
        self.contest_by_id = contest_by_id
        self.contests_last_cache = time.time()

        cf_common.event_sys.dispatch('EVENT_CONTEST_LIST_REFRESH', self.contests.copy())

        return delay


class ProblemCache:
    _RELOAD_INTERVAL = 6 * 60 * 60

    def __init__(self, cache_master):
        self.cache_master = cache_master

        self.problems = []
        self.problem_by_name = {}
        self.problems_last_cache = 0

        self.reload_lock = asyncio.Lock()
        self.reload_exception = None

        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        await self._try_disk()
        asyncio.create_task(self._problem_updater_task())

    async def reload_now(self):
        """Force a reload. If currently reloading it will wait until done."""
        reloading = self.reload_lock.locked()
        if reloading:
            # Wait until reload complete.
            # To wait until lock is free, await acquire then release immediately.
            async with self.reload_lock:
                pass
        else:
            await self._pre_reload()

        if self.reload_exception:
            raise self.reload_exception

    async def _try_disk(self):
        async with self.reload_lock:
            problems = self.cache_master.conn.fetch_problems()
            if not problems:
                # Load failed.
                return
            self.problems = problems
            self.problem_by_name = {problem.name: problem for problem in problems}
            self.logger.info(f'{len(self.problems)} problems fetched from disk')

    async def _problem_updater_task(self):
        self.logger.info('Running problem updater task')
        while True:
            await self._pre_reload()
            await asyncio.sleep(self._RELOAD_INTERVAL)

    async def _pre_reload(self):
        try:
            async with self.reload_lock:
                await self._reload_problems()
            self.reload_exception = None
        except Exception as ex:
            self.reload_exception = ex
            self.logger.warning('Exception in problem updater task, ignoring.', exc_info=True)

    async def _reload_problems(self):
        problems, _ = await cf.problemset.problems()
        await self._update(problems)

    async def _update(self, problems):
        self.logger.info(f'{len(problems)} problems fetched from API')
        banned_tags = ['*special']
        contest_map = {problem.contestId: self.cache_master.contest_cache.contest_by_id.get(problem.contestId)
                       for problem in problems}

        def keep(problem):
            return (contest_map[problem.contestId] and
                    problem.has_metadata() and
                    not problem.tag_matches(banned_tags))

        filtered_problems = list(filter(keep, problems))
        problem_by_name = {
            problem.name: problem  # This will discard some valid problems
            for problem in filtered_problems
        }
        self.logger.info(f'Keeping {len(problem_by_name)} problems')

        self.problems = list(problem_by_name.values())
        self.problem_by_name = problem_by_name
        self.problems_last_cache = time.time()

        rc = self.cache_master.conn.cache_problems(self.problems)
        self.logger.info(f'{rc} problems stored in database')


class RatingChangesCache:
    DEFAULT_RATING = 1500
    _RATED_DELAY = 36 * 60 * 60
    _RELOAD_DELAY = 10 * 60

    def __init__(self, cache_master):
        self.cache_master = cache_master

        self.monitored_contests = []

        self.handle_rating_cache = {}
        self.update_task = None

        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        self._refresh_handle_cache()
        asyncio.create_task(self._rating_changes_updater_task())

    async def fetch_contest(self, contest_id):
        """Fetch rating changes for a particular contest. Intended for manual trigger."""
        contest = self.cache_master.contest_cache.contest_by_id[contest_id]
        changes = await self._fetch([contest])
        self.cache_master.conn.clear_rating_changes(contest_id=contest_id)
        self._save_changes(changes)
        return len(changes)

    async def fetch_all_contests(self):
        """Fetch rating changes for all contests. Intended for manual trigger."""
        contests = self.cache_master.contest_cache.contests_by_phase['FINISHED']
        changes = await self._fetch(contests)
        self.cache_master.conn.clear_rating_changes()
        self._save_changes(changes)
        return len(changes)

    async def fetch_missing_contests(self):
        """Fetch rating changes for contests which are not saved in database. Intended for
        manual trigger."""
        contests = self.cache_master.contest_cache.contests_by_phase['FINISHED']
        contests = [contest for contest in contests if not self.has_rating_changes_saved(contest.id)]
        changes = await self._fetch(contests)
        self._save_changes(changes)
        return len(changes)

    async def _rating_changes_updater_task(self):
        self.logger.info('Running rating changes updater task')
        while True:
            try:
                await cf_common.event_sys.wait_for('EVENT_CONTEST_LIST_REFRESH')
                await self._process_contests()
            except Exception:
                self.logger.warning(f'Exception in rating changes updater task, ignoring.', exc_info=True)

    def is_newly_finished_without_rating_changes(self, contest):
        now = time.time()
        return (contest.phase == 'FINISHED' and
                now - contest.end_time < self._RATED_DELAY and
                not self.has_rating_changes_saved(contest.id))

    async def _process_contests(self):
        # Some notes:
        # A hack phase is tagged as FINISHED with empty list of rating changes. After the hack
        # phase, the phase changes to systest then again FINISHED. Since we cannot differentiate
        # between the two FINISHED phases, we are forced to fetch during both.
        # A contest also has empty list if it is unrated. We assume that is the case if
        # _RATED_DELAY time has passed since the contest end.

        to_monitor = [contest for contest in self.cache_master.contest_cache.contests_by_phase['FINISHED']
                      if self.is_newly_finished_without_rating_changes(contest)]
        cur_ids = {contest.id for contest in self.monitored_contests}
        new_ids = {contest.id for contest in to_monitor}
        if new_ids != cur_ids:
            if self.update_task:
                self.update_task.cancel()
            if to_monitor:
                self.update_task = asyncio.create_task(self._update_task(to_monitor))
            else:
                self.monitored_contests = []

    async def _update_task(self, contests):
        self.monitored_contests = contests
        while True:
            self.monitored_contests = [contest for contest in self.monitored_contests
                                       if self.is_newly_finished_without_rating_changes(contest)]
            if not self.monitored_contests:
                break
            try:
                all_changes = await self._fetch(contests)
            except Exception:
                self.logger.warning(f'Exception in rating change update task 2, ignoring.', exc_info=True)
            else:
                self._save_changes(all_changes)
            await asyncio.sleep(self._RELOAD_DELAY)
        self.monitored_contests = []
        self.logger.info('Rated changes fetched for contests that were being monitored, '
                         'halting update task.')

    async def _fetch(self, contests):
        all_changes = []
        for contest in contests:
            try:
                changes = await cf.contest.ratingChanges(contest_id=contest.id)
                self.logger.info(f'{len(changes)} rating changes fetched for contest {contest.id}')
                all_changes += changes
            except cf.CodeforcesApiError as er:
                self.logger.warning(f'Fetch rating changes failed for contest {contest.id}, ignoring. {er!r}')
                pass
        return all_changes

    def _save_changes(self, changes):
        if not changes:
            return
        rc = self.cache_master.conn.save_rating_changes(changes)
        self.logger.info(f'Saved {rc} changes to database.')
        self._refresh_handle_cache()

    def _refresh_handle_cache(self):
        changes = self.cache_master.conn.get_all_rating_changes()
        handle_rating_cache = {}
        for change in changes:
            delta = change.newRating - change.oldRating
            try:
                handle_rating_cache[change.handle] += delta
            except KeyError:
                handle_rating_cache[change.handle] = self.DEFAULT_RATING + delta
        self.handle_rating_cache = handle_rating_cache
        self.logger.info(f'Ratings for {len(handle_rating_cache)} handles cached')

    def get_users_with_more_than_n_contests(self, time_cutoff, n):
        return self.cache_master.conn.get_users_with_more_than_n_contests(time_cutoff, n)

    def get_rating_changes_for_contest(self, contest_id):
        return self.cache_master.conn.get_rating_changes_for_contest(contest_id)

    def has_rating_changes_saved(self, contest_id):
        return self.cache_master.conn.has_rating_changes_saved(contest_id)

    def get_rating_changes_for_handle(self, handle):
        return self.cache_master.conn.get_rating_changes_for_handle(handle)

    def get_current_rating(self, handle):
        return self.handle_rating_cache.get(handle)

    def get_current_rating_or_default(self, handle):
        return self.handle_rating_cache.get(handle, self.DEFAULT_RATING)

    def get_all_ratings(self):
        return list(self.handle_rating_cache.values())


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

        self.ranklist_by_contest = {}
        self.update_task = None

        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        asyncio.create_task(self._ranklist_updater_task())

    def get_ranklist(self, contest):
        try:
            return self.ranklist_by_contest[contest.id]
        except KeyError:
            raise RanklistNotMonitored(contest)

    async def _ranklist_updater_task(self):
        self.logger.info('Running ranklist updater task')
        while True:
            try:
                await cf_common.event_sys.wait_for('EVENT_CONTEST_LIST_REFRESH')
                await self._process_contests()
            except Exception:
                self.logger.warning('Exception in ranklist updater task, ignoring.', exc_info=True)

    async def _process_contests(self):
        contests_by_phase = self.cache_master.contest_cache.contests_by_phase
        running_contests = contests_by_phase['_RUNNING']
        check = self.cache_master.rating_changes_cache.is_newly_finished_without_rating_changes
        to_monitor = running_contests + list(filter(check, contests_by_phase['FINISHED']))
        new_ids = {contest.id for contest in to_monitor}
        if new_ids != self.ranklist_by_contest.keys():
            if self.update_task:
                self.update_task.cancel()
            if to_monitor:
                self.update_task = asyncio.create_task(self._update_task(to_monitor))
            else:
                self.ranklist_by_contest = {}

    async def _update_task(self, contests):
        check = self.cache_master.rating_changes_cache.is_newly_finished_without_rating_changes
        while True:
            contests = [contest for contest in contests
                        if contest.phase != 'FINISHED' or check(contest)]
            if not contests:
                break
            try:
                ranklist_by_contest = await self._fetch(contests)
            except Exception:
                self.logger.warning(f'Exception in ranklist update task 2, ignoring.', exc_info=True)
            else:
                for contest in contests:
                    # Keep previous ranklist (if exists) in case fetch failed
                    if contest.id in self.ranklist_by_contest and contest.id not in ranklist_by_contest:
                        ranklist_by_contest[contest.id] = self.ranklist_by_contest[contest.id]
                self.ranklist_by_contest = ranklist_by_contest
            await asyncio.sleep(self._RELOAD_DELAY)
        self.ranklist_by_contest = {}
        self.logger.info('Halting ranklist monitor task')

    async def generate_ranklist(self, contest_id, *, fetch_changes=False, predict_changes=False):
        assert fetch_changes ^ predict_changes

        contest, problems, standings = await cf.contest.standings(contest_id=contest_id,
                                                                  show_unofficial=True)
        now = time.time()

        # Exclude PRACTICE and MANAGER
        standings = [row for row in standings
                     if row.party.participantType in ('CONTESTANT', 'OUT_OF_COMPETITION', 'VIRTUAL')]

        if fetch_changes:
            # Fetch final rating changes from CF.
            # For older contests.
            is_rated = False
            try:
                changes = await cf.contest.ratingChanges(contest_id=contest_id)
                # For contests intended to be rated but declared unrated, an empty list is returned.
                is_rated = len(changes) > 0
            except cf.RatingChangesUnavailableError:
                pass
            ranklist = Ranklist(contest, problems, standings, now, is_rated=is_rated)
            if is_rated:
                delta_by_handle = {change.handle: change.newRating - change.oldRating
                                   for change in changes}
                ranklist.set_deltas(delta_by_handle)
        elif predict_changes:
            # Rating changes have not been applied yet, predict rating changes.
            # For running/recent contests.
            _, _, standings_official = await cf.contest.standings(contest_id=contest_id)

            has_teams = any(row.party.teamId is not None for row in standings_official)
            if cf_common.is_nonstandard_contest(contest) or has_teams:
                # The contest is not rated
                ranklist = Ranklist(contest, problems, standings, now, is_rated=False)
            else:
                get_rating = self.cache_master.rating_changes_cache.get_current_rating_or_default
                current_rating = {row.party.members[0].handle: get_rating(row.party.members[0].handle)
                                  for row in standings_official}
                if 'Educational' in contest.name:
                    # For some reason educational contests return all contestants in ranklist even
                    # when unofficial contestants are not requested.
                    current_rating = {handle: rating
                                      for handle, rating in current_rating.items() if rating < 2100}
                ranklist = Ranklist(contest, problems, standings, now, is_rated=True)
                ranklist.predict(current_rating)

        return ranklist

    async def _fetch(self, contests):
        ranklist_by_contest = {}
        for contest in contests:
            try:
                ranklist = await self.generate_ranklist(contest.id, predict_changes=True)
                ranklist_by_contest[contest.id] = ranklist
                self.logger.info(f'Ranklist fetched for contest {contest.id}')
            except cf.CodeforcesApiError as er:
                self.logger.warning(f'Ranklist fetch failed for contest {contest.id}. {er!r}')

        return ranklist_by_contest


class CacheSystem:
    def __init__(self, conn):
        self.conn = conn
        self.contest_cache = ContestCache(self)
        self.problem_cache = ProblemCache(self)
        self.rating_changes_cache = RatingChangesCache(self)
        self.ranklist_cache = RanklistCache(self)

    async def run(self):
        await self.rating_changes_cache.run()
        await self.ranklist_cache.run()
        await self.contest_cache.run()
        await self.problem_cache.run()
