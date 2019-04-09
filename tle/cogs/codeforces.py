# import asyncio
import datetime
import io
import json
# import logging
import os
import random
import time
from typing import List

import aiohttp
import discord
from discord.ext import commands
from matplotlib import pyplot as plt

from tle import constants
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common

# suppress pandas warning
from pandas.plotting import register_matplotlib_converters
register_matplotlib_converters()

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


def plot_rating(resp, return_ratings=True, labels: List[str] = None):
    """Returns list of (current) ratings when return_ratings=True"""
    rates = []
    labels = [""] * len(resp) if labels is None else labels
    for rating_changes, label in zip(resp, labels):
        ratings, times = [], []
        for rating_change in rating_changes:
            ratings.append(rating_change.newRating)
            times.append(datetime.datetime.fromtimestamp(rating_change.ratingUpdateTimeSeconds))

        plt.plot(times,
                 ratings,
                 linestyle='-',
                 marker='o',
                 markersize=3,
                 markerfacecolor='white',
                 markeredgewidth=0.5,
                 label=label)
        rates.append(ratings[-1])

    plot_rating_bg()
    return rates if return_ratings else None


def classify_subs(submissions, contests):
    submissions.sort(key=lambda s: s.creationTimeSeconds)
    contests = {contest['id']: contest['startTimeSeconds'] for contest in contests}
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


def plot_average(practice, bin_size, label: str = ""):
    if len(practice) > bin_size:
        times, ratings = map(list, zip(*practice))

        times = [datetime.datetime.timestamp(time) for time in times]
        times = running_mean(times, bin_size)
        ratings = running_mean(ratings, bin_size)
        times = [datetime.datetime.fromtimestamp(time) for time in times]

        plt.plot(times,
                 ratings,
                 linestyle='-',
                 markerfacecolor='white',
                 markeredgewidth=0.5,
                 label=label)


