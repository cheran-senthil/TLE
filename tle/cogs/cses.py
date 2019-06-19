import asyncio
from collections import defaultdict

from discord.ext import commands
from tle.util import cses_scraper as cses
from tle.util import table


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
    async def on_ready(self):
        asyncio.create_task(self._cache_data())

    async def _cache_data(self):
        while True:
            await self._reload()
            await asyncio.sleep(600)

    async def _reload(self):
        self.reloading = True
        self.short_placings = {}
        self.fast_placings = {}

        short_placings = defaultdict(list)
        fast_placings = defaultdict(list)
        try:
            for pid in await cses.get_problems():
                fast, short = await cses.get_problem_leaderboard(pid)
                for i in range(len(fast)):
                    fast_placings[fast[i]].append(i + 1)
                for i in range(len(short)):
                    short_placings[short[i]].append(i + 1)
        except cses.CSESError:
            pass  # TODO log here?
        finally:
            self.reloading = False
            self.short_placings = short_placings
            self.fast_placings = fast_placings

    def leaderboard(self, placings, num):
        leaderboard = sorted(
            ((k, score(v)) for k, v in placings.items() if k != 'N/A'),
            key=lambda x: x[1],
            reverse=True)

        if not leaderboard:
            return 'Failed to load :<'

        top = leaderboard[:num]

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

    @property
    def fastest(self, num=10):
        return self.leaderboard(self.fast_placings, num)

    @property
    def shortest(self, num=10):
        return self.leaderboard(self.short_placings, num)

    @commands.command(brief='Shows compiled CSES leaderboard')
    async def cses(self, ctx):
        """Shows compiled CSES leaderboard."""
        await ctx.send('```\n' 'Fastest\n' + self.fastest + '\n\n' + 'Shortest\n' + self.shortest + '\n' + '```')

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
