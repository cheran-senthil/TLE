import aiohttp

from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import handle_conn


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
            handle = handle_conn.conn.gethandle(member.id)
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
