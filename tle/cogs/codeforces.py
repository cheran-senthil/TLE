import datetime
import io
import math
import os
import random
import time

import aiohttp
import discord
from discord.ext import commands
from matplotlib import pyplot as plt
from tle.cogs.util import codeforces_api as cf
from db_utils.handle_conn import HandleConn


class Codeforces(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = HandleConn('handles.db')
        self.converter = commands.MemberConverter()

    async def Resolve(self, ctx, handle: str):
        if handle[0] != '!':
            return handle

        member = await self.converter.convert(ctx, handle[1:])
        res = self.conn.gethandle(member.id)
        if res is None:
            raise Exception('bad')
        return res

    @commands.command(brief='Recommend a problem')
    async def gitgud(self, ctx, handle: str = None, tag: str = 'all', lower_bound: int = None, upper_bound: int = None):
        """Recommends a problem based on Codeforces rating of the handle provided."""
        try:
            handle = await self.Resolve(ctx, handle or '!' + str(ctx.author))
        except:
            await ctx.send('bad handle')
            return

        try:
            probresp = await cf.problemset.problems()
            inforesp = await cf.user.info(handles=[handle])
            subsresp = await cf.user.status(handle=handle, count=10000)
        except aiohttp.ClientConnectionError:
            await ctx.send('Error connecting to Codeforces API')
            return
        except cf.NotFoundError:
            await ctx.send(f'Handle not found: `{handle}`')
            return
        except cf.CodeforcesApiError:
            await ctx.send('Codeforces API denied the request, please make the handle is valid.')
            return

        if lower_bound is None:
            lower_bound = inforesp[0].get('rating')
            if lower_bound is None:
                lower_bound = 1500
            lower_bound = round(lower_bound, -2)
        if upper_bound is None:
            upper_bound = lower_bound + 300

        problems = set()
        for problem in probresp['problems']:
            if ('contestId' in problem) and ('rating' in problem):
                if ('*special' not in problem['tags']) and (tag == 'all' or tag in problem['tags']):
                    if lower_bound <= problem['rating'] <= upper_bound:
                        problems.add((problem['contestId'], problem['index'], problem['name'], problem['rating']))

        for sub in subsresp:
            problem = sub['problem']
            if ('contestId' in problem) and ('rating' in problem) and (sub['verdict'] == 'OK'):
                problems.discard((problem['contestId'], problem['index'], problem['name'], problem['rating']))

        if not problems:
            await ctx.send('{} is already too gud'.format(handle))
        else:
            problems = sorted(problems)
            choice = int(len(problems) * random.random()**0.5)  # prefer newer problems

            contestid, index, name, rating = problems[choice]
            contestresp = await cf.contest.standings(contestid=contestid, from_=1, count=1)
            contestname = contestresp['contest']['name']

            title = f'{index}. {name}'
            url = f'{cf.CONTEST_BASE_URL}{contestid}/problem/{index}'
            desc = f'{contestname}\nRating: {rating}'

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
            probresp = await cf.problemset.problems()
            subsresp = await cf.user.status(handle=handle, count=10000)
        except aiohttp.ClientConnectionError:
            await ctx.send('Error connecting to Codeforces API')
            return
        except cf.NotFoundError:
            await ctx.send(f'Handle not found: `{handle}`')
            return
        except cf.CodeforcesApiError:
            await ctx.send('Codeforces API denied the request, please make the handle is valid.')
            return

        recommendations = set()

        problems = probresp['problems']
        for problem in problems:
            if ('*special' not in problem['tags']) and (problem.get('contestId', 10000) < 10000):
                recommendations.add(problem['contestId'])

        for sub in subsresp:
            if 'rating' in sub['problem']:
                recommendations.discard(problem['contestId'])

        if not recommendations:
            await ctx.send('{} is already too gud'.format(handle))
        else:
            contestid = random.choice(list(recommendations))
            contestresp = await cf.contest.standings(contestid=contestid, from_=1, count=1)
            contestname = contestresp['contest']['name']
            url = f'{cf.CONTEST_BASE_URL}{contestid}/'

            await ctx.send(f'Recommended contest for `{handle}`', embed=discord.Embed(title=contestname, url=url))

    @commands.command(brief='Compare epeens.')
    async def rating(self, ctx, *handles: str):
        """Compare epeens."""
        handles = handles or ('!' + str(ctx.author), )
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

            ratings, times = [], []
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

        bgcolor = plt.gca().get_facecolor()
        for color, lo, hi in colors:
            plt.axhspan(lo, hi, facecolor=color, alpha=0.8, edgecolor=bgcolor, linewidth=0.5)

        plt.ylim(ymin, ymax)
        plt.gcf().autofmt_xdate()
        locs, labels = plt.xticks()

        for loc in locs:
            plt.axvline(loc, color=bgcolor, linewidth=0.5)

        zero_width_space = '\u200b'
        labels = [f'{zero_width_space}{handle} ({rating})' for handle, rating in zip(handles, rate)]
        plt.legend(labels, loc='upper left')
        plt.title('Rating graph on Codeforces')

        discord_file = self.get_current_figure_as_file()
        await ctx.send(file=discord_file)

    @commands.command(brief='Show histogram of solved problems on CF.')
    async def solved(self, ctx, *handles: str):
        """Shows a histogram of problems solved on Codeforces for the handles provided."""
        handles = handles or ('!' + str(ctx.author), )
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
            except cf.CodeforcesApiError:
                await ctx.send('Codeforces API denied the request, please make sure handles are valid.')
                return

            problems = dict()
            for submission in submissions:
                problem = submission['problem']
                if ('rating' in problem) and (submission['verdict'] == 'OK'):
                    problems[(problem['contestId'], problem['index'])] = problem['rating']

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

        discord_file = self.get_current_figure_as_file()
        await ctx.send(file=discord_file)
        
    @commands.command(brief='Show historical geniosity.')
    async def geniosity(self, ctx, handle: str, bin_size: int):
        plt.clf()

        if not bin_size or bin_size <= 0:
            await ctx.send('Moving average window size must be at least 1.')
            return

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
        times = [[], [], []]
        ratings = [[], [], []]
        ts, rs = [], []
        rkey = ['PRACTICE', 'VIRTUAL', 'CONTESTANT']
        for submission in submissions:
            if submission['verdict'] == 'OK':
                problem = submission['problem']
                # CF problems don't have IDs! Just hope (name, rating) pairs don't clash?
                name = problem['name']
                rating = problem.get('rating')
                t = submission['author']['participantType']
                startTimeSeconds = submission.get('creationTimeSeconds')
                if rating:
                    key = 2
                    if t == 'PRACTICE': key = 0
                    elif t == 'VIRTUAL': key = 1
                    times[key].append(datetime.datetime.fromtimestamp(startTimeSeconds))
                    ratings[key].append(rating)
                    ts.append(datetime.datetime.fromtimestamp(startTimeSeconds))
                    rs.append(rating)

        labels = rkey
        for i in range(3):
            plt.scatter(times[i], ratings[i], zorder=10, s = 3)

        ymin, ymax = plt.gca().get_ylim()
        colors = [('#AA0000', 3000, 4000), ('#FF3333', 2600, 3000), ('#FF7777', 2400, 2600), ('#FFBB55', 2300, 2400),
                  ('#FFCC88', 2100, 2300), ('#FF88FF', 1900, 2100), ('#AAAAFF', 1600, 1900), ('#77DDBB', 1400, 1600),
                  ('#77FF77', 1200, 1400), ('#CCCCCC', 0, 1200)]

        plt.title('Solved Problem Rating History on Codeforces')
        plt.xlabel('Date')
        plt.ylabel('Rating')
        labels = ['Practice', 'Virtual', 'Contest']
        plt.legend(labels, loc='upper left')

        for color, lo, hi in colors:
            plt.axhspan(lo, hi, facecolor=color, zorder=1)
        plt.ylim(ymin, ymax)
        plt.gcf().autofmt_xdate()
        locs, labels = plt.xticks()
        for loc in locs:
            plt.axvspan(loc, loc, facecolor='white')
        
        # moving average for loop cancer
        if len(rs) > bin_size:
            avg_ts = []
            avg_rs = []
            cur_t, cur_r = 0, 0
            for i in range(bin_size - 1):
                cur_t += datetime.datetime.timestamp(ts[i])
                cur_r += rs[i]
            for i in range(bin_size - 1, len(rs)):
                cur_t += datetime.datetime.timestamp(ts[i])
                cur_r += rs[i]
                avg_ts.append(datetime.datetime.fromtimestamp(cur_t / bin_size))
                avg_rs.append(cur_r / bin_size)
                cur_t -= datetime.datetime.timestamp(ts[i - bin_size + 1])
                cur_r -= rs[i - bin_size + 1]
            plt.plot(
                avg_ts, avg_rs, linestyle='-', markerfacecolor='white', markeredgewidth=0.5)

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
