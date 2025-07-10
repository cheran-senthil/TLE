
import random
import discord
import asyncio
import time
import logging

from functools import cmp_to_key
from collections import namedtuple

from discord.ext import commands
from discord.ext.commands import cooldown, BucketType

from tle import constants
from tle.util import codeforces_common as cf_common
from tle.util import codeforces_api as cf
from tle.util import discord_common
from tle.util import elo
from tle.util import paginator

logger = logging.getLogger(__name__)

MAX_ROUND_USERS = 5
LOWER_RATING = 800
UPPER_RATING = 3500
MATCH_DURATION = [5, 180]
MAX_PROBLEMS = 6
MAX_ALTS = 5
ROUNDS_PER_PAGE = 5
AUTO_UPDATE_TIME = 30
RECENT_SUBS_LIMIT = 50
PROBLEM_STATUS_UNSOLVED = 10**18
PROBLEM_STATUS_TESTING = -1
_PAGINATE_WAIT_TIME = 5 * 60

def _calc_round_score(users, status, times):
    def comp(a, b):
        if a[0] > b[0]:
            return -1
        if a[0] < b[0]:
            return 1
        if a[1] == b[1]:
            return 0
        return -1 if a[1] < b[1] else 1

    ranks = [[status[i], times[i], users[i]] for i in range(len(status))]
    ranks.sort(key=cmp_to_key(comp))
    res = []

    for user in ranks:
        User = namedtuple("User", "id points rank")
        # user points rank
        res.append(User(user[2], user[0], [[x[0], x[1]] for x in ranks].index([user[0], user[1]]) + 1))
    return res

class RoundCogError(commands.CommandError):
    pass

