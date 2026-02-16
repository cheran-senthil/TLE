import asyncio
import functools
import itertools
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, NamedTuple

import aiohttp
from discord.ext import commands

# ruff: noqa: N815

API_BASE_URL = 'https://codeforces.com/api/'
CONTEST_BASE_URL = 'https://codeforces.com/contest/'
CONTESTS_BASE_URL = 'https://codeforces.com/contests/'
GYM_BASE_URL = 'https://codeforces.com/gym/'
PROFILE_BASE_URL = 'https://codeforces.com/profile/'
ACMSGURU_BASE_URL = 'https://codeforces.com/problemsets/acmsguru/'
GYM_ID_THRESHOLD = 100000
DEFAULT_RATING = 1500

logger = logging.getLogger(__name__)


class Rank(NamedTuple):
    """Codeforces rank."""

    low: int | None
    high: int | None
    title: str
    title_abbr: str | None
    color_graph: str | None
    color_embed: int | None


RATED_RANKS = (
    Rank(-(10**9), 1200, 'Newbie', 'N', '#CCCCCC', 0x808080),
    Rank(1200, 1400, 'Pupil', 'P', '#77FF77', 0x008000),
    Rank(1400, 1600, 'Specialist', 'S', '#77DDBB', 0x03A89E),
    Rank(1600, 1900, 'Expert', 'E', '#AAAAFF', 0x0000FF),
    Rank(1900, 2100, 'Candidate Master', 'CM', '#FF88FF', 0xAA00AA),
    Rank(2100, 2300, 'Master', 'M', '#FFCC88', 0xFF8C00),
    Rank(2300, 2400, 'International Master', 'IM', '#FFBB55', 0xF57500),
    Rank(2400, 2600, 'Grandmaster', 'GM', '#FF7777', 0xFF3030),
    Rank(2600, 3000, 'International Grandmaster', 'IGM', '#FF3333', 0xFF0000),
    Rank(3000, 10**9, 'Legendary Grandmaster', 'LGM', '#AA0000', 0xCC0000),
)
UNRATED_RANK = Rank(None, None, 'Unrated', None, None, None)


def rating2rank(rating: int | None) -> Rank:
    """Returns the rank corresponding to the given rating."""
    if rating is None:
        return UNRATED_RANK
    for rank in RATED_RANKS:
        assert rank.low is not None and rank.high is not None
        if rank.low <= rating < rank.high:
            return rank
    raise ValueError(f'Rating {rating} outside range of known ranks.')


# Data classes


class User(NamedTuple):
    """Codeforces user."""

    handle: str
    firstName: str | None
    lastName: str | None
    country: str | None
    city: str | None
    organization: str | None
    contribution: int
    rating: int | None
    maxRating: int | None
    lastOnlineTimeSeconds: int
    registrationTimeSeconds: int
    friendOfCount: int
    titlePhoto: str

    @property
    def effective_rating(self) -> int:
        """Returns the effective rating of the user."""
        return self.rating if self.rating is not None else DEFAULT_RATING

    @property
    def rank(self) -> Rank:
        """Returns the rank corresponding to the user's rating."""
        return rating2rank(self.rating)

    @property
    def url(self) -> str:
        """Returns the URL of the user's profile."""
        return f'{PROFILE_BASE_URL}{self.handle}'


def fix_urls(user: 'User') -> 'User':
    """Fix protocol-relative URLs in user's titlePhoto."""
    if user.titlePhoto.startswith('//'):
        user = user._replace(titlePhoto='https:' + user.titlePhoto)
    return user


class RatingChange(NamedTuple):
    """Codeforces rating change."""

    contestId: int
    contestName: str
    handle: str
    rank: int
    ratingUpdateTimeSeconds: int
    oldRating: int
    newRating: int


