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
        if not handles or len(handles) > 5:
            await ctx.send('Number of handles must be between 1 and 5')
            return

        url = API_BASE_URL + '/user.status'
        allratings = []

        for handle in handles:
            params = {'handle': handle}
            try:
                async with self.session.get(url, params=params) as resp:
                    respjson = await resp.json()
            except aiohttp.ClientConnectionError as e:
                logging.error(f'Request to CF API encountered error: {e}')
                await ctx.send('Error connecting to Codeforces API')
                return

            if respjson['status'] == 'FAILED':
                if 'not found' in respjson['comment']:
                    await ctx.send(f'Handle not found: `{handle}`')
                else:
                    logging.info(f'CF API denied request with comment {respjson["comment"]}')
                    await ctx.send('Codeforces API denied the request, please make sure handles are valid.')
                return

            submissions = respjson['result']
            problems = set()
            for submission in submissions:
                if submission['verdict'] == 'OK':
                    problem = submission['problem']
                    # CF problems don't have IDs! Just hope (name, rating) pairs don't clash?
                    name = problem['name']
                    rating = problem.get('rating')
                    if rating:
                        problems.add((name, rating))

            ratings = [rating for name, rating in problems]
            allratings.append(ratings)

        # Adjust bin size so it looks nice
        step = 100 if len(handles) == 1 else 200
        histbins = np.arange(500, 3800, step)

        # matplotlib ignores labels that begin with _
        # https://matplotlib.org/api/pyplot_api.html#matplotlib.pyplot.legend
        # Add zero-width space to work around this
        zero_width_space = '\u200b'
        labels = [f'{zero_width_space}{handle}: {len(ratings)}' for handle, ratings in zip(handles, allratings)]

        plt.clf()
        plt.hist(allratings, bins=histbins, label=labels)
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
