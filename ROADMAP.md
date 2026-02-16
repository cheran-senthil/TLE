# TLE Modernization Roadmap

This roadmap orders all fixes from AUDIT.md to minimize risk and maximize value at each step. Changes are grouped into steps where each step builds on the previous one. Within each step, items are ordered by dependency (do the first items first).

---

## Step 1: Quick Safety Fixes

**Risk:** Minimal | **Effort:** Small | **Blocks:** Nothing, but prevents data loss and hangs

These are isolated, low-risk changes that fix real bugs. Each can be done and verified independently in minutes.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~1a~~ | ~~SEC-05~~ | ~~`tle/cogs/meta.py`~~ | ~~DONE - removed `restart` command (shell script no longer exists), replaced `os._exit(0)` with `await bot.close()` + `sys.exit(0)` in `kill`~~ |
| ~~1b~~ | ~~SEC-03~~ | ~~`tle/cogs/meta.py`~~ | ~~DONE - added `timeout=10` to `communicate()` in `git_history()`~~ |
| ~~1c~~ | ~~CQ-04~~ | ~~`tle/cogs/logging.py`~~ | ~~DONE - replaced bare `except:` with `except Exception:`~~ |
| ~~1d~~ | ~~CQ-07~~ | ~~`tle/util/discord_common.py`~~ | ~~DONE - removed inner `while True` loop; task waiter now controls repetition at 10m interval~~ |
| ~~1e~~ | ~~Constants bug~~ | ~~`tle/constants.py`~~ | ~~DONE - changed `ALL_DIRS` from generator expression to `tuple()`~~ |
| ~~1f~~ | ~~CQ-06~~ | ~~`tle/util/discord_common.py`~~ | ~~DONE - fixed docstring typo~~ |
| ~~1g~~ | ~~CSES session~~ | ~~`tle/util/cses_scraper.py`~~ | ~~DONE - deleted~~ |
| ~~1h~~ | ~~CQ-05~~ | ~~`tle/cogs/deactivated/`~~ | ~~DONE - deleted~~ |

**Verification:** Bot starts and runs normally. Run `ruff check .` to confirm no regressions.

---

## Step 2: Build & Dependency Hygiene

**Risk:** Low | **Effort:** Small | **Blocks:** Reproducible builds for all subsequent steps

Lock down the build so that every subsequent change happens on a stable, reproducible foundation.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~2a~~ | ~~DEP-01~~ | ~~`pyproject.toml`~~ | ~~DONE - pinned all dependencies to compatible ranges~~ |
| ~~2b~~ | ~~DEP-03~~ | ~~`pyproject.toml`~~ | ~~DONE - changed `requires-python` to `">= 3.10"`~~ |
| ~~2c~~ | ~~DEP-02~~ | ~~`pyproject.toml`, `tle/__main__.py`~~ | ~~DONE - added `python-dotenv`; call `load_dotenv()` in `main()`~~ |
| ~~2d~~ | ~~DEP-04~~ | | ~~DEFERRED - generate a lock file once deps stabilize after Step 6~~ |
| ~~2e~~ | ~~CI-01~~ | ~~`.github/workflows/*.yaml`~~ | ~~DONE - updated `checkout@v3`→`v4`, `setup-python@v4`→`v5`~~ |
| ~~2f~~ | ~~CI-04~~ | ~~`.github/workflows/lint.yaml`~~ | ~~DONE - pinned `ruff==0.9.7`~~ |
| ~~2g~~ | ~~DOCK-04~~ | ~~`.dockerignore`~~ | ~~DONE - created~~ |
| ~~2h~~ | ~~DOCK-03~~ | ~~`Dockerfile`~~ | ~~DONE - added non-root `botuser`~~ |
| ~~2i~~ | ~~DOCK-01~~ | ~~`Dockerfile`~~ | ~~DONE - multi-stage build separating build tools from runtime~~ |
| ~~2j~~ | ~~STY-04~~ | ~~`ruff.toml`~~ | ~~ALREADY DONE - `"I"` was already in select~~ |

**Verification:** `docker build` succeeds. `pip install .` from a clean venv succeeds. CI passes.

---

## Step 3: Database Layer Modernization

**Risk:** Medium | **Effort:** Medium | **Blocks:** Proper async behavior, testability, discord.py 2.x migration

