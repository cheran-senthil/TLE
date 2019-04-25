import bisect
import datetime
import io
import time
import os
from typing import List

import discord
import pandas.plotting
from discord.ext import commands
from matplotlib import pyplot as plt
from matplotlib import patches as patches
from matplotlib import lines as mlines
import numpy as np

from tle import constants
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common

_ZERO_WIDTH_SPACE = '\u200b'

pandas.plotting.register_matplotlib_converters()


def _get_current_figure_as_file():
    filename = os.path.join(constants.FILEDIR, f'tempplot_{time.time()}.png')
    plt.savefig(filename, facecolor=plt.gca().get_facecolor(), bbox_inches='tight', pad_inches=0.25)

    with open(filename, 'rb') as file:
        discord_file = discord.File(io.BytesIO(file.read()), filename='plot.png')

    os.remove(filename)
    return discord_file


def _plot_rating_bg():
    ymin, ymax = plt.gca().get_ylim()
    bgcolor = plt.gca().get_facecolor()
    for rank in cf.RATED_RANKS:
        plt.axhspan(rank.low, rank.high, facecolor=rank.color_graph, alpha=0.8, edgecolor=bgcolor, linewidth=0.5)

    plt.gcf().autofmt_xdate()
    locs, labels = plt.xticks()
    for loc in locs:
        plt.axvline(loc, color=bgcolor, linewidth=0.5)
    plt.ylim(ymin, ymax)


def _plot_rating(resp, mark='o', labels: List[str] = None):
    labels = [''] * len(resp) if labels is None else labels
    for rating_changes, label in zip(resp, labels):
        ratings, times = [], []
        for rating_change in rating_changes:
            ratings.append(rating_change.newRating)
            times.append(datetime.datetime.fromtimestamp(rating_change.ratingUpdateTimeSeconds))

        plt.plot(times,
                 ratings,
                 linestyle='-',
                 marker=mark,
                 markersize=3,
                 markerfacecolor='white',
                 markeredgewidth=0.5,
                 label=label)

    _plot_rating_bg()


def _classify_subs(submissions, contests):
    submissions.sort(key=lambda s: s.creationTimeSeconds)
    contest_id_map = {contest.id: contest for contest in contests}
    regular, practice, virtual = {}, {}, {}
    for submission in submissions:
        if submission.verdict != 'OK':
            continue
        problem = submission.problem
        submission_time = datetime.datetime.fromtimestamp(submission.creationTimeSeconds)
        contest = contest_id_map.get(problem.contestId)
        if submission_time and problem.rating and contest:
            contest_type = submission.author.participantType
            entry = (submission_time, problem.rating)
            problem_key = (problem.name, contest.startTimeSeconds)
            if problem_key in practice or problem_key in virtual or problem_key in regular:
                continue
            if contest_type == 'PRACTICE':
                practice[problem_key] = entry
            elif contest_type == 'VIRTUAL':
                virtual[problem_key] = entry
            else:
                regular[problem_key] = entry
    return list(regular.values()), list(practice.values()), list(virtual.values())


def _plot_scatter(regular, practice, virtual):
    for contest in [practice, regular, virtual]:
        if contest:
            times, ratings = zip(*contest)
            plt.scatter(times, ratings, zorder=10, s=3, alpha=0.5)


def _running_mean(x, bin_size):
    n = len(x)

    cum_sum = [0] * (n + 1)
    for i in range(n):
        cum_sum[i + 1] = x[i] + cum_sum[i]

    res = [0] * (n - bin_size + 1)
    for i in range(bin_size, n + 1):
        res[i - bin_size] = (cum_sum[i] - cum_sum[i - bin_size]) / bin_size

    return res


def _plot_average(practice, bin_size, label: str = ''):
    if len(practice) > bin_size:
        sub_times, ratings = map(list, zip(*practice))

        sub_timestamps = [sub_time.timestamp() for sub_time in sub_times]
        mean_sub_timestamps = _running_mean(sub_timestamps, bin_size)
        mean_sub_times = [datetime.datetime.fromtimestamp(timestamp) for timestamp in mean_sub_timestamps]
        mean_ratings = _running_mean(ratings, bin_size)

        plt.plot(mean_sub_times,
                 mean_ratings,
                 linestyle='-',
                 marker='',
                 markerfacecolor='white',
                 markeredgewidth=0.5,
                 label=label)


