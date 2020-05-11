import datetime
import random
from typing import List
import math
import time
from collections import defaultdict

import discord
from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common
from tle.util.db.user_db_conn import Gitgud
from tle.util import paginator
from tle.util import cache_system2


_GITGUD_NO_SKIP_TIME = 3 * 60 * 60
_GITGUD_SCORE_DISTRIB = (2, 3, 5, 8, 12, 17, 23)
_GITGUD_MAX_ABS_DELTA_VALUE = 300


class CodeforcesCogError(commands.CommandError):
    pass


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

    async def _validate_gitgud_status(self, ctx, delta):
        if delta is not None and delta % 100 != 0:
            raise CodeforcesCogError('Delta must be a multiple of 100.')

        if delta is not None and abs(delta) > _GITGUD_MAX_ABS_DELTA_VALUE:
            raise CodeforcesCogError(f'Delta must range from -{_GITGUD_MAX_ABS_DELTA_VALUE} to {_GITGUD_MAX_ABS_DELTA_VALUE}.')

        user_id = ctx.message.author.id
        active = cf_common.user_db.check_challenge(user_id)
        if active is not None:
            _, _, name, contest_id, index, _ = active
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            raise CodeforcesCogError(f'You have an active challenge {name} at {url}')

    async def _gitgud(self, ctx, handle, problem, delta):
        # The caller of this function is responsible for calling `_validate_gitgud_status` first.
        user_id = ctx.author.id

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
        await self._validate_gitgud_status(ctx,delta=None)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        user = cf_common.user_db.fetch_cf_user(handle)
        rating = round(user.effective_rating, -2)
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

        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds, reverse=True)

        if choice > 0 and choice <= len(problems):
            problem = problems[choice - 1]
            await self._gitgud(ctx, handle, problem, problem.rating - rating)
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
        submissions = await cf.user.status(handle=handle)
        solved = {sub.problem.name for sub in submissions if sub.verdict == 'OK'}

        lower = bounds[0] if len(bounds) > 0 else None
        if lower is None:
            user = cf_common.user_db.fetch_cf_user(handle)
            lower = round(user.effective_rating, -2)
        upper = bounds[1] if len(bounds) > 1 else lower + 200
        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if lower <= prob.rating and prob.name not in solved]
        problems = [prob for prob in problems if not cf_common.is_contest_writer(prob.contestId, handle)]
        if tags:
            problems = [prob for prob in problems if prob.tag_matches(tags)]
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

    @commands.command(brief='List solved problems',
                      usage='[handles] [+hardest] [+practice] [+contest] [+virtual] [+outof] [+team] [+tag..] [r>=rating] [r<=rating] [d>=[[dd]mm]yyyy] [d<[[dd]mm]yyyy] [c+marker..] [i+index..]')
    async def stalk(self, ctx, *args):
        """Print problems solved by user sorted by time (default) or rating.
        All submission types are included by default (practice, contest, etc.)
        """
        (hardest,), args = cf_common.filter_flags(args, ['+hardest'])
        filt = cf_common.SubFilter(False)
        args = filt.parse(args)
        handles = args or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles(ctx, self.converter, handles)
        submissions = [await cf.user.status(handle=handle) for handle in handles]
        submissions = [sub for subs in submissions for sub in subs]
        submissions = filt.filter_subs(submissions)

        if not submissions:
            raise CodeforcesCogError('Submissions not found within the search parameters')

        if hardest:
            submissions.sort(key=lambda sub: (sub.problem.rating or 0, sub.creationTimeSeconds), reverse=True)
        else:
            submissions.sort(key=lambda sub: sub.creationTimeSeconds, reverse=True)

        msg = '\n'.join(
            f'[{sub.problem.name}]({sub.problem.url})\N{EN SPACE}'
            f'[{sub.problem.rating if sub.problem.rating else "?"}]\N{EN SPACE}'
            f'({cf_common.days_ago(sub.creationTimeSeconds)})'
            for sub in submissions[:10]
        )
        title = '{} solved problems by `{}`'.format('Hardest' if hardest else 'Recently',
                                                    '`, `'.join(handles))
        embed = discord_common.cf_color_embed(title=title, description=msg)
        await ctx.send(embed=embed)

    @commands.command(brief='Create a mashup', usage='[handles] [+tags]')
    async def mashup(self, ctx, *args):
        """Create a mashup contest using problems within +-100 of average rating of handles provided.
        Add tags with "+" before them.
        """
        handles = [arg for arg in args if arg[0] != '+']
        tags = [arg[1:] for arg in args if arg[0] == '+' and len(arg) > 1]

        handles = handles or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles(ctx, self.converter, handles)
        resp = [await cf.user.status(handle=handle) for handle in handles]
        submissions = [sub for user in resp for sub in user]
        solved = {sub.problem.name for sub in submissions}
        info = await cf.user.info(handles=handles)
        rating = int(round(sum(user.effective_rating for user in info) / len(handles), -2))
        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if abs(prob.rating - rating) <= 100 and prob.name not in solved
                    and not any(cf_common.is_contest_writer(prob.contestId, handle) for handle in handles)
                    and not cf_common.is_nonstandard_problem(prob)]
        if tags:
            problems = [prob for prob in problems if prob.tag_matches(tags)]

        if len(problems) < 4:
            await ctx.send('Problems not found within the search parameters')
            return

        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds)

        choices = []
        for i in range(4):
            k = max(random.randrange(len(problems) - i) for _ in range(2))
            for c in choices:
                if k >= c:
                    k += 1
            choices.append(k)
            choices.sort()

        problems = reversed([problems[k] for k in choices])
        msg = '\n'.join(f'{"ABCD"[i]}: [{p.name}]({p.url}) [{p.rating}]' for i, p in enumerate(problems))
        str_handles = '`, `'.join(handles)
        embed = discord_common.cf_color_embed(description=msg)
        await ctx.send(f'Mashup contest for `{str_handles}`', embed=embed)

    @commands.command(brief='Challenge')
    @cf_common.user_guard(group='gitgud')
    async def gitgud(self, ctx, delta: int = 0):
        """Request a problem for gitgud points.
        delta  | -300 | -200 | -100 |  0  | +100 | +200 | +300
        points |   2  |   3  |   5  |  8  |  12  |  17  |  23
        """
        await self._validate_gitgud_status(ctx, delta)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        user = cf_common.user_db.fetch_cf_user(handle)
        rating = round(user.effective_rating, -2)
        submissions = await cf.user.status(handle=handle)
        solved = {sub.problem.name for sub in submissions}
        noguds = cf_common.user_db.get_noguds(ctx.message.author.id)

        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if (prob.rating == rating + delta and
                        prob.name not in solved and
                        prob.name not in noguds)]

        def check(problem):
            return (not cf_common.is_nonstandard_problem(problem) and
                    not cf_common.is_contest_writer(problem.contestId, handle))

        problems = list(filter(check, problems))
        if not problems:
            await ctx.send('No problem to assign')
            return

        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds)

        choice = max(random.randrange(len(problems)) for _ in range(2))
        await self._gitgud(ctx, handle, problems[choice], delta)

    @commands.command(brief='Print user gitgud history')
    async def gitlog(self, ctx, member: discord.Member = None):
        """Displays the list of gitgud problems issued to the specified member, excluding those noguded by admins.
        If the challenge was completed, time of completion and amount of points gained will also be displayed.
        """
        def make_line(entry):
            issue, finish, name, contest, index, delta, status = entry
            problem = cf_common.cache2.problem_cache.problem_by_name[name]
            line = f'[{name}]({problem.url})\N{EN SPACE}[{problem.rating}]'
            if finish:
                time_str = cf_common.days_ago(finish)
                points = f'{_GITGUD_SCORE_DISTRIB[delta // 100 + 3]:+}'
                line += f'\N{EN SPACE}{time_str}\N{EN SPACE}[{points}]'
            return line

        def make_page(chunk):
            message = f'gitgud log for {member.display_name}'
            log_str = '\n'.join(make_line(entry) for entry in chunk)
            embed = discord_common.cf_color_embed(description=log_str)
            return message, embed

        member = member or ctx.author
        data = cf_common.user_db.gitlog(member.id)
        pages = [make_page(chunk) for chunk in paginator.chunkify(data, 7)]
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=5 * 60, set_pagenum_footers=True)

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

        delta = _GITGUD_SCORE_DISTRIB[delta // 100 + 3]
        finish_time = int(datetime.datetime.now().timestamp())
        rc = cf_common.user_db.complete_challenge(user_id, challenge_id, finish_time, delta)
        if rc == 1:
            duration = cf_common.pretty_time_format(finish_time - issue_time)
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
            skip_time = cf_common.pretty_time_format(issue_time + _GITGUD_NO_SKIP_TIME - finish_time)
            await ctx.send(f'Think more. You can skip your challenge in {skip_time}.')
            return
        cf_common.user_db.skip_challenge(user_id, challenge_id, Gitgud.NOGUD)
        await ctx.send(f'Challenge skipped.')

    @commands.command(brief='Force skip a challenge')
    @cf_common.user_guard(group='gitgud')
    @commands.has_any_role('Admin', 'Moderator')
    async def _nogud(self, ctx, member: discord.Member):
        active = cf_common.user_db.check_challenge(member.id)
        rc = cf_common.user_db.skip_challenge(member.id, active[0], Gitgud.FORCED_NOGUD)
        if rc == 1:
            await ctx.send(f'Challenge skip forced.')
        else:
            await ctx.send(f'Failed to force challenge skip.')

    @commands.command(brief='Recommend a contest', usage='[handles...] [+pattern...]')
    async def vc(self, ctx, *args: str):
        """Recommends a contest based on Codeforces rating of the handle provided.
        e.g ;vc mblazev c1729 +global +hello +goodbye +avito"""
        markers = [x for x in args if x[0] == '+']
        handles = [x for x in args if x[0] != '+'] or ('!' + str(ctx.author),)
        handles = await cf_common.resolve_handles(ctx, self.converter, handles, maxcnt=10)
        user_submissions = [await cf.user.status(handle=handle) for handle in handles]
        info = await cf.user.info(handles=handles)
        contests = cf_common.cache2.contest_cache.get_contests_in_phase('FINISHED')
        problem_to_contests = cf_common.cache2.problemset_cache.problem_to_contests

        if not markers:
            divr = sum(user.effective_rating for user in info) / len(handles)
            div1_indicators = ['div1', 'global', 'avito', 'goodbye', 'hello']
            markers = ['div3'] if divr < 1600 else ['div2'] if divr < 2100 else div1_indicators

        recommendations = {contest.id for contest in contests if
                           contest.matches(markers)
                           and not cf_common.is_nonstandard_contest(contest)
                           and not any(cf_common.is_contest_writer(contest.id, handle)
                                       for handle in handles)}

        # discard contests in which user has non-CE submissions
        for subs in user_submissions:
            for sub in subs:
                if sub.verdict == 'COMPILATION_ERROR':
                    continue

                try:
                    contest = cf_common.cache2.contest_cache.get_contest(sub.problem.contestId)
                    problem_id = (sub.problem.name, contest.startTimeSeconds)
                    for cid in problem_to_contests[problem_id]:
                        recommendations.discard(cid)
                except cache_system2.ContestNotFound:
                    pass

        if not recommendations:
            raise CodeforcesCogError('Unable to recommend a contest')

        recommendations = list(recommendations)
        random.shuffle(recommendations)
        contests = [cf_common.cache2.contest_cache.get_contest(contest_id) for contest_id in recommendations[:5]]
        msg = '\n'.join(f'{i+1}. [{c.name}]({c.url})' for i, c in enumerate(contests))
        embed = discord_common.cf_color_embed(description=msg)
        str_handles = '`, `'.join(handles)
        await ctx.send(f'Recommended contest(s) for `{str_handles}`', embed=embed)

    @commands.command(brief="Display unsolved rounds closest to completion", usage='[keywords]')
    async def fullsolve(self, ctx, *args: str):
        """Displays a list of contests, sorted by number of unsolved problems.
        Contest names matching any of the provided tags will be considered. e.g ;fullsolve +edu"""
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        tags = [x for x in args if x[0] == '+']

        problem_to_contests = cf_common.cache2.problemset_cache.problem_to_contests
        contests = [contest for contest in cf_common.cache2.contest_cache.get_contests_in_phase('FINISHED')
                    if (not tags or contest.matches(tags)) and not cf_common.is_nonstandard_contest(contest)]

        # subs_by_contest_id contains contest_id mapped to [list of problem.name]
        subs_by_contest_id = defaultdict(set)
        for sub in await cf.user.status(handle=handle):
            if sub.verdict == 'OK':
                try:
                    contest = cf_common.cache2.contest_cache.get_contest(sub.problem.contestId)
                    problem_id = (sub.problem.name, contest.startTimeSeconds)
                    for contestId in problem_to_contests[problem_id]:
                        subs_by_contest_id[contestId].add(sub.problem.name)
                except cache_system2.ContestNotFound:
                    pass

        contest_unsolved_pairs = []
        for contest in contests:
            num_solved = len(subs_by_contest_id[contest.id])
            try:
                num_problems = len(cf_common.cache2.problemset_cache.get_problemset(contest.id))
                if 0 < num_solved < num_problems:
                    contest_unsolved_pairs.append((contest, num_solved, num_problems))
            except cache_system2.ProblemsetNotCached:
                # In case of recent contents or cetain bugged contests
                pass

        contest_unsolved_pairs.sort(key=lambda p: (p[2] - p[1], -p[0].startTimeSeconds))

        if not contest_unsolved_pairs:
            await ctx.send(f'`{handle}` has no contests to fullsolve :confetti_ball:')
            return

        def make_line(entry):
            contest, solved, total = entry
            return f'[{contest.name}]({contest.url})\N{EN SPACE}[{solved}/{total}]'

        def make_page(chunk):
            message = f'Fullsolve list for `{handle}`'
            full_solve_list = '\n'.join(make_line(entry) for entry in chunk)
            embed = discord_common.cf_color_embed(description=full_solve_list)
            return message, embed

        pages = [make_page(chunk) for chunk in paginator.chunkify(contest_unsolved_pairs, 10)]
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=5 * 60, set_pagenum_footers=True)

    @staticmethod
    def getEloWinProbability(ra: float, rb: float) -> float:
        return 1.0 / (1 + 10**((rb - ra) / 400.0))

    @staticmethod
    def composeRatings(left: float, right: float, ratings: List[float]) -> int:
        for tt in range(20):
            r = (left + right) / 2.0

            rWinsProbability = 1.0
            for rating, count in ratings:
                rWinsProbability *= Codeforces.getEloWinProbability(r, rating)**count

            if rWinsProbability < 0.5:
                left = r
            else:
                right = r
        return round((left + right) / 2)

    @commands.command(brief='Calculate team rating', usage='[handles]')
    async def teamrate(self, ctx, *handles: str):
        """Provides the combined rating of the entire team.
        If +server is provided as the only handle, will display the rating of the entire server.
        Supports multipliers. e.g: ;teamrate gamegame*1000"""

        handles = handles or ('!' + str(ctx.author),)
        is_entire_server = (handles == ('+server',))
        if is_entire_server:
            res = cf_common.user_db.get_cf_users_for_guild(ctx.guild.id)
            ratings = [cf_user.rating for user_id, cf_user in res if cf_user.rating is not None]
            user_str = '+server'
        else:
            def normalize(x):
                return [i.lower() for i in x]
            handle_counts = {}
            parsed_handles = []
            for i in handles:
                parse_str = normalize(i.split('*'))
                if len(parse_str) > 1:
                    try:
                        handle_counts[parse_str[0]] = int(parse_str[1])
                    except ValueError:
                        raise CodeforcesCogError("Can't multiply by non-integer")
                else:
                    handle_counts[parse_str[0]] = 1
                parsed_handles.append(parse_str[0])

            cf_handles = await cf_common.resolve_handles(ctx, self.converter, parsed_handles, mincnt=1, maxcnt=1000)
            cf_handles = normalize(cf_handles)
            cf_to_original = {a: b for a, b in zip(cf_handles, parsed_handles)}
            original_to_cf = {a: b for a, b in zip(parsed_handles, cf_handles)}
            users = await cf.user.info(handles=cf_handles)
            user_strs = []
            for a, b in handle_counts.items():
                if b > 1:
                    user_strs.append(f'{original_to_cf[a]}*{b}')
                elif b == 1:
                    user_strs.append(original_to_cf[a])
                elif b <= 0:
                    raise CodeforcesCogError('How can you have nonpositive members in team?')

            user_str = ', '.join(user_strs)
            ratings = [(user.rating, handle_counts[cf_to_original[user.handle.lower()]]) for user in users if user.rating]

        if len(ratings) == 0:
            raise CodeforcesCogError("No CF usernames with ratings passed in.")

        left = -100.0
        right = 10000.0
        teamRating = Codeforces.composeRatings(left, right, ratings)
        embed = discord.Embed(title=user_str, description=teamRating, color=cf.rating2rank(teamRating).color_embed)
        await ctx.send(embed = embed)

    @discord_common.send_error_if(CodeforcesCogError, cf_common.ResolveHandleError,
                                  cf_common.FilterError)
    async def cog_command_error(self, ctx, error):
        pass


def setup(bot):
    bot.add_cog(Codeforces(bot))
