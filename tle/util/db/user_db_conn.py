from collections import namedtuple
from enum import IntEnum
import sqlite3

from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common

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


def namedtuple_factory(cursor, row):
  """Returns sqlite rows as named tuples."""
  fields = [col[0] for col in cursor.description if col[0].isidentifier()]
  Row = namedtuple("Row", fields)
  return Row(*row)

class UniqueConstraintFailed(UserDbError):
  pass

class UserDbConn:
  def __init__(self, dbfile):
    self.conn = sqlite3.connect(dbfile)
    self.conn.row_factory = namedtuple_factory
    self.create_tables()

  def create_tables(self):
    # existing tables
    self.conn.execute(
      'CREATE TABLE IF NOT EXISTS user_handle ('
      'user_id     TEXT,'
      'guild_id    TEXT,'
      'handle      TEXT,'
      'active      INTEGER,'
      'PRIMARY KEY (user_id, guild_id)'
      ')'
    )
    self.conn.execute(
      'CREATE UNIQUE INDEX IF NOT EXISTS ix_user_handle_guild_handle '
      'ON user_handle (guild_id, handle)'
    )
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
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS duelist(
        "user_id"  INTEGER PRIMARY KEY NOT NULL,
        "rating"   INTEGER NOT NULL
      )
    ''')
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS duel(
        "id"          INTEGER PRIMARY KEY AUTOINCREMENT,
        "challenger"  INTEGER NOT NULL,
        "challengee"  INTEGER NOT NULL,
        "issue_time"  REAL NOT NULL,
        "start_time"  REAL,
        "finish_time" REAL,
        "problem_name" TEXT,
        "contest_id"  INTEGER,
        "p_index"     INTEGER,
        "status"      INTEGER,
        "winner"      INTEGER,
        "type"        INTEGER
      )
    ''')
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS "challenge" (
        "id"             INTEGER PRIMARY KEY AUTOINCREMENT,
        "user_id"        TEXT NOT NULL,
        "issue_time"     REAL NOT NULL,
        "finish_time"    REAL,
        "problem_name"   TEXT NOT NULL,
        "contest_id"     INTEGER NOT NULL,
        "p_index"        INTEGER NOT NULL,
        "rating_delta"   INTEGER NOT NULL,
        "status"         INTEGER NOT NULL
      )
    ''')
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS "user_challenge" (
        "user_id"            TEXT,
        "active_challenge_id" INTEGER,
        "issue_time"         REAL,
        "score"              INTEGER NOT NULL,
        "num_completed"      INTEGER NOT NULL,
        "num_skipped"        INTEGER NOT NULL,
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
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS "rated_vcs" (
        "id"            INTEGER PRIMARY KEY AUTOINCREMENT,
        "contest_id"    INTEGER NOT NULL,
        "start_time"    REAL,
        "finish_time"   REAL,
        "status"        INTEGER,
        "guild_id"      TEXT
      )
    ''')
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS "rated_vc_users" (
        "vc_id"         INTEGER,
        "user_id"       TEXT NOT NULL,
        "rating"        INTEGER,
        CONSTRAINT fk_vc FOREIGN KEY (vc_id) REFERENCES rated_vcs(id),
        PRIMARY KEY(vc_id, user_id)
      )
    ''')
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS rated_vc_settings (
        guild_id TEXT PRIMARY KEY,
        channel_id TEXT
      )
    ''')

    # --- new multi-emoji starboard schema & migration ---
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS starboard_config (
        guild_id   TEXT,
        emoji      TEXT,
        channel_id TEXT,
        PRIMARY KEY (guild_id, emoji)
      )
    ''')
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS starboard_emoji (
        guild_id   TEXT,
        emoji      TEXT,
        threshold  INTEGER,
        PRIMARY KEY (guild_id, emoji)
      )
    ''')
    old = self.conn.execute('SELECT guild_id, channel_id FROM starboard').fetchall()
    for guild_id, channel_id in old:
      self.conn.execute(
        'INSERT OR IGNORE INTO starboard_config VALUES (?,?,?)',
        (guild_id, '\u2B50', channel_id)
      )
      self.conn.execute(
        'INSERT OR IGNORE INTO starboard_emoji VALUES (?,?,?)',
        (guild_id, '\u2B50', 5)
      )
    self.conn.execute('DROP TABLE IF EXISTS starboard')
    self.conn.execute('''
      CREATE TABLE IF NOT EXISTS starboard_message_new (
        original_msg_id  TEXT,
        starboard_msg_id TEXT,
        guild_id         TEXT,
        emoji            TEXT,
        PRIMARY KEY (original_msg_id, emoji)
      )
    ''')
    msgs = self.conn.execute(
      'SELECT original_msg_id, starboard_msg_id, guild_id FROM starboard_message'
    ).fetchall()
    for orig, star, g in msgs:
      self.conn.execute(
        'INSERT OR IGNORE INTO starboard_message_new VALUES (?,?,?,?)',
        (orig, star, g, '\u2B50')
      )
    self.conn.execute('DROP TABLE IF EXISTS starboard_message')
    self.conn.execute('ALTER TABLE starboard_message_new RENAME TO starboard_message')

    self.conn.commit()
    # --- end migration ---

  # helper functions
  def _insert_one(self, table: str, columns, values: tuple):
    n = len(values)
    query = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['?']*n)})"
    rc = self.conn.execute(query, values).rowcount
    self.conn.commit()
    return rc

  def _insert_many(self, table: str, columns, values: list):
    n = len(columns)
    query = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['?']*n)})"
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
      VALUES (?, ?, ?, ?, ?, ?, 1)
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
      self.conn.rollback(); return 0
    cur.execute(query2, (user_id,))
    cur.execute(query3, (last_id, issue_time, user_id))
    if cur.rowcount != 1:
      self.conn.rollback(); return 0
    self.conn.commit(); return 1

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

  # ... (all other existing methods unchanged, including cache_cf_user, fetch_cf_user, set_handle, duel methods, rated_vc methods) ...

  # --- new methods for starboard ---
  def add_starboard_emoji(self, guild_id, emoji, threshold):
    return self._insert_one(
      'starboard_emoji',
      ('guild_id','emoji','threshold'),
      (guild_id, emoji, threshold)
    )

  def remove_starboard_emoji(self, guild_id, emoji):
    rc = self.conn.execute(
      'DELETE FROM starboard_emoji WHERE guild_id = ? AND emoji = ?',
      (guild_id, emoji)
    ).rowcount
    self.conn.commit(); return rc

  def update_starboard_threshold(self, guild_id, emoji, threshold):
    rc = self.conn.execute(
      'UPDATE starboard_emoji SET threshold = ? WHERE guild_id = ? AND emoji = ?',
      (threshold, guild_id, emoji)
    ).rowcount
    self.conn.commit(); return rc

  def set_starboard_channel(self, guild_id, emoji, channel_id):
    return self._insert_one(
      'starboard_config',
      ('guild_id','emoji','channel_id'),
      (guild_id, emoji, channel_id)
    )

  def clear_starboard_channel(self, guild_id, emoji):
    rc = self.conn.execute(
      'DELETE FROM starboard_config WHERE guild_id = ? AND emoji = ?',
      (guild_id, emoji)
    ).rowcount
    self.conn.commit(); return rc

  def get_starboard_entry(self, guild_id, emoji):
    row = self.conn.execute(
      'SELECT channel_id FROM starboard_config WHERE guild_id = ? AND emoji = ?',
      (guild_id, emoji)
    ).fetchone()
    if not row: return None
    thr = self.conn.execute(
      'SELECT threshold FROM starboard_emoji WHERE guild_id = ? AND emoji = ?',
      (guild_id, emoji)
    ).fetchone()
    return (int(row[0]), int(thr[0])) if thr else None

  def add_starboard_message(self, original_msg_id, starboard_msg_id, guild_id, emoji):
    self.conn.execute(
      'INSERT INTO starboard_message '
      '(original_msg_id, starboard_msg_id, guild_id, emoji) '
      'VALUES (?, ?, ?, ?)',
      (original_msg_id, starboard_msg_id, guild_id, emoji)
    )
    self.conn.commit()

  def check_exists_starboard_message(self, original_msg_id, emoji):
    row = self.conn.execute(
      'SELECT 1 FROM starboard_message WHERE original_msg_id = ? AND emoji = ?',
      (original_msg_id, emoji)
    ).fetchone()
    return row is not None

  def remove_starboard_message(self, *, original_msg_id=None, starboard_msg_id=None):
    if original_msg_id is not None and isinstance(original_msg_id, tuple):
      orig, emoji = original_msg_id
      rc = self.conn.execute(
        'DELETE FROM starboard_message WHERE original_msg_id = ? AND emoji = ?',
        (orig, emoji)
      ).rowcount
    elif starboard_msg_id is not None:
      rc = self.conn.execute(
        'DELETE FROM starboard_message WHERE starboard_msg_id = ?',
        (starboard_msg_id,)
      ).rowcount
    else:
      rc = self.conn.execute(
        'DELETE FROM starboard_message WHERE original_msg_id = ?',
        (original_msg_id,)
      ).rowcount
    self.conn.commit(); return rc

  def close(self):
    self.conn.close()