class Round(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.locked = False

    @commands.Cog.listener()
    @discord_common.once
    async def on_ready(self):
        asyncio.create_task(self._check_ongoing_rounds())

    async def _check_ongoing_rounds(self):
        for guild in self.bot.guilds:
            await self._check_ongoing_rounds_for_guild(guild)    
        await asyncio.sleep(AUTO_UPDATE_TIME)
        asyncio.create_task(self._check_ongoing_rounds()) 

    async def _check_ongoing_rounds_for_guild(self, guild):
        channel_id = cf_common.user_db.get_round_channel(guild.id)
        if channel_id == None:
            logger.warn(f'_check_ongoing_rounds_for_guild: lockout round channel is not set.')
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.warn(f'_check_ongoing_rounds_for_guild: lockout round channel is not found on the server.')
            return

        await self._update_all_ongoing_rounds(guild, channel, True)

    async def _update_all_ongoing_rounds(self, guild, channel, isAutomaticRun):
        if not self.locked:
            self.locked = True
            rounds = cf_common.user_db.get_ongoing_rounds(guild.id)
            try:
                for round in rounds:
                    await self._check_round_complete(guild, channel, round, isAutomaticRun)
            except Exception as exception:
                if isAutomaticRun:
                    # in automatic run we need to handle exceptions on our own -> put them into server log for now (TODO: logging channel would be better)
                    msg = 'Ignoring exception in command {}:'.format("_check_round_complete")
                    exc_info = type(exception), exception, exception.__traceback__
                    extra = { }
                    logger.exception(msg, exc_info=exc_info, extra=extra)
                else:
                    # Exceptions will be handled through other mechanisms but we make sure that the locked variable is reset
                    self.locked = False
                    raise exception
            self.locked = False

    def _check_if_correct_channel(self, ctx):
        lockout_channel_id = cf_common.user_db.get_round_channel(ctx.guild.id)
        channel = ctx.guild.get_channel(lockout_channel_id)
        if not lockout_channel_id or ctx.channel.id != lockout_channel_id:
            raise RoundCogError(f'You must use this command in lockout round channel ({channel.mention}).')

    async def _check_if_all_members_ready(self, ctx, members):
        embed = discord.Embed(description=f"{' '.join(x.mention for x in members)} react on the message with ✅ within 30 seconds to join the round. {'Since you are the only participant, this will be a practice round and there will be no rating changes' if len(members) == 1 else ''}",
            color=discord.Color.purple())
        message = await ctx.send(embed=embed)
        await message.add_reaction("✅")

        # check for reaction of all users
        all_reacted = False
        reacted = []

        def check(reaction, member):
            return reaction.message.id == message.id and reaction.emoji == "✅" and member in members

        while True:
            try:
                _, member = await self.bot.wait_for('reaction_add', timeout=30, check=check)
                reacted.append(member)
                if all(item in reacted for item in members):
                    all_reacted = True
                    break
            except asyncio.TimeoutError:
                break

        if not all_reacted:
            raise RoundCogError(f'Unable to start round, some participant(s) did not react in time!')

    def _check_if_any_member_is_already_in_round(self, ctx, members):
        busy_members = []
        for member in members:
            if cf_common.user_db.check_if_user_in_ongoing_round(ctx.guild.id, member.id):
                busy_members.append(member)
        if busy_members:
            busy_members_str = ", ".join([ctx.guild.get_member(int(member.id)).mention for member in busy_members])
            error = f'{busy_members_str} are registered in ongoing lockout rounds.'
            raise RoundCogError(error)

    async def _get_time_response(self, client, ctx, message, time, author, range_):
        original = await ctx.send(embed=discord.Embed(description=message, color=discord.Color.green()))

        def check(m):
            if not m.content.isdigit() or not m.author == author:
                return False
            i = m.content
            if int(i) < range_[0] or int(i) > range_[1]:
                return False
            return True
        try:
            msg = await client.wait_for('message', timeout=time, check=check)
            await original.delete()
            return int(msg.content)
        except asyncio.TimeoutError:
            await original.delete()
            raise RoundCogError(f'{ctx.author.mention} you took too long to decide')

    async def _get_seq_response(self, client, ctx, message, time, length, author, range_):
        original = await ctx.send(embed=discord.Embed(description=message, color=discord.Color.green()))

        def check(m):
            if m.author != author:
                return False
            data = m.content.split()
            if len(data) != length:
                return False
            for i in data:
                if not i.isdigit():
                    return False
                if int(i) < range_[0] or int(i) > range_[1]:
                    return False
            return True

        try:
            msg = await client.wait_for('message', timeout=time, check=check)
            await original.delete()
            return [int(x) for x in msg.content.split()]
        except asyncio.TimeoutError:
            await original.delete()
            raise RoundCogError(f'{ctx.author.mention} you took too long to decide')

    def _round_problems_embed(self, round_info):
        ranklist = _calc_round_score(list(map(int, round_info.users.split())), list(map(int, round_info.status.split())), list(map(int, round_info.times.split())))

        problemEntries = round_info.problems.split()
        def get_problem(problemContestId, problemIndex):
            return [prob for prob in cf_common.cache2.problem_cache.problems if prob.contest_identifier == f'{problemContestId}{problemIndex}' ]

        problems = [get_problem(prob.split('/')[0], prob.split('/')[1]) if prob != '0' else None for prob in problemEntries]

        replacementStr = 'This problem has been solved' if round_info.repeat == 0 else 'No problems of this rating left'
        names = [f'[{prob[0].name}](https://codeforces.com/contest/{prob[0].contestId}/problem/{prob[0].index})' 
                    if prob is not None else replacementStr for prob in problems]

        desc = ""
        for user in ranklist:
            emojis = [':first_place:', ':second_place:', ':third_place:']
            handle = cf_common.user_db.get_handle(user.id, round_info.guild) 
            desc += f'{emojis[user.rank-1] if user.rank <= len(emojis) else user.rank} [{handle}](https://codeforces.com/profile/{handle}) **{user.points}** points\n'

        embed = discord.Embed(description=desc, color=discord.Color.magenta())
        embed.set_author(name=f'Problems')

        embed.add_field(name='Points', value='\n'.join(round_info.points.split()), inline=True)
        embed.add_field(name='Problem Name', value='\n'.join(names), inline=True)
        embed.add_field(name='Rating', value='\n'.join(round_info.rating.split()), inline=True)
        timestr = cf_common.pretty_time_format(((round_info.time + 60 * round_info.duration) - int(time.time())), shorten=True, always_seconds=True)
        embed.set_footer(text=f'Time left: {timestr}')

        return embed
    
    def make_round_embed(self, ctx):
        desc = "Information about Round related commands! **[use ;round <command>]**\n\n"
        match = self.bot.get_command('round')

        for cmd in match.commands:
            desc += f"`{cmd.name}`: **{cmd.brief}**\n"
        embed = discord.Embed(description=desc, color=discord.Color.dark_magenta())
        embed.set_author(name="Lockout commands help", icon_url=ctx.me.avatar)
        embed.set_footer(
            text="For detailed usage about a particular command, type ;help round <command>")
        embed.add_field(name="Based on Lockout bot", value=f"[GitHub](https://github.com/pseudocoder10/Lockout-Bot)",
                        inline=True)
        return embed

    @commands.group(brief='Commands related to lockout rounds! Type ;round for more details', invoke_without_command=True)
    async def round(self, ctx):
        await ctx.send(embed=self.make_round_embed(ctx))

    @round.command(brief='Set the lockout channel to the current channel (Admin/Mod only)')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)  # OK
    async def set_channel(self, ctx):
        """ Sets the lockout round channel to the current channel.
        """
        cf_common.user_db.set_round_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(embed=discord_common.embed_success('Lockout round channel saved successfully'))

    @round.command(brief='Get the lockout channel')
    async def get_channel(self, ctx):
        """ Gets the lockout round channel.
        """
        channel_id = cf_common.user_db.get_round_channel(ctx.guild.id)
        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            raise RoundCogError('There is no lockout round channel')
        embed = discord_common.embed_success('Current lockout round channel')
        embed.add_field(name='Channel', value=channel.mention)
        await ctx.send(embed=embed)

    async def _pick_problem(self, handles, solved, rating, selected):
        def get_problems(rating):
            return [prob for prob in cf_common.cache2.problem_cache.problems
                    if prob.rating == rating and prob.name not in solved
                    and not any(cf_common.is_contest_writer(prob.contestId, handle) for handle in handles)
                    and not cf_common.is_nonstandard_problem(prob)
                    and prob not in selected]

        problems = get_problems(rating)
        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(problem.contestId).startTimeSeconds)

        if not problems:
            raise RoundCogError(f'Not enough unsolved problems of rating {rating} available.')
        choice = max(random.randrange(len(problems)) for _ in range(5)) 
        problem = problems[choice]            
        return problem


    @round.command(name="challenge", brief="Challenge multiple users to a round", usage="[@user1 @user2...]")
    async def challenge(self, ctx, *members: discord.Member):
        # check if we are in the correct channel
        self._check_if_correct_channel(ctx)
        
        members = list(set(members))
        if ctx.author not in members:
            members.append(ctx.author)
        if len(members) > MAX_ROUND_USERS:
            raise RoundCogError(f'{ctx.author.mention} atmost {MAX_ROUND_USERS} users can compete at a time') 

        # get handles first. This also checks if discord member has a linked handle!
        handles = cf_common.members_to_handles(members, ctx.guild.id)            
        for member in members:
            if not cf_common.user_db.is_duelist(member.id, ctx.guild.id):
                cf_common.user_db.register_duelist(member.id, ctx.guild.id)         

        # check for members still in a round
        self._check_if_any_member_is_already_in_round(ctx, members)

        await self._check_if_all_members_ready(ctx, members)           

        problem_cnt = await self._get_time_response(self.bot, ctx, f"{ctx.author.mention} enter the number of problems between [1, {MAX_PROBLEMS}]", 30, ctx.author, [1, MAX_PROBLEMS])

        duration = await self._get_time_response(self.bot, ctx, f"{ctx.author.mention} enter the duration of match in minutes between {MATCH_DURATION}", 30, ctx.author, MATCH_DURATION)

        ratings = await self._get_seq_response(self.bot, ctx, f"{ctx.author.mention} enter {problem_cnt} space seperated integers denoting the ratings of problems (between {LOWER_RATING} and {UPPER_RATING})", 60, problem_cnt, ctx.author, [LOWER_RATING, UPPER_RATING])

        points = await self._get_seq_response(self.bot, ctx, f"{ctx.author.mention} enter {problem_cnt} space seperated integer denoting the points of problems (between 100 and 10,000)", 60, problem_cnt, ctx.author, [100, 10000])

        repeat = await self._get_time_response(self.bot, ctx, f"{ctx.author.mention} do you want a new problem to appear when someone solves a problem (type 1 for yes and 0 for no)", 30, ctx.author, [0, 1])

        # pick problems
        submissions = [await cf.user.status(handle=handle) for handle in handles]        
        solved = {sub.problem.name for subs in submissions for sub in subs if sub.verdict != 'COMPILATION_ERROR'} 
        selected = []
        for rating in ratings:
            problem = await self._pick_problem(handles, solved, rating, selected)
            selected.append(problem)

        await ctx.send(embed=discord.Embed(description="Starting the round...", color=discord.Color.green()))

        cf_common.user_db.create_ongoing_round(ctx.guild.id, int(time.time()), members, ratings, points, selected, duration, repeat)
        round_info = cf_common.user_db.get_round_info(ctx.guild.id, members[0].id)

        await ctx.send(embed=self._round_problems_embed(round_info))

    @round.command(brief="Invalidate a round (Admin/Mod only)", usage="@user")
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)  # OK
    async def _invalidate(self, ctx, member: discord.Member):
        if not cf_common.user_db.check_if_user_in_ongoing_round(ctx.guild.id, member.id):
            raise RoundCogError(f'{member.mention} is not in a round')
        cf_common.user_db.delete_round(ctx.guild.id, member.id)
        await ctx.send(f'Round deleted.')

    @round.command(brief="View problems of your round or for a specific user", usage="[@user]")
    async def problems(self, ctx, member: discord.Member=None):
        # check if we are in the correct channel
        self._check_if_correct_channel(ctx)

        if not member:
            member = ctx.author
        if not cf_common.user_db.check_if_user_in_ongoing_round(ctx.guild.id, member.id):
            raise RoundCogError(f'{member.mention} is not in a round')

        round_info = cf_common.user_db.get_round_info(ctx.guild.id, member.id)
        await ctx.send(embed=self._round_problems_embed(round_info))

    # ranklist = [[DiscordUser, rank, elo]]
    def _calculateRatingChanges(self, ranklist):
        ELO = elo.ELOMatch()
        for player in ranklist:
            ELO.addPlayer(player[0].id, player[1], player[2])
        ELO.calculateELOs()
        res = {}
        for player in ranklist:
            res[player[0].id] = [ELO.getELO(player[0].id), ELO.getELOChange(player[0].id)]
        return res

    async def _get_solve_time(self, recent_subs, contest_id, index):
        subs = [sub for sub in recent_subs
                if (sub.verdict == 'OK' or sub.verdict == 'TESTING')
                and sub.problem.contest_identifier == f'{contest_id}{index}']

        if not subs:
            return PROBLEM_STATUS_UNSOLVED
        if 'TESTING' in [sub.verdict for sub in subs]:
            return PROBLEM_STATUS_TESTING
        return min(subs, key=lambda sub: sub.creationTimeSeconds).creationTimeSeconds

    def _no_round_change_possible(self, status, points, problems):
        status.sort()
        sum = 0
        for i in range(len(points)):
            if problems[i] != '0':
                sum = sum + points[i]
        for i in range(len(status) - 1):
            if status[i] + sum > status[i + 1]:
                return False
        if len(status) == 1 and sum > 0:
            return False
        return True

    async def _round_end_embed(self, channel, round_info, ranklist, eloChanges):
        embed = discord.Embed(color=discord.Color.dark_magenta())
        pos, name, ratingChange = '', '', ''
        for user in ranklist:
            handle = cf_common.user_db.get_handle(user.id, round_info.guild)
            emojis = [":first_place:", ":second_place:", ":third_place:"]
            pos += f"{emojis[user.rank-1] if user.rank <= len(emojis) else str(user.rank)} **{user.points}**\n"
            name += f"[{handle}](https://codeforces.com/profile/{handle})\n"
            ratingChange += f"{eloChanges[user.id][0]} (**{'+' if eloChanges[user.id][1] >= 0 else ''}{eloChanges[user.id][1]}**)\n"
        embed.add_field(name="Position", value=pos)
        embed.add_field(name="User", value=name)
        embed.add_field(name="Rating changes", value=ratingChange)
        embed.set_author(name=f"Round over! Final standings")

        await channel.send(embed=embed)    

    async def _update_round(self, round_info):
        user_ids = list(map(int, round_info.users.split()))
        handles = [cf_common.user_db.get_handle(user_id, round_info.guild) for user_id in user_ids]
        rating = list(map(int, round_info.rating.split()))
        enter_time = time.time()
        points = list(map(int, round_info.points.split()))
        status = list(map(int, round_info.status.split()))
        timestamp = list(map(int, round_info.times.split()))
        problems = round_info.problems.split()

        judging, over, updated = False, False, False

        updates = []
        recent_subs = [await cf.user.status(handle=handle, count=RECENT_SUBS_LIMIT) for handle in handles]
        for i in range(len(problems)):
            # Problem was solved before and no replacement -> skip
            if problems[i] == '0':
                updates.append([])
                continue

            times = [await self._get_solve_time(recent_subs[index], int(problems[i].split('/')[0]), problems[i].split('/')[1]) for index in range(len(handles))]

            # There are pending submission that need to be judged -> skip this problem for now
            if any([substatus == PROBLEM_STATUS_TESTING for substatus in times]):
                judging = True
                updates.append([])
                continue

            # Check if someone solved a problem
            solved = []
            for j in range(len(user_ids)):
                if times[j] != PROBLEM_STATUS_UNSOLVED and times[j] == min(times) and times[j] <= round_info.time + 60 * round_info.duration:
                    solved.append(user_ids[j])
                    status[j] += points[i]
                    problems[i] = '0'
                    timestamp[j] = max(timestamp[j], min(times))
                    updated = True

            updates.append((solved))

            # Get new problem if repeat is set to 1
            if len(solved) > 0 and round_info.repeat == 1:
                try: 
                    submissions = [await cf.user.status(handle=handle) for handle in handles]        
                    solved = {sub.problem.name for subs in submissions for sub in subs if sub.verdict != 'COMPILATION_ERROR'} 
                    problem = await self._pick_problem(handles, solved, rating[i], [])
                    problems[i] = f'{problem.contestId}/{problem.index}'
                except RoundCogError:
                    problems[i] = '0'

        # If changes to the round state were made update the DB
        if updated:
            cf_common.user_db.update_round_status(round_info.guild, user_ids[0], status, problems, timestamp)

        # check if round is over (time over or no more ranklist changes possible)
        if not judging and (enter_time > round_info.time + 60 * round_info.duration or (round_info.repeat == 0 and self._no_round_change_possible(status[:], points, problems))):
            over = True
        return updates, over, updated

    async def _check_round_complete(self, guild, channel, round, isAutomaticRun = False):
        updates, over, updated = await self._update_round(round)

        if updated or over:
            await channel.send(f"{' '.join([(guild.get_member(int(m))).mention for m in round.users.split()])} there is an update in standings")

        for i in range(len(updates)):
            if len(updates[i]):
                await channel.send(embed=discord.Embed(
                    description=f"{' '.join([(guild.get_member(m)).mention for m in updates[i]])} has solved problem worth **{round.points.split()[i]}** points",
                    color=discord.Color.blue()))

        if not over and updated:
            round_info = cf_common.user_db.get_round_info(round.guild, round.users)
            await channel.send(embed=self._round_problems_embed(round_info))

        # round ended -> make rating changes, change db, show results
        if over:
            round_info = cf_common.user_db.get_round_info(round.guild, round.users)
            ranklist = _calc_round_score(list(map(int, round_info.users.split())),
                                    list(map(int, round_info.status.split())),
                                    list(map(int, round_info.times.split())))

            # change duel rating
            eloChanges = self._calculateRatingChanges([[(guild.get_member(user.id)), user.rank, cf_common.user_db.get_duel_rating(user.id, guild.id)] for user in ranklist])
            for id in list(map(int, round_info.users.split())):
                cf_common.user_db.update_duel_rating(id, guild.id, eloChanges[id][1])


            cf_common.user_db.delete_round(round_info.guild, round_info.users)
            cf_common.user_db.create_finished_round(round_info, int(time.time()))

            await self._round_end_embed(channel, round_info, ranklist, eloChanges)



    @round.command(brief="Update matches status for the server")
    @cooldown(1, AUTO_UPDATE_TIME, BucketType.guild)
    async def update(self, ctx):
        # check if we are in the correct channel
        self._check_if_correct_channel(ctx)

        await ctx.send(embed=discord.Embed(description="Updating rounds for this server", color=discord.Color.green()))

        await self._update_all_ongoing_rounds(ctx.guild, ctx.channel, False)

        

    @round.command(name="ongoing", brief="View ongoing rounds")
    async def ongoing(self, ctx):
        data = cf_common.user_db.get_ongoing_rounds(ctx.guild.id)

        if not data:
            raise RoundCogError(f"No ongoing rounds")

        def _make_pages(data, title):
            chunks = paginator.chunkify(data, ROUNDS_PER_PAGE)
            pages = []

            for chunk in chunks:
                msg = ''
                for round in chunk:
                    ranklist = _calc_round_score(list(map(int, round.users.split())), list(map(int, round.status.split())),
                                                    list(map(int, round.times.split())))
                    msg += ' vs '.join([f"[{cf_common.user_db.get_handle(user.id, round.guild) }](https://codeforces.com/profile/{cf_common.user_db.get_handle(user.id, round.guild) }) `Rank {user.rank}` `{user.points} Points`"
                                    for user in ranklist])
                    msg += f"\n**Problem ratings:** {round.rating}"
                    msg += f"\n**Score distribution** {round.points}"
                    timestr = cf_common.pretty_time_format(((round.time + 60 * round.duration) - int(time.time())), shorten=True, always_seconds=True)
                    msg += f"\n**Time left:** {timestr}\n\n"
                embed = discord_common.cf_color_embed(description=msg)
                pages.append((title, embed))

            return pages

        title = 'List of ongoing lockout rounds'
        pages = _make_pages(data, title)
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=_PAGINATE_WAIT_TIME,
                           set_pagenum_footers=True)

    @round.command(name="recent", brief="Show recent rounds")
    async def recent(self, ctx, user: discord.Member=None):
        data = cf_common.user_db.get_recent_rounds(ctx.guild.id, str(user.id) if user else None)
        
        if not data:
            raise RoundCogError(f"No recent rounds")

        def _make_pages(data, title):
            chunks = paginator.chunkify(data, ROUNDS_PER_PAGE)
            pages = []

            for chunk in chunks:
                msg = ''
                for round in chunk:
                    ranklist = _calc_round_score(list(map(int, round.users.split())), list(map(int, round.status.split())),
                                                    list(map(int, round.times.split())))
                    msg += ' vs '.join([f"[{cf_common.user_db.get_handle(user.id, round.guild) }](https://codeforces.com/profile/{cf_common.user_db.get_handle(user.id, round.guild) }) `Rank {user.rank}` `{user.points} Points`"
                                    for user in ranklist])
                    msg += f"\n**Problem ratings:** {round.rating}"
                    msg += f"\n**Score distribution** {round.points}"
                    timestr = cf_common.pretty_time_format(min(60*round.duration, round.end_time-round.time), shorten=True, always_seconds=True)
                    msg += f"\n**Duration:** {timestr}\n\n"
                embed = discord_common.cf_color_embed(description=msg)
                pages.append((title, embed))

            return pages

        title = 'List of recent lockout rounds'
        pages = _make_pages(data, title)
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=_PAGINATE_WAIT_TIME,
                           set_pagenum_footers=True)

