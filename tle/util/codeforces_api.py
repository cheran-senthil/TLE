import asyncio
import logging
import time
import functools
from collections import namedtuple, deque, defaultdict

import aiohttp

from discord.ext import commands
from tle.util import codeforces_common as cf_common

API_BASE_URL = 'https://codeforces.com/api/'
CONTEST_BASE_URL = 'https://codeforces.com/contest/'
CONTESTS_BASE_URL = 'https://codeforces.com/contests/'
GYM_BASE_URL = 'https://codeforces.com/gym/'
PROFILE_BASE_URL = 'https://codeforces.com/profile/'
ACMSGURU_BASE_URL = 'https://codeforces.com/problemsets/acmsguru/'
GYM_ID_THRESHOLD = 100000
DEFAULT_RATING = 800

logger = logging.getLogger(__name__)

Rank = namedtuple('Rank', 'low high title title_abbr color_graph color_embed')

RATED_RANKS = (
    Rank(-10 ** 9, 1200, 'Newbie', 'N', '#CCCCCC', 0x808080),
    Rank(1200, 1400, 'Pupil', 'P', '#77FF77', 0x008000),
    Rank(1400, 1600, 'Specialist', 'S', '#77DDBB', 0x03a89e),
    Rank(1600, 1900, 'Expert', 'E', '#AAAAFF', 0x0000ff),
    Rank(1900, 2100, 'Candidate Master', 'CM', '#FF88FF', 0xaa00aa),
    Rank(2100, 2300, 'Master', 'M', '#FFCC88', 0xff8c00),
    Rank(2300, 2400, 'International Master', 'IM', '#FFBB55', 0xf57500),
    Rank(2400, 2600, 'Grandmaster', 'GM', '#FF7777', 0xff3030),
    Rank(2600, 3000, 'International Grandmaster', 'IGM', '#FF3333', 0xff0000),
    Rank(3000, 10 ** 9, 'Legendary Grandmaster', 'LGM', '#AA0000', 0xcc0000)
)
UNRATED_RANK = Rank(None, None, 'Unrated', None, None, None)


def rating2rank(rating):
    if rating is None:
        return UNRATED_RANK
    for rank in RATED_RANKS:
        if rank.low <= rating < rank.high:
            return rank


# Data classes

class User(namedtuple('User', 'handle firstName lastName country city organization contribution '
                              'rating maxRating lastOnlineTimeSeconds registrationTimeSeconds '
                              'friendOfCount titlePhoto')):
    __slots__ = ()

    @property
    def effective_rating(self):
        return self.rating if self.rating is not None else DEFAULT_RATING

    @property
    def rank(self):
        return rating2rank(self.rating)

    @property
    def url(self):
        return f'{PROFILE_BASE_URL}{self.handle}'


RatingChange = namedtuple('RatingChange',
                          'contestId contestName handle rank ratingUpdateTimeSeconds oldRating newRating')


class Contest(namedtuple('Contest', 'id name startTimeSeconds durationSeconds type phase preparedBy')):
    __slots__ = ()
    PHASES = 'BEFORE CODING PENDING_SYSTEM_TEST SYSTEM_TEST FINISHED'.split()

    @property
    def end_time(self):
        return self.startTimeSeconds + self.durationSeconds

    @property
    def url(self):
        return f'{CONTEST_BASE_URL if self.id < GYM_ID_THRESHOLD else GYM_BASE_URL}{self.id}'

    @property
    def register_url(self):
        return f'{CONTESTS_BASE_URL}{self.id}'

    def matches(self, markers):
        def strfilt(s):
            return ''.join(x for x in s.lower() if x.isalnum())
        return any(strfilt(marker) in strfilt(self.name) for marker in markers)

class Party(namedtuple('Party', ('contestId members participantType teamId teamName ghost room '
                                 'startTimeSeconds'))):
    __slots__ = ()
    PARTICIPANT_TYPES = ('CONTESTANT', 'PRACTICE', 'VIRTUAL', 'MANAGER', 'OUT_OF_COMPETITION')


Member = namedtuple('Member', 'handle')


class Problem(namedtuple('Problem', 'contestId problemsetName index name type points rating tags')):
    __slots__ = ()

    @property
    def contest_identifier(self):
        return f'{self.contestId}{self.index}'

    @property
    def url(self):
        if self.contestId is None:
            assert self.problemsetName == 'acmsguru', f'Unknown problemset {self.problemsetName}'
            return f'{ACMSGURU_BASE_URL}problem/99999/{self.index}'
        base = CONTEST_BASE_URL if self.contestId < GYM_ID_THRESHOLD else GYM_BASE_URL
        return f'{base}{self.contestId}/problem/{self.index}'

    def has_metadata(self):
        return self.contestId is not None and self.rating is not None

    def _matching_tags_dict(self, match_tags):
        """Returns a dict with matching tags."""
        tags = defaultdict(list)
        for match_tag in match_tags:
            for tag in self.tags:
                if match_tag in tag:
                    tags[match_tag].append(tag)
        return dict(tags)

    def matches_all_tags(self, match_tags):
        match_tags = set(match_tags)
        return len(self._matching_tags_dict(match_tags)) == len(match_tags)

    def matches_any_tag(self, match_tags):
        match_tags = set(match_tags)
        return len(self._matching_tags_dict(match_tags)) > 0

    def get_matched_tags(self, match_tags):
        return [
            tag for tags in self._matching_tags_dict(match_tags).values()
            for tag in tags
        ]

