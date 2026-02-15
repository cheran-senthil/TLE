from collections import namedtuple
from enum import IntEnum

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
    def __getattribute__(self, item):
        raise DatabaseDisabledError


class UniqueConstraintFailed(UserDbError):
    pass


def namedtuple_factory(cursor, row):
    """Returns sqlite rows as named tuples."""
    fields = [col[0] for col in cursor.description]
    for f in fields:
        if not f.isidentifier():
            raise ValueError(f'Column name {f!r} is not a valid identifier')
    Row = namedtuple('Row', fields)
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
    def __init__(self, dbfile):
        self.db_file = dbfile
        self.conn = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.db_file)
        self.conn.row_factory = namedtuple_factory
        await self.create_tables()

    async def create_tables(self):
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

    async def _insert_one(self, table: str, columns, values: tuple):
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

    async def _insert_many(self, table: str, columns, values: list):
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

    async def _fetchone(self, query: str, params=None, row_factory=None):
        cursor = await self.conn.execute(query, params or ())
        if row_factory:
            cursor.row_factory = row_factory
        return await cursor.fetchone()

    async def _fetchall(self, query: str, params=None, row_factory=None):
        cursor = await self.conn.execute(query, params or ())
        if row_factory:
            cursor.row_factory = row_factory
        return await cursor.fetchall()

    async def new_challenge(self, user_id, issue_time, prob, delta):
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

    async def check_challenge(self, user_id):
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

    async def get_gudgitters(self):
        query = """
            SELECT
                user_id,
                score
            FROM user_challenge
        """
        cursor = await self.conn.execute(query)
        return await cursor.fetchall()

    async def howgud(self, user_id):
        query = """
            SELECT rating_delta FROM challenge
            WHERE user_id = ? AND finish_time IS NOT NULL
        """
        cursor = await self.conn.execute(query, (user_id,))
        return await cursor.fetchall()

    async def get_noguds(self, user_id):
        query = """
            SELECT problem_name FROM challenge
            WHERE user_id = ? AND status = ?
        """
        cursor = await self.conn.execute(query, (user_id, Gitgud.NOGUD))
        return {name for (name,) in await cursor.fetchall()}

    async def gitlog(self, user_id):
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

    async def complete_challenge(self, user_id, challenge_id, finish_time, delta):
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

    async def skip_challenge(self, user_id, challenge_id, status):
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

    async def cache_cf_user(self, user):
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

    async def fetch_cf_user(self, handle):
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

    async def set_handle(self, user_id, guild_id, handle):
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

    async def set_inactive(self, guild_id_user_id_pairs):
        query = """
            UPDATE user_handle SET active = 0
            WHERE guild_id = ? AND user_id = ?
        """
        cursor = await self.conn.executemany(query, guild_id_user_id_pairs)
        await self.conn.commit()
        return cursor.rowcount

    async def get_handle(self, user_id, guild_id):
        query = """
            SELECT handle FROM user_handle
            WHERE user_id = ? AND guild_id = ?
        """
        cursor = await self.conn.execute(query, (user_id, guild_id))
        res = await cursor.fetchone()
        return res[0] if res else None

    async def get_user_id(self, handle, guild_id):
        query = """
            SELECT user_id FROM user_handle
            WHERE UPPER(handle) = UPPER(?) AND guild_id = ?
        """
        cursor = await self.conn.execute(query, (handle, guild_id))
        res = await cursor.fetchone()
        return int(res[0]) if res else None

    async def remove_handle(self, handle, guild_id):
        query = """
            DELETE FROM user_handle
            WHERE UPPER(handle) = UPPER(?) AND guild_id = ?
        """
        cursor = await self.conn.execute(query, (handle, guild_id))
        await self.conn.commit()
        return cursor.rowcount

    async def get_handles_for_guild(self, guild_id):
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

    async def get_cf_users_for_guild(self, guild_id):
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

    async def get_reminder_settings(self, guild_id):
        query = """
            SELECT channel_id, role_id, before
            FROM reminder
            WHERE guild_id = ?
        """
        cursor = await self.conn.execute(query, (guild_id,))
        return await cursor.fetchone()

    async def set_reminder_settings(self, guild_id, channel_id, role_id, before):
        query = """
            INSERT OR REPLACE INTO reminder (guild_id, channel_id, role_id, before)
            VALUES (?, ?, ?, ?)
        """
        await self.conn.execute(query, (guild_id, channel_id, role_id, before))
        await self.conn.commit()

    async def clear_reminder_settings(self, guild_id):
        query = """
            DELETE FROM reminder WHERE guild_id = ?
        """
        await self.conn.execute(query, (guild_id,))
        await self.conn.commit()

    async def get_starboard_entry(self, guild_id, emoji):
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

    async def add_starboard_emoji(self, guild_id, emoji, threshold, color):
        return await self._insert_one(
            'starboard_emoji_v1',
            ('guild_id', 'emoji', 'threshold', 'color'),
            (guild_id, emoji, threshold, color),
        )

    async def remove_starboard_emoji(self, guild_id, emoji):
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

    async def update_starboard_threshold(self, guild_id, emoji, threshold):
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

    async def update_starboard_color(self, guild_id, emoji, color):
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

    async def set_starboard_channel(self, guild_id, emoji, channel_id):
        return await self._insert_one(
            'starboard_config_v1',
            ('guild_id', 'emoji', 'channel_id'),
            (guild_id, emoji, channel_id),
        )

    async def clear_starboard_channel(self, guild_id, emoji):
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
        self, original_msg_id, starboard_msg_id, guild_id, emoji
    ):
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

    async def check_exists_starboard_message(self, original_msg_id, emoji):
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
        self, *, original_msg_id=None, emoji=None, starboard_msg_id=None
    ):
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

    async def check_duel_challenge(self, userid):
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

    async def check_duel_accept(self, challengee):
        query = """
            SELECT id, challenger, problem_name FROM duel
            WHERE challengee = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (challengee, Duel.PENDING))
        return await cursor.fetchone()

    async def check_duel_decline(self, challengee):
        query = """
            SELECT id, challenger FROM duel
            WHERE challengee = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (challengee, Duel.PENDING))
        return await cursor.fetchone()

    async def check_duel_withdraw(self, challenger):
        query = """
            SELECT id, challengee FROM duel
            WHERE challenger = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (challenger, Duel.PENDING))
        return await cursor.fetchone()

    async def check_duel_draw(self, userid):
        query = """
            SELECT id, challenger, challengee, start_time, type FROM duel
            WHERE (challenger = ? OR challengee = ?) AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, userid, Duel.ONGOING))
        return await cursor.fetchone()

    async def check_duel_complete(self, userid):
        query = """
            SELECT
                id, challenger, challengee, start_time, problem_name,
                contest_id, p_index, type FROM duel
            WHERE (challenger = ? OR challengee = ?) AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, userid, Duel.ONGOING))
        return await cursor.fetchone()

    async def create_duel(self, challenger, challengee, issue_time, prob, dtype):
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

    async def cancel_duel(self, duelid, status):
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

    async def invalidate_duel(self, duelid):
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

    async def start_duel(self, duelid, start_time):
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
        duelid,
        winner,
        finish_time,
        winner_id=-1,
        loser_id=-1,
        delta=0,
        dtype=DuelType.OFFICIAL,
    ):
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

    async def update_duel_rating(self, userid, delta):
        query = """
            UPDATE duelist SET rating = rating + ? WHERE user_id = ?
        """
        cursor = await self.conn.execute(query, (delta, userid))
        await self.conn.commit()
        return cursor.rowcount

    async def get_duel_wins(self, userid):
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

    async def get_duels(self, userid):
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

    async def get_duel_problem_names(self, userid):
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

    async def get_pair_duels(self, userid1, userid2):
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

    async def get_recent_duels(self):
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

    async def get_ongoing_duels(self):
        query = """
            SELECT start_time, problem_name, challenger, challengee
            FROM duel
            WHERE status == ? ORDER BY start_time DESC
        """
        cursor = await self.conn.execute(query, (Duel.ONGOING,))
        return await cursor.fetchall()

    async def get_num_duel_completed(self, userid):
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE (challengee = ? OR challenger = ?) AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, userid, Duel.COMPLETE))
        return (await cursor.fetchone())[0]

    async def get_num_duel_draws(self, userid):
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE (challengee = ? OR challenger = ?) AND winner == ?
        """
        cursor = await self.conn.execute(query, (userid, userid, Winner.DRAW))
        return (await cursor.fetchone())[0]

    async def get_num_duel_losses(self, userid):
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

    async def get_num_duel_declined(self, userid):
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE challengee = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, Duel.DECLINED))
        return (await cursor.fetchone())[0]

    async def get_num_duel_rdeclined(self, userid):
        query = """
            SELECT COUNT(*) AS cnt
            FROM duel
            WHERE challenger = ? AND status == ?
        """
        cursor = await self.conn.execute(query, (userid, Duel.DECLINED))
        return (await cursor.fetchone())[0]

    async def get_duel_rating(self, userid):
        query = """
            SELECT rating
            FROM duelist
            WHERE user_id = ?
        """
        cursor = await self.conn.execute(query, (userid,))
        return (await cursor.fetchone())[0]

    async def is_duelist(self, userid):
        query = """
            SELECT 1 AS x
            FROM duelist
            WHERE user_id = ?
        """
        cursor = await self.conn.execute(query, (userid,))
        return await cursor.fetchone()

    async def register_duelist(self, userid):
        query = """
            INSERT OR IGNORE INTO duelist (user_id, rating)
            VALUES (?, 1500)
        """
        cursor = await self.conn.execute(query, (userid,))
        await self.conn.commit()
        return cursor.rowcount

    async def get_duelists(self):
        query = """
            SELECT user_id, rating
            FROM duelist
            ORDER BY rating DESC
        """
        cursor = await self.conn.execute(query)
        return await cursor.fetchall()

    async def get_complete_official_duels(self):
        query = """
            SELECT challenger, challengee, winner, finish_time
            FROM duel
            WHERE
                status=? AND type=?
            ORDER BY finish_time ASC
        """
        cursor = await self.conn.execute(query, (Duel.COMPLETE, DuelType.OFFICIAL))
        return await cursor.fetchall()

    async def get_rankup_channel(self, guild_id):
        query = 'SELECT channel_id FROM rankup WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        channel_id = await cursor.fetchone()
        return int(channel_id[0]) if channel_id else None

    async def set_rankup_channel(self, guild_id, channel_id):
        query = 'INSERT OR REPLACE INTO rankup (guild_id, channel_id) VALUES (?, ?)'
        await self.conn.execute(query, (guild_id, channel_id))
        await self.conn.commit()

    async def clear_rankup_channel(self, guild_id):
        query = 'DELETE FROM rankup WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        await self.conn.commit()
        return cursor.rowcount

    async def enable_auto_role_update(self, guild_id):
        query = 'INSERT OR REPLACE INTO auto_role_update (guild_id) VALUES (?)'
        cursor = await self.conn.execute(query, (guild_id,))
        await self.conn.commit()
        return cursor.rowcount

    async def disable_auto_role_update(self, guild_id):
        query = 'DELETE FROM auto_role_update WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        await self.conn.commit()
        return cursor.rowcount

    async def has_auto_role_update_enabled(self, guild_id):
        query = 'SELECT 1 AS x FROM auto_role_update WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        return await cursor.fetchone() is not None

    async def reset_status(self, id):
        inactive_query = """
            UPDATE user_handle
            SET active = 0
            WHERE guild_id = ?
        """
        await self.conn.execute(inactive_query, (id,))
        await self.conn.commit()

    async def update_status(self, guild_id: str, active_ids: list):
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
        user_ids: [str],
    ):
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

    async def get_rated_vc(self, vc_id: int):
        query = 'SELECT * FROM rated_vcs WHERE id = ? '
        return await self._fetchone(
            query, params=(vc_id,), row_factory=namedtuple_factory
        )

    async def get_ongoing_rated_vc_ids(self):
        query = 'SELECT id FROM rated_vcs WHERE status = ? '
        vcs = await self._fetchall(
            query, params=(RatedVC.ONGOING,), row_factory=namedtuple_factory
        )
        vc_ids = [vc.id for vc in vcs]
        return vc_ids

    async def get_rated_vc_user_ids(self, vc_id: int):
        query = 'SELECT user_id FROM rated_vc_users WHERE vc_id = ? '
        users = await self._fetchall(
            query, params=(vc_id,), row_factory=namedtuple_factory
        )
        user_ids = [user.user_id for user in users]
        return user_ids

    async def finish_rated_vc(self, vc_id: int):
        query = 'UPDATE rated_vcs SET status = ? WHERE id = ? '
        await self.conn.execute(query, (RatedVC.FINISHED, vc_id))
        await self.conn.commit()

    async def update_vc_rating(self, vc_id: int, user_id: str, rating: int):
        query = """
            INSERT OR REPLACE INTO rated_vc_users (vc_id, user_id, rating)
            VALUES (?, ?, ?)
        """
        await self.conn.execute(query, (vc_id, user_id, rating))
        await self.conn.commit()

    async def get_vc_rating(self, user_id: str, default_if_not_exist: bool = True):
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

    async def get_vc_rating_history(self, user_id: str):
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

    async def set_rated_vc_channel(self, guild_id, channel_id):
        query = """
            INSERT OR REPLACE INTO rated_vc_settings (guild_id, channel_id)
            VALUES (?, ?)
        """
        await self.conn.execute(query, (guild_id, channel_id))
        await self.conn.commit()

    async def get_rated_vc_channel(self, guild_id):
        query = 'SELECT channel_id FROM rated_vc_settings WHERE guild_id = ?'
        cursor = await self.conn.execute(query, (guild_id,))
        channel_id = await cursor.fetchone()
        return int(channel_id[0]) if channel_id else None

    async def remove_last_ratedvc_participation(self, user_id: str):
        query = 'SELECT MAX(vc_id) AS vc_id FROM rated_vc_users WHERE user_id = ? '
        row = await self._fetchone(
            query, params=(user_id,), row_factory=namedtuple_factory
        )
        vc_id = row.vc_id
        query = 'DELETE FROM rated_vc_users WHERE user_id = ? AND vc_id = ? '
        cursor = await self.conn.execute(query, (user_id, vc_id))
        await self.conn.commit()
        return cursor.rowcount

    async def close(self):
        if self.conn:
            await self.conn.close()