#     @round.command(name="custom", brief="Challenge to a round with custom problemset")
#     async def custom(self, ctx, *users: discord.Member):
#         users = list(set(users))
#         if len(users) == 0:
#             await discord_.send_message(ctx, f"The correct usage is `.round custom @user1 @user2...`")
#             return
#         if ctx.author not in users:
#             users.append(ctx.author)
#         if len(users) > MAX_ROUND_USERS:
#             await ctx.send(f"{ctx.author.mention} atmost {MAX_ROUND_USERS} users can compete at a time")
#             return
#         for i in users:
#             if not self.db.get_handle(ctx.guild.id, i.id):
#                 await discord_.send_message(ctx, f"Handle for {i.mention} not set! Use `.handle identify` to register")
#                 return
#             if self.db.in_a_round(ctx.guild.id, i.id):
#                 await discord_.send_message(ctx, f"{i.mention} is already in a round!")
#                 return

#         embed = discord.Embed(
#             description=f"{' '.join(x.mention for x in users)} react on the message with ✅ within 30 seconds to join the round. {'Since you are the only participant, this will be a practice round and there will be no rating changes' if len(users) == 1 else ''}",
#             color=discord.Color.purple())
#         message = await ctx.send(embed=embed)
#         await message.add_reaction("✅")

