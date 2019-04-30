import logging
from collections import namedtuple

import aiohttp

API_BASE_URL = 'https://codeforces.com/api/'
CONTEST_BASE_URL = 'https://codeforces.com/contest/'
CONTESTS_BASE_URL = 'https://codeforces.com/contests/'
PROFILE_BASE_URL = 'https://codeforces.com/profile/'

logger = logging.getLogger(__name__)
session = aiohttp.ClientSession()

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

class User(namedtuple('User', 'handle rating titlePhoto')):
    __slots__ = ()

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
        return f'{CONTEST_BASE_URL}{self.id}'

    @property
    def register_url(self):
        return f'{CONTESTS_BASE_URL}{self.id}'


Party = namedtuple('Party', 'contestId members participantType')


class Problem(namedtuple('Problem', 'contestId index name type rating tags')):
    __slots__ = ()

    @property
    def contest_identifier(self):
        return f'{self.contestId}{self.index}'

    @property
    def url(self):
        return f'{CONTEST_BASE_URL}{self.contestId}/problem/{self.index}'

    def has_metadata(self):
        return self.contestId is not None and self.rating is not None

    def tag_matches(self, query_tags):
        """If every query tag is a substring of any problem tag, returns a list of matched tags."""
        matches = set()
        for query_tag in query_tags:
            curmatch = [tag for tag in self.tags if query_tag in tag]
            if not curmatch:
                return None
            matches.update(curmatch)
        return list(matches)


ProblemStatistics = namedtuple('ProblemStatistics', 'contestId index solvedCount')

Submission = namedtuple('Submissions', 'id contestId problem author programmingLanguage verdict creationTimeSeconds')

RanklistRow = namedtuple('RanklistRow', 'party rank')


def make_from_dict(namedtuple_cls, dict_):
    field_vals = [dict_.get(field) for field in namedtuple_cls._fields]
    return namedtuple_cls._make(field_vals)


# Error classes

class CodeforcesApiError(Exception):
    pass


class ClientError(CodeforcesApiError):
    pass


class NotFoundError(CodeforcesApiError):
    pass


class InvalidParamError(CodeforcesApiError):
    pass


class CallLimitExceededError(CodeforcesApiError):
    pass


class RatingChangesUnavailableError(CodeforcesApiError):
    pass


# Codeforces API query methods

async def _query_api(path, params=None):
    url = API_BASE_URL + path
    try:
        logger.info(f'Querying CF API at {url} with {params}')
        headers = {'Accept-Encoding': 'gzip'}  # Explicitly state encoding (though aiohttp accepts gzip by default)
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 200:
                resp = await resp.json()
                return resp['result']
            comment = f'HTTP Error {resp.status}'
            try:
                respjson = await resp.json()
                comment += f', {respjson.get("comment")}'
            except aiohttp.ContentTypeError:
                pass
    except aiohttp.ClientError as e:
        logger.error(f'Request to CF API encountered error: {e}')
        raise ClientError(e) from e
    logger.warning(f'Query to CF API failed: {comment}')
    if 'not found' in comment:
        raise NotFoundError(comment)
    if 'should contain' in comment:
        raise InvalidParamError(comment)
    if 'limit exceeded' in comment:
        raise CallLimitExceededError(comment)
    if 'Rating changes are unavailable' in comment:
        raise RatingChangesUnavailableError(comment)
    raise CodeforcesApiError(comment)


class contest:
    @staticmethod
    async def list(*, gym=False):
        params = {}
        if gym:
            params['gym'] = 'true'
        resp = await _query_api('contest.list', params)
        return [make_from_dict(Contest, contest_dict) for contest_dict in resp]

    @staticmethod
    async def ratingChanges(*, contest_id):
        params = {'contestId': contest_id}
        resp = await _query_api('contest.ratingChanges', params)
        return [make_from_dict(RatingChange, change_dict) for change_dict in resp]

    @staticmethod
    async def standings(*, contest_id, from_=None, count=None, handles=None, room=None, show_unofficial=None):
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
            params['showUnofficial'] = show_unofficial
        resp = await _query_api('contest.standings', params)
        contest_ = make_from_dict(Contest, resp['contest'])
        problems = [make_from_dict(Problem, problem_dict) for problem_dict in resp['problems']]
        for row in resp['rows']:
            row['party'] = make_from_dict(Party, row['party'])
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


class user:
    @staticmethod
    async def info(*, handles):
        params = {'handles': ';'.join(handles)}
        resp = await _query_api('user.info', params)
        return [make_from_dict(User, user_dict) for user_dict in resp]

    @staticmethod
    async def rating(*, handle):
        params = {'handle': handle}
        resp = await _query_api('user.rating', params)
        return [make_from_dict(RatingChange, ratingchange_dict) for ratingchange_dict in resp]

    @staticmethod
    async def ratedList(*, activeOnly = True):
        params = {}
        if activeOnly:
            params['activeOnly'] = 'true'
        resp = await _query_api('user.ratedList', params=params)
        return [make_from_dict(User, user_dict) for user_dict in resp]

    @staticmethod
    async def status(*, handle, from_=None, count=None):
        params = {'handle': handle}
        if from_ is not None:
            params['from'] = from_
        if count is not None:
            params['count'] = count
        resp = await _query_api('user.status', params)
        for submission in resp:
            submission['problem'] = make_from_dict(Problem, submission['problem'])
            submission['author'] = make_from_dict(Party, submission['author'])
        return [make_from_dict(Submission, submission_dict) for submission_dict in resp]
