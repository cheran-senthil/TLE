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

async def fetch_user_info(resource, account_ids=None, handles=None):
    params = {'resource':resource, 'limit':1000}
    if account_ids!=None:
        ids = ""
        for i in range(len(account_ids)):
            ids += str(account_ids[i])
            if i!=(len(account_ids)-1):
                ids += ','
        params['id__in']=ids
    if handles!=None:
        regex = '$|^'.join(handles)
        params['handle__regex'] = '^'+regex+'$'
    resp = await _query_clist_api('account', params)
    if resp==None or 'objects' not in resp:
        raise ClientError
    else:
        resp = resp['objects']
    return resp

async def statistics(account_id=None, contest_id=None, order_by=None, account_ids=None, resource=None):
    params = {'limit':1000}
    if account_id!=None: params['account_id'] = account_id
    if contest_id!=None: params['contest_id'] = contest_id
    if order_by!=None: params['order_by'] = order_by
    if account_ids!=None:
        ids = ""
        for i in range(len(account_ids)):
            ids += str(account_ids[i])
            if i!=(len(account_ids)-1):
                ids += ','
        params['account_id__in']=ids
    if resource!=None: params['resource'] = resource
    results = []
    offset = 0
    while True:
        params['offset'] = offset
        resp = await _query_clist_api('statistics', params)
        if resp==None or 'objects' not in resp:
            if offset==0:
                raise ClientError
            else:
                break
        else:
            objects = resp['objects']
            results += objects
            if(len(objects)<1000):
                break
        offset+=1000
    return results

async def contest(contest_id):
    resp = await _query_clist_api('contest/'+str(contest_id), None)
    return resp

async def search_contest(regex=None, date_limits=None, resource=None):
    params = {'limit':1000}
    if resource!=None:
        params['resource'] = resource
    if regex!=None:
        params['event__regex'] = regex
    if date_limits!=None:
        params['start__gte'] = date_limits[0]
        params['start__lt'] = date_limits[1]
    resp = await _query_clist_api('contest', data=params)
    if resp==None or 'objects' not in resp:
        raise ClientError
    else:
        resp = resp['objects']
    return resp