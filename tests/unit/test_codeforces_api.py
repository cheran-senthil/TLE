"""Tests for tle.util.codeforces_api — namedtuples and pure helpers only.

We deliberately skip anything that requires discord.ext.commands (error classes,
API query methods) since discord.py will be updated in Step 6.
"""

from tle.util.codeforces_api import (
    ACMSGURU_BASE_URL,
    CONTESTS_BASE_URL,
    CONTEST_BASE_URL,
    DEFAULT_RATING,
    GYM_BASE_URL,
    PROFILE_BASE_URL,
    UNRATED_RANK,
    Contest,
    Problem,
    RatingChange,
    User,
    make_from_dict,
    rating2rank,
    user_info_chunkify,
)


class TestRating2Rank:
    def test_newbie(self):
        assert rating2rank(800).title == 'Newbie'

    def test_pupil(self):
        assert rating2rank(1200).title == 'Pupil'

    def test_specialist(self):
        assert rating2rank(1400).title == 'Specialist'

    def test_expert(self):
        assert rating2rank(1600).title == 'Expert'

    def test_candidate_master(self):
        assert rating2rank(1900).title == 'Candidate Master'

    def test_master(self):
        assert rating2rank(2100).title == 'Master'

    def test_international_master(self):
        assert rating2rank(2300).title == 'International Master'

    def test_grandmaster(self):
        assert rating2rank(2400).title == 'Grandmaster'

    def test_international_grandmaster(self):
        assert rating2rank(2600).title == 'International Grandmaster'

    def test_legendary_grandmaster(self):
        assert rating2rank(3000).title == 'Legendary Grandmaster'

    def test_unrated(self):
        assert rating2rank(None) is UNRATED_RANK

    def test_negative_rating(self):
        assert rating2rank(-100).title == 'Newbie'

    def test_boundary_1199(self):
        assert rating2rank(1199).title == 'Newbie'


class TestUser:
    def _make_user(self, **kwargs):
        defaults = dict(
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
        )
        defaults.update(kwargs)
        return User(**defaults)

    def test_effective_rating_rated(self):
        u = self._make_user(rating=2500)
        assert u.effective_rating == 2500

    def test_effective_rating_unrated(self):
        u = self._make_user(rating=None)
        assert u.effective_rating == DEFAULT_RATING

    def test_rank_property(self):
        u = self._make_user(rating=3000)
        assert u.rank.title == 'Legendary Grandmaster'

    def test_url(self):
        u = self._make_user(handle='tourist')
        assert u.url == f'{PROFILE_BASE_URL}tourist'


class TestContest:
    def _make_contest(self, **kwargs):
        defaults = dict(
            id=1,
            name='Codeforces Round #1',
            startTimeSeconds=1_000_000,
            durationSeconds=7200,
            type='CF',
            phase='FINISHED',
            preparedBy=None,
        )
        defaults.update(kwargs)
        return Contest(**defaults)

    def test_end_time(self):
        c = self._make_contest(startTimeSeconds=1000, durationSeconds=200)
        assert c.end_time == 1200

    def test_end_time_none(self):
        c = self._make_contest(startTimeSeconds=None, durationSeconds=None)
        assert c.end_time is None

    def test_url_normal(self):
        c = self._make_contest(id=42)
        assert c.url == f'{CONTEST_BASE_URL}42'

    def test_url_gym(self):
        c = self._make_contest(id=200_000)
        assert c.url == f'{GYM_BASE_URL}200000'

    def test_register_url(self):
        c = self._make_contest(id=42)
        assert c.register_url == f'{CONTESTS_BASE_URL}42'

    def test_matches_positive(self):
        c = self._make_contest(name='Codeforces Round #100')
        assert c.matches(['round'])

    def test_matches_negative(self):
        c = self._make_contest(name='Codeforces Round #100')
        assert not c.matches(['educational'])

    def test_matches_special_chars(self):
        c = self._make_contest(name='Codeforces Round #100')
        assert c.matches(['Round #100'])


