import traceback

from discord.ext import commands

from tle.util import codeforces_common as cf_common


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
        await cf_common.cache2.contest_cache.reload_now()
        await ctx.send('Done')

    @cache.command()
    async def problems(self, ctx):
        await ctx.send('Running...')
        await cf_common.cache2.problem_cache.reload_now()
        await ctx.send('Done')

    @cache.command(brief='Warning! This may freeze the bot for some time',
                   usage='[contest_id|all]')
    async def ratingchanges(self, ctx, contest_id):
        if contest_id != 'all':
            try:
                contest_id = int(contest_id)
            except ValueError:
                return
        await ctx.send('Running...')
        if contest_id == 'all':
            count = await cf_common.cache2.rating_changes_cache.fetch_all_contests()
        else:
            count = await cf_common.cache2.rating_changes_cache.fetch_contest(contest_id)
        await ctx.send(f'Done, fetched {count} changes')

    async def cog_command_error(self, ctx, error):
        error = error.__cause__
        lines = traceback.format_exception(type(error), error, error.__traceback__)
        msg = '\n'.join(lines)
        await ctx.send(f'```{msg}```')


def setup(bot):
    bot.add_cog(CacheControl(bot))
