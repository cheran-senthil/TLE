import os

import aiohttp
import discord
import numpy as np
from discord.ext import commands
from matplotlib import pyplot as plt

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
            print(handle, sorted(Counter(ratings).items()))
            allratings.append(ratings)

        # Adjust bin size so it looks nice
        step = 100 if len(handles) == 1 else 200
        histbins = np.arange(300, 3800, step)
        plt.clf()
        plt.hist(allratings, bins=histbins, label=handles)
        plt.title('Histogram of problems solved on Codeforces')
        plt.xlabel('Problem rating')
        plt.ylabel('Number solved')
        plt.legend(loc='upper right')
        filename = 'tempplot.png'
        plt.savefig(filename)
        await ctx.send(file=discord.File(filename))
        os.remove(filename)


def setup(bot):
    bot.add_cog(Codeforces(bot))
