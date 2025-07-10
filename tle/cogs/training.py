import random
from enum import IntEnum
import discord
from discord.ext import commands
import datetime

from tle import constants
from tle.util.db.user_db_conn import Training, TrainingProblemStatus
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common

# stuff for drawing image
import html
import io
import cairo
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo

FONTS = [
    'Noto Sans',
    'Noto Sans CJK JP',
    'Noto Sans CJK SC',
    'Noto Sans CJK TC',
    'Noto Sans CJK HK',
    'Noto Sans CJK KR',
]


_TRAINING_MIN_RATING_VALUE = 800
_TRAINING_MAX_RATING_VALUE = 3500


class TrainingMode(IntEnum):
    NORMAL = 0
    SURVIVAL = 1
    TIMED15 = 2
    TIMED30 = 3
    TIMED60 = 4
    TIMED1 = 5


class TrainingResult(IntEnum):
    SOLVED = 0
    TOOSLOW = 1
    SKIPPED = 2
    INVALIDATED = 3


class TrainingCogError(commands.CommandError):
    pass

def rating_to_color(rating):
    """returns (r, g, b) pixels values corresponding to rating"""
    # TODO: Integrate these colors with the ranks in codeforces_api.py
    BLACK = (10, 10, 10)
    RED = (255, 20, 20)
    BLUE = (0, 0, 200)
    GREEN = (0, 140, 0)
    ORANGE = (250, 140, 30)
    PURPLE = (160, 0, 120)
    CYAN = (0, 165, 170)
    GREY = (70, 70, 70)
    if rating is None or rating=='N/A':
        return BLACK
    if rating < 1200:
        return GREY
    if rating < 1400:
        return GREEN
    if rating < 1600:
        return CYAN
    if rating < 1900:
        return BLUE
    if rating < 2100:
        return PURPLE
    if rating < 2400:
        return ORANGE
    return RED



def get_fastest_solves_image(rankings):
    """return PIL image for rankings"""
    SMOKE_WHITE = (250, 250, 250)
    BLACK = (0, 0, 0)

    DISCORD_GRAY = (.212, .244, .247)

    ROW_COLORS = ((0.95, 0.95, 0.95), (0.9, 0.9, 0.9))

    WIDTH = 1000
    #HEIGHT = 900
    BORDER_MARGIN = 20
    COLUMN_MARGIN = 10
    HEADER_SPACING = 1.25
    WIDTH_RANK = 0.10*WIDTH
    WIDTH_NAME = 0.35*WIDTH
    LINE_HEIGHT = 40#(HEIGHT - 2*BORDER_MARGIN)/(20 + HEADER_SPACING)
    HEIGHT = int((len(rankings) + HEADER_SPACING) * LINE_HEIGHT + 2*BORDER_MARGIN)
    # Cairo+Pango setup
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    context = cairo.Context(surface)
    context.set_line_width(1)
    context.set_source_rgb(*DISCORD_GRAY)
    context.rectangle(0, 0, WIDTH, HEIGHT)
    context.fill()
    layout = PangoCairo.create_layout(context)
    layout.set_font_description(Pango.font_description_from_string(','.join(FONTS) + ' 20'))
    layout.set_ellipsize(Pango.EllipsizeMode.END)

    def draw_bg(y, color_index):
        nxty = y + LINE_HEIGHT

        # Simple
        context.move_to(BORDER_MARGIN, y)
        context.line_to(WIDTH, y)
        context.line_to(WIDTH, nxty)
        context.line_to(0, nxty)
        context.set_source_rgb(*ROW_COLORS[color_index])
        context.fill()

    def draw_row(pos, username, handle, rating, color, y, bold=False):
        context.set_source_rgb(*[x/255.0 for x in color])

        context.move_to(BORDER_MARGIN, y)

        def draw(text, width=-1):
            text = html.escape(text)
            if bold:
                text = f'<b>{text}</b>'
            layout.set_width((width - COLUMN_MARGIN)*1000) # pixel = 1000 pango units
            layout.set_markup(text, -1)
            PangoCairo.show_layout(context, layout)
            context.rel_move_to(width, 0)

        draw(pos, WIDTH_RANK)
        draw(username, WIDTH_NAME)
        draw(handle, WIDTH_NAME)
        draw(rating)

    #

    y = BORDER_MARGIN

    # draw header
    draw_row('Rating', 'Name', 'Handle', 'Time', SMOKE_WHITE, y, bold=True)
    y += LINE_HEIGHT*HEADER_SPACING

    for i, (pos, name, handle, rating, time) in enumerate(rankings):
        color = rating_to_color(rating)
        draw_bg(y, i%2)
        timeFormatted = cf_common.pretty_time_format(time, shorten=True, always_seconds=True)
        draw_row(str(pos), f'{name}', f'{handle} ({rating if rating else "N/A"})' , timeFormatted, color, y)
        if rating and rating >= 3000:  # nutella
            draw_row('', name[0], handle[0], '', BLACK, y)
        y += LINE_HEIGHT

    image_data = io.BytesIO()
    surface.write_to_png(image_data)
    image_data.seek(0)
    discord_file = discord.File(image_data, filename='fastesttraining.png')
    return discord_file