ProblemStatistics = namedtuple('ProblemStatistics', 'contestId index solvedCount')

Submission = namedtuple('Submissions',
                        'id contestId problem author programmingLanguage verdict creationTimeSeconds relativeTimeSeconds')

RanklistRow = namedtuple('RanklistRow', 'party rank points penalty problemResults')

ProblemResult = namedtuple('ProblemResult',
                           'points penalty rejectedAttemptCount type bestSubmissionTimeSeconds')


def make_from_dict(namedtuple_cls, dict_):
    field_vals = [dict_.get(field) for field in namedtuple_cls._fields]
    return namedtuple_cls._make(field_vals)


# Error classes

class CodeforcesApiError(commands.CommandError):
    """Base class for all API related errors."""
    def __init__(self, message=None):
        super().__init__(message or 'Codeforces API error. There is nothing you or the Admins of the Discord server can do to fix it. We need to wait until Mike does his job.')


class TrueApiError(CodeforcesApiError):
    """An error originating from a valid response of the API."""
    def __init__(self, comment, message=None):
        super().__init__(message)
        self.comment = comment


class ClientError(CodeforcesApiError):
    """An error caused by a request to the API failing."""
    def __init__(self):
        super().__init__('Error connecting to Codeforces API')


class HandleNotFoundError(TrueApiError):
    def __init__(self, comment, handle):
        super().__init__(comment, f'Handle `{handle}` not found on Codeforces')
        self.handle = handle


class HandleInvalidError(TrueApiError):
    def __init__(self, comment, handle):
        super().__init__(comment, f'`{handle}` is not a valid Codeforces handle')
        self.handle = handle


class CallLimitExceededError(TrueApiError):
    def __init__(self, comment):
        super().__init__(comment, 'Codeforces API call limit exceeded')


class ContestNotFoundError(TrueApiError):
    def __init__(self, comment, contest_id):
        super().__init__(comment, f'Contest with ID `{contest_id}` not found on Codeforces')


class RatingChangesUnavailableError(TrueApiError):
    def __init__(self, comment, contest_id):
        super().__init__(comment, f'Rating changes unavailable for contest with ID `{contest_id}`')


# Codeforces API query methods

_session = None


async def initialize():
    global _session
    _session = aiohttp.ClientSession()


def _bool_to_str(value):
    if type(value) is bool:
        return 'true' if value else 'false'
    raise TypeError(f'Expected bool, got {value} of type {type(value)}')


def cf_ratelimit(f):
    tries = 3
    per_second = 1
    last = deque([0]*per_second)

    @functools.wraps(f)
    async def wrapped(*args, **kwargs):
        for i in range(tries):
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
                logger.info(f'Try {i+1}/{tries} at query failed.')
                logger.info(repr(e))
                if i < tries - 1:
                    logger.info(f'Retrying...')
                else:
                    logger.info(f'Aborting.')
                    raise e
    return wrapped


@cf_ratelimit
async def _query_api(path, data=None):
    url = API_BASE_URL + path
    try:
        logger.info(f'Querying CF API at {url} with {data}')
        # Explicitly state encoding (though aiohttp accepts gzip by default)
        headers = {'Accept-Encoding': 'gzip'}
        async with _session.post(url, data=data, headers=headers) as resp:
            try:
                respjson = await resp.json()
            except aiohttp.ContentTypeError:
                logger.warning(f'CF API did not respond with JSON, status {resp.status}.')
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
    async def list(*, gym=None):
        params = {}
        if gym is not None:
            params['gym'] = _bool_to_str(gym)
        resp = await _query_api('contest.list', params)
        return [make_from_dict(Contest, contest_dict) for contest_dict in resp]

    @staticmethod
    async def ratingChanges(*, contest_id):
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
    async def standings(*, contest_id, from_=None, count=None, handles=None, room=None,
                        show_unofficial=None):
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
        problems = [make_from_dict(Problem, problem_dict) for problem_dict in resp['problems']]
        for row in resp['rows']:
            row['party']['members'] = [make_from_dict(Member, member)
                                       for member in row['party']['members']]
            row['party'] = make_from_dict(Party, row['party'])
            row['problemResults'] = [make_from_dict(ProblemResult, problem_result)
                                     for problem_result in row['problemResults']]
        ranklist = [make_from_dict(RanklistRow, row_dict) for row_dict in resp['rows']]
        return contest_, problems, ranklist


