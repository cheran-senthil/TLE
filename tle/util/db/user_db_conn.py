# mypy: disable-error-code="no-any-return"
from collections import namedtuple
from collections.abc import Callable, Sequence
from enum import IntEnum
from typing import Any

import aiosqlite
from discord.ext import commands

from tle import constants
from tle.util import codeforces_api as cf

_DEFAULT_VC_RATING = 1500


class Gitgud(IntEnum):
    GOTGUD = 0
    GITGUD = 1
    NOGUD = 2
    FORCED_NOGUD = 3


class Duel(IntEnum):
    PENDING = 0
    DECLINED = 1
    WITHDRAWN = 2
    EXPIRED = 3
    ONGOING = 4
    COMPLETE = 5
    INVALID = 6


class Winner(IntEnum):
    DRAW = 0
    CHALLENGER = 1
    CHALLENGEE = 2


class DuelType(IntEnum):
    UNOFFICIAL = 0
    OFFICIAL = 1


class RatedVC(IntEnum):
    ONGOING = 0
    FINISHED = 1


class UserDbError(commands.CommandError):
    pass


class DatabaseDisabledError(UserDbError):
    pass


class DummyUserDbConn:
    def __getattribute__(self, item: str) -> Any:
        raise DatabaseDisabledError


class UniqueConstraintFailed(UserDbError):
    pass


def namedtuple_factory(cursor: Any, row: tuple[Any, ...]) -> Any:
    """Returns sqlite rows as named tuples."""
    fields = [col[0] for col in cursor.description]
    for f in fields:
        if not f.isidentifier():
            raise ValueError(f'Column name {f!r} is not a valid identifier')
    Row = namedtuple('Row', fields)  # type: ignore[misc]
    return Row(*row)


# Allowlists for table/column names used in _insert_one/_insert_many
_VALID_TABLES = frozenset(
    {
        'starboard_emoji_v1',
        'starboard_config_v1',
        'starboard_message_v1',
    }
)
_VALID_COLUMNS = frozenset(
    {
        'guild_id',
        'emoji',
        'threshold',
        'color',
        'channel_id',
        'original_msg_id',
        'starboard_msg_id',
    }
)


