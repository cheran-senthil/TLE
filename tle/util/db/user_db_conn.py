import sqlite3
from enum import IntEnum
from collections import namedtuple

from discord.ext import commands

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
    fields = [col[0] for col in cursor.description if col[0].isidentifier()]
    Row = namedtuple("Row", fields)
    return Row(*row)


class UserDbConn:
    def __init__(self, dbfile):
        self.conn = sqlite3.connect(dbfile)
        self.conn.row_factory = namedtuple_factory
        self.create_tables()

    def create_tables(self):
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS user_handle ('
            'user_id     TEXT,'
            'guild_id    TEXT,'
            'handle      TEXT,'
            'active      INTEGER,'
            'PRIMARY KEY (user_id, guild_id)'
            ')'
        )
        self.conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_user_handle_guild_handle '
                          'ON user_handle (guild_id, handle)')
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS cf_user_cache ('
            'handle              TEXT PRIMARY KEY,'
            'first_name          TEXT,'
            'last_name           TEXT,'
            'country             TEXT,'
            'city                TEXT,'
            'organization        TEXT,'
            'contribution        INTEGER,'
            'rating              INTEGER,'
            'maxRating           INTEGER,'
            'last_online_time    INTEGER,'
            'registration_time   INTEGER,'
            'friend_of_count     INTEGER,'
            'title_photo         TEXT'
            ')'
        )
        # TODO: Make duel tables guild-aware.
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS duelist(
                "user_id"	INTEGER PRIMARY KEY NOT NULL,
                "rating"	INTEGER NOT NULL
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS duel(
                "id"	INTEGER PRIMARY KEY AUTOINCREMENT,
                "challenger"	INTEGER NOT NULL,
                "challengee"	INTEGER NOT NULL,
                "issue_time"	REAL NOT NULL,
                "start_time"	REAL,
                "finish_time"	REAL,
                "problem_name"	TEXT,
                "contest_id"	INTEGER,
                "p_index"	INTEGER,
                "status"	INTEGER,
                "winner"	INTEGER,
                "type"		INTEGER
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS "challenge" (
                "id"	INTEGER PRIMARY KEY AUTOINCREMENT,
                "user_id"	TEXT NOT NULL,
                "issue_time"	REAL NOT NULL,
                "finish_time"	REAL,
                "problem_name"	TEXT NOT NULL,
                "contest_id"	INTEGER NOT NULL,
                "p_index"	INTEGER NOT NULL,
                "rating_delta"	INTEGER NOT NULL,
                "status"	INTEGER NOT NULL
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS "user_challenge" (
                "user_id"	TEXT,
                "active_challenge_id"	INTEGER,
                "issue_time"	REAL,
                "score"	INTEGER NOT NULL,
                "num_completed"	INTEGER NOT NULL,
                "num_skipped"	INTEGER NOT NULL,
                PRIMARY KEY("user_id")
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS reminder (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT,
                role_id TEXT,
                before TEXT
            )
        ''')
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS starboard ('
            'guild_id     TEXT PRIMARY KEY,'
            'channel_id   TEXT'
            ')'
        )
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS starboard_message ('
            'original_msg_id    TEXT PRIMARY KEY,'
            'starboard_msg_id   TEXT,'
            'guild_id           TEXT'
            ')'
        )
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS rankup ('
            'guild_id     TEXT PRIMARY KEY,'
            'channel_id   TEXT'
            ')'
        )
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS auto_role_update ('
            'guild_id     TEXT PRIMARY KEY'
            ')'
        )

        # Rated VCs stuff:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS "rated_vcs" (
                "id"	         INTEGER PRIMARY KEY AUTOINCREMENT,
                "contest_id"     INTEGER NOT NULL,
                "start_time"     REAL,
                "finish_time"    REAL,
                "status"         INTEGER,
                "guild_id"       TEXT
            )
        ''')

        # TODO: Do we need to explicitly specify the fk constraint or just depend on the middleware?
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS "rated_vc_users" (
                "vc_id"	         INTEGER,
                "user_id"        TEXT NOT NULL,
                "rating"         INTEGER,

                CONSTRAINT fk_vc
                    FOREIGN KEY (vc_id)
                    REFERENCES rated_vcs(id),

                PRIMARY KEY(vc_id, user_id)
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS rated_vc_settings (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT
            )
        ''')


    # Helper functions.

    def _insert_one(self, table: str, columns, values: tuple):
        n = len(values)
        query = '''
            INSERT OR REPLACE INTO {} ({}) VALUES ({})
        '''.format(table, ', '.join(columns), ', '.join(['?'] * n))
        rc = self.conn.execute(query, values).rowcount
        self.conn.commit()
        return rc

    def _insert_many(self, table: str, columns, values: list):
        n = len(columns)
        query = '''
            INSERT OR REPLACE INTO {} ({}) VALUES ({})
        '''.format(table, ', '.join(columns), ', '.join(['?'] * n))
        rc = self.conn.executemany(query, values).rowcount
        self.conn.commit()
        return rc

    def _fetchone(self, query: str, params=None, row_factory=None):
        self.conn.row_factory = row_factory
        res = self.conn.execute(query, params).fetchone()
        self.conn.row_factory = None
        return res

    def _fetchall(self, query: str, params=None, row_factory=None):
        self.conn.row_factory = row_factory
        res = self.conn.execute(query, params).fetchall()
        self.conn.row_factory = None
        return res

    def new_challenge(self, user_id, issue_time, prob, delta):
        query1 = '''
            INSERT INTO challenge
            (user_id, issue_time, problem_name, contest_id, p_index, rating_delta, status)
            VALUES
            (?, ?, ?, ?, ?, ?, 1)
        '''
        query2 = '''
            INSERT OR IGNORE INTO user_challenge (user_id, score, num_completed, num_skipped)
            VALUES (?, 0, 0, 0)
        '''
        query3 = '''
            UPDATE user_challenge SET active_challenge_id = ?, issue_time = ?
            WHERE user_id = ? AND active_challenge_id IS NULL
        '''
        cur = self.conn.cursor()
        cur.execute(query1, (user_id, issue_time, prob.name, prob.contestId, prob.index, delta))
        last_id, rc = cur.lastrowid, cur.rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        cur.execute(query2, (user_id,))
        cur.execute(query3, (last_id, issue_time, user_id))
        if cur.rowcount != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return 1

    def check_challenge(self, user_id):
        query1 = '''
            SELECT active_challenge_id, issue_time FROM user_challenge
            WHERE user_id = ?
        '''
        res = self.conn.execute(query1, (user_id,)).fetchone()
        if res is None: return None
        c_id, issue_time = res
        query2 = '''
            SELECT problem_name, contest_id, p_index, rating_delta FROM challenge
            WHERE id = ?
        '''
        res = self.conn.execute(query2, (c_id,)).fetchone()
        if res is None: return None
        return c_id, issue_time, res[0], res[1], res[2], res[3]

    def get_gudgitters(self):
        query = '''
            SELECT user_id, score FROM user_challenge
        '''
        return self.conn.execute(query).fetchall()

    def howgud(self, user_id):
        query = '''
            SELECT rating_delta FROM challenge WHERE user_id = ? AND finish_time IS NOT NULL
        '''
        return self.conn.execute(query, (user_id,)).fetchall()

    def get_noguds(self, user_id):
        query = ('SELECT problem_name '
                 'FROM challenge '
                 f'WHERE user_id = ? AND status = {Gitgud.NOGUD}')
        return {name for name, in self.conn.execute(query, (user_id,)).fetchall()}

    def gitlog(self, user_id):
        query = f'''
            SELECT issue_time, finish_time, problem_name, contest_id, p_index, rating_delta, status
            FROM challenge WHERE user_id = ? AND status != {Gitgud.FORCED_NOGUD} ORDER BY issue_time DESC
        '''
        return self.conn.execute(query, (user_id,)).fetchall()

    def complete_challenge(self, user_id, challenge_id, finish_time, delta):
        query1 = f'''
            UPDATE challenge SET finish_time = ?, status = {Gitgud.GOTGUD}
            WHERE id = ? AND status = {Gitgud.GITGUD}
        '''
        query2 = '''
            UPDATE user_challenge SET score = score + ?, num_completed = num_completed + 1,
            active_challenge_id = NULL, issue_time = NULL
            WHERE user_id = ? AND active_challenge_id = ?
        '''
        rc = self.conn.execute(query1, (finish_time, challenge_id)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        rc = self.conn.execute(query2, (delta, user_id, challenge_id)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return 1

    def skip_challenge(self, user_id, challenge_id, status):
        query1 = '''
            UPDATE user_challenge SET active_challenge_id = NULL, issue_time = NULL
            WHERE user_id = ? AND active_challenge_id = ?
        '''
        query2 = f'''
            UPDATE challenge SET status = ? WHERE id = ? AND status = {Gitgud.GITGUD}
        '''
        rc = self.conn.execute(query1, (user_id, challenge_id)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        rc = self.conn.execute(query2, (status, challenge_id)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return 1

    def cache_cf_user(self, user):
        query = ('INSERT OR REPLACE INTO cf_user_cache '
                 '(handle, first_name, last_name, country, city, organization, contribution, '
                 '    rating, maxRating, last_online_time, registration_time, friend_of_count, title_photo) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
        with self.conn:
            return self.conn.execute(query, user).rowcount

    def fetch_cf_user(self, handle):
        query = ('SELECT handle, first_name, last_name, country, city, organization, contribution, '
                 '    rating, maxRating, last_online_time, registration_time, friend_of_count, title_photo '
                 'FROM cf_user_cache '
                 'WHERE UPPER(handle) = UPPER(?)')
        user = self.conn.execute(query, (handle,)).fetchone()
        return cf.User._make(user) if user else None

    def set_handle(self, user_id, guild_id, handle):
        query = ('SELECT user_id '
                 'FROM user_handle '
                 'WHERE guild_id = ? AND handle = ?')
        existing = self.conn.execute(query, (guild_id, handle)).fetchone()
        if existing and int(existing[0]) != user_id:
            raise UniqueConstraintFailed

        query = ('INSERT OR REPLACE INTO user_handle '
                 '(user_id, guild_id, handle, active) '
                 'VALUES (?, ?, ?, 1)')
        with self.conn:
            return self.conn.execute(query, (user_id, guild_id, handle)).rowcount

    def set_inactive(self, guild_id_user_id_pairs):
        query = ('UPDATE user_handle '
                 'SET active = 0 '
                 'WHERE guild_id = ? AND user_id = ?')
        with self.conn:
            return self.conn.executemany(query, guild_id_user_id_pairs).rowcount

    def get_handle(self, user_id, guild_id):
        query = ('SELECT handle '
                 'FROM user_handle '
                 'WHERE user_id = ? AND guild_id = ?')
        res = self.conn.execute(query, (user_id, guild_id)).fetchone()
        return res[0] if res else None

    def get_user_id(self, handle, guild_id):
        query = ('SELECT user_id '
                 'FROM user_handle '
                 'WHERE UPPER(handle) = UPPER(?) AND guild_id = ? AND active = 1')
        res = self.conn.execute(query, (handle, guild_id)).fetchone()
        return int(res[0]) if res else None

    def remove_handle(self, user_id, guild_id):
        query = ('DELETE FROM user_handle '
                 'WHERE user_id = ? AND guild_id = ?')
        with self.conn:
            return self.conn.execute(query, (user_id, guild_id)).rowcount

    def get_handles_for_guild(self, guild_id):
        query = ('SELECT user_id, handle '
                 'FROM user_handle '
                 'WHERE guild_id = ? AND active = 1')
        res = self.conn.execute(query, (guild_id,)).fetchall()
        return [(int(user_id), handle) for user_id, handle in res]

    def get_cf_users_for_guild(self, guild_id):
        query = ('SELECT u.user_id, c.handle, c.first_name, c.last_name, c.country, c.city, '
                 '    c.organization, c.contribution, c.rating, c.maxRating, c.last_online_time, '
                 '    c.registration_time, c.friend_of_count, c.title_photo '
                 'FROM user_handle AS u '
                 'LEFT JOIN cf_user_cache AS c '
                 'ON u.handle = c.handle '
                 'WHERE u.guild_id = ? AND u.active = 1')
        res = self.conn.execute(query, (guild_id,)).fetchall()
        return [(int(t[0]), cf.User._make(t[1:])) for t in res]

    def get_reminder_settings(self, guild_id):
        query = '''
            SELECT channel_id, role_id, before
            FROM reminder
            WHERE guild_id = ?
        '''
        return self.conn.execute(query, (guild_id,)).fetchone()

    def set_reminder_settings(self, guild_id, channel_id, role_id, before):
        query = '''
            INSERT OR REPLACE INTO reminder (guild_id, channel_id, role_id, before)
            VALUES (?, ?, ?, ?)
        '''
        self.conn.execute(query, (guild_id, channel_id, role_id, before))
        self.conn.commit()

    def clear_reminder_settings(self, guild_id):
        query = '''DELETE FROM reminder WHERE guild_id = ?'''
        self.conn.execute(query, (guild_id,))
        self.conn.commit()

    def get_starboard(self, guild_id):
        query = ('SELECT channel_id '
                 'FROM starboard '
                 'WHERE guild_id = ?')
        return self.conn.execute(query, (guild_id,)).fetchone()

    def set_starboard(self, guild_id, channel_id):
        query = ('INSERT OR REPLACE INTO starboard '
                 '(guild_id, channel_id) '
                 'VALUES (?, ?)')
        self.conn.execute(query, (guild_id, channel_id))
        self.conn.commit()

    def clear_starboard(self, guild_id):
        query = ('DELETE FROM starboard '
                 'WHERE guild_id = ?')
        self.conn.execute(query, (guild_id,))
        self.conn.commit()

    def add_starboard_message(self, original_msg_id, starboard_msg_id, guild_id):
        query = ('INSERT INTO starboard_message '
                 '(original_msg_id, starboard_msg_id, guild_id) '
                 'VALUES (?, ?, ?)')
        self.conn.execute(query, (original_msg_id, starboard_msg_id, guild_id))
        self.conn.commit()

    def check_exists_starboard_message(self, original_msg_id):
        query = ('SELECT 1 '
                 'FROM starboard_message '
                 'WHERE original_msg_id = ?')
        res = self.conn.execute(query, (original_msg_id,)).fetchone()
        return res is not None

    def remove_starboard_message(self, *, original_msg_id=None, starboard_msg_id=None):
        assert (original_msg_id is None) ^ (starboard_msg_id is None)
        if original_msg_id is not None:
            query = ('DELETE FROM starboard_message '
                     'WHERE original_msg_id = ?')
            rc = self.conn.execute(query, (original_msg_id,)).rowcount
        else:
            query = ('DELETE FROM starboard_message '
                     'WHERE starboard_msg_id = ?')
            rc = self.conn.execute(query, (starboard_msg_id,)).rowcount
        self.conn.commit()
        return rc

    def clear_starboard_messages_for_guild(self, guild_id):
        query = ('DELETE FROM starboard_message '
                 'WHERE guild_id = ?')
        rc = self.conn.execute(query, (guild_id,)).rowcount
        self.conn.commit()
        return rc

    def check_duel_challenge(self, userid):
        query = f'''
            SELECT id FROM duel
            WHERE (challengee = ? OR challenger = ?) AND (status == {Duel.ONGOING} OR status == {Duel.PENDING})
        '''
        return self.conn.execute(query, (userid, userid)).fetchone()

    def check_duel_accept(self, challengee):
        query = f'''
            SELECT id, challenger, problem_name FROM duel
            WHERE challengee = ? AND status == {Duel.PENDING}
        '''
        return self.conn.execute(query, (challengee,)).fetchone()

    def check_duel_decline(self, challengee):
        query = f'''
            SELECT id, challenger FROM duel
            WHERE challengee = ? AND status == {Duel.PENDING}
        '''
        return self.conn.execute(query, (challengee,)).fetchone()

    def check_duel_withdraw(self, challenger):
        query = f'''
            SELECT id, challengee FROM duel
            WHERE challenger = ? AND status == {Duel.PENDING}
        '''
        return self.conn.execute(query, (challenger,)).fetchone()

    def check_duel_draw(self, userid):
        query = f'''
            SELECT id, challenger, challengee, start_time, type FROM duel
            WHERE (challenger = ? OR challengee = ?) AND status == {Duel.ONGOING}
        '''
        return self.conn.execute(query, (userid, userid)).fetchone()

    def check_duel_complete(self, userid):
        query = f'''
            SELECT id, challenger, challengee, start_time, problem_name, contest_id, p_index, type FROM duel
            WHERE (challenger = ? OR challengee = ?) AND status == {Duel.ONGOING}
        '''
        return self.conn.execute(query, (userid, userid)).fetchone()

    def create_duel(self, challenger, challengee, issue_time, prob, dtype):
        query = f'''
            INSERT INTO duel (challenger, challengee, issue_time, problem_name, contest_id, p_index, status, type) VALUES (?, ?, ?, ?, ?, ?, {Duel.PENDING}, ?)
        '''
        duelid = self.conn.execute(query, (challenger, challengee, issue_time, prob.name, prob.contestId, prob.index, dtype)).lastrowid
        self.conn.commit()
        return duelid

    def cancel_duel(self, duelid, status):
        query = f'''
            UPDATE duel SET status = ? WHERE id = ? AND status = {Duel.PENDING}
        '''
        rc = self.conn.execute(query, (status, duelid)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return rc

    def invalidate_duel(self, duelid):
        query = f'''
            UPDATE duel SET status = {Duel.INVALID} WHERE id = ? AND status = {Duel.ONGOING}
        '''
        rc = self.conn.execute(query, (duelid,)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return rc

    def start_duel(self, duelid, start_time):
        query = f'''
            UPDATE duel SET start_time = ?, status = {Duel.ONGOING}
            WHERE id = ? AND status = {Duel.PENDING}
        '''
        rc = self.conn.execute(query, (start_time, duelid)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return rc

    def complete_duel(self, duelid, winner, finish_time, winner_id = -1, loser_id = -1, delta = 0, dtype = DuelType.OFFICIAL):
        query = f'''
            UPDATE duel SET status = {Duel.COMPLETE}, finish_time = ?, winner = ? WHERE id = ? AND status = {Duel.ONGOING}
        '''
        rc = self.conn.execute(query, (finish_time, winner, duelid)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0

        if dtype == DuelType.OFFICIAL:
            self.update_duel_rating(winner_id, +delta)
            self.update_duel_rating(loser_id, -delta)

        self.conn.commit()
        return 1

    def update_duel_rating(self, userid, delta):
        query = '''
            UPDATE duelist SET rating = rating + ? WHERE user_id = ?
        '''
        rc = self.conn.execute(query, (delta, userid)).rowcount
        self.conn.commit()
        return rc

    def get_duel_wins(self, userid):
        query = f'''
            SELECT start_time, finish_time, problem_name, challenger, challengee FROM duel
            WHERE ((challenger = ? AND winner == {Winner.CHALLENGER}) OR (challengee = ? AND winner == {Winner.CHALLENGEE})) AND status = {Duel.COMPLETE}
        '''
        return self.conn.execute(query, (userid, userid)).fetchall()

    def get_duels(self, userid):
        query = f'''
            SELECT id, start_time, finish_time, problem_name, challenger, challengee, winner FROM duel WHERE (challengee = ? OR challenger = ?) AND status == {Duel.COMPLETE} ORDER BY start_time DESC
        '''
        return self.conn.execute(query, (userid, userid)).fetchall()

    def get_duel_problem_names(self, userid):
        query = f'''
            SELECT problem_name FROM duel WHERE (challengee = ? OR challenger = ?) AND (status == {Duel.COMPLETE} OR status == {Duel.INVALID})
        '''
        return self.conn.execute(query, (userid, userid)).fetchall()

    def get_pair_duels(self, userid1, userid2):
        query = f'''
            SELECT id, start_time, finish_time, problem_name, challenger, challengee, winner FROM duel
            WHERE ((challenger = ? AND challengee = ?) OR (challenger = ? AND challengee = ?)) AND status == {Duel.COMPLETE} ORDER BY start_time DESC
        '''
        return self.conn.execute(query, (userid1, userid2, userid2, userid1)).fetchall()

    def get_recent_duels(self):
        query = f'''
            SELECT id, start_time, finish_time, problem_name, challenger, challengee, winner FROM duel WHERE status == {Duel.COMPLETE} ORDER BY start_time DESC LIMIT 7
        '''
        return self.conn.execute(query).fetchall()

    def get_ongoing_duels(self):
        query = f'''
            SELECT start_time, problem_name, challenger, challengee FROM duel
            WHERE status == {Duel.ONGOING} ORDER BY start_time DESC
        '''
        return self.conn.execute(query).fetchall()

    def get_num_duel_completed(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel WHERE (challengee = ? OR challenger = ?) AND status == {Duel.COMPLETE}
        '''
        return self.conn.execute(query, (userid, userid)).fetchone()[0]

    def get_num_duel_draws(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel WHERE (challengee = ? OR challenger = ?) AND winner == {Winner.DRAW}
        '''
        return self.conn.execute(query, (userid, userid)).fetchone()[0]

    def get_num_duel_losses(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel
            WHERE ((challengee = ? AND winner == {Winner.CHALLENGER}) OR (challenger = ? AND winner == {Winner.CHALLENGEE})) AND status = {Duel.COMPLETE}
        '''
        return self.conn.execute(query, (userid, userid)).fetchone()[0]

    def get_num_duel_declined(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel WHERE challengee = ? AND status == {Duel.DECLINED}
        '''
        return self.conn.execute(query, (userid,)).fetchone()[0]

    def get_num_duel_rdeclined(self, userid):
        query = f'''
            SELECT COUNT(*) FROM duel WHERE challenger = ? AND status == {Duel.DECLINED}
        '''
        return self.conn.execute(query, (userid,)).fetchone()[0]

    def get_duel_rating(self, userid):
        query = '''
            SELECT rating FROM duelist WHERE user_id = ?
        '''
        return self.conn.execute(query, (userid,)).fetchone()[0]

    def is_duelist(self, userid):
        query = '''
            SELECT 1 FROM duelist WHERE user_id = ?
        '''
        return self.conn.execute(query, (userid,)).fetchone()

    def register_duelist(self, userid):
        query = '''
            INSERT OR IGNORE INTO duelist (user_id, rating)
            VALUES (?, 1500)
        '''
        with self.conn:
            return self.conn.execute(query, (userid,)).rowcount

    def get_duelists(self):
        query = '''
            SELECT user_id, rating FROM duelist ORDER BY rating DESC
        '''
        return self.conn.execute(query).fetchall()

    def get_complete_official_duels(self):
        query = f'''
            SELECT challenger, challengee, winner, finish_time FROM duel WHERE status={Duel.COMPLETE}
            AND type={DuelType.OFFICIAL} ORDER BY finish_time ASC
        '''
        return self.conn.execute(query).fetchall()

    def get_rankup_channel(self, guild_id):
        query = ('SELECT channel_id '
                 'FROM rankup '
                 'WHERE guild_id = ?')
        channel_id = self.conn.execute(query, (guild_id,)).fetchone()
        return int(channel_id[0]) if channel_id else None

    def set_rankup_channel(self, guild_id, channel_id):
        query = ('INSERT OR REPLACE INTO rankup '
                 '(guild_id, channel_id) '
                 'VALUES (?, ?)')
        with self.conn:
            self.conn.execute(query, (guild_id, channel_id))

    def clear_rankup_channel(self, guild_id):
        query = ('DELETE FROM rankup '
                 'WHERE guild_id = ?')
        with self.conn:
            return self.conn.execute(query, (guild_id,)).rowcount

    def enable_auto_role_update(self, guild_id):
        query = ('INSERT OR REPLACE INTO auto_role_update '
                 '(guild_id) '
                 'VALUES (?)')
        with self.conn:
            return self.conn.execute(query, (guild_id,)).rowcount

    def disable_auto_role_update(self, guild_id):
        query = ('DELETE FROM auto_role_update '
                 'WHERE guild_id = ?')
        with self.conn:
            return self.conn.execute(query, (guild_id,)).rowcount

    def has_auto_role_update_enabled(self, guild_id):
        query = ('SELECT 1 '
                 'FROM auto_role_update '
                 'WHERE guild_id = ?')
        return self.conn.execute(query, (guild_id,)).fetchone() is not None

    def reset_status(self, id):
        inactive_query = '''
            UPDATE user_handle
            SET active = 0
            WHERE guild_id = ?
        '''
        self.conn.execute(inactive_query, (id,))
        self.conn.commit()

    def update_status(self, guild_id: str, active_ids: list):
        placeholders = ', '.join(['?'] * len(active_ids))
        if not active_ids: return 0
        active_query = '''
            UPDATE user_handle
            SET active = 1
            WHERE user_id IN ({})
            AND guild_id = ?
        '''.format(placeholders)
        rc = self.conn.execute(active_query, (*active_ids, guild_id)).rowcount
        self.conn.commit()
        return rc

    # Rated VC stuff

    def create_rated_vc(self, contest_id: int, start_time: float, finish_time: float, guild_id: str, user_ids: [str]):
        """ Creates a rated vc and returns its id.
        """
        query = ('INSERT INTO rated_vcs '
                 '(contest_id, start_time, finish_time, status, guild_id) '
                 'VALUES ( ?, ?, ?, ?, ?)')
        id = None
        with self.conn:
            id = self.conn.execute(query, (contest_id, start_time, finish_time, RatedVC.ONGOING, guild_id)).lastrowid
            for user_id in user_ids:
                query = ('INSERT INTO rated_vc_users '
                         '(vc_id, user_id) '
                         'VALUES (? , ?)')
                self.conn.execute(query, (id, user_id))
        return id

    def get_rated_vc(self, vc_id: int):
        query = ('SELECT * '
                'FROM rated_vcs '
                'WHERE id = ? ')
        vc = self._fetchone(query, params=(vc_id,), row_factory=namedtuple_factory)
        return vc

    def get_ongoing_rated_vc_ids(self):
        query = ('SELECT id '
                 'FROM rated_vcs '
                 'WHERE status = ? '
                 )
        vcs = self._fetchall(query, params=(RatedVC.ONGOING,), row_factory=namedtuple_factory)
        vc_ids = [vc.id for vc in vcs]
        return vc_ids

    def get_rated_vc_user_ids(self, vc_id: int):
        query = ('SELECT user_id '
                 'FROM rated_vc_users '
                 'WHERE vc_id = ? '
                 )
        users = self._fetchall(query, params=(vc_id,), row_factory=namedtuple_factory)
        user_ids = [user.user_id for user in users]
        return user_ids

    def finish_rated_vc(self, vc_id: int):
        query = ('UPDATE rated_vcs '
                'SET status = ? '
                'WHERE id = ? ')

        with self.conn:
            self.conn.execute(query, (RatedVC.FINISHED, vc_id))

    def update_vc_rating(self, vc_id: int, user_id: str, rating: int):
        query = ('INSERT OR REPLACE INTO rated_vc_users '
                 '(vc_id, user_id, rating) '
                 'VALUES (?, ?, ?) ')

        with self.conn:
            self.conn.execute(query, (vc_id, user_id, rating))

    def get_vc_rating(self, user_id: str, default_if_not_exist: bool = True):
        query = ('SELECT MAX(vc_id) AS latest_vc_id, rating '
                 'FROM rated_vc_users '
                 'WHERE user_id = ? AND rating IS NOT NULL'
                 )
        rating = self._fetchone(query, params=(user_id, ), row_factory=namedtuple_factory).rating
        if rating is None:
            if default_if_not_exist:
                return _DEFAULT_VC_RATING
            return None
        return rating

    def get_vc_rating_history(self, user_id: str):
        """ Return [vc_id, rating].
        """
        query = ('SELECT vc_id, rating '
                 'FROM rated_vc_users '
                 'WHERE user_id = ? AND rating IS NOT NULL'
                 )
        ratings = self._fetchall(query, params=(user_id,), row_factory=namedtuple_factory)
        return ratings

    def set_rated_vc_channel(self, guild_id, channel_id):
        query = ('INSERT OR REPLACE INTO rated_vc_settings '
                 ' (guild_id, channel_id) VALUES (?, ?)'
                 )
        with self.conn:
            self.conn.execute(query, (guild_id, channel_id))

    def get_rated_vc_channel(self, guild_id):
        query = ('SELECT channel_id '
                 'FROM rated_vc_settings '
                 'WHERE guild_id = ?')
        channel_id = self.conn.execute(query, (guild_id,)).fetchone()
        return int(channel_id[0]) if channel_id else None

    def remove_last_ratedvc_participation(self, user_id: str):
        query = ('SELECT MAX(vc_id) AS vc_id '
                 'FROM rated_vc_users '
                 'WHERE user_id = ? '
                 )
        vc_id = self._fetchone(query, params=(user_id, ), row_factory=namedtuple_factory).vc_id
        query = ('DELETE FROM rated_vc_users '
                 'WHERE user_id = ? AND vc_id = ? ')
        with self.conn:
            return self.conn.execute(query, (user_id, vc_id)).rowcount

    def close(self):
        self.conn.close()
