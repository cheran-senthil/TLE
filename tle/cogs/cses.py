import asyncio
from collections import defaultdict

import discord
from discord.ext import commands
from tle.cogs.util import cses_scraper as cses


def score(placings):
    points = {1: 8, 2: 5, 3: 3, 4: 2, 5: 1}
    #points = {1:5, 2:4, 3:3, 4:2, 5:1}
    return sum(points[rank] for rank in placings)


class CSES(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.short_placings = defaultdict(list)
        self.fast_placings = defaultdict(list)

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self._cache_data())

    async def _cache_data(self):
        while True:
            await self._reload()
            await asyncio.sleep(600)

    async def _reload(self):
        self.short_placings = defaultdict(list)
        self.fast_placings = defaultdict(list)

        try:
            for pid in await cses.get_problems():
                fast, short = await cses.get_problem_leaderboard(pid)
                for i in range(len(fast)):
                    self.fast_placings[fast[i]].append(i + 1)
                for i in range(len(short)):
                    self.short_placings[short[i]].append(i + 1)
        except cses.CSESError:
            pass  # TODO log here?

    def leaderboard(self, placings, num):
        leaderboard = sorted(((k, score(v)) for k, v in placings.items()), key=lambda x: x[1], reverse=True)

        if not leaderboard:
            return 'Failed to load :<'

        top = leaderboard[:num]
        maxname = max(len(name) for name, _ in top)

        S = []
        for user, points in top:
            userpad = user.rjust(maxname)
            hist = [placings[user].count(i + 1) for i in range(5)]
            ranks = ' '.join(f'{count:3d}' for count in hist)
            S.append(f'{userpad} | {ranks} | {points:3d} points')

        header = (maxname + 3) * ' ' + '1st 2nd 3rd 4th 5th'
        return '\n'.join([header] + S)

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


def setup(bot):
    bot.add_cog(CSES(bot))
