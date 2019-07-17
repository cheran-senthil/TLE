import datetime
import random

import discord
from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common

_GITGUD_NO_SKIP_TIME = 3 * 60 * 60


class Codeforces(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()

    @commands.command(brief='update status, mark guild members as active')
    @commands.has_role('Admin')
    async def _updatestatus(self, ctx):
        active_ids = [m.id for m in ctx.guild.members]
        rc = cf_common.user_db.update_status(active_ids)
        await ctx.send(f'{rc} members active with handle')

    async def _gitgud(self, ctx, handle, problem, delta):
        user_id = ctx.message.author.id
        active = cf_common.user_db.check_challenge(user_id)
        if active is not None:
            challenge_id, issue_time, name, contest_id, index, c_delta = active
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            await ctx.send(f'You have an active challenge {name} at {url}')
            return

        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.new_challenge(user_id, issue_time, problem, delta)
        if rc != 1:
            await ctx.send('Your challenge has already been added to the database!')
            return

        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache2.contest_cache.get_contest(problem.contestId).name
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'Challenge problem for `{handle}`', embed=embed)

    @commands.command(brief='Upsolve a problem')
    @cf_common.user_guard(group='gitgud')
    async def upsolve(self, ctx, choice: int = -1):
        """Request an unsolved problem from a contest you participated in
        delta  | -300 | -200 | -100 |  0  | +100 | +200 | +300
        points |   2  |   3  |   5  |  8  |  12  |  17  |  23
        """
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        user = cf_common.user_db.fetch_cfuser(handle)
        rating = round(user.rating, -2)
        resp = await cf.user.rating(handle=handle)
        contests = {change.contestId for change in resp}
        submissions = await cf.user.status(handle=handle)
        solved = {sub.problem.name for sub in submissions if sub.verdict == 'OK'}
        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if prob.name not in solved and prob.contestId in contests
                    and abs(rating - prob.rating) <= 300]

        if not problems:
            await ctx.send('Problems not found within the search parameters')
            return

        problems.sort(key=lambda problem: problem.rating)
        if choice > 0 and choice <= len(problems):
            problem = problems[choice - 1]
            await self._gitgud(ctx, handle, problem, abs(rating - problem.rating))
        else:
            msg = '\n'.join(f'{i + 1}: [{prob.name}]({prob.url}) [{prob.rating}]'
                            for i, prob in enumerate(problems[:5]))
            title = f'Select a problem to upsolve (1-{len(problems)}):'
            embed = discord_common.cf_color_embed(title=title, description=msg)
            await ctx.send(embed=embed)

    @commands.command(brief='Recommend a problem',
                      usage='[tags...] [lower] [upper]')
    @cf_common.user_guard(group='gitgud')
    async def gimme(self, ctx, *args):
        tags = []
        bounds = []
        for arg in args:
            if arg.isdigit():
                bounds.append(int(arg))
            else:
                tags.append(arg)

        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        user = cf_common.user_db.fetch_cfuser(handle)
        rating = user.rating
        submissions = await cf.user.status(handle=handle)
        solved = {sub.problem.name for sub in submissions if sub.verdict == 'OK'}

        lower = bounds[0] if len(bounds) > 0 else None
        if lower is None:
            lower = rating  # round later. rounding a null value causes exception
            if lower is None:
                await ctx.send('Personal cf data not found. Assume rating of 1500.')
                lower = 1500
            else:
                lower = round(lower, -2)
        upper = bounds[1] if len(bounds) > 1 else lower + 200
        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if lower <= prob.rating and prob.name not in solved]
        problems = [prob for prob in problems if not cf_common.is_contest_writer(prob.contestId, handle)]
        if tags: problems = [prob for prob in problems if prob.tag_matches(tags)]
        if not problems:
            await ctx.send('Problems not found within the search parameters')
            return
        upper = max(upper, min([prob.rating for prob in problems]))
        problems = [prob for prob in problems if prob.rating <= upper]
        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds)

        choice = max([random.randrange(len(problems)) for _ in range(2)])
        problem = problems[choice]

        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache2.contest_cache.get_contest(problem.contestId).name
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        if tags:
            tagslist = ', '.join(problem.tag_matches(tags))
            embed.add_field(name='Matched tags', value=tagslist)
        await ctx.send(f'Recommended problem for `{handle}`', embed=embed)

    @commands.command(brief='Print recently solved practice problems by user')
    async def stalk(self, ctx, handle: str):
        handle = handle or '!' + str(ctx.author)
        handle, = await cf_common.resolve_handles(ctx, self.converter, (handle,))
        user = cf_common.user_db.fetch_cfuser(handle)
        submissions = await cf.user.status(handle=handle)
        submissions = list({sub.problem.name : sub for sub in submissions
                            if sub.author.participantType == 'PRACTICE'
                            and sub.verdict == 'OK'}.values())
        submissions.sort(key=lambda sub: sub.creationTimeSeconds, reverse=True)
        problems = [sub.problem for sub in submissions]

        msg = '\n'.join(
            f'{prob.name} [{prob.rating if prob.rating else "?"}] - <{prob.url}>'
            for prob in problems[:5])
        await ctx.send(msg)

    @commands.command(brief='Challenge')
    @cf_common.user_guard(group='gitgud')
    async def gitgud(self, ctx, delta: int = 0):
        """Request a problem for gitgud points.
        delta  | -300 | -200 | -100 |  0  | +100 | +200 | +300
        points |   2  |   3  |   5  |  8  |  12  |  17  |  23
        """
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        user = cf_common.user_db.fetch_cfuser(handle)
        rating = round(user.rating, -2)
        submissions = await cf.user.status(handle=handle)
        solved = {sub.problem.name for sub in submissions}

        delta = round(delta, -2)
        if delta < -300 or delta > 300:
            await ctx.send('Delta can range from -300 to 300.')
            return

        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if prob.rating == rating + delta and prob.name not in solved]

        def check(problem):
            contest = cf_common.cache2.contest_cache.get_contest(problem.contestId)
            return (not cf_common.is_nonstandard_contest(contest) and
                    not cf_common.is_contest_writer(problem.contestId, handle))

        problems = list(filter(check, problems))
        if not problems:
            await ctx.send('No problem to assign')
            return

        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds)

        choice = max([random.randrange(len(problems)) for _ in range(2)])
        await self._gitgud(ctx, handle, problems[choice], delta)

    @commands.command(brief='Report challenge completion')
    @cf_common.user_guard(group='gitgud')
    async def gotgud(self, ctx):
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        user_id = ctx.message.author.id
        active = cf_common.user_db.check_challenge(user_id)
        if not active:
            await ctx.send(f'You do not have an active challenge')
            return

        submissions = await cf.user.status(handle=handle)
        solved = {sub.problem.name for sub in submissions if sub.verdict == 'OK'}

        challenge_id, issue_time, name, contestId, index, delta = active
        if not name in solved:
            await ctx.send('You haven\'t completed your challenge.')
            return

        def pretty_time_delta(seconds):
            seconds = int(seconds)
            days, seconds = divmod(seconds, 86400)
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)

            timespec = [
                (days, 'day', 'days'),
                (hours, 'hour', 'hours'),
                (minutes, 'minute', 'minutes'),
            ]
            return ' '.join(f'{count} {singular if count == 1 else plural}'
                            for count, singular, plural in timespec)

        score_distrib = [2, 3, 5, 8, 12, 17, 23]
        delta = score_distrib[delta // 100 + 3]
        finish_time = int(datetime.datetime.now().timestamp())
        rc = cf_common.user_db.complete_challenge(user_id, challenge_id, finish_time, delta)
        if rc == 1:
            duration = pretty_time_delta(finish_time - issue_time)
            await ctx.send(f'Challenge completed in {duration}. {handle} gained {delta} points.')
        else:
            await ctx.send('You have already claimed your points')

    @commands.command(brief='Skip challenge')
    @cf_common.user_guard(group='gitgud')
    async def nogud(self, ctx):
        await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        user_id = ctx.message.author.id
        active = cf_common.user_db.check_challenge(user_id)
        if not active:
            await ctx.send(f'You do not have an active challenge')
            return
        challenge_id, issue_time, name, contestId, index, delta = active
        finish_time = int(datetime.datetime.now().timestamp())
        if finish_time - issue_time < _GITGUD_NO_SKIP_TIME:
            skip_time = (int(issue_time) + _GITGUD_NO_SKIP_TIME - finish_time) // 60
            await ctx.send(f'Think more. You can skip your challenge in {skip_time} minutes.')
            return
        cf_common.user_db.skip_challenge(user_id, challenge_id)
        await ctx.send(f'Challenge skipped.')

    @commands.command(brief='Force skip a challenge')
    @cf_common.user_guard(group='gitgud')
    @commands.has_role('Admin')
    async def _nogud(self, ctx, user: str):
        rc = cf_common.user_db.force_skip_challenge(user)
        if rc == 1:
            await ctx.send(f'Challenge skip forced.')
        else:
            await ctx.send(f'Failed to force challenge skip.')

    @commands.command(brief='Recommend a contest')
    async def vc(self, ctx, *handles: str):
        """Recommends a contest based on Codeforces rating of the handle provided."""
        handles = handles or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles(ctx, self.converter, handles)
        resp = [await cf.user.status(handle=handle) for handle in handles]

        user_submissions = resp
        try:
            info = await cf.user.info(handles=handles)
            contests = await cf.contest.list()
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
            contest, _, _ = await cf.contest.standings(contest_id=contest_id, from_=1, count=1)
            embed = discord.Embed(title=contest.name, url=contest.url)
            await ctx.send(f'Recommended contest for `{str_handles}`', embed=embed)

    async def cog_command_error(self, ctx, error):
        await cf_common.resolve_handle_error_handler(ctx, error)


def setup(bot):
    bot.add_cog(Codeforces(bot))
