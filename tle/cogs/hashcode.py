import asyncio
from collections import defaultdict

from discord.ext import commands
from tle.util import cses_scraper as cses
from tle.util import table

import logging
import aiohttp
from lxml import etree


class HashcodeError(Exception):
    pass


session = aiohttp.ClientSession()

teams = [
    'grumpycapybara',
    'too_difficult_stop_creating_problems',
    'heisenbugs certainty principle',
    'daegons',
    ]

async def _fetch(url):
    async with session.get(url) as response:
        if response.status != 200:
            raise HashcodeError(f"Bad response from Hashcode, status code {status}")
        myparser = etree.HTMLParser(encoding="utf-8")
        tree = etree.HTML(await response.read(), parser=myparser)

    return tree

async def get_leaderboard():
    tree = await _fetch('https://hashcodejudge.withgoogle.com/scoreboard')
    leaderboard = []

    i = 0
    for tr in tree.xpath('//tr[@class="recruitingHashcodeJudgeServerTableBodyLine"]'):
        place,name,score = [td.text for td in tr]
        if i < 5 or name.lower() in teams:
            leaderboard.append((place, name, score))
        i += 1
    return leaderboard


class Hashcode(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def format_leaderboard(self, leaderboard):
        style = table.Style(
                header = '{:>} {:^} {:>}',
                body   = '{:>} {:^} {:>}'
        )

        t = table.Table(style)
        t += table.Header('Rank', 'Name', 'Score')
        t += table.Line()
        for row in leaderboard:
            t += table.Data(*row)

        return str(t)        

    @commands.command(brief='Shows how our teams are doing')
    async def hashcode(self, ctx):
        """Shows hashcode scoreboard"""

        leader = self.format_leaderboard(await get_leaderboard())
        await ctx.send('```\n' + leader + '\n```')



def setup(bot):
    bot.add_cog(Hashcode(bot))
