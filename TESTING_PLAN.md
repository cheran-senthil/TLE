# TLE Testing Plan

## Current State

The project has **zero tests**. `pytest` is listed as an optional dependency in `pyproject.toml` but there is no `tests/` directory, no test configuration, and no test CI job. The codebase has tight coupling to external services (Discord API, Codeforces API, SQLite) and heavy use of global state, which makes testing challenging but not impossible.

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
         - Database operations against real SQLite (in-memory)
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
│   ├── test_constants.py
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
    "dpytest",      # discord.py testing utility
]
```

### Key Fixtures (`tests/conftest.py`)

```python
import sqlite3
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def in_memory_db():
    """Provides a fresh in-memory SQLite database."""
    from tle.util.db.user_db_conn import UserDbConn
    db = UserDbConn(":memory:")
    yield db
    db.close()

@pytest.fixture
def cache_db():
    """Provides a fresh cache database."""
    from tle.util.db.cache_db_conn import CacheDbConn
    db = CacheDbConn(":memory:")
    yield db
    db.close()

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
    """Provides a sample Codeforces User namedtuple."""
    from tle.util.codeforces_api import User
    return User(
        handle="tourist",
        email=None,
        vkId=None,
        openId=None,
        firstName="Gennady",
        lastName="Korotkevich",
        country="Belarus",
        city="Gomel",
        organization="ITMO University",
        contribution=100,
        rank="legendary grandmaster",
        rating=3800,
        maxRank="legendary grandmaster",
        maxRating=3979,
        lastOnlineTimeSeconds=1700000000,
        registrationTimeSeconds=1200000000,
        friendOfCount=50000,
        avatar="//userpic.codeforces.org/...",
        titlePhoto="//userpic.codeforces.org/...",
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
```

#### `test_handledict.py`

```
Tests to write:
- test_case_insensitive_lookup
- test_case_insensitive_set
- test_case_insensitive_contains
- test_preserves_original_key
```

#### `test_events.py`

```
Tests to write:
- test_register_listener
- test_publish_fires_listener
- test_publish_no_listeners
- test_wait_for_returns_event
- test_multiple_listeners
- test_listener_exception_handling
```

### Priority 1B: Data Model Tests

#### `test_codeforces_api.py` (models only)

```
Tests to write:
- test_user_creation
- test_problem_url_normal_contest
- test_problem_url_gym_contest
- test_problem_matches_all_tags
- test_problem_matches_any_tag
- test_problem_contest_identifier
- test_contest_end_time
- test_contest_url_normal
- test_contest_url_gym
- test_contest_register_url
- test_contest_matches_markers
- test_contest_phases
- test_submission_creation
- test_rating_change_creation
```

### Priority 1C: SubFilter Tests

#### `test_subfilter.py`

```
Tests to write:
- test_parse_tag_flags
- test_parse_ban_tag_flags
- test_parse_type_flags_contest
- test_parse_type_flags_virtual
- test_parse_date_range
- test_parse_rating_range
- test_parse_contest_filter
- test_parse_index_filter
- test_parse_team_flag
- test_parse_mixed_flags
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
- test_waiter_creation
- test_waiter_fixed_delay
- test_task_spec_descriptor_get
- test_task_start_and_stop
- test_task_manual_trigger
- test_task_exception_handler_called
- test_task_waiter_required_error
- test_task_already_running_error
```

---

## Layer 2: Component Tests

### Priority 2A: Database Tests

#### `test_user_db.py`

```
Tests to write (using in-memory SQLite):
- test_create_tables_succeeds
- test_set_and_get_handle
- test_set_handle_duplicate_raises
- test_remove_handle
- test_get_handles_for_guild
- test_get_user_id
- test_set_inactive
- test_update_status
- test_cache_and_fetch_cf_user
- test_new_challenge
- test_check_challenge_exists
- test_check_challenge_none
- test_complete_challenge
- test_skip_challenge
- test_get_gudgitters
- test_gitlog
- test_get_noguds
- test_register_duelist
- test_is_duelist
- test_create_duel
- test_start_duel
- test_complete_duel_challenger_wins
- test_complete_duel_draw
- test_cancel_duel
- test_invalidate_duel
- test_get_duel_rating
- test_get_duels
- test_get_pair_duels
- test_get_recent_duels
- test_get_ongoing_duels
- test_get_duel_stats (wins, losses, draws, declined)
- test_reminder_settings_crud
- test_rankup_channel_crud
- test_auto_role_update_toggle
- test_rated_vc_lifecycle
- test_vc_rating_update_and_history
- test_starboard_emoji_crud
- test_starboard_channel_crud
- test_starboard_message_crud
- test_starboard_migration_from_v0
```

#### `test_cache_db.py`

```
Tests to write:
- test_cache_contests
- test_fetch_contests
- test_cache_problems
- test_fetch_problems
- test_cache_rating_changes
- test_fetch_rating_changes
- test_problem_tag_serialization
- test_problemset_cache_and_fetch
```

### Priority 2B: API Response Parsing

#### `test_api_parsing.py`

```
Tests to write (using fixture JSON files):
- test_parse_contest_list_response
- test_parse_user_info_response
- test_parse_user_status_response
- test_parse_rating_changes_response
- test_parse_standings_response
- test_parse_problemset_response
- test_parse_error_response
- test_parse_not_found_response
- test_parse_rate_limited_response
```

### Priority 2C: Cache Logic Tests

#### `test_cache_system.py`

```
Tests to write (with mocked API):
- test_contest_cache_load_from_disk
- test_contest_cache_get_contest
- test_contest_cache_get_contest_not_found_raises
- test_contest_cache_delay_calculation_normal
- test_contest_cache_delay_calculation_active
- test_problem_cache_filters_incomplete_problems
- test_rating_changes_cache_blacklist
- test_rating_changes_cache_event_published
- test_ranklist_cache_prediction
```

---

## Layer 3: Integration Tests

These require a mocked Discord context (using `dpytest` or manual mocking).

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
- test_contests_cog_clist_future
- test_contests_cog_remind_settings
- test_starboard_cog_add_emoji
- test_starboard_cog_reaction_threshold
- test_meta_cog_ping
- test_meta_cog_uptime
- test_graphs_cog_plot_rating (verify file output)
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

```python
class CFApiResponseBuilder:
    """Build realistic Codeforces API responses for testing."""

    @staticmethod
    def user(handle="testuser", rating=1500, **kwargs):
        ...

    @staticmethod
    def problem(contestId=1, index="A", rating=800, tags=None, **kwargs):
        ...

    @staticmethod
    def submission(verdict="OK", **kwargs):
        ...

    @staticmethod
    def contest(id=1, phase="FINISHED", **kwargs):
        ...
```

### 2. Database Seeder

```python
class DbSeeder:
    """Seed a test database with realistic data."""

    def seed_handles(self, db, count=10): ...
    def seed_duels(self, db, count=5): ...
    def seed_challenges(self, db, count=10): ...
    def seed_starboard(self, db): ...
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

1. **Start with `test_table.py` and `test_handledict.py`** - Simplest modules, zero dependencies
2. **Add `test_codeforces_common.py`** - Pure utility functions, high value
3. **Add `test_rating_calculator.py`** - Mathematically verifiable
4. **Add `test_events.py`** - Core infrastructure
5. **Add `test_user_db.py`** - Most critical component, in-memory SQLite makes it easy
6. **Add `test_api_parsing.py`** - Requires fixture files but high value
7. **Add `test_codeforces_cog.py`** - First integration test, validates the pattern
8. **Expand outward** from there

---

## Prerequisites Before Testing

1. **Dependency injection** - The global singletons (`cf_common.user_db`, `cf_common.cache2`) must be replaceable for testing. At minimum, add setter functions or accept them as constructor parameters.
2. **`aiosqlite` migration** - Testing async code with sync SQLite is painful. Migrate first.
3. **Fixture data collection** - Save real CF API responses as JSON fixtures for replay testing.
