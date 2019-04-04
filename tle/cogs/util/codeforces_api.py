import logging
from collections import namedtuple

import aiohttp

API_BASE_URL = 'http://codeforces.com/api/'
CONTEST_BASE_URL = 'http://codeforces.com/contest/'

session = aiohttp.ClientSession()


class RankHelper:
    INF = 10 ** 9
    rank_info = [
        (-INF, 1200, '#CCCCCC', 'Newbie'),
        (1200, 1400, '#77FF77', 'Pupil'),
        (1400, 1600, '#77DDBB', 'Specialist'),
        (1600, 1900, '#AAAAFF', 'Expert'),
        (1900, 2100, '#FF88FF', 'Candidate Master'),
        (2100, 2300, '#FFCC88', 'Master'),
        (2300, 2400, '#FFBB55', 'International Master'),
        (2400, 2600, '#FF7777', 'Grandmaster'),
        (2600, 3000, '#FF3333', 'International Grandmaster'),
        (3000, INF, '#AA0000', 'Legendary Grandmaster')
    ]

    @classmethod
    def rating2rank(cls, rating):
        if rating is None:
            return 'Unrated'
        for low, high, _, title in cls.rank_info:
            if low <= rating < high:
                return title

    @classmethod
    def get_ranks(cls):
        return [rank for _, _, _, rank in cls.rank_info]


# Data classes

class User(namedtuple('User', 'handle rating titlePhoto')):
    __slots__ = ()

    @property
    def rank(self):
        return RankHelper.rating2rank(self.rating)


RatingChange = namedtuple('RatingChange',
                          'contestId contestName handle rank ratingUpdateTimeSeconds oldRating newRating')

Contest = namedtuple('Contest', 'id name')

Party = namedtuple('Party', 'contestId members participantType')


class Problem(namedtuple('Problem', 'contestId index name type rating tags')):
    __slots__ = ()

    @property
    def contest_identifier(self):
        return f'{self.contestId}{self.index}'

    def has_metadata(self):
        return self.contestId is not None and self.rating is not None

    def has_any_tag_from(self, tags):
        return any(tag in self.tags for tag in tags)


ProblemStatistics = namedtuple('ProblemStatistics', 'contestId index solvedCount')

Submission = namedtuple('Submissions', 'id contestId problem author programmingLanguage verdict')

RanklistRow = namedtuple('RanklistRow', 'party rank')


def make_from_dict(namedtuple_cls, dict_):
    field_vals = [dict_.get(field) for field in namedtuple_cls._fields]
    return namedtuple_cls(*field_vals)


# Error classes

class CodeforcesApiError(Exception):
    pass


class NotFoundError(CodeforcesApiError):
    pass


class InvalidParamError(CodeforcesApiError):
    pass


class CallLimitExceededError(CodeforcesApiError):
    pass


# Codeforces API query methods

async def query_api(path, params=None):
    url = API_BASE_URL + path
    try:
        logging.info(f'Querying CF API at {url} with {params}')
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                resp = await resp.json()
                return resp['result']
            comment = f'HTTP Error {resp.status}'
            try:
                respjson = await resp.json()
                comment += f', {respjson.get("comment")}'
            except aiohttp.ContentTypeError:
                pass
            logging.warning(f'Query to CF API failed: {comment}')
            if 'not found' in comment:
                raise NotFoundError(comment)
            if 'should contain' in comment:
                raise InvalidParamError(comment)
            if 'limit exceeded' in comment:
                raise CallLimitExceededError(comment)
            raise CodeforcesApiError(comment)
    except aiohttp.ClientConnectionError as e:
        logging.error(f'Request to CF API encountered error: {e}')
        raise


class contest:
    @staticmethod
    async def list(*, gym=False):
        params = {}
        if gym:
            params['gym'] = True
        resp = await query_api('contest.list', params)
        return [make_from_dict(Contest, contest_dict) for contest_dict in resp]

    @staticmethod
    async def standings(*, contestid, from_=None, count=None, handles=None, room=None, show_unofficial=None):
        params = {'contestId': contestid}
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
        resp = await query_api('contest.standings', params)
        contest_ = make_from_dict(Contest, resp['contest'])
        problems = [make_from_dict(Problem, problem_dict) for problem_dict in resp['problems']]
        ranklist = [make_from_dict(RanklistRow, row_dict) for row_dict in resp['problems']]
        return contest_, problems, ranklist


class problemset:
    @staticmethod
    async def problems(*, tags=None, problemset_name=None):
        params = {}
        if tags is not None:
            params['tags'] = ';'.join(tags)
        if problemset_name is not None:
            params['problemsetName'] = problemset_name
        resp = await query_api('problemset.problems', params)
        problems = [make_from_dict(Problem, problem_dict) for problem_dict in resp['problems']]
        problemstats = [make_from_dict(ProblemStatistics, problemstat_dict) for problemstat_dict in
                        resp['problemStatistics']]
        return problems, problemstats


class user:
    @staticmethod
    async def info(*, handles):
        params = {'handles': ';'.join(handles)}
        resp = await query_api('user.info', params)
        return [make_from_dict(User, user_dict) for user_dict in resp]

    @staticmethod
    async def rating(*, handle):
        params = {'handle': handle}
        resp = await query_api('user.rating', params)
        return [make_from_dict(RatingChange, ratingchange_dict) for ratingchange_dict in resp]

    @staticmethod
    async def status(*, handle, from_=None, count=None):
        params = {'handle': handle}
        if from_ is not None:
            params['from'] = from_
        if count is not None:
            params['count'] = count
        resp = await query_api('user.status', params)
        for submission in resp:
            submission['problem'] = make_from_dict(Problem, submission['problem'])
        return [make_from_dict(Submission, submission_dict) for submission_dict in resp]
