# TLE Testing Plan

## Current State

**355 tests** pass across Layer 1 (unit), Layer 2 (component), and Layer 3 (integration), implemented through Step 10. CI runs on Python 3.10/3.11/3.12 with codecov reporting.

**What's tested:**
- Layer 1 (unit): `table.py`, `handledict.py`, `codeforces_api.py` (namedtuples + helpers), `codeforces_common.py` (pure functions + SubFilter), `rating_calculator.py`, `events.py`, `tasks.py`, `paginator.py`
- Layer 2 (component): Full async CRUD for `UserDbConn` and `CacheDbConn` using in-memory aiosqlite, API response parsing with fixture JSON files, cache sub-system data management
- Layer 3 (integration): `codeforces.py` cog commands (`_validate_gitgud_status`, `_gitgud`, `gimme`)

**What's NOT tested yet:**
- `discord_common.py` utility functions
- Remaining cog integration tests (duel, handles, contests, graphs, starboard, meta)
- Ranklist cache (depends on complex API interactions)
- End-to-end tests (Layer 4)

---

## Testing Strategy

### Layered Approach

```
Layer 4: End-to-End Tests (manual/semi-automated)
         - Full bot integration with test Discord server
         - Codeforces API live tests

Layer 3: Integration Tests
         - Cog command tests with mocked Discord context
         - Database round-trip tests
         - Cache system tests with mocked API

Layer 2: Component Tests
         - Async database operations against in-memory SQLite
         - API response parsing with fixture data
         - Cache logic with injected data

Layer 1: Unit Tests (start here)
         - Pure functions and data transformations
         - Rating calculations
         - Filtering and parsing logic
         - Table and embed formatting
```

**Priority:** Start from Layer 1 (highest value, lowest effort) and work upward.

---

## Test Infrastructure Setup

### Directory Structure

```
tests/
├── conftest.py              # Shared fixtures
├── fixtures/                # Test data
│   ├── cf_api_responses/    # Saved Codeforces API responses
│   │   ├── contest_list.json
│   │   ├── user_status.json
│   │   ├── user_info.json
│   │   ├── contest_standings.json
│   │   └── rating_changes.json
│   └── db/                  # Database fixtures
│       └── seed_data.sql
├── unit/
│   ├── test_codeforces_api.py
│   ├── test_codeforces_common.py
│   ├── test_rating_calculator.py
│   ├── test_table.py
│   ├── test_paginator.py
│   ├── test_handledict.py
│   ├── test_events.py
│   └── test_tasks.py
├── component/
│   ├── test_user_db.py
│   ├── test_cache_db.py
│   ├── test_cache_system.py
│   └── test_api_parsing.py
├── integration/
│   ├── test_codeforces_cog.py
│   ├── test_contests_cog.py
│   ├── test_duel_cog.py
│   ├── test_handles_cog.py
│   ├── test_graphs_cog.py
│   ├── test_starboard_cog.py
│   └── test_meta_cog.py
└── e2e/
    └── test_bot_lifecycle.py
```

### Configuration

**`pyproject.toml` additions:**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks integration tests requiring mocked Discord context",
    "e2e: marks end-to-end tests requiring live services",
]

