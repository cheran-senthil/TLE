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

    def removehandle(self, id):
        """ returns 1 if removed, 0 if not """
        query = 'DELETE FROM user_handle WHERE id = ?'
        rc = self.conn.execute(query, (id, )).rowcount
        self.conn.commit()
        return rc

    def close(self):
        self.conn.close()