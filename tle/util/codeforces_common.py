import asyncio
import functools
import json
import logging
import os
from collections import defaultdict

from discord.ext import commands

from tle import constants
from tle.util import cache_system2
from tle.util import codeforces_api as cf
from tle.util import db
from tle.util import discord_common
from tle.util import event_system
from tle.util.cache_system import CacheSystem

logger = logging.getLogger(__name__)

# Connection to database
user_db = None

# Cache system
cache = None
cache2 = None

# Event system
event_sys = event_system.EventSystem()

_contest_id_to_writers_map = None

active_groups = defaultdict(set)


async def initialize(nodb):
    global cache
    global cache2
    global user_db
    global event_sys
    global _contest_id_to_writers_map

    if nodb:
        user_db = db.DummyUserDbConn()
    else:
        user_db_file = os.path.join(constants.FILEDIR, constants.USER_DB_FILENAME)
        user_db = db.UserDbConn(user_db_file)

    cache = CacheSystem(user_db)
    # Initial fetch from CF API
    await cache.force_update()
    if cache.contest_last_cache and cache.problems_last_cache:
        logger.info('Initial fetch done, cache loaded')
    else:
        # If fetch failed, load from disk
        logger.info('Loading cache from disk')
        cache.try_disk()
    asyncio.create_task(_cache_refresher_task())

    cache_db_file = os.path.join(constants.FILEDIR, constants.CACHE_DB_FILENAME)
    cache_db = db.CacheDbConn(cache_db_file)
    cache2 = cache_system2.CacheSystem(cache_db)
    await cache2.run()

    jsonfile = os.path.join(constants.FILEDIR, constants.CONTEST_WRITERS_JSON_FILE)
    try:
        with open(jsonfile) as f:
            data = json.load(f)
        _contest_id_to_writers_map = {contest['id']: contest['writers'] for contest in data}
        logger.info('Contest writers loaded from JSON file')
    except FileNotFoundError:
        logger.warning('JSON file containing contest writers not found')


# algmyr's guard idea:
def user_guard(*, group):
    active = active_groups[group]

    def guard(fun):
        @functools.wraps(fun)
        async def f(self, ctx, *args, **kwargs):
            user = ctx.message.author.id
            if user in active:
                logger.info(f'{user} repeatedly calls {group} group')
                return
            active.add(user)
            try:
                await fun(self, ctx, *args, **kwargs)
            finally:
                active.remove(user)

        return f

    return guard


_CACHE_REFRESH_INTERVAL = 60 * 60


async def _cache_refresher_task():
    while True:
        await asyncio.sleep(_CACHE_REFRESH_INTERVAL)
        logger.info('Attempting cache refresh')
        await cache.force_update()


def is_contest_writer(contest_id, handle):
    if _contest_id_to_writers_map is None:
        return False
    writers = _contest_id_to_writers_map.get(contest_id)
    return writers and handle in writers


_NONSTANDARD_CONTEST_INDICATORS = [
    'wild', 'fools', 'unrated', 'surprise', 'unknown', 'friday', 'q#', 'testing', 'marathon']


def is_nonstandard_contest(contest):
    return any(string in contest.name.lower() for string in _NONSTANDARD_CONTEST_INDICATORS)


class CodeforcesHandleError(commands.CommandError):
    pass


class HandleCountOutOfBoundsError(CodeforcesHandleError):
    def __init__(self, mincnt, maxcnt):
        super().__init__(f'Number of handles must be between {mincnt} and {maxcnt}')


class FindMemberFailedError(CodeforcesHandleError):
    def __init__(self, member):
        super().__init__(f'Unable to convert `{member}` to a server member')


class HandleNotRegisteredError(CodeforcesHandleError):
    def __init__(self, member):
        super().__init__(f'Codeforces handle for member {member.mention} not found in database')


class HandleIsVjudgeError(CodeforcesHandleError):
    HANDLES = 'vjudge1 vjudge2 vjudge3 vjudge4 vjudge5'.split()

    def __init__(self, handle):
        super().__init__(f"`{handle}`? I'm not doing that!\n\n(╯°□°）╯︵ ┻━┻")


class RunHandleCoroFailedError(commands.CommandError):
    def __init__(self, handle, error):
        message = None
        if isinstance(error, cf.ClientError):
            message = 'Error connecting to Codeforces API'
        elif isinstance(error, cf.NotFoundError):
            message = f'Handle not found on Codeforces: `{handle}`'
        elif isinstance(error, cf.InvalidParamError):
            message = f'Not a valid Codeforces handle: `{handle}`'
        elif isinstance(error, cf.CodeforcesApiError):
            message = 'Codeforces API error'
        if message is not None:
            super().__init__(message)
        else:
            super().__init__()


async def resolve_handles(ctx, converter, handles, *, mincnt=1, maxcnt=5):
    """Convert an iterable of strings to CF handles. A string beginning with ! indicates Discord username,
     otherwise it is a raw CF handle to be left unchanged."""
    # If this is called from a Discord command, it is recommended to call the
    # cf_handle_error_handler function below from the command's error handler.
    if len(handles) < mincnt or maxcnt < len(handles):
        raise HandleCountOutOfBoundsError(mincnt, maxcnt)
    resolved_handles = []
    for handle in handles:
        if handle.startswith('!'):
            # ! denotes Discord user
            member_identifier = handle[1:]
            try:
                member = await converter.convert(ctx, member_identifier)
            except commands.errors.CommandError:
                raise FindMemberFailedError(member_identifier)
            handle = user_db.gethandle(member.id)
            if handle is None:
                raise HandleNotRegisteredError(member)
        if handle in HandleIsVjudgeError.HANDLES:
            raise HandleIsVjudgeError(handle)
        resolved_handles.append(handle)
    return resolved_handles


async def run_handle_related_coro(handles, coro):
    """Run a coroutine that takes a handle, for each handle in handles. Returns a list of results."""
    # If this is called from a Discord command, it is recommended to call the
    # run_handle_coro_error_handler function below from the command's error handler.
    results = []
    for handle in handles:
        try:
            res = await coro(handle=handle)
            results.append(res)
            continue
        except cf.CodeforcesApiError as ex:
            raise RunHandleCoroFailedError(handle, ex) from ex
    return results


async def cf_handle_error_handler(ctx, error):
    if isinstance(error, CodeforcesHandleError):
        await ctx.send(embed=discord_common.embed_alert(error))
        error.handled = True


async def run_handle_coro_error_handler(ctx, error):
    if isinstance(error, RunHandleCoroFailedError):
        await ctx.send(embed=discord_common.embed_alert(error))
        error.handled = True