class Graphs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()

    @commands.group(brief='Graphs for analyzing Codeforces activity',
                    invoke_without_command=True)
    async def plot(self, ctx):
        """Plot various graphs. Wherever Codeforces handles are accepted it is possible to
        use a server member's name instead by prefixing it with '!'."""
        await ctx.send_help('plot')

    @plot.command(brief='Plot Codeforces rating graph')
    async def rating(self, ctx, *handles: str):
        """Plots Codeforces rating graph for the handles provided."""
        handles = handles or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles(ctx, self.converter, handles)
        resp = await cf_common.run_handle_related_coro(handles, cf.user.rating)

        plt.clf()
        _plot_rating(resp)
        current_ratings = [rating_changes[-1].newRating if rating_changes else 'Unrated' for rating_changes in resp]
        labels = [f'{_ZERO_WIDTH_SPACE}{handle} ({rating})' for handle, rating in zip(handles, current_ratings)]
        plt.legend(labels, loc='upper left')

        discord_file = _get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title='Rating graph on Codeforces')
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send(embed=embed, file=discord_file)

    @plot.command(brief='Show histogram of solved problems on CF.')
    async def solved(self, ctx, *handles: str):
        """Shows a histogram of problems solved on Codeforces for the handles provided."""
        handles = handles or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles(ctx, self.converter, handles)
        resp = await cf_common.run_handle_related_coro(handles, cf.user.status)

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
        labels = [f'{_ZERO_WIDTH_SPACE}{handle}: {len(ratings)}' for handle, ratings in zip(handles, allratings)]

        plt.clf()
        plt.hist(allratings, bins=hist_bins, label=labels)
        plt.xlabel('Problem rating')
        plt.ylabel('Number solved')
        plt.legend(loc='upper right')

        discord_file = _get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title='Histogram of problems solved on Codeforces')
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send(embed=embed, file=discord_file)

    @plot.command(brief='Show history of problems solved by rating.',
                  aliases=['chilli'])
    async def scatter(self, ctx, handle: str = None, bin_size: int = 10):
        """Plot Codeforces rating overlaid on a scatter plot of problems solved.
        Also plots a running average of ratings of problems solved in practice."""
        if bin_size < 1:
            await ctx.send(embed=discord_common.embed_alert('Moving average window size must be at least 1'))
            return

        handle = handle or '!' + str(ctx.author)
        handles = await cf_common.resolve_handles(ctx, self.converter, (handle,))
        resp = await cf_common.run_handle_related_coro(handles, cf.user.status)
        rating_resp = await cf_common.run_handle_related_coro(handles, cf.user.rating)
        contests = await cf.contest.list()
        handle = handles[0]
        submissions = resp[0]

        regular, practice, virtual = _classify_subs(submissions, contests)
        plt.clf()
        _plot_scatter(regular, practice, virtual)
        labels = ['Practice', 'Regular', 'Virtual']
        plt.legend(labels, loc='upper left')
        _plot_average(practice, bin_size)
        _plot_rating(rating_resp, mark='')

        discord_file = _get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title=f'Rating vs solved problem rating for {handle}')
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send(embed=embed, file=discord_file)

    @plot.command(brief='Show server rating distribution')
    async def distrib(self, ctx):
        """Plots rating distribution of server members."""
        res = cf_common.conn.getallhandleswithrating()
        ratings = [rating for _, _, rating in res]
        bin_count = min(len(ratings), 30)

        plt.clf()
        plt.hist(ratings, bins=bin_count)
        plt.xlabel('Rating')
        plt.ylabel('Number of users')

        discord_file = _get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title=f'Rating distribution of server members')
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send(embed=embed, file=discord_file)

    @plot.command(brief='Show percentile distribution on codeforces', usage='[+zoom] [handles...]')
    async def centile(self, ctx, *args: str):
        """Show percentile distribution of codeforces and mark given handles in the plot. If +zoom and handles are given, it zooms to the neighborhood of the handles."""

        # Handle args
        args = list(args)
        if '+zoom' in args:
            zoom = True
            args.remove('+zoom')
        else:
            zoom = False

        # Prepare data
        rating_map = await cf_common.cache.get_user_rating(600)
        if args:
            handles = await cf_common.resolve_handles(ctx,
                                                      self.converter,
                                                      args,
                                                      mincnt=0,
                                                      maxcnt=50)
            handles = set(handles)
        else:
            handles = set()

        intervals = [(rank.low, rank.high) for rank in cf.RATED_RANKS]
        colors = [rank.color_graph for rank in cf.RATED_RANKS]

        ratings = np.array(sorted(rating_map.values()))
        n = len(ratings)
        perc = 100*np.arange(n)/n

        # Plot
        plt.clf()
        fig,ax = plt.subplots(1)
        ax.plot(ratings, perc, color='#00000099')

        plt.xlabel('Rating')
        plt.ylabel('Percentile')

        for pos in ['right','top','bottom','left']:
            ax.spines[pos].set_visible(False)
        ax.tick_params(axis='both', which='both',length=0)

        # Color intervals by rank
        for interval,color in zip(intervals,colors):
            alpha = '99'
            l,r = interval
            col = color + alpha
            rect = patches.Rectangle((l,-50), r-l, 200,
                                     edgecolor='none',
                                     facecolor=col)
            ax.add_patch(rect)

        # Mark users in plot
        failed = []
        to_mark = {}
        for user in handles:
            if user in rating_map:
                rating = rating_map[user]
                ix = bisect.bisect_left(ratings, rating)
                cent = 100*ix/len(ratings)
                to_mark[user] = rating,cent
            else:
                failed.append(user)
        for user,point in to_mark.items():
            x,y = point
            plt.annotate(user,
                         xy=point,
                         xytext=(0, 0),
                         textcoords='offset points',
                         ha='right',
                         va='bottom')
            plt.plot(*point,
                     marker='o',
                     markersize=5,
                     color='red',
                     markeredgecolor='darkred')

        # Set limits (before drawing tick lines)
        if handles and zoom:
            xmargin = 50
            ymargin = 5
            xmin = min(point[0] for point in to_mark.values())
            xmax = max(point[0] for point in to_mark.values())
            ymin = min(point[1] for point in to_mark.values())
            ymax = max(point[1] for point in to_mark.values())
            plt.xlim(xmin - xmargin, xmax + xmargin)
            plt.ylim(ymin - ymargin, ymax + ymargin)
        else:
            plt.xlim(ratings[0], ratings[-1])
            plt.ylim(-1.5, 101.5)

        # Draw tick lines
        linecolor = '#00000022'
        for y in ax.get_yticks():
            l = mlines.Line2D([ratings[0],ratings[-1]], [y,y], color=linecolor)
            ax.add_line(l)
        for x in ax.get_xticks():
            l = mlines.Line2D([x,x], [-10,110], color=linecolor)
            ax.add_line(l)

        # Discord stuff
        discord_file = _get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title=f'Rating/percentile relationship')
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send("Couldn't find ratings for: "+', '.join(failed), embed=embed, file=discord_file)

    @plot.command(brief='Show codeforces rating distribution')
    async def cfdistrib(self, ctx, mode: str = 'log'):
        resp = await cf_common.cache.get_user_rating(3600)
        ratings = [max(r, 0) for r in resp.values()]
        bins = 39

        colors = []
        low, high = 0, 100 * bins
        for rank in cf.RATED_RANKS:
            for r in range(max(rank.low, low), min(rank.high, high), 100):
                colors.append('#' + '%06x' % rank.color_embed)
        assert len(colors) == bins, f'Expected {bins} colors, got {len(colors)}'

        height = [0] * bins
        for r in ratings:
            height[r // 100] += 1

        csum = 0
        cent = []
        users = sum(height)
        for h in height:
            csum += h
            cent.append(round(100 * csum / users))

        x = [k * 100 for k in range(bins)]
        label = [f'{r} ({c})' for r,c in zip(x, cent)]

        plt.clf()
        if mode == 'log':
            fig = plt.figure(figsize=(15, 5))
        elif mode == 'normal':
            fig = plt.figure(figsize=(20,100))
            plt.locator_params(axis='y', nbins=50)
        else:
            await ctx.send(embed=discord_common.embed_alert('Mode should be either `log` or `normal`.'))
            return

        plt.xticks(rotation=45)
        plt.xlim(-50, 100 * bins - 50)
        plt.bar(x, height, 90, color=colors, linewidth=0, tick_label=label, log=(mode == 'log'))
        plt.xlabel('Rating')
        plt.ylabel('Number of users')

        discord_file = _get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title=f'Rating distribution of cf users')
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send(embed=embed, file=discord_file)
        plt.close(fig)

    async def cog_command_error(self, ctx, error):
        await cf_common.cf_handle_error_handler(ctx, error)
        await cf_common.run_handle_coro_error_handler(ctx, error)


def setup(bot):
    bot.add_cog(Graphs(bot))
