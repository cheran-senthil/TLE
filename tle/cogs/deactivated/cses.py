import asyncio
from collections import defaultdict

from discord.ext import commands
from tle.util import cses_scraper as cses
from tle.util import discord_common
from tle.util import table
from tle.util import tasks


def score(placings):
    points = {1: 8, 2: 5, 3: 3, 4: 2, 5: 1}
    #points = {1:5, 2:4, 3:3, 4:2, 5:1}
    return sum(points[rank] for rank in placings)


class CSES(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.short_placings = {}
        self.fast_placings = {}
        self.reloading = False

    @commands.Cog.listener()
    @discord_common.once
    async def on_ready(self):
        self._cache_data.start()

    @tasks.task_spec(name='ProblemsetCacheUpdate',
                     waiter=tasks.Waiter.fixed_delay(30*60))
    async def _cache_data(self, _):
        await self._reload()

    async def _reload(self):
        self.reloading = True
        short_placings = defaultdict(list)
        fast_placings = defaultdict(list)
        try:
            for pid in await cses.get_problems():
                fast, short = await cses.get_problem_leaderboard(pid)
                for i in range(len(fast)):
                    fast_placings[fast[i]].append(i + 1)
                for i in range(len(short)):
                    short_placings[short[i]].append(i + 1)
            self.short_placings = short_placings
            self.fast_placings = fast_placings
        finally:
            self.reloading = False

    def format_leaderboard(self, top, placings):
        if not top:
            return 'Failed to load :<'

        header = ' 1st 2nd 3rd 4th 5th '.split(' ')

        style = table.Style(
                header = '{:>}   {:>} {:>} {:>} {:>} {:>}   {:>}',
                body   = '{:>} | {:>} {:>} {:>} {:>} {:>} | {:>} pts'
        )

        t = table.Table(style)
        t += table.Header(*header)

        for user, points in top:
            hist = [placings[user].count(i + 1) for i in range(5)]
            t += table.Data(user, *hist, points)

        return str(t)        

    def leaderboard(self, placings, num):
        leaderboard = sorted(
            ((k, score(v)) for k, v in placings.items() if k != 'N/A'),
            key=lambda x: x[1],
            reverse=True)

        top = leaderboard[:num]
        
        return self.format_leaderboard(top, placings)
    
    def leaderboard_individual(self, placings, handles):
        leaderboard = sorted(
            ((k, score(v)) for k, v in placings.items() if k != 'N/A' and k in handles),
            key=lambda x: x[1],
            reverse=True)
        
        included = [handle for handle, score in leaderboard]
        leaderboard += [(handle, 0) for handle in handles if handle not in included]
        
        top = leaderboard
        
        return self.format_leaderboard(top, placings)

    @property
    def fastest(self, num=10):
        return self.leaderboard(self.fast_placings, num)

    @property
    def shortest(self, num=10):
        return self.leaderboard(self.short_placings, num)

    def fastest_individual(self, handles):
        return self.leaderboard_individual(self.fast_placings, handles)

    def shortest_individual(self, handles):
        return self.leaderboard_individual(self.short_placings, handles)

    @commands.command(brief='Shows compiled CSES leaderboard', usage='[handles...]')
    async def cses(self, ctx, *handles: str):
        """Shows compiled CSES leaderboard. If handles are given, leaderboard will contain only those indicated handles, otherwise leaderboard will contain overall top ten."""
        if not handles:
            await ctx.send('```\n' 'Fastest\n' + self.fastest + '\n\n' + 'Shortest\n' + self.shortest + '\n' + '```')
        elif len(handles) > 10:
            await ctx.send('```Please indicate at most 10 users```')
        else:
            handles = set(handles)
            await ctx.send('```\n' 'Fastest\n' + self.fastest_individual(handles) + '\n\n' + 'Shortest\n' + self.shortest_individual(handles) + '\n' + '```')

    @commands.command(brief='Force update the CSES leaderboard')
    async def _updatecses(self, ctx):
        """Shows compiled CSES leaderboard."""
        if self.reloading:
            await ctx.send("Have some patience, I'm already reloading!")
        else:
            await self._reload()
            await ctx.send('CSES leaderboards updated!')


def setup(bot):
    bot.add_cog(CSES(bot))
