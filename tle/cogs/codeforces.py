import io
import os
import time
import datetime
import random

import aiohttp
from matplotlib import pyplot as plt

import discord
from discord.ext import commands

from .util import codeforces_api as cf


class Codeforces(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(brief='Recommend a problem')
    async def gitgud(self, ctx, handle: str):
        """Recommends a problem based on Codeforces rating of the handle provided."""

        def round_rating(rating):
            rem = rating % 100
            rating -= rem
            return rating + 100 if rem >= 50 else rating

        try:
            probresp = await cf.problemset.problems()
            inforesp = await cf.user.info(handles=[handle])
            subsresp = await cf.user.status(handle=handle)
        except aiohttp.ClientConnectionError:
            await ctx.send('Error connecting to Codeforces API')
            return
        except cf.NotFoundError:
            await ctx.send(f'Handle not found: `{handle}`')
            return
        except cf.CodeforcesApiError:
            await ctx.send('Codeforces API denied the request, please make the handle is valid.')
            return

        user_rating = inforesp[0].get('rating')
        if user_rating is None:
            # Assume unrated is noob
            user_rating = 500
        user_rating = round_rating(user_rating)
        problems = probresp['problems']
        recommendations = {}
        for problem in problems:
            if '*special' not in problem['tags'] and problem.get('rating') == user_rating:
                if 'contestId' in problem:
                    name = problem['name']
                    contestid = problem['contestId']
                    index = problem['index']
                    rating = problem['rating']
                    # Consider (name, rating) as key
                    recommendations[(name, rating)] = (contestid, index)

        for sub in subsresp:
            problem = sub['problem']
            if sub['verdict'] == 'OK' and 'rating' in problem:
                name = problem['name']
                rating = problem['rating']
                recommendations.pop((name, rating), None)

        if not recommendations:
            await ctx.send('{} is already too gud'.format(handle))
        else:
            name, rating = random.choice(list(recommendations.keys()))
            contestid, index = recommendations[(name, rating)]
            # 'from' and 'count' are for ranklist, query minimum allowed (1) since we do not need it
            contestresp = await cf.contest.standings(contestid=contestid, from_=1, count=1)
            contestname = contestresp['contest']['name']
            title = f'{index}. {name}'
            url = f'{cf.CONTEST_BASE_URL}{contestid}/problem/{index}'
            desc = f'{contestname}\nRating: {rating}'
            await ctx.send(
                f'Recommended problem for `{handle}`', embed=discord.Embed(title=title, url=url, description=desc))

    @commands.command(brief='Compare epeens.')
    async def rating(self, ctx, *handles: str):
        """Compare epeens."""
        if not handles or len(handles) > 5:
            await ctx.send('Number of handles must be between 1 and 5')
            return

        plt.clf()
        rate = []
        for handle in handles:
            try:
                contests = await cf.user.rating(handle=handle)
            except aiohttp.ClientConnectionError:
                await ctx.send('Error connecting to Codeforces API')
                return
            except cf.NotFoundError:
                await ctx.send(f'Handle not found: `{handle}`')
                return
            except cf.CodeforcesApiError:
                await ctx.send('Codeforces API denied the request, please make sure handles are valid.')
                return

            ratings = []
            times = []
            for contest in contests:
                ratings.append(contest['newRating'])
                times.append(datetime.datetime.fromtimestamp(contest['ratingUpdateTimeSeconds']))
            plt.plot(
                times, ratings, linestyle='-', marker='o', markersize=3, markerfacecolor='white', markeredgewidth=0.5)
            rate.append(ratings[-1])

        ymin, ymax = plt.gca().get_ylim()
        colors = [('#AA0000', 3000, 4000), ('#FF3333', 2600, 3000), ('#FF7777', 2400, 2600), ('#FFBB55', 2300, 2400),
                  ('#FFCC88', 2100, 2300), ('#FF88FF', 1900, 2100), ('#AAAAFF', 1600, 1900), ('#77DDBB', 1400, 1600),
                  ('#77FF77', 1200, 1400), ('#CCCCCC', 0, 1200)]

        for color, lo, hi in colors:
            plt.axhspan(lo, hi, facecolor=color)
        plt.ylim(ymin, ymax)
        plt.gcf().autofmt_xdate()
        locs, labels = plt.xticks()
        for loc in locs:
            plt.axvspan(loc, loc, facecolor='white')

        zero_width_space = '\u200b'
        labels = [f'{zero_width_space}{handle} ({rating})' for handle, rating in zip(handles, rate)]
        plt.legend(labels)
        discord_file = self.get_current_figure_as_file()
        await ctx.send(file=discord_file)

    @commands.command(brief='Show histogram of solved problems on CF.')
    async def solved(self, ctx, *handles: str):
        """Shows a histogram of problems solved on Codeforces for the handles provided."""
        if not handles or len(handles) > 5:
            await ctx.send('Number of handles must be between 1 and 5')
            return

        allratings = []

        for handle in handles:
            try:
                submissions = await cf.user.status(handle=handle)
            except aiohttp.ClientConnectionError:
                await ctx.send('Error connecting to Codeforces API')
                return
            except cf.NotFoundError:
                await ctx.send(f'Handle not found: `{handle}`')
                return
            except cf.CodeforcesApiError:
                await ctx.send('Codeforces API denied the request, please make sure handles are valid.')
                return

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
        discord_file = self.get_current_figure_as_file()
        await ctx.send(file=discord_file)

    @staticmethod
    def get_current_figure_as_file():
        filename = f'tempplot_{time.time()}.png'
        plt.savefig(filename, facecolor=plt.gca().get_facecolor(), bbox_inches='tight', pad_inches=0.25)
        with open(filename, 'rb') as file:
            discord_file = discord.File(io.BytesIO(file.read()), filename='plot.png')
        os.remove(filename)
        return discord_file


def setup(bot):
    bot.add_cog(Codeforces(bot))
