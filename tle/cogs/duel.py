import random
import datetime
import discord
import asyncio
import itertools

from discord.ext import commands
from tle.util.db.user_db_conn import Duel, Winner
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import paginator
from tle.util import discord_common
from tle.util import table

_DUEL_EXPIRY_TIME = 5 * 60
_DUEL_RATING_DELTA = -400
_DUEL_NO_DRAW_TIME = 30 * 60
_ELO_CONSTANT = 60

class DuelCogError(commands.CommandError):
    pass

def elo_prob(player, opponent):
    return (1 + 10**((opponent - player) / 400))**-1

def elo_delta(player, opponent, win):
    return _ELO_CONSTANT * (win - elo_prob(player, opponent))

def get_cf_user(userid):
    handle = cf_common.user_db.gethandle(userid)
    return cf_common.user_db.fetch_cfuser(handle)

def complete_duel(duelid, win_status, winner, loser, finish_time, score):
    winner_r = cf_common.user_db.get_duel_rating(winner.id)
    loser_r = cf_common.user_db.get_duel_rating(loser.id)
    delta = round(elo_delta(winner_r, loser_r, score))
    rc = cf_common.user_db.complete_duel(duelid, win_status, finish_time, winner.id, loser.id, delta)
    if rc == 0:
        raise DuelCogError('Hey! No cheating!')

    winner_cf = get_cf_user(winner.id)
    loser_cf = get_cf_user(loser.id)
    desc = f'Rating change after **[{winner_cf.handle}]({winner_cf.url})** vs **[{loser_cf.handle}]({loser_cf.url})**:'
    embed = discord_common.cf_color_embed(description=desc)
    embed.add_field(name=f'{winner.display_name}', value=f'{winner_r} -> {winner_r + delta}', inline=False)
    embed.add_field(name=f'{loser.display_name}', value=f'{loser_r} -> {loser_r - delta}', inline=False)
    return embed