class Contest(NamedTuple):
    """Codeforces contest."""

    id: int
    name: str
    startTimeSeconds: int | None
    durationSeconds: int | None
    type: str
    phase: str
    preparedBy: str | None

    @property
    def end_time(self) -> int | None:
        """Returns the end time of the contest."""
        if self.startTimeSeconds is None or self.durationSeconds is None:
            return None
        return self.startTimeSeconds + self.durationSeconds

    @property
    def url(self) -> str:
        """Returns the URL of the contest."""
        if self.id < GYM_ID_THRESHOLD:
            return f'{CONTEST_BASE_URL}{self.id}'
        return f'{GYM_BASE_URL}{self.id}'

    @property
    def register_url(self) -> str:
        """Returns the URL to register for the contest."""
        return f'{CONTESTS_BASE_URL}{self.id}'

    def matches(self, markers: Iterable[str]) -> bool:
        """Returns whether the contest matches any of the given markers."""

        def filter_and_normalize(s: str) -> str:
            return ''.join(x for x in s.lower() if x.isalnum())

        return any(
            filter_and_normalize(marker) in filter_and_normalize(self.name)
            for marker in markers
        )


class Member(NamedTuple):
    """Codeforces party member."""

    handle: str


class Party(NamedTuple):
    """Codeforces party."""

    contestId: int | None
    members: list[Member]
    participantType: str
    teamId: int | None
    teamName: str | None
    ghost: bool
    room: int | None
    startTimeSeconds: int | None


CONTEST_PHASES = 'BEFORE CODING PENDING_SYSTEM_TEST SYSTEM_TEST FINISHED'.split()

PARTICIPANT_TYPES = (
    'CONTESTANT',
    'PRACTICE',
    'VIRTUAL',
    'MANAGER',
    'OUT_OF_COMPETITION',
)


class Problem(NamedTuple):
    """Codeforces problem."""

    contestId: int | None
    problemsetName: str | None
    index: str  # type: ignore[assignment]
    name: str
    type: str  # type: ignore[assignment]
    points: float | None
    rating: int | None
    tags: list[str]

    @property
    def contest_identifier(self) -> str:
        """Returns a string identifying the contest."""
        return f'{self.contestId}{self.index}'

    @property
    def url(self) -> str:
        """Returns the URL of the problem."""
        if self.contestId is None:
            assert self.problemsetName == 'acmsguru', (
                f'Unknown problemset {self.problemsetName}'
            )
            return f'{ACMSGURU_BASE_URL}problem/99999/{self.index}'
        base = CONTEST_BASE_URL if self.contestId < GYM_ID_THRESHOLD else GYM_BASE_URL
        return f'{base}{self.contestId}/problem/{self.index}'

    def has_metadata(self) -> bool:
        """Returns whether the problem has metadata."""
        return self.contestId is not None and self.rating is not None

    def _matching_tags_dict(self, match_tags: Iterable[str]) -> dict[str, list[str]]:
        """Returns a dict with matching tags."""
        tags = defaultdict(list)
        for match_tag in match_tags:
            for tag in self.tags:
                if match_tag in tag:
                    tags[match_tag].append(tag)
        return dict(tags)

    def matches_all_tags(self, match_tags: Iterable[str]) -> bool:
        """Returns whether the problem matches all of the given tags."""
        match_tags = set(match_tags)
        return len(self._matching_tags_dict(match_tags)) == len(match_tags)

    def matches_any_tag(self, match_tags: Iterable[str]) -> bool:
        """Returns whether the problem matches any of the given tags."""
        match_tags = set(match_tags)
        return len(self._matching_tags_dict(match_tags)) > 0

    def get_matched_tags(self, match_tags: Iterable[str]) -> list[str]:
        """Returns a list of tags that match any of the given tags."""
        return [
            tag
            for tags in self._matching_tags_dict(match_tags).values()
            for tag in tags
        ]


class ProblemStatistics(NamedTuple):
    """Codeforces problem statistics."""

    contestId: int | None
    index: str  # type: ignore[assignment]
    solvedCount: int


class Submission(NamedTuple):
    """Codeforces submission for a problem."""

    id: int
    contestId: int | None
    problem: Problem
    author: Party
    programmingLanguage: str
    verdict: str | None
    creationTimeSeconds: int
    relativeTimeSeconds: int


class RanklistRow(NamedTuple):
    """Codeforces ranklist row."""

    party: Party
    rank: int
    points: float
    penalty: int
    problemResults: list['ProblemResult']


class ProblemResult(NamedTuple):
    """Codeforces problem result."""

    points: float
    penalty: int | None
    rejectedAttemptCount: int
    type: str
    bestSubmissionTimeSeconds: int | None