class UserDbConn:
    def __init__(self, dbfile: str) -> None:
        self.db_file = dbfile
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, 'Database not connected. Call connect() first.'
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_file)
        await self._conn.execute('PRAGMA journal_mode=WAL')
        await self._conn.execute('PRAGMA synchronous=NORMAL')
        self._conn.row_factory = namedtuple_factory
        await self.create_tables()

    async def create_tables(self) -> None:
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_handle (
                user_id     TEXT,
                guild_id    TEXT,
                handle      TEXT,
                active      INTEGER,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await self.conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            ix_user_handle_guild_handle ON user_handle (guild_id, handle)
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cf_user_cache (
                handle              TEXT PRIMARY KEY,
                first_name          TEXT,
                last_name           TEXT,
                country             TEXT,
                city                TEXT,
                organization        TEXT,
                contribution        INTEGER,
                rating              INTEGER,
                maxRating           INTEGER,
                last_online_time    INTEGER,
                registration_time   INTEGER,
                friend_of_count     INTEGER,
                title_photo         TEXT
            )
        """)
        # TODO: Make duel tables guild-aware.
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS duelist(
                "user_id"  INTEGER PRIMARY KEY NOT NULL,
                "rating"   INTEGER NOT NULL
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS duel(
                "id"           INTEGER PRIMARY KEY AUTOINCREMENT,
                "challenger"   INTEGER NOT NULL,
                "challengee"   INTEGER NOT NULL,
                "issue_time"   REAL NOT NULL,
                "start_time"   REAL,
                "finish_time"  REAL,
                "problem_name" TEXT,
                "contest_id"   INTEGER,
                "p_index"      INTEGER,
                "status"       INTEGER,
                "winner"       INTEGER,
                "type"         INTEGER
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS "challenge" (
                "id" INTEGER PRIMARY KEY AUTOINCREMENT,
                "user_id" TEXT NOT NULL,
                "issue_time" REAL NOT NULL,
                "finish_time" REAL,
                "problem_name" TEXT NOT NULL,
                "contest_id" INTEGER NOT NULL,
                "p_index" INTEGER NOT NULL,
                "rating_delta" INTEGER NOT NULL,
                "status" INTEGER NOT NULL
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS "user_challenge" (
                "user_id" TEXT,
                "active_challenge_id" INTEGER,
                "issue_time" REAL,
                "score" INTEGER NOT NULL,
                "num_completed" INTEGER NOT NULL,
                "num_skipped" INTEGER NOT NULL,
                PRIMARY KEY ("user_id")
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS "reminder" (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT,
                role_id TEXT,
                before TEXT
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS rankup (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_role_update (
                guild_id TEXT PRIMARY KEY
            )
        """)

        # Rated VCs stuff:
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS "rated_vcs" (
                "id" INTEGER PRIMARY KEY AUTOINCREMENT,
                "contest_id" INTEGER NOT NULL,
                "start_time" REAL,
                "finish_time" REAL,
                "status" INTEGER,
                "guild_id" TEXT
            )
        """)

        # TODO: Do we need to explicitly specify the fk constraint
        #       or just depend on the middleware?
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS "rated_vc_users" (
                "vc_id" INTEGER,
                "user_id" TEXT NOT NULL,
                "rating" INTEGER,

                CONSTRAINT fk_vc
                FOREIGN KEY (vc_id)
                REFERENCES rated_vcs (id),

                PRIMARY KEY (vc_id, user_id)
            )
        """)

        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS rated_vc_settings (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT
            )
        """)

        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS starboard_config_v1 (
                guild_id TEXT,
                emoji TEXT,
                channel_id TEXT,
                PRIMARY KEY (guild_id, emoji)
            )
        """)

        # 1b) emoji holds threshold + color
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS starboard_emoji_v1 (
                guild_id TEXT,
                emoji TEXT,
                threshold INTEGER,
                color INTEGER,
                PRIMARY KEY (guild_id, emoji)
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS starboard_message_v1 (
                original_msg_id TEXT,
                starboard_msg_id TEXT,
                guild_id TEXT,
                emoji TEXT,
                PRIMARY KEY (original_msg_id, emoji)
            )
         """)

        # === one-time migration from old tables ===
        cursor = await self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='starboard'"
        )
        old_exists = bool(await cursor.fetchone())

        cursor = await self.conn.execute(
            'SELECT COUNT(*) AS cnt FROM starboard_config_v1'
        )
        row = await cursor.fetchone()
        migrated = row.cnt > 0

        if old_exists and not migrated:
            cursor = await self.conn.execute(
                'SELECT guild_id, channel_id FROM starboard'
            )
            for guild_id, channel_id in await cursor.fetchall():
                await self.conn.execute(
                    """
                    INSERT OR IGNORE INTO starboard_config_v1 (
                        guild_id, emoji, channel_id
                    ) VALUES (?, ?, ?)
                    """,
                    (guild_id, constants._DEFAULT_STAR, channel_id),
                )
                await self.conn.execute(
                    """
                    INSERT OR IGNORE INTO starboard_emoji_v1 (
                        guild_id, emoji, threshold, color
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (guild_id, constants._DEFAULT_STAR, 5, constants._DEFAULT_COLOR),
                )

            # lift old messages
            cursor = await self.conn.execute("""
                SELECT
                    original_msg_id,
                    starboard_msg_id,
                    guild_id
                FROM starboard_message
                """)
            for orig, star, guild_id in await cursor.fetchall():
                await self.conn.execute(
                    """
                    INSERT OR IGNORE INTO starboard_message_v1 (
                        original_msg_id, starboard_msg_id, guild_id, emoji
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (orig, star, guild_id, constants._DEFAULT_STAR),
                )
            await self.conn.commit()

    # Helper functions.

    async def _insert_one(
        self, table: str, columns: Sequence[str], values: tuple[Any, ...]
    ) -> int:
        if table not in _VALID_TABLES:
            raise ValueError(f'Invalid table name: {table!r}')
        for col in columns:
            if col not in _VALID_COLUMNS:
                raise ValueError(f'Invalid column name: {col!r}')
        n = len(values)
        query = """
            INSERT OR REPLACE INTO {} ({}) VALUES ({})
        """.format(table, ', '.join(columns), ', '.join(['?'] * n))
        cursor = await self.conn.execute(query, values)
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def _insert_many(
        self, table: str, columns: Sequence[str], values: list[tuple[Any, ...]]
    ) -> int:
        if table not in _VALID_TABLES:
            raise ValueError(f'Invalid table name: {table!r}')
        for col in columns:
            if col not in _VALID_COLUMNS:
                raise ValueError(f'Invalid column name: {col!r}')
        n = len(columns)
        query = """
            INSERT OR REPLACE INTO {} ({}) VALUES ({})
        """.format(table, ', '.join(columns), ', '.join(['?'] * n))
        cursor = await self.conn.executemany(query, values)
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def _fetchone(
        self,
        query: str,
        params: tuple[Any, ...] | None = None,
        row_factory: Callable[..., Any] | None = None,
    ) -> Any:
        cursor = await self.conn.execute(query, params or ())
        if row_factory:
            cursor.row_factory = row_factory
        return await cursor.fetchone()

    async def _fetchall(
        self,
        query: str,
        params: tuple[Any, ...] | None = None,
        row_factory: Callable[..., Any] | None = None,
    ) -> list[Any]:
        cursor = await self.conn.execute(query, params or ())
        if row_factory:
            cursor.row_factory = row_factory
        return await cursor.fetchall()

    async def new_challenge(
        self, user_id: int, issue_time: float, prob: Any, delta: int
    ) -> int:
        query1 = """
            INSERT INTO challenge
            (
                user_id, issue_time, problem_name,
                contest_id, p_index, rating_delta, status
            )
            VALUES
            (?, ?, ?, ?, ?, ?, 1)
        """
        query2 = """
            INSERT OR IGNORE INTO user_challenge (
                user_id, score, num_completed, num_skipped
            )
            VALUES (?, 0, 0, 0)
        """
        query3 = """
            UPDATE user_challenge SET active_challenge_id = ?, issue_time = ?
            WHERE user_id = ? AND active_challenge_id IS NULL
        """
        cursor = await self.conn.execute(
            query1, (user_id, issue_time, prob.name, prob.contestId, prob.index, delta)
        )
        last_id, rc = cursor.lastrowid, cursor.rowcount
        if rc != 1:
            await self.conn.rollback()
            return 0
        await self.conn.execute(query2, (user_id,))
        cursor = await self.conn.execute(query3, (last_id, issue_time, user_id))
        if cursor.rowcount != 1:
            await self.conn.rollback()
            return 0
        await self.conn.commit()
        return 1

    async def check_challenge(self, user_id: int) -> Any:
        query1 = """
            SELECT
                active_challenge_id,
                issue_time
            FROM user_challenge
            WHERE user_id = ?
        """
        cursor = await self.conn.execute(query1, (user_id,))
        res = await cursor.fetchone()
        if res is None:
            return None
        c_id, issue_time = res
        query2 = """
            SELECT
                problem_name,
                contest_id,
                p_index,
                rating_delta
            FROM challenge
            WHERE id = ?
        """
        cursor = await self.conn.execute(query2, (c_id,))
        res = await cursor.fetchone()
        if res is None:
            return None
        return c_id, issue_time, res[0], res[1], res[2], res[3]

    async def get_gudgitters(self) -> list[Any]:
        query = """
            SELECT
                user_id,
                score
            FROM user_challenge
        """
        cursor = await self.conn.execute(query)
        return await cursor.fetchall()

    async def howgud(self, user_id: int) -> list[Any]:
        query = """
            SELECT rating_delta FROM challenge
            WHERE user_id = ? AND finish_time IS NOT NULL
        """
        cursor = await self.conn.execute(query, (user_id,))
        return await cursor.fetchall()

    async def get_noguds(self, user_id: int) -> set[str]:
        query = """
            SELECT problem_name FROM challenge
            WHERE user_id = ? AND status = ?
        """
        cursor = await self.conn.execute(query, (user_id, Gitgud.NOGUD))
        return {name for (name,) in await cursor.fetchall()}

    async def gitlog(self, user_id: int) -> list[Any]:
        query = """
            SELECT
                issue_time,
                finish_time,
                problem_name,
                contest_id,
                p_index,
                rating_delta,
                status
            FROM challenge
            WHERE user_id = ? AND status != ?
            ORDER BY issue_time DESC
        """
        cursor = await self.conn.execute(query, (user_id, Gitgud.FORCED_NOGUD))
        return await cursor.fetchall()

    async def complete_challenge(
        self, user_id: int, challenge_id: int, finish_time: float, delta: int
    ) -> int:
        query1 = """
            UPDATE challenge SET finish_time = ?, status = ?
            WHERE id = ? AND status = ?
        """
        query2 = """
            UPDATE user_challenge SET
                score = score + ?, num_completed = num_completed + 1,
                active_challenge_id = NULL, issue_time = NULL
            WHERE user_id = ? AND active_challenge_id = ?
        """
        cursor = await self.conn.execute(
            query1, (finish_time, Gitgud.GOTGUD, challenge_id, Gitgud.GITGUD)
        )
        if cursor.rowcount != 1:
            await self.conn.rollback()
            return 0
        cursor = await self.conn.execute(query2, (delta, user_id, challenge_id))
        if cursor.rowcount != 1:
            await self.conn.rollback()
            return 0
        await self.conn.commit()
        return 1

    async def skip_challenge(self, user_id: int, challenge_id: int, status: int) -> int:
        query1 = """
            UPDATE user_challenge SET active_challenge_id = NULL, issue_time = NULL
            WHERE user_id = ? AND active_challenge_id = ?
        """
        query2 = """
            UPDATE challenge
            SET status = ?
            WHERE id = ? AND status = ?
        """
        cursor = await self.conn.execute(query1, (user_id, challenge_id))
        if cursor.rowcount != 1:
            await self.conn.rollback()
            return 0
        cursor = await self.conn.execute(query2, (status, challenge_id, Gitgud.GITGUD))
        if cursor.rowcount != 1:
            await self.conn.rollback()
            return 0
        await self.conn.commit()
        return 1

    async def cache_cf_user(self, user: Any) -> int:
        query = """
            INSERT OR REPLACE INTO cf_user_cache
            (
                handle, first_name, last_name, country, city, organization,
                contribution,rating, maxRating, last_online_time,
                registration_time, friend_of_count, title_photo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.execute(query, user)
        await self.conn.commit()
        return cursor.rowcount

    async def fetch_cf_user(self, handle: str) -> Any:
        query = """
            SELECT
                handle, first_name, last_name, country, city, organization,
                contribution, rating, maxRating, last_online_time,
                registration_time, friend_of_count, title_photo
            FROM cf_user_cache
            WHERE UPPER(handle) = UPPER(?)
        """
        cursor = await self.conn.execute(query, (handle,))
        user = await cursor.fetchone()
        return cf.fix_urls(cf.User._make(user)) if user else None

    async def set_handle(self, user_id: int, guild_id: int, handle: str) -> int:
        query = """
            SELECT user_id FROM user_handle
            WHERE guild_id = ? AND handle = ?
        """
        cursor = await self.conn.execute(query, (guild_id, handle))
        existing = await cursor.fetchone()
        if existing and int(existing[0]) != user_id:
            raise UniqueConstraintFailed

        query = """
            INSERT OR REPLACE INTO user_handle (user_id, guild_id, handle, active)
            VALUES (?, ?, ?, 1)
        """
        cursor = await self.conn.execute(query, (user_id, guild_id, handle))
        await self.conn.commit()
        return cursor.rowcount

    async def set_inactive(self, guild_id_user_id_pairs: list[tuple[str, str]]) -> int:
        query = """
            UPDATE user_handle SET active = 0
            WHERE guild_id = ? AND user_id = ?
        """
        cursor = await self.conn.executemany(query, guild_id_user_id_pairs)
        await self.conn.commit()
        return cursor.rowcount

    async def get_handle(self, user_id: int, guild_id: int) -> str | None:
        query = """
            SELECT handle FROM user_handle
            WHERE user_id = ? AND guild_id = ?
        """
        cursor = await self.conn.execute(query, (user_id, guild_id))
        res = await cursor.fetchone()
        return res[0] if res else None

    async def get_user_id(self, handle: str, guild_id: int) -> int | None:
        query = """
            SELECT user_id FROM user_handle
            WHERE UPPER(handle) = UPPER(?) AND guild_id = ?
        """
        cursor = await self.conn.execute(query, (handle, guild_id))
        res = await cursor.fetchone()
        return int(res[0]) if res else None

    async def remove_handle(self, handle: str, guild_id: int) -> int:
        query = """
            DELETE FROM user_handle
            WHERE UPPER(handle) = UPPER(?) AND guild_id = ?
        """
        cursor = await self.conn.execute(query, (handle, guild_id))
        await self.conn.commit()
        return cursor.rowcount

    async def get_handles_for_guild(self, guild_id: int) -> list[tuple[int, str]]:
        query = """
            SELECT
                user_id,
                handle
            FROM user_handle
            WHERE guild_id = ? AND active = 1
        """
        cursor = await self.conn.execute(query, (guild_id,))
        res = await cursor.fetchall()
        return [(int(user_id), handle) for user_id, handle in res]

    async def get_cf_users_for_guild(self, guild_id: int) -> list[Any]:
        query = """
            SELECT
                u.user_id, c.handle, c.first_name, c.last_name, c.country,
                c.city, c.organization, c.contribution, c.rating, c.maxRating,
                c.last_online_time, c.registration_time, c.friend_of_count,
                c.title_photo
            FROM user_handle AS u
            LEFT JOIN cf_user_cache AS c
            ON u.handle = c.handle
            WHERE u.guild_id = ? AND u.active = 1
        """
        cursor = await self.conn.execute(query, (guild_id,))
        res = await cursor.fetchall()
        return [(int(t[0]), cf.User._make(t[1:])) for t in res]

    async def get_reminder_settings(self, guild_id: int) -> Any:
        query = """
            SELECT channel_id, role_id, before
            FROM reminder
            WHERE guild_id = ?
        """
        cursor = await self.conn.execute(query, (guild_id,))
        return await cursor.fetchone()

    async def set_reminder_settings(
        self, guild_id: int, channel_id: int, role_id: int, before: str
    ) -> None:
        query = """
            INSERT OR REPLACE INTO reminder (guild_id, channel_id, role_id, before)
            VALUES (?, ?, ?, ?)
        """
        await self.conn.execute(query, (guild_id, channel_id, role_id, before))
        await self.conn.commit()

    async def clear_reminder_settings(self, guild_id: int) -> None:
        query = """
            DELETE FROM reminder WHERE guild_id = ?
        """
        await self.conn.execute(query, (guild_id,))
        await self.conn.commit()

    async def get_starboard_entry(
        self, guild_id: str, emoji: str
    ) -> tuple[int, int, int] | None:
        cursor = await self.conn.execute(
            """
            SELECT channel_id
            FROM starboard_config_v1 WHERE guild_id=? AND emoji=?
            """,
            (guild_id, emoji),
        )
        cfg = await cursor.fetchone()
        if not cfg:
            return None
        cursor = await self.conn.execute(
            """
            SELECT threshold, color
            FROM starboard_emoji_v1 WHERE guild_id=? AND emoji=?
            """,
            (guild_id, emoji),
        )
        emo = await cursor.fetchone()
        return (int(cfg[0]), int(emo[0]), int(emo[1]))

    async def add_starboard_emoji(
        self, guild_id: str, emoji: str, threshold: int, color: int
    ) -> int:
        return await self._insert_one(
            'starboard_emoji_v1',
            ('guild_id', 'emoji', 'threshold', 'color'),
            (guild_id, emoji, threshold, color),
        )

    async def remove_starboard_emoji(self, guild_id: str, emoji: str) -> int:
        cursor = await self.conn.execute(
            """
            DELETE FROM starboard_emoji_v1
            WHERE guild_id = ? AND emoji = ?
            """,
            (guild_id, emoji),
        )
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def update_starboard_threshold(
        self, guild_id: str, emoji: str, threshold: int
    ) -> int:
        cursor = await self.conn.execute(
            """
            UPDATE starboard_emoji_v1
            SET threshold=?
            WHERE guild_id=? AND emoji=?
            """,
            (threshold, guild_id, emoji),
        )
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def update_starboard_color(
        self, guild_id: str, emoji: str, color: int
    ) -> int:
        cursor = await self.conn.execute(
            """
            UPDATE starboard_emoji_v1
            SET color=?
            WHERE guild_id=? AND emoji=?
            """,
            (color, guild_id, emoji),
        )
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def set_starboard_channel(
        self, guild_id: str, emoji: str, channel_id: str
    ) -> int:
        return await self._insert_one(
            'starboard_config_v1',
            ('guild_id', 'emoji', 'channel_id'),
            (guild_id, emoji, channel_id),
        )

    async def clear_starboard_channel(self, guild_id: str, emoji: str) -> int:
        cursor = await self.conn.execute(
            """
            DELETE FROM starboard_config_v1
            WHERE guild_id = ? AND emoji = ?
            """,
            (guild_id, emoji),
        )
        rc = cursor.rowcount
        await self.conn.commit()
        return rc

    async def add_starboard_message(
        self,
        original_msg_id: str,
        starboard_msg_id: str,
        guild_id: str,
        emoji: str,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO
                starboard_message_v1
                (original_msg_id, starboard_msg_id, guild_id, emoji)
            VALUES (?,?,?,?)
            """,
            (original_msg_id, starboard_msg_id, guild_id, emoji),
        )
        await self.conn.commit()

    async def check_exists_starboard_message(
        self, original_msg_id: str, emoji: str
    ) -> bool:
        cursor = await self.conn.execute(
            """
            SELECT 1 AS x
            FROM starboard_message_v1
            WHERE original_msg_id = ? AND emoji = ?
            """,
            (original_msg_id, emoji),
        )
        row = await cursor.fetchone()
        return bool(row)

    async def remove_starboard_message(
        self,
        *,
        original_msg_id: str | None = None,
        emoji: str | None = None,
        starboard_msg_id: str | None = None,
    ) -> int:
        if original_msg_id is not None and emoji is not None:
            cursor = await self.conn.execute(
                """
                DELETE FROM starboard_message_v1
                WHERE original_msg_id = ? AND emoji = ?
                """,
                (original_msg_id, emoji),
            )
            rc = cursor.rowcount
        elif starboard_msg_id is not None:
            cursor = await self.conn.execute(
                """
                DELETE FROM starboard_message_v1
                WHERE starboard_msg_id = ?
                """,
                (starboard_msg_id,),
            )
            rc = cursor.rowcount
        else:
            rc = 0
        await self.conn.commit()
        return rc

    async def check_duel_challenge(self, userid: int) -> Any:
        query = """
            SELECT id FROM duel
            WHERE
                (challengee = ? OR challenger = ?)
                AND (status == ? OR status == ?)
        """
        cursor = await self.conn.execute(
            query, (userid, userid, Duel.ONGOING, Duel.PENDING)
        )
        return await cursor.fetchone()

    async def check_duel_accept(self, challengee: int) -> Any:
        query = """
            SELECT id, challenger, problem_name FROM duel
            WHERE challengee = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (challengee, Duel.PENDING))
        return await cursor.fetchone()

    async def check_duel_decline(self, challengee: int) -> Any:
        query = """
            SELECT id, challenger FROM duel
            WHERE challengee = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (challengee, Duel.PENDING))
        return await cursor.fetchone()

    async def check_duel_withdraw(self, challenger: int) -> Any:
        query = """
            SELECT id, challengee FROM duel
            WHERE challenger = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (challenger, Duel.PENDING))
        return await cursor.fetchone()

    async def check_duel_draw(self, userid: int) -> Any:
        query = """
            SELECT id, challenger, challengee, start_time, type FROM duel
            WHERE (challenger = ? OR challengee = ?) AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, userid, Duel.ONGOING))
        return await cursor.fetchone()

    async def check_duel_complete(self, userid: int) -> Any:
        query = """
            SELECT
                id, challenger, challengee, start_time, problem_name,
                contest_id, p_index, type FROM duel
            WHERE (challenger = ? OR challengee = ?) AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, userid, Duel.ONGOING))
        return await cursor.fetchone()

    async def create_duel(
        self,
        challenger: int,
        challengee: int,
        issue_time: float,
        prob: Any,
        dtype: int,
    ) -> int | None:
        query = """
            INSERT INTO duel (
                challenger, challengee, issue_time, problem_name, contest_id,
                p_index, status, type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.execute(
            query,
            (
                challenger,
                challengee,
                issue_time,
                prob.name,
                prob.contestId,
                prob.index,
                Duel.PENDING,
                dtype,
            ),
        )
        duelid = cursor.lastrowid
        await self.conn.commit()
        return duelid

    async def cancel_duel(self, duelid: int, status: int) -> int:
        query = """
            UPDATE duel SET status = ? WHERE id = ? AND status = ?
        """
        cursor = await self.conn.execute(query, (status, duelid, Duel.PENDING))
        rc = cursor.rowcount
        if rc != 1:
            await self.conn.rollback()
            return 0
        await self.conn.commit()
        return rc

    async def invalidate_duel(self, duelid: int) -> int:
        query = """
            UPDATE duel SET status = ?
            WHERE id = ? AND status = ?
        """
        cursor = await self.conn.execute(query, (Duel.INVALID, duelid, Duel.ONGOING))
        rc = cursor.rowcount
        if rc != 1:
            await self.conn.rollback()
            return 0
        await self.conn.commit()
        return rc

    async def start_duel(self, duelid: int, start_time: float) -> int:
        query = """
            UPDATE duel SET start_time = ?, status = ?
            WHERE id = ? AND status = ?
        """
        cursor = await self.conn.execute(
            query, (start_time, Duel.ONGOING, duelid, Duel.PENDING)
        )
        rc = cursor.rowcount
        if rc != 1:
            await self.conn.rollback()
            return 0
        await self.conn.commit()
        return rc

    async def complete_duel(
        self,
        duelid: int,
        winner: int,
        finish_time: float,
        winner_id: int = -1,
        loser_id: int = -1,
        delta: int = 0,
        dtype: int = DuelType.OFFICIAL,
    ) -> int:
        query = """
            UPDATE duel SET status = ?, finish_time = ?, winner = ?
            WHERE id = ? AND status = ?
        """
        cursor = await self.conn.execute(
            query, (Duel.COMPLETE, finish_time, winner, duelid, Duel.ONGOING)
        )
        if cursor.rowcount != 1:
            await self.conn.rollback()
            return 0

        if dtype == DuelType.OFFICIAL:
            await self.update_duel_rating(winner_id, +delta)
            await self.update_duel_rating(loser_id, -delta)

        await self.conn.commit()
        return 1

    async def update_duel_rating(self, userid: int, delta: int) -> int:
        query = """
            UPDATE duelist SET rating = rating + ? WHERE user_id = ?
        """
        cursor = await self.conn.execute(query, (delta, userid))
        await self.conn.commit()
        return cursor.rowcount

    async def get_duel_wins(self, userid: int) -> list[Any]:
        query = """
            SELECT
                start_time, finish_time, problem_name, challenger, challengee FROM duel
            WHERE (
                (challenger = ? AND winner == ?)
                OR (challengee = ? AND winner == ?)
            ) AND status = ?
        """
        cursor = await self.conn.execute(
            query, (userid, Winner.CHALLENGER, userid, Winner.CHALLENGEE, Duel.COMPLETE)
        )
        return await cursor.fetchall()

    async def get_duels(self, userid: int) -> list[Any]:
        query = """
            SELECT
                id, start_time, finish_time, problem_name, challenger,
                challengee, winner
            FROM duel
            WHERE (challengee = ? OR challenger = ?) AND status == ?
            ORDER BY start_time DESC
        """
        cursor = await self.conn.execute(query, (userid, userid, Duel.COMPLETE))
        return await cursor.fetchall()

    async def get_duel_problem_names(self, userid: int) -> list[Any]:
        query = """
            SELECT problem_name
            FROM duel
            WHERE
                (challengee = ? OR challenger = ?)
                AND (status == ? OR status == ?)
        """
        cursor = await self.conn.execute(
            query, (userid, userid, Duel.COMPLETE, Duel.INVALID)
        )
        return await cursor.fetchall()

    async def get_pair_duels(self, userid1: int, userid2: int) -> list[Any]:
        query = """
            SELECT
                id, start_time, finish_time, problem_name, challenger,
                challengee, winner FROM duel
            WHERE (
                (challenger = ? AND challengee = ?)
                OR (challenger = ? AND challengee = ?)
            ) AND status == ?
            ORDER BY start_time DESC
        """
        cursor = await self.conn.execute(
            query, (userid1, userid2, userid2, userid1, Duel.COMPLETE)
        )
        return await cursor.fetchall()

    async def get_recent_duels(self) -> list[Any]:
        query = """
            SELECT
                id, start_time, finish_time, problem_name, challenger,
                challengee, winner
            FROM duel
            WHERE status == ?
            ORDER BY start_time DESC
            LIMIT 7
        """
        cursor = await self.conn.execute(query, (Duel.COMPLETE,))
        return await cursor.fetchall()

    async def get_ongoing_duels(self) -> list[Any]:
        query = """
            SELECT start_time, problem_name, challenger, challengee
            FROM duel
            WHERE status == ? ORDER BY start_time DESC
        """
        cursor = await self.conn.execute(query, (Duel.ONGOING,))
        return await cursor.fetchall()

    async def get_num_duel_completed(self, userid: int) -> int:
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE (challengee = ? OR challenger = ?) AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, userid, Duel.COMPLETE))
        return (await cursor.fetchone())[0]

    async def get_num_duel_draws(self, userid: int) -> int:
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE (challengee = ? OR challenger = ?) AND winner == ?
        """
        cursor = await self.conn.execute(query, (userid, userid, Winner.DRAW))
        return (await cursor.fetchone())[0]

    async def get_num_duel_losses(self, userid: int) -> int:
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE (
                (challengee = ? AND winner == ?)
                OR (challenger = ? AND winner == ?)
            ) AND status = ?
        """
        cursor = await self.conn.execute(
            query,
            (userid, Winner.CHALLENGER, userid, Winner.CHALLENGEE, Duel.COMPLETE),
        )
        return (await cursor.fetchone())[0]

    async def get_num_duel_declined(self, userid: int) -> int:
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE challengee = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, Duel.DECLINED))
        return (await cursor.fetchone())[0]

    async def get_num_duel_rdeclined(self, userid: int) -> int:
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE challenger = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, Duel.DECLINED))
        return (await cursor.fetchone())[0]

    async def get_duel_rating(self, userid: int) -> int:
        query = """
            SELECT rating
            FROM duelist
            WHERE user_id = ?
        """
        cursor = await self.conn.execute(query, (userid,))
        return (await cursor.fetchone())[0]

    async def is_duelist(self, userid: int) -> Any:
        query = """
            SELECT 1 AS x
            FROM duelist
            WHERE user_id = ?
        """
        cursor = await self.conn.execute(query, (userid,))
        return await cursor.fetchone()

    async def register_duelist(self, userid: int) -> int:
        query = """
            INSERT OR IGNORE INTO duelist (user_id, rating)
            VALUES (?, 1500)
        """
        cursor = await self.conn.execute(query, (userid,))
        await self.conn.commit()
        return cursor.rowcount

    async def get_duelists(self) -> list[Any]:
        query = """
            SELECT user_id, rating
            FROM duelist
            ORDER BY rating DESC
        """
        cursor = await self.conn.execute(query)
        return await cursor.fetchall()

    async def get_complete_official_duels(self) -> list[Any]:
        query = """
            SELECT challenger, challengee, winner, finish_time
            FROM duel
            WHERE
                status=? AND type=?
            ORDER BY finish_time ASC
        """
        cursor = await self.conn.execute(query, (Duel.COMPLETE, DuelType.OFFICIAL))
        return await cursor.fetchall()

    async def get_rankup_channel(self, guild_id: int) -> int | None:
        query = 'SELECT channel_id FROM rankup WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        channel_id = await cursor.fetchone()
        return int(channel_id[0]) if channel_id else None

    async def set_rankup_channel(self, guild_id: int, channel_id: int) -> None:
        query = 'INSERT OR REPLACE INTO rankup (guild_id, channel_id) VALUES (?, ?)'
        await self.conn.execute(query, (guild_id, channel_id))
        await self.conn.commit()

    async def clear_rankup_channel(self, guild_id: int) -> int:
        query = 'DELETE FROM rankup WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        await self.conn.commit()
        return cursor.rowcount

    async def enable_auto_role_update(self, guild_id: int) -> int:
        query = 'INSERT OR REPLACE INTO auto_role_update (guild_id) VALUES (?)'
        cursor = await self.conn.execute(query, (guild_id,))
        await self.conn.commit()
        return cursor.rowcount

    async def disable_auto_role_update(self, guild_id: int) -> int:
        query = 'DELETE FROM auto_role_update WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        await self.conn.commit()
        return cursor.rowcount

    async def has_auto_role_update_enabled(self, guild_id: int) -> bool:
        query = 'SELECT 1 AS x FROM auto_role_update WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        return await cursor.fetchone() is not None

    async def reset_status(self, id: int) -> None:
        inactive_query = """
            UPDATE user_handle
            SET active = 0
            WHERE guild_id = ?
        """
        await self.conn.execute(inactive_query, (id,))
        await self.conn.commit()

    async def update_status(self, guild_id: str, active_ids: list[str]) -> int:
        placeholders = ', '.join(['?'] * len(active_ids))
        if not active_ids:
            return 0
        active_query = """
            UPDATE user_handle
            SET active = 1
            WHERE user_id IN ({})
            AND guild_id = ?
        """.format(placeholders)
        cursor = await self.conn.execute(active_query, (*active_ids, guild_id))
        await self.conn.commit()
        return cursor.rowcount

    # Rated VC stuff

    async def create_rated_vc(
        self,
        contest_id: int,
        start_time: float,
        finish_time: float,
        guild_id: str,
        user_ids: list[str],
    ) -> int | None:
        """Creates a rated vc and returns its id."""
        query = """
            INSERT INTO rated_vcs (
                contest_id, start_time, finish_time, status, guild_id
            ) VALUES ( ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.execute(
            query, (contest_id, start_time, finish_time, RatedVC.ONGOING, guild_id)
        )
        vc_id = cursor.lastrowid
        for user_id in user_ids:
            query = 'INSERT INTO rated_vc_users (vc_id, user_id) VALUES (? , ?)'
            await self.conn.execute(query, (vc_id, user_id))
        await self.conn.commit()
        return vc_id

    async def get_rated_vc(self, vc_id: int) -> Any:
        query = 'SELECT * FROM rated_vcs WHERE id = ? '
        return await self._fetchone(
            query, params=(vc_id,), row_factory=namedtuple_factory
        )

    async def get_ongoing_rated_vc_ids(self) -> list[int]:
        query = 'SELECT id FROM rated_vcs WHERE status = ? '
        vcs = await self._fetchall(
            query, params=(RatedVC.ONGOING,), row_factory=namedtuple_factory
        )
        vc_ids = [vc.id for vc in vcs]
        return vc_ids

    async def get_rated_vc_user_ids(self, vc_id: int) -> list[str]:
        query = 'SELECT user_id FROM rated_vc_users WHERE vc_id = ? '
        users = await self._fetchall(
            query, params=(vc_id,), row_factory=namedtuple_factory
        )
        user_ids = [user.user_id for user in users]
        return user_ids

    async def finish_rated_vc(self, vc_id: int) -> None:
        query = 'UPDATE rated_vcs SET status = ? WHERE id = ? '
        await self.conn.execute(query, (RatedVC.FINISHED, vc_id))
        await self.conn.commit()

    async def update_vc_rating(self, vc_id: int, user_id: str, rating: int) -> None:
        query = """
            INSERT OR REPLACE INTO rated_vc_users (vc_id, user_id, rating)
            VALUES (?, ?, ?)
        """
        await self.conn.execute(query, (vc_id, user_id, rating))
        await self.conn.commit()

    async def get_vc_rating(
        self, user_id: str, default_if_not_exist: bool = True
    ) -> int | None:
        query = """
            SELECT
                MAX(vc_id) AS latest_vc_id,
                rating
            FROM rated_vc_users
            WHERE user_id = ? AND rating IS NOT NULL
        """
        row = await self._fetchone(
            query, params=(user_id,), row_factory=namedtuple_factory
        )
        rating = row.rating
        if rating is None:
            if default_if_not_exist:
                return _DEFAULT_VC_RATING
            return None
        return rating

    async def get_vc_rating_history(self, user_id: str) -> list[Any]:
        """Return [vc_id, rating]."""
        query = """
            SELECT
                vc_id,
                rating
            FROM rated_vc_users
            WHERE user_id = ? AND rating IS NOT NULL
        """
        ratings = await self._fetchall(
            query, params=(user_id,), row_factory=namedtuple_factory
        )
        return ratings

    async def set_rated_vc_channel(self, guild_id: int, channel_id: int) -> None:
        query = """
            INSERT OR REPLACE INTO rated_vc_settings (guild_id, channel_id)
            VALUES (?, ?)
        """
        await self.conn.execute(query, (guild_id, channel_id))
        await self.conn.commit()

    async def get_rated_vc_channel(self, guild_id: int) -> int | None:
        query = 'SELECT channel_id FROM rated_vc_settings WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        channel_id = await cursor.fetchone()
        return int(channel_id[0]) if channel_id else None

    async def remove_last_ratedvc_participation(self, user_id: str) -> int:
        query = 'SELECT MAX(vc_id) AS vc_id FROM rated_vc_users WHERE user_id = ? '
        row = await self._fetchone(
            query, params=(user_id,), row_factory=namedtuple_factory
        )
        vc_id = row.vc_id
        query = 'DELETE FROM rated_vc_users WHERE user_id = ? AND vc_id = ? '
        cursor = await self.conn.execute(query, (user_id, vc_id))
        await self.conn.commit()
        return cursor.rowcount

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