[project.optional-dependencies]
test = [
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "pytest-mock",
    "aioresponses",
]
```

**Note:** `dpytest` is omitted because discord.py 1.7.3 is EOL and dpytest compatibility is unreliable. Integration tests should use manual mocking of the Discord context instead.

### Key Fixtures (`tests/conftest.py`)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
async def user_db():
    """Provides a fresh async in-memory user database."""
    from tle.util.db.user_db_conn import UserDbConn
    db = UserDbConn(":memory:")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
async def cache_db():
    """Provides a fresh async in-memory cache database."""
    from tle.util.db.cache_db_conn import CacheDbConn
    db = CacheDbConn(":memory:")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def mock_ctx():
    """Provides a mocked Discord context."""
    ctx = AsyncMock()
    ctx.guild.id = 123456789
    ctx.author.id = 987654321
    ctx.author.mention = "<@987654321>"
    ctx.send = AsyncMock()
    return ctx


@pytest.fixture
def sample_cf_user():
    """Provides a sample Codeforces User namedtuple.

    The User model has 13 fields (handle through titlePhoto).
    """
    from tle.util.codeforces_api import User
    return User(
        handle="tourist",
        firstName="Gennady",
        lastName="Korotkevich",
        country="Belarus",
        city="Gomel",
        organization="ITMO University",
        contribution=100,
        rating=3800,
        maxRating=3979,
        lastOnlineTimeSeconds=1700000000,
        registrationTimeSeconds=1200000000,
        friendOfCount=50000,
        titlePhoto="https://userpic.codeforces.org/no-title.jpg",
    )


@pytest.fixture
def sample_problem():
    """Provides a sample Codeforces Problem namedtuple."""
    from tle.util.codeforces_api import Problem
    return Problem(
        contestId=1,
        problemsetName=None,
        index="A",
        name="Theatre Square",
        type="PROGRAMMING",
        points=None,
        rating=1000,
        tags=["math"],
    )


@pytest.fixture
def sample_contest():
    """Provides a sample Codeforces Contest namedtuple."""
    from tle.util.codeforces_api import Contest
    return Contest(
        id=1,
        name="Codeforces Beta Round #1",
        startTimeSeconds=1265979600,
        durationSeconds=7200,
        type="CF",
        phase="FINISHED",
        preparedBy="MikeMirzayanov",
    )
```

---

## Layer 1: Unit Tests

### Priority 1A: Pure Functions (No Dependencies)

#### `test_codeforces_common.py`

```
Tests to write:
- test_time_format_zero_seconds
- test_time_format_mixed_units
- test_pretty_time_format_default
- test_pretty_time_format_shorten
- test_pretty_time_format_only_most_significant
- test_pretty_time_format_always_seconds
- test_days_ago_today
- test_days_ago_yesterday
- test_days_ago_multiple_days
- test_parse_date_8_chars (ddmmyyyy)
- test_parse_date_6_chars (mmyyyy)
- test_parse_date_4_chars (yyyy)
- test_parse_date_invalid_raises
- test_parse_tags_with_prefix
- test_parse_tags_empty
- test_parse_rating_found
- test_parse_rating_not_found_returns_default
- test_filter_flags_basic
- test_filter_flags_no_match
- test_negate_flags
- test_fix_urls_adds_https
- test_fix_urls_already_has_scheme
- test_is_nonstandard_contest_wild
- test_is_nonstandard_contest_normal
```

#### `test_rating_calculator.py`

```
Tests to write:
- test_intdiv_positive
- test_intdiv_negative
- test_contestant_creation
- test_simple_two_person_contest
- test_rating_changes_sum_to_near_zero
- test_process_does_not_crash_empty_standings
- test_rank_assignment_with_ties
- test_get_seed_without_exclusion
- test_get_seed_with_exclusion
- test_binary_search_rank_to_rating
```

#### `test_table.py`

```
Tests to write:
- test_table_creation
- test_table_with_header_and_data
- test_table_formatting_alignment
- test_table_style_options
- test_east_asian_width_handling
```

#### `test_handledict.py`

```
Tests to write:
- test_case_insensitive_lookup
- test_case_insensitive_set
- test_case_insensitive_contains
- test_preserves_original_key
- test_delete_key
- test_iteration_preserves_casing
```

#### `test_events.py`

```
Tests to write:
- test_register_listener
- test_dispatch_fires_listener
- test_dispatch_no_listeners
- test_wait_for_returns_event
- test_wait_for_timeout
- test_multiple_listeners
- test_listener_exception_handling
- test_remove_listener
```

### Priority 1B: Data Model Tests

#### `test_codeforces_api.py` (models only)

```
Tests to write:
- test_user_creation (13 fields: handle through titlePhoto)
- test_user_effective_rating_with_rating
- test_user_effective_rating_unrated (defaults to 1500)
- test_user_rank_property
- test_user_url
- test_rating2rank_boundaries
- test_rating2rank_unrated
- test_problem_url_normal_contest
- test_problem_url_gym_contest (contestId >= 100000)
- test_problem_url_acmsguru
- test_problem_has_metadata
- test_problem_matches_all_tags
- test_problem_matches_any_tag
- test_problem_get_matched_tags
- test_problem_contest_identifier
- test_contest_end_time
- test_contest_end_time_none (missing start/duration)
- test_contest_url_normal
- test_contest_url_gym
- test_contest_register_url
- test_contest_matches_markers
- test_contest_phases
- test_make_from_dict
- test_submission_creation
- test_rating_change_creation
```

