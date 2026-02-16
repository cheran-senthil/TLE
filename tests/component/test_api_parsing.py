"""Component tests for CF API response parsing.

Tests make_from_dict with real JSON fixtures.
"""

import json
from pathlib import Path

import pytest

from tle.util.codeforces_api import (
    Contest,
    Member,
    Party,
    Problem,
    ProblemResult,
    RanklistRow,
    RatingChange,
    Submission,
    User,
    make_from_dict,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / 'fixtures' / 'cf_api_responses'


def _load_fixture(name):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


# --- contest.list parsing ---


class TestParseContestList:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_fixture('contest_list.json')

    def test_parse_all_contests(self):
        contests = [make_from_dict(Contest, d) for d in self.data]
        assert len(contests) == 2

    def test_field_values(self):
        contest = make_from_dict(Contest, self.data[0])
        assert contest.id == 1
        assert contest.name == 'Codeforces Beta Round #1'
        assert contest.type == 'CF'
        assert contest.phase == 'FINISHED'
        assert contest.durationSeconds == 7200
        assert contest.startTimeSeconds == 1265979600

    def test_missing_optional_defaults_none(self):
        contest = make_from_dict(Contest, self.data[0])
        assert contest.preparedBy is None

    def test_prepared_by_present(self):
        contest = make_from_dict(Contest, self.data[1])
        assert contest.preparedBy == 'MikeMirzayanov'


# --- user.info parsing ---


class TestParseUserInfo:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_fixture('user_info.json')

    def test_parse_user(self):
        user = make_from_dict(User, self.data[0])
        assert isinstance(user, User)

    def test_field_values(self):
        user = make_from_dict(User, self.data[0])
        assert user.handle == 'tourist'
        assert user.firstName == 'Gennady'
        assert user.lastName == 'Korotkevich'
        assert user.country == 'Belarus'
        assert user.city == 'Gomel'
        assert user.organization == 'ITMO University'
        assert user.contribution == 158
        assert user.rating == 3825
        assert user.maxRating == 3979
        assert user.lastOnlineTimeSeconds == 1700000000
        assert user.registrationTimeSeconds == 1265987288
        assert user.friendOfCount == 30000

    def test_effective_rating(self):
        user = make_from_dict(User, self.data[0])
        assert user.effective_rating == 3825

    def test_rank_property(self):
        user = make_from_dict(User, self.data[0])
        assert user.rank.title == 'Legendary Grandmaster'


# --- user.status parsing (nested) ---


class TestParseUserStatus:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_fixture('user_status.json')

    def _parse_submission(self, raw):
        """Replicate the nested parsing from cf.user.status."""
        raw['problem'] = make_from_dict(Problem, raw['problem'])
        raw['author']['members'] = [
            make_from_dict(Member, m) for m in raw['author']['members']
        ]
        raw['author'] = make_from_dict(Party, raw['author'])
        return make_from_dict(Submission, raw)

    def test_parse_submission(self):
        sub = self._parse_submission(self.data[0])
        assert isinstance(sub, Submission)
        assert sub.id == 123456789

    def test_nested_problem(self):
        sub = self._parse_submission(self.data[0])
        assert isinstance(sub.problem, Problem)
        assert sub.problem.name == 'Theatre Square'
        assert sub.problem.rating == 1000
        assert sub.problem.tags == ['math']

    def test_nested_party(self):
        sub = self._parse_submission(self.data[0])
        assert isinstance(sub.author, Party)
        assert sub.author.participantType == 'CONTESTANT'

    def test_nested_member(self):
        sub = self._parse_submission(self.data[0])
        assert isinstance(sub.author.members[0], Member)
        assert sub.author.members[0].handle == 'tourist'

    def test_verdict_and_language(self):
        sub = self._parse_submission(self.data[0])
        assert sub.verdict == 'OK'
        assert sub.programmingLanguage == 'GNU C++17'


# --- contest.ratingChanges parsing ---


class TestParseRatingChanges:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_fixture('rating_changes.json')

    def test_parse_changes(self):
        changes = [make_from_dict(RatingChange, d) for d in self.data]
        assert len(changes) == 1

    def test_field_values(self):
        change = make_from_dict(RatingChange, self.data[0])
        assert change.contestId == 1
        assert change.contestName == 'Codeforces Beta Round #1'
        assert change.handle == 'tourist'
        assert change.rank == 1
        assert change.ratingUpdateTimeSeconds == 1265986800
        assert change.oldRating == 1500
        assert change.newRating == 1602


# --- contest.standings parsing (nested) ---


class TestParseContestStandings:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_fixture('contest_standings.json')

    def _parse_standings(self):
        """Replicate the nested parsing from cf.contest.standings."""
        resp = self.data
        contest = make_from_dict(Contest, resp['contest'])
        problems = [make_from_dict(Problem, d) for d in resp['problems']]
        for row in resp['rows']:
            row['party']['members'] = [
                make_from_dict(Member, m) for m in row['party']['members']
            ]
            row['party'] = make_from_dict(Party, row['party'])
            row['problemResults'] = [
                make_from_dict(ProblemResult, pr) for pr in row['problemResults']
            ]
        ranklist = [make_from_dict(RanklistRow, row) for row in resp['rows']]
        return contest, problems, ranklist

    def test_parse_contest(self):
        contest, _, _ = self._parse_standings()
        assert isinstance(contest, Contest)
        assert contest.id == 1

    def test_parse_problems(self):
        _, problems, _ = self._parse_standings()
        assert len(problems) == 2
        assert problems[0].index == 'A'
        assert problems[1].index == 'B'

    def test_ranklist_row_fields(self):
        _, _, ranklist = self._parse_standings()
        assert len(ranklist) == 1
        row = ranklist[0]
        assert row.rank == 1
        assert row.points == 1500.0
        assert row.penalty == 120

    def test_problem_result_fields(self):
        _, _, ranklist = self._parse_standings()
        pr = ranklist[0].problemResults[0]
        assert isinstance(pr, ProblemResult)
        assert pr.points == 500.0
        assert pr.rejectedAttemptCount == 0
        assert pr.type == 'FINAL'
        assert pr.bestSubmissionTimeSeconds == 300

    def test_party_in_standings(self):
        _, _, ranklist = self._parse_standings()
        party = ranklist[0].party
        assert isinstance(party, Party)
        assert party.participantType == 'CONTESTANT'
        assert len(party.members) == 1
        assert party.members[0].handle == 'tourist'
