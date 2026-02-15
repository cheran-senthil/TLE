"""Shared fixtures for all tests."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
async def user_db():
    from tle.util.db.user_db_conn import UserDbConn

    db = UserDbConn(':memory:')
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
async def cache_db():
    from tle.util.db.cache_db_conn import CacheDbConn

    db = CacheDbConn(':memory:')
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def make_user():
    """Factory fixture returning a builder for User namedtuples."""
    from tle.util.codeforces_api import User

    def _make(
        handle='tourist',
        firstName=None,
        lastName=None,
        country=None,
        city=None,
        organization=None,
        contribution=0,
        rating=3000,
        maxRating=3800,
        lastOnlineTimeSeconds=0,
        registrationTimeSeconds=0,
        friendOfCount=0,
        titlePhoto='https://example.com/photo.jpg',
    ):
        return User(
            handle=handle,
            firstName=firstName,
            lastName=lastName,
            country=country,
            city=city,
            organization=organization,
            contribution=contribution,
            rating=rating,
            maxRating=maxRating,
            lastOnlineTimeSeconds=lastOnlineTimeSeconds,
            registrationTimeSeconds=registrationTimeSeconds,
            friendOfCount=friendOfCount,
            titlePhoto=titlePhoto,
        )

    return _make


@pytest.fixture
def make_problem():
    """Factory fixture returning a builder for Problem namedtuples."""
    from tle.util.codeforces_api import Problem

    def _make(
        contestId=1,
        problemsetName=None,
        index='A',
        name='Test Problem',
        type='PROGRAMMING',
        points=None,
        rating=1500,
        tags=None,
    ):
        return Problem(
            contestId=contestId,
            problemsetName=problemsetName,
            index=index,
            name=name,
            type=type,
            points=points,
            rating=rating,
            tags=tags if tags is not None else [],
        )

    return _make


@pytest.fixture
def make_contest():
    """Factory fixture returning a builder for Contest namedtuples."""
    from tle.util.codeforces_api import Contest

    def _make(
        id=1,
        name='Codeforces Round #1',
        startTimeSeconds=1_000_000,
        durationSeconds=7200,
        type='CF',
        phase='FINISHED',
        preparedBy=None,
    ):
        return Contest(
            id=id,
            name=name,
            startTimeSeconds=startTimeSeconds,
            durationSeconds=durationSeconds,
            type=type,
            phase=phase,
            preparedBy=preparedBy,
        )

    return _make


@pytest.fixture
def make_rating_change():
    """Factory fixture returning a builder for RatingChange namedtuples."""
    from tle.util.codeforces_api import RatingChange

    def _make(
        contestId=1,
        contestName='Codeforces Round #1',
        handle='tourist',
        rank=1,
        ratingUpdateTimeSeconds=1_000_000,
        oldRating=3000,
        newRating=3050,
    ):
        return RatingChange(
            contestId=contestId,
            contestName=contestName,
            handle=handle,
            rank=rank,
            ratingUpdateTimeSeconds=ratingUpdateTimeSeconds,
            oldRating=oldRating,
            newRating=newRating,
        )

    return _make


@pytest.fixture
def make_member():
    """Factory fixture returning a builder for Member namedtuples."""
    from tle.util.codeforces_api import Member

    def _make(handle='tourist'):
        return Member(handle=handle)

    return _make


@pytest.fixture
def make_party(make_member):
    """Factory fixture returning a builder for Party namedtuples."""
    from tle.util.codeforces_api import Party

    def _make(
        contestId=1,
        members=None,
        participantType='CONTESTANT',
        teamId=None,
        teamName=None,
        ghost=False,
        room=None,
        startTimeSeconds=None,
    ):
        if members is None:
            members = [make_member()]
        return Party(
            contestId=contestId,
            members=members,
            participantType=participantType,
            teamId=teamId,
            teamName=teamName,
            ghost=ghost,
            room=room,
            startTimeSeconds=startTimeSeconds,
        )

    return _make


@pytest.fixture
def make_submission(make_problem, make_party):
    """Factory fixture returning a builder for Submission namedtuples."""
    from tle.util.codeforces_api import Submission

    def _make(
        id=1,
        contestId=1,
        problem=None,
        author=None,
        programmingLanguage='C++',
        verdict='OK',
        creationTimeSeconds=1_000_000,
        relativeTimeSeconds=0,
    ):
        if problem is None:
            problem = make_problem()
        if author is None:
            author = make_party()
        return Submission(
            id=id,
            contestId=contestId,
            problem=problem,
            author=author,
            programmingLanguage=programmingLanguage,
            verdict=verdict,
            creationTimeSeconds=creationTimeSeconds,
            relativeTimeSeconds=relativeTimeSeconds,
        )

    return _make


@pytest.fixture
def event_system():
    """Returns a fresh EventSystem instance for testing."""
    from tle.util.events import EventSystem

    return EventSystem()


@pytest.fixture
def mock_ctx():
    """Returns a mocked Discord Context object."""
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = 12345
    ctx.message = MagicMock()
    ctx.message.author = ctx.author
    ctx.channel = MagicMock()
    return ctx


@contextmanager
def patch_cf_common(**attrs):
    """Context manager to temporarily patch cf_common module-level attributes.

    Usage:
        with patch_cf_common(event_sys=my_event_sys, user_db=mock_db):
            ...
    """
    import tle.util.codeforces_common as cf_common

    originals = {}
    for attr, value in attrs.items():
        originals[attr] = getattr(cf_common, attr)
        setattr(cf_common, attr, value)
    try:
        yield
    finally:
        for attr, value in originals.items():
            setattr(cf_common, attr, value)