This is the single highest-impact change for bot responsiveness. It's self-contained in the `db/` module and can be fully tested independently.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~3a~~ | ~~CRIT-03~~ | ~~`tle/util/db/user_db_conn.py`~~ | ~~DONE - Replaced `sqlite3` with `aiosqlite`. All methods async. All callers updated to `await`.~~ |
| ~~3b~~ | ~~CRIT-03~~ | ~~`tle/util/db/cache_db_conn.py`~~ | ~~DONE - Same as 3a for the cache database~~ |
| ~~3c~~ | ~~DB-02~~ | ~~`user_db_conn.py`~~ | ~~DONE - Methods with conditional rollback kept explicit; simple writes use `async with conn:`~~ |
| ~~3d~~ | ~~SEC-01~~ | ~~`user_db_conn.py`~~ | ~~DONE - Replaced all f-string SQL interpolation with parameterized `?` placeholders~~ |
| ~~3e~~ | ~~SEC-02~~ | ~~`user_db_conn.py`~~ | ~~DONE - Added `_VALID_TABLES` and `_VALID_COLUMNS` allowlist validation in `_insert_one`/`_insert_many`~~ |
| ~~3f~~ | ~~DB-04~~ | ~~`user_db_conn.py`~~ | ~~DONE - Cursor-level `row_factory` instead of mutating `conn.row_factory`~~ |
| ~~3g~~ | ~~DB-03~~ | ~~`user_db_conn.py`~~ | ~~DONE - `namedtuple_factory` raises `ValueError` on non-identifier columns~~ |
| 3h | DB-05 | `user_db_conn.py` | DEFERRED - Standardize `user_id` TEXT→INTEGER (schema-breaking, moved to Step 9) |
| ~~3i~~ | ~~DB-06~~ | ~~`tle/__main__.py`~~ | ~~DONE - Registered `user_db.close()` and `cache_db.close()` in bot shutdown cleanup~~ |

**Verification:** All bot commands still work. Database reads/writes succeed. No event loop blocking warnings.

---

## Step 4: Architecture Refactoring

**Risk:** Medium | **Effort:** Medium | **Blocks:** Testability, clean discord.py migration

These changes decouple the codebase so that (a) tests can inject mocks, and (b) the discord.py migration has fewer cross-cutting concerns.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~4a~~ | ~~ARCH-01~~ | ~~`tle/util/codeforces_common.py`, all cogs~~ | ~~DONE - Moved `user_db`, `cache2`, `event_sys` onto `bot` instance via `initialize(bot, nodb)`. Module globals kept as aliases for non-cog code.~~ |
| ~~4b~~ | ~~ARCH-02~~ | ~~All cogs~~ | ~~DONE - All cog methods use `self.bot.user_db`, `self.bot.cache2`, `self.bot.event_sys`. Module-level/static functions kept using `cf_common.*`.~~ |
| ~~4c~~ | ~~PERF-04~~ | ~~`tle/util/graph_common.py`~~ | ~~DONE - Replaced temp file with `io.BytesIO()`. Added `plt.close()` to prevent memory leak.~~ |
| ~~4d~~ | ~~ARCH-03~~ | ~~`tle/util/cache_system2.py`~~ | ~~DONE - Split into `tle/util/cache/` package: `_common.py`, `contest.py`, `problem.py`, `problemset.py`, `rating_changes.py`, `ranklist.py`, `cache_system.py`, `__init__.py`. Old `cache_system2.py` is a backward-compat re-export shim.~~ |
| 4e | CRIT-04 | `tle/cogs/duel.py` | DEFERRED - Persist `draw_offers` in the duel DB table (schema-breaking, moved to Step 9) |
| ~~4f~~ | ~~CRIT-04~~ | ~~`tle/cogs/starboard.py`~~ | ~~DONE - Replaced unbounded `self.locks` dict with LRU-bounded `_BoundedLockDict(maxsize=256)`~~ |
| ~~4g~~ | ~~PERF-01~~ | ~~`tle/util/codeforces_common.py`~~ | ~~DONE - Changed sequential API calls in `get_visited_contests()` to `asyncio.gather()`. Rate limit still respected via shared `@cf_ratelimit` decorator.~~ |
| ~~4h~~ | ~~STY-05~~ | ~~`tle/constants.py`~~ | ~~DONE - Migrated all paths from `os.path.join` to `pathlib.Path` `/` operator~~ |

**Verification:** All commands still work. `import tle` succeeds. No circular imports.

---

## Step 5: Testing Infrastructure

