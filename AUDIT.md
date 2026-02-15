# TLE Codebase Audit

**Date:** 2026-02-14
**Scope:** Full codebase review - code quality, security, modernization, correctness
**Files Reviewed:** 32 Python files, Dockerfile, pyproject.toml, CI workflows, .env

---

## Table of Contents

1. [Critical Issues](#1-critical-issues)
2. [Security Vulnerabilities](#2-security-vulnerabilities)
3. [Dependency Issues](#3-dependency-issues)
4. [Code Quality Issues](#4-code-quality-issues)
5. [Architectural Issues](#5-architectural-issues)
6. [Discord.py Migration Issues](#6-discordpy-migration-issues)
7. [Database Issues](#7-database-issues)
8. [Performance Issues](#8-performance-issues)
9. [CI/CD Issues](#9-cicd-issues)
10. [Docker Issues](#10-docker-issues)
11. [Code Style & Conventions](#11-code-style--conventions)
12. [Per-File Findings](#12-per-file-findings)
13. [Modernization Roadmap](#13-modernization-roadmap)

---

## 1. Critical Issues

### CRIT-01: discord.py 1.7.3 is End-of-Life
**File:** `pyproject.toml:7`
**Severity:** Critical
**Description:** discord.py 1.7.3 was released in 2021 and is no longer maintained. The library has since released v2.x with breaking changes. The pinned version has known bugs, missing features (slash commands, modals, buttons), and no security updates.
**Impact:** No access to modern Discord features, potential security vulnerabilities, community support is gone.
**Fix:** Migrate to discord.py 2.x (or the maintained `py-cord` / `nextcord` fork). This is a major undertaking as v2 changed intents, event handlers, `avatar_url` -> `avatar.url`, cog loading, and many other APIs.

### CRIT-02: aiohttp Pinned Below 3.8
**File:** `pyproject.toml:8`
**Severity:** Critical
**Description:** `aiohttp < 3.8` pins to a version from 2021. Current aiohttp is 3.11+. This blocks security patches and compatibility with modern Python.
**Impact:** Known CVEs in old aiohttp versions. Incompatible with Python 3.12+.
**Fix:** Remove the upper bound pin after migrating to discord.py 2.x (which supports modern aiohttp).

### ~~CRIT-03: Synchronous SQLite Blocking the Event Loop~~ (RESOLVED)
**Status:** Fixed in Step 3. Migrated both `user_db_conn.py` and `cache_db_conn.py` from `sqlite3` to `aiosqlite`. All methods are now async, all callers updated to `await`.

### CRIT-04: In-Memory State Lost on Restart (PARTIALLY RESOLVED)
**File:** `tle/cogs/duel.py:456-479` (draw_offers), `tle/cogs/starboard.py` (locks)
**Severity:** Critical
**Description:** Duel draw offers (`self.draw_offers = {}`) are stored only in memory. If the bot restarts during a duel, draw state is lost. Similarly, starboard guild locks accumulate without cleanup.
**Impact:** Data loss on restart, inconsistent game state, potential memory leak from unbounded lock dict.
**Status:** Starboard locks bounded with LRU dict (maxsize=256) in Step 4. Duel draw persistence deferred to Step 9 (schema-breaking).

---

## 2. Security Vulnerabilities

### ~~SEC-01: SQL Injection via f-string Queries~~ (RESOLVED)
**Status:** Fixed in Step 3. All f-string SQL interpolation replaced with parameterized `?` placeholders.

### ~~SEC-02: `_insert_one` / `_insert_many` Use `.format()` for Table/Column Names~~ (RESOLVED)
**Status:** Fixed in Step 3. Added `_VALID_TABLES` and `_VALID_COLUMNS` allowlist validation before formatting.

### SEC-03: Subprocess Without Timeout
**File:** `tle/cogs/meta.py:28-43`
**Severity:** Medium
**Description:** `git_history()` runs `subprocess.Popen(['git', ...])` with `communicate()` but no timeout. A hanging git process would block indefinitely.
**Fix:** Add `timeout=10` to `communicate()`.

### SEC-04: No Input Validation on Rating/Contest Arguments
**File:** `tle/util/codeforces_common.py:334-338, 390-396`
**Severity:** Low
**Description:** `parse_rating()` calls `int(arg)` without range validation. A user could pass extremely large numbers. Similarly, rating filter args like `r>=99999999` are accepted.
**Fix:** Validate ratings are within reasonable bounds (e.g., 0-5000).

### ~~SEC-05: `os._exit()` Used for Bot Restart/Kill~~ (RESOLVED)
**Status:** Fixed in Steps 1 and 3. Replaced with `await bot.close()` + `sys.exit(0)` in Step 1. DB connections are now closed on shutdown via `bot.close` override in Step 3.

---

## 3. Dependency Issues

### DEP-01: Unpinned Major Dependencies
**File:** `pyproject.toml:10-18`
**Severity:** High
**Description:** `numpy`, `pandas`, `matplotlib`, `seaborn`, `pillow`, `pycairo`, `PyGObject`, `aiocache` have no version constraints. A `pip install` could pull incompatible major versions.
**Fix:** Pin to compatible ranges: `numpy>=1.24,<3`, `matplotlib>=3.7,<4`, etc.

### DEP-02: Missing `python-dotenv` Dependency
**File:** `tle/__main__.py`
**Severity:** Medium
**Description:** The bot reads from `.env` but relies on the shell environment or Docker to load it. There's no `python-dotenv` in dependencies, meaning `python -m tle` without Docker won't load `.env`.
**Fix:** Add `python-dotenv` and call `load_dotenv()` in `__main__.py`, or document that `.env` is only for Docker.

### DEP-03: `requires-python >= 3.9` Too Permissive
**File:** `pyproject.toml:4`
**Severity:** Low
**Description:** The code uses `str | int` union syntax (`constants.py:32`) which requires Python 3.10+. The `requires-python` should reflect this.
**Fix:** Change to `requires-python = ">= 3.10"` or use `Union[str, int]` from typing.

### DEP-04: No Lock File
**Severity:** Medium
**Description:** No `requirements.txt`, `poetry.lock`, or `uv.lock` exists. Builds are not reproducible.
**Fix:** Add a lock file mechanism. Consider migrating to `uv` or `poetry` for deterministic builds.

---

## 4. Code Quality Issues

### CQ-01: No Type Annotations
**Severity:** High
**Description:** Almost no functions have type hints. The few that exist are incomplete (e.g., `user_ids: [str]` at `user_db_conn.py:1060` is invalid - should be `list[str]`).
**Fix:** Add type annotations incrementally. Enable `mypy` or `pyright` in CI.

### CQ-02: Magic Numbers Throughout
**Severity:** Medium
**Files:** Multiple
**Examples:**
- `codeforces.py:332`: `delta // 100 + 3` (array index offset)
- `duel.py:120-124`: `_DUEL_INVALIDATE_TIME = 120` (seconds? minutes?)
- `cache_system2.py:42-45`: `30 * 60`, `5 * 60`, `20 * 60` (reload delays)
- `codeforces.py:41`: `_GITGUD_NO_SKIP_TIME = 3 * 60` (minutes, but reads as seconds)
- `rating_calculator.py:54`: `MAX = 6144` (unexplained bound)
**Fix:** Extract to well-named constants with units in the name (e.g., `_CONTEST_RELOAD_DELAY_SECONDS = 1800`).

### CQ-03: God Functions
**Severity:** Medium
**Examples:**
- `handles.py` `_update_ranks()` - ~100 lines handling role updates, rank detection, embed creation
- `contests.py` `_watch_rated_vc()` - ~75 lines with sequential API calls and rating calculations
- `graphs.py` `_plot_rating()` - ~60 lines combining data fetching, transformation, and plotting
**Fix:** Break into smaller, focused functions with single responsibilities.

### CQ-04: Inconsistent Error Handling Patterns
**Severity:** Medium
**Description:** Three different patterns coexist:
1. Custom exception + `@send_error_if` decorator (most cogs)
2. Bare `except: pass` (logging.py:61-62)
3. No error handling at all (some cache operations)
**Fix:** Standardize on the decorator pattern. Never use bare `except`.

### CQ-05: ~~Commented-Out and Dead Code~~ (RESOLVED)
**Status:** Fixed. The `deactivated/` directory and `cses_scraper.py` have been deleted.

### CQ-06: Typos in Source
**File:** `tle/util/discord_common.py:103`
**Description:** `"""Decorator that wraps a corouting asuch that it is executed only once."""` - "corouting asuch" should be "coroutine such".
**Fix:** Fix the docstring.

### CQ-07: `while True` Inside a Task
**File:** `tle/util/discord_common.py:138`
**Description:** `presence_task` contains a `while True` loop with `asyncio.sleep(10 * 60)` inside a task that itself uses `Waiter.fixed_delay(5 * 60)`. The inner loop means the waiter never fires after the first run.
**Fix:** Remove the inner `while True` loop and let the task framework handle repetition.

---

## 5. Architectural Issues

### ~~ARCH-01: Global Mutable Singletons~~ (RESOLVED)
**Status:** Fixed in Step 4. Services (`user_db`, `cache2`, `event_sys`) are now attached to the `bot` instance during `initialize(bot, nodb)`. Cogs access them via `self.bot.user_db`, etc. Module-level globals kept as aliases for utility code.

### ~~ARCH-02: Tight Coupling Between Cogs and Utility Modules~~ (RESOLVED)
**Status:** Fixed in Step 4. All cog methods access services through `self.bot.*` instead of importing globals. Module-level functions that can't use `self.bot` still use `cf_common.*` aliases.

### ~~ARCH-03: Cache System Is Too Complex~~ (RESOLVED)
**Status:** Fixed in Step 4. Split `cache_system2.py` (850 lines) into `tle/util/cache/` package with focused modules: `_common.py`, `contest.py`, `problem.py`, `problemset.py`, `rating_changes.py`, `ranklist.py`, `cache_system.py`. Old file replaced with backward-compat re-export shim.

### ARCH-04: No Separation Between Business Logic and Presentation
**Severity:** Medium
**Description:** Cog methods mix data fetching, business logic, embed creation, and response sending in single functions. For example, `contests.py`'s ranklist command fetches standings, formats tables, creates embeds, and paginates all in one method.
**Fix:** Extract business logic into service classes. Keep cogs thin - only parsing input and sending output.

### ARCH-05: Custom Task Framework vs discord.py Tasks
**File:** `tle/util/tasks.py` (251 lines)
**Severity:** Low
**Description:** A custom task framework was built instead of using `discord.ext.tasks`. While more flexible, it's non-standard and adds maintenance burden.
**Fix:** Evaluate whether discord.py 2.x's improved `tasks.loop` can replace this. If not, keep but document thoroughly.

---

## 6. Discord.py Migration Issues

These issues must be addressed when migrating from discord.py 1.7.3 to 2.x:

### DPY-01: `avatar_url` Deprecated
**File:** `tle/util/discord_common.py:50`
**Description:** `user.avatar_url` -> `user.display_avatar.url` in v2.
**Fix:** Update all `avatar_url` references.

### DPY-02: `Embed.Empty` Removed
**File:** `tle/util/discord_common.py:19`
**Description:** `discord.Embed.Empty` -> `None` in v2.
**Fix:** Replace with `None`.

### DPY-03: Synchronous `setup()` Function in Cogs
**File:** All cog files (e.g., `codeforces.py:618`)
**Description:** `def setup(bot): bot.add_cog(...)` must become `async def setup(bot): await bot.add_cog(...)` in v2.
**Fix:** Make all `setup()` functions async.

### DPY-04: `bot.load_extension()` Is Now Async
**File:** `tle/__main__.py:88`
**Description:** `bot.load_extension(...)` must be awaited in v2.
**Fix:** Move extension loading into an async setup hook.

### DPY-05: Intent Changes
**File:** `tle/__main__.py:82-83`
**Description:** v2 requires `intents.message_content = True` for reading message content. The current code only enables `intents.members`.
**Fix:** Add `intents.message_content = True`.

### DPY-06: `guild.icon_url` Removed
**File:** `tle/cogs/meta.py` (guilds command)
**Description:** `guild.icon_url` -> `guild.icon.url` in v2 (with None check).
**Fix:** Update with null safety.

### DPY-07: Slash Commands Not Supported
**Severity:** Medium
**Description:** The bot uses only prefix commands (`;`). Modern Discord bots should support slash commands for discoverability.
**Fix:** Add hybrid commands or migrate to app commands after v2 migration.

---

## 7. Database Issues

### DB-01: No Migration System
**File:** `tle/util/db/user_db_conn.py:238-288`
**Severity:** High
**Description:** Database migrations are inline `if old_exists and not migrated:` blocks in `create_tables()`. This doesn't scale and makes schema evolution error-prone.
**Fix:** Use Alembic, or at minimum a versioned migration system with a `schema_version` table.

### ~~DB-02: Inconsistent Transaction Management~~ (PARTIALLY RESOLVED)
**Status:** Improved in Step 3. Simple writes use `async with conn:`. Methods with conditional rollback logic kept explicit `commit()`/`rollback()` since context managers can't express that pattern.

### ~~DB-03: `namedtuple_factory` Silently Drops Columns~~ (RESOLVED)
**Status:** Fixed in Step 3. Now raises `ValueError` on non-identifier column names instead of silently dropping them.

### ~~DB-04: `_fetchone`/`_fetchall` Temporarily Replace `row_factory`~~ (RESOLVED)
**Status:** Fixed in Step 3. Now uses cursor-level `row_factory` instead of mutating `conn.row_factory`.

### DB-05: Mixed `user_id` Types
**File:** `tle/util/db/user_db_conn.py`
**Severity:** Medium
**Description:** `user_id` is stored as `TEXT` in `user_handle` but as `INTEGER` in `duelist`. Discord IDs are large integers (snowflakes). The inconsistency requires casting at boundaries (e.g., `int(user_id)` at line 547).
**Fix:** Standardize on `INTEGER` for all Discord IDs.

### ~~DB-06: No Database Connection Closing~~ (RESOLVED)
**Status:** Fixed in Step 3. `bot.close` is overridden in `__main__.py` to close both `user_db` and `cache_db` connections on shutdown.

### DB-07: Duel Tables Not Guild-Scoped
**File:** `tle/util/db/user_db_conn.py:107`
**Description:** The `duelist` and `duel` tables have no `guild_id` column. A user's duel rating is shared across all guilds the bot serves. There's even a TODO comment acknowledging this.
**Fix:** Add `guild_id` to duel tables with migration.

---

## 8. Performance Issues

### ~~PERF-01: N+1 Query Pattern in Handle Resolution~~ (RESOLVED)
**Status:** Fixed in Step 4. Replaced sequential loop with `asyncio.gather()`. Rate limit still respected via shared `@cf_ratelimit` decorator on `_query_api`.

### PERF-02: Entire Problemset in Memory
**File:** `tle/util/cache_system2.py`
**Severity:** Medium
**Description:** The problem cache loads all ~10,000+ CF problems into memory as Python objects. Combined with the contest cache and ranklist cache, memory usage can be significant.
**Fix:** Consider lazy loading or database-backed queries for less frequently accessed data.

### PERF-03: FFT-Based Rating Calculator
**File:** `tle/util/ranklist/rating_calculator.py:53-65`
**Description:** Uses numpy FFT to precompute seeds for all possible ratings (array size 12288). While mathematically elegant, this is heavy for what could be a simpler computation, especially for small contests.
**Fix:** Profile and consider a direct computation for small contest sizes.

### ~~PERF-04: Temporary File I/O for Every Plot~~ (RESOLVED)
**Status:** Fixed in Step 4. Replaced temp file with `io.BytesIO()` in-memory buffer. Added `plt.close()` to prevent matplotlib memory leak.

### PERF-05: `guild.icon_url` Iteration in Presence
**File:** `tle/util/discord_common.py:139-145`
**Description:** `bot.get_all_members()` iterates ALL members in ALL guilds every 10 minutes to pick one random member. For large bots, this could be thousands of members.
**Fix:** Cache the member list or use `random.choice(guild.members)` on a single guild.

---

## 9. CI/CD Issues

### CI-01: Outdated GitHub Actions
**File:** `.github/workflows/lint.yaml:13-14, build.yaml:13`
**Severity:** Medium
**Description:** Uses `actions/checkout@v3` and `actions/setup-python@v4`. Current versions are v4 and v5 respectively.
**Fix:** Update to latest action versions.

### CI-02: No Test Job in CI
**Severity:** High
**Description:** Despite having `pytest` as an optional dependency, there are no tests and no test job in CI.
**Fix:** Add tests and a test job. See TESTING_PLAN.md.

### CI-03: Lint Job Pins Python 3.11 But Project Requires 3.9+
**File:** `.github/workflows/lint.yaml:16-17`
**Severity:** Low
**Description:** Lint only runs on 3.11. Should test on all supported versions, or at minimum on the declared minimum version.
**Fix:** Add matrix for supported Python versions.

### CI-04: Ruff Not Pinned to a Version
**File:** `.github/workflows/lint.yaml:18`
**Description:** `pip install ruff` installs the latest version. A new ruff release with new rules could break CI.
**Fix:** Pin ruff version: `pip install ruff==0.x.y`.

### CI-05: No Security Scanning
**Severity:** Medium
**Description:** No dependency vulnerability scanning (e.g., `pip-audit`, `safety`, Dependabot).
**Fix:** Add `pip-audit` step to CI and enable Dependabot.

---

## 10. Docker Issues

### DOCK-01: Build Dependencies in Final Image
**File:** `Dockerfile:3-8`
**Severity:** Medium
**Description:** `build-essential`, `cmake`, `gcc`, `meson` are installed and remain in the final image. These are only needed for compiling Python packages.
**Fix:** Use multi-stage build: compile in builder stage, copy only runtime dependencies to final stage.

### DOCK-02: No Health Check
**Severity:** Low
**Description:** No `HEALTHCHECK` instruction. Docker/orchestrators can't monitor bot health.
**Fix:** Add a health check (e.g., HTTP endpoint or file touch).

### DOCK-03: Running as Root
**Severity:** Medium
**Description:** No `USER` instruction. The bot runs as root inside the container.
**Fix:** Add `RUN useradd -m botuser` and `USER botuser`.

### DOCK-04: `COPY . .` Copies Unnecessary Files
**File:** `Dockerfile:18`
**Severity:** Low
**Description:** No `.dockerignore` file. `COPY . .` includes `.git/`, `.env`, `data/`, IDE files, etc.
**Fix:** Create `.dockerignore` with `.git`, `.env`, `data/`, `logs/`, `__pycache__/`, `.vscode/`, `.idea/`.

### DOCK-05: `pip install .` in Dockerfile Installs Editable
**File:** `Dockerfile:16`
**Severity:** Low
**Description:** `pip install --no-cache-dir .` installs the package in the workdir. This is fine, but the subsequent `COPY . .` overwrites the installed package with source. The bot runs via `python -m tle` which uses the source directly.
**Fix:** Either install properly and remove source, or don't install and just run from source (current effective behavior).

---

## 11. Code Style & Conventions

### STY-01: Inconsistent String Formatting
**Description:** Mix of f-strings, `.format()`, and `%` formatting across the codebase.
**Fix:** Standardize on f-strings everywhere.

### STY-02: Leading Underscore Convention Inconsistent
**Description:** Some admin commands use `_` prefix (`_nogud`, `_invalidate`), others don't (`cache`). No clear convention.
**Fix:** Document convention and apply consistently.

### STY-03: Missing Module-Level Docstrings
**Description:** Most modules have no docstring explaining their purpose.
**Fix:** Add docstrings to all modules.

### STY-04: Inconsistent Import Ordering
**Description:** Some files import `discord` before stdlib, others follow PEP 8 ordering.
**Fix:** Enable `ruff`'s import sorting rules (`I` ruleset).

### ~~STY-05: `os.path` vs `pathlib.Path`~~ (RESOLVED)
**Status:** Fixed in Step 4. All paths in `tle/constants.py` migrated from `os.path.join` to `pathlib.Path` `/` operator.

---

## 12. Per-File Findings

### `tle/__main__.py` (112 lines)
| Line | Issue | Severity |
|------|-------|----------|
| 38 | `plt.rcParams` set globally during import-time setup | Low |
| 85 | Hardcoded command prefix `;` - should be configurable | Low |
| 86 | `Path('tle', 'cogs')` uses relative path - breaks if CWD changes | Medium |
| 88 | `bot.load_extension()` is sync - needs async in discord.py 2.x | High |
| 104 | `asyncio.create_task(discord_common.presence(bot))` - task not awaited or tracked | Low |

### `tle/constants.py` (48 lines)
| Line | Issue | Severity |
|------|-------|----------|
| 3 | `DATA_DIR = 'data'` - relative path, breaks if CWD changes | Medium |
| 23-27 | `ALL_DIRS` is a generator expression - can only be iterated once | Medium |
| 32 | `str | int` return type requires Python 3.10+ but `requires-python >= 3.9` | Low |
| 46-47 | `_DEFAULT_COLOR` and `_DEFAULT_STAR` use leading underscore but are imported by other modules | Low |

### `tle/util/codeforces_api.py` (682 lines)
| Line | Issue | Severity |
|------|-------|----------|
| ~360 | Global `_session` initialized lazily, not thread-safe | Medium |
| ~375-407 | Rate limiter retries 3 times with 1s delay - doesn't handle 429 properly | Medium |
| ~532 | Chunk size 10000 for batch user info - no adaptive sizing | Low |
| ~625 | `_resolve_redirect()` only handles specific redirect patterns | Low |
| Various | All NamedTuples use camelCase (matching CF API) - Pythonic would be snake_case | Low |

### `tle/util/codeforces_common.py` (485 lines)
| Line | Issue | Severity |
|------|-------|----------|
| 31 | `active_groups = defaultdict(set)` - race condition in async context | Medium |
| 72-73 | `active` set captured at decoration time, not dynamically | Low |
| 131 | `handles: [str]` is not valid type annotation (should be `list[str]`) | Low |
| 272 | `member_identifier[-2:] == '#0'` - hardcoded Discord discriminator removal hack | Medium |
| 351 | `self.dhi = 10**10` - magic number for max timestamp | Low |

### `tle/util/discord_common.py` (153 lines)
| Line | Issue | Severity |
|------|-------|----------|
| 50 | `user.avatar_url` - deprecated in discord.py 2.x | High |
| 103 | Typo in docstring: "corouting asuch" | Low |
| 138 | `while True` inside task function - waiter never re-fires | Medium |
| 143-144 | `constants.TLE_PURGATORY` compared to `role.name` - fails if configured as role ID | Medium |

### ~~`tle/util/cache_system2.py`~~ → `tle/util/cache/` package
| Line | Issue | Severity |
|------|-------|----------|
| 20 | `CONTEST_BLACKLIST = {1308, 1309, 1431, 1432}` - hardcoded, should be configurable | Low |
| 70-77 | `reload_now()` race: checks `locked()` then acts - TOCTOU | Medium |
| ~249 | Problem name collisions silently overwrite data | Medium |
| ~~Various~~ | ~~Five cache classes with different patterns in one file~~ | ~~RESOLVED - split into focused modules~~ |

### `tle/util/db/user_db_conn.py` (1167 lines)
| Line | Issue | Severity |
|------|-------|----------|
| ~~65~~ | ~~`isidentifier()` filter can silently drop columns~~ | ~~RESOLVED~~ |
| 107 | TODO: duel tables not guild-aware (since original code) | High |
| 238-288 | Migration code mixed with schema creation | Medium |
| ~~292-308~~ | ~~`_insert_one`/`_insert_many` use `.format()` for SQL~~ | ~~RESOLVED~~ |
| ~~310-314~~ | ~~`_fetchone` mutates shared `conn.row_factory`~~ | ~~RESOLVED~~ |
| 369 | Tuple unpacking assumes column order `c_id, issue_time = res` | Low |
| ~~401-403~~ | ~~f-string in SQL query (safe here but bad pattern)~~ | ~~RESOLVED~~ |

### `tle/cogs/codeforces.py`
| Line | Issue | Severity |
|------|-------|----------|
| ~147 | `max(random.randrange()...)` for weighted random - unclear intent | Low |
| ~332 | `delta // 100 + 3` - magic index offset | Low |
| ~573-619 | `teamrate` has nested normalization with magic math | Low |

### `tle/cogs/contests.py`
| Line | Issue | Severity |
|------|-------|----------|
| ~174-202 | All guild tasks rescheduled on any contest update | Medium |
| ~188 | `json.loads(before)` without try/except | Medium |
| ~364-397 | Duplicated CF/IOI standings formatting logic | Low |
| ~752-826 | `_watch_rated_vc()` is very long, sequential async calls | Medium |

### `tle/cogs/duel.py`
| Line | Issue | Severity |
|------|-------|----------|
| ~244 | 5-minute `asyncio.sleep()` blocking pattern | Medium |
| ~456-479 | `draw_offers` dict not persisted | High |
| ~571-572 | No cleanup of expired draw offers | Medium |
| ~213-216 | Double `randrange` loop for problem selection is inefficient | Low |

### `tle/cogs/graphs.py`
| Line | Issue | Severity |
|------|-------|----------|
| ~670 | Parameter validation after parsing (should validate early) | Low |
| ~737-744 | Color generation uses `assert` instead of proper error handling | Medium |
| ~774-789 | Figure size hardcoded `(1500, 500)` | Low |

### `tle/cogs/handles.py`
| Line | Issue | Severity |
|------|-------|----------|
| ~359-420 | `maybe_add_trusted_role()` with deeply nested try/except | Medium |
| ~607-609 | Font loading with no error handling | Low |
| ~775-776 | `zip()` without `strict=True` could silently truncate | Medium |
| ~1162-1228 | `grandfather()` is 66 lines with high cyclomatic complexity | Medium |

### `tle/cogs/logging.py`
| Line | Issue | Severity |
|------|-------|----------|
| ~61-62 | Bare `except: pass` silences all errors | Medium |
| ~45-52 | Silent attribute access errors | Low |
| N/A | No backpressure on log queue | Low |

### `tle/cogs/meta.py`
| Line | Issue | Severity |
|------|-------|----------|
| ~~28-43~~ | ~~subprocess with no timeout~~ | ~~RESOLVED~~ |
| ~~63~~ | ~~`os._exit(42)` bypasses cleanup~~ | ~~RESOLVED~~ |
| ~~70~~ | ~~`os._exit(0)` bypasses cleanup~~ | ~~RESOLVED~~ |

### `tle/cogs/starboard.py`
| Line | Issue | Severity |
|------|-------|----------|
| ~~~97~~ | ~~`self.locks.setdefault()` creates unbounded dict growth~~ | ~~RESOLVED - replaced with LRU-bounded `_BoundedLockDict(maxsize=256)`~~ |
| ~66-67 | Incomplete image type checking | Low |

### `tle/util/graph_common.py` (67 lines)
| Line | Issue | Severity |
|------|-------|----------|
| ~~39-50~~ | ~~Temp file not cleaned up on exception (no try/finally)~~ | ~~RESOLVED - replaced with `io.BytesIO()`~~ |
| ~~N/A~~ | ~~No `plt.close()` after figure creation - memory leak~~ | ~~RESOLVED - added `plt.close()`~~ |
| N/A | Hardcoded font path with no fallback | Low |

### `tle/util/events.py` (188 lines)
| Line | Issue | Severity |
|------|-------|----------|
| N/A | Event listeners accumulate without cleanup for removed cogs | Low |

### `tle/util/paginator.py` (103 lines)
| Line | Issue | Severity |
|------|-------|----------|
| N/A | Uses reaction-based pagination (deprecated Discord pattern) | Low |

### ~~`tle/util/cses_scraper.py`~~ (DELETED)

---

## 13. Modernization Roadmap

### Phase 1: Safety & Stability (Immediate)
1. Rotate the bot token
2. Fix `os._exit()` calls to use proper shutdown
3. Add subprocess timeout to `git_history()`
4. Fix bare `except` in logging cog
5. Pin all dependency versions
6. Create `.dockerignore`
7. ~~Close CSES scraper session properly (or remove)~~ (DONE - removed)
8. Fix `ALL_DIRS` generator-consumed-once bug in constants.py

### Phase 2: discord.py 2.x Migration
1. Update `discord.py` to 2.x
2. Remove `aiohttp < 3.8` pin
3. Fix all deprecated APIs (avatar_url, Embed.Empty, etc.)
4. Make cog `setup()` functions async
5. Add `message_content` intent
6. Move extension loading to async setup hook
7. Update `requires-python` to `>= 3.10`

### Phase 3: Database Modernization
1. ~~Migrate from `sqlite3` to `aiosqlite`~~ (DONE)
2. ~~Standardize transaction management (context managers)~~ (DONE where appropriate)
3. Standardize `user_id` types to INTEGER (deferred to Step 9)
4. Implement proper migration system (versioned SQL files)
5. Move migration code out of `create_tables()`
6. Add guild_id to duel tables

### Phase 4: Architecture Improvements
1. ~~Replace global singletons with dependency injection via bot instance~~ (DONE)
2. ~~Split `cache_system2.py` into separate modules per cache~~ (DONE)
3. Extract business logic from cogs into service classes
4. ~~Use `io.BytesIO()` for plot generation instead of temp files~~ (DONE)
5. Add proper type annotations throughout
6. Replace custom task framework with discord.py 2.x tasks (evaluate feasibility)

### Phase 5: Modern Discord Features
1. Add hybrid commands (prefix + slash)
2. Implement button/select-based pagination (replace reaction pagination)
3. Add modals for complex input (handle registration)
4. Use embeds with components for interactive features (duel accept/decline)

### Phase 6: Testing & CI
1. Add unit tests (see TESTING_PLAN.md)
2. Add integration tests
3. Update GitHub Actions versions
4. Pin ruff version
5. Add `pip-audit` security scanning
6. Add type checking (mypy/pyright) to CI
7. Add test coverage reporting

### Phase 7: Docker & Deployment
1. Multi-stage Docker build
2. Run as non-root user
3. Add health check
4. Consider Docker Compose for development
5. Add secrets management
