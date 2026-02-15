# TLE Architecture Document

## Overview

TLE (Time Limit Exceeded) is a Discord bot for competitive programming communities, built around the Codeforces platform. It provides problem recommendations, contest tracking, dueling, performance visualization, and community management features.

**Tech Stack:** Python 3.10+, discord.py 2.x, aiosqlite, aiohttp, matplotlib/seaborn, numpy, Pillow, PyCairo/PyGObject, PyJWT

---

## High-Level Architecture

```
Discord Gateway
       |
       v
+------------------+
|   Bot Runtime    |  tle/__main__.py
|  (commands.Bot)  |  - Entry point, arg parsing, cog loading
+------------------+
       |
       +--- bot.user_db          (UserDbConn)
       +--- bot.cf_cache         (CacheSystem)
       +--- bot.event_sys        (EventSystem)
       +--- bot.oauth_server     (OAuthServer, optional)
       +--- bot.oauth_state_store (OAuthStateStore, optional)
       |
       v
+------------------+     +-------------------+
|     Cogs (9)     |---->|   Utility Layer   |
| (Command Groups) |     | codeforces_common |
+------------------+     | discord_common    |
       |                  +-------------------+
       |                         |
       v                         v
+------------------+     +-------------------+
|  Cache System    |     |   Database Layer  |
| util/cache/      |     | (aiosqlite)       |
| (5 sub-caches)   |     | user_db_conn.py   |
+------------------+     | cache_db_conn.py  |
       |                  +-------------------+
       v                         |
+------------------+             v
| Codeforces API   |     +-------------------+
| codeforces_api.py|     |     SQLite3       |
+------------------+     | data/db/user.db   |
                         | data/db/cache.db  |
                         +-------------------+
```

---

## Directory Structure

```
TLE/
├── tle/
│   ├── __init__.py
│   ├── __main__.py              # Entry point: bot setup, cog loading, initialization
│   ├── constants.py             # Paths, role names, env config, feature flags, OAuth config
│   ├── cogs/                    # Discord command modules (Cog pattern)
│   │   ├── cache_control.py     # Admin cache management commands
│   │   ├── codeforces.py        # Problem recommendations, gitgud, upsolve, mashup
│   │   ├── contests.py          # Contest listing, reminders, rated virtual contests
│   │   ├── duel.py              # 1v1 dueling system with ELO ratings
│   │   ├── graphs.py            # matplotlib/seaborn visualizations
│   │   ├── handles.py           # Handle registration, role management, rank updates
│   │   ├── logging.py           # Discord channel logging handler
│   │   ├── meta.py              # Bot control: restart, kill, ping, uptime
│   │   └── starboard.py         # Reaction-based message archival
│   └── util/
│       ├── __init__.py
│       ├── codeforces_api.py    # CF API wrapper with rate limiting and data models
│       ├── codeforces_common.py # Shared logic: handle resolution, filtering, globals
│       ├── discord_common.py    # Embed helpers, error handler, presence system
│       ├── events.py            # Pub/sub event system for inter-component communication
│       ├── graph_common.py      # matplotlib setup, BytesIO plotting, rating backgrounds
│       ├── handledict.py        # Case-insensitive handle dictionary
│       ├── oauth.py             # Codeforces OAuth (OIDC) state store, token handling, callback server
│       ├── paginator.py         # Discord message pagination with reactions
│       ├── table.py             # ASCII table formatter
│       ├── tasks.py             # Custom async task framework (Task, TaskSpec, Waiter)
│       ├── cache/               # Modular cache system (split from former cache_system2.py)
│       │   ├── __init__.py      # Re-exports CacheSystem and error types
│       │   ├── _common.py       # Shared cache utilities
│       │   ├── cache_system.py  # CacheSystem orchestrator
│       │   ├── contest.py       # ContestCache
│       │   ├── problem.py       # ProblemCache
│       │   ├── problemset.py    # ProblemsetCache
│       │   ├── ranklist.py      # RanklistCache
│       │   └── rating_changes.py # RatingChangesCache
│       ├── db/
│       │   ├── __init__.py      # Re-exports db connections
│       │   ├── cache_db_conn.py # Async cache for CF API data (aiosqlite)
│       │   └── user_db_conn.py  # Async user data: handles, duels, challenges, starboard
│       └── ranklist/
│           ├── __init__.py
│           ├── ranklist.py      # Contest ranklist construction and querying
│           └── rating_calculator.py  # FFT-based CF rating calculator
├── extra/
│   └── scrape_cf_contest_writers.py
├── data/                        # Runtime data (gitignored)
│   ├── db/                      # SQLite databases
│   ├── misc/                    # contest_writers.json
│   └── temp/                    # Temporary plot images
├── logs/                        # Rotating log files (gitignored)
├── .github/workflows/
│   ├── build.yaml               # Docker build CI
│   └── lint.yaml                # Ruff linting CI
├── pyproject.toml               # PEP 517 project config with pinned dependencies
├── ruff.toml                    # Linting configuration
├── Dockerfile                   # Multi-stage Python 3.11-slim container
├── docker-compose.yaml          # Single-service deployment
├── .env                         # Bot token and config (gitignored)
└── .gitignore
```

