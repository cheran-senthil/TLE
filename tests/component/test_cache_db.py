"""Component tests for tle.util.db.cache_db_conn — async in-memory aiosqlite."""

from tle.util.codeforces_api import Problem, RatingChange


class TestTableCreation:
    async def test_tables_exist(self, cache_db):
        cursor = await cache_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}
        expected = {'contest', 'problem', 'rating_change', 'problem2'}
        assert expected.issubset(table_names)


class TestContestCache:
    async def test_cache_and_fetch(self, cache_db):
        contests = [(1, 'Round #1', 1000, 7200, 'CF', 'FINISHED', None)]
        await cache_db.cache_contests(contests)
        fetched = await cache_db.fetch_contests()
        assert len(fetched) == 1
        assert fetched[0].id == 1
        assert fetched[0].name == 'Round #1'

    async def test_multiple(self, cache_db):
        contests = [
            (1, 'Round #1', 1000, 7200, 'CF', 'FINISHED', None),
            (2, 'Round #2', 2000, 7200, 'CF', 'FINISHED', None),
        ]
        await cache_db.cache_contests(contests)
        fetched = await cache_db.fetch_contests()
        assert len(fetched) == 2

    async def test_upsert(self, cache_db):
        contests = [(1, 'Round #1', 1000, 7200, 'CF', 'BEFORE', None)]
        await cache_db.cache_contests(contests)
        updated = [(1, 'Round #1', 1000, 7200, 'CF', 'FINISHED', None)]
        await cache_db.cache_contests(updated)
        fetched = await cache_db.fetch_contests()
        assert len(fetched) == 1
        assert fetched[0].phase == 'FINISHED'


class TestProblemCache:
    def _make_problem(self, **kwargs):
        defaults = dict(
            contestId=1,
            problemsetName=None,
            index='A',
            name='Test Problem',
            type='PROGRAMMING',
            points=None,
            rating=1500,
            tags=['dp', 'math'],
        )
        defaults.update(kwargs)
        return Problem(**defaults)

    async def test_cache_and_fetch(self, cache_db):
        prob = self._make_problem()
        await cache_db.cache_problems([prob])
        fetched = await cache_db.fetch_problems()
        assert len(fetched) == 1
        assert fetched[0].name == 'Test Problem'

    async def test_tag_json_roundtrip(self, cache_db):
        prob = self._make_problem(tags=['dp', 'math', 'greedy'])
        await cache_db.cache_problems([prob])
        fetched = await cache_db.fetch_problems()
        assert fetched[0].tags == ['dp', 'math', 'greedy']

    async def test_empty_tags(self, cache_db):
        prob = self._make_problem(tags=[])
        await cache_db.cache_problems([prob])
        fetched = await cache_db.fetch_problems()
        assert fetched[0].tags == []


class TestRatingChanges:
    def _make_change(self, **kwargs):
        defaults = dict(
            contestId=1,
            contestName='Round #1',
            handle='tourist',
            rank=1,
            ratingUpdateTimeSeconds=1000,
            oldRating=3000,
            newRating=3050,
        )
        defaults.update(kwargs)
        return RatingChange(**defaults)

    async def test_save_and_fetch_by_contest(self, cache_db):
        # Need to cache the contest first for the JOIN
        contest = [(1, 'Round #1', 1000, 7200, 'CF', 'FINISHED', None)]
        await cache_db.cache_contests(contest)
        change = self._make_change()
        await cache_db.save_rating_changes([change])
        fetched = await cache_db.get_rating_changes_for_contest(1)
        assert len(fetched) == 1
        assert fetched[0].handle == 'tourist'

    async def test_has_saved(self, cache_db):
        change = self._make_change()
        await cache_db.save_rating_changes([change])
        assert await cache_db.has_rating_changes_saved(1) is True
        assert await cache_db.has_rating_changes_saved(999) is False

    async def test_fetch_by_handle(self, cache_db):
        contest = [(1, 'Round #1', 1000, 7200, 'CF', 'FINISHED', None)]
        await cache_db.cache_contests(contest)
        change = self._make_change()
        await cache_db.save_rating_changes([change])
        fetched = await cache_db.get_rating_changes_for_handle('tourist')
        assert len(fetched) == 1

    async def test_get_all(self, cache_db):
        await cache_db.cache_contests(
            [
                (1, 'Round #1', 1000, 7200, 'CF', 'FINISHED', None),
                (2, 'Round #2', 2000, 7200, 'CF', 'FINISHED', None),
            ]
        )
        changes = [
            self._make_change(contestId=1, handle='alice'),
            self._make_change(contestId=2, handle='bob'),
        ]
        await cache_db.save_rating_changes(changes)
        all_changes = list(await cache_db.get_all_rating_changes())
        assert len(all_changes) == 2

    async def test_clear_all(self, cache_db):
        change = self._make_change()
        await cache_db.save_rating_changes([change])
        await cache_db.clear_rating_changes()
        assert await cache_db.has_rating_changes_saved(1) is False

    async def test_clear_by_contest(self, cache_db):
        changes = [
            self._make_change(contestId=1, handle='alice'),
            self._make_change(contestId=2, handle='bob'),
        ]
        await cache_db.save_rating_changes(changes)
        await cache_db.clear_rating_changes(contest_id=1)
        assert await cache_db.has_rating_changes_saved(1) is False
        assert await cache_db.has_rating_changes_saved(2) is True