#         all_reacted = False
#         reacted = []

#         def check(reaction, user):
#             return reaction.message.id == message.id and reaction.emoji == "✅" and user in users

#         while True:
#             try:
#                 reaction, user = await self.bot.wait_for('reaction_add', timeout=30, check=check)
#                 reacted.append(user)
#                 if all(item in reacted for item in users):
#                     all_reacted = True
#                     break
#             except asyncio.TimeoutError:
#                 break

#         if not all_reacted:
#             await discord_.send_message(ctx, f"Unable to start round, some participant(s) did not react in time!")
#             return

#         problem_cnt = await discord_.get_time_response(self.bot, ctx,
#                                                        f"{ctx.author.mention} enter the number of problems between [1, {MAX_PROBLEMS}]",
#                                                        30, ctx.author, [1, MAX_PROBLEMS])
#         if not problem_cnt[0]:
#             await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
#             return
#         problem_cnt = problem_cnt[1]

#         duration = await discord_.get_time_response(self.bot, ctx,
#                                                     f"{ctx.author.mention} enter the duration of match in minutes between {MATCH_DURATION}",
#                                                     30, ctx.author, MATCH_DURATION)
#         if not duration[0]:
#             await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
#             return
#         duration = duration[1]

#         problems = await discord_.get_problems_response(self.bot, ctx,
#                                                  f"{ctx.author.mention} enter {problem_cnt} space seperated problem ids denoting the problems. Eg: `123/A 455/B 242/C ...`",
#                                                  60, problem_cnt, ctx.author)
#         if not problems[0]:
#             await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
#             return
#         problems = problems[1]