---

## Component Deep-Dive

### 1. Bot Runtime (`tle/__main__.py`)

The entry point performs:
1. Loads `.env` with `python-dotenv`
2. Parses `--nodb` CLI flag
3. Creates required data directories
4. Configures logging (console + daily rotating file)
5. Sets up matplotlib/seaborn defaults
6. Creates a `TLEBot(commands.Bot)` subclass with prefix `;` (or mention), member intents, and `message_content` intent
7. In `setup_hook()`: auto-discovers and loads all cogs from `tle/cogs/*.py`, then calls `cf_common.initialize(bot, nodb)`
8. Registers a global DM check (commands only work in guilds)
9. On ready: starts the presence update task
10. Overrides `close()` to gracefully close database connections on shutdown

**Initialization order is guaranteed by `setup_hook()`:** This runs before the bot connects to Discord, so all cogs are loaded, `cf_common.initialize()` completes (setting up database connections, cache system, and event system as `bot.user_db`, `bot.cf_cache`, `bot.event_sys`), and the OAuth callback server starts (if configured) before any events or commands are processed.

### 2. Cog Layer (`tle/cogs/`)

Each cog is a `commands.Cog` subclass that groups related commands. Cogs access services via `self.bot.user_db`, `self.bot.cf_cache`, and `self.bot.event_sys`:

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(brief='...', usage='...')
    async def my_command(self, ctx, ...):
        ...

    @discord_common.send_error_if(MyCogError)
    async def cog_command_error(self, ctx, error):
        pass

async def setup(bot):
    await bot.add_cog(MyCog(bot))
```

| Cog | Commands | Responsibility |
|-----|----------|---------------|
| **CacheControl** | 4 | Admin-only cache reload operations |
| **Codeforces** | 13 | Problem recommendation, gitgud challenges, upsolve, mashup, team rating |
| **Contests** | 12 | Contest listing, reminders, ranklist, rated virtual contests |
| **Dueling** | 17 | 1v1 challenges with ELO rating, draws, history, rankings |
| **Graphs** | 13 | Rating plots, solve history, distributions, country comparisons |
| **Handles** | 17 | Handle linking (via Codeforces OAuth), role management, rank updates, trusted roles |
| **Logging** | 0 | Background log handler sending warnings to a Discord channel |
| **Meta** | 5 | Bot control: kill, ping, git info, uptime, guild list |
| **Starboard** | 7 | Multi-emoji reaction archival with configurable thresholds |

### 3. Cache System (`tle/util/cache/`)

The cache system is organized as a package with each cache in its own module, coordinated by `CacheSystem` in `cache_system.py`:

```
CacheSystem (cache_system.py)
├── ContestCache      (contest.py)       # All CF contests, refreshes every 30m (5m when active)
├── ProblemCache      (problem.py)       # Problemset with ratings/tags, refreshes every 6h
├── ProblemsetCache   (problemset.py)    # Per-contest problems from standings, monitors 14 days post-finish
├── RatingChangesCache (rating_changes.py) # Rating changes for finished contests, monitors up to 36h
└── RanklistCache     (ranklist.py)      # Standings with predictions for running contests
```

Shared utilities live in `_common.py`. The `__init__.py` re-exports `CacheSystem` and error types for clean imports.

Each cache uses the custom `TaskSpec` framework (not discord.py's `tasks.loop`) for periodic updates with dynamic delays. Caches persist to SQLite (via `CacheDbConn`) and reload from disk on startup for fast restarts.

**Event flow:** When `RatingChangesCache` detects new rating changes, it fires a `RatingChangesUpdate` event via `EventSystem`, which `Handles` cog listens to for automatic rank role updates.

### 4. Database Layer (`tle/util/db/`)

Two SQLite databases accessed asynchronously via `aiosqlite`, with direct parameterized SQL queries (no ORM). Connections use a two-step initialization pattern: `__init__(path)` followed by `async connect()`.

```python
# Initialization in cf_common.initialize()
user_db = db.UserDbConn(constants.USER_DB_FILE_PATH)
await user_db.connect()  # Opens aiosqlite connection and creates tables

