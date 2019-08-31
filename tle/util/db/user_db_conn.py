import sqlite3
import time

from discord.ext import commands

from tle.util import codeforces_api as cf


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
            CREATE TABLE IF NOT EXISTS "contest" (
                "id"	INTEGER,
                "name"	TEXT,
                "start_time"	INTEGER,
                "duration"	INTEGER,
                "type"	TEXT,
                "phase"	TEXT,
                "prepared_by"	TEXT,
                PRIMARY KEY("id")
            );
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS "problem" (
                "name"	TEXT,
                "contest_id"	INTEGER,
                "p_index"	TEXT,
                "start_time"	INTEGER,
                "rating"	INTEGER,
                "type"	TEXT,
                "tags"	TEXT,
                PRIMARY KEY("name")
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

    def fetch_contests(self):
        query = 'SELECT id, name, start_time, duration, type, phase, prepared_by FROM contest'
        res = self.conn.execute(query).fetchall()
        if res is None: return None
        return [cf.Contest(*r) for r in res]

    def fetch_problems(self):
        query = '''
            SELECT contest_id, p_index, name, type, rating, tags, start_time
            FROM problem
        '''
        res = self.conn.execute(query).fetchall()
        if res is None: return None
        return [(cf.Problem(*r[:6]), r[6]) for r in res]

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

    def complete_challenge(self, user_id, challenge_id, finish_time, delta):
        query1 = '''
            UPDATE challenge SET finish_time = ?, status = 0
            WHERE id = ? AND status = 1
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

    def force_skip_challenge(self, user_id):
        query = '''
            UPDATE user_challenge SET active_challenge_id = NULL, issue_time = NULL
            WHERE user_id = ?
        '''
        rc = self.conn.execute(query, (user_id,)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return 1

    def skip_challenge(self, user_id, challenge_id):
        query = '''
            UPDATE user_challenge SET active_challenge_id = NULL, issue_time = NULL
            WHERE user_id = ? AND active_challenge_id = ?
        '''
        rc = self.conn.execute(query, (user_id, challenge_id)).rowcount
        if rc != 1:
            self.conn.rollback()
            return 0
        self.conn.commit()
        return 1

    def cache_contests(self, contests: list):
        return self._insert_many('contest',
            ['id', 'name', 'start_time', 'duration', 'type', 'phase', 'prepared_by'],
            contests
        )

    def cache_problems(self, problems: list):
        return self._insert_many('problem',
            ['name', 'contest_id', 'p_index', 'start_time', 'rating', 'type', 'tags'],
            problems
        )

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

    def close(self):
        self.conn.close()