**Risk:** None (additive) | **Effort:** Medium | **Blocks:** Confidence in discord.py migration

Set up testing *before* the big discord.py migration so we can validate correctness.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~5a~~ | ~~CI-02~~ | ~~`pyproject.toml`~~ | ~~DONE - Added `pytest >= 7.0, < 9`, `pytest-asyncio >= 0.23, < 1`, `pytest-cov >= 4.0, < 6`, `pytest-mock >= 3.10, < 4` to `[project.optional-dependencies] test`. Added `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`.~~ |
| ~~5b~~ | ~~CI-02~~ | ~~`tests/conftest.py`~~ | ~~DONE - Created shared fixtures: async `user_db` and `cache_db` (in-memory aiosqlite), factory fixtures `make_user`, `make_problem`, `make_contest`, `make_rating_change`~~ |
| ~~5c~~ | ~~CI-02~~ | ~~`tests/unit/`~~ | ~~DONE - 100 unit tests across 5 files: `test_table.py` (13), `test_handledict.py` (8), `test_codeforces_api.py` (30), `test_codeforces_common.py` (35), `test_rating_calculator.py` (14)~~ |
| ~~5d~~ | ~~CI-02~~ | ~~`tests/component/`~~ | ~~DONE - 126 component tests across 2 files: `test_user_db.py` (55 tests covering handle CRUD, status, CF user cache, challenges, duels, reminders, rankup, auto-role, rated VC, starboard) and `test_cache_db.py` (20 tests covering contests, problems, rating changes, problemset)~~ |
| ~~5e~~ | ~~CI-02~~ | ~~`.github/workflows/test.yaml`~~ | ~~DONE - Test CI job with Python 3.10/3.11/3.12 matrix, codecov upload on 3.11~~ |
| ~~5f~~ | ~~CI-05~~ | ~~`.github/workflows/lint.yaml`~~ | ~~DONE - Added parallel `audit` job running `pip-audit`~~ |

**Additional fixes discovered during testing:**
- Moved `fix_urls()` from `codeforces_common.py` to `codeforces_api.py` (belongs with the `User` type it operates on), breaking a circular import chain architecturally
- Fixed 8 SQL queries in `user_db_conn.py` with non-identifier column names (`SELECT 1` → `SELECT 1 AS x`, `SELECT COUNT(*)` → `SELECT COUNT(*) AS cnt`) — latent bugs from Step 4's `namedtuple_factory`
- Removed unused `codeforces_common` import from `user_db_conn.py`

**Verification:** 226 tests pass. `ruff check` and `ruff format --check` clean on all files.

---

## Step 6: discord.py 2.x Migration

**Risk:** High | **Effort:** Large | **Blocks:** Modern Discord features, slash commands

This is the largest single change. Having tests from Step 5 and clean architecture from Step 4 makes this manageable.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~6a~~ | ~~CRIT-01~~ | ~~`pyproject.toml`~~ | ~~DONE - Updated `discord.py == 1.7.3` to `discord.py >= 2.3, < 3`~~ |
| ~~6b~~ | ~~CRIT-02~~ | ~~`pyproject.toml`~~ | ~~DONE - Removed `aiohttp < 3.8` pin~~ |
| ~~6c~~ | ~~DPY-05~~ | ~~`tle/__main__.py`~~ | ~~DONE - Added `intents.message_content = True`~~ |
| ~~6d~~ | ~~DPY-04~~ | ~~`tle/__main__.py`, `tle/util/codeforces_common.py`, cog `on_ready` handlers~~ | ~~DONE - Created `TLEBot(commands.Bot)` subclass with `setup_hook()` that loads cog extensions and calls `cf_common.initialize()`. Moved cleanup into `TLEBot.close()` override. Removed `wait_for_initialize()`, `_initialize_done`, `_initialize_event` from `codeforces_common.py`. Removed `on_ready_event_once` decorator from `discord_common.py`. Removed `await cf_common.wait_for_initialize()` calls from `contests.py` and `handles.py` `on_ready`.~~ |
| ~~6e~~ | ~~DPY-03~~ | ~~All cog files~~ | ~~DONE - Changed `def setup(bot)` to `async def setup(bot)`, `bot.add_cog()` to `await bot.add_cog()` in all 9 cog files~~ |
| ~~6f~~ | ~~DPY-01~~ | ~~`tle/util/discord_common.py`, `tle/cogs/starboard.py`~~ | ~~DONE - Changed `user.avatar_url` to `user.display_avatar.url` (2 sites)~~ |
| ~~6g~~ | ~~DPY-02~~ | ~~`tle/util/discord_common.py`~~ | ~~DONE - Changed `discord.Embed.Empty` to `None`~~ |
| ~~6h~~ | ~~DPY-06~~ | ~~`tle/cogs/meta.py`~~ | ~~DONE - Changed `guild.icon_url` to `guild.icon.url if guild.icon else None`~~ |
| ~~6i~~ | ~~Purgatory role check~~ | ~~`tle/util/discord_common.py`, `tle/cogs/handles.py`, `tle/cogs/graphs.py`~~ | ~~DONE - Added `get_role()` and `has_role()` helpers supporting str/int identifiers. Updated 6 call sites: presence purgatory filter, `update_member_rank_role`, `ispurg`, `in_purgatory`, `refer`, `grandfather`.~~ |
| ~~6j~~ | ~~Discriminator hack~~ | ~~`tle/util/codeforces_common.py`~~ | ~~DONE - Removed `#0` discriminator stripping (discriminators removed in new Discord)~~ |

