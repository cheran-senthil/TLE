import sqlite3
from tle.cogs.util import codeforces_api as cf


class HandleConn():
    def __init__(self, dbfile):
        self.conn = sqlite3.connect(dbfile)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS user_handle(
                id TEXT PRIMARY KEY,
                handle TEXT
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS cf_cache(
                handle TEXT PRIMARY KEY,
                rating INTEGER,
                titlePhoto TEXT
            )
        ''')

    def cache_cfuser(self, user):
        """ return 1 if set, 0 if not """
        query = '''
            INSERT OR REPLACE INTO cf_cache (handle, rating, titlePhoto)
            values (?, ?, ?)
        '''
        rc = self.conn.execute(query, user)
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

    def getallcache(self):
        query = 'SELECT handle, rating, titlePhoto FROM cf_cache'
        users = self.conn.execute(query).fetchall()
        return [cf.User._make(user) for user in users]

    def clearcache(self):
        query = 'DELETE FROM cf_cache'
        self.conn.execute(query)
        self.conn.commit()

    def sethandle(self, id, handle):
        """ returns 1 if set, 0 if not """
        query = '''
            INSERT OR REPLACE INTO user_handle (id, handle) values
            (?, ?)
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
        query = 'SELECT id, handle FROM user_handle'
        return self.conn.execute(query).fetchall()

    def getallhandleswithrating(self):
        """ returns list of (id, handle, rating) """
        query = '''
            SELECT user_handle.id, user_handle.handle, cf_cache.rating 
            FROM user_handle
            LEFT JOIN cf_cache
            ON user_handle.handle = cf_cache.handle        
        '''
        return self.conn.execute(query).fetchall()

    def removehandle(self, id):
        """ returns 1 if removed, 0 if not """
        query = 'DELETE FROM user_handle WHERE id = ?'
        rc = self.conn.execute(query, (id,)).rowcount
        self.conn.commit()
        return rc

    def close(self):
        self.conn.close()
