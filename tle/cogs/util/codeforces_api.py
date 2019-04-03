import logging

import aiohttp

API_BASE_URL = 'http://codeforces.com/api/'
CONTEST_BASE_URL = 'http://codeforces.com/contest/'

session = aiohttp.ClientSession()


class CodeforcesApiError(Exception):
    pass


class NotFoundError(CodeforcesApiError):
    pass


class CallLimitExceededError(CodeforcesApiError):
    pass


async def query_api(path, params=None):
    url = API_BASE_URL + path
    try:
        logging.info(f'Querying CF API at {url} with {params}')
        async with session.get(url, params=params) as resp:
            resp = await resp.json()
    except aiohttp.ClientConnectionError as e:
        logging.error(f'Request to CF API encountered error: {e}')
        raise
    if resp['status'] == 'OK':
        return resp['result']
    comment = resp['comment']
    logging.info(f'Query to CF API failed with comment {comment}')
    if 'not found' in comment:
        raise NotFoundError(comment)
    if 'limit exceeded' in comment:
        raise CallLimitExceededError(comment)
    raise CodeforcesApiError(comment)


class contest:
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
        return await query_api('contest.standings', params)

    @staticmethod
    async def list(*, gym=False):
        if gym: return await query_api('contest.list', {'gym': 'true'})
        return await query_api('contest.list', {'gym' : 'false'})

class problemset:
    @staticmethod
    async def problems(*, tags=None, problemset_name=None):
        params = {}
        if tags is not None:
            params['tags'] = ';'.join(tags)
        if problemset_name is not None:
            params['problemsetName'] = problemset_name
        return await query_api('problemset.problems', params)


class user:
    @staticmethod
    async def info(*, handles):
        params = {'handles': ';'.join(handles)}
        return await query_api('user.info', params)

    @staticmethod
    async def rating(*, handle):
        params = {'handle': handle}
        return await query_api('user.rating', params)

    @staticmethod
    async def status(*, handle, from_=None, count=None):
        params = {'handle': handle}
        if from_ is not None:
            params['from'] = from_
        if count is not None:
            params['count'] = count
        return await query_api('user.status', params)