### Priority 1C: SubFilter Tests

#### `test_subfilter.py`

SubFilter lives in `tle/util/codeforces_common.py`. Note: `filter_solved` and `filter_subs` reference the global `cf_cache`, so those methods need the cache to be mocked or the global to be patched.

```
Tests to write (parse method - no external deps):
- test_parse_tag_flags (+dp, +greedy)
- test_parse_ban_tag_flags (~dp, ~implementation)
- test_parse_type_flags_contest (+contest)
- test_parse_type_flags_virtual (+virtual)
- test_parse_type_flags_practice (+practice)
- test_parse_type_flags_outof (+outof)
- test_parse_date_range (d>=, d<)
- test_parse_rating_range (r>=, r<=)
- test_parse_contest_filter (c+)
- test_parse_index_filter (i+)
- test_parse_team_flag (+team)
- test_parse_mixed_flags
- test_parse_returns_unrecognized_args

Tests to write (filtering - requires mocked cf_cache):
- test_filter_solved_deduplicates
- test_filter_solved_keeps_first_ac
- test_filter_subs_by_type
- test_filter_subs_by_rating
- test_filter_subs_by_tags
- test_filter_subs_by_date
- test_filter_rating_changes_by_date
```

### Priority 1D: Task Framework Tests

#### `test_tasks.py`

```
Tests to write:
- test_waiter_fixed_delay_creation
- test_waiter_for_event_creation
- test_task_spec_descriptor_get
- test_task_start_and_stop
- test_task_manual_trigger
- test_task_exception_handler_called
- test_task_waiter_required_error
- test_task_already_running_error
```

---

## Layer 2: Component Tests

All database tests are **async** since both `UserDbConn` and `CacheDbConn` use `aiosqlite`. Use the `user_db` and `cache_db` async fixtures from `conftest.py`.

### Priority 2A: Database Tests

#### `test_user_db.py`

```
Tests to write (all async, using in-memory aiosqlite):
- test_connect_creates_tables
- test_set_and_get_handle
- test_set_handle_duplicate_raises_unique_constraint
- test_set_handle_same_user_updates
- test_remove_handle
- test_get_handles_for_guild
- test_get_user_id
- test_get_user_id_case_insensitive
- test_set_inactive
- test_update_status
- test_reset_status
- test_cache_and_fetch_cf_user
- test_fetch_cf_user_not_found
- test_fetch_cf_user_fixes_urls
- test_get_cf_users_for_guild
- test_new_challenge
- test_check_challenge_exists
- test_check_challenge_none
- test_complete_challenge
- test_skip_challenge
- test_get_gudgitters
- test_howgud
- test_gitlog
- test_get_noguds
- test_register_duelist
- test_is_duelist
- test_is_duelist_not_registered
- test_create_duel
- test_start_duel
- test_complete_duel_challenger_wins
- test_complete_duel_draw
- test_cancel_duel
- test_invalidate_duel
- test_get_duel_rating
- test_update_duel_rating
- test_get_duels
- test_get_duel_wins
- test_get_pair_duels
- test_get_recent_duels
- test_get_ongoing_duels
- test_get_num_duel_completed
- test_get_num_duel_draws
- test_get_num_duel_losses
- test_get_num_duel_declined
- test_get_num_duel_rdeclined
- test_check_duel_challenge
- test_check_duel_accept
- test_check_duel_decline
- test_check_duel_withdraw
- test_check_duel_draw
- test_check_duel_complete
- test_reminder_settings_crud
- test_clear_reminder_settings
- test_rankup_channel_crud
- test_clear_rankup_channel
- test_auto_role_update_toggle
- test_create_rated_vc
- test_get_rated_vc
- test_get_ongoing_rated_vc_ids
- test_finish_rated_vc
- test_get_rated_vc_user_ids
- test_update_vc_rating
- test_get_vc_rating
- test_get_vc_rating_default
- test_get_vc_rating_history
- test_set_and_get_rated_vc_channel
- test_remove_last_ratedvc_participation
- test_starboard_emoji_crud
- test_starboard_channel_crud
- test_starboard_message_crud
- test_check_exists_starboard_message
- test_remove_starboard_message_by_original
- test_remove_starboard_message_by_starboard_id
- test_get_starboard_entry
- test_starboard_migration_from_v0
```