cache_db = db.CacheDbConn(constants.CACHE_DB_FILE_PATH)
await cache_db.connect()
```

**`user.db`** (via `UserDbConn`) - 13 tables:
- `user_handle` - Discord-to-CF handle mapping (guild-scoped)
- `cf_user_cache` - Cached CF user profiles
- `duelist`, `duel` - Duel system with ELO ratings
- `challenge`, `user_challenge` - Gitgud challenge tracking
- `reminder` - Contest reminder settings per guild
- `rankup`, `auto_role_update` - Role update configuration
- `rated_vcs`, `rated_vc_users`, `rated_vc_settings` - Virtual contest rating
- `starboard_config_v1`, `starboard_emoji_v1`, `starboard_message_v1` - Starboard

**`cache.db`** (via `CacheDbConn`) - 4 tables:
- `contest` - Cached contest metadata
- `problem` - Problem metadata with JSON-serialized tags
- `problem2` - Problemset-specific problem data
- `rating_change` - Historical rating changes

All database methods are async and all call sites use `await`.

### 5. Codeforces API Client (`tle/util/codeforces_api.py`)

A full async wrapper around the Codeforces REST API:

- **Data Models:** 10 NamedTuple classes (`User`, `Problem`, `Contest`, `Submission`, `RatingChange`, `Party`, `Member`, `RanklistRow`, `ProblemResult`, `ProblemStatistics`)
- **Rate Limiting:** 1 request/second with 3 retries on `CallLimitExceeded`
- **Session Management:** Global `aiohttp.ClientSession` initialized once
- **Handle Resolution:** Batch redirect detection for renamed accounts
- **Endpoints:** `contest.list`, `contest.ratingChanges`, `contest.standings`, `problemset.problems`, `user.info`, `user.rating`, `user.ratedList`, `user.status`

### 6. Event System (`tle/util/events.py`)

A pub/sub system enabling loose coupling between components:

```python
# Publisher (in cache modules)
cf_common.event_sys.dispatch(events.ContestListRefresh, contests)

# Subscriber (in cogs, via task framework)
@tasks.task_spec(name='...', waiter=tasks.Waiter.for_event(events.ContestListRefresh))
async def _update_task(self, _):
    ...
```

Events: `ContestListRefresh`, `RatingChangesUpdate`

### 7. Custom Task Framework (`tle/util/tasks.py`)

A custom alternative to `discord.ext.tasks` providing:
- **`Task`**: Repeating async task with waiter, exception handler, manual trigger
- **`TaskSpec`**: Descriptor-based task that auto-creates per-instance tasks
- **`Waiter`**: Pluggable wait strategies (fixed delay, event-based, custom)

This framework is used throughout the cache system and by background maintenance tasks.

### 8. OAuth / Codeforces OpenID Connect (`tle/util/oauth.py`)

The `identify` command uses Codeforces's OpenID Connect (OAuth 2.0) flow to verify handle ownership. This replaces the older compile-error verification method with a one-click authorization link.

**Components:**
- **`OAuthStateStore`** — In-memory `dict[str, OAuthPending]` mapping state tokens to `(user_id, guild_id, channel_id)` with 5-minute TTL and single-use consumption
- **`OAuthServer`** — aiohttp web server (default port 8080) with a `/callback` route that handles the authorization code exchange
- **Helper functions:** `build_auth_url()`, `exchange_code()`, `decode_id_token()` (HS256 via PyJWT with issuer/audience/expiry validation)

**Flow:**
```
User runs ;handle identify
  -> Bot generates state token, stores mapping
  -> Bot sends Discord message with "Link Codeforces Account" link button
  -> User clicks, logs in on CF, authorizes
  -> CF redirects to /callback?code=...&state=...
  -> OAuthServer exchanges code for ID token at CF token endpoint
  -> Decodes ID token (HS256) -> extracts handle
  -> Fetches full CF user info via cf.user.info()
  -> Calls handles_cog._set_from_oauth(guild, member, user)
  -> Sends confirmation embed to Discord channel
  -> Returns success HTML to browser