def make_from_dict(namedtuple_cls: Any, dict_: dict[str, Any]) -> Any:
    """Creates a namedtuple from a subset of values in a dict."""
    field_vals = [dict_.get(field) for field in namedtuple_cls._fields]
    return namedtuple_cls._make(field_vals)


# Error classes


class CodeforcesApiError(commands.CommandError):
    """Base class for all API related errors."""

    def __init__(self, message: str | None = None):
        super().__init__(message or 'Codeforces API error')


class TrueApiError(CodeforcesApiError):
    """An error originating from a valid response of the API."""

    def __init__(self, comment: str, message: str | None = None):
        super().__init__(message)
        self.comment = comment


class ClientError(CodeforcesApiError):
    """An error caused by a request to the API failing."""

    def __init__(self) -> None:
        super().__init__('Error connecting to Codeforces API')


class HandleNotFoundError(TrueApiError):
    """An error caused by a handle not being found on Codeforces."""

    def __init__(self, comment: str, handle: str):
        super().__init__(comment, f'Handle `{handle}` not found on Codeforces')
        self.handle = handle


class HandleInvalidError(TrueApiError):
    """An error caused by a handle not being valid on Codeforces."""

    def __init__(self, comment: str, handle: str):
        super().__init__(comment, f'`{handle}` is not a valid Codeforces handle')
        self.handle = handle


class CallLimitExceededError(TrueApiError):
    """An error caused by the call limit being exceeded."""

    def __init__(self, comment: str):
        super().__init__(comment, 'Codeforces API call limit exceeded')


class ContestNotFoundError(TrueApiError):
    """An error caused by a contest not being found on Codeforces."""

    def __init__(self, comment: str, contest_id: Any):
        super().__init__(
            comment, f'Contest with ID `{contest_id}` not found on Codeforces'
        )


class RatingChangesUnavailableError(TrueApiError):
    """An error caused by rating changes being unavailable for a contest."""

    def __init__(self, comment: str, contest_id: Any):
        super().__init__(
            comment, f'Rating changes unavailable for contest with ID `{contest_id}`'
        )


# Codeforces API query methods

_session: aiohttp.ClientSession | None = None


async def initialize() -> None:
    """Initialization for the Codeforces API module."""
    global _session
    _session = aiohttp.ClientSession()


def _bool_to_str(value: bool) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    raise TypeError(f'Expected bool, got {value} of type {type(value)}')


def cf_ratelimit(f: Callable[..., Any]) -> Callable[..., Any]:
    tries = 3
    per_second = 1
    last = deque([0.0] * per_second)

    @functools.wraps(f)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        for i in itertools.count():
            now = time.time()

            # Next valid slot is 1s after the `per_second`th last request
            next_valid = max(now, 1 + last[0])
            last.append(next_valid)
            last.popleft()

            # Delay as needed
            delay = next_valid - now
            if delay > 0:
                await asyncio.sleep(delay)

            try:
                return await f(*args, **kwargs)
            except (ClientError, CallLimitExceededError) as e:
                logger.info(f'Try {i + 1}/{tries} at query failed.')
                logger.info(repr(e))
                if i < tries - 1:
                    logger.info('Retrying...')
                else:
                    logger.info('Aborting.')
                    raise e
        raise AssertionError('Unreachable')

    return wrapped


@cf_ratelimit
async def _query_api(path: str, data: Any = None) -> Any:
    url = API_BASE_URL + path
    try:
        logger.info(f'Querying CF API at {url} with {data}')
        # Explicitly state encoding (though aiohttp accepts gzip by default)
        headers = {'Accept-Encoding': 'gzip'}
        assert _session is not None, 'Session not initialized. Call initialize() first.'
        async with _session.post(url, data=data, headers=headers) as resp:
            try:
                respjson = await resp.json()
            except aiohttp.ContentTypeError:
                logger.warning(
                    f'CF API did not respond with JSON, status {resp.status}.'
                )
                raise CodeforcesApiError
            if resp.status == 200:
                return respjson['result']
            comment = f'HTTP Error {resp.status}, {respjson.get("comment")}'
    except aiohttp.ClientError as e:
        logger.error(f'Request to CF API encountered error: {e!r}')
        raise ClientError from e
    logger.warning(f'Query to CF API failed: {comment}')
    if 'limit exceeded' in comment:
        raise CallLimitExceededError(comment)
    raise TrueApiError(comment)


