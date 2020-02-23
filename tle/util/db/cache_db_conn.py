import json
import sqlite3

from tle.util import codeforces_api as cf


class CacheDbConn:
    def __init__(self, db_file):
        self.conn = sqlite3.connect(db_file)
        self.create_tables()

    def create_tables(self):
        # Table for contests from the contest.list endpoint.
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

        # Table for problems from the problemset.problems endpoint.
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS problem ('
            'contest_id       INTEGER,'
            'problemset_name  TEXT,'
            '[index]          TEXT,'
            'name             TEXT NOT NULL,'
            'type             TEXT,'
            'points           REAL,'
            'rating           INTEGER,'
            'tags             TEXT,'
            'PRIMARY KEY (name)'
            ')'
        )

        # Table for rating changes fetched from contest.ratingChanges endpoint for every contest.
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

        # Table for problems fetched from contest.standings endpoint for every contest.
        # This is separate from table problem as it contains the same problem twice if it
        # appeared in both Div 1 and Div 2 of some round.
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS problem2 ('
            'contest_id       INTEGER,'
            'problemset_name  TEXT,'
            '[index]          TEXT,'
            'name             TEXT NOT NULL,'
            'type             TEXT,'
            'points           REAL,'
            'rating           INTEGER,'
            'tags             TEXT,'
            'PRIMARY KEY (contest_id, [index])'
            ')'
        )
        self.conn.execute('CREATE INDEX IF NOT EXISTS ix_problem2_contest_id '
                          'ON problem2 (contest_id)')

    def cache_contests(self, contests):
        query = ('INSERT OR REPLACE INTO contest '
                 '(id, name, start_time, duration, type, phase, prepared_by) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?)')
        rc = self.conn.executemany(query, contests).rowcount
        self.conn.commit()
        return rc

    def fetch_contests(self):
        query = ('SELECT id, name, start_time, duration, type, phase, prepared_by '
                 'FROM contest')
        res = self.conn.execute(query).fetchall()
        return [cf.Contest._make(contest) for contest in res]

    @staticmethod
    def _squish_tags(problem):
        return (problem.contestId, problem.problemsetName, problem.index, problem.name,
                problem.type, problem.points, problem.rating, json.dumps(problem.tags))

    def cache_problems(self, problems):
        query = ('INSERT OR REPLACE INTO problem '
                 '(contest_id, problemset_name, [index], name, type, points, rating, tags) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
        rc = self.conn.executemany(query, list(map(self._squish_tags, problems))).rowcount
        self.conn.commit()
        return rc

    @staticmethod
    def _unsquish_tags(problem):
        args, tags = problem[:-1], json.loads(problem[-1])
        return cf.Problem(*args, tags)

    def fetch_problems(self):
        query = ('SELECT contest_id, problemset_name, [index], name, type, points, rating, tags '
                 'FROM problem')
        res = self.conn.execute(query).fetchall()
        return list(map(self._unsquish_tags, res))

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

    def clear_rating_changes(self, contest_id=None):
        if contest_id is None:
            query = 'DELETE FROM rating_change'
            self.conn.execute(query)
        else:
            query = 'DELETE FROM rating_change WHERE contest_id = ?'
            self.conn.execute(query, (contest_id,))
        self.conn.commit()

    def get_users_with_more_than_n_contests(self, time_cutoff, n):
        query = ('SELECT handle, COUNT(*) AS num_contests '
                 'FROM rating_change GROUP BY handle HAVING num_contests >= ? '
                 'AND MAX(rating_update_time) >= ?')
        res = self.conn.execute(query, (n, time_cutoff,)).fetchall()
        return [user[0] for user in res]

    def get_all_rating_changes(self):
        query = ('SELECT contest_id, name, handle, rank, rating_update_time, old_rating, new_rating '
                 'FROM rating_change r '
                 'LEFT JOIN contest c '
                 'ON r.contest_id = c.id')
        res = self.conn.execute(query)
        return (cf.RatingChange._make(change) for change in res)

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

    def cache_problemset(self, problemset):
        query = ('INSERT OR REPLACE INTO problem2 '
                 '(contest_id, problemset_name, [index], name, type, points, rating, tags) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
        rc = self.conn.executemany(query, list(map(self._squish_tags, problemset))).rowcount
        self.conn.commit()
        return rc

    def fetch_problems2(self):
        query = ('SELECT contest_id, problemset_name, [index], name, type, points, rating, tags '
                 'FROM problem2 ')
        res = self.conn.execute(query).fetchall()
        return list(map(self._unsquish_tags, res))

    def clear_problemset(self, contest_id=None):
        if contest_id is None:
            query = 'DELETE FROM problem2'
            self.conn.execute(query)
        else:
            query = 'DELETE FROM problem2 WHERE contest_id = ?'
            self.conn.execute(query, (contest_id,))

    def fetch_problemset(self, contest_id):
        query = ('SELECT contest_id, problemset_name, [index], name, type, points, rating, tags '
                 'FROM problem2 '
                 'WHERE contest_id = ?')
        res = self.conn.execute(query, (contest_id,)).fetchall()
        return list(map(self._unsquish_tags, res))

    def problemset_empty(self):
        query = 'SELECT 1 FROM problem2'
        res = self.conn.execute(query).fetchone()
        return res is None

    def close(self):
        self.conn.close()
