import time
import traceback

from discord.ext import commands

from tle.util import codeforces_common as cf_common


class Timer:
    def __init__(self):
        self.begin = None
        self.elapsed = None

    def __enter__(self):
        self.begin = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed = time.time() - self.begin


class CacheControl(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(brief='Commands to force reload of cache',
                    invoke_without_command=True)
    @commands.has_role('Admin')
    async def cache(self, ctx):
        await ctx.send_help('cache')

    @cache.command()
    async def contests(self, ctx):
        await ctx.send('Running...')
        with Timer() as timer:
            await cf_common.cache2.contest_cache.reload_now()
        await ctx.send(f'Done in {timer.elapsed:.2f} seconds')

    @cache.command()
    async def problems(self, ctx):
        await ctx.send('Running...')
        with Timer() as timer:
            await cf_common.cache2.problem_cache.reload_now()
        await ctx.send(f'Done in {timer.elapsed:.2f} seconds')

    @cache.command(usage='[contest_id|all|missing]')
    async def ratingchanges(self, ctx, contest_id):
        if contest_id not in ('all', 'missing'):
            try:
                contest_id = int(contest_id)
            except ValueError:
                return
        await ctx.send('Running...')
        with Timer() as timer:
            if contest_id == 'all':
                await ctx.send('This will take a while')
                count = await cf_common.cache2.rating_changes_cache.fetch_all_contests()
            elif contest_id == 'missing':
                await ctx.send('This may take a while')
                count = await cf_common.cache2.rating_changes_cache.fetch_missing_contests()
            else:
                count = await cf_common.cache2.rating_changes_cache.fetch_contest(contest_id)
        await ctx.send(f'Done, fetched {count} changes and recached handle ratings in '
                       f'{timer.elapsed:.2f} seconds')

    async def cog_command_error(self, ctx, error):
        error = error.__cause__
        lines = traceback.format_exception(type(error), error, error.__traceback__)
        msg = '\n'.join(lines)
        await ctx.send(f'```{msg}```')


def setup(bot):
    bot.add_cog(CacheControl(bot))