#### `test_cache_db.py`

```
Tests to write (all async):
- test_connect_creates_tables
- test_cache_and_fetch_contests
- test_cache_and_fetch_problems
- test_problem_tag_json_serialization
- test_save_and_fetch_rating_changes
- test_get_rating_changes_for_contest
- test_get_rating_changes_for_handle
- test_get_all_rating_changes
- test_has_rating_changes_saved
- test_clear_rating_changes_all
- test_clear_rating_changes_by_contest
- test_cache_and_fetch_problemset
- test_fetch_problemset_by_contest
- test_clear_problemset
- test_problemset_empty
- test_get_users_with_more_than_n_contests
```

### Priority 2B: API Response Parsing

#### `test_api_parsing.py`

Tests `make_from_dict` and the nested parsing in API methods using fixture JSON files.

```
Tests to write (using fixture JSON files):
- test_make_from_dict_basic
- test_make_from_dict_missing_fields
- test_parse_contest_list_response
- test_parse_user_info_response
- test_parse_user_status_response (nested Problem, Party, Member)
- test_parse_rating_changes_response
- test_parse_standings_response (nested RanklistRow, ProblemResult)
- test_parse_problemset_response
```

### Priority 2C: Cache Logic Tests

#### `test_cache_system.py`

The cache system is a package at `tle/util/cache/` with 5 sub-caches coordinated by `CacheSystem`. Each sub-cache uses the custom `TaskSpec` framework for periodic updates.

```
Tests to write (with mocked API and in-memory cache_db):
- test_cache_system_initialization
- test_contest_cache_load_from_disk
- test_contest_cache_get_contest
- test_contest_cache_get_contest_not_found_raises (ContestNotFound)
- test_contest_cache_contest_by_id_mapping
- test_problem_cache_filters_incomplete_problems
- test_problem_cache_problems_list
- test_rating_changes_cache_stores_to_db
- test_rating_changes_cache_event_published (RatingChangesUpdate)
- test_problemset_cache_fetch
- test_problemset_cache_not_cached_raises (ProblemsetNotCached)
- test_ranklist_cache_prediction
- test_ranklist_cache_not_monitored_raises (RanklistNotMonitored)
```

---

## Layer 3: Integration Tests

These require a mocked Discord context using manual `AsyncMock`/`MagicMock` (not dpytest, since discord.py 1.7.3 is EOL). Cogs access services via `self.bot.user_db`, `self.bot.cf_cache`, and `self.bot.event_sys`, so the bot mock must expose these attributes.

### Priority 3A: Core Command Tests

#### `test_codeforces_cog.py`

```
Tests to write:
- test_gimme_returns_problem_embed
- test_gimme_with_tag_filter
- test_gimme_with_rating_filter
- test_gimme_no_matching_problems
- test_gitgud_creates_challenge
- test_gitgud_already_active
- test_gotgud_marks_complete
- test_nogud_before_time_limit
- test_nogud_after_time_limit
- test_upsolve_finds_unsolved
- test_stalk_lists_problems
- test_teamrate_calculation
```

#### `test_duel_cog.py`

```
Tests to write:
- test_duel_challenge_flow
- test_duel_accept_and_complete
- test_duel_decline
- test_duel_withdraw
- test_duel_draw_offered_and_accepted
- test_duel_invalidate_within_time
- test_duel_invalidate_after_time_fails
- test_duel_rating_update
- test_duel_self_challenge_fails
- test_duel_unregistered_fails
```

#### `test_handles_cog.py`

```
Tests to write:
- test_handle_set
- test_handle_get
- test_handle_remove
- test_handle_identify_flow
- test_role_update_assigns_correct_rank
- test_role_update_removes_old_rank
```

### Priority 3B: Secondary Command Tests

