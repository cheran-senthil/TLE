import asyncio
import logging

import aiohttp

from discord.ext import commands
from collections import defaultdict
from functools import wraps

from tle.util import codeforces_api as cf
from tle.util.handle_conn import HandleConn
from tle.util.cache_system import CacheSystem

logger = logging.getLogger(__name__)

CONTESTS_BASE_URL = 'https://codeforces.com/contests/'

# Connection to database
conn = None
# Cache system
cache = None

active_groups = defaultdict(set)

def guard_group(*, group):
    active = active_groups[group]
    def guard(fun):
        @wraps(fun)
        async def f(self, ctx, *args, **kwargs):
            user = ctx.message.author.id
            if user in active:
                logging.info(f'{user} repeatedly calls {group} group')
                return
            active.add(user)
            await fun(self, ctx, *args, **kwargs)
            active.remove(user)
        return f
    return guard

def initialize_conn(dbfile):
    global conn
    conn = HandleConn(dbfile)

async def initialize_cache(refresh_interval):
    global cache
    cache = CacheSystem(conn)
    # Initial fetch from CF API
    await cache.force_update()
    if cache.contest_last_cache and cache.problems_last_cache:
        logger.info('Initial fetch done, cache loaded')
    else:
        # If fetch failed, load from disk
        logger.info('Loading cache from disk')
        cache.try_disk()
    asyncio.create_task(_cache_refresher_task(refresh_interval))


async def _cache_refresher_task(refresh_interval):
    while True:
        await asyncio.sleep(refresh_interval)
        logger.info('Attempting cache refresh')
        await cache.force_update()


class CodeforcesHandleError(Exception):
    pass


class ResolveHandleFailedError(CodeforcesHandleError):
    pass


class RunHandleCoroFailedError(CodeforcesHandleError):
    pass


async def resolve_handles_or_reply_with_error(ctx, converter, handles, *, mincnt=1, maxcnt=5):
    """Convert an iterable of strings to CF handles. A string beginning with ! indicates Discord username,
     otherwise it is a raw CF handle to be left unchanged."""
    if len(handles) < mincnt or maxcnt < len(handles):
        await ctx.send(f'Number of handles must be between {mincnt} and {maxcnt}')
        return []
    resolved_handles = []
    for handle in handles:
        if handle.startswith('!'):
            # ! denotes Discord user
            try:
                member = await converter.convert(ctx, handle[1:])
            except commands.errors.CommandError:
                await ctx.send(f'Unable to convert `{handle}` to a server member')
                raise ResolveHandleFailedError(handle)
            handle = conn.gethandle(member.id)
            if handle is None:
                await ctx.send(f'Codeforces handle for member {member.display_name} not found in database')
                raise ResolveHandleFailedError(handle)
        resolved_handles.append(handle)
    return resolved_handles


async def run_handle_related_coro_or_reply_with_error(ctx, handles, coro):
    """Run a coroutine that takes a handle, for each handle in handles. Returns a list of results."""
    results = []
    for handle in handles:
        try:
            res = await coro(handle=handle)
            results.append(res)
            continue
        except aiohttp.ClientConnectionError:
            await ctx.send('Error connecting to Codeforces API')
        except cf.NotFoundError:
            await ctx.send(f'Handle not found: `{handle}`')
        except cf.InvalidParamError:
            await ctx.send(f'Not a valid Codeforces handle: `{handle}`')
        except cf.CodeforcesApiError:
            await ctx.send('Codeforces API error.')
        raise RunHandleCoroFailedError(handle)
    return results
