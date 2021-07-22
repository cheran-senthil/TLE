import logging
import os
import requests

from discord.ext import commands

import functools
import asyncio
from urllib.parse import urlencode

logger = logging.getLogger(__name__)
URL_BASE = 'https://clist.by/api/v2/'
_SUPPORTED_CLIST_RESOURCES = ('codechef.com', 'atcoder.jp','codingcompetitions.withgoogle.com')
_CLIST_RESOURCE_SHORT_FORMS = {'cc':'codechef.com','codechef':'codechef.com', 'cf':'codeforces.com',
 'codeforces':'codeforces.com','ac':'atcoder.jp', 'atcoder':'atcoder.jp', 
 'google':'codingcompetitions.withgoogle.com'}

class ClistNotConfiguredError(commands.CommandError):
    """An error caused when clist credentials are not set in environment variables"""
    def __init__(self, message=None):
        super().__init__(message or 'Clist API not configured')    

class ClistApiError(commands.CommandError):
    """Base class for all API related errors."""

    def __init__(self, message=None):
        super().__init__(message or 'Clist API error')


class ClientError(ClistApiError):
    """An error caused by a request to the API failing."""

    def __init__(self):
        super().__init__('Error connecting to Clist API')

class TrueApiError(ClistApiError):
    """An error originating from a valid response of the API."""
    def __init__(self, comment=None, message=None):
        super().__init__(message)
        self.comment = comment

class HandleNotFoundError(TrueApiError):
    def __init__(self, handle, resource=None):
        super().__init__(message=f'Handle `{handle}` not found{" on `"+str(resource)+"`" if resource!=None else "."}')
        self.handle = handle

class CallLimitExceededError(TrueApiError):
    def __init__(self, comment=None):
        super().__init__(message='Clist API call limit exceeded')
        self.comment = comment

def ratelimit(f):
    tries = 3
    @functools.wraps(f)
    async def wrapped(*args, **kwargs):
        for i in range(tries):
            delay = 10
            await asyncio.sleep(delay*i)
            try:
                return await f(*args, **kwargs)
            except (ClientError, CallLimitExceededError, ClistApiError) as e:
                logger.info(f'Try {i+1}/{tries} at query failed.')
                if i < tries - 1:
                    logger.info(f'Retrying...')
                else:
                    logger.info(f'Aborting.')
                    raise e
    return wrapped


@ratelimit
async def _query_clist_api(path, data):
    url = URL_BASE + path
    clist_token = os.getenv('CLIST_API_TOKEN')
    if not clist_token:
        raise ClistNotConfiguredError
    if data is None:
        url += '?'+clist_token
    else:
        url += '?'+ str(urlencode(data))
        url+='&'+clist_token
    try:
        resp = requests.get(url)
        if resp.status_code != 200:
            if resp.status_code == 429:
                raise CallLimitExceededError
            else:
                raise ClistApiError
        return resp.json()
    except Exception as e:
        logger.error(f'Request to Clist API encountered error: {e!r}')
        raise ClientError from e

async def account(handle, resource):
    params = {'total_count': True, 'handle':handle} 
    if resource!=None:
        params['resource'] = resource
    resp = await _query_clist_api('account', params)
    if resp==None or 'objects' not in resp:
        raise ClientError
    else:
        resp = resp['objects']
    if len(resp)==0:
        raise HandleNotFoundError(handle=handle, resource=resource) 
    return resp