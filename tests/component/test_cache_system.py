"""Component tests for cache sub-systems — ContestCache, ProblemCache,
RatingChangesCache, ProblemsetCache.

Tests data management methods directly, NOT the periodic task infrastructure.

NOTE: The cache modules have a circular import chain
(tle.util.cache.__init__ <-> tle.util.codeforces_common). To avoid triggering
this at test collection time we import cache classes lazily inside fixtures.
"""

import asyncio
from unittest.mock import patch

import pytest

from tle.util.codeforces_api import Contest, Problem, RatingChange
from tle.util.events import ContestListRefresh, EventSystem, Listener


def _make_contest(id=1, name='Round #1', start=1_000_000, dur=7200, phase='FINISHED'):
    return Contest(
        id=id,
        name=name,
        startTimeSeconds=start,
        durationSeconds=dur,
        type='CF',
        phase=phase,
        preparedBy=None,
    )


def _make_problem(contestId=1, index='A', name='Problem A', rating=1500):
    return Problem(
        contestId=contestId,
        problemsetName=None,
        index=index,
        name=name,
        type='PROGRAMMING',
        points=None,
        rating=rating,
        tags=[],
    )


def _make_rating_change(contestId=1, handle='alice', old=1500, new=1600):
    return RatingChange(
        contestId=contestId,
        contestName='Round',
        handle=handle,
        rank=1,
        ratingUpdateTimeSeconds=1_000_000,
        oldRating=old,
        newRating=new,
    )


@pytest.fixture
def cache_system(cache_db):
    """Build a CacheSystem with a real in-memory DB, using lazy import."""
    from tle.util.cache.cache_system import CacheSystem

    return CacheSystem(cache_db)


# --- CacheSystem init ---


class TestCacheSystemInit:
    def test_creates_all_sub_caches(self, cache_system):
        from tle.util.cache.contest import ContestCache
        from tle.util.cache.problem import ProblemCache
        from tle.util.cache.problemset import ProblemsetCache
        from tle.util.cache.rating_changes import RatingChangesCache

        assert isinstance(cache_system.contest_cache, ContestCache)
        assert isinstance(cache_system.problem_cache, ProblemCache)
        assert isinstance(cache_system.rating_changes_cache, RatingChangesCache)
        assert isinstance(cache_system.problemset_cache, ProblemsetCache)

    def test_conn_reference(self, cache_system, cache_db):
        assert cache_system.conn is cache_db


# --- ContestCache ---


class TestContestCache:
    async def test_update_populates_contests(self, cache_system):
        contests = [
            _make_contest(id=1),
            _make_contest(id=2, name='Round #2', start=2_000_000),
        ]
        es = EventSystem()
        with patch('tle.util.cache.contest.cf_common') as mock_cc:
            mock_cc.event_sys = es
            await cache_system.contest_cache._update(contests, from_api=False)
        assert len(cache_system.contest_cache.contests) == 2
        assert 1 in cache_system.contest_cache.contest_by_id
        assert 2 in cache_system.contest_cache.contest_by_id

    async def test_update_populates_contests_by_phase(self, cache_system):
        c_finished = _make_contest(id=1, phase='FINISHED')
        c_before = _make_contest(id=2, phase='BEFORE', start=99_999_999_999)
        es = EventSystem()
        with patch('tle.util.cache.contest.cf_common') as mock_cc:
            mock_cc.event_sys = es
            await cache_system.contest_cache._update(
                [c_finished, c_before],
                from_api=False,
            )
        assert len(cache_system.contest_cache.contests_by_phase['FINISHED']) == 1
        assert len(cache_system.contest_cache.contests_by_phase['BEFORE']) == 1

    async def test_get_contest_found(self, cache_system):
        contests = [_make_contest(id=42)]
        es = EventSystem()
        with patch('tle.util.cache.contest.cf_common') as mock_cc:
            mock_cc.event_sys = es
            await cache_system.contest_cache._update(contests, from_api=False)
        result = cache_system.contest_cache.get_contest(42)
        assert result.id == 42

    async def test_get_contest_not_found(self, cache_system):
        from tle.util.cache.contest import ContestNotFound

        with pytest.raises(ContestNotFound):
            cache_system.contest_cache.get_contest(999)

    async def test_running_phase_grouping(self, cache_system):
        c_coding = _make_contest(id=1, phase='CODING', start=1_000_000)
        c_system = _make_contest(id=2, phase='SYSTEM_TEST', start=2_000_000)
        es = EventSystem()
        with patch('tle.util.cache.contest.cf_common') as mock_cc:
            mock_cc.event_sys = es
            await cache_system.contest_cache._update(
                [c_coding, c_system],
                from_api=False,
            )
        assert len(cache_system.contest_cache.contests_by_phase['_RUNNING']) == 2

    async def test_update_dispatches_event(self, cache_system):
        es = EventSystem()
        received = []

        async def on_refresh(event):
            received.append(event)

        lst = Listener('test', ContestListRefresh, on_refresh)
        es.add_listener(lst)

        with patch('tle.util.cache.contest.cf_common') as mock_cc:
            mock_cc.event_sys = es
            await cache_system.contest_cache._update([_make_contest()], from_api=False)

        await asyncio.sleep(0.05)
        assert len(received) == 1
        assert isinstance(received[0], ContestListRefresh)

    async def test_update_from_api_stores_to_db(self, cache_system):
        contests = [_make_contest(id=1)]
        es = EventSystem()
        with patch('tle.util.cache.contest.cf_common') as mock_cc:
            mock_cc.event_sys = es
            await cache_system.contest_cache._update(contests, from_api=True)
        fetched = await cache_system.conn.fetch_contests()
        assert len(fetched) == 1

    async def test_try_disk_loads_from_db(self, cache_system):
        await cache_system.conn.cache_contests(
            [_make_contest(id=10, name='Disk Round')],
        )
        es = EventSystem()
        with patch('tle.util.cache.contest.cf_common') as mock_cc:
            mock_cc.event_sys = es
            await cache_system.contest_cache._try_disk()
        assert 10 in cache_system.contest_cache.contest_by_id


