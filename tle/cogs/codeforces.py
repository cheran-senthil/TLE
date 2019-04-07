import asyncio
import datetime
import io
import json
import logging
import os
import random
import time
from bisect import bisect_left
from functools import lru_cache

import aiohttp
import discord
from discord.ext import commands
from matplotlib import pyplot as plt

from tle import constants
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import handle_conn

zero_width_space = '\u200b'

def get_current_figure_as_file():
    filename = os.path.join(constants.FILEDIR, 'tempplot_{time.time()}.png')
    plt.savefig(filename, facecolor=plt.gca().get_facecolor(), bbox_inches='tight', pad_inches=0.25)

    with open(filename, 'rb') as file:
        discord_file = discord.File(io.BytesIO(file.read()), filename='plot.png')

    os.remove(filename)
    return discord_file


def plot_rating_bg():
    ymin, ymax = plt.gca().get_ylim()
    bgcolor = plt.gca().get_facecolor()
    for low, high, color, _ in cf.RankHelper.rank_info:
        plt.axhspan(low, high, facecolor=color, alpha=0.8, edgecolor=bgcolor, linewidth=0.5)

    plt.gcf().autofmt_xdate()
    locs, labels = plt.xticks()
    for loc in locs:
        plt.axvline(loc, color=bgcolor, linewidth=0.5)
    plt.ylim(ymin, ymax)


def plot_rating(resp):
    rate = []
    for rating_changes in resp:
        ratings, times = [], []
        for rating_change in rating_changes:
            ratings.append(rating_change.newRating)
            times.append(datetime.datetime.fromtimestamp(rating_change.ratingUpdateTimeSeconds))

        plt.plot(
            times, ratings, linestyle='-', marker='o', markersize=3, markerfacecolor='white', markeredgewidth=0.5)
        rate.append(ratings[-1])

    plot_rating_bg()
    return rate


def classify_subs(submissions, contests):
    submissions.sort(key=lambda s: s.creationTimeSeconds)
    contests = {contest['id']:contest['startTimeSeconds'] for contest in contests}
    regular, practice, virtual = {}, {}, {}
    for submission in submissions:
        if submission.verdict == 'OK':
            rating = submission.problem.rating
            time = submission.creationTimeSeconds
            if rating and time:
                contest_type = submission.author.participantType
                entry = [datetime.datetime.fromtimestamp(time), rating]
                prob = (submission.problem.name, contests[submission.problem.contestId])
                if prob in practice or prob in virtual or prob in regular:
                    continue
                if contest_type == 'PRACTICE':
                    practice[prob] = entry
                elif contest_type == 'VIRTUAL':
                    virtual[prob] = entry
                else:
                    regular[prob] = entry
    return regular.values(), practice.values(), virtual.values()


def plot_scatter(regular, practice, virtual):
    for contest in [regular, practice, virtual]:
        if contest:
            times, ratings = zip(*contest)
            plt.scatter(times, ratings, zorder=10, s=3)
        else:
            plt.scatter([], [], zorder=10, s=3)


def running_mean(x, bin_size=1):
    n = len(x)

    cum_sum = [0] * (n + 1)
    for i in range(n):
        cum_sum[i + 1] = x[i] + cum_sum[i]

    res = [0] * (n - bin_size + 1)
    for i in range(bin_size, n + 1):
        res[i - bin_size] = (cum_sum[i] - cum_sum[i - bin_size]) / bin_size

    return res


def plot_average(practice, bin_size):
    if len(practice) > bin_size:
        times, ratings = map(list, zip(*practice))

        times = [datetime.datetime.timestamp(time) for time in times]
        times = running_mean(times, bin_size)
        ratings = running_mean(ratings, bin_size)
        times = [datetime.datetime.fromtimestamp(time) for time in times]

        plt.plot(times, ratings, linestyle='-', markerfacecolor='white', markeredgewidth=0.5)


