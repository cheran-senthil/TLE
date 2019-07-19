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

pandas.plotting.register_matplotlib_converters()


class GraphCogError(commands.CommandError):
    pass


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


def _filter_solved_submissions(submissions, contests):
    """Filters and keeps only solved submissions with problems that have a rating and belong to
    some contest from given contests. If a problem is solved multiple times the first accepted
    submission is kept. The unique id for a problem is (problem name, contest start time).
    """
    submissions.sort(key=lambda sub: sub.creationTimeSeconds)
    contest_id_map = {contest.id: contest for contest in contests}
    problems = set()
    solved_subs = []
    for submission in submissions:
        contest = contest_id_map.get(submission.problem.contestId)
        if submission.verdict == 'OK' and submission.problem.rating and contest:
            # Assume (name, contest start time) is a unique identifier for problems
            problem_key = (submission.problem.name, contest.startTimeSeconds)
            if problem_key not in problems:
                solved_subs.append(submission)
                problems.add(problem_key)
    return solved_subs


def _classify_submissions(submissions):
    solved_by_type = {sub_type: [] for sub_type in cf.Party.PARTICIPANT_TYPES}
    for submission in submissions:
        solved_by_type[submission.author.participantType].append(submission)
    return solved_by_type


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

    @plot.command(brief='Plot Codeforces rating graph', usage='[+zoom] [handles...]')
    async def rating(self, ctx, *args: str):
        """Plots Codeforces rating graph for the handles provided."""
        args = list(args)
        if '+zoom' in args:
            zoom = True
            args.remove('+zoom')
        else:
            zoom = False

        handles = args or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles(ctx, self.converter, handles)
        resp = [await cf.user.rating(handle=handle) for handle in handles]

        if not any(resp):
            handles_str = ', '.join(f'`{handle}`' for handle in handles)
            if len(handles) == 1:
                message = f'User {handles_str} is not rated'
            else:
                message = f'None of the given users {handles_str} are rated'
            raise GraphCogError(message)

        plt.clf()
        _plot_rating(resp)
        current_ratings = [rating_changes[-1].newRating if rating_changes else 'Unrated' for rating_changes in resp]
        labels = [f'\N{ZERO WIDTH SPACE}{handle} ({rating})' for handle, rating in zip(handles, current_ratings)]
        plt.legend(labels, loc='upper left')

        if not zoom:
            min_rating = 1100
            max_rating = 1800
            for rating_changes in resp:
                for rating in rating_changes:
                    min_rating = min(min_rating, rating.newRating)
                    max_rating = max(max_rating, rating.newRating)
            plt.ylim(min_rating - 100, max_rating + 200)

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
        resp = [await cf.user.status(handle=handle) for handle in handles]
        contests = await cf.contest.list()

        all_solved_subs = [_filter_solved_submissions(submissions, contests)
                           for submissions in resp]

        if not any(all_solved_subs):
            handles_str = ', '.join(f'`{handle}`' for handle in handles)
            if len(handles) == 1:
                message = f'User {handles_str} has not solved any rated problem'
            else:
                message = f'None of the users {handles_str} have solved any rated problem'
            raise GraphCogError(message)

        if len(handles) == 1:
            # Display solved problem separately by type for a single user.
            handle, solved_by_type = handles[0], _classify_submissions(all_solved_subs[0])

            types_to_show = ['CONTESTANT', 'OUT_OF_COMPETITION', 'VIRTUAL', 'PRACTICE']
            all_ratings = [[sub.problem.rating for sub in solved_by_type[sub_type]]
                           for sub_type in types_to_show]
            nice_names = ['Contest: {}', 'Unofficial: {}', 'Virtual: {}', 'Practice: {}']
            labels = [name.format(len(ratings)) for name, ratings in zip(nice_names, all_ratings)]
            total = sum(map(len, all_ratings))

            step = 100
            hist_bins = list(range(500, 3800 + step, step))
            plt.clf()
            plt.hist(all_ratings, stacked=True, bins=hist_bins, label=labels)
            plt.xlabel('Problem rating')
            plt.ylabel('Number solved')
            plt.legend(title=f'{handle}: {total}', title_fontsize=plt.rcParams['legend.fontsize'],
                       loc='upper right')

        else:
            all_ratings = [[sub.problem.rating for sub in solved_subs]
                           for solved_subs in all_solved_subs]

            # NOTE: matplotlib ignores labels that begin with _
            # https://matplotlib.org/api/pyplot_api.html#matplotlib.pyplot.legend
            # Add zero-width space to work around this
            labels = [f'\N{ZERO WIDTH SPACE}{handle}: {len(ratings)}'
                      for handle, ratings in zip(handles, all_ratings)]

            step = 200
            hist_bins = list(range(500, 3800 + step, step))
            plt.clf()
            plt.hist(all_ratings, bins=hist_bins, label=labels)
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
            raise GraphCogError('Moving average window size must be at least 1')

        handle = handle or '!' + str(ctx.author)
        handles = await cf_common.resolve_handles(ctx, self.converter, (handle,))
        resp = [await cf.user.status(handle=handle) for handle in handles]
        rating_resp = [await cf.user.rating(handle=handle) for handle in handles]
        contests = await cf.contest.list()
        handle = handles[0]
        submissions = resp[0]

        def extract_time_and_rating(submissions):
            return [(datetime.datetime.fromtimestamp(sub.creationTimeSeconds), sub.problem.rating)
                    for sub in submissions]

        solved_subs = _filter_solved_submissions(submissions, contests)

        if not any(rating_resp) and not any(solved_subs):
            raise GraphCogError(f'User `{handle}` is not rated and has not solved any rated problem')

        solved_by_type = _classify_submissions(solved_subs)
        regular = extract_time_and_rating(solved_by_type['CONTESTANT'] +
                                          solved_by_type['OUT_OF_COMPETITION'])
        practice = extract_time_and_rating(solved_by_type['PRACTICE'])
        virtual = extract_time_and_rating(solved_by_type['VIRTUAL'])

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

    async def _rating_hist(self, ctx, ratings, mode, binsize, title):
        if mode not in ('log', 'normal'):
            raise GraphCogError('Mode should be either `log` or `normal`')
        title += ' (log scale)' if mode == 'log' else ' (normal scale)'

        ratings = [max(r, 0) for r in ratings]

        assert 100%binsize == 0 # because bins is semi-hardcoded
        bins = 39*100//binsize

        colors = []
        low, high = 0, binsize * bins
        for rank in cf.RATED_RANKS:
            for r in range(max(rank.low, low), min(rank.high, high), binsize):
                colors.append('#' + '%06x' % rank.color_embed)
        assert len(colors) == bins, f'Expected {bins} colors, got {len(colors)}'

        height = [0] * bins
        for r in ratings:
            height[r // binsize] += 1

        csum = 0
        cent = []
        users = sum(height)
        for h in height:
            csum += h
            cent.append(round(100 * csum / users))

        x = [k * binsize for k in range(bins)]
        label = [f'{r} ({c})' for r,c in zip(x, cent)]

        l,r = 0,bins-1
        while not height[l]: l += 1
        while not height[r]: r -= 1
        x = x[l:r+1]
        cent = cent[l:r+1]
        label = label[l:r+1]
        colors = colors[l:r+1]
        height = height[l:r+1]

        plt.clf()
        fig = plt.figure(figsize=(15, 5))

        plt.xticks(rotation=45)
        plt.xlim(l * binsize - binsize//2, r * binsize + binsize//2)
        plt.bar(x, height, binsize*0.9, color=colors, linewidth=0, tick_label=label, log=(mode == 'log'))
        plt.xlabel('Rating')
        plt.ylabel('Number of users')

        discord_file = _get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title=title)
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send(embed=embed, file=discord_file)
        plt.close(fig)

    @plot.command(brief='Show rating distribution', usage='[server/cf] [normal/log]')
    async def distrib(self, ctx, subcommand: str = None, mode: str = None):
        """Plots rating distribution of users on Codeforces or in this server, in either
        normal or log scale. Default mode for Codeforces is log and default mode for
        server is normal.
        """
        if subcommand == 'server':
            mode = mode or 'normal'
            res = cf_common.user_db.getallhandleswithrating()
            ratings = [rating for _, _, rating in res if rating]
            await self._rating_hist(ctx,
                                    ratings,
                                    mode,
                                    binsize=100,
                                    title='Rating distribution of server members')
        elif subcommand == 'cf':
            mode = mode or 'log'
            ratings = cf_common.cache2.rating_changes_cache.get_all_ratings()
            await self._rating_hist(ctx,
                                    ratings,
                                    mode,
                                    binsize=100,
                                    title='Rating distribution of Codeforces users')
        else:
            raise GraphCogError('Subcommand should be either `server` or `cf`')

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
        intervals = [(rank.low, rank.high) for rank in cf.RATED_RANKS]
        colors = [rank.color_graph for rank in cf.RATED_RANKS]

        ratings = cf_common.cache2.rating_changes_cache.get_all_ratings()
        ratings = np.array(sorted(ratings))
        n = len(ratings)
        perc = 100*np.arange(n)/n

        if args:
            handles = await cf_common.resolve_handles(ctx,
                                                      self.converter,
                                                      args,
                                                      mincnt=0,
                                                      maxcnt=50)
            infos = await cf.user.info(handles=set(handles))

            users_to_mark = {}
            for info in infos:
                if info.rating is None:
                    raise GraphCogError(f'User `{info.handle}` is not rated')
                ix = bisect.bisect_left(ratings, info.rating)
                cent = 100*ix/len(ratings)
                users_to_mark[info.handle] = info.rating,cent
        else:
            users_to_mark = {}

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
        for user,point in users_to_mark.items():
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
        if users_to_mark and zoom:
            xmargin = 50
            ymargin = 5
            xmin = min(point[0] for point in users_to_mark.values())
            xmax = max(point[0] for point in users_to_mark.values())
            ymin = min(point[1] for point in users_to_mark.values())
            ymax = max(point[1] for point in users_to_mark.values())
            plt.xlim(xmin - xmargin, xmax + xmargin)
            plt.ylim(ymin - ymargin, ymax + ymargin)
        else:
            plt.xlim(ratings[0], ratings[-1])
            plt.ylim(-1.5, 101.5)

        # Draw tick lines
        linecolor = '#00000022'
        inf = 10000
        def horz_line(y):
            l = mlines.Line2D([-inf,inf], [y,y], color=linecolor)
            ax.add_line(l)
        def vert_line(x):
            l = mlines.Line2D([x,x], [-inf,inf], color=linecolor)
            ax.add_line(l)
        for y in ax.get_yticks():
            horz_line(y)
        for x in ax.get_xticks():
            vert_line(x)

        # Discord stuff
        discord_file = _get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title=f'Rating/percentile relationship')
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send(embed=embed, file=discord_file)

    async def cog_command_error(self, ctx, error):
        if isinstance(error, GraphCogError):
            await ctx.send(embed=discord_common.embed_alert(error))
            error.handled = True
            return
        await cf_common.resolve_handle_error_handler(ctx, error)


def setup(bot):
    bot.add_cog(Graphs(bot))
