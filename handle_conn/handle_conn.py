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
        cur = self.conn.cursor()
        cur.execute(query, (id, handle))
        self.conn.commit()
        return cur.rowcount

    def gethandle(self, id):
        """ returns string or None """
        query = 'SELECT handle FROM user_handle WHERE id = ?'
        cur = self.conn.cursor()
        cur.execute(query, (id, ))
        res = cur.fetchone()
        if res: return res[0]
        return None

    def getallhandles(self):
        """ returns list of (id, handle) """
        query = 'SELECT id, handle FROM user_handle'
        cur = self.conn.cursor()
        cur.execute(query)
        return cur.fetchall()

    def close(self):
        self.conn.close()