class TestProblemset:
    def _make_problem(self, **kwargs):
        defaults = dict(
            contestId=1,
            problemsetName=None,
            index='A',
            name='Test Problem',
            type='PROGRAMMING',
            points=None,
            rating=1500,
            tags=['dp'],
        )
        defaults.update(kwargs)
        return Problem(**defaults)

    async def test_cache_and_fetch(self, cache_db):
        prob = self._make_problem()
        await cache_db.cache_problemset([prob])
        fetched = await cache_db.fetch_problems2()
        assert len(fetched) == 1

    async def test_by_contest(self, cache_db):
        probs = [
            self._make_problem(contestId=1, index='A', name='P1'),
            self._make_problem(contestId=1, index='B', name='P2'),
            self._make_problem(contestId=2, index='A', name='P3'),
        ]
        await cache_db.cache_problemset(probs)
        fetched = await cache_db.fetch_problemset(1)
        assert len(fetched) == 2

    async def test_clear_all(self, cache_db):
        prob = self._make_problem()
        await cache_db.cache_problemset([prob])
        await cache_db.clear_problemset()
        fetched = await cache_db.fetch_problems2()
        assert len(fetched) == 0

    async def test_clear_by_contest(self, cache_db):
        probs = [
            self._make_problem(contestId=1, index='A', name='P1'),
            self._make_problem(contestId=2, index='A', name='P2'),
        ]
        await cache_db.cache_problemset(probs)
        await cache_db.clear_problemset(contest_id=1)
        fetched = await cache_db.fetch_problems2()
        assert len(fetched) == 1
        assert fetched[0].contestId == 2

    async def test_empty_check(self, cache_db):
        assert await cache_db.problemset_empty() is True
        prob = self._make_problem()
        await cache_db.cache_problemset([prob])
        assert await cache_db.problemset_empty() is False

    async def test_get_from_contest(self, cache_db):
        probs = [
            self._make_problem(contestId=1, index='A', name='P1'),
            self._make_problem(contestId=1, index='B', name='P2'),
        ]
        await cache_db.cache_problemset(probs)
        fetched = await cache_db.get_problemset_from_contest(1)
        assert len(fetched) == 2


class TestUsersWithContests:
    async def test_get_users_with_n_plus_contests(self, cache_db):
        changes = [
            RatingChange(
                contestId=1,
                contestName='R1',
                handle='alice',
                rank=1,
                ratingUpdateTimeSeconds=1000,
                oldRating=1500,
                newRating=1600,
            ),
            RatingChange(
                contestId=2,
                contestName='R2',
                handle='alice',
                rank=1,
                ratingUpdateTimeSeconds=2000,
                oldRating=1600,
                newRating=1700,
            ),
            RatingChange(
                contestId=1,
                contestName='R1',
                handle='bob',
                rank=2,
                ratingUpdateTimeSeconds=1000,
                oldRating=1500,
                newRating=1400,
            ),
        ]
        await cache_db.save_rating_changes(changes)
        users = await cache_db.get_users_with_more_than_n_contests(0, 2)
        assert 'alice' in users
        assert 'bob' not in users