class Codeforces(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()
        self.problems = None
        self.problem_ratings = None  # for binary search
        self.contest_names = {}

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self._cache_data())
        logging.info('warming up cache...')

    async def regular_cache(self, interval, handle_interval=None):
        await self.cache_problems()
        handles = handle_conn.conn.getallhandles()
        logging.info(f'{len(handles)} handles active')
        if handles:
            iv = handle_interval or interval / len(handles)
            for _, h in handles:
                await self.cache_cfuser_subs(h)
                await asyncio.sleep(iv)
        else:
            await asyncio.sleep(interval)

    async def _cache_data(self):
        await self.regular_cache(1, 5)
        logging.info('initial cache complete. entering regular cache schedule...')
        three_hours = 10800  # seconds
        await asyncio.sleep(three_hours // 2)
        while True:
            await self.regular_cache(three_hours)
            await self.cache_problems()

    @commands.command(brief='update status')
    @commands.has_role('Admin')
    async def updatestatus_(self, ctx):
        active_ids = [m.id for m in ctx.guild.members]
        rc = handle_conn.conn.update_status(active_ids)
        await ctx.send(f'{rc} members active with handle')

    @commands.command(brief='clear cache (admin-only)', hidden=True)
    @commands.has_role('Admin')
    async def clearcache_(self, ctx):
        try:
            handle_conn.conn.clear_cache()
            self.problems = None
            self.problem_ratings = None
            self.contest_names = {}
            self.get_cached_user.cache_clear()
            msg = 'clear cache success'
        except Exception as e:
            print(e)
            msg = 'clear cache error'
        await ctx.send(msg)

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
        self.problems = [prob for prob in problems if prob.has_metadata() and not prob.tag_matches(banned_tags)]
        self.problems.sort(key=lambda p: p.rating)
        self.problem_ratings = [p.rating for p in self.problems]

    @commands.command(brief='force cache problems, cf handles, and submissions')
    @commands.has_role('Admin')
    async def forcecache_(self, ctx):
        await self.updatestatus_(ctx)
        await self.regular_cache(1, 5)
        await ctx.send('forcecache_: success')

    async def cache_cfuser_subs(self, handle: str):
        info = await cf.user.info(handles=[handle])
        subs = await cf.user.status(handle=handle)
        info = info[0]
        solved = [sub.problem for sub in subs if sub.verdict == 'OK']
        solved = {prob.contest_identifier for prob in solved if prob.has_metadata()}
        solved = json.dumps(list(solved))
        stamp = time.time()
        handle_conn.conn.cache_cfuser_full((handle, info.rating, info.titlePhoto, solved, stamp))
        return stamp, info.rating, solved

    @lru_cache(maxsize=15)
    def get_cached_user(self, handle: str):
        res = handle_conn.conn.fetch_cfuser_custom(handle, ['rating', 'solved', 'lastCached'])
        if res:  # cache found in database
            return [res[2], res[0], (set(json.loads(res[1])) if res[1] else None)]
        return [None, None, None]

    @commands.command(brief='Recommend a problem. Use "any" to not filter by tags')
    async def gitgud(self, ctx, tags: str = 'any', lower_bound: int = None, upper_bound: int = None):
        """Recommends a Codeforces problem.
        A space separated string of tags is supported. If the tag "any" is present tags will be ignored.
        Tags will match if they appear as substring in the problem tags.
        Lower bound defaults to the invoker's user rating. Upper bound defaults to lower bound + 300."""
        handle = handle_conn.conn.gethandle(ctx.message.author.id)
        rating, solved = None, None
        if handle:
            res = self.get_cached_user(handle)
            stamp, rating, solved = res
            if not all(res) or time.time() - stamp > 3600:
                try:
                    stamp, rating, solved = await self.cache_cfuser_subs(handle)
                    res[:] = stamp, rating, solved  # need to slice [:] for &ref
                except Exception as e:
                    print(e)
                    pass

        # 1500 is default lower_bound for unrated user
        # changed this back to if None because 0 -> False (try gitgud all 0 800)
        if lower_bound is None:
            lower_bound = rating
            if lower_bound is None:
                await ctx.send('Personal cf data not found. Assume rating of 1500.')
                lower_bound = 1500
        lower_bound = round(lower_bound, -2)
        upper_bound = upper_bound or lower_bound + 300

        if not self.problems:  # Try once
            await self.cache_problems()
            if not self.problems:  # Could not cache problems
                await ctx.send('Error connecting to Codeforces API')
                return

        begin = bisect_left(self.problem_ratings, lower_bound)
        end = bisect_left(self.problem_ratings, upper_bound + 1, lo=begin)

        problems = self.problems[begin:end]
        tags = tags.lower().split()
        if 'any' not in tags:
            problems = [prob for prob in problems if prob.tag_matches(tags)]
        if solved:
            problems = [prob for prob in problems if prob.contest_identifier not in solved]
        if not problems:
            await ctx.send('Sorry, no problem found. Try changing the search criteria.')
            return

        problems.sort(key=lambda p: p.contestId)
        numproblems = len(problems)
        # Choose problems with largest contestId with greater probability (heuristic for newer problems)
        choice = max(random.randrange(numproblems), random.randrange(numproblems))
        problem = problems[choice]

        title = f'{problem.index}. {problem.name}'
        url = f'{cf.CONTEST_BASE_URL}{problem.contestId}/problem/{problem.index}'
        desc = self.contest_names.get(problem.contestId)
        embed = discord.Embed(title=title, url=url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)

        if 'any' not in tags:
            tagslist = ', '.join(problem.tag_matches(tags))
            embed.add_field(name='Matched tags', value=tagslist)

        await ctx.send(f'Recommended problem for `{handle}`', embed=embed)

    @commands.command(brief='Recommend a contest')
    async def vc(self, ctx, *handles: str):
        """Recommends a contest based on Codeforces rating of the handle provided."""
        handles = handles or ('!' + str(ctx.author),)
        try:
            handles = await cf_common.resolve_handles_or_reply_with_error(ctx, self.converter, handles)
            resp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.status)
        except cf_common.CodeforcesHandleError:
            return

        usubs = resp
        try:
            info = await cf.user.info(handles=handles)
            contests = await cf.contest.list()
        except aiohttp.ClientConnectionError:
            await ctx.send('Error connecting to Codeforces API')
            return
        except cf.CodeforcesApiError:
            await ctx.send('Codeforces API error.')
            return

        # TODO: div1 classification is wrong
        divr = sum([user.rating or 1500 for user in info]) / len(handles)
        divs = 'Div. 3' if divr < 1600 else 'Div. 2' if divr < 2100 else 'Div. 1'
        recommendations = {contest.id for contest in contests if divs in contest.name}

        for subs in usubs:
            for sub in subs:
                recommendations.discard(sub.problem.contestId)

        if not recommendations:
            await ctx.send('Unable to recommend a contest')
        else:
            numcontests = len(recommendations)
            choice = max(random.randrange(numcontests), random.randrange(numcontests))
            contestid = sorted(list(recommendations))[choice]
            # from and count are for ranklist, set to minimum (1) because we only need name
            str_handles = '`, `'.join(handles)
            contest, _, _ = await cf.contest.standings(contestid=contestid, from_=1, count=1)
            url = f'{cf.CONTEST_BASE_URL}{contestid}/'

            await ctx.send(f'Recommended contest for `{str_handles}`', embed=discord.Embed(title=contest.name, url=url))

    @commands.command(brief='Compare epeens.')
    async def rating(self, ctx, *handles: str):
        """Compare epeens."""
        handles = handles or ('!' + str(ctx.author),)
        try:
            handles = await cf_common.resolve_handles_or_reply_with_error(ctx, self.converter, handles)
            resp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.rating)
        except cf_common.CodeforcesHandleError:
            return

        plt.clf()
        rate = plot_rating(resp)
        labels = [f'{zero_width_space}{handle} ({rating})' for handle, rating in zip(handles, rate)]
        plt.legend(labels, loc='upper left')
        plt.title('Rating graph on Codeforces')
        await ctx.send(file=get_current_figure_as_file())

    @commands.command(brief='Show histogram of solved problems on CF.')
    async def solved(self, ctx, *handles: str):
        """Shows a histogram of problems solved on Codeforces for the handles provided."""
        handles = handles or ('!' + str(ctx.author),)
        try:
            handles = await cf_common.resolve_handles_or_reply_with_error(ctx, self.converter, handles)
            resp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.status)
        except cf_common.CodeforcesHandleError:
            return

        allratings = []
        for submissions in resp:
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
        labels = [f'{zero_width_space}{handle}: {len(ratings)}' for handle, ratings in zip(handles, allratings)]

        plt.clf()
        plt.hist(allratings, bins=histbins, label=labels)
        plt.title('Histogram of problems solved on Codeforces')
        plt.xlabel('Problem rating')
        plt.ylabel('Number solved')
        plt.legend(loc='upper right')

        await ctx.send(file=get_current_figure_as_file())

    @commands.command(brief='Show history of problems solved by rating.')
    async def scatter(self, ctx, handle: str = None, bin_size: int = 10):
        if bin_size < 1:
            await ctx.send('Moving average window size must be at least 1.')
            return

        handle = handle or '!' + str(ctx.author)
        try:
            handles = await cf_common.resolve_handles_or_reply_with_error(ctx, self.converter, (handle,))
            resp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.status)
            contests = await cf.query_api('contest.list')
            submissions = resp[0]
        except cf_common.CodeforcesHandleError:
            return

        regular, practice, virtual = classify_subs(submissions, contests)
        plt.clf()
        plot_scatter(regular, practice, virtual)
        plt.title('Solved Problem Rating History on Codeforces')
        labels = ['Regular', 'Practice', 'Virtual']
        plt.legend(labels, loc='upper left')
        plot_rating_bg()
        plot_average(practice, bin_size)
        await ctx.send(file=get_current_figure_as_file())

    @commands.command(brief='chilli graph')
    async def chilli(self, ctx, handle: str = None, bin_size: int = 10):
        if bin_size < 1:
            await ctx.send('Moving average window size must be at least 1.')
            return

        handle = handle or '!' + str(ctx.author)
        try:
            handles = await cf_common.resolve_handles_or_reply_with_error(ctx, self.converter, (handle,))
            sresp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.status)
            rresp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.rating)
            contests = await cf.query_api('contest.list')
        except cf_common.CodeforcesHandleError:
            return

        _, practice, _ = classify_subs(sresp[0], contests)
        plt.clf()
        plot_average(practice, bin_size)
        rate = plot_rating(rresp)
        labels = [f'{zero_width_space}{handle} ({rating})' for handle, rating in zip(handles, rate)]
        plt.legend(labels, loc='upper left')
        await ctx.send(file=get_current_figure_as_file())

    @commands.command(brief="Show server rating distribution")
    async def distrib(self, ctx):
        res = handle_conn.conn.getallhandleswithrating()
        ratings = [rating for _, _, rating in res]
        step = 100
        histbins = list(range(500, 3800 + step, step))

        plt.clf()
        plt.hist(ratings, bins=histbins)
        plt.title('Server rating distribution')
        plt.xlabel('Rating')
        plt.ylabel('Number of users')
        plt.legend(loc='upper right')
        await ctx.send(file=get_current_figure_as_file())


def setup(bot):
    bot.add_cog(Codeforces(bot))