class contest:
    @staticmethod
    async def to_list(*, gym: bool | None = None) -> list[Contest]:
        """Returns a list of contests."""
        params = {}
        if gym is not None:
            params['gym'] = _bool_to_str(gym)
        resp = await _query_api('contest.list', params)
        return [make_from_dict(Contest, contest_dict) for contest_dict in resp]

    @staticmethod
    async def ratingChanges(*, contest_id: Any) -> list[RatingChange]:
        """Returns a list of rating changes for a contest."""
        params = {'contestId': contest_id}
        try:
            resp = await _query_api('contest.ratingChanges', params)
        except TrueApiError as e:
            if 'not found' in e.comment:
                raise ContestNotFoundError(e.comment, contest_id)
            if 'Rating changes are unavailable' in e.comment:
                raise RatingChangesUnavailableError(e.comment, contest_id)
            raise
        return [make_from_dict(RatingChange, change_dict) for change_dict in resp]

    @staticmethod
    async def standings(
        *,
        contest_id: Any,
        from_: int | None = None,
        count: int | None = None,
        handles: list[str] | None = None,
        room: Any | None = None,
        show_unofficial: bool | None = None,
    ) -> tuple[Contest, list[Problem], list[RanklistRow]]:
        params = {'contestId': contest_id}
        if from_ is not None:
            params['from'] = from_
        if count is not None:
            params['count'] = count
        if handles is not None:
            params['handles'] = ';'.join(handles)
        if room is not None:
            params['room'] = room
        if show_unofficial is not None:
            params['showUnofficial'] = _bool_to_str(show_unofficial)
        try:
            resp = await _query_api('contest.standings', params)
        except TrueApiError as e:
            if 'not found' in e.comment:
                raise ContestNotFoundError(e.comment, contest_id)
            raise
        contest_ = make_from_dict(Contest, resp['contest'])
        problems = [
            make_from_dict(Problem, problem_dict) for problem_dict in resp['problems']
        ]
        for row in resp['rows']:
            row['party']['members'] = [
                make_from_dict(Member, member) for member in row['party']['members']
            ]
            row['party'] = make_from_dict(Party, row['party'])
            row['problemResults'] = [
                make_from_dict(ProblemResult, problem_result)
                for problem_result in row['problemResults']
            ]
        ranklist = [make_from_dict(RanklistRow, row_dict) for row_dict in resp['rows']]
        return contest_, problems, ranklist


class problemset:
    @staticmethod
    async def problems(
        *, tags: list[str] | None = None, problemset_name: str | None = None
    ) -> tuple[list[Problem], list[ProblemStatistics]]:
        """Returns a list of problems."""
        params = {}
        if tags is not None:
            params['tags'] = ';'.join(tags)
        if problemset_name is not None:
            params['problemsetName'] = problemset_name
        resp = await _query_api('problemset.problems', params)
        problems = [
            make_from_dict(Problem, problem_dict) for problem_dict in resp['problems']
        ]
        problemstats = [
            make_from_dict(ProblemStatistics, problemstat_dict)
            for problemstat_dict in resp['problemStatistics']
        ]
        return problems, problemstats


def user_info_chunkify(handles: Iterable[str]) -> Iterator[list[str]]:
    """Yields chunks of handles that can be queried with user.info."""
    # Querying user.info using POST requests is limited to 10000 handles or 2**16
    # bytes, so requests might need to be split into chunks
    SIZE_LIMIT = 2**16
    HANDLE_LIMIT = 10000
    chunk: list[str] = []
    size = 0
    for handle in handles:
        if size + len(handle) > SIZE_LIMIT or len(chunk) == HANDLE_LIMIT:
            yield chunk
            chunk = []
            size = 0
        chunk.append(handle)
        size += len(handle) + 1
    if chunk:
        yield chunk