**Verification:** 226 tests pass. `ruff check` clean. All removed patterns (`avatar_url`, `Embed.Empty`, `wait_for_initialize`, `_initialize_done`, `_initialize_event`, `on_ready_event_once`) verified absent from `tle/`.

---

## Step 7: Modern Discord Features

**Risk:** Low (additive) | **Effort:** Medium | **Blocks:** Nothing (these are enhancements)

Now that we're on discord.py 2.x, add modern Discord UX.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~7a~~ | ~~DPY-07~~ | ~~All cogs, `tle/__main__.py`, `tle/util/paginator.py`~~ | ~~DONE - Converted 8 groups to `hybrid_group` (with `fallback='show'`), 12 standalone commands to `hybrid_command`, added `with_app_command=False` to 16 subcommands with variadic `*args`. Added `tree.sync()` in `setup_hook()`, `interaction_guild_check` for slash commands. Added `TLEContext` subclass that auto-replies to prefix command messages. Updated paginator to use `ctx.send()` for proper interaction responses and prefix replies.~~ |
| ~~7b~~ | ~~Pagination~~ | ~~`tle/util/paginator.py`, all cogs~~ | ~~DONE - Replaced `Paginated` class (emoji reactions + `bot.wait_for`) with `PaginatorView(discord.ui.View)` using 4 navigation buttons. Made `paginate()` async, removed `bot` parameter and `manage_messages` permission check. Updated all 13 callers across 4 cog files. Removed `InsufficientPermissionsError`.~~ |
| ~~7c~~ | ~~Duel UX~~ | ~~`tle/cogs/duel.py`~~ | ~~DONE - Added `DuelChallengeView` with Accept/Decline/Withdraw buttons. Challenge command no longer blocks with `asyncio.sleep`; View handles expiry via timeout. Standalone text commands kept as fallback.~~ |
| ~~7d~~ | ~~Handle UX~~ | ~~`tle/cogs/handles.py`, `tle/util/oauth.py`, `tle/__main__.py`, `tle/constants.py`~~ | ~~DONE - Replaced compile-error identification flow with Codeforces OAuth (OpenID Connect). Added `OAuthStateStore`, `OAuthServer` with `/callback` route, JWT token decoding (PyJWT). `identify` command now sends a "Link Codeforces Account" link button. Refactored `_set` into `_set_from_oauth` for callback access. Added OAuth env vars, port exposure in `docker-compose.yaml`, 15 unit tests.~~ |

**Verification:** Slash commands appear in Discord. Buttons work. Existing prefix commands still work. OAuth identify flow links handle via one-click CF authorization. 392 tests pass.

---

## Step 8: Code Quality Sweep

**Risk:** Low | **Effort:** Medium | **Blocks:** Nothing (polish)

