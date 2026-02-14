# TLE Modernization Roadmap

This roadmap orders all fixes from AUDIT.md to minimize risk and maximize value at each step. Changes are grouped into steps where each step builds on the previous one. Within each step, items are ordered by dependency (do the first items first).

---

## Step 1: Quick Safety Fixes

**Risk:** Minimal | **Effort:** Small | **Blocks:** Nothing, but prevents data loss and hangs

These are isolated, low-risk changes that fix real bugs. Each can be done and verified independently in minutes.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| ~~1a~~ | ~~SEC-05~~ | ~~`tle/cogs/meta.py`~~ | ~~DONE - removed `restart` command (shell script no longer exists), replaced `os._exit(0)` with `await bot.close()` + `sys.exit(0)` in `kill`~~ |
| 1b | SEC-03 | `tle/cogs/meta.py:28-43` | Add `timeout=10` to `communicate()` in `git_history()` |
| 1c | CQ-04 | `tle/cogs/logging.py:61-62` | Replace bare `except: pass` with `except Exception: logger.debug(...)` |
| 1d | CQ-07 | `tle/util/discord_common.py:138` | Remove the inner `while True` loop; let the task waiter handle repetition |
| 1e | Constants bug | `tle/constants.py:23-27` | Change `ALL_DIRS` from generator expression to tuple (generator consumed once) |
| 1f | CQ-06 | `tle/util/discord_common.py:103` | Fix docstring typo: "corouting asuch" -> "coroutine such" |
| ~~1g~~ | ~~CSES session~~ | ~~`tle/util/cses_scraper.py`~~ | ~~DONE - deleted~~ |
| ~~1h~~ | ~~CQ-05~~ | ~~`tle/cogs/deactivated/`~~ | ~~DONE - deleted~~ |

**Verification:** Bot starts and runs normally. Run `ruff check .` to confirm no regressions.

---

## Step 2: Build & Dependency Hygiene

**Risk:** Low | **Effort:** Small | **Blocks:** Reproducible builds for all subsequent steps

Lock down the build so that every subsequent change happens on a stable, reproducible foundation.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 2a | DEP-01 | `pyproject.toml` | Pin all dependencies to compatible ranges (e.g., `numpy>=1.24,<3`) |
| 2b | DEP-03 | `pyproject.toml:4` | Change `requires-python` to `">= 3.10"` (code uses `str \| int` syntax) |
| 2c | DEP-02 | `pyproject.toml`, `tle/__main__.py` | Add `python-dotenv` dependency; call `load_dotenv()` in `main()` |
| 2d | DEP-04 | Project root | Generate a lock file (add `uv.lock` via `uv lock`, or `pip freeze > requirements.lock`) |
| 2e | CI-01 | `.github/workflows/*.yaml` | Update `actions/checkout@v3` -> `v4`, `actions/setup-python@v4` -> `v5` |
| 2f | CI-04 | `.github/workflows/lint.yaml` | Pin ruff: `pip install ruff==0.9.7` (or current version) |
| 2g | DOCK-04 | `.dockerignore` (new) | Create with: `.git`, `.env`, `data/`, `logs/`, `__pycache__/`, `.vscode/`, `.idea/`, `*.md` |
| 2h | DOCK-03 | `Dockerfile` | Add `RUN useradd -m botuser` and `USER botuser` before `CMD` |
| 2i | DOCK-01 | `Dockerfile` | Multi-stage build: builder stage with gcc/cmake, final stage with only runtime libs |
| 2j | STY-04 | `ruff.toml` | Enable import sorting rules (`select = ["I"]`) |

**Verification:** `docker build` succeeds. `pip install .` from a clean venv succeeds. CI passes.

---

## Step 3: Database Layer Modernization

**Risk:** Medium | **Effort:** Medium | **Blocks:** Proper async behavior, testability, discord.py 2.x migration

