import io
import logging
import os
import time
import datetime
import random

import aiohttp
import discord
from matplotlib import pyplot as plt

from discord.ext import commands

def round_rating(rating):
    rem = rating % 100
    rating -= rem
    return rating + 100 if rem >= 50 else rating

API_BASE_URL = 'http://codeforces.com/api/'
CNT_BASE_URL = 'http://codeforces.com/contest/'

class Codeforces(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    async def query_api(self, path, params=None):
        url = API_BASE_URL + path
        try:
            async with self.session.get(url, params=params) as resp:
                return await resp.json()
        except aiohttp.ClientConnectionError as e:
            logging.error(f'Request to CF API encountered error: {e}')
            return None

    @commands.command(brief='git gud.')
    async def gitgud(self, ctx, *handles: str):
        """git gud."""
        if not handles or len(handles) > 1:
            await ctx.send('Number of handles must be between 1 and 1')
            return

        probjson = await self.query_api('problemset.problems')
        respjson = await self.query_api('user.info', {'handles': handles[0]})
        subsjson = await self.query_api('user.status', {'handle': handles[0]})
        rating = round_rating(respjson['result'][0]['rating'])
        problems = probjson['result']['problems']
        probs = set()
        for problem in problems:
            if '*special' not in problem['tags'] and 'rating' in problem and problem['rating'] == rating:
                if 'contestId' in problem:
                    probs.add((problem['name'], problem['contestId']))

        solved = set()
        for sub in subsjson['result']:
            problem = sub['problem']
            if sub['verdict'] == 'OK' and 'contestId' in problem:
                solved.add((problem['name'], problem['contestId']))

        gudprobs = [x for x in probs if x not in solved]
        gudprob = random.choice(gudprobs)
        await ctx.send('Solve `{}` from {}{} to git gud, {}'.format(gudprob[0], CNT_BASE_URL, gudprob[1], handles[0]))

    @commands.command(brief='Compare epeens.')
    async def rating(self, ctx, *handles: str):
        """Compare epeens."""
        if not handles or len(handles) > 5:
            await ctx.send('Number of handles must be between 1 and 5')
            return

        plt.clf()
        rate = []
        for handle in handles:
            respjson = await self.query_api('user.rating', {'handle': handle})
            if respjson is None:
                await ctx.send('Error connecting to Codeforces API')
                return

            if respjson['status'] == 'FAILED':
                if 'not found' in respjson['comment']:
                    await ctx.send(f'Handle not found: `{handle}`')
                else:
                    logging.info(f'CF API denied request with comment {respjson["comment"]}')
                    await ctx.send('Codeforces API denied the request, please make sure handles are valid.')
                return

            contests = respjson['result']
            ratings = []
            times = []
            for contest in contests:
                ratings.append(contest['newRating'])
                times.append(datetime.datetime.fromtimestamp(contest['ratingUpdateTimeSeconds']))
            plt.plot(times, ratings)
            rate.append(ratings[-1])

        ymin, ymax = plt.gca().get_ylim()
        colors = [('#AA0000', 3000, 4000),
                  ('#FF3333', 2600, 3000),
                  ('#FF7777', 2400, 2600),
                  ('#FFBB55', 2300, 2400),
                  ('#FFCC88', 2100, 2300),
                  ('#FF88FF', 1900, 2100),
                  ('#AAAAFF', 1600, 1900),
                  ('#77DDBB', 1400, 1600),
                  ('#77FF77', 1200, 1400),
                  ('#CCCCCC', 0, 1200)]

        for color, lo, hi in colors:
            plt.axhspan(lo, hi, facecolor=color)
        plt.ylim(ymin, ymax)
        plt.gcf().autofmt_xdate()

        zero_width_space = '\u200b'
        labels = [f'{zero_width_space}{handle} ({rating})' for handle, rating in zip(handles, rate)]
        plt.legend(labels)
        discordFile = self.get_current_figure_as_file()
        await ctx.send(file=discordFile)

    @commands.command(brief='Show histogram of solved problems on CF.')
    async def solved(self, ctx, *handles: str):
        """Shows a histogram of problems solved on Codeforces for the handles provided."""
        if not handles or len(handles) > 5:
            await ctx.send('Number of handles must be between 1 and 5')
            return

        allratings = []

        for handle in handles:
            respjson = await self.query_api('user.status', {'handle': handle})
            if respjson is None:
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
        histbins = list(range(500, 3800 + step, step))

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
        discordFile = self.get_current_figure_as_file()
        await ctx.send(file=discordFile)

    @staticmethod
    def get_current_figure_as_file():
        filename = f'tempplot_{time.time()}.png'
        plt.savefig(filename, facecolor=plt.gca().get_facecolor(), bbox_inches='tight', pad_inches=0.25)
        with open(filename, 'rb') as file:
            discordFile = discord.File(io.BytesIO(file.read()), filename='plot.png')
        os.remove(filename)
        return discordFile


def setup(bot):
    bot.add_cog(Codeforces(bot))
