import random
import datetime
import discord
import asyncio
import logging
import itertools

from discord.ext import commands
from collections import defaultdict, namedtuple
from matplotlib import pyplot as plt

from tle import constants
from tle.util.db.user_db_conn import Duel, DuelType, Winner
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import paginator
from tle.util import discord_common
from tle.util import table
from tle.util import graph_common as gc
from tle.util.elo import _ELO_CONSTANT

logger = logging.getLogger(__name__)

_DUEL_INVALIDATE_TIME = 2 * 60
_DUEL_EXPIRY_TIME = 5 * 60
_DUEL_RATING_DELTA = -400
_DUEL_OFFICIAL_CUTOFF = 3500
_DUEL_NO_DRAW_TIME = 10 * 60
_DUEL_MAX_RATIO = 3.0

_DUEL_STATUS_UNSOLVED = 0
_DUEL_STATUS_TESTING = -1
_DUEL_CHECK_ONGOING_INTERVAL = 60
_DUEL_MAX_DUEL_DURATION = 24 * 60 * 60

DuelRank = namedtuple(
    'Rank', 'low high title title_abbr color_graph color_embed')

DUEL_RANKS = (
    DuelRank(-10 ** 9, 1300, 'Newbie', 'N', '#CCCCCC', 0x808080),
    DuelRank(1300, 1400, 'Pupil', 'P', '#77FF77', 0x008000),
    DuelRank(1400, 1500, 'Specialist', 'S', '#77DDBB', 0x03a89e),
    DuelRank(1500, 1600, 'Expert', 'E', '#AAAAFF', 0x0000ff),
    DuelRank(1600, 1700, 'Candidate Master', 'CM', '#FF88FF', 0xaa00aa),
    DuelRank(1700, 1800, 'Master', 'M', '#FFCC88', 0xff8c00),
    DuelRank(1800, 1900, 'International Master', 'IM', '#FFBB55', 0xf57500),
    DuelRank(1900, 2000, 'Grandmaster', 'GM', '#FF7777', 0xff3030),
    DuelRank(2000, 2100, 'International Grandmaster',
             'IGM', '#FF3333', 0xff0000),
    DuelRank(2100, 10 ** 9, 'Legendary Grandmaster',
             'LGM', '#AA0000', 0xcc0000)
)


def rating2rank(rating):
    for rank in DUEL_RANKS:
        if rank.low <= rating < rank.high:
            return rank


def parse_nohandicap(args):
    for arg in args:
        if arg == "nohandicap":
            return True
    return False


class DuelCogError(commands.CommandError):
    pass

def elo_prob(player, opponent):
    return (1 + 10**((opponent - player) / 400))**-1


def elo_delta(player, opponent, win):
    return _ELO_CONSTANT * (win - elo_prob(player, opponent))


def get_cf_user(userid, guild_id):
    handle = cf_common.user_db.get_handle(userid, guild_id)
    return cf_common.user_db.fetch_cf_user(handle)


def complete_duel(duelid, guild_id, win_status, winner, loser, finish_time, score, dtype):
    winner_r = cf_common.user_db.get_duel_rating(winner.id, guild_id)
    loser_r = cf_common.user_db.get_duel_rating(loser.id, guild_id)
    delta = round(elo_delta(winner_r, loser_r, score))
    rc = cf_common.user_db.complete_duel(
        duelid, guild_id, win_status, finish_time, winner.id, loser.id, delta, dtype)
    if rc == 0:
        raise DuelCogError('Hey! No cheating!')

    if dtype == DuelType.UNOFFICIAL or dtype == DuelType.ADJUNOFFICIAL:
        return None

    winner_cf = get_cf_user(winner.id, guild_id)
    loser_cf = get_cf_user(loser.id, guild_id)
    desc = f'Rating change after **[{winner_cf.handle}]({winner_cf.url})** vs **[{loser_cf.handle}]({loser_cf.url})**:'
    embed = discord_common.cf_color_embed(description=desc)
    embed.add_field(name=f'{winner.display_name}',
                    value=f'{winner_r} -> {winner_r + delta}', inline=False)
    embed.add_field(name=f'{loser.display_name}',
                    value=f'{loser_r} -> {loser_r - delta}', inline=False)
    return embed


def _get_coefficient(problem_rating, lowerrated_rating, higherrated_rating):
    p_lowrated = 1 / (1 + 10**((problem_rating - lowerrated_rating) / 1000))
    p_highrated = 1 / (1 + 10**((problem_rating - higherrated_rating) / 1000))
    coeff = p_highrated / p_lowrated
    # cap values
    coeff = min(_DUEL_MAX_RATIO, max(1./_DUEL_MAX_RATIO, coeff))
    return coeff