```

**Configuration:** Requires `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_REDIRECT_URI` environment variables. When not set, `constants.OAUTH_CONFIGURED` is `False` and the `identify` command shows a configuration error. The server is only started when OAuth is configured.

### 9. Visualization (`tle/util/graph_common.py` + `tle/cogs/graphs.py`)

Generates matplotlib/seaborn plots as Discord file attachments:
- Rating history over time (by contest or date)
- Solve statistics and histograms
- Performance scatter plots
- Rating distributions (server-wide and global CF)
- Country comparisons
- Speed analysis

Plots are rendered to in-memory `BytesIO` buffers (not temp files on disk) and sent as Discord `File` attachments. Cairo/Pango is used for advanced text rendering (handle lists with rating colors). CJK fonts are installed as system packages in the Docker image (`fonts-noto-cjk`).

---

## Data Flow Examples

### Command: `;gimme dp 1400`
```
User Input -> Bot.process_commands -> Codeforces.gimme()
  -> Parse tags ["dp"], rating 1400
  -> cf_common.cf_cache.problem_cache.problems (cached list)
  -> Filter by tag, rating, exclude solved
  -> cf.user.status(handle=...) to get submissions
  -> Random selection from matching problems
  -> Create embed with problem link
  -> ctx.send(embed)
```

### Background: Rating Change Detection
```
RatingChangesCache._update_task fires periodically
  -> cf.contest.ratingChanges(contest_id=...)
  -> Store in cache_db (via aiosqlite)
  -> event_sys.dispatch(RatingChangesUpdate)
  -> Handles cog listener wakes up
  -> For each guild with auto_role_update enabled:
     -> Fetch new ratings, compare to old
     -> Update Discord roles to match new rank
     -> Post rank changes to configured channel
```

---

## Configuration

| Source | Variables |
|--------|-----------|
| `.env` | `BOT_TOKEN`, `LOGGING_COG_CHANNEL_ID`, `ALLOW_DUEL_SELF_REGISTER` |
| `.env` (OAuth) | `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`, `OAUTH_SERVER_PORT` (default 8080) |
| Environment | `TLE_ADMIN`, `TLE_MODERATOR`, `TLE_TRUSTED`, `TLE_PURGATORY` (role names or IDs) |
| Runtime | `--nodb` flag disables database (uses `DummyUserDbConn`) |

---

## Docker Deployment

The Dockerfile uses a multi-stage build:

1. **Builder stage** (`python:3.11-slim`): Compiles native dependencies (cairo, PyGObject, PIL) with build tools
2. **Runtime stage** (`python:3.11-slim`): Slim image with only runtime libraries, CJK fonts, and compiled packages
3. Runs as non-root `botuser` for security
4. `docker-compose.yaml` defines a single service with `./data` volume mount, `.env` passthrough, and OAuth callback port exposure

---

## Known Architectural Limitations

1. **Global mutable singletons** - `user_db`, `cf_cache`, `event_sys`, `active_groups` live as module-level globals in `codeforces_common.py` (also attached to bot instance for cog access)
2. **No ORM or migration system** - Raw SQL with inline schema creation and migration code mixed into `create_tables()`
3. **In-memory state not persisted** - Duel draw offers, active command guards, and guild locks exist only in memory
