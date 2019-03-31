import logging
import os
import time

import aiohttp
import discord
import numpy as np
from matplotlib import pyplot as plt

from discord.ext import commands

API_BASE_URL = 'http://codeforces.com/api/'


class Codeforces(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    @commands.command(brief='Show histogram of solved problems on CF.')
    async def solved(self, ctx, *handles: str):
        """Shows a histogram of problems solved on Codeforces for the handles provided."""
        if not handles:
            await ctx.send('Specify some handles')
            return
        if len(handles) > 5:
            await ctx.send('No more than 5 handles at once are supported')
            return

        url = API_BASE_URL + '/user.status'
        allratings = []

        for handle in handles:
            params = {'handle': handle}
            async with self.session.get(url, params=params) as resp:
                respjson = await resp.json()
            if respjson['status'] == 'FAILED':
                if 'not found' in respjson['comment']:
                    await ctx.send(f'Invalid handle: *{handle}*')
                else:
                    logging.info(f'Request to CF API failed with status {respjson["status"]} '
                                 f'and comment {respjson["comment"]}')
                    await ctx.send('Codeforces API error :(')
                return

            submissions = respjson['result']
            problems = set()
            for submission in submissions:
                if submission['verdict'] == 'OK':
                    problem = submission['problem']
                    # CF problems don't have IDs! Just hope names don't clash?
                    name = problem['name']
                    rating = problem.get('rating')
                    if rating:
                        problems.add((name, rating))

            ratings = [rating for name, rating in problems]
            from collections import Counter
            logging.debug(f'Problems: {handle}, {sorted(Counter(ratings).items())}')
            allratings.append(ratings)

        # Adjust bin size so it looks nice
        step = 100 if len(handles) == 1 else 200
        histbins = np.arange(500, 3800, step)

        # matplotlib ignores labels that begin with _
        # https://matplotlib.org/api/pyplot_api.html#matplotlib.pyplot.legend
        adjusted_handles = [handle.lstrip('_') for handle in handles]

        plt.clf()
        plt.hist(allratings, bins=histbins, label=adjusted_handles)
        plt.title('Histogram of problems solved on Codeforces')
        plt.xlabel('Problem rating')
        plt.ylabel('Number solved')
        plt.legend(loc='upper right')
        filename = f'tempplot_{time.time()}.png'
        plt.savefig(filename)
        await ctx.send(file=discord.File(filename))
        os.remove(filename)


def setup(bot):
    bot.add_cog(Codeforces(bot))
