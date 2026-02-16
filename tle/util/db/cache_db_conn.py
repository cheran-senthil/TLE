# mypy: disable-error-code="no-any-return"
import json
from collections.abc import Iterator
from typing import Any

import aiosqlite

from tle.util import codeforces_api as cf


class CacheDbConn:
    def __init__(self, db_file: str) -> None:
        self.db_file = db_file
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, 'Database not connected. Call connect() first.'
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_file)
        await self._conn.execute('PRAGMA journal_mode=WAL')
        await self._conn.execute('PRAGMA synchronous=NORMAL')
        await self.create_tables()

    async def create_tables(self) -> None:
        # Table for contests from the contest.list endpoint.
        await self.conn.execute(
            'CREATE TABLE IF NOT EXISTS contest ('
            'id             INTEGER NOT NULL,'
            'name           TEXT,'
            'start_time     INTEGER,'
            'duration       INTEGER,'
            'type           TEXT,'
            'phase          TEXT,'
            'prepared_by    TEXT,'
            'PRIMARY KEY (id)'
            ')'
        )

        # Table for problems from the problemset.problems endpoint.
        await self.conn.execute(
            'CREATE TABLE IF NOT EXISTS problem ('
            'contest_id       INTEGER,'
            'problemset_name  TEXT,'
            '[index]          TEXT,'
            'name             TEXT NOT NULL,'
            'type             TEXT,'
            'points           REAL,'
            'rating           INTEGER,'
            'tags             TEXT,'
            'PRIMARY KEY (name)'
            ')'
        )

        # Table for rating changes fetched from contest.ratingChanges endpoint
        # for every contest.
        await self.conn.execute(
            'CREATE TABLE IF NOT EXISTS rating_change ('
            'contest_id           INTEGER NOT NULL,'
            'handle               TEXT NOT NULL,'
            'rank                 INTEGER,'
            'rating_update_time   INTEGER,'
            'old_rating           INTEGER,'
            'new_rating           INTEGER,'
            'UNIQUE (contest_id, handle)'
            ')'
        )
        await self.conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_rating_change_contest_id ON rating_change (
                contest_id
            )
        """)
        await self.conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_rating_change_handle ON rating_change (handle)
        """)

        # Table for problems fetched from contest.standings endpoint for every
        # contest. This is separate from table problem as it contains the same
        # problem twice if it appeared in both Div 1 and Div 2 of some round.
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS problem2 (
                contest_id       INTEGER,
                problemset_name  TEXT,
                [index]          TEXT,
                name             TEXT NOT NULL,
                type             TEXT,
                points           REAL,
                rating           INTEGER,
                tags             TEXT,
                PRIMARY KEY (contest_id, [index])
            )
        """)
        await self.conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_problem2_contest_id ON problem2 (contest_id)
        """)

    async def cache_contests(self, contests: list[Any]) -> int:
        query = """
            INSERT OR REPLACE INTO contest (
                id, name, start_time, duration, type, phase, prepared_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.executemany(query, contests)
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def fetch_contests(self) -> list[cf.Contest]:
        query = """
            SELECT id, name, start_time, duration, type, phase, prepared_by FROM contest
        """
        cursor = await self.conn.execute(query)
        res = await cursor.fetchall()
        return [cf.Contest._make(contest) for contest in res]

    @staticmethod
    def _squish_tags(problem: cf.Problem) -> tuple[Any, ...]:
        return (
            problem.contestId,
            problem.problemsetName,
            problem.index,
            problem.name,
            problem.type,
            problem.points,
            problem.rating,
            json.dumps(problem.tags),
        )

    async def cache_problems(self, problems: list[cf.Problem]) -> int:
        query = """
            INSERT OR REPLACE INTO problem (
                contest_id, problemset_name, [index], name, type, points, rating, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.executemany(
            query, list(map(self._squish_tags, problems))
        )
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    @staticmethod
    def _unsquish_tags(problem: tuple[Any, ...]) -> cf.Problem:
        args = problem[:-1]
        tags: list[str] = json.loads(problem[-1])
        return cf.Problem._make((*args, tags))

    async def fetch_problems(self) -> list[cf.Problem]:
        query = """
            SELECT
                contest_id, problemset_name, [index], name, type, points, rating, tags
            FROM problem
        """
        cursor = await self.conn.execute(query)
        res = await cursor.fetchall()
        return list(map(self._unsquish_tags, res))

    async def save_rating_changes(self, changes: list[cf.RatingChange]) -> int:
        change_tuples = [
            (
                change.contestId,
                change.handle,
                change.rank,
                change.ratingUpdateTimeSeconds,
                change.oldRating,
                change.newRating,
            )
            for change in changes
        ]
        query = """
            INSERT OR REPLACE INTO rating_change (
                contest_id, handle, rank, rating_update_time, old_rating, new_rating
            ) VALUES (?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.executemany(query, change_tuples)
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def clear_rating_changes(self, contest_id: int | None = None) -> None:
        if contest_id is None:
            query = 'DELETE FROM rating_change'
            await self.conn.execute(query)
        else:
            query = 'DELETE FROM rating_change WHERE contest_id = ?'
            await self.conn.execute(query, (contest_id,))
        await self.conn.commit()

    async def get_users_with_more_than_n_contests(
        self, time_cutoff: int, n: int
    ) -> list[str]:
        query = """
            SELECT
                handle,
                COUNT(*) AS num_contests
            FROM rating_change
            GROUP BY handle
            HAVING num_contests >= ? AND MAX(rating_update_time) >= ?
        """
        cursor = await self.conn.execute(
            query,
            (
                n,
                time_cutoff,
            ),
        )
        res = await cursor.fetchall()
        return [user[0] for user in res]

    async def get_all_rating_changes(self) -> Iterator[cf.RatingChange]:
        query = """
            SELECT
                contest_id,
                name,
                handle,
                rank,
                rating_update_time,
                old_rating,
                new_rating
            FROM rating_change r
            LEFT JOIN contest c ON r.contest_id = c.id
            ORDER BY rating_update_time
        """
        cursor = await self.conn.execute(query)
        res = await cursor.fetchall()
        return (cf.RatingChange._make(change) for change in res)

    async def get_latest_rating_by_handle(self) -> dict[str, int]:
        """Return {handle: latest_new_rating} without loading the full table."""
        query = """
            SELECT handle, new_rating
            FROM rating_change
            ORDER BY rating_update_time
        """
        cursor = await self.conn.execute(query)
        result: dict[str, int] = {}
        async for handle, new_rating in cursor:
            result[handle] = new_rating
        return result

    async def get_rating_changes_for_contest(
        self, contest_id: int
    ) -> list[cf.RatingChange]:
        query = """
            SELECT
                contest_id,
                name,
                handle,
                rank,
                rating_update_time,
                old_rating,
                new_rating
            FROM rating_change r
            LEFT JOIN contest c ON r.contest_id = c.id
            WHERE r.contest_id = ?
        """
        cursor = await self.conn.execute(query, (contest_id,))
        res = await cursor.fetchall()
        return [cf.RatingChange._make(change) for change in res]

    async def has_rating_changes_saved(self, contest_id: int) -> bool:
        query = 'SELECT contest_id FROM rating_change WHERE contest_id = ?'
        cursor = await self.conn.execute(query, (contest_id,))
        res = await cursor.fetchone()
        return res is not None

    async def get_rating_changes_for_handle(self, handle: str) -> list[cf.RatingChange]:
        query = """
            SELECT
                contest_id,
                name,
                handle,
                rank,
                rating_update_time,
                old_rating,
                new_rating
            FROM rating_change r
            LEFT JOIN contest c ON r.contest_id = c.id
            WHERE r.handle = ?
        """
        cursor = await self.conn.execute(query, (handle,))
        res = await cursor.fetchall()
        return [cf.RatingChange._make(change) for change in res]

    async def cache_problemset(self, problemset: list[cf.Problem]) -> int:
        query = """
            INSERT OR REPLACE INTO problem2 (
                contest_id, problemset_name, [index], name, type, points, rating, tags
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.executemany(
            query, list(map(self._squish_tags, problemset))
        )
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def fetch_problems2(self) -> list[cf.Problem]:
        query = """
            SELECT
                contest_id, problemset_name, [index], name, type, points, rating, tags
            FROM problem2
        """
        cursor = await self.conn.execute(query)
        res = await cursor.fetchall()
        return list(map(self._unsquish_tags, res))

    async def clear_problemset(self, contest_id: int | None = None) -> None:
        if contest_id is None:
            query = 'DELETE FROM problem2'
            await self.conn.execute(query)
        else:
            query = 'DELETE FROM problem2 WHERE contest_id = ?'
            await self.conn.execute(query, (contest_id,))

    async def fetch_problemset(self, contest_id: int) -> list[cf.Problem]:
        query = """
            SELECT
                contest_id, problemset_name, [index], name, type, points, rating, tags
            FROM problem2
            WHERE contest_id = ?
        """
        cursor = await self.conn.execute(query, (contest_id,))
        res = await cursor.fetchall()
        return list(map(self._unsquish_tags, res))

    async def problemset_empty(self) -> bool:
        query = 'SELECT 1 FROM problem2'
        cursor = await self.conn.execute(query)
        res = await cursor.fetchone()
        return res is None

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def get_problemset_from_contest(self, contest_id: int) -> list[cf.Problem]:
        return await self.fetch_problemset(contest_id)