```
- test_cache_control_cog_reload
- test_contests_cog_clist_future
- test_contests_cog_remind_settings
- test_starboard_cog_add_emoji
- test_starboard_cog_reaction_threshold
- test_meta_cog_ping
- test_meta_cog_uptime
- test_graphs_cog_plot_rating (verify BytesIO file output)
```

---

## Layer 4: End-to-End Tests

These are manual/semi-automated tests run against a test Discord server.

### Setup
1. Create a test Discord server
2. Create a test bot application
3. Configure test `.env`
4. Populate with test data

### Test Scenarios

```
E2E-01: Bot startup and initialization
  - Start bot with --nodb flag
  - Verify bot comes online
  - Verify cogs loaded message in logs

E2E-02: Full handle registration flow
  - ;handle set @user tourist
  - Verify role assignment
  - ;handle get @user -> "tourist"
  - ;handle list -> shows user

E2E-03: Full gitgud flow
  - ;gitgud -> problem assigned
  - Solve problem on Codeforces
  - ;gotgud -> challenge completed, score updated
  - ;gitlog -> shows history

E2E-04: Full duel flow
  - ;duel register @user1 / ;duel register @user2
  - ;duel challenge @user2 1400
  - ;duel accept
  - ;duel complete -> ratings updated

E2E-05: Contest reminders
  - ;remind here @role 30
  - Verify reminder sent before contest

E2E-06: Rated virtual contest
  - ;ratedvc <contest_id> @user1 @user2
  - Complete contest
  - ;vcratings -> updated
```

---

## Test Utilities to Build

### 1. CF API Response Builder

Builds realistic NamedTuple instances matching the actual data models in `tle/util/codeforces_api.py`.

```python
from tle.util.codeforces_api import (
    User, Problem, Contest, Submission, RatingChange,
    Party, Member, ProblemResult, RanklistRow,
)

class CFApiResponseBuilder:
    """Build realistic Codeforces API data for testing."""

    @staticmethod
    def user(handle="testuser", rating=1500, **kwargs):
        defaults = dict(
            handle=handle,
            firstName=None,
            lastName=None,
            country=None,
            city=None,
            organization=None,
            contribution=0,
            rating=rating,
            maxRating=rating,
            lastOnlineTimeSeconds=1700000000,
            registrationTimeSeconds=1200000000,
            friendOfCount=0,
            titlePhoto="https://userpic.codeforces.org/no-title.jpg",
        )
        defaults.update(kwargs)
        return User(**defaults)

    @staticmethod
    def problem(contestId=1, index="A", rating=800, tags=None, **kwargs):
        defaults = dict(
            contestId=contestId,
            problemsetName=None,
            index=index,
            name=f"Problem {contestId}{index}",
            type="PROGRAMMING",
            points=None,
            rating=rating,
            tags=tags or [],
        )
        defaults.update(kwargs)
        return Problem(**defaults)

    @staticmethod
    def contest(id=1, phase="FINISHED", **kwargs):
        defaults = dict(
            id=id,
            name=f"Contest {id}",
            startTimeSeconds=1700000000,
            durationSeconds=7200,
            type="CF",
            phase=phase,
            preparedBy=None,
        )
        defaults.update(kwargs)
        return Contest(**defaults)

    @staticmethod
    def submission(verdict="OK", **kwargs):
        defaults = dict(
            id=1,
            contestId=1,
            problem=CFApiResponseBuilder.problem(),
            author=Party(
                contestId=1,
                members=[Member(handle="testuser")],
                participantType="CONTESTANT",
                teamId=None,
                teamName=None,
                ghost=False,
                room=None,
                startTimeSeconds=None,
            ),
            programmingLanguage="Python 3",
            verdict=verdict,
            creationTimeSeconds=1700000000,
            relativeTimeSeconds=0,
        )
        defaults.update(kwargs)
        return Submission(**defaults)

    @staticmethod
    def rating_change(**kwargs):
        defaults = dict(
            contestId=1,
            contestName="Contest 1",
            handle="testuser",
            rank=1,
            ratingUpdateTimeSeconds=1700000000,
            oldRating=1500,
            newRating=1600,
        )
        defaults.update(kwargs)
        return RatingChange(**defaults)
```

### 2. Database Seeder

All seed methods are async to match the aiosqlite-based database layer.

