import datetime
import io
import os
import random
import time

import aiohttp
import discord
import asyncio
from discord.ext import commands
from matplotlib import pyplot as plt
from tle.cogs.util import codeforces_api as cf
from db_utils.handle_conn import HandleConn

from bisect import bisect_left


def get_current_figure_as_file():
    filename = f'tempplot_{time.time()}.png'
    plt.savefig(filename, facecolor=plt.gca().get_facecolor(), bbox_inches='tight', pad_inches=0.25)

    with open(filename, 'rb') as file:
        discord_file = discord.File(io.BytesIO(file.read()), filename='plot.png')

    os.remove(filename)
    return discord_file


class Codeforces(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = HandleConn('handles.db')
        self.converter = commands.MemberConverter()
        self.problems = None
        self.problem_ratings = None  # for binary search
        self.contest_names = {}

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.cache_problems())

    async def _cache_data(self):
        while True:
            await self.cache_problems()
            await asyncio.sleep(21600)

    async def Resolve(self, ctx, handle: str):
        if handle[0] != '!':
            return handle
        member = await self.converter.convert(ctx, handle[1:])
        res = self.conn.gethandle(member.id)
        if res is None:
            raise Exception('bad')
        return res

    async def cache_problems(self):
        try:
            problems, _ = await cf.problemset.problems()
            contests = await cf.contest.list()
        except aiohttp.ClientConnectionError:
            return
        except cf.CodeforcesApiError:
            return

        self.contest_names = dict((contest.id, contest.name) for contest in contests)
        banned_tags = ['*special']
        self.problems = [prob for prob in problems if prob.has_metadata() and not prob.has_any_tag_from(banned_tags)]
        self.problems.sort(key=lambda p: p.rating)
        self.problem_ratings = [p.rating for p in self.problems]

    @commands.command(brief='cache all cf problems and contest names')
    @commands.has_role('Admin')
    async def cacheproblems(self, ctx):
        await self.cache_problems()

    @commands.command(brief='Recommend a problem')
    async def gitgud(self, ctx, handle: str = None, tag: str = 'all', lower_bound: int = None, upper_bound: int = None):
        """Recommends a problem based on Codeforces rating of the handle provided."""
        try:
            handle = await self.Resolve(ctx, handle or '!' + str(ctx.author))
        except:
            await ctx.send('bad handle')
            return

        try:
            info = await cf.user.info(handles=[handle])
            subs = await cf.user.status(handle=handle)
        except aiohttp.ClientConnectionError:
            await ctx.send('Error connecting to Codeforces API')
            return
        except cf.NotFoundError:
            await ctx.send(f'Handle not found: `{handle}`')
            return
        except cf.InvalidParamError:
            await ctx.send(f'Not a valid Codeforces handle: `{handle}`')
            return
        except cf.CodeforcesApiError:
            await ctx.send('Codeforces API error.')
            return

        # 1500 is default lower_bound for unrated user
        lower_bound = lower_bound or info[0].rating or 1500
        lower_bound = round(lower_bound, -2)
        upper_bound = upper_bound or lower_bound + 300

        if not self.problems:
            # Try once
            await self.cache_problems()
        if not self.problems:
            # Could not cache problems
            await ctx.send('Error connecting to Codeforces API')
            return

        solved = [sub.problem for sub in subs if sub.verdict == 'OK']
        solved = set(prob.contest_identifier for prob in solved if prob.has_metadata())

        begin = bisect_left(self.problem_ratings, lower_bound)
        end = bisect_left(self.problem_ratings, upper_bound + 1, lo=begin)

        problems = [prob for prob in self.problems[begin:end] if prob.contest_identifier not in solved]
        if tag != 'all':
            problems = [prob for prob in problems if tag in prob.tags]

        if not problems:
            await ctx.send('Sorry, no problem found. Try changing the rating range.')
            return

        problems.sort(key=lambda p: p.contestId)
        numproblems = len(problems)
        # Choose problems with largest contestId with greater probability (heuristic for newer problems)
        choice = max(random.randrange(numproblems), random.randrange(numproblems))

        problem = problems[choice]
        contestname = self.contest_names[problem.contestId]

        title = f'{problem.index}. {problem.name}'
        url = f'{cf.CONTEST_BASE_URL}{problem.contestId}/problem/{problem.index}'
        desc = f'{contestname}\nRating: {problem.rating}'

        await ctx.send(
            f'Recommended problem for `{handle}`', embed=discord.Embed(title=title, url=url, description=desc))

    @commands.command(brief='Recommend a contest')
    async def vc(self, ctx, handle: str):
        """Recommends a contest based on Codeforces rating of the handle provided."""
        try:
            handle = await self.Resolve(ctx, handle)
        except:
            await ctx.send('Bad Handle')
            return

        try:
            problems, _ = await cf.problemset.problems()
            subs = await cf.user.status(handle=handle, count=10000)
        except aiohttp.ClientConnectionError:
            await ctx.send('Error connecting to Codeforces API')
            return
        except cf.NotFoundError:
            await ctx.send(f'Handle not found: `{handle}`')
            return
        except cf.InvalidParamError:
            await ctx.send(f'Not a valid Codeforces handle: `{handle}`')
            return
        except cf.CodeforcesApiError:
            await ctx.send('Codeforces API error.')
            return

        recommendations = set()

        for problem in problems:
            if '*special' not in problem.tags and problem.contestId:
                recommendations.add(problem.contestId)

        for sub in subs:
            recommendations.discard(sub.problem.contestId)

        if not recommendations:
            await ctx.send('{} is already too gud'.format(handle))
        else:
            contestid = random.choice(list(recommendations))
            # from and count are for ranklist, set to minimum (1) because we only need name
            contest, _, _ = await cf.contest.standings(contestid=contestid, from_=1, count=1)
            url = f'{cf.CONTEST_BASE_URL}{contestid}/'

            await ctx.send(f'Recommended contest for `{handle}`', embed=discord.Embed(title=contest.name, url=url))

    @commands.command(brief='Compare epeens.')
    async def rating(self, ctx, *handles: str):
        """Compare epeens."""
        handles = handles or ('!' + str(ctx.author),)
        if len(handles) > 5:
            await ctx.send('Number of handles must be at most 5')
            return
        try:
            handles = [await self.Resolve(ctx, h) for h in handles]
        except:
            await ctx.send('Bad Handle')
            return

        plt.clf()
        rate = []

        for handle in handles:
            try:
                rating_changes = await cf.user.rating(handle=handle)
            except aiohttp.ClientConnectionError:
                await ctx.send('Error connecting to Codeforces API')
                return
            except cf.NotFoundError:
                await ctx.send(f'Handle not found: `{handle}`')
                return
            except cf.InvalidParamError:
                await ctx.send(f'Not a valid Codeforces handle: `{handle}`')
                return
            except cf.CodeforcesApiError:
                await ctx.send('Codeforces API error.')
                return

            ratings, times = [], []
            for rating_change in rating_changes:
                ratings.append(rating_change.newRating)
                times.append(datetime.datetime.fromtimestamp(rating_change.ratingUpdateTimeSeconds))

            plt.plot(
                times, ratings, linestyle='-', marker='o', markersize=3, markerfacecolor='white', markeredgewidth=0.5)
            rate.append(ratings[-1])

        ymin, ymax = plt.gca().get_ylim()
        bgcolor = plt.gca().get_facecolor()
        for low, high, color, _ in cf.RankHelper.rank_info:
            plt.axhspan(low, high, facecolor=color, alpha=0.8, edgecolor=bgcolor, linewidth=0.5)

        plt.ylim(ymin, ymax)
        plt.gcf().autofmt_xdate()
        locs, labels = plt.xticks()

        for loc in locs:
            plt.axvline(loc, color=bgcolor, linewidth=0.5)

        zero_width_space = '\u200b'
        labels = [f'{zero_width_space}{handle} ({rating})' for handle, rating in zip(handles, rate)]
        plt.legend(labels, loc='upper left')
        plt.title('Rating graph on Codeforces')

        await ctx.send(file=get_current_figure_as_file())

    @commands.command(brief='Show histogram of solved problems on CF.')
    async def solved(self, ctx, *handles: str):
        """Shows a histogram of problems solved on Codeforces for the handles provided."""
        handles = handles or ('!' + str(ctx.author),)
        if len(handles) > 5:
            await ctx.send('Number of handles must be at most 5')
            return
        try:
            handles = [await self.Resolve(ctx, h) for h in handles]
        except:
            await ctx.send('Bad Handle')
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
            except cf.InvalidParamError:
                await ctx.send(f'Not a valid Codeforces handle: `{handle}`')
                return
            except cf.CodeforcesApiError:
                await ctx.send('Codeforces API error.')
                return

            problems = dict()
            for submission in submissions:
                problem = submission.problem
                if submission.verdict == 'OK' and problem.rating:
                    problems[problem.contest_identifier] = problem.rating

            ratings = list(problems.values())
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

        await ctx.send(file=get_current_figure_as_file())


def setup(bot):
    bot.add_cog(Codeforces(bot))
