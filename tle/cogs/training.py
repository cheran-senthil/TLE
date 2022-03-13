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

_TRAINING_MIN_RATING_VALUE = 800
_TRAINING_MAX_RATING_VALUE = 3500

class TrainingMode(IntEnum):
    NORMAL = 0
    SURVIVAL = 1
    TIMED15 = 2
    TIMED30 = 3
    TIMED60 = 4

class TrainingResult(IntEnum):
    SOLVED = 0,
    TOOSLOW = 1
    SKIPPED = 2
    INVALIDATED = 3

class TrainingCogError(commands.CommandError):
    pass

class Game: 
    def __init__(self, mode, score = None, lives = None, timeleft = None):
        self.mode = int(mode)
        # existing game
        if score is not None:
            self.score = int(score)
            self.lives = int(lives) if lives is not None else 0
            self.timeleft = int(timeleft) if timeleft is not None else 0
            self.alive = True if self.lives > 0 or mode == TrainingMode.NORMAL else False
            return
        #else we init a new game
        self.timeleft = int(self._getBaseTime())
        self.lives = self._getBaseLives()
        self.alive = True
        self.score = int(0)

    def _getBaseLives(self):
        if self.mode == TrainingMode.NORMAL:
            return 0
        else:
            return 3

    def _getBaseTime(self):
        if self.mode == TrainingMode.NORMAL or self.mode == TrainingMode.SURVIVAL:
            return 0
        if self.mode == TrainingMode.TIMED15:
            return 15*60
        if self.mode == TrainingMode.TIMED30:
            return 30*60
        if self.mode == TrainingMode.TIMED60:
            return 60*60

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
        if self.mode != TrainingMode.NORMAL and self.mode != TrainingMode.SURVIVAL and duration > self.timeleft:
            success = TrainingResult.TOOSLOW
            self.lives -= 1
            self.timeleft = int(self._getBaseTime())
        else:
            self.score += 1
            self.timeleft += int(max(0, min(self._getBaseTime() - duration, 2*self._getBaseTime())))
        newRating = self._newRating(success, rating)
        if self.mode != TrainingMode.NORMAL:
            if (self.lives == 0): self.alive = False
        return success, newRating

    def doSkip(self, rating, duration):
        rating = int(rating)
        success = TrainingResult.SKIPPED
        if self.mode != TrainingMode.NORMAL:
            self.lives -= 1
            self.timeleft = int(self._getBaseTime())
            if (self.lives <= 0): self.alive = False
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
        """Group for commands pertaining trainings"""
        await ctx.send_help(ctx.command)


    def _checkIfCorrectChannel(self, ctx): 
        training_channel_id = cf_common.user_db.get_training_channel(ctx.guild.id)
        if not training_channel_id or ctx.channel.id != training_channel_id:
            raise TrainingCogError('You must use this command in training channel.')

    async def _getActiveTraining(self, ctx):
        user_id = ctx.message.author.id
        active = cf_common.user_db.check_training(user_id)
        return active

    def _extractArgs(self, args):
        mode = TrainingMode.NORMAL
        rating = 800
        unrecognizedArgs = []
        for arg in args:
            if arg.isdigit():
                rating = int(arg)
            elif arg == "survival":
                mode = TrainingMode.SURVIVAL
            elif arg == "timed15":
                mode = TrainingMode.TIMED15
            elif arg == "timed30":
                mode = TrainingMode.TIMED30
            elif arg == "timed60":
                mode = TrainingMode.TIMED60
            else:
                unrecognizedArgs.append(arg)
        if len(unrecognizedArgs) > 0:
            raise TrainingCogError('Unrecognized arguments: {}'.format(' '.join(unrecognizedArgs)))
        return rating, mode

    def _validateTrainingStatus(self, ctx, rating, active):
        if rating is not None and rating % 100 != 0:
            raise TrainingCogError('Delta must be a multiple of 100.')
        if rating is not None and (rating < _TRAINING_MIN_RATING_VALUE or rating > _TRAINING_MAX_RATING_VALUE):
            raise TrainingCogError(f'Start rating must range from {_TRAINING_MIN_RATING_VALUE} to {_TRAINING_MAX_RATING_VALUE}.')
        
        if active is not None:
            _, _, name, contest_id, index, _, _ ,_ ,_ ,_ = active
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            raise TrainingCogError(f'You have an active training problem {name} at {url}')        

    async def _pickTrainingProblem(self, handle, rating, submissions):
        solved = {sub.problem.name for sub in submissions}        
        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if (prob.rating == rating and
                        prob.name not in solved)]

        def check(problem):
            return (not cf_common.is_nonstandard_problem(problem) and
                    not cf_common.is_contest_writer(problem.contestId, handle))     

        problems = list(filter(check, problems))  
        if not problems:
            raise TrainingCogError('No problem to assign. Start of training failed.')                      
        problems.sort(key=lambda problem: cf_common.cache2.contest_cache.get_contest(
            problem.contestId).startTimeSeconds)

        choice = max(random.randrange(len(problems)) for _ in range(5))  
        return problems[choice]

    def _checkTrainingActive(self, ctx, active):
        if not active:
            raise TrainingCogError('You do not have an active training')

    async def _checkIfSolved(self, ctx, active, handle, submissions, skip):
        _, issue_time, name, contest_id, index, _, _, _, _, _ = active
        ac = [sub for sub in submissions if sub.problem.name == name and sub.verdict == 'OK']
        #order by creation time increasing 
        ac.sort(key=lambda y: y[6])

        if skip:
            finish_time = int(datetime.datetime.now().timestamp())
            return finish_time
        
        if len(ac) == 0:
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            raise TrainingCogError(f'You haven\'t completed your active training problem {name} at {url}')               
        finish_time = int(ac[0].creationTimeSeconds)
        return finish_time        

    async def _postProblemFinished(self, ctx, handle, name, contest_id, index, duration, gamestate, success, timeleft):
        if success == TrainingResult.SOLVED:
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            durationFormatted = cf_common.pretty_time_format(duration)
            title = f'{handle} solved training problem \"{name}\"'
            desc  = f'Time taken: {durationFormatted}'
            embed = discord.Embed(title=title, description=desc, url=url, color=0x008000)
            embed.add_field(name='Score', value=gamestate.score)
            if gamestate.mode != TrainingMode.NORMAL:
                embed.add_field(name='Lives left:', value=gamestate.lives)
            await ctx.send('Problem solved.', embed=embed)
        if success == TrainingResult.TOOSLOW:
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            durationFormatted = cf_common.pretty_time_format(duration)
            timeleftFormatted = cf_common.pretty_time_format(timeleft)
            title = f'{handle} solved training problem \"{name}\" but was too slow.'
            desc  = f'Time taken: {durationFormatted} (Timelimit: {timeleftFormatted})'
            embed = discord.Embed(title=title, description=desc, url=url, color=0x008000)
            embed.add_field(name='Score', value=gamestate.score)
            if gamestate.mode != TrainingMode.NORMAL:
                embed.add_field(name='Lives left:', value=gamestate.lives)
            await ctx.send('Problem solved but not fast enough.', embed=embed)
        if success == TrainingResult.SKIPPED:
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            title = f'{handle} skipped training problem \"{name}\"'
            embed = discord.Embed(title=title, url=url, color=0xff3030)
            embed.add_field(name='Score', value=gamestate.score)
            if gamestate.mode != TrainingMode.NORMAL:
                embed.add_field(name='Lives left:', value=gamestate.lives)
            await ctx.send('Problem skipped.', embed=embed)

    async def _postProblem(self, ctx, handle, problemName, problemIndex, problemContestId, problemRating, gamestate, new: bool = True):
        title = f'{problemIndex}. {problemName}'
        desc = cf_common.cache2.contest_cache.get_contest(problemContestId).name
        url = f'{cf.CONTEST_BASE_URL}{problemContestId}/problem/{problemIndex}'
        prefix = 'New' if new else 'Current'
        embed = discord.Embed(title=title, url=url, description=desc)
        embed.add_field(name='Rating', value=problemRating)
        if gamestate.mode != TrainingMode.NORMAL:
            embed.add_field(name='Lives left:', value=gamestate.lives)
        ## TODO: this is bugged if we post it in "status"
        if gamestate.mode != TrainingMode.NORMAL and gamestate.mode != TrainingMode.SURVIVAL:
            embed.add_field(name='Time left:', value=gamestate.timeleft)
        if not new:
            embed.add_field(name='Score', value=gamestate.score)
        await ctx.send(f'{prefix} training problem for `{handle}`', embed=embed)

    async def _startTrainingAndAssignProblem(self, ctx, handle, problem, gamestate):
        # The caller of this function is responsible for calling `_validate_training_status` first.
        user_id = ctx.author.id
        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.new_training(user_id, issue_time, problem, gamestate.mode, gamestate.score, gamestate.lives, gamestate.timeleft)
        if rc != 1:
            raise TrainingCogError('Your training has already been added to the database!')

        await self._postProblem(ctx, handle, problem.name, problem.index, problem.contestId, problem.rating, gamestate)

    def _getStatus(self, success):
        if success == TrainingResult.SOLVED:
            return TrainingProblemStatus.SOLVED
        if success == TrainingResult.TOOSLOW:
            return TrainingProblemStatus.SOLVED_TOO_SLOW
        if success == TrainingResult.SKIPPED:
            return TrainingProblemStatus.SKIPPED
        if success == TrainingResult.INVALIDATED:
            return TrainingProblemStatus.INVALIDATED

    async def _completeCurrentTrainingProblem(self, ctx, active, handle, finish_time, duration, gamestate, success):
        training_id, _, name, contest_id, index, _, _, _, _ ,timeleft = active
        status = self._getStatus(success)
        rc = cf_common.user_db.end_current_training_problem(training_id, finish_time, status, gamestate.score, gamestate.lives, gamestate.timeleft)
        if rc == 1:
            await self._postProblemFinished(ctx, handle, name, contest_id, index, duration, gamestate, success, timeleft)            
        if rc == -1: 
            raise TrainingCogError("You already completed your training problem!")
        if rc == -2:
            raise TrainingCogError('You don\'t have an active training session!')

    async def _assignNewTrainingProblem(self, ctx, active, handle, problem, gamestate):
        training_id, _, _, _, _, _, _, _, _ ,_ = active
        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.assign_training_problem(training_id, issue_time, problem)
        if rc == 1:
            await self._postProblem(ctx, handle, problem.name, problem.index, problem.contestId, problem.rating, gamestate)            
        if rc == -1:
            raise TrainingCogError('Your training problem has already been added to the database!')       

    async def _showActiveTrainingProblem(self, ctx, active, handle, gamestate):
        _, _, name, contest_id, index, rating, _, _, _ ,_ = active
        await self._postProblem(ctx, handle, name, index, contest_id, rating, gamestate, False)  

    async def _finishCurrentTraining(self, ctx, active):
        training_id, _, _, _, _, _, _, _, _ ,_ = active

        rc = cf_common.user_db.finish_training(training_id)
        if rc == -1:
            raise TrainingCogError("You already ended your training!")    

    async def _endTrainingIfDead(self, ctx, active, handle, gamestate):
        if not gamestate.alive:
            # show death message
            await self._finishCurrentTraining(ctx, active)
            ### end game and post results
            await self._postTrainingStatistics(ctx, active, handle, gamestate)
            return True
        return False


    ### TODO: Get data from DB
    async def _postTrainingStatistics(self, ctx, active, handle, gamestate, finish = True):
        training_id, _, name, contest_id, index, rating, _, _, _ ,_ = active
        numSkips = cf_common.user_db.train_get_num_skips(training_id) 
        numSolves = cf_common.user_db.train_get_num_solves(training_id) 
        numSlowSolves = cf_common.user_db.train_get_num_slow_solves(training_id) 
        maxRating = cf_common.user_db.train_get_max_rating(training_id) 
        startRating = cf_common.user_db.train_get_start_rating(training_id) 

        title = f'Training session of `{handle}`'
        if finish: 
            title += ' finished'
        embed = discord.Embed(title=title)
        embed.add_field(name='Score', value = gamestate.score, inline=True)
        embed.add_field(name='Lives left', value = gamestate.lives, inline=True)
        # TODO: time will not reflect actual time remaining
        if not finish and gamestate.mode != TrainingMode.NORMAL: 
            timeLeftFormatted = cf_common.pretty_time_format(gamestate.timeleft)
            embed.add_field(name='Time left', value = timeLeftFormatted, inline=True)
        embed.add_field(name='Solves', value = numSolves, inline=True)
        embed.add_field(name='Slow solves', value = numSlowSolves, inline=True)
        embed.add_field(name='Skips', value = numSkips, inline=True)
        embed.add_field(name='Start rating', value = startRating, inline=True)
        embed.add_field(name='Highest solve', value = maxRating, inline=True)
        await ctx.send('', embed=embed) 
        if not finish:
            await self._postProblem(ctx, handle, name, index, contest_id, rating, gamestate, False)       

    @training.command(  brief='Start a training session',
                        usage='[rating] [normal|survival|timed15|timed30|timed60]')
    @cf_common.user_guard(group='training')
    async def start(self, ctx, *args):
        """ TODO: Detailed description
        """
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        ### get cf handle
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        ### get user submissions
        submissions = await cf.user.status(handle=handle)

        rating, mode = self._extractArgs(args)

        gamestate = Game(mode)

        # check if start of a new training is possible
        active = await self._getActiveTraining(ctx)
        self._validateTrainingStatus(ctx, rating, active)

        ### Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, rating, submissions)  

        #assign new problem
        await self._startTrainingAndAssignProblem(ctx, handle, problem, gamestate)



    @training.command(brief='If you have solved your current problem it will assign a new one',
                      usage='[+force]')
    @cf_common.user_guard(group='training')
    async def solved(self, ctx, *args):
        """ TODO: Detailed description
            +force: marks the problem as solved even if its not solved (DEBUG MODE only!!!)
        """        
        #### TODO: debug helper:
        skip = False
        for arg in args:
            if arg == "+force":
                skip = True


        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        ### get cf handle
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        ### get user submissions
        submissions = await cf.user.status(handle=handle)
        
        ### check game running
        active = await self._getActiveTraining(ctx)
        self._checkTrainingActive(ctx, active)
        

        ### check if solved
        finish_time = await self._checkIfSolved(ctx, active, handle, submissions, skip)
        
        ### game logic here 
        _, issue_time, _, _, _, rating, _, _, _ ,_ = active
        gamestate = Game(active[6], active[7], active[8], active[9])
        duration = finish_time - issue_time
        success, newRating = gamestate.doSolved(rating, duration)

        ### Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, newRating, submissions)  

        ### Complete old problem
        await self._completeCurrentTrainingProblem(ctx, active, handle, finish_time, duration, gamestate, success)       

        ### Check if game ends here
        if await self._endTrainingIfDead(ctx, active, handle, gamestate): return

        ### Assign new problem
        await self._assignNewTrainingProblem(ctx, active, handle, problem, gamestate)

    @training.command(brief='If you want to skip your current problem you can get a new one.') #This reduces your life by 1 (if not in Unlimited Mode).
    @cf_common.user_guard(group='training')
    async def skip(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        ### get cf handle
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        ### get user submissions
        submissions = await cf.user.status(handle=handle)

        ### check game running
        active = await self._getActiveTraining(ctx)
        self._checkTrainingActive(ctx, active)

        ### game logic here
        _, issue_time, _, _, _, rating, _, _, _ ,_ = active
        gamestate = Game(active[6], active[7], active[8], active[9])
        finish_time = datetime.datetime.now().timestamp()
        duration = finish_time - issue_time
        success, newRating = gamestate.doSkip(rating, duration)

        ### Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, newRating, submissions)  

        ### Complete old problem
        await self._completeCurrentTrainingProblem(ctx, active, handle, finish_time, duration, gamestate, success)       

        ### Check if game ends here
        if await self._endTrainingIfDead(ctx, active, handle, gamestate): return

        ### Assign new problem
        await self._assignNewTrainingProblem(ctx, active, handle, problem, gamestate)

    @training.command(brief='End your training session.')
    @cf_common.user_guard(group='training')
    async def finish(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))

        ### check game running
        active = await self._getActiveTraining(ctx)
        self._checkTrainingActive(ctx, active)


        ### invalidate active problem and finish training
        _, issue_time, _, _, _, rating, _, _, _ ,_ = active
        gamestate = Game(active[6], active[7], active[8], active[9])
        finish_time = datetime.datetime.now().timestamp()
        duration = finish_time - issue_time
        success, newRating = gamestate.doFinish(rating, duration)

        ### Complete old problem
        await self._completeCurrentTrainingProblem(ctx, active, handle, finish_time, duration, gamestate, success)       

        ### Check if game ends here // should trigger each time
        if await self._endTrainingIfDead(ctx, active, handle, gamestate): return

    @training.command(brief='Shows current status of your training session.')
    async def status(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))

        ### check game running
        active = await self._getActiveTraining(ctx)
        self._checkTrainingActive(ctx, active)

        gamestate = Game(active[6], active[7], active[8], active[9])
        
        await self._postTrainingStatistics(ctx, active, handle, gamestate, False)
        #await self._showActiveTrainingProblem(ctx, active, handle, gamestate)

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
    

def setup(bot):
    bot.add_cog(Training(bot))


### TODO:
# - how to handle corruption of DB when solved / skip is spammed
#   - make finish problem and assign new problem one transaction?
# - support queries for getting training stats (over all trainings and for current / last training)