class Codeforces(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()

    @commands.command(brief='update status, mark guild members as active')
    @commands.has_role('Admin')
    async def _updatestatus(self, ctx):
        active_ids = [m.id for m in ctx.guild.members]
        rc = cf_common.conn.update_status(active_ids)
        await ctx.send(f'{rc} members active with handle')

    @commands.command(brief='force cache refresh of contests and problems')
    @commands.has_role('Admin')
    async def _forcecache(self, ctx):
        # TODO: Update user submissions cache or discard caching method entirely.
        await cf_common.cache.force_update()
        await ctx.send('forcecache_: success')

    async def cache_cfuser_subs(self, handle: str):
        info = await cf.user.info(handles=[handle])
        subs = await cf.user.status(handle=handle)
        info = info[0]
        solved = [sub.problem for sub in subs if sub.verdict == 'OK']
        solved = {prob.contest_identifier for prob in solved if prob.has_metadata()}
        solved = json.dumps(list(solved))
        stamp = time.time()
        cf_common.conn.cache_cfuser_full(info + (solved, stamp))
        return stamp, info.rating, solved

    @commands.command(brief='Recommend a problem')
    async def gimme(self, ctx, *args):
        if cf_common.cache.problem_dict is None:
            await cf_common.cache.cache_problems()
        tags = []
        bounds = []
        for arg in args:
            if arg.isdigit(): bounds.append(int(arg))
            else: tags.append(arg)
        handle = cf_common.conn.gethandle(ctx.message.author.id)

        rating, solved = None, None
        if handle:
            rating, solved = await cf_common.cache.get_rating_solved(handle)
        if solved is None:
            solved = set()

        lower = bounds[0] if len(bounds) > 0 else None
        if lower is None:
            lower = round(rating, -2)
            if lower is None:
                await ctx.send('Personal cf data not found. Assume rating of 1500.')
                lower = 1500
        upper = bounds[1] if len(bounds) > 1 else lower + 200
        problems = [prob for prob in cf_common.cache.problem_dict.values()
                    if lower <= prob.rating and prob.name not in solved]
        if tags: problems = [prob for prob in problems if prob.tag_matches(tags)]
        if not problems:
            await ctx.send('Problems not found within the search parameters')
            return
        upper = max(upper, min([prob.rating for prob in problems]))
        problems = [prob for prob in problems if prob.rating <= upper]
        indices = sorted([(cf_common.cache.problem_start[p.contest_identifier], i)
                          for i, p in enumerate(problems)])
        problems = [problems[i] for _, i in indices]
        choice = max([random.randrange(len(problems)) for _ in range(3)])
        problem = problems[choice]

        title = f'{problem.index}. {problem.name}'
        url = f'{cf.CONTEST_BASE_URL}{problem.contestId}/problem/{problem.index}'
        desc = cf_common.cache.contest_dict.get(problem.contestId)
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
        handle = cf_common.conn.gethandle(user_id)
        if not handle:
            await ctx.send('You must link your handle to be able to use this feature.')
            return
        active = cf_common.conn.check_challenge(user_id)
        if active is not None:
            challenge_id, issue_time, name, contest_id, index, c_delta = active
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            await ctx.send(f'You have an active challenge {name} at {url}')
            return
        if cf_common.cache.problem_dict is None:
            await cf_common.cache.cache_problems()
        rating, solved = await cf_common.cache.get_rating_solved(handle, time_out=0)
        if rating is None or solved is None:
            await ctx.send('Cannot pull your data at this time. Try again later.')
            return
        delta = round(delta, -2)
        if delta < -200 or delta > 200:
            await ctx.send('Delta can range from -200 to 200.')
            return
        rating = round(rating, -2)
        problems = [prob for prob in cf_common.cache.problem_dict.values()
                    if prob.rating == rating + delta and prob.name not in solved]
        if not problems:
            await ctx.send('No problem to assign')
            return
        indices = [(cf_common.cache.problem_start[p.contest_identifier], i) for i, p in enumerate(problems)]
        indices.sort()
        problems = [problems[i] for _, i in indices]
        choice = max([random.randrange(len(problems)) for _ in range(3)])
        problem = problems[choice]

        issue_time = datetime.datetime.now().timestamp()

        rc = cf_common.conn.new_challenge(user_id, issue_time, problem, delta)
        if rc != 1:
            # await ctx.send('Error updating the database')
            await ctx.send('Your challenge has already been added to the database!')
            return
        title = f'{problem.index}. {problem.name}'
        url = f'{cf.CONTEST_BASE_URL}{problem.contestId}/problem/{problem.index}'
        desc = cf_common.cache.contest_dict.get(problem.contestId)
        desc = desc.name if desc else 'N/A'
        embed = discord.Embed(title=title, url=url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'Challenge problem for `{handle}`', embed=embed)

    @commands.command(brief='Report challenge completion')
    async def gotgud(self, ctx):
        user_id = ctx.message.author.id
        handle = cf_common.conn.gethandle(user_id)
        if not handle:
            await ctx.send('You must link your handle to be able to use this feature.')
            return
        active = cf_common.conn.check_challenge(user_id)
        if not active:
            await ctx.send(f'You do not have an active challenge')
            return
        _, solved = await cf_common.cache.get_rating_solved(handle, time_out=0)
        if solved is None:
            await ctx.send('Cannot pull your data at this time. Try again later.')
            return
        challenge_id, issue_time, name, contestId, index, delta = active
        if not name in solved:
            await ctx.send('You haven\'t completed your challenge.')
            return
        delta = delta // 100 + 3
        finish_time = int(datetime.datetime.now().timestamp())
        cf_common.conn.complete_challenge(user_id, challenge_id, finish_time, delta)
        await ctx.send(f'Challenge completed. {handle} gained {delta} points.')

    @commands.command(brief='Recommend a contest')
    async def vc(self, ctx, *handles: str):
        """Recommends a contest based on Codeforces rating of the handle provided."""
        handles = handles or ('!' + str(ctx.author),)
        try:
            handles = await cf_common.resolve_handles_or_reply_with_error(ctx, self.converter, handles)
            resp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.status)
        except cf_common.CodeforcesHandleError:
            return

        user_submissions = resp
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

        for subs in user_submissions:
            for sub in subs:
                recommendations.discard(sub.problem.contestId)

        if not recommendations:
            await ctx.send('Unable to recommend a contest')
        else:
            num_contests = len(recommendations)
            choice = max(random.randrange(num_contests), random.randrange(num_contests))
            contest_id = sorted(list(recommendations))[choice]
            # from and count are for ranklist, set to minimum (1) because we only need name
            str_handles = '`, `'.join(handles)
            contest, _, _ = await cf.contest.standings(contestid=contest_id, from_=1, count=1)
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/'

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
        hist_bins = list(range(500, 3800 + step, step))

        # NOTE: matplotlib ignores labels that begin with _
        # https://matplotlib.org/api/pyplot_api.html#matplotlib.pyplot.legend
        # Add zero-width space to work around this
        labels = [f'{zero_width_space}{handle}: {len(ratings)}' for handle, ratings in zip(handles, allratings)]

        plt.clf()
        plt.hist(allratings, bins=hist_bins, label=labels)
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

    @commands.command(brief="Plots average practice problems ratings with contest ratings")
    async def chilli(self, ctx, handle: str = None, bin_size: int = 10):
        if bin_size < 1:
            await ctx.send('Moving average window size must be at least 1.')
            return

        handle = handle or '!' + str(ctx.author)
        try:
            handles = await cf_common.resolve_handles_or_reply_with_error(ctx, self.converter, (handle,))
            status_resp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.status)
            rating_resp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.rating)
            contests = await cf.query_api('contest.list')
        except cf_common.CodeforcesHandleError:
            return

        handle, = handles
        rating_changes, = rating_resp
        if not rating_changes:
            await ctx.send("User is unrated!")
            return
        _, practice, _ = classify_subs(status_resp[0], contests)
        plt.clf()
        plot_average(practice, bin_size, label="practice")
        latest_rating = rating_changes[-1].newRating

        labels = [f'contest ({latest_rating})']
        plot_rating(rating_resp, return_ratings=False, labels=labels)
        plt.legend(loc='upper left')
        plt.gcf().suptitle(f"{handle}'s rating")

        await ctx.send(file=get_current_figure_as_file())

    @commands.command(brief="Show server rating distribution")
    async def distrib(self, ctx):
        res = cf_common.conn.getallhandleswithrating()
        ratings = [rating for _, _, rating in res]
        step = 100
        hist_bins = list(range(500, 3800 + step, step))

        plt.clf()
        plt.hist(ratings, bins=hist_bins)
        plt.title('Server rating distribution')
        plt.xlabel('Rating')
        plt.ylabel('Number of users')
        plt.legend(loc='upper right')
        await ctx.send(file=get_current_figure_as_file())


def setup(bot):
    bot.add_cog(Codeforces(bot))