class user:
    @staticmethod
    async def info(*, handles: Sequence[str]) -> list[User]:
        """Returns a list of user info."""
        chunks = list(user_info_chunkify(handles))
        if len(chunks) > 1:
            logger.warning(
                f'cf.info request with {len(handles)} handles,'
                f' will be chunkified into {len(chunks)} requests.'
            )

        result = []
        for chunk in chunks:
            params = {'handles': ';'.join(chunk)}
            try:
                resp = await _query_api('user.info', params)
            except TrueApiError as e:
                if 'not found' in e.comment:
                    # Comment format is "handles: User with handle ***** not found"
                    handle = e.comment.partition('not found')[0].split()[-1]
                    raise HandleNotFoundError(e.comment, handle)
                raise
            result += [make_from_dict(User, user_dict) for user_dict in resp]
        return [fix_urls(user) for user in result]

    @staticmethod
    async def rating(*, handle: str) -> list[RatingChange]:
        """Returns a list of rating changes for a user."""
        params = {'handle': handle}
        try:
            resp = await _query_api('user.rating', params)
        except TrueApiError as e:
            if 'not found' in e.comment:
                raise HandleNotFoundError(e.comment, handle)
            if 'should contain' in e.comment:
                raise HandleInvalidError(e.comment, handle)
            raise
        return [
            make_from_dict(RatingChange, ratingchange_dict)
            for ratingchange_dict in resp
        ]

    @staticmethod
    async def ratedList(*, activeOnly: bool | None = None) -> list[User]:
        """Returns a list of rated users."""
        params = {}
        if activeOnly is not None:
            params['activeOnly'] = _bool_to_str(activeOnly)
        resp = await _query_api('user.ratedList', params)
        return [make_from_dict(User, user_dict) for user_dict in resp]

    @staticmethod
    async def status(
        *, handle: str, from_: int | None = None, count: int | None = None
    ) -> list[Submission]:
        """Returns a list of submissions for a user."""
        params: dict[str, Any] = {'handle': handle}
        if from_ is not None:
            params['from'] = from_
        if count is not None:
            params['count'] = count
        try:
            resp = await _query_api('user.status', params)
        except TrueApiError as e:
            if 'not found' in e.comment:
                raise HandleNotFoundError(e.comment, handle)
            if 'should contain' in e.comment:
                raise HandleInvalidError(e.comment, handle)
            raise
        for submission in resp:
            submission['problem'] = make_from_dict(Problem, submission['problem'])
            submission['author']['members'] = [
                make_from_dict(Member, member)
                for member in submission['author']['members']
            ]
            submission['author'] = make_from_dict(Party, submission['author'])
        return [make_from_dict(Submission, submission_dict) for submission_dict in resp]


async def _resolve_redirect(handle: str) -> str | None:
    url = PROFILE_BASE_URL + handle
    assert _session is not None, 'Session not initialized. Call initialize() first.'
    async with _session.head(url) as r:
        if r.status == 200:
            return handle
        if r.status == 302:
            redirected = r.headers.get('Location')
            if redirected is None or '/profile/' not in redirected:
                # Ended up not on profile page, probably invalid handle
                return None
            return str(redirected.split('/profile/')[-1])
        raise CodeforcesApiError(f'Something went wrong trying to redirect {url}')


async def _resolve_handle_to_new_user(
    handle: str,
) -> User | None:
    new_handle = await _resolve_redirect(handle)
    if new_handle is None:
        return None
    (cf_user,) = await user.info(handles=[new_handle])
    return cf_user


async def _resolve_handles(handles: Iterable[str]) -> dict[str, User]:
    chunks = user_info_chunkify(handles)

    resolved_handles: dict[str, User] = {}
    for handle_chunk in chunks:
        while handle_chunk:
            try:
                cf_users = await user.info(handles=handle_chunk)
                # No failure, all handles resolve to users,
                for handle, cf_user in zip(handle_chunk, cf_users, strict=False):
                    if cf_user is not None:
                        resolved_handles[handle] = cf_user
                break
            except HandleNotFoundError as e:
                # Handle not found, drop it.
                logger.warning(f'Handle {e.handle} not found, dropping it.')
                handle_chunk.remove(e.handle)
    return resolved_handles


async def resolve_redirects(
    handles: Iterable[str], skip_filter: bool = False
) -> dict[str, User]:
    """Returns a mapping of handles to their resolved CF users."""
    resolved_handles = await _resolve_handles(handles)
    if skip_filter:
        return resolved_handles

    return {
        handle: cf_user
        for handle, cf_user in resolved_handles.items()
        if cf_user is not None and handle != cf_user.handle
    }