This is the single highest-impact change for bot responsiveness. It's self-contained in the `db/` module and can be fully tested independently.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 3a | CRIT-03 | `tle/util/db/user_db_conn.py` | Replace `sqlite3` with `aiosqlite`. Make all methods `async`. Update all callers to `await`. |
| 3b | CRIT-03 | `tle/util/db/cache_db_conn.py` | Same as 3a for the cache database |
| 3c | DB-02 | `user_db_conn.py` | Standardize all writes to use `async with conn:` context manager (replaces manual commit/rollback) |
| 3d | SEC-01 | `user_db_conn.py:401-453,714-764` | Replace all f-string SQL interpolation with parameterized `?` placeholders |
| 3e | SEC-02 | `user_db_conn.py:292-308` | Add allowlist validation in `_insert_one`/`_insert_many` for table/column names |
| 3f | DB-04 | `user_db_conn.py:310-320` | Stop mutating `conn.row_factory` in `_fetchone`/`_fetchall`; use cursor-level factory |
| 3g | DB-03 | `user_db_conn.py:65` | Make `namedtuple_factory` raise on non-identifier columns instead of silently dropping |
| 3h | DB-05 | `user_db_conn.py` | Standardize all `user_id` columns to INTEGER type (add migration for `user_handle`) |
| 3i | DB-06 | `tle/__main__.py`, `tle/cogs/meta.py` | Register `user_db.close()` in bot cleanup (on graceful shutdown) |

**Verification:** All bot commands still work. Database reads/writes succeed. No event loop blocking warnings.

---

## Step 4: Architecture Refactoring

**Risk:** Medium | **Effort:** Medium | **Blocks:** Testability, clean discord.py migration

These changes decouple the codebase so that (a) tests can inject mocks, and (b) the discord.py migration has fewer cross-cutting concerns.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 4a | ARCH-01 | `tle/util/codeforces_common.py`, all cogs | Move `user_db`, `cache2`, `event_sys` onto the `bot` instance. Replace `cf_common.user_db` with `self.bot.user_db` in cogs. |
| 4b | ARCH-02 | All cogs | After 4a, cogs access services via `self.bot.*` instead of importing globals |
| 4c | PERF-04 | `tle/util/graph_common.py` | Replace temp file with `io.BytesIO()` for `get_current_figure_as_file()`. Add `plt.close()` after save. |
| 4d | ARCH-03 | `tle/util/cache_system2.py` | Split into `cache/contest.py`, `cache/problem.py`, `cache/rating_changes.py`, `cache/ranklist.py`, `cache/__init__.py` |
| 4e | CRIT-04 | `tle/cogs/duel.py` | Persist `draw_offers` in the duel DB table (add `draw_offerer_id` column) |
| 4f | CRIT-04 | `tle/cogs/starboard.py` | Replace unbounded `self.locks` dict with a bounded `LRUCache` or per-operation locking |
| 4g | PERF-01 | `tle/util/codeforces_common.py:135` | Change sequential API calls in `get_visited_contests()` to `asyncio.gather()` |
| 4h | STY-05 | `tle/constants.py` | Migrate from `os.path` to `pathlib.Path` throughout |

**Verification:** All commands still work. `import tle` succeeds. No circular imports.

---

## Step 5: Testing Infrastructure

**Risk:** None (additive) | **Effort:** Medium | **Blocks:** Confidence in discord.py migration