```python
class DbSeeder:
    """Seed a test database with realistic data."""

    async def seed_handles(self, db, count=10): ...
    async def seed_duels(self, db, count=5): ...
    async def seed_challenges(self, db, count=10): ...
    async def seed_starboard(self, db): ...
```

### 3. Mock Discord Context

```python
class MockContext:
    """Rich mock for Discord command context."""

    def __init__(self, guild_id, author_id, channel_id=None):
        ...

    async def send(self, content=None, embed=None, file=None):
        self.sent_messages.append(...)

    @property
    def last_embed(self): ...
    @property
    def last_file(self): ...
```

### 4. Global State Patcher

Helper to safely monkey-patch `codeforces_common` globals for testing.

```python
import contextlib
from tle.util import codeforces_common as cf_common

@contextlib.contextmanager
def patch_cf_common(*, user_db=None, cf_cache=None, event_sys=None):
    """Temporarily replace cf_common globals for testing."""
    originals = {
        'user_db': cf_common.user_db,
        'cf_cache': cf_common.cf_cache,
        'event_sys': cf_common.event_sys,
    }
    try:
        if user_db is not None:
            cf_common.user_db = user_db
        if cf_cache is not None:
            cf_common.cf_cache = cf_cache
        if event_sys is not None:
            cf_common.event_sys = event_sys
        yield
    finally:
        cf_common.user_db = originals['user_db']
        cf_common.cf_cache = originals['cf_cache']
        cf_common.event_sys = originals['event_sys']
```

---

## Coverage Goals

| Phase | Target Coverage | Timeline |
|-------|----------------|----------|
| Layer 1 (Unit) | 80% of utility modules | First |
| Layer 2 (Component) | 70% of DB and cache | Second |
| Layer 3 (Integration) | 50% of cog commands | Third |
| Layer 4 (E2E) | Key user journeys | Ongoing |
| **Overall** | **60% line coverage** | **Target** |

---

## CI Integration

### GitHub Actions Test Job

```yaml
name: Test

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y libcairo2 gir1.2-pango-1.0 libgirepository-2.0-dev
      - name: Install dependencies
        run: pip install ".[test]"
      - name: Run tests
        run: pytest --cov=tle --cov-report=xml -m "not e2e"
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
```

---

## Recommended Test Execution Order

1. ~~**Start with `test_table.py` and `test_handledict.py`** - Simplest modules, zero dependencies~~ DONE
2. ~~**Add `test_codeforces_api.py`** - Data model tests, pure NamedTuple logic and properties~~ DONE
3. ~~**Add `test_codeforces_common.py`** - Pure utility functions, high value~~ DONE
4. ~~**Add `test_rating_calculator.py`** - Mathematically verifiable~~ DONE
5. ~~**Add `test_events.py`** - Core infrastructure, async tests~~ DONE
6. ~~**Add `test_user_db.py`** - Most critical component, async in-memory aiosqlite~~ DONE
7. ~~**Add `test_cache_db.py`** - Cache persistence, async in-memory aiosqlite~~ DONE
8. ~~**Add `test_api_parsing.py`** - API response parsing with fixture JSON files~~ DONE
9. ~~**Add `test_codeforces_cog.py`** - First integration test, validates the pattern~~ DONE
10. ~~**Add `test_tasks.py`** - Task framework (Waiter, Task, TaskSpec, decorators)~~ DONE
11. ~~**Add `test_paginator.py`** - Paginator (chunkify, Paginated, paginate function)~~ DONE
12. ~~**Add `test_cache_system.py`** - Cache sub-system data management~~ DONE
13. **Expand outward** from there

---

## Prerequisites Before Next Testing Phase

1. ~~**discord.py 2.x migration (Step 6)** - Unblocks testing of `events.py`, `tasks.py`, `paginator.py`, and all cog integration tests.~~ DONE
2. ~~**Fixture data collection** - Save real CF API responses as JSON fixtures for replay testing.~~ DONE (5 fixture files in `tests/fixtures/cf_api_responses/`)
3. ~~**Global state management** - Use the `patch_cf_common` context manager (see Test Utilities) to safely replace module-level singletons (`cf_common.user_db`, `cf_common.cf_cache`) during tests.~~ DONE (implemented in `tests/conftest.py`)
