import sqlite3
import time
from enum import IntEnum

from discord.ext import commands

from tle.util import codeforces_api as cf

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

class DatabaseDisabledError(commands.CommandError):
    pass


class DummyUserDbConn:
    def __getattribute__(self, item):
        raise DatabaseDisabledError


class UserDbConn:
    def __init__(self, dbfile):
        self.conn = sqlite3.connect(dbfile)
        self.create_tables()

    def create_tables(self):
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
                "winner"	INTEGER
            )
        ''')
        # status => 0 inactive, 1 active
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS user_handle(
                id TEXT PRIMARY KEY,
                handle TEXT,
                status INT
            )
        ''')
        # solved => problem identifier of all solved problems in json dump
        # lastCached => last time the user was cached
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS cf_cache(
                handle TEXT PRIMARY KEY,
                rating INTEGER,
                titlePhoto TEXT,
                solved TEXT,
                lastCached REAL
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

    def cache_cfuser(self, user):
        return self._insert_one('cf_cache',
            ('handle', 'rating', 'titlePhoto', 'lastCached'),
            user + (time.time(),)
        )

    def cache_cfuser_full(self, columns: tuple):
        return self._insert_one('cf_cache',
            ('handle', 'rating', 'titlePhoto', 'solved', 'lastCached'),
            columns
        )

    def fetch_cfuser(self, handle):
        query = '''
            SELECT handle, rating, titlePhoto FROM cf_cache
            WHERE handle = ?
        '''
        user = self.conn.execute(query, (handle,)).fetchone()
        if user:
            user = cf.User._make(user)
        return user

    def fetch_rating_solved(self, handle):
        query = 'SELECT lastCached, rating, solved FROM cf_cache WHERE handle = ?'
        return self.conn.execute(query, (handle,)).fetchone()

    def getallcache(self):
        query = 'SELECT handle, rating, titlePhoto FROM cf_cache'
        users = self.conn.execute(query).fetchall()
        return [cf.User._make(user) for user in users]

    def clear_cache(self):
        query = 'DELETE FROM cf_cache'
        self.conn.execute(query)
        self.conn.commit()

    def sethandle(self, id, handle):
        """ returns 1 if set, 0 if not """
        query = '''
            INSERT OR REPLACE INTO user_handle (id, handle, status) values
            (?, ?, 1)
        '''
        rc = self.conn.execute(query, (id, handle)).rowcount
        self.conn.commit()
        return rc

    def gethandle(self, id):
        """ returns string or None """
        query = 'SELECT handle FROM user_handle WHERE id = ?'
        res = self.conn.execute(query, (id,)).fetchone()
        return res[0] if res else None

    def rgethandle(self, handle):
        """ returns string or None """
        query = 'SELECT id FROM user_handle WHERE handle = ?'
        res = self.conn.execute(query, (handle,)).fetchone()
        return res[0] if res else None

    def getallhandles(self):
        """ returns list of (id, handle) """
        query = 'SELECT id, handle FROM user_handle WHERE status = 1'
        return self.conn.execute(query).fetchall()

    def getallhandleswithrating(self):
        """ returns list of (id, handle, rating) """
        query = '''
            SELECT user_handle.id, user_handle.handle, cf_cache.rating
            FROM user_handle
            LEFT JOIN cf_cache
            ON user_handle.handle = cf_cache.handle
            WHERE user_handle.status = 1
        '''
        return self.conn.execute(query).fetchall()

    def get_handles_for_guild(self, guild_id):
        # TODO: Modify the database to store users on a guild basis.
        # Currently returns all users.
        return self.getallhandles()

    def removehandle(self, id):
        """ returns 1 if removed, 0 if not """
        query = 'DELETE FROM user_handle WHERE id = ?'
        rc = self.conn.execute(query, (id,)).rowcount
        self.conn.commit()
        return rc

    def update_status(self, active_ids: list):
        if not active_ids: return 0
        placeholders = ', '.join(['?'] * len(active_ids))
        inactive_query = '''
            UPDATE user_handle
            SET status = 0
            WHERE id NOT IN ({})
        '''.format(placeholders)
        active_query = '''
            UPDATE user_handle
            SET status = 1
            WHERE id IN ({})
        '''.format(placeholders)
        self.conn.execute(inactive_query, active_ids)
        rc = self.conn.execute(active_query, active_ids).rowcount
        self.conn.commit()
        return rc

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
            SELECT id, challenger FROM duel
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
            SELECT id, challenger, challengee, start_time FROM duel
            WHERE (challenger = ? OR challengee = ?) AND status == {Duel.ONGOING}
        '''
        return self.conn.execute(query, (userid, userid)).fetchone()

    def check_duel_complete(self, userid):
        query = f'''
            SELECT id, challenger, challengee, start_time, problem_name, contest_id, p_index FROM duel
            WHERE (challenger = ? OR challengee = ?) AND status == {Duel.ONGOING}
        '''
        return self.conn.execute(query, (userid, userid)).fetchone()

    def create_duel(self, challenger, challengee, issue_time):
        query = f'''
            INSERT INTO duel (challenger, challengee, issue_time, status) VALUES (?, ?, ?, {Duel.PENDING})
        '''
        duelid = self.conn.execute(query, (challenger, challengee, issue_time)).lastrowid
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
            UPDATE duel SET status = {Duel.INVALID} WHERE id = ?
        '''
        rc = self.conn.execute(query, (duelid,)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return rc

    def start_duel(self, duelid, start_time, prob):
        query = f'''
            UPDATE duel SET start_time = ?, problem_name = ?, contest_id = ?, p_index = ?, status = {Duel.ONGOING}
            WHERE id = ? AND status = {Duel.PENDING}
        '''
        rc = self.conn.execute(query, (start_time, prob.name, prob.contestId, prob.index, duelid)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return rc

    def complete_duel(self, duelid, winner, finish_time, winner_id = -1, loser_id = -1, delta = 0):
        query = f'''
            UPDATE duel SET status = {Duel.COMPLETE}, finish_time = ?, winner = ? WHERE id = ? AND status = {Duel.ONGOING}
        '''
        rc = self.conn.execute(query, (finish_time, winner, duelid)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0

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
        return self.conn.execute(query, (userid,)).rowcount

    def get_duelists(self):
        query = '''
            SELECT user_id, rating FROM duelist ORDER BY rating DESC
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

    def close(self):
        self.conn.close()
