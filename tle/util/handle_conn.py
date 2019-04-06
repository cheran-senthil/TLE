import sqlite3
import time

from tle.util import codeforces_api as cf

# Connection to database available across modules
conn = None


def initialize_conn(dbfile):
    global conn
    conn = HandleConn(dbfile)


class HandleConn:
    def __init__(self, dbfile):
        self.conn = sqlite3.connect(dbfile)
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

    def cache_cfuser(self, user):
        """ return 1 if set, 0 if not """
        query = '''
            INSERT OR REPLACE INTO cf_cache
            (handle, rating, titlePhoto, lastCached)
            VALUES (?, ?, ?, ?)
        '''
        rc = self.conn.execute(query, user + (time.time(),))
        self.conn.commit()
        return rc

    def cache_cfuser_full(self, columns: tuple):
        query = '''
            INSERT OR REPLACE INTO cf_cache
            (handle, rating, titlePhoto, solved, lastCached)
            VALUES (?, ?, ?, ?, ?)
        '''
        rc = self.conn.execute(query, columns)
        self.conn.commit()
        return rc

    def fetch_cfuser(self, handle):
        query = '''
            SELECT handle, rating, titlePhoto FROM cf_cache
            WHERE handle = ?
        '''
        user = self.conn.execute(query, (handle,)).fetchone()
        if user:
            user = cf.User._make(user)
        return user

    def fetch_cfuser_custom(self, handle: str, columns: list):
        query = 'SELECT {} FROM cf_cache WHERE handle = ?'.format(', '.join(columns))
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

    def close(self):
        self.conn.close()
