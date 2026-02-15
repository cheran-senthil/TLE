"""Shared fixtures for all tests."""

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
