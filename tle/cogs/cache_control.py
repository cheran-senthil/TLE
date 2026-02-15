import functools
import time
from collections.abc import Callable, Coroutine
from typing import Any

from discord.ext import commands

from tle import constants


def timed_command(
    coro: Callable[..., Coroutine[Any, Any, None]],
) -> Callable[..., Coroutine[Any, Any, None]]:
    @functools.wraps(coro)
    async def wrapper(cog: commands.Cog, ctx: commands.Context, *args: Any) -> None:
        await ctx.send('Running...')
        begin = time.time()
        await coro(cog, ctx, *args)
        elapsed = time.time() - begin
        await ctx.send(f'Completed in {elapsed:.2f} seconds')

    return wrapper


class CacheControl(commands.Cog):
    """Cog to manually trigger update of cached data. Intended for dev/admin use."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(brief='Commands to force reload of cache', fallback='show')
    @commands.has_role(constants.TLE_ADMIN)
    async def cache(self, ctx: commands.Context) -> None:
        await ctx.send_help('cache')

    @cache.command()
    @commands.has_role(constants.TLE_ADMIN)
    @timed_command
    async def contests(self, ctx: commands.Context) -> None:
        await self.bot.cf_cache.contest_cache.reload_now()

    @cache.command()
    @commands.has_role(constants.TLE_ADMIN)
    @timed_command
    async def problems(self, ctx: commands.Context) -> None:
        await self.bot.cf_cache.problem_cache.reload_now()

    @cache.command(usage='[missing|all|contest_id]')
    @commands.has_role(constants.TLE_ADMIN)
    @timed_command
    async def ratingchanges(
        self, ctx: commands.Context, contest_id: str = 'missing'
    ) -> None:
        """Defaults to 'missing'. Mode 'all' clears existing cached changes.
        Mode 'contest_id' clears existing changes with the given contest id.
        """
        if contest_id not in ('all', 'missing'):
            try:
                contest_id_int = int(contest_id)
            except ValueError:
                return
            count = await self.bot.cf_cache.rating_changes_cache.fetch_contest(
                contest_id_int
            )
        elif contest_id == 'all':
            await ctx.send('This will take a while')
            count = await self.bot.cf_cache.rating_changes_cache.fetch_all_contests()
        else:
            await ctx.send('This may take a while')
            count = (
                await self.bot.cf_cache.rating_changes_cache.fetch_missing_contests()
            )
        await ctx.send(f'Done, fetched {count} changes and recached handle ratings')

    @cache.command(usage='contest_id|all')
    @commands.has_role(constants.TLE_ADMIN)
    @timed_command
    async def problemsets(self, ctx: commands.Context, contest_id: str) -> None:
        """Mode 'all' clears all existing cached problems. Mode 'contest_id'
        clears existing problems with the given contest id.
        """
        if contest_id == 'all':
            await ctx.send('This will take a while')
            count = await self.bot.cf_cache.problemset_cache.update_for_all()
        else:
            try:
                contest_id_int = int(contest_id)
            except ValueError:
                return
            count = await self.bot.cf_cache.problemset_cache.update_for_contest(
                contest_id_int
            )
        await ctx.send(f'Done, fetched {count} problems')


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CacheControl(bot))
