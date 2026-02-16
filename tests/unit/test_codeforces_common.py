"""Tests for tle.util.codeforces_common — pure functions only.

We skip anything that depends on discord globals, bot state, or discord.ext.commands.
"""

import time

import pytest

from tle.util import codeforces_api as cf
from tle.util.codeforces_common import (
    ParamParseError,
    SubFilter,
    days_ago,
    filter_flags,
    fix_urls,
    is_nonstandard_contest,
    negate_flags,
    parse_date,
    parse_rating,
    parse_tags,
    pretty_time_format,
    time_format,
)


class TestTimeFormat:
    def test_zero(self):
        assert time_format(0) == (0, 0, 0, 0)

    def test_full_day(self):
        assert time_format(86400) == (1, 0, 0, 0)

    def test_mixed(self):
        assert time_format(90061) == (1, 1, 1, 1)

    def test_only_seconds(self):
        assert time_format(45) == (0, 0, 0, 45)

    def test_hours_and_minutes(self):
        assert time_format(3661) == (0, 1, 1, 1)


class TestPrettyTimeFormat:
    def test_default(self):
        result = pretty_time_format(90061)
        assert '1 day' in result
        assert '1 hour' in result
        assert '1 minute' in result

    def test_zero(self):
        result = pretty_time_format(0)
        assert '0 seconds' in result

    def test_shorten(self):
        result = pretty_time_format(86400, shorten=True)
        assert '1d' in result

    def test_only_most_significant(self):
        result = pretty_time_format(90061, only_most_significant=True)
        assert 'day' in result
        assert 'hour' not in result

    def test_always_seconds(self):
        result = pretty_time_format(3600, always_seconds=True)
        assert 'second' in result

    def test_singular(self):
        result = pretty_time_format(3600)
        assert '1 hour' in result

    def test_plural(self):
        result = pretty_time_format(7200)
        assert '2 hours' in result


class TestDaysAgo:
    def test_today(self):
        assert days_ago(time.time()) == 'today'

    def test_yesterday(self):
        assert days_ago(time.time() - 86400) == 'yesterday'

    def test_multiple_days(self):
        result = days_ago(time.time() - 5 * 86400)
        assert '5 days ago' in result


class TestParseDate:
    def test_8_char(self):
        result = parse_date('01012020')
        assert result > 0

    def test_6_char(self):
        result = parse_date('012020')
        assert result > 0

    def test_4_char(self):
        result = parse_date('2020')
        assert result > 0

    def test_invalid(self):
        with pytest.raises(ParamParseError):
            parse_date('abc')

    def test_invalid_length(self):
        with pytest.raises(ParamParseError):
            parse_date('12345')


class TestParseTags:
    def test_basic(self):
        tags = parse_tags(['+dp', '+math', 'greedy'], prefix='+')
        assert tags == ['dp', 'math']

    def test_no_match(self):
        tags = parse_tags(['dp', 'math'], prefix='+')
        assert tags == []

    def test_bantags(self):
        tags = parse_tags(['~dp', '~math', '+greedy'], prefix='~')
        assert tags == ['dp', 'math']


class TestParseRating:
    def test_found(self):
        assert parse_rating(['dp', '1500', 'math']) == 1500

    def test_not_found(self):
        assert parse_rating(['dp', 'math']) is None

    def test_default(self):
        assert parse_rating(['dp'], default_value=800) == 800


class TestFilterFlags:
    def test_basic(self):
        args = ['+practice', 'dp', '+virtual']
        params = ['+practice', '+virtual', '+contest']
        flags, rest = filter_flags(args, params)
        assert flags == [True, True, False]
        assert rest == ['dp']

    def test_no_flags(self):
        flags, rest = filter_flags(['dp', 'math'], ['+practice'])
        assert flags == [False]
        assert rest == ['dp', 'math']


class TestNegateFlags:
    def test_basic(self):
        assert negate_flags(True, False, True) == [False, True, False]

    def test_all_false(self):
        assert negate_flags(False, False) == [True, True]


class TestFixUrls:
    def test_protocol_relative(self):
        u = cf.User(
            handle='test',
            firstName=None,
            lastName=None,
            country=None,
            city=None,
            organization=None,
            contribution=0,
            rating=1500,
            maxRating=1500,
            lastOnlineTimeSeconds=0,
            registrationTimeSeconds=0,
            friendOfCount=0,
            titlePhoto='//example.com/photo.jpg',
        )
        fixed = fix_urls(u)
        assert fixed.titlePhoto == 'https://example.com/photo.jpg'

    def test_already_https(self):
        u = cf.User(
            handle='test',
            firstName=None,
            lastName=None,
            country=None,
            city=None,
            organization=None,
            contribution=0,
            rating=1500,
            maxRating=1500,
            lastOnlineTimeSeconds=0,
            registrationTimeSeconds=0,
            friendOfCount=0,
            titlePhoto='https://example.com/photo.jpg',
        )
        fixed = fix_urls(u)
        assert fixed.titlePhoto == 'https://example.com/photo.jpg'