class Game:
    def __init__(self, mode, score=None, lives=None, timeleft=None):
        self.mode = int(mode)
        # existing game
        if score is not None:
            self.score = int(score)
            self.lives = int(lives) if lives is not None else lives
            self.timeleft = int(timeleft) if timeleft is not None else timeleft
            self.alive = True if self.lives is None or self.lives > 0 else False
            return
        # else we init a new game
        self.timeleft = self._getBaseTime()
        self.lives = self._getBaseLives()
        self.alive = True
        self.score = int(0)

    def _getModeStr(self):
        if self.mode == TrainingMode.NORMAL:
            return "Infinite"
        elif self.mode == TrainingMode.SURVIVAL:
            return "Survival"
        elif self.mode == TrainingMode.TIMED1:
            return "Timed 1 mins"
        elif self.mode == TrainingMode.TIMED15:
            return "Timed 15 mins"
        elif self.mode == TrainingMode.TIMED30:
            return "Timed 30 mins"
        elif self.mode == TrainingMode.TIMED60:
            return "Timed 60 mins"

    def _getBaseLives(self):
        if self.mode == TrainingMode.NORMAL:
            return None
        else:
            return 3

    def _getBaseTime(self):
        if self.mode == TrainingMode.NORMAL or self.mode == TrainingMode.SURVIVAL:
            return None
        if self.mode == TrainingMode.TIMED1:
            return int(1*60+1)
        if self.mode == TrainingMode.TIMED15:
            return int(15*60+1)
        if self.mode == TrainingMode.TIMED30:
            return int(30*60+1)
        if self.mode == TrainingMode.TIMED60:
            return int(60*60+1)

    def _newRating(self, success, rating):
        newRating = rating
        if success == TrainingResult.SOLVED:
            newRating += 100
        else:
            newRating -= 100
        newRating = min(newRating, 3500)
        newRating = max(newRating, 800)
        return newRating

    def doSolved(self, rating, duration):
        rating = int(rating)
        success = TrainingResult.SOLVED
        if self.mode != TrainingMode.NORMAL and self.mode != TrainingMode.SURVIVAL:
            if duration > self.timeleft:
                success = TrainingResult.TOOSLOW
                self.lives -= 1
                self.timeleft = self._getBaseTime()
                if self.lives is not None and self.lives == 0:
                    self.alive = False
            else:
                self.score += 1
                self.timeleft = int(
                    min(self.timeleft - duration + self._getBaseTime(), 2*self._getBaseTime()))
        else:
            self.score += 1
        newRating = self._newRating(success, rating)
        return success, newRating

    def doSkip(self, rating, duration):
        rating = int(rating)
        success = TrainingResult.SKIPPED
        if self.mode != TrainingMode.NORMAL:
            self.lives -= 1
            if self.lives is not None and self.lives == 0:
                self.alive = False

        self.timeleft = self._getBaseTime()
        newRating = self._newRating(success, rating)
        return success, newRating

    def doFinish(self, rating, duration):
        success = TrainingResult.INVALIDATED
        self.alive = False
        return success, rating