class Dueling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()
        self.draw_offers = {}

    @commands.group(brief='Duel commands',
                    invoke_without_command=True)
    async def duel(self, ctx):
        """Group for commands pertaining to duels"""
        await ctx.send_help(ctx.command)

    @duel.command(brief='Register a duelist')
    @commands.has_role('Admin')
    async def register(self, ctx, member: discord.Member):
        """Register a duelist"""
        cf_common.user_db.register_duelist(member.id)
        await ctx.send(f'{member.mention} successfully registered as a duelist.')

    @duel.command(brief='Challenge to a duel')
    async def challenge(self, ctx, opponent: discord.Member):
        """Challenge another server member to a duel. Problem difficulty will be the lesser of duelist ratings minus 400."""
        challenger_id = ctx.author.id
        challengee_id = opponent.id

        if not cf_common.user_db.is_duelist(challenger_id):
            raise DuelCogError(f'{ctx.author.mention}, you are not a registered duelist!')
        if not cf_common.user_db.is_duelist(challengee_id):
            raise DuelCogError(f'{opponent.display_name} is not a registered duelist!')
        if challenger_id == challengee_id:
            raise DuelCogError(f'{ctx.author.mention}, you cannot challenge yourself!')
        if cf_common.user_db.check_duel_challenge(challenger_id):
            raise DuelCogError(f'{ctx.author.mention}, you are currently in a duel!')
        if cf_common.user_db.check_duel_challenge(challengee_id):
            raise DuelCogError(f'{opponent.display_name} is currently in a duel!')

        issue_time = datetime.datetime.now().timestamp()
        duelid = cf_common.user_db.create_duel(challenger_id, challengee_id, issue_time)
        await ctx.send(f'{ctx.author.mention} is challenging {opponent.mention} to a duel!')
        await asyncio.sleep(_DUEL_EXPIRY_TIME)
        if cf_common.user_db.cancel_duel(duelid, Duel.EXPIRED):
            await ctx.send(f'{ctx.author.mention}, your request to duel {opponent.display_name} has expired!')

    @duel.command(brief='Decline a duel')
    async def decline(self, ctx):
        active = cf_common.user_db.check_duel_decline(ctx.author.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not being challenged!')

        duelid, challenger = active
        challenger = ctx.guild.get_member(challenger)
        cf_common.user_db.cancel_duel(duelid, Duel.DECLINED)
        await ctx.send(f'{ctx.author.display_name} declined a challenge by {challenger.mention}.')

    @duel.command(brief='Withdraw a challenge')
    async def withdraw(self, ctx):
        active = cf_common.user_db.check_duel_withdraw(ctx.author.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not challenging anyone.')

        duelid, challengee = active
        challengee = ctx.guild.get_member(challengee)
        cf_common.user_db.cancel_duel(duelid, Duel.WITHDRAWN)
        await ctx.send(f'{ctx.author.mention} withdrew a challenge to {challengee.display_name}.')

    @duel.command(brief='Accept a duel')
    async def accept(self, ctx):
        active = cf_common.user_db.check_duel_accept(ctx.author.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not being challenged.')

        duelid, challenger_id = active
        challenger = ctx.guild.get_member(challenger_id)
        await ctx.send(f'Duel between {challenger.mention} and {ctx.author.mention} starting in 15 seconds!')
        await asyncio.sleep(15)

        await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author), '!' + str(challenger)))
        userids = [ctx.author.id, challenger_id]
        handles = [cf_common.user_db.gethandle(userid) for userid in userids]
        users = [cf_common.user_db.fetch_cfuser(handle) for handle in handles]
        lowest_rating = min(user.rating for user in users)
        rating = max(round(lowest_rating, -2) + _DUEL_RATING_DELTA, 500)

        submissions = [await cf.user.status(handle=handle) for handle in handles]
        solved = {sub.problem.name for subs in submissions for sub in subs if sub.verdict == 'OK'}
        def get_problems(rating):
            return [prob for prob in cf_common.cache2.problem_cache.problems
                    if prob.rating == rating and prob.name not in solved
                    and not any(cf_common.is_contest_writer(prob.contestId, handle) for handle in handles)
                    and not cf_common.is_nonstandard_problem(prob)]

        ratings = itertools.chain(range(rating, 400, -100), range(rating + 100, 3900, 100))
        for problems in map(get_problems, ratings):
            if problems:
                break

        if not problems:
            raise DuelCogError(f'No unsolved problems left for {challenger.mention} vs {ctx.author.mention}.')

        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds)

        choice = max(random.randrange(len(problems)) for _ in range(2))
        problem = problems[choice]
        start_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.start_duel(duelid, start_time, problem)
        if rc != 1:
            raise DuelCogError(f'Unable to start the duel between {challenger.mention} and {ctx.author.mention}.')

        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache2.contest_cache.get_contest(problem.contestId).name
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'Starting duel: {challenger.mention} vs {ctx.author.mention}', embed=embed)

    @duel.command(brief='Complete a duel')
    async def complete(self, ctx):
        active = cf_common.user_db.check_duel_complete(ctx.author.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not in a duel.')

        duelid, challenger_id, challengee_id, start_time, problem_name, contest_id, index = active

        UNSOLVED = 0
        TESTING = -1
        async def get_solve_time(userid):
            handle = cf_common.user_db.gethandle(userid)
            subs = [sub for sub in await cf.user.status(handle=handle)
                    if (sub.verdict == 'OK' or sub.verdict == 'TESTING')
                    and sub.problem.contestId == contest_id
                    and sub.problem.index == index]

            if not subs:
                return UNSOLVED
            if 'TESTING' in [sub.verdict for sub in subs]:
                return TESTING
            return min(subs, key=lambda sub: sub.creationTimeSeconds).creationTimeSeconds

        challenger_time = await get_solve_time(challenger_id)
        challengee_time = await get_solve_time(challengee_id)

        if challenger_time == TESTING or challengee_time == TESTING:
            await ctx.send(f'Wait a bit, {ctx.author.mention}. A submission is still being judged.')
            return

        challenger = ctx.guild.get_member(challenger_id)
        challengee = ctx.guild.get_member(challengee_id)

        if challenger_time and challengee_time:
            if challenger_time != challengee_time:
                diff = cf_common.pretty_time_format(abs(challengee_time - challenger_time), always_seconds=True)
                winner = challenger if challenger_time < challengee_time else challengee
                loser = challenger if challenger_time > challengee_time else challengee
                win_status = Winner.CHALLENGER if winner == challenger else Winner.CHALLENGEE
                embed = complete_duel(duelid, win_status, winner, loser, min(challenger_time, challengee_time), 1)
                await ctx.send(f'Both {challenger.mention} and {challengee.mention} solved it but {winner.mention} was {diff} faster!', embed=embed)
            else:
                embed = complete_duel(duelid, Winner.DRAW, challenger, challengee, challenger_time, 0.5)
                await ctx.send(f"{challenger.mention} and {challengee.mention} solved the problem in the exact same amount of time! It's a draw!", embed=embed)

        elif challenger_time:
            embed = complete_duel(duelid, Winner.CHALLENGER, challenger, challengee, challenger_time, 1)
            await ctx.send(f'{challenger.mention} beat {challengee.mention} in a duel!', embed=embed)
        elif challengee_time:
            embed = complete_duel(duelid, Winner.CHALLENGEE, challengee, challenger, challengee_time, 1)
            await ctx.send(f'{challengee.mention} beat {challenger.mention} in a duel!', embed=embed)
        else:
            await ctx.send('Nobody solved the problem yet.')

    @duel.command(brief='Offer/Accept a draw')
    async def draw(self, ctx):
        active = cf_common.user_db.check_duel_draw(ctx.author.id)
        if not active:
            raise DuelCogError(f'{ctx.author.mention}, you are not in a duel.')

        duelid, challenger_id, challengee_id, start_time = active
        now = datetime.datetime.now().timestamp()
        if now - start_time < _DUEL_NO_DRAW_TIME:
            draw_time = cf_common.pretty_time_format(start_time + _DUEL_NO_DRAW_TIME - now)
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
        embed = complete_duel(duelid, Winner.DRAW, offerer, ctx.author, now, 0.5)
        await ctx.send(f'{ctx.author.mention} accepted draw offer by {offerer.mention}.', embed=embed)

    @duel.command(brief='Show duelist profile')
    async def profile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        if not cf_common.user_db.is_duelist(member.id):
            raise DuelCogError(f'{member.display_name} is not a registered duelist.')

        user = get_cf_user(member.id)
        desc = f'Duelist profile of {member.mention} aka **[{user.handle}]({user.url})**'
        embed = discord.Embed(description=desc, color=user.rank.color_embed)

        rating = cf_common.user_db.get_duel_rating(member.id)
        embed.add_field(name='Rating', value=rating, inline=True)

        wins = cf_common.user_db.get_duel_wins(member.id)
        num_wins = len(wins)
        embed.add_field(name='Wins', value=num_wins, inline=True)
        num_losses = cf_common.user_db.get_num_duel_losses(member.id)
        embed.add_field(name='Losses', value=num_losses, inline=True)
        num_draws = cf_common.user_db.get_num_duel_draws(member.id)
        embed.add_field(name='Draws', value=num_draws, inline=True)
        num_declined = cf_common.user_db.get_num_duel_declined(member.id)
        embed.add_field(name='Declined', value=num_declined, inline=True)
        num_rdeclined = cf_common.user_db.get_num_duel_rdeclined(member.id)
        embed.add_field(name='Got declined', value=num_rdeclined, inline=True)

        def duel_to_string(duel):
            start_time, finish_time, problem_name, challenger, challengee = duel
            duel_time = cf_common.pretty_time_format(finish_time - start_time, shorten=True, always_seconds=True)
            when = cf_common.days_ago(start_time)
            loser_id = challenger if member.id != challenger else challengee
            loser = get_cf_user(loser_id)
            problem = cf_common.cache2.problem_cache.problem_by_name[problem_name]
            return f'**[{problem.name}]({problem.url})** [{problem.rating}] versus [{loser.handle}]({loser.url}) {when} in {duel_time}'

        if wins:
            # sort by finish_time - start_time
            wins.sort(key=lambda duel: duel[1] - duel[0])
            embed.add_field(name='Fastest win', value=duel_to_string(wins[0]), inline=False)
            embed.add_field(name='Slowest win', value=duel_to_string(wins[-1]), inline=False)

        embed.set_thumbnail(url=f'https:{user.titlePhoto}')
        await ctx.send(embed=embed)

    @duel.command(brief='Print user dueling history')
    async def history(self, ctx, member: discord.Member = None):
        def make_line(entry):
            start_time, finish_time, name, challenger, challengee, winner = entry
            duel_time = cf_common.pretty_time_format(finish_time - start_time, shorten=True, always_seconds=True)
            problem = cf_common.cache2.problem_cache.problem_by_name[name]
            when = cf_common.days_ago(start_time)
            if winner != Winner.DRAW:
                loser = get_cf_user(challenger if winner == Winner.CHALLENGEE else challengee)
                winner = get_cf_user(challenger if winner == Winner.CHALLENGER else challengee)
                return f'[{name}]({problem.url}) [{problem.rating}] won by [{winner.handle}]({winner.url}) vs [{loser.handle}]({loser.url}) {when} in {duel_time}'
            else:
                challenger = get_cf_user(challenger)
                challengee = get_cf_user(challengee)
                return f'[{name}]({problem.url}) [{problem.rating}] drawn by [{challenger.handle}]({challenger.url}) and [{challengee.handle}]({challengee.url}) {when} after {duel_time}'

        def make_page(chunk):
            message = f'dueling history of {member.display_name}'
            log_str = '\n'.join(make_line(entry) for entry in chunk)
            embed = discord_common.cf_color_embed(description=log_str)
            return message, embed

        member = member or ctx.author
        data = cf_common.user_db.get_duels(member.id)
        if not data:
            raise DuelCogError(f'{member.display_name} has no dueling history.')

        pages = [make_page(chunk) for chunk in paginator.chunkify(data, 7)]
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=5 * 60, set_pagenum_footers=True)

    @duel.command(brief="Show duelists")
    async def ranklist(self, ctx):
        """Show the list of duelists with their duel rating."""
        res = cf_common.user_db.get_duelists()
        style = table.Style('{:>}  {:<}  {:<}  {:<}')
        t = table.Table(style)
        t += table.Header('#', 'Name', 'Handle', 'Rating')
        t += table.Line()
        index = 0
        for user_id, rating in res:
            member = ctx.guild.get_member(user_id)
            if member is None:
                continue

            handle = cf_common.user_db.gethandle(user_id)
            t += table.Data(index, f'{member.display_name}', handle, rating)
            index += 1

        if index == 0:
            await ctx.send('```There are no active duelists.```')
        else:
            await ctx.send('```\n' + str(t) + '\n```')

    async def cog_command_error(self, ctx, error):
        if isinstance(error, DuelCogError):
            await ctx.send(embed=discord_common.embed_alert(error))
            error.handled = True


def setup(bot):
    bot.add_cog(Dueling(bot))
