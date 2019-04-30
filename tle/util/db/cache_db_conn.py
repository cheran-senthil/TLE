import sqlite3

from tle.util import codeforces_api as cf


class CacheDbConn:
    def __init__(self, db_file):
        self.conn = sqlite3.connect(db_file)
        self.create_tables()

    def create_tables(self):
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS contest ('
            'id             INTEGER NOT NULL,'
            'name           TEXT,'
            'start_time     INTEGER,'
            'duration       INTEGER,'
            'type           TEXT,'
            'phase          TEXT,'
            'prepared_by    TEXT,'
            'PRIMARY KEY (id)'
            ')'
        )
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS problem ('
            'name           TEXT NOT NULL,'
            'contest_id     INTEGER,'
            'p_index        TEXT,'
            'start_time     INTEGER,'
            'rating         INTEGER,'
            'type           TEXT,'
            'tags           TEXT,'
            'PRIMARY KEY (name)'
            ')'
        )
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS rating_change ('
            'contest_id           INTEGER NOT NULL,'
            'handle               TEXT NOT NULL,'
            'rank                 INTEGER,'
            'rating_update_time   INTEGER,'
            'old_rating           INTEGER,'
            'new_rating           INTEGER,'
            'UNIQUE (contest_id, handle)'
            ')'
        )
        self.conn.execute('CREATE INDEX IF NOT EXISTS ix_rating_change_contest_id '
                          'ON rating_change (contest_id)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS ix_rating_change_handle '
                          'ON rating_change (handle)')

    def fetch_contests(self):
        query = ('SELECT id, name, start_time, duration, type, phase, prepared_by '
                 'FROM contest')
        res = self.conn.execute(query).fetchall()
        return [cf.Contest._make(contest) for contest in res]

    def fetch_problems(self):
        query = ('SELECT contest_id, p_index, name, type, rating, tags, start_time '
                 'FROM problem')
        res = self.conn.execute(query).fetchall()
        return [(cf.Problem._make(problem[:6]), problem[6]) for problem in res]

    def cache_contests(self, contests):
        query = ('INSERT OR REPLACE INTO contest '
                 '(id, name, start_time, duration, type, phase, prepared_by) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?)')
        rc = self.conn.executemany(query, contests).rowcount
        self.conn.commit()
        return rc

    def cache_problems(self, problems):
        query = ('INSERT OR REPLACE INTO problem '
                 '(name, contest_id, p_index, start_time, rating, type, tags) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?)')
        rc = self.conn.executemany(query, problems).rowcount
        self.conn.commit()
        return rc

    def save_rating_changes(self, changes):
        change_tuples = [(change.contestId,
                          change.handle,
                          change.rank,
                          change.ratingUpdateTimeSeconds,
                          change.oldRating,
                          change.newRating) for change in changes]
        query = ('INSERT OR REPLACE INTO rating_change '
                 '(contest_id, handle, rank, rating_update_time, old_rating, new_rating) '
                 'VALUES (?, ?, ?, ?, ?, ?)')
        rc = self.conn.executemany(query, change_tuples).rowcount
        self.conn.commit()
        return rc

    def get_all_rating_changes(self):
        query = ('SELECT contest_id, name, handle, rank, rating_update_time, old_rating, new_rating '
                 'FROM rating_change r '
                 'LEFT JOIN contest c '
                 'ON r.contest_id = c.id')
        res = self.conn.execute(query).fetchall()
        return [cf.RatingChange._make(change) for change in res]

    def get_rating_changes_for_contest(self, contest_id):
        query = ('SELECT contest_id, name, handle, rank, rating_update_time, old_rating, new_rating '
                 'FROM rating_change r '
                 'LEFT JOIN contest c '
                 'ON r.contest_id = c.id '
                 'WHERE r.contest_id = ?')
        res = self.conn.execute(query, (contest_id,)).fetchall()
        return [cf.RatingChange._make(change) for change in res]

    def has_rating_changes_saved(self, contest_id):
        query = ('SELECT contest_id '
                 'FROM rating_change '
                 'WHERE contest_id = ?')
        res = self.conn.execute(query, (contest_id,)).fetchone()
        return res is not None

    def get_rating_changes_for_handle(self, handle):
        query = ('SELECT contest_id, name, handle, rank, rating_update_time, old_rating, new_rating '
                 'FROM rating_change r '
                 'LEFT JOIN contest c '
                 'ON r.contest_id = c.id '
                 'WHERE r.handle = ?')
        res = self.conn.execute(query, (handle,)).fetchall()
        return [cf.RatingChange._make(change) for change in res]

    def close(self):
        self.conn.close()