class Training(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.converter = commands.MemberConverter()

    @commands.group(brief='Training commands',
                    invoke_without_command=True)
    async def training(self, ctx):
        """ A training is a game played against the bot. In this game the bot will assign you a codeforces problem that you should solve. If you manage to solve the problem the bot will assign you a harder problem. If you need to skip the problem the bot will lower the difficulty.
            You can start a game by using the ;training start command. The bot will assign you a codeforces problem that you should solve. If you manage to solve the problem you can do ;training solved and the bot will assign you a problem that is 100 points higher rated. If you need editorial / external help or have no idea how to solve it you can do ;training skip. The bot will reduce the difficulty of the next problem by 100 points.
            You may end your training at any time with ;training end
            The game is available in the following modes: 
            - infinite: Try to get as high as possible. You are allowed to skip any number of times. 
            - survival: Seeking for some thrill? In this mode you only have 3 lives (you can skip 3 problems). How far will you get?
            - time trial: Still bored? Prepare for the ultimate challenge: In this mode you will only have limited time to solve each problem. 
                          If you need to skip a problem or if you are too slow at solving the problem you will lose one of your 3 lives.
                          Available difficulty levels: timed15 (15 minutes for each problem), timed30 (30 minutes), timed60 (60 minutes)
                          You get some bonus time if you manage to solve a problem within the time limit.
            For further help on usage of a command do ;help training <command> (e.g. ;help training start)        
        """
        await ctx.send_help(ctx.command)

    def _checkIfCorrectChannel(self, ctx):
        training_channel_id = cf_common.user_db.get_training_channel(
            ctx.guild.id)
        if not training_channel_id or ctx.channel.id != training_channel_id:
            raise TrainingCogError(
                'You must use this command in training channel.')

    async def _getActiveTraining(self, user_id):
        active = cf_common.user_db.get_active_training(user_id)
        return active

    async def _getLatestTraining(self, user_id):
        latest = cf_common.user_db.get_latest_training(user_id)
        return latest

    def _extractArgs(self, args):
        mode = TrainingMode.NORMAL
        rating = 800
        unrecognizedArgs = []
        for arg in args:
            if arg.isdigit():
                rating = int(arg)
            elif arg == "infinite" or arg == "+infinite":
                mode = TrainingMode.NORMAL
            elif arg == "survival" or arg == "+survival":
                mode = TrainingMode.SURVIVAL
            elif arg == "timed15" or arg == "+timed15":
                mode = TrainingMode.TIMED15
            elif arg == "timed30" or arg == "+timed30":
                mode = TrainingMode.TIMED30
            elif arg == "timed60" or arg == "+timed60":
                mode = TrainingMode.TIMED60
            else:
                unrecognizedArgs.append(arg)
        if len(unrecognizedArgs) > 0:
            raise TrainingCogError(
                'Unrecognized arguments: {}'.format(' '.join(unrecognizedArgs)))
        return rating, mode

    def _getStatus(self, success):
        if success == TrainingResult.SOLVED:
            return TrainingProblemStatus.SOLVED
        if success == TrainingResult.TOOSLOW:
            return TrainingProblemStatus.SOLVED_TOO_SLOW
        if success == TrainingResult.SKIPPED:
            return TrainingProblemStatus.SKIPPED
        if success == TrainingResult.INVALIDATED:
            return TrainingProblemStatus.INVALIDATED

    def _getFormattedTimeleft(self, issue_time, time_left):
        if time_left is None:
            return 'Inf'
        now_time = datetime.datetime.now().timestamp()
        time_passed = now_time - issue_time
        if time_passed > time_left:
            return 'Time over'
        else:
            return cf_common.pretty_time_format(int(time_left - time_passed), shorten=True, always_seconds=True)

    def _validateTrainingStatus(self, ctx, rating, active):
        if rating is not None and rating % 100 != 0:
            raise TrainingCogError('Delta must be a multiple of 100.')
        if rating is not None and (rating < _TRAINING_MIN_RATING_VALUE or rating > _TRAINING_MAX_RATING_VALUE):
            raise TrainingCogError(
                f'Start rating must range from {_TRAINING_MIN_RATING_VALUE} to {_TRAINING_MAX_RATING_VALUE}.')

        if active is not None:
            _, _, name, contest_id, index, _, _, _, _, _ = active
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            raise TrainingCogError(
                f'You have an active training problem {name} at {url}')

    def _checkTrainingActive(self, ctx, active):
        if not active:
            raise TrainingCogError(
                'You do not have an active training. You can start one with ;training start')

    async def _pickTrainingProblem(self, handle, rating, submissions, user_id):
        solved = {sub.problem.name for sub in submissions}
        skips = cf_common.user_db.get_training_skips(user_id)
        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if (prob.rating == rating and
                        prob.name not in solved and
                        prob.name not in skips)]

        def check(problem):
            return (not cf_common.is_nonstandard_problem(problem) and
                    not cf_common.is_contest_writer(problem.contestId, handle))

        problems = list(filter(check, problems))
        # TODO: What happens to DB if this one triggers?
        if not problems:
            raise TrainingCogError(
                'No problem to assign. Start of training failed.')
        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds)

        choice = max(random.randrange(len(problems)) for _ in range(5))
        return problems[choice]

    async def _checkIfSolved(self, ctx, active, handle, submissions):
        _, _, name, contest_id, index, _, _, _, _, _ = active
        ac = [sub for sub in submissions if sub.problem.name ==
              name and sub.verdict == 'OK']
        # order by creation time increasing
        ac.sort(key=lambda y: y[6])

        if len(ac) == 0:
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            raise TrainingCogError(
                f'You haven\'t completed your active training problem {name} at {url}')
        finish_time = int(ac[0].creationTimeSeconds)
        return finish_time

    async def _postProblemFinished(self, ctx, handle, name, contest_id, index, duration, gamestate, success, timeleft):
        if success == TrainingResult.INVALIDATED:
            return
        desc = ''
        text = ''
        color = 0x000000
        if success == TrainingResult.SOLVED:
            desc = f'{handle} solved training problem.'
            text = 'Problem solved.'
            color = 0x008000
        if success == TrainingResult.TOOSLOW:
            timeDiffFormatted = cf_common.pretty_time_format(
                duration-timeleft, shorten=True, always_seconds=True)
            desc = f'{handle} solved training problem but was {timeDiffFormatted} too slow.'
            text = 'Problem solved but not fast enough.'
            color = 0xf98e1b
        if success == TrainingResult.SKIPPED:
            desc = f'{handle} skipped training problem'
            text = 'Problem skipped.'
            color = 0xff3030

        url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
        title = f'{index}. {name}'
        durationFormatted = cf_common.pretty_time_format(
            duration, shorten=True, always_seconds=True)
        embed = discord.Embed(
            title=title, description=desc, url=url, color=color)
        embed.add_field(name='Score', value=gamestate.score)
        embed.add_field(name='Time taken:', value=durationFormatted)
        embed.add_field(
            name='Lives left:', value=gamestate.lives if gamestate.lives is not None else 'Inf')
        await ctx.send(text, embed=embed)

    async def _postProblem(self, ctx, handle, problemName, problemIndex, problemContestId, problemRating, issue_time, gamestate, new: bool = True):
        url = f'{cf.CONTEST_BASE_URL}{problemContestId}/problem/{problemIndex}'
        title = f'{problemIndex}. {problemName}'
        desc = cf_common.cache2.contest_cache.get_contest(
            problemContestId).name
        embed = discord.Embed(title=title, url=url,
                              description=desc, color=0x008000)
        embed.add_field(name='Rating', value=problemRating)
        embed.add_field(
            name='Lives left:', value=gamestate.lives if gamestate.lives is not None else 'Inf')
        timeleftFormatted = self._getFormattedTimeleft(
            issue_time, gamestate.timeleft)
        embed.add_field(name='Time left:', value=timeleftFormatted)

        prefix = 'New' if new else 'Current'
        await ctx.send(f'{prefix} training problem for `{handle}`', embed=embed)

    async def _postTrainingStatistics(self, ctx, active, handle, gamestate, finished=True, past=False):
        training_id = active[0]
        numSkips = cf_common.user_db.train_get_num_skips(training_id)
        numSolves = cf_common.user_db.train_get_num_solves(training_id)
        numSlowSolves = cf_common.user_db.train_get_num_slow_solves(
            training_id)
        maxRating = cf_common.user_db.train_get_max_rating(training_id)
        startRating = cf_common.user_db.train_get_start_rating(training_id)

        text = ''
        title = f'Current training session of `{handle}`'
        color = 0x000080
        if past:
            text = 'You don\'t have an active training session.'
            title = f'Latest training session of `{handle}`'
            color = 0x000000
        if finished:
            title = f'Game over! Training session of `{handle}` ended.'
            color = 0x000040
        embed = discord.Embed(title=title, color=color)
        embed.add_field(name='Game mode',
                        value=gamestate._getModeStr(), inline=False)
        embed.add_field(name='Start rating', value=startRating, inline=True)
        embed.add_field(name='Highest solve', value=maxRating, inline=False)
        embed.add_field(name='Solves', value=numSolves, inline=True)
        embed.add_field(name='Slow solves', value=numSlowSolves, inline=True)
        embed.add_field(name='Skips', value=numSkips, inline=True)
        embed.add_field(name='Score', value=gamestate.score, inline=False)
        await ctx.send(text, embed=embed)
        if not finished and not past:
            _, issue_time, name, contest_id, index, rating, _, _, _, _ = active
            await self._postProblem(ctx, handle, name, index, contest_id, rating, issue_time, gamestate, False)

    async def _startTrainingAndAssignProblem(self, ctx, handle, problem, gamestate):
        # The caller of this function is responsible for calling `_validate_training_status` first.
        user_id = ctx.author.id
        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.new_training(
            user_id, issue_time, problem, gamestate.mode, gamestate.score, gamestate.lives, gamestate.timeleft)
        if rc != 1:
            raise TrainingCogError(
                'Your training has already been added to the database!')

        active = await self._getActiveTraining(user_id)
        await self._postTrainingStatistics(ctx, active, handle, gamestate, False, False)

    async def _assignNewTrainingProblem(self, ctx, active, handle, problem, gamestate):
        training_id, _, _, _, _, _, _, _, _, _ = active
        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.assign_training_problem(
            training_id, issue_time, problem)
        if rc == 1:
            await self._postProblem(ctx, handle, problem.name, problem.index, problem.contestId, problem.rating, issue_time, gamestate)
        if rc == -1:
            raise TrainingCogError(
                'Your training problem has already been added to the database!')

    async def _completeCurrentTrainingProblem(self, ctx, active, handle, finish_time, duration, gamestate, success):
        training_id, _, name, contest_id, index, _, _, _, _, timeleft = active
        status = self._getStatus(success)
        rc = cf_common.user_db.end_current_training_problem(
            training_id, finish_time, status, gamestate.score, gamestate.lives, gamestate.timeleft)
        if rc == 1:
            await self._postProblemFinished(ctx, handle, name, contest_id, index, duration, gamestate, success, timeleft)
        if rc == -1:
            raise TrainingCogError(
                "You already completed your training problem!")
        if rc == -2:
            raise TrainingCogError(
                'You don\'t have an active training session!')

    async def _finishCurrentTraining(self, ctx, active):
        training_id, _, _, _, _, _, _, _, _, _ = active

        rc = cf_common.user_db.finish_training(training_id)
        if rc == -1:
            raise TrainingCogError("You already ended your training!")

    async def _endTrainingIfDead(self, ctx, active, handle, gamestate):
        if not gamestate.alive:
            # show death message
            await self._finishCurrentTraining(ctx, active)
            # end game and post results
            await self._postTrainingStatistics(ctx, active, handle, gamestate, True, False)
            return True
        return False

    # User commands start here

    @training.command(brief='Start a training session',
                      usage='[rating] [infinite|survival|timed15|timed30|timed60]')
    @cf_common.user_guard(group='training')
    async def start(self, ctx, *args):
        """ Start your training session
            - Game modes:
              - infinite: Play the game in infinite mode (you can skip at any time) [DEFAULT]
              - survival: Challenge mode with only 3 skips available
              - timed15/timed30/timed60: Challenge mode similar to survival but u only have a limited time to solve your problem. 
                                         Slow solves will also reduce your life by 1. Fast solves will increase available time for the next problem.
            - It is possible to change the start rating from 800 to any other valid rating
        """
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        # get cf handle
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        # get user submissions
        submissions = await cf.user.status(handle=handle)

        rating, mode = self._extractArgs(args)

        gamestate = Game(mode)

        # check if start of a new training is possible
        active = await self._getActiveTraining(ctx.author.id)
        self._validateTrainingStatus(ctx, rating, active)

        # Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, rating, submissions, ctx.author.id)

        # assign new problem
        await self._startTrainingAndAssignProblem(ctx, handle, problem, gamestate)

    @training.command(brief='If you have solved your current problem it will assign a new one')
    @cf_common.user_guard(group='training')
    async def solved(self, ctx, *args):
        """ Use this command if you got AC on the training problem. If game continues the bot will assign a new problem.
        """

        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        # get cf handle
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        # get user submissions
        submissions = await cf.user.status(handle=handle)

        # check game running
        active = await self._getActiveTraining(ctx.author.id)
        self._checkTrainingActive(ctx, active)

        # check if solved
        finish_time = await self._checkIfSolved(ctx, active, handle, submissions)

        # game logic here
        _, issue_time, _, _, _, rating, _, _, _, _ = active
        gamestate = Game(active[6], active[7], active[8], active[9])
        duration = finish_time - issue_time
        success, newRating = gamestate.doSolved(rating, duration)

        # Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, newRating, submissions, ctx.author.id)

        # Complete old problem
        await self._completeCurrentTrainingProblem(ctx, active, handle, finish_time, duration, gamestate, success)

        # Check if game ends here
        if await self._endTrainingIfDead(ctx, active, handle, gamestate):
            return

        # Assign new problem
        await self._assignNewTrainingProblem(ctx, active, handle, problem, gamestate)

    @training.command(brief='If you want to skip your current problem you can get a new one.')
    @cf_common.user_guard(group='training')
    async def skip(self, ctx):
        """ Use this command if you want to skip your current training problem. If not in infinite mode this will reduce your lives by 1.
        """
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        # get cf handle
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        # get user submissions
        submissions = await cf.user.status(handle=handle)

        # check game running
        active = await self._getActiveTraining(ctx.author.id)
        self._checkTrainingActive(ctx, active)

        # game logic here
        _, issue_time, _, _, _, rating, _, _, _, _ = active
        gamestate = Game(active[6], active[7], active[8], active[9])
        finish_time = datetime.datetime.now().timestamp()
        duration = finish_time - issue_time
        success, newRating = gamestate.doSkip(rating, duration)

        # Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, newRating, submissions, ctx.author.id)

        # Complete old problem
        await self._completeCurrentTrainingProblem(ctx, active, handle, finish_time, duration, gamestate, success)

        # Check if game ends here
        if await self._endTrainingIfDead(ctx, active, handle, gamestate):
            return

        # Assign new problem
        await self._assignNewTrainingProblem(ctx, active, handle, problem, gamestate)

    @training.command(brief='End your training session.')
    @cf_common.user_guard(group='training')
    async def end(self, ctx):
        """ Use this command to end the current training session. 
        """
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))

        # check game running
        active = await self._getActiveTraining(ctx.author.id)
        self._checkTrainingActive(ctx, active)

        # invalidate active problem and finish training
        _, issue_time, _, _, _, rating, _, _, _, _ = active
        gamestate = Game(active[6], active[7], active[8], active[9])
        finish_time = datetime.datetime.now().timestamp()
        duration = finish_time - issue_time
        success, newRating = gamestate.doFinish(rating, duration)

        # Complete old problem
        await self._completeCurrentTrainingProblem(ctx, active, handle, finish_time, duration, gamestate, success)

        # Check if game ends here // should trigger each time
        if await self._endTrainingIfDead(ctx, active, handle, gamestate):
            return

    @training.command(brief='Shows current status of your training session.', usage='[username]')
    async def status(self, ctx, member: discord.Member = None):
        """ Use this command to show the current status of your training session and the current assigned problem. 
            If you don't have an active training this will show the stats of your latest training session.
            You can add the discord name of a user to get his status instead.
        """
        member = member or ctx.author
        # check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(member),))

        # check game running
        active = await self._getActiveTraining(member.id)
        if active is not None:
            gamestate = Game(active[6], active[7], active[8], active[9])
            await self._postTrainingStatistics(ctx, active, handle, gamestate, False, False)
        else:
            latest = await self._getLatestTraining(member.id)
            if latest is None:
                raise TrainingCogError(
                    "You don't have an active or past training!")
            gamestate = Game(latest[6], latest[7], latest[8], latest[9])
            await self._postTrainingStatistics(ctx, latest, handle, gamestate, False, True)

    @training.command(brief="Show fastest training solves")
    async def fastest(self, ctx, *args):
        """Show a list of fastest solves within a training session for each rating."""
        res = cf_common.user_db.train_get_fastest_solves()
        
        rankings = []
        index = 0
        for user_id, rating, time in res:
            member = ctx.guild.get_member(int(user_id))
            handle = cf_common.user_db.get_handle(user_id, ctx.guild.id)
            user = cf_common.user_db.fetch_cf_user(handle)
            if user is None:
                continue
            user_rating = user.rating

            discord_handle = ""
            if member is not None: 
                discord_handle = member.display_name
                
            rankings.append((rating, discord_handle, handle, user_rating, time))

        if not rankings:
            raise TrainingCogError('No one has completed a training challenge yet.')
        discord_file = get_fastest_solves_image(rankings)
        await ctx.send(file=discord_file)

    @training.command(brief='Set the training channel to the current channel')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)  # OK
    async def set_channel(self, ctx):
        """ Sets the training channel to the current channel.
        """
        cf_common.user_db.set_training_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(embed=discord_common.embed_success('Training channel saved successfully'))

    @training.command(brief='Get the training channel')
    async def get_channel(self, ctx):
        """ Gets the training channel.
        """
        channel_id = cf_common.user_db.get_training_channel(ctx.guild.id)
        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            raise TrainingCogError('There is no training channel')
        embed = discord_common.embed_success('Current training channel')
        embed.add_field(name='Channel', value=channel.mention)
        await ctx.send(embed=embed)

    @discord_common.send_error_if(TrainingCogError, cf_common.ResolveHandleError,
                                  cf_common.FilterError)
    async def cog_command_error(self, ctx, error):
        pass


async def setup(bot):
    await bot.add_cog(Training(bot))