# --- ProblemCache ---


class TestProblemCache:
    @pytest.fixture
    def cache_with_contests(self, cache_system):
        cache_system.contest_cache.contest_by_id = {1: _make_contest(id=1)}
        return cache_system

    async def test_update_filters_problems(self, cache_with_contests):
        p1 = _make_problem(contestId=1, name='Good', rating=1500)
        p2 = _make_problem(contestId=1, name='NoRating', rating=None)
        p3 = _make_problem(contestId=999, name='UnknownContest', rating=1500)

        await cache_with_contests.problem_cache._update([p1, p2, p3])
        assert len(cache_with_contests.problem_cache.problems) == 1
        assert cache_with_contests.problem_cache.problems[0].name == 'Good'

    async def test_problem_by_name_mapping(self, cache_with_contests):
        p = _make_problem(contestId=1, name='Unique', rating=1500)
        await cache_with_contests.problem_cache._update([p])
        assert 'Unique' in cache_with_contests.problem_cache.problem_by_name

    async def test_try_disk_loads(self, cache_with_contests):
        p = _make_problem(contestId=1, name='DiskProblem', rating=1500)
        await cache_with_contests.conn.cache_problems([p])
        await cache_with_contests.problem_cache._try_disk()
        assert len(cache_with_contests.problem_cache.problems) == 1
        prob = cache_with_contests.problem_cache.problem_by_name['DiskProblem']
        assert prob.rating == 1500


# --- RatingChangesCache ---


class TestRatingChangesCache:
    async def test_get_current_rating_found(self, cache_system):
        change = _make_rating_change(handle='alice', new=1700)
        await cache_system.conn.save_rating_changes([change])
        await cache_system.rating_changes_cache._refresh_handle_cache()
        assert cache_system.rating_changes_cache.get_current_rating('alice') == 1700

    async def test_get_current_rating_missing_returns_none(self, cache_system):
        assert cache_system.rating_changes_cache.get_current_rating('nobody') is None

    async def test_get_current_rating_default_if_absent(self, cache_system):
        result = cache_system.rating_changes_cache.get_current_rating(
            'nobody', default_if_absent=True
        )
        assert result == 1500

    async def test_get_all_ratings(self, cache_system):
        changes = [
            _make_rating_change(contestId=1, handle='alice', new=1700),
            _make_rating_change(contestId=2, handle='bob', new=1800),
        ]
        await cache_system.conn.save_rating_changes(changes)
        await cache_system.rating_changes_cache._refresh_handle_cache()
        ratings = cache_system.rating_changes_cache.get_all_ratings()
        assert sorted(ratings) == [1700, 1800]

    async def test_refresh_handle_cache_from_db(self, cache_system):
        changes = [_make_rating_change(handle='charlie', new=2000)]
        await cache_system.conn.save_rating_changes(changes)
        await cache_system.rating_changes_cache._refresh_handle_cache()
        assert cache_system.rating_changes_cache.get_current_rating('charlie') == 2000

    async def test_save_changes_stores_and_refreshes(self, cache_system):
        contest = _make_contest(id=1)
        change = _make_rating_change(contestId=1, handle='dave', new=1900)
        await cache_system.rating_changes_cache._save_changes([(contest, [change])])
        assert cache_system.rating_changes_cache.get_current_rating('dave') == 1900


# --- ProblemsetCache ---


class TestProblemsetCache:
    async def test_get_problemset_not_cached_raises(self, cache_system):
        from tle.util.cache.problemset import ProblemsetNotCached

        with pytest.raises(ProblemsetNotCached):
            await cache_system.problemset_cache.get_problemset(999)

    async def test_get_problemset_returns_data(self, cache_system):
        p = _make_problem(contestId=1, index='A', name='P1', rating=1500)
        await cache_system.conn.cache_problemset([p])
        result = await cache_system.problemset_cache.get_problemset(1)
        assert len(result) == 1
        assert result[0].name == 'P1'