Set up testing *before* the big discord.py migration so we can validate correctness.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 5a | CI-02 | `pyproject.toml` | Add test dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock` |
| 5b | CI-02 | `tests/conftest.py` | Create shared fixtures: in-memory DB, mock context, sample CF data |
| 5c | CI-02 | `tests/unit/` | Write unit tests for pure functions: `time_format`, `parse_date`, `parse_tags`, `parse_rating`, `filter_flags`, `SubFilter`, rating calculator, `table.py`, `handledict.py`, `events.py` |
| 5d | CI-02 | `tests/component/` | Write DB tests against in-memory SQLite: handle CRUD, duel lifecycle, challenge lifecycle, starboard CRUD |
| 5e | CI-02 | `.github/workflows/test.yaml` | Add test CI job with Python 3.10/3.11/3.12 matrix |
| 5f | CI-05 | `.github/workflows/lint.yaml` | Add `pip-audit` step for dependency vulnerability scanning |

**Verification:** `pytest` passes. CI green on all Python versions.

---

## Step 6: discord.py 2.x Migration

**Risk:** High | **Effort:** Large | **Blocks:** Modern Discord features, slash commands

This is the largest single change. Having tests from Step 5 and clean architecture from Step 4 makes this manageable.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 6a | CRIT-01 | `pyproject.toml` | Update `discord.py == 1.7.3` to `discord.py >= 2.3, < 3` |
| 6b | CRIT-02 | `pyproject.toml` | Remove `aiohttp < 3.8` pin |
| 6c | DPY-05 | `tle/__main__.py` | Add `intents.message_content = True` |
| 6d | DPY-04 | `tle/__main__.py` | Move `bot.load_extension()` calls into `async def setup_hook()` on the bot |
| 6e | DPY-03 | All cog files | Change `def setup(bot)` to `async def setup(bot)`, `bot.add_cog()` to `await bot.add_cog()` |
| 6f | DPY-01 | `tle/util/discord_common.py:50` | Change `user.avatar_url` to `user.display_avatar.url` |
| 6g | DPY-02 | `tle/util/discord_common.py:19` | Change `discord.Embed.Empty` to `None` |
| 6h | DPY-06 | `tle/cogs/meta.py` | Change `guild.icon_url` to `guild.icon.url if guild.icon else None` |
| 6i | Purgatory role check | `tle/util/discord_common.py:143-144` | Fix role comparison to handle both name and ID: check `role.name` and `role.id` |
| 6j | Discriminator hack | `tle/util/codeforces_common.py:272` | Remove `#0` discriminator stripping (discriminators removed in new Discord) |

**Verification:** Bot connects. All commands respond. Run full test suite. Manual smoke test of key commands: `;gimme`, `;gitgud`, `;duel challenge`, `;plot rating`, `;handle set`.

---

## Step 7: Modern Discord Features

**Risk:** Low (additive) | **Effort:** Medium | **Blocks:** Nothing (these are enhancements)

Now that we're on discord.py 2.x, add modern Discord UX.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 7a | DPY-07 | All cogs | Convert `@commands.command` to `@commands.hybrid_command` for slash command support |
| 7b | Pagination | `tle/util/paginator.py` | Replace reaction-based pagination with `discord.ui.View` + buttons |
| 7c | Duel UX | `tle/cogs/duel.py` | Add accept/decline/withdraw buttons using `discord.ui.Button` |
| 7d | Handle UX | `tle/cogs/handles.py` | Add modal for handle identification flow |

**Verification:** Slash commands appear in Discord. Buttons work. Existing prefix commands still work.

---

## Step 8: Code Quality Sweep

**Risk:** Low | **Effort:** Medium | **Blocks:** Nothing (polish)

With the architecture clean and tests in place, address remaining code quality items.

| # | Issue | File(s) | What to Do |
|---|-------|---------|------------|
| 8a | CQ-01 | All files | Add type annotations to all public functions. Start with `util/` modules, then cogs. |
| 8b | CQ-02 | Multiple | Extract magic numbers to named constants with units (e.g., `_SKIP_COOLDOWN_MINUTES = 180`) |
| 8c | CQ-03 | `handles.py`, `contests.py`, `graphs.py` | Decompose god functions into smaller helpers |
| 8d | STY-01 | All files | Standardize on f-strings (ruff can auto-fix) |
| 8e | STY-02 | All cogs | Document admin command naming convention and apply consistently |
| 8f | STY-03 | All modules | Add module-level docstrings |
| 8g | SEC-04 | `tle/util/codeforces_common.py` | Add bounds validation to `parse_rating()` (0-5000 range) |
| 8h | CQ type hints | `tle/util/codeforces_common.py:131` | Fix `handles: [str]` -> `handles: list[str]` and similar |
| 8i | CI type check | `.github/workflows/lint.yaml` | Add `mypy` or `pyright` check to CI |

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
