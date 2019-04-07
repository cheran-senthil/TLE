import asyncio
import datetime
import io
import json
import logging
import os
import random
import time
from bisect import bisect_left

import aiohttp
import discord
from discord.ext import commands
from matplotlib import pyplot as plt

from tle import constants
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import handle_conn
from tle.util import cache_system

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
        self.cache = cache_system.CacheSystem()

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.schedule_cache())

    async def schedule_cache(self):        
        await self.cache.try_disk()        
        logging.info('data read from disk')
        logging.info(f'updating cache every {constants.CONTEST_CACHE_PERIOD} seconds')
        while True:
            await asyncio.sleep(constants.CONTEST_CACHE_PERIOD)
            await self.cache.cache_contests()
            await self.cache.cache_problems()
            logging.info('scheduled cache complete')
  
    @commands.command(brief='update status')
    @commands.has_role('Admin')
    async def updatestatus_(self, ctx):
        active_ids = [m.id for m in ctx.guild.members]
        rc = handle_conn.conn.update_status(active_ids)
        await ctx.send(f'{rc} members active with handle')

    @commands.command(brief='force cache problems, cf handles, and submissions')
    @commands.has_role('Admin')
    async def forcecache_(self, ctx):
        await self.updatestatus_(ctx)
        await self.cache.force_update()
        await ctx.send('forcecache_: success')

    async def cache_cfuser_subs(self, handle: str):
        info = await cf.user.info(handles=[handle])
        subs = await cf.user.status(handle=handle)
        info = info[0]
        solved = [sub.problem for sub in subs if sub.verdict == 'OK']
        solved = {prob.contest_identifier for prob in solved if prob.has_metadata()}
        solved = json.dumps(list(solved))
        stamp = time.time()
        handle_conn.conn.cache_cfuser_full(info + (solved, stamp))
        return stamp, info.rating, solved

    @commands.command(brief='Recommend a problem')
    async def gimme(self, ctx, *args):
        if self.cache.problem_dict is None:
            await self.cache.cache_problems()
        tags = []
        bounds = []
        for arg in args:
            if arg.isdigit(): bounds.append(int(arg))
            else: tags.append(arg)
        handle = handle_conn.conn.gethandle(ctx.message.author.id)

        rating, solved = None, None
        if handle: rating, solved = await self.cache.get_rating_solved(handle)
        if solved is None: solved = set()

        lower = bounds[0] if len(bounds) > 0 else None
        if lower is None:
            lower = rating
            if lower is None:
                await ctx.send('Personal cf data not found. Assume rating of 1500.')
                lower = 1500
        upper = bounds[1] if len(bounds) > 1 else 5000
        problems = [
            prob for prob in self.cache.problem_dict.values()
            if lower <= prob.rating <= upper and prob.name not in solved
        ]
        if tags: problems = [prob for prob in problems if prob.tag_matches(tags)]
        indices = [((p.rating-lower)//200,
                    -self.cache.problem_start[p.contest_identifier], i)
                    for i, p in enumerate(problems)]
        indices.sort(reverse=True)
        problems = [problems[i] for _, _, i in indices]
        numproblems = len(problems)
        if numproblems == 0:
            await ctx.send('Problems not found within the search parameters')
            return
        choice = max([random.randrange(numproblems) for _ in range(7)])
        problem = problems[choice]

        title = f'{problem.index}. {problem.name}'
        url = f'{cf.CONTEST_BASE_URL}{problem.contestId}/problem/{problem.index}'
        desc = self.cache.contest_dict.get(problem.contestId)
        desc = desc.name if desc else 'N/A'
        embed = discord.Embed(title=title, url=url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        if tags:
            tagslist = ', '.join(problem.tag_matches(tags))
            embed.add_field(name='Matched tags', value=tagslist)
        await ctx.send(f'Recommended problem for `{handle}`', embed=embed)

    @commands.command(brief='Challenge')
    async def gitgud(self, ctx, delta: int = 0):
        user_id = ctx.message.author.id
        handle = handle_conn.conn.gethandle(user_id)
        if not handle:
            await ctx.send('You must link your handle to be able to use this feature.')
            return
        active = handle_conn.conn.check_challenge(user_id)
        if active is not None:
            issue_time, name, contestId, index = active
            url = f'{cf.CONTEST_BASE_URL}{contestId}/problem/{index}'
            await ctx.send(f'You have an active challenge {name} at {url}')
            return
        if self.cache.problem_dict is None:
            await self.cache.cache_problems()
        rating, solved = await self.cache.get_rating_solved(handle, time_out=0)
        if rating is None or solved is None:
            await ctx.send('Cannot pull your data at this time. Try again later.')
            return
        rating = round(rating, -2)
        problems = [
            prob for prob in self.cache.problem_dict.values()
            if prob.rating == rating + delta and prob.name not in solved
        ]
        if not problems:
            await ctx.send('No problem to assign')
            return
        indices = [
            (self.cache.problem_start[p.contest_identifier], i)
            for i, p in enumerate(problems)
        ]
        indices.sort()
        numproblems = len(problems)
        choice = max([random.randrange(numproblems) for _ in range(7)])
        problem = problems[choice]
        
        issue_time = datetime.datetime.now().timestamp()

        rc = handle_conn.conn.new_challenge(user_id, issue_time, problem, delta)
        if rc != 1:
            await ctx.send('Error updating the database')
            return        
        title = f'{problem.index}. {problem.name}'
        url = f'{cf.CONTEST_BASE_URL}{problem.contestId}/problem/{problem.index}'
        desc = self.cache.contest_dict.get(problem.contestId)
        desc = desc.name if desc else 'N/A'
        embed = discord.Embed(title=title, url=url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'Challenge problem for `{handle}`', embed=embed)

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
