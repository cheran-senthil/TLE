import datetime
import json
import random
import time

import aiohttp
import discord
from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common


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
    @cf_common.user_guard(group='gitgud')
    async def gimme(self, ctx, *args):
        problem_dict = await cf_common.cache.get_problems(7200)
        tags = []
        bounds = []
        for arg in args:
            if arg.isdigit():
                bounds.append(int(arg))
            else:
                tags.append(arg)
        handle = cf_common.conn.gethandle(ctx.message.author.id)

        rating, solved = None, None
        if handle:
            rating, solved = await cf_common.cache.get_rating_solved(handle, time_out=7200)
        if solved is None:
            solved = set()

        lower = bounds[0] if len(bounds) > 0 else None
        if lower is None:
            lower = rating  # round later. rounding a null value causes exception
            if lower is None:
                await ctx.send('Personal cf data not found. Assume rating of 1500.')
                lower = 1500
            else:
                lower = round(lower, -2)
        upper = bounds[1] if len(bounds) > 1 else lower + 200
        problems = [prob for prob in problem_dict.values()
                    if lower <= prob.rating and prob.name not in solved]
        problems = [prob for prob in problems if not cf_common.is_contest_writer(prob.contestId, handle)]
        if tags: problems = [prob for prob in problems if prob.tag_matches(tags)]
        if not problems:
            await ctx.send('Problems not found within the search parameters')
            return
        upper = max(upper, min([prob.rating for prob in problems]))
        problems = [prob for prob in problems if prob.rating <= upper]
        indices = sorted([(cf_common.cache.problem_start[p.contest_identifier], i)
                          for i, p in enumerate(problems)])
        problems = [problems[i] for _, i in indices]
        choice = max([random.randrange(len(problems)) for _ in range(2)])
        problem = problems[choice]

        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache.contest_dict.get(problem.contestId)
        desc = desc.name if desc else 'N/A'
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        if tags:
            tagslist = ', '.join(problem.tag_matches(tags))
            embed.add_field(name='Matched tags', value=tagslist)
        await ctx.send(f'Recommended problem for `{handle}`', embed=embed)

    @commands.command(brief='Challenge')
    @cf_common.user_guard(group='gitgud')
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
        problem_dict = await cf_common.cache.get_problems(7200)
        rating, solved = await cf_common.cache.get_rating_solved(handle, time_out=0)
        if rating is None or solved is None:
            await ctx.send('Cannot pull your data at this time. Try again later.')
            return
        delta = round(delta, -2)
        if delta < -200 or delta > 200:
            await ctx.send('Delta can range from -200 to 200.')
            return
        rating = round(rating, -2)
        problems = [prob for prob in problem_dict.values()
                    if prob.rating == rating + delta and prob.name not in solved]

        def is_shit(contest):
            shitlist = ['Wild', 'Fools', 'unrated', 'Unrated', 'Surprise', 'Unknown', 'Friday', 'Q#', 'Testing']
            return any(shit in contest.name for shit in shitlist)

        contests = await cf_common.cache.get_contests(60 * 60 * 24)
        problems = [prob for prob in problems if not is_shit(contests[prob.contestId])]
        problems = [prob for prob in problems if not cf_common.is_contest_writer(prob.contestId, handle)]
        if not problems:
            await ctx.send('No problem to assign')
            return
        indices = [(cf_common.cache.problem_start[p.contest_identifier], i) for i, p in enumerate(problems)]
        indices.sort()
        problems = [problems[i] for _, i in indices]
        choice = max([random.randrange(len(problems)) for _ in range(2)])
        problem = problems[choice]

        issue_time = datetime.datetime.now().timestamp()

        rc = cf_common.conn.new_challenge(user_id, issue_time, problem, delta)
        if rc != 1:
            # await ctx.send('Error updating the database')
            await ctx.send('Your challenge has already been added to the database!')
            return
        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache.contest_dict.get(problem.contestId)
        desc = desc.name if desc else 'N/A'
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'Challenge problem for `{handle}`', embed=embed)

    @commands.command(brief='Report challenge completion')
    @cf_common.user_guard(group='gitgud')
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
        rc = cf_common.conn.complete_challenge(user_id, challenge_id, finish_time, delta)
        if rc == 1:
            await ctx.send(f'Challenge completed. {handle} gained {delta} points.')
        else:
            await ctx.send('You have already claimed your points')

    @commands.command(brief='Skip challenge')
    @cf_common.user_guard(group='gitgud')
    async def nogud(self, ctx):
        user_id = ctx.message.author.id
        handle = cf_common.conn.gethandle(user_id)
        if not handle:
            await ctx.send('You must link your handle to be able to use this feature.')
            return
        active = cf_common.conn.check_challenge(user_id)
        if not active:
            await ctx.send(f'You do not have an active challenge')
            return
        challenge_id, issue_time, name, contestId, index, delta = active
        finish_time = int(datetime.datetime.now().timestamp())
        if finish_time - issue_time < 10800:
            await ctx.send(f'You can\'t skip your challenge yet. Think more.')
            return
        cf_common.conn.skip_challenge(user_id, challenge_id)
        await ctx.send(f'Challenge skipped.')

    @commands.command(brief='Force skip a challenge')
    @cf_common.user_guard(group='gitgud')
    @commands.has_role('Admin')
    async def _nogud(self, ctx, user: str):
        rc = cf_common.conn.force_skip_challenge(user)
        if rc == 1:
            await ctx.send(f'Challenge skip forced.')
        else:
            await ctx.send(f'Failed to force challenge skip.')

    @commands.command(brief='Recommend a contest')
    async def vc(self, ctx, *handles: str):
        """Recommends a contest based on Codeforces rating of the handle provided."""
        handles = handles or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles_or_reply_with_error(ctx, self.converter, handles)
        resp = await cf_common.run_handle_related_coro_or_reply_with_error(ctx, handles, cf.user.status)

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
            embed = discord.Embed(title=contest.name, url=contest.url)
            await ctx.send(f'Recommended contest for `{str_handles}`', embed=embed)

    async def cog_command_error(self, ctx, error):
        await cf_common.cf_handle_error_handler(ctx, error)
        await cf_common.run_handle_coro_error_handler(ctx, error)


def setup(bot):
    bot.add_cog(Codeforces(bot))
