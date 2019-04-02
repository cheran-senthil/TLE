import sqlite3


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
                photo TEXT
            )
        ''')

    def cachehandle(self, handle, rating, photo):
        """ return 1 if set, 0 if not """
        query = '''
            INSERT OR REPLACE INTO cf_cache (handle, rating, photo)
            values (?, ?, ?)
        '''
        rc = self.conn.execute(query, (handle, rating, photo))
        self.conn.commit()
        return rc

    def fetch_handle_info(self, handle):
        query = '''
            SELECT rating, photo FROM cf_cache
            WHERE handle = ?
        '''
        return self.conn.execute(query, (handle,)).fetchone()

    def getallcache(self):
        query = 'SELECT handle, rating, photo FROM cf_cache'
        return self.conn.execute(query).fetchall()

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
        res = self.conn.execute(query, (id, )).fetchone()
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
        rc = self.conn.execute(query, (id, )).rowcount
        self.conn.commit()
        return rc

    def close(self):
        self.conn.close()