class Dueling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()
        self.draw_offers = {}

    @commands.Cog.listener()
    @discord_common.once
    async def on_ready(self):
        asyncio.create_task(self._check_ongoing_duels())
    
    async def _check_ongoing_duels(self):
        try:
            for guild in self.bot.guilds:
                await self._check_ongoing_duels_for_guild(guild)    
        except Exception as exception:
            # we need to handle exceptions on our own -> put them into server log for now (TODO: logging channel would be better)
            msg = 'Ignoring exception in command {}:'.format("_check_round_complete")
            exc_info = type(exception), exception, exception.__traceback__
            extra = { }
            logger.exception(msg, exc_info=exc_info, extra=extra)            
        await asyncio.sleep(_DUEL_CHECK_ONGOING_INTERVAL)
        asyncio.create_task(self._check_ongoing_duels())   

    async def _check_ongoing_duels_for_guild(self, guild):
        logger.info(f'_check_ongoing_duels_for_guild: running for {guild.id}')
        # check for ongoing duels that are older than _DUEL_MAX_DUEL_DURATION
        data = cf_common.user_db.get_ongoing_duels(guild.id)
        channel_id = cf_common.user_db.get_duel_channel(guild.id)
        if channel_id == None:
            logger.warn(f'_check_ongoing_duels_for_guild: duel channel is not set.')
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.warn(f'_check_ongoing_duels_for_guild: duel channel is not found on the server.')
            return


        for entry in data:
            duelid, challenger_id, challengee_id, start_timestamp, problem_name, _, _, dtype = entry
            now = datetime.datetime.now().timestamp()
            if now - start_timestamp >= _DUEL_MAX_DUEL_DURATION:
                challenger = guild.get_member(challenger_id)
                if challenger is None:
                    logger.warn(f'_check_ongoing_duels_for_guild: member with {challenger_id} could not be retrieved.')
                challengee = guild.get_member(challengee_id)                    
                if challengee is None:
                    logger.warn(f'_check_ongoing_duels_for_guild: member with {challengee_id} could not be retrieved.')

                embed = complete_duel(duelid, guild.id, Winner.DRAW,
                                challenger, challengee, now, 0.5, dtype)
                timelimit = cf_common.pretty_time_format(_DUEL_MAX_DUEL_DURATION) 
                await channel.send(f'Auto draw of duel between {challenger.mention} and {challengee.mention} since it was active for more than {timelimit}.', embed=embed)    

        # check for duels that can be completed
        for entry in data:
            await self._check_duel_complete(guild, channel, entry, True)
                    

    @commands.group(brief='Duel commands',
                    invoke_without_command=True)
    async def duel(self, ctx):
        """Group for commands pertaining to duels"""
        await ctx.send_help(ctx.command)

    def _checkIfCorrectChannel(self, ctx):
        duel_channel_id = cf_common.user_db.get_duel_channel(
            ctx.guild.id)
        if not duel_channel_id or ctx.channel.id != duel_channel_id:
            raise DuelCogError(
                'You must use this command in duel channel.')

    @duel.command(brief='Set the duel channel to the current channel')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)  # OK
    async def set_channel(self, ctx):
        """ Sets the duel channel to the current channel.
        """
        cf_common.user_db.set_duel_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(embed=discord_common.embed_success('Duel channel saved successfully'))

    @duel.command(brief='Get the duel channel')
    async def get_channel(self, ctx):
        """ Gets the duel channel.
        """
        channel_id = cf_common.user_db.get_duel_channel(ctx.guild.id)
        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            raise DuelCogError('There is no duel channel. Set one with ;duel set_channel')
        embed = discord_common.embed_success('Current duel channel')
        embed.add_field(name='Channel', value=channel.mention)
        await ctx.send(embed=embed)

    @duel.command(brief='Challenge to a duel', usage='opponent [rating] [+tag..] [~tag..] [+divX] [~divX] [nohandicap]')
    async def challenge(self, ctx, opponent: discord.Member, *args):
        """Challenge another server member to a duel. Problem difficulty will be the lesser of duelist ratings minus 400. You can alternatively specify a different rating. 
        All duels will be rated. The challenge expires if ignored for 5 minutes.
        The bot will allow the lower rated duelist to take more time for the duel. 
        If the keyword 'nohandicap' is added there will be no handicap for the higher rated duelist."""
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        challenger_id = ctx.author.id
        challengee_id = opponent.id

        await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author), '!' + str(opponent)))
        userids = [challenger_id, challengee_id]
        handles = [cf_common.user_db.get_handle(
            userid, ctx.guild.id) for userid in userids]
        submissions = [await cf.user.status(handle=handle) for handle in handles]

        if not cf_common.user_db.is_duelist(challenger_id, ctx.guild.id):
            cf_common.user_db.register_duelist(challenger_id, ctx.guild.id)
        if not cf_common.user_db.is_duelist(challengee_id, ctx.guild.id):
            cf_common.user_db.register_duelist(challengee_id, ctx.guild.id)
        if challenger_id == challengee_id:
            raise DuelCogError(
                f'{ctx.author.mention}, you cannot challenge yourself!')
        if cf_common.user_db.check_duel_challenge(challenger_id, ctx.guild.id):
            raise DuelCogError(
                f'{ctx.author.mention}, you are currently in a duel!')
        if cf_common.user_db.check_duel_challenge(challengee_id, ctx.guild.id):
            raise DuelCogError(
                f'{opponent.mention} is currently in a duel!')
                
        tags = cf_common.parse_tags(args, prefix='+')
        bantags = cf_common.parse_tags(args, prefix='~')
        rating = cf_common.parse_rating(args)
        nohandicap = parse_nohandicap(args)
        users = [cf_common.user_db.fetch_cf_user(handle) for handle in handles]
        lowest_rating = min(user.effective_rating or 0 for user in users)
        suggested_rating = round(lowest_rating, -2) + _DUEL_RATING_DELTA
        rating = round(rating, -2) if rating else suggested_rating
        rating = min(3500, max(rating, 800))
        unofficial = rating > _DUEL_OFFICIAL_CUTOFF #suggested_rating 
        if not nohandicap:
            dtype = DuelType.ADJUNOFFICIAL if unofficial else DuelType.ADJOFFICIAL
        else:
            dtype = DuelType.UNOFFICIAL if unofficial else DuelType.OFFICIAL
        
        solved = {
            sub.problem.name for subs in submissions for sub in subs if sub.verdict != 'COMPILATION_ERROR'}
        seen = {name for userid in userids for name,
                in cf_common.user_db.get_duel_problem_names(userid, ctx.guild.id)} # maybe guild id is not needed here

        def get_problems(rating):
            return [prob for prob in cf_common.cache2.problem_cache.problems
                    if prob.rating == rating and prob.name not in solved and prob.name not in seen
                    and not any(cf_common.is_contest_writer(prob.contestId, handle) for handle in handles)
                    and not cf_common.is_nonstandard_problem(prob)
                    and prob.matches_all_tags(tags)
                    and not prob.matches_any_tag(bantags)]

        for problems in map(get_problems, range(rating, 400, -100)):
            if problems:
                break

        rstr = f'{rating} rated ' if rating else ''
        if not problems:
            raise DuelCogError(
                f'No unsolved {rstr}problems left for {ctx.author.mention} vs {opponent.mention}.')

        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds)

        choice = max(random.randrange(len(problems)) for _ in range(5))
        problem = problems[choice]

        issue_time = datetime.datetime.now().timestamp()
        duelid = cf_common.user_db.create_duel(
            challenger_id, challengee_id, issue_time, problem, dtype, ctx.guild.id)

        if not nohandicap:
            # get cf handles and cf.Users
            userids = [challenger_id, challengee_id]
            handles = [cf_common.user_db.get_handle(
                userid, ctx.guild.id) for userid in userids]
            users = [cf_common.user_db.fetch_cf_user(handle) for handle in handles] 
     
            # get discord member
            challenger = ctx.guild.get_member(challenger_id)
            challengee = ctx.guild.get_member(challengee_id)

            highrated_user = users[0] if users[0].effective_rating > users[1].effective_rating else users[1]
            lowrated_user = users[1] if users[0].effective_rating > users[1].effective_rating else users[0]
            highrated_member = challenger if users[0].effective_rating > users[1].effective_rating else challengee
            lowrated_member = challengee if users[0].effective_rating > users[1].effective_rating else challenger
            higherrated_rating, lowerrated_rating = highrated_user.effective_rating, lowrated_user.effective_rating
            coeff = _get_coefficient(problem.rating, lowerrated_rating, higherrated_rating)
            percentage = round((coeff - 1.0)*100,1)
            ostr = 'an **unofficial** ' if unofficial else 'a '
            diff = cf_common.pretty_time_format(600 * coeff-600, always_seconds=True)
            if lowerrated_rating == higherrated_rating:
                await ctx.send(f'{ctx.author.mention} is challenging {opponent.mention} to {ostr} {rstr}duel with handicap! Since {lowrated_member.mention} and {highrated_member.mention} have same rating no one will get a time bonus.' )
            else:     
                await ctx.send(f'{ctx.author.mention} is challenging {opponent.mention} to {ostr} {rstr}duel with handicap! {lowrated_member.mention} is lower rated and will get {percentage} % more time (bonus of {diff} for every 10 minutes of duel duration).' )
        else: 
            ostr = 'an **unofficial**' if unofficial else 'a'
            await ctx.send(f'{ctx.author.mention} is challenging {opponent.mention} to {ostr} {rstr}duel!')
        await asyncio.sleep(_DUEL_EXPIRY_TIME)
        if cf_common.user_db.cancel_duel(duelid, ctx.guild.id, Duel.EXPIRED):
            message = f'{ctx.author.mention}, your request to duel {opponent.mention} has expired!'
            embed = discord_common.embed_alert(message)
            await ctx.send(embed=embed)

    @duel.command(brief='Decline a duel challenge. Can be used to decline a challenge as challengee.')
    async def decline(self, ctx):
        active = cf_common.user_db.check_duel_decline(ctx.author.id, ctx.guild.id)
        if not active:
            raise DuelCogError(
                f'{ctx.author.mention}, you are not being challenged!')

        duelid, challenger = active
        challenger = ctx.guild.get_member(challenger)
        cf_common.user_db.cancel_duel(duelid, ctx.guild.id, Duel.DECLINED)
        message = f'`{ctx.author.mention}` declined a challenge by {challenger.mention}.'
        embed = discord_common.embed_alert(message)
        await ctx.send(embed=embed)

    @duel.command(brief='Withdraw a duel challenge. Can be used to revert the challenge as challenger.')
    async def withdraw(self, ctx):
        active = cf_common.user_db.check_duel_withdraw(ctx.author.id, ctx.guild.id)
        if not active:
            raise DuelCogError(
                f'{ctx.author.mention}, you are not challenging anyone.')

        duelid, challengee = active
        challengee = ctx.guild.get_member(challengee)
        cf_common.user_db.cancel_duel(duelid, ctx.guild.id, Duel.WITHDRAWN)
        message = f'{ctx.author.mention} withdrew a challenge to `{challengee.mention}`.'
        embed = discord_common.embed_alert(message)
        await ctx.send(embed=embed)

    @duel.command(brief='Accept a duel challenge. This starts the duel.')
    async def accept(self, ctx):
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        active = cf_common.user_db.check_duel_accept(ctx.author.id, ctx.guild.id)
        if not active:
            raise DuelCogError(
                f'{ctx.author.mention}, you are not being challenged.')

        duelid, challenger_id, name = active
        challenger = ctx.guild.get_member(challenger_id)
        await ctx.send(f'Duel between {challenger.mention} and {ctx.author.mention} starting in 15 seconds!')
        await asyncio.sleep(15)

        start_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.start_duel(duelid, ctx.guild.id, start_time)
        if rc != 1:
            raise DuelCogError(
                f'Unable to start the duel between {challenger.mention} and {ctx.author.mention}.')

        problem = cf_common.cache2.problem_cache.problem_by_name[name]
        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache2.contest_cache.get_contest(
            problem.contestId).name
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'Starting duel: {challenger.mention} vs {ctx.author.mention}', embed=embed)
    
    async def _get_solve_time(self, handle, contest_id, index):
        subs = [sub for sub in await cf.user.status(handle=handle)
                if (sub.verdict == 'OK' or sub.verdict == 'TESTING')
                and sub.problem.contestId == contest_id
                and sub.problem.index == index]

        if not subs:
            return _DUEL_STATUS_UNSOLVED
        if 'TESTING' in [sub.verdict for sub in subs]:
            return _DUEL_STATUS_TESTING
        return min(subs, key=lambda sub: sub.creationTimeSeconds).creationTimeSeconds
    
    @duel.command(brief='Give up the duel (only for duels with handicap). Can only be used by the lower rated duelist after the higher rated duelist has solved the problem.')
    async def giveup(self, ctx):
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        active = cf_common.user_db.check_duel_giveup(ctx.author.id, ctx.guild.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not in a duel.')

        duelid, challenger_id, challengee_id, start_timestamp, problem_name, contest_id, index, dtype = active


        # get discord member
        challenger = ctx.guild.get_member(challenger_id)
        challengee = ctx.guild.get_member(challengee_id)

         # get cf handles and cf.Users
        userids = [challenger_id, challengee_id]
        handles = [cf_common.user_db.get_handle(
            userid, ctx.guild.id) for userid in userids]
        users = [cf_common.user_db.fetch_cf_user(handle) for handle in handles] 
        
        highrated_user = users[0] if users[0].effective_rating > users[1].effective_rating else users[1]
        lowrated_user = users[1] if users[0].effective_rating > users[1].effective_rating else users[0]
        highrated_member = challenger if users[0].effective_rating > users[1].effective_rating else challengee
        lowrated_member = challengee if users[0].effective_rating > users[1].effective_rating else challenger

        highrated_timestamp = await self._get_solve_time(highrated_user.handle, contest_id, index)
        lowrated_timestamp = await self._get_solve_time(lowrated_user.handle, contest_id, index)            

        lowerrated_id = userids[1] if users[0].effective_rating > users[1].effective_rating else userids[0]

        # only low rated user can invoke the command
        if ctx.author.id != lowerrated_id:
            await ctx.send(f'Only the lower rated user can give up the duel.')
            return

        # no pending submissions allowed
        if highrated_timestamp == _DUEL_STATUS_TESTING or lowrated_timestamp == _DUEL_STATUS_TESTING:
            await ctx.send(f'Wait a bit, {ctx.author.mention}. A submission is still being judged.')
            return

        # only if the high rated has already finished
        if highrated_timestamp == _DUEL_STATUS_UNSOLVED:
            await ctx.send(f'You can\'t give up the duel if the higher rated user has not finished the problem.')
            return

        # end the duel and declare high rated as winner
        winner = highrated_member 
        loser = lowrated_member
        win_status = Winner.CHALLENGER if winner == challenger else Winner.CHALLENGEE
        win_time = highrated_timestamp       
        embed = complete_duel(duelid, ctx.guild.id, win_status,
                            winner, loser, win_time, 1, dtype)
        await ctx.send(f'{loser.mention} gave up. {winner.mention} won the duel against {loser.mention}!', embed=embed)

    async def _check_duel_complete(self, guild, channel, data, isAutoComplete = False):
        duelid, challenger_id, challengee_id, start_timestamp, problem_name, contest_id, index, dtype = data

        # get discord member
        challenger = guild.get_member(challenger_id)
        challengee = guild.get_member(challengee_id)

         # get cf handles and cf.Users
        userids = [challenger_id, challengee_id]
        handles = [cf_common.user_db.get_handle(
            userid, guild.id) for userid in userids]
        users = [cf_common.user_db.fetch_cf_user(handle) for handle in handles] 
        
        highrated_user = users[0] if users[0].effective_rating > users[1].effective_rating else users[1]
        lowrated_user = users[1] if users[0].effective_rating > users[1].effective_rating else users[0]
        highrated_member = challenger if users[0].effective_rating > users[1].effective_rating else challengee
        lowrated_member = challengee if users[0].effective_rating > users[1].effective_rating else challenger
        higherrated_rating, lowerrated_rating = highrated_user.effective_rating, lowrated_user.effective_rating
        highrated_timestamp = await self._get_solve_time(highrated_user.handle, contest_id, index)
        lowrated_timestamp = await self._get_solve_time(lowrated_user.handle, contest_id, index) 


        # no pending submissions allowed
        if highrated_timestamp == _DUEL_STATUS_TESTING or lowrated_timestamp == _DUEL_STATUS_TESTING:
            if not isAutoComplete:
                await channel.send(f'Wait a bit. A submission is still being judged.')
            return

        # get problem including rating
        problem = [prob for prob in cf_common.cache2.problem_cache.problems
                   if prob.name == problem_name]

        adjusted = False
        coeff = 1.0

        #for adjusted duels we calc coefficient and set flag
        if dtype == DuelType.ADJUNOFFICIAL or dtype == DuelType.ADJOFFICIAL:
            coeff = _get_coefficient(problem[0].rating, lowerrated_rating, higherrated_rating)
            adjusted = True

        # if lower rated finished first -> win for him
        # if higher rated finished first
        #       if lower rated is also done -> check times and announce winner
        #       if lower rated is still missing -> make timer till his time is over and check again
        if highrated_timestamp and lowrated_timestamp:
            highrated_duration = highrated_timestamp - start_timestamp
            lowerrated_duration = lowrated_timestamp - start_timestamp
            if highrated_duration*coeff != lowerrated_duration: 
                if highrated_duration * coeff < lowerrated_duration:
                    winner = highrated_member
                    loser = lowrated_member
                    win_time = highrated_timestamp
                else:
                    winner = lowrated_member
                    loser = highrated_member
                    win_time = lowrated_timestamp

                diff = cf_common.pretty_time_format(
                abs(highrated_duration * coeff - lowerrated_duration), always_seconds=True)                    
                win_status = Winner.CHALLENGER if winner == challenger else Winner.CHALLENGEE
                embed = complete_duel(duelid, guild.id, win_status, winner, loser, win_time, 1, dtype)
                if adjusted:
                    await channel.send(f"Both {challenger.mention} and {challengee.mention} solved it. But {winner.mention} was {diff} faster than the adjusted time limit!", embed=embed)
                else: 
                    await channel.send(f'Both {challenger.mention} and {challengee.mention} solved it but {winner.mention} was {diff} faster!', embed=embed)
            else:
                embed = complete_duel(duelid, guild.id, Winner.DRAW,
                                      challenger, challengee, highrated_timestamp, 0.5, dtype)
                if adjusted:
                    await channel.send(f"{challenger.mention} and {challengee.mention} solved the problem with the same adjusted time! It's a draw!", embed=embed)
                else: 
                    await channel.send(f"{challenger.mention} and {challengee.mention} solved the problem in the exact same amount of time! It's a draw!", embed=embed)
        elif highrated_timestamp: # special handling since we cant know if lowrated will still solve within time
            highrated_duration = highrated_timestamp - start_timestamp
            lowerrated_duration = highrated_duration * coeff
            current_duration = datetime.datetime.now().timestamp() - start_timestamp
            if current_duration >= lowerrated_duration: # we can make a decision, higher rated won
                winner = highrated_member 
                loser = lowrated_member
                win_status = Winner.CHALLENGER if winner == challenger else Winner.CHALLENGEE
                win_time = highrated_timestamp
                embed = complete_duel(duelid, guild.id, win_status,
                                    winner, loser, win_time, 1, dtype)
                await channel.send(f'{winner.mention} beat {loser.mention} in a duel!', embed=embed)
            else:
                time_remaining = lowerrated_duration - current_duration
                time_remaining_formatted = cf_common.pretty_time_format(
                    time_remaining, always_seconds=True)
                if not isAutoComplete:
                    await channel.send(f'{highrated_member.mention} solved it but {lowrated_member.mention} still has {time_remaining_formatted} to solve the problem! Bot will check automatically if the problem has been solved or time is up. {lowrated_member.mention} can also invoke `;duel giveup` if they want to give up.')

        elif lowrated_timestamp:
            winner = lowrated_member 
            loser = highrated_member
            win_status = Winner.CHALLENGER if winner == challenger else Winner.CHALLENGEE
            win_time = lowrated_timestamp
            embed = complete_duel(duelid, guild.id, win_status,
                                  winner, loser, win_time, 1, dtype)
            await channel.send(f'{winner.mention} beat {loser.mention} in a duel!', embed=embed)
        else:
            if not isAutoComplete:
                await channel.send('Nobody solved the problem yet.')


    @duel.command(brief='Complete a duel. Can be used after the problem was solved by one of the duelists.')
    async def complete(self, ctx):
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        active = cf_common.user_db.check_duel_complete(ctx.author.id, ctx.guild.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not in a duel.')

        await self._check_duel_complete(ctx.guild, ctx.channel, active)

    @duel.command(brief='Offer a draw or accept a draw offer.')
    async def draw(self, ctx):
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        active = cf_common.user_db.check_duel_draw(ctx.author.id, ctx.guild.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not in a duel.')

        duelid, challenger_id, challengee_id, start_time, dtype = active
        now = datetime.datetime.now().timestamp()
        if now - start_time < _DUEL_NO_DRAW_TIME:
            draw_time = cf_common.pretty_time_format(
                start_time + _DUEL_NO_DRAW_TIME - now)
            await ctx.send(f'Think more {ctx.author.mention}. You can offer a draw in {draw_time}.')
            return

        if not duelid in self.draw_offers:
            self.draw_offers[duelid] = ctx.author.id
            offeree_id = challenger_id if ctx.author.id != challenger_id else challengee_id
            offeree = ctx.guild.get_member(offeree_id)
            await ctx.send(f'{ctx.author.mention} is offering a draw to {offeree.mention}!')
            return

        if self.draw_offers[duelid] == ctx.author.id:
            await ctx.send(f'{ctx.author.mention}, you\'ve already offered a draw.')
            return

        offerer = ctx.guild.get_member(self.draw_offers[duelid])
        embed = complete_duel(duelid, ctx.guild.id, Winner.DRAW,
                              offerer, ctx.author, now, 0.5, dtype)
        await ctx.send(f'{ctx.author.mention} accepted draw offer by {offerer.mention}.', embed=embed)

    @duel.command(brief='Show duelist profile page')
    async def profile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        
        if not cf_common.user_db.is_duelist(member.id, ctx.guild.id):
            raise DuelCogError(
                f'{member.mention} has not done any duels.')

        user = get_cf_user(member.id, ctx.guild.id)
        rating = cf_common.user_db.get_duel_rating(member.id, ctx.guild.id)
        desc = f'Duelist profile of {rating2rank(rating).title} {member.mention} aka **[{user.handle}]({user.url})**'
        embed = discord.Embed(
            description=desc, color=rating2rank(rating).color_embed)
        embed.add_field(name='Rating', value=rating, inline=True)

        wins = cf_common.user_db.get_duel_wins(member.id, ctx.guild.id)
        num_wins = len(wins)
        embed.add_field(name='Wins', value=num_wins, inline=True)
        num_losses = cf_common.user_db.get_num_duel_losses(member.id, ctx.guild.id)
        embed.add_field(name='Losses', value=num_losses, inline=True)
        num_draws = cf_common.user_db.get_num_duel_draws(member.id, ctx.guild.id)
        embed.add_field(name='Draws', value=num_draws, inline=True)
        num_declined = cf_common.user_db.get_num_duel_declined(member.id, ctx.guild.id)
        embed.add_field(name='Declined', value=num_declined, inline=True)
        num_rdeclined = cf_common.user_db.get_num_duel_rdeclined(member.id, ctx.guild.id)
        embed.add_field(name='Got declined', value=num_rdeclined, inline=True)

        def duel_to_string(duel):
            start_time, finish_time, problem_name, challenger, challengee = duel
            duel_time = cf_common.pretty_time_format(
                finish_time - start_time, shorten=True, always_seconds=True)
            when = cf_common.days_ago(start_time)
            loser_id = challenger if member.id != challenger else challengee
            loser = get_cf_user(loser_id, ctx.guild.id)
            problem = cf_common.cache2.problem_cache.problem_by_name[problem_name]
            return f'**[{problem.name}]({problem.url})** [{problem.rating}] versus [{loser.handle}]({loser.url}) {when} in {duel_time}'

        if wins:
            # sort by finish_time - start_time
            wins.sort(key=lambda duel: duel[1] - duel[0])
            embed.add_field(name='Fastest win',
                            value=duel_to_string(wins[0]), inline=False)
            embed.add_field(name='Slowest win',
                            value=duel_to_string(wins[-1]), inline=False)

        embed.set_thumbnail(url=f'{user.titlePhoto}')
        await ctx.send(embed=embed)

    def _paginate_duels(self, data, message, guild_id, show_id):
        def make_line(entry):
            duelid, start_time, finish_time, name, challenger, challengee, winner = entry
            duel_time = cf_common.pretty_time_format(
                finish_time - start_time, shorten=True, always_seconds=True)
            problem = cf_common.cache2.problem_cache.problem_by_name[name]
            when = cf_common.days_ago(start_time)
            idstr = f'{duelid}: '
            if winner != Winner.DRAW:
                loser = get_cf_user(challenger if winner ==
                                    Winner.CHALLENGEE else challengee, guild_id)
                winner = get_cf_user(challenger if winner ==
                                     Winner.CHALLENGER else challengee, guild_id)
                if (winner == None and loser == None):
                    return f'{idstr if show_id else str()}[{name}]({problem.url}) [{problem.rating}] won by [unknown] vs [unknown] {when} in {duel_time}'
                if (loser == None):
                    return f'{idstr if show_id else str()}[{name}]({problem.url}) [{problem.rating}] won by [{winner.handle}]({winner.url}) vs [unknown] {when} in {duel_time}'
                if (winner == None):
                    return f'{idstr if show_id else str()}[{name}]({problem.url}) [{problem.rating}] won by [unknown] vs [{loser.handle}]({loser.url}) {when} in {duel_time}'
                return f'{idstr if show_id else str()}[{name}]({problem.url}) [{problem.rating}] won by [{winner.handle}]({winner.url}) vs [{loser.handle}]({loser.url}) {when} in {duel_time}'
            else:
                challenger = get_cf_user(challenger, guild_id)
                challengee = get_cf_user(challengee, guild_id)
                if (challenger == None and challengee == None):
                    return f'{idstr if show_id else str()}[{name}]({problem.url}) [{problem.rating}] drawn by [unknown] vs [unknown] {when} after {duel_time}'
                if (challenger == None):
                    return f'{idstr if show_id else str()}[{name}]({problem.url}) [{problem.rating}] drawn by [unknown] vs [{challengee.handle}]({challengee.url}) {when} after {duel_time}'
                if (challengee == None):
                    return f'{idstr if show_id else str()}[{name}]({problem.url}) [{problem.rating}] drawn by [{challenger.handle}]({challenger.url}) vs [unknown] {when} after {duel_time}'
                return f'{idstr if show_id else str()}[{name}]({problem.url}) [{problem.rating}] drawn by [{challenger.handle}]({challenger.url}) and [{challengee.handle}]({challengee.url}) {when} after {duel_time}'

        def make_page(chunk):
            log_str = '\n'.join(make_line(entry) for entry in chunk)
            embed = discord_common.cf_color_embed(description=log_str)
            return message, embed

        if not data:
            raise DuelCogError('There are no duels to show.')

        return [make_page(chunk) for chunk in paginator.chunkify(data, 7)]

    @duel.command(brief='Print head to head dueling history',
                  aliases=['versushistory'])
    async def vshistory(self, ctx, member1: discord.Member = None, member2: discord.Member = None):
        if not member1:
            raise DuelCogError(
                f'You need to specify one or two discord members.')

        member2 = member2 or ctx.author
        data = cf_common.user_db.get_pair_duels(member1.id, member2.id, ctx.guild.id)
        w, l, d = 0, 0, 0
        for _, _, _, _, challenger, challengee, winner in data:
            if winner != Winner.DRAW:
                winnerid = challenger if winner == Winner.CHALLENGER else challengee
                if winnerid == member1.id:
                    w += 1
                else:
                    l += 1
            else:
                d += 1
        message = discord.utils.escape_mentions(f'`{member1.display_name}` ({w}/{d}/{l}) `{member2.display_name}`')
        pages = self._paginate_duels(
            data, message, ctx.guild.id, False)
        paginator.paginate(self.bot, ctx.channel, pages,
                           wait_time=5 * 60, set_pagenum_footers=True)

    @duel.command(brief='Print user dueling history')
    async def history(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        data = cf_common.user_db.get_duels(member.id, ctx.guild.id)
        message = discord.utils.escape_mentions(f'dueling history of `{member.display_name}`')
        pages = self._paginate_duels(
            data, message, ctx.guild.id, False)
        paginator.paginate(self.bot, ctx.channel, pages,
                           wait_time=5 * 60, set_pagenum_footers=True)

    @duel.command(brief='Print a list of recent duels.')
    async def recent(self, ctx):
        data = cf_common.user_db.get_recent_duels(ctx.guild.id)
        pages = self._paginate_duels(
            data, 'list of recent duels', ctx.guild.id, True)
        paginator.paginate(self.bot, ctx.channel, pages,
                           wait_time=5 * 60, set_pagenum_footers=True)

    @duel.command(brief='Print list of ongoing duels.')
    async def ongoing(self, ctx, member: discord.Member = None):
        def make_line(entry):
            _, challenger, challengee, start_time, name, _, _, _ = entry
            problem = cf_common.cache2.problem_cache.problem_by_name[name]
            now = datetime.datetime.now().timestamp()
            when = cf_common.pretty_time_format(
                now - start_time, shorten=True, always_seconds=True)
            challenger = get_cf_user(challenger, ctx.guild.id)
            challengee = get_cf_user(challengee, ctx.guild.id)
            return f'[{challenger.handle}]({challenger.url}) vs [{challengee.handle}]({challengee.url}): [{name}]({problem.url}) [{problem.rating}] {when}'

        def make_page(chunk):
            message = f'List of ongoing duels:'
            log_str = '\n'.join(make_line(entry) for entry in chunk)
            embed = discord_common.cf_color_embed(description=log_str)
            return message, embed

        member = member or ctx.author
        data = cf_common.user_db.get_ongoing_duels(ctx.guild.id)
        if not data:
            raise DuelCogError('There are no ongoing duels.')

        pages = [make_page(chunk) for chunk in paginator.chunkify(data, 7)]
        paginator.paginate(self.bot, ctx.channel, pages,
                           wait_time=5 * 60, set_pagenum_footers=True)

    @duel.command(brief="Show duelists")
    async def ranklist(self, ctx):
        """Show the list of duelists with their duel rating."""
        users = [(ctx.guild.get_member(user_id), rating)
                 for user_id, rating in cf_common.user_db.get_duelists(ctx.guild.id)]
        users = [(member, cf_common.user_db.get_handle(member.id, ctx.guild.id), rating)
                 for member, rating in users
                 if member is not None and cf_common.user_db.get_num_duel_completed(member.id, ctx.guild.id) > 0]

        _PER_PAGE = 10

        def make_page(chunk, page_num):
            style = table.Style('{:>}  {:<}  {:<}  {:<}')
            t = table.Table(style)
            t += table.Header('#', 'Name', 'Handle', 'Rating')
            t += table.Line()
            for index, (member, handle, rating) in enumerate(chunk):
                rating_str = f'{rating} ({rating2rank(rating).title_abbr})'

                handlestr = 'Unknown'
                if (handle is not None):
                    handlestr = handle
                t += table.Data(_PER_PAGE * page_num + index + 1,
                                f'{member.display_name}', handlestr, rating_str)

            table_str = f'```\n{t}\n```'
            embed = discord_common.cf_color_embed(description=table_str)
            return 'List of duelists', embed

        if not users:
            raise DuelCogError('There are no active duelists.')

        pages = [make_page(chunk, k) for k, chunk in enumerate(
            paginator.chunkify(users, _PER_PAGE))]
        paginator.paginate(self.bot, ctx.channel, pages,
                           wait_time=5 * 60, set_pagenum_footers=True)

    async def invalidate_duel(self, ctx, duelid, challenger_id, challengee_id): 
        rc = cf_common.user_db.invalidate_duel(duelid, ctx.guild.id)
        if rc == 0:
            raise DuelCogError(f'Unable to invalidate duel {duelid}.')

        challenger = ctx.guild.get_member(challenger_id)
        challengee = ctx.guild.get_member(challengee_id)
        await ctx.send(f'Duel between {challenger.mention} and {challengee.mention} has been invalidated.')

    @duel.command(brief='Invalidate the duel. Can be used within 2 minutes after the duel has been started.')
    async def invalidate(self, ctx): # @@@ TODO: broken with new duel types
        """Declare your duel invalid. Use this if you've solved the problem prior to the duel.
        You can only use this functionality during the first 120 seconds of the duel."""
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        active = cf_common.user_db.check_duel_complete(ctx.author.id, ctx.guild.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not in a duel.')

        duelid, challenger_id, challengee_id, start_time, _, _, _, _ = active
        if datetime.datetime.now().timestamp() - start_time > _DUEL_INVALIDATE_TIME:
            raise DuelCogError(
                f'{ctx.author.mention}, you can no longer invalidate your duel.')
        await self.invalidate_duel(ctx, duelid, challenger_id, challengee_id)

    @duel.command(brief='Invalidate a duel', usage='[duelist]')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def _invalidate(self, ctx, member: discord.Member):
        """Declare an ongoing duel invalid."""
        active = cf_common.user_db.check_duel_complete(member.id, ctx.guild.id)
        if not active:
            raise DuelCogError(f'{member.mention} is not in a duel.')

        duelid, challenger_id, challengee_id, _, _, _, _, _ = active
        await self.invalidate_duel(ctx, duelid, challenger_id, challengee_id)

    # TODO: Add _invalidate by cfhandle
     
    # rating does not plot rating changes through lockouts
    @duel.command(brief='Plot rating', usage='[duelist]')
    async def rating(self, ctx, *members: discord.Member):
        """Plot duelist's rating."""
        members = members or (ctx.author, )
        if len(members) > 5:
            raise DuelCogError(f'Cannot plot more than 5 duelists at once.')

        duelists = [member.id for member in members]
        duels = cf_common.user_db.get_complete_official_duels(ctx.guild.id)
        rating = dict()
        plot_data = defaultdict(list)
        time_tick = 0
        for challenger, challengee, winner, finish_time in duels:
            challenger_r = rating.get(challenger, 1500)
            challengee_r = rating.get(challengee, 1500)
            if winner == Winner.CHALLENGER:
                delta = round(elo_delta(challenger_r, challengee_r, 1))
            elif winner == Winner.CHALLENGEE:
                delta = round(elo_delta(challenger_r, challengee_r, 0))
            else:
                delta = round(elo_delta(challenger_r, challengee_r, 0.5))

            rating[challenger] = challenger_r + delta
            rating[challengee] = challengee_r - delta
            if challenger in duelists or challengee in duelists:
                if challenger in duelists:
                    plot_data[challenger].append(
                        (time_tick, rating[challenger]))
                if challengee in duelists:
                    plot_data[challengee].append(
                        (time_tick, rating[challengee]))
                time_tick += 1

        if time_tick == 0:
            raise DuelCogError(f'Nothing to plot.')

        plt.clf()
        # plot at least from mid gray to mid purple
        min_rating = 1350
        max_rating = 1550
        for rating_data in plot_data.values():
            for tick, rating in rating_data:
                min_rating = min(min_rating, rating)
                max_rating = max(max_rating, rating)

            x, y = zip(*rating_data)
            plt.plot(x, y,
                     linestyle='-',
                     marker='o',
                     markersize=2,
                     markerfacecolor='white',
                     markeredgewidth=0.5)

        gc.plot_rating_bg(DUEL_RANKS)
        plt.xlim(0, time_tick - 1)
        plt.ylim(min_rating - 100, max_rating + 100)

        labels = [
            gc.StrWrap('{} ({})'.format(
                ctx.guild.get_member(duelist).display_name,
                rating_data[-1][1]))
            for duelist, rating_data in plot_data.items()
        ]
        plt.legend(labels, loc='upper left', prop=gc.fontprop)

        discord_file = gc.get_current_figure_as_file()
        embed = discord_common.cf_color_embed(title='Duel rating graph')
        discord_common.attach_image(embed, discord_file)
        discord_common.set_author_footer(embed, ctx.author)
        await ctx.send(embed=embed, file=discord_file)

    @discord_common.send_error_if(DuelCogError, cf_common.ResolveHandleError)
    async def cog_command_error(self, ctx, error):
        pass


async def setup(bot):
    await bot.add_cog(Dueling(bot))