class problemset:
    @staticmethod
    async def problems(*, tags=None, problemset_name=None):
        params = {}
        if tags is not None:
            params['tags'] = ';'.join(tags)
        if problemset_name is not None:
            params['problemsetName'] = problemset_name
        resp = await _query_api('problemset.problems', params)
        problems = [make_from_dict(Problem, problem_dict) for problem_dict in resp['problems']]
        problemstats = [make_from_dict(ProblemStatistics, problemstat_dict) for problemstat_dict in
                        resp['problemStatistics']]
        return problems, problemstats

def user_info_chunkify(handles):
    """
    Querying user.info using POST requests is limited to 10000 handles or 2**16
    bytes, so requests might need to be split into chunks
    """
    SIZE_LIMIT = 2**16
    HANDLE_LIMIT = 10000
    chunk = []
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
    async def info(*, handles):
        chunks = list(user_info_chunkify(handles))
        if len(chunks) > 1:
            logger.warning(f'cf.info request with {len(handles)} handles,'
            f'will be chunkified into {len(chunks)} requests.')

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
        return [cf_common.fix_urls(user) for user in result]

    @staticmethod
    def correct_rating_changes(*, resp):
        adaptO = [1400, 900, 550, 300, 150, 50]
        adaptN = [900, 550, 300, 150, 50, 0]
        for r in resp:
            if (len(r) > 0):
                if (r[0].newRating <= 1200):
                    for ind in range(0,(min(6, len(r)))):
                        r[ind] = RatingChange(r[ind].contestId, r[ind].contestName, r[ind].handle, r[ind].rank, r[ind].ratingUpdateTimeSeconds, r[ind].oldRating+adaptO[ind], r[ind].newRating+adaptN[ind])
                else:
                    r[0] = RatingChange(r[0].contestId, r[0].contestName, r[0].handle, r[0].rank, r[0].ratingUpdateTimeSeconds, r[0].oldRating+1500, r[0].newRating)
        for r in resp:
            oldPerf = 0
            for ind in range(0,len(r)):
                r[ind] = RatingChange(r[ind].contestId, r[ind].contestName, r[ind].handle, r[ind].rank, r[ind].ratingUpdateTimeSeconds, oldPerf, r[ind].oldRating + 4*(r[ind].newRating-r[ind].oldRating))
                oldPerf = r[ind].oldRating + 4*(r[ind].newRating-r[ind].oldRating)
        return resp


    @staticmethod
    async def rating(*, handle):
        params = {'handle': handle}
        try:
            resp = await _query_api('user.rating', params)
        except TrueApiError as e:
            if 'not found' in e.comment:
                raise HandleNotFoundError(e.comment, handle)
            if 'should contain' in e.comment:
                raise HandleInvalidError(e.comment, handle)
            raise
        return [make_from_dict(RatingChange, ratingchange_dict) for ratingchange_dict in resp]

    @staticmethod
    async def ratedList(*, activeOnly=None):
        params = {}
        if activeOnly is not None:
            params['activeOnly'] = _bool_to_str(activeOnly)
        resp = await _query_api('user.ratedList', params)
        return [make_from_dict(User, user_dict) for user_dict in resp]

    @staticmethod
    async def status(*, handle, from_=None, count=None):
        params = {'handle': handle}
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
            submission['author']['members'] = [make_from_dict(Member, member)
                                               for member in submission['author']['members']]
            submission['author'] = make_from_dict(Party, submission['author'])
        return [make_from_dict(Submission, submission_dict) for submission_dict in resp]


async def _needs_fixing(handles):
    to_fix = []
    chunks = user_info_chunkify(handles)
    for handle_chunk in chunks:
        while handle_chunk:
            try:
                cf_users = await user.info(handles=handle_chunk)

                # Users could still have changed capitalization
                for handle, cf_user in zip(handle_chunk, cf_users):
                    assert handle.lower() == cf_user.handle.lower()
                    if handle != cf_user.handle:
                        to_fix.append(handle)
                break
            except HandleNotFoundError as e:
                to_fix.append(e.handle)
                handle_chunk.remove(e.handle)
            time.sleep(1)
    return to_fix


async def _resolve_redirect(handle):
    url = PROFILE_BASE_URL + handle
    async with _session.head(url) as r:
        if r.status == 200:
            return handle
        if r.status == 301 or r.status == 302:
            redirected = r.headers.get('Location')
            if '/profile/' not in redirected:
                # Ended up not on profile page, probably invalid handle
                return None
            return redirected.split('/profile/')[-1]
        raise CodeforcesApiError(
            f'Something went wrong trying to redirect {url}')


async def _resolve_handle_mapping(handles_to_fix):
    redirections = {}
    failed = []
    for handle in handles_to_fix:
        new_handle = await _resolve_redirect(handle)
        if not new_handle:
            redirections[handle] = None
        else:
            cf_user, = await user.info(handles=[new_handle])
            redirections[handle] = cf_user
        time.sleep(1)
    return redirections


async def resolve_redirects(handles):
    handles_to_fix = await _needs_fixing(handles)
    handle_mapping = await _resolve_handle_mapping(handles_to_fix)
    return handle_mapping