#         points = await discord_.get_seq_response(self.bot, ctx,
#                                                  f"{ctx.author.mention} enter {problem_cnt} space seperated integer denoting the points of problems (between 100 and 10,000)",
#                                                  60, problem_cnt, ctx.author, [100, 10000])
#         if not points[0]:
#             await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
#             return
#         points = points[1]

#         for i in users:
#             if self.db.in_a_round(ctx.guild.id, i.id):
#                 await discord_.send_message(ctx, f"{i.name} is already in a round!")
#                 return
#         rating = [problem.rating for problem in problems]

#         tournament = 0
#         if len(users) == 2 and (await tournament_helper.is_a_match(ctx.guild.id, users[0].id, users[1].id, self.api, self.db)):
#             tournament = await discord_.get_time_response(self.bot, ctx,
#                                                           f"{ctx.author.mention} this round is a part of the tournament. Do you want the result of this round to be counted in the tournament. Type `1` for yes and `0` for no",
#                                                           30, ctx.author, [0, 1])
#             if not tournament[0]:
#                 await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
#                 return
#             tournament = tournament[1]

#         await ctx.send(embed=discord.Embed(description="Starting the round...", color=discord.Color.green()))
#         self.db.add_to_ongoing_round(ctx, users, rating, points, problems, duration, 0, [], tournament)
#         round_info = self.db.get_round_info(ctx.guild.id, users[0].id)

#         await ctx.send(embed=discord_.round_problems_embed(round_info))

    @discord_common.send_error_if(RoundCogError, cf_common.ResolveHandleError,
                                  cf_common.FilterError)
    async def cog_command_error(self, ctx, error):
        pass

async def setup(bot):
    await bot.add_cog(Round(bot))