class TestProblem:
    def _make_problem(self, **kwargs):
        defaults = dict(
            contestId=1,
            problemsetName=None,
            index='A',
            name='Test Problem',
            type='PROGRAMMING',
            points=None,
            rating=1500,
            tags=['dp', 'math'],
        )
        defaults.update(kwargs)
        return Problem(**defaults)

    def test_contest_identifier(self):
        p = self._make_problem(contestId=42, index='B')
        assert p.contest_identifier == '42B'

    def test_url_normal(self):
        p = self._make_problem(contestId=42, index='A')
        assert p.url == f'{CONTEST_BASE_URL}42/problem/A'

    def test_url_gym(self):
        p = self._make_problem(contestId=200_000, index='A')
        assert p.url == f'{GYM_BASE_URL}200000/problem/A'

    def test_url_acmsguru(self):
        p = self._make_problem(contestId=None, problemsetName='acmsguru', index='101')
        assert p.url == f'{ACMSGURU_BASE_URL}problem/99999/101'

    def test_has_metadata_true(self):
        p = self._make_problem(contestId=1, rating=1500)
        assert p.has_metadata() is True

    def test_has_metadata_no_contest(self):
        p = self._make_problem(contestId=None, rating=1500)
        assert p.has_metadata() is False

    def test_has_metadata_no_rating(self):
        p = self._make_problem(contestId=1, rating=None)
        assert p.has_metadata() is False

    def test_matches_all_tags(self):
        p = self._make_problem(tags=['dp', 'math', 'greedy'])
        assert p.matches_all_tags(['dp', 'math'])

    def test_matches_all_tags_partial_match(self):
        p = self._make_problem(tags=['dp', 'math'])
        assert not p.matches_all_tags(['dp', 'greedy'])

    def test_matches_any_tag(self):
        p = self._make_problem(tags=['dp', 'math'])
        assert p.matches_any_tag(['greedy', 'dp'])

    def test_matches_any_tag_none(self):
        p = self._make_problem(tags=['dp', 'math'])
        assert not p.matches_any_tag(['greedy', 'strings'])

    def test_get_matched_tags(self):
        p = self._make_problem(tags=['dp', 'math', 'number theory'])
        matched = p.get_matched_tags(['math'])
        assert 'math' in matched


class TestMakeFromDict:
    def test_basic(self):
        d = {
            'contestId': 1,
            'contestName': 'Round #1',
            'handle': 'tourist',
            'rank': 1,
            'ratingUpdateTimeSeconds': 1000,
            'oldRating': 3000,
            'newRating': 3050,
        }
        rc = make_from_dict(RatingChange, d)
        assert rc.handle == 'tourist'
        assert rc.newRating == 3050

    def test_missing_fields(self):
        d = {'handle': 'tourist'}
        rc = make_from_dict(RatingChange, d)
        assert rc.handle == 'tourist'
        assert rc.contestId is None

    def test_extra_fields(self):
        d = {
            'contestId': 1,
            'contestName': 'Round #1',
            'handle': 'tourist',
            'rank': 1,
            'ratingUpdateTimeSeconds': 1000,
            'oldRating': 3000,
            'newRating': 3050,
            'extraField': 'ignored',
        }
        rc = make_from_dict(RatingChange, d)
        assert rc.handle == 'tourist'


class TestUserInfoChunkify:
    def test_small(self):
        handles = ['tourist', 'Petr', 'jiangly']
        chunks = list(user_info_chunkify(handles))
        assert len(chunks) == 1
        assert chunks[0] == handles

    def test_empty(self):
        chunks = list(user_info_chunkify([]))
        assert len(chunks) == 0

    def test_handle_limit(self):
        # Use very short handles so size limit doesn't kick in first
        handles = [f'u{i}' for i in range(10_001)]
        chunks = list(user_info_chunkify(handles))
        assert len(chunks) == 2
        assert len(chunks[0]) == 10_000

    def test_size_limit(self):
        # Each handle is about 100 chars, 2^16 = 65536 bytes
        handles = ['x' * 100 for _ in range(1000)]
        chunks = list(user_info_chunkify(handles))
        assert len(chunks) > 1