class TestIsNonstandardContest:
    def _contest(self, name):
        return cf.Contest(
            id=1,
            name=name,
            startTimeSeconds=0,
            durationSeconds=7200,
            type='CF',
            phase='FINISHED',
            preparedBy=None,
        )

    def test_wild(self):
        assert is_nonstandard_contest(self._contest('April Fools Wild Round'))

    def test_normal(self):
        c = self._contest('Codeforces Round #800 (Div. 2)')
        assert is_nonstandard_contest(c) is False

    def test_kotlin(self):
        assert is_nonstandard_contest(self._contest('Kotlin Heroes'))

    def test_unrated(self):
        assert is_nonstandard_contest(self._contest('Unrated Round'))


class TestSubFilterParse:
    def test_tags(self):
        sf = SubFilter()
        rest = sf.parse(['+dp', '+math'])
        assert set(sf.tags) == {'dp', 'math'}
        assert rest == []

    def test_bantags(self):
        sf = SubFilter()
        rest = sf.parse(['~dp', '~math'])
        assert set(sf.bantags) == {'dp', 'math'}
        assert rest == []

    def test_type_contest(self):
        sf = SubFilter()
        sf.parse(['+contest'])
        assert 'CONTESTANT' in sf.types

    def test_type_virtual(self):
        sf = SubFilter()
        sf.parse(['+virtual'])
        assert 'VIRTUAL' in sf.types

    def test_type_practice(self):
        sf = SubFilter()
        sf.parse(['+practice'])
        assert 'PRACTICE' in sf.types

    def test_type_outof(self):
        sf = SubFilter()
        sf.parse(['+outof'])
        assert 'OUT_OF_COMPETITION' in sf.types

    def test_defaults_all_types(self):
        sf = SubFilter()
        sf.parse(['+dp'])
        assert len(sf.types) == 4

    def test_team(self):
        sf = SubFilter()
        sf.parse(['+team'])
        assert sf.team is True

    def test_contest_filter(self):
        sf = SubFilter()
        sf.parse(['c+round'])
        assert 'round' in sf.contests

    def test_index_filter(self):
        sf = SubFilter()
        sf.parse(['i+A'])
        assert 'A' in sf.indices

    def test_rating_range(self):
        sf = SubFilter()
        sf.parse(['r>=1200', 'r<=1800'])
        assert sf.rlo == 1200
        assert sf.rhi == 1800

    def test_date_range(self):
        sf = SubFilter()
        sf.parse(['d>=2020', 'd<2021'])
        assert sf.dlo > 0
        assert sf.dhi > sf.dlo

    def test_unrecognized_args(self):
        sf = SubFilter()
        rest = sf.parse(['unknown', '+dp'])
        assert 'unknown' in rest

    def test_empty_tag_raises(self):
        sf = SubFilter()
        with pytest.raises(ParamParseError):
            sf.parse(['+'])

    def test_empty_bantag_raises(self):
        sf = SubFilter()
        with pytest.raises(ParamParseError):
            sf.parse(['~'])

    def test_mixed(self):
        sf = SubFilter()
        rest = sf.parse(['+dp', '~greedy', '+contest', 'r>=1200', 'other'])
        assert sf.tags == ['dp']
        assert sf.bantags == ['greedy']
        assert 'CONTESTANT' in sf.types
        assert sf.rlo == 1200
        assert rest == ['other']


class TestSubFilterRatingChanges:
    def test_date_range_filtering(self, make_rating_change):
        sf = SubFilter()
        sf.dlo = 1000
        sf.dhi = 2000
        changes = [
            make_rating_change(ratingUpdateTimeSeconds=500),
            make_rating_change(ratingUpdateTimeSeconds=1500),
            make_rating_change(ratingUpdateTimeSeconds=2500),
        ]
        filtered = sf.filter_rating_changes(changes)
        assert len(filtered) == 1
        assert filtered[0].ratingUpdateTimeSeconds == 1500

    def test_all_in_range(self, make_rating_change):
        sf = SubFilter()
        sf.dlo = 0
        sf.dhi = 10**10
        changes = [
            make_rating_change(ratingUpdateTimeSeconds=100),
            make_rating_change(ratingUpdateTimeSeconds=200),
        ]
        filtered = sf.filter_rating_changes(changes)
        assert len(filtered) == 2

    def test_none_in_range(self, make_rating_change):
        sf = SubFilter()
        sf.dlo = 1000
        sf.dhi = 2000
        changes = [
            make_rating_change(ratingUpdateTimeSeconds=500),
            make_rating_change(ratingUpdateTimeSeconds=2500),
        ]
        filtered = sf.filter_rating_changes(changes)
        assert len(filtered) == 0
