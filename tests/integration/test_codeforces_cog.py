"""Integration tests for tle.cogs.codeforces — Codeforces cog commands."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tle.cogs.codeforces import Codeforces, CodeforcesCogError
from tle.util.codeforces_api import Contest, Member, Party, Problem, Submission, User

pytestmark = pytest.mark.integration


def _make_user(handle='tourist', rating=3000):
    return User(
        handle=handle,
        firstName=None,
        lastName=None,
        country=None,
        city=None,
        organization=None,
        contribution=0,
        rating=rating,
        maxRating=rating,
        lastOnlineTimeSeconds=0,
        registrationTimeSeconds=0,
        friendOfCount=0,
        titlePhoto='https://example.com/photo.jpg',
    )


def _make_contest(id=1, name='Round #1', start=1_000_000):
    return Contest(
        id=id,
        name=name,
        startTimeSeconds=start,
        durationSeconds=7200,
        type='CF',
        phase='FINISHED',
        preparedBy=None,
    )


def _make_problem(contestId=1, index='A', name='Problem A', rating=1500, tags=None):
    return Problem(
        contestId=contestId,
        problemsetName=None,
        index=index,
        name=name,
        type='PROGRAMMING',
        points=None,
        rating=rating,
        tags=tags or [],
    )


def _make_submission(problem, verdict='OK'):
    party = Party(
        contestId=problem.contestId,
        members=[Member(handle='tourist')],
        participantType='CONTESTANT',
        teamId=None,
        teamName=None,
        ghost=False,
        room=None,
        startTimeSeconds=None,
    )
    return Submission(
        id=1,
        contestId=problem.contestId,
        problem=problem,
        author=party,
        programmingLanguage='C++',
        verdict=verdict,
        creationTimeSeconds=1_000_000,
        relativeTimeSeconds=0,
    )


@pytest.fixture
async def cog_env(user_db):
    """Set up a Codeforces cog with mocked bot and services."""
    bot = MagicMock()
    bot.user_db = user_db

    # Register a handle for our test user
    await user_db.set_handle(12345, 1, 'tourist')
    cf_user = _make_user(handle='tourist', rating=3000)
    await user_db.cache_cf_user(cf_user)

    # Set up cf_cache mock
    contest = _make_contest(id=1)
    problems = [
        _make_problem(contestId=1, index='A', name='Easy', rating=3000),
        _make_problem(contestId=1, index='B', name='Medium', rating=3100),
        _make_problem(contestId=1, index='C', name='Hard', rating=3200),
    ]

    cf_cache = MagicMock()
    cf_cache.problem_cache.problems = problems
    cf_cache.contest_cache.get_contest.return_value = contest
    cf_cache.contest_cache.contest_by_id = {1: contest}
    bot.cf_cache = cf_cache

    cog = Codeforces(bot)

    # Mock context
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = 12345
    ctx.author.__str__ = MagicMock(return_value='TestUser#1234')
    ctx.message = MagicMock()
    ctx.message.author = ctx.author
    ctx.guild = MagicMock()
    ctx.guild.id = 1

    return cog, ctx, bot, problems


# --- _validate_gitgud_status ---


class TestValidateGitgudStatus:
    async def test_invalid_delta_not_multiple_of_100(self, cog_env):
        cog, ctx, _, _ = cog_env
        with pytest.raises(CodeforcesCogError, match='multiple of 100'):
            await cog._validate_gitgud_status(ctx, delta=50)

    async def test_delta_too_large(self, cog_env):
        cog, ctx, _, _ = cog_env
        with pytest.raises(CodeforcesCogError, match='Delta must range'):
            await cog._validate_gitgud_status(ctx, delta=400)

    async def test_delta_too_negative(self, cog_env):
        cog, ctx, _, _ = cog_env
        with pytest.raises(CodeforcesCogError, match='Delta must range'):
            await cog._validate_gitgud_status(ctx, delta=-400)

    async def test_active_challenge_raises(self, cog_env):
        cog, ctx, bot, problems = cog_env
        # Create an active challenge
        p = problems[0]
        await bot.user_db.new_challenge(
            12345, datetime.datetime.now().timestamp(), p, 0
        )
        with pytest.raises(CodeforcesCogError, match='active challenge'):
            await cog._validate_gitgud_status(ctx, delta=0)

    async def test_delta_none_skips_delta_checks(self, cog_env):
        cog, ctx, _, _ = cog_env
        # delta=None should skip delta validation (used by upsolve)
        await cog._validate_gitgud_status(ctx, delta=None)


# --- _gitgud ---


class TestGitgud:
    async def test_creates_challenge_and_sends_embed(self, cog_env):
        cog, ctx, bot, problems = cog_env
        problem = problems[0]
        await cog._gitgud(ctx, 'tourist', problem, 0)

        # Should have sent a message with embed
        ctx.send.assert_awaited_once()
        call_args = ctx.send.call_args
        assert 'tourist' in call_args.args[0]
        assert call_args.kwargs['embed'] is not None

        # Should have stored challenge in DB
        active = await bot.user_db.check_challenge(12345)
        assert active is not None


# --- gimme ---


class TestGimme:
    @patch('tle.cogs.codeforces.cf')
    @patch('tle.cogs.codeforces.cf_common')
    async def test_returns_embed(self, mock_cf_common, mock_cf, cog_env):
        cog, ctx, bot, problems = cog_env

        # Mock resolve_handles
        mock_cf_common.resolve_handles = AsyncMock(return_value=['tourist'])
        mock_cf_common.parse_tags.return_value = []
        mock_cf_common.parse_rating.return_value = 3000
        mock_cf_common.is_contest_writer.return_value = False
        mock_cf_common.user_guard = MagicMock(side_effect=lambda **kwargs: lambda f: f)
        mock_cf_common.active_groups = {}

        # Mock cf.user.status — return no solved submissions
        mock_cf.user.status = AsyncMock(return_value=[])

        # Need to rebind fetch_cf_user since we need the handle
        bot.user_db.fetch_cf_user = AsyncMock(
            return_value=_make_user(handle='tourist', rating=3000)
        )

        # Call the underlying callback directly
        await cog.gimme.callback(cog, ctx)
        ctx.send.assert_awaited_once()
        call_args = ctx.send.call_args
        assert 'tourist' in call_args.args[0]

    @patch('tle.cogs.codeforces.cf')
    @patch('tle.cogs.codeforces.cf_common')
    async def test_no_problems_raises(self, mock_cf_common, mock_cf, cog_env):
        cog, ctx, bot, _ = cog_env

        mock_cf_common.resolve_handles = AsyncMock(return_value=['tourist'])
        mock_cf_common.parse_tags.return_value = []
        mock_cf_common.parse_rating.return_value = 9999  # impossible rating
        mock_cf_common.is_contest_writer.return_value = False
        mock_cf_common.user_guard = MagicMock(side_effect=lambda **kwargs: lambda f: f)
        mock_cf_common.active_groups = {}

        mock_cf.user.status = AsyncMock(return_value=[])

        bot.user_db.fetch_cf_user = AsyncMock(
            return_value=_make_user(handle='tourist', rating=9999)
        )

        with pytest.raises(CodeforcesCogError, match='not found'):
            await cog.gimme.callback(cog, ctx)