With the architecture clean and tests in place, address remaining code quality items.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~8a~~ | ~~CQ-01~~ | ~~All files~~ | ~~DONE - Added type annotations to all public functions across 32 files (util modules + all cogs). Modernized `Optional[X]` to `X | None` (PEP 604). Added `from typing import Any` and `from collections.abc import Callable, Sequence, Iterable` imports.~~ |
| 8b | CQ-02 | Multiple | Extract magic numbers to named constants with units (e.g., `_SKIP_COOLDOWN_MINUTES = 180`) |
| 8c | CQ-03 | `handles.py`, `contests.py`, `graphs.py` | Decompose god functions into smaller helpers |
| 8d | STY-01 | All files | Standardize on f-strings (ruff can auto-fix) |
| 8e | STY-02 | All cogs | Document admin command naming convention and apply consistently |
| 8f | STY-03 | All modules | Add module-level docstrings |
| 8g | SEC-04 | `tle/util/codeforces_common.py` | Add bounds validation to `parse_rating()` (0-5000 range) |
| ~~8h~~ | ~~CQ type hints~~ | ~~`tle/util/codeforces_common.py`~~ | ~~DONE - Fixed `handles: [str]` → `handles: list[str]`, `members: [discord.Member]` → `members: Iterable[discord.Member]`, and similar invalid annotations~~ |
| 8i | CI type check | `.github/workflows/lint.yaml`, `pyproject.toml` | Add `mypy` or `pyright` check to CI (mypy config added to `pyproject.toml`, CI integration pending) |

**Progress:** 8a and 8h complete. mypy config added (8i partial). Remaining: 8b-8g, 8i CI integration.

**Verification:** `ruff check .` clean. `mypy tle/` clean (or minimal ignores). All tests pass.

---

## Step 9: Database Schema Improvements

**Risk:** Medium (requires data migration) | **Effort:** Medium | **Blocks:** Multi-guild correctness

These are schema-level changes that need careful migration with existing production data.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 9a | DB-01 | `tle/util/db/` | Implement versioned migration system: `schema_version` table + numbered `.sql` migration files |
| 9b | DB-01 | `user_db_conn.py:238-288` | Move starboard migration into migration system (migration 001) |
| 9c | DB-07 | `user_db_conn.py`, `duel.py` | Add `guild_id` to `duelist` and `duel` tables (migration 002). Update all duel queries. |
| 9d | DB-05 | `user_db_conn.py` | Migrate `user_handle.user_id` from TEXT to INTEGER (migration 003) |

**Verification:** Fresh database creation works. Migration from old schema works. Duel commands are guild-scoped.

---

## Step 10: Performance & Operational Polish

**Risk:** Low | **Effort:** Small-Medium | **Blocks:** Nothing (optimization)

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 10a | PERF-05 | `tle/util/discord_common.py:139-145` | Pick random member from a single guild instead of iterating all |
| 10b | PERF-03 | `tle/util/ranklist/rating_calculator.py` | Profile FFT calculator; add direct computation path for contests < 100 participants |
| 10c | DOCK-02 | `Dockerfile` | Add `HEALTHCHECK` instruction |
| 10d | Cache config | `tle/util/cache_system2.py:20` | Make `CONTEST_BLACKLIST` configurable via environment variable |
| 10e | ARCH-05 | `tle/util/tasks.py` | Evaluate whether discord.py 2.x `tasks.loop` can replace custom framework; if not, add docstrings |
| 10f | CI-03 | `.github/workflows/` | Add Python version matrix (3.10, 3.11, 3.12) to lint and build jobs |

---

## Summary: Critical Path

```
Step 1 (Quick Fixes)
  |
Step 2 (Build Hygiene)
  |
Step 3 (Async Database)  ←── Biggest responsiveness win
  |
Step 4 (Architecture)    ←── Enables testing + clean migration
  |
Step 5 (Testing)         ←── Safety net for everything after
  |
Step 6 (discord.py 2.x)  ←── Biggest modernization win
  |
  +--→ Step 7 (Modern Discord)
  +--→ Step 8 (Code Quality)
  +--→ Step 9 (Schema Improvements)
  +--→ Step 10 (Polish)
```

Steps 7-10 can be done in any order or in parallel after Step 6.

---

## Effort Estimates

| Step | Items | Relative Effort |
|------|-------|----------------|
| 1. Quick Fixes | 8 | Small (a few hours) |
| 2. Build Hygiene | 10 | Small (a day) |
| 3. Async Database | 9 | Medium (several days) |
| 4. Architecture | 8 | Medium (several days) |
| 5. Testing | 6 | Medium (several days) |
| 6. discord.py 2.x | 10 | Large (a week+) |
| 7. Modern Discord | 4 | Medium (several days) |
| 8. Code Quality | 9 | Medium (several days) |
| 9. Schema Improvements | 4 | Medium (several days) |
| 10. Polish | 6 | Small (a few days) |
