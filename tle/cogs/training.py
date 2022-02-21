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

class TrainingCogError(commands.CommandError):
    pass

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


    def _validateTrainingStatus(self, ctx, rating, active):
        if rating is not None and rating % 100 != 0:
            raise TrainingCogError('Delta must be a multiple of 100.')
        if rating is not None and (rating < _TRAINING_MIN_RATING_VALUE or rating > _TRAINING_MAX_RATING_VALUE):
            raise TrainingCogError(f'Start rating must range from {_TRAINING_MIN_RATING_VALUE} to {_TRAINING_MAX_RATING_VALUE}.')
        
        if active is not None:
            _, _, name, contest_id, index, _, _ ,_ ,_ = active
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            raise TrainingCogError(f'You have an active training problem {name} at {url}')        

    async def _pickTrainingProblem(self, handle, rating):
        #TODO: Avoid second call to user.status
        submissions = await cf.user.status(handle=handle)
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



    ### NOTE: Unused now since we switched to the combined queries
    # async def _assignTrainingProblem(self, ctx, handle, problem, mode):
    #     # The caller of this function is responsible for calling `_validate_training_status` first.
    #     user_id = ctx.author.id

    #     issue_time = datetime.datetime.now().timestamp()
    #     rc = cf_common.user_db.new_training_problem(user_id, issue_time, problem)
    #     if rc is None:
    #         raise TrainingCogError('You don\'t have an active training session!')
    #     if rc == 0:
    #         raise TrainingCogError('Your training has already been added to the database!')

        
    #     #{handle} will be assigned a new problem with rating {rating}.') # (current lives: {lives})')        

    def _checkTrainingActive(self, ctx, active):
        if not active:
            raise TrainingCogError(f'You do not have an active training')

    async def _checkIfSolved(self, ctx, active, handle):
        _, issue_time, name, contest_id, index, _, _, _, _ = active
        submissions = await cf.user.status(handle=handle)
        ac = [sub for sub in submissions if sub.problem.name == name and sub.verdict == 'OK']
        #order by creation time increasing 
        ac.sort(key=lambda y: y[6])

        ### TODO: Add back after debugging
        # if len(ac) == 0:
        #     url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
        #     raise TrainingCogError(f'You haven\'t completed your active training problem {name} at {url}')               
        # ac = {sub for sub in submissions if sub.name == name and sub.verdict == 'OK'} 
        # finish_time = int(ac[0].creationTimeSeconds)

        finish_time = int(datetime.datetime.now().timestamp())
        return finish_time

    async def _postProblemFinished(self, ctx, handle, name, contest_id, index, duration):
        durationFormatted = cf_common.pretty_time_format(duration)
        url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
        await ctx.send(f'`{handle}` solved training problem {name} at {url} in {durationFormatted}.')

    async def _postProblemSkipped(self, ctx, handle, name, contest_id, index):
        url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
        await ctx.send(f'`{handle}` skipped training problem {name} at {url}.')

    async def _postNewProblem(self, ctx, handle, problem):
        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache2.contest_cache.get_contest(problem.contestId).name
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'New training problem for `{handle}`', embed=embed)

    async def _startTrainingAndAssignProblem(self, ctx, handle, problem, mode):
        # The caller of this function is responsible for calling `_validate_training_status` first.
        user_id = ctx.author.id

        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.new_training(user_id, issue_time, problem, mode, 0, 0)
        if rc != 1:
            raise TrainingCogError('Your training has already been added to the database!')

        await self._postNewProblem(ctx, handle, problem)

    async def _completeCurrentTrainingProblem(self, ctx, active, handle, problem, finish_time, duration):
        # The caller of this function is responsible for calling `_validate_training_status` first.
        training_id, _, name, contest_id, index, _, _, score, _ = active
        user_id = ctx.message.author.id

        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.solved_and_assign_training_problem(user_id, training_id, issue_time, finish_time, 0, score+1, problem)
        if rc == 1:
            await self._postProblemFinished(ctx, handle, name, contest_id, index, duration)            
            await self._postNewProblem(ctx, handle, problem)            
        if rc == -1: 
            raise TrainingCogError("You already completed your training problem!")
        if rc == -2:
            raise TrainingCogError('You don\'t have an active training session!')
        if rc == -3:
            raise TrainingCogError('Your training problem has already been added to the database!')

    async def _skipCurrentTrainingProblem(self, ctx, active, handle, problem):
        # The caller of this function is responsible for calling `_validate_training_status` first.
        training_id, _, name, contest_id, index, _, _, score, _ = active
        user_id = ctx.message.author.id

        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.skip_and_assign_training_problem(user_id, training_id, issue_time, 0, score, problem)
        if rc == 1:
            await self._postProblemSkipped(ctx, handle, name, contest_id, index)            
            await self._postNewProblem(ctx, handle, problem)            
        if rc == -1: 
            raise TrainingCogError("You already skipped your training problem!")
        if rc == -2:
            raise TrainingCogError('You don\'t have an active training session!')
        if rc == -3:
            raise TrainingCogError('Your training problem has already been added to the database!')

    async def _showActiveTrainingProblem(self, ctx, active, handle):
        _, _, name, contest_id, index, rating, _, _, _ = active
        title = f'{index}. {name}'
        desc = cf_common.cache2.contest_cache.get_contest(contest_id).name
        url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
        embed = discord.Embed(title=title, url=url, description=desc)
        embed.add_field(name='Rating', value=rating)
        await ctx.send(f'Current training problem of `{handle}`', embed=embed)


    async def _finishCurrentTraining(self, ctx, active):
        training_id, _, _, _, _, _, _, _, _ = active
        user_id = ctx.message.author.id

        rc = cf_common.user_db.finish_training(user_id, training_id)
        if rc != 1:
            raise TrainingCogError("You already ended your training!")    

    ### TODO: This is a dummy
    async def _postTrainingStatistics(self, ctx, active, handle):
        title = f'Training session of `{handle}` finished'
        desc = 'You attempted 15 problems and solved 10 problems'
        embed = discord.Embed(title=title, description=desc)
        embed.add_field(name='Highest Rating', value=1234)
        await ctx.send('', embed=embed)        

    @training.command(brief='Start a training session')
    @cf_common.user_guard(group='training')
    async def start(self, ctx, *args):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))

        #extract args     TODO: own method
        rating = 800
        for arg in args:
            if arg.isdigit():
                rating = int(arg)

        # check if start of a new training is possible
        active = await self._getActiveTraining(ctx)
        self._validateTrainingStatus(ctx, rating, active)

        ### Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, rating)  
        
        #assign new problem
        await self._startTrainingAndAssignProblem(ctx, handle, problem, TrainingMode.NORMAL)

    @training.command(brief='Do this command if you have solved your current problem')
    @cf_common.user_guard(group='training')
    async def solved(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        ### check game running
        active = await self._getActiveTraining(ctx)
        self._checkTrainingActive(ctx, active)

        ### check if solved
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        finish_time = await self._checkIfSolved(ctx, active, handle)
        
        ### game logic here    TODO: extract into method
        _, issue_time, _, _, _, rating, _, _, _ = active
        rating = rating + 100
        rating = min(rating, 3500)
        rating = max(rating, 800)
        duration = finish_time - issue_time
        
        ### Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, rating)  

        ### check game state 
        await self._completeCurrentTrainingProblem(ctx, active, handle, problem, finish_time, duration)       

    @training.command(brief='Do this command if you want to skip your current problem.') #This reduces your life by 1 (if not in Unlimited Mode).
    @cf_common.user_guard(group='training')
    async def skip(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))

        ### check game running
        active = await self._getActiveTraining(ctx)
        self._checkTrainingActive(ctx, active)

        ### game logic here         TODO: extract into method
        _, _, _, _, _, rating, _, _, _ = active
        rating = rating - 100
        rating = min(rating, 3500)
        rating = max(rating, 800)

        ### Picking a new problem with a certain rating
        problem = await self._pickTrainingProblem(handle, rating)  


        ### skip problem
        await self._skipCurrentTrainingProblem(ctx, active, handle, problem)

    @training.command(brief='Do this command if you want to finish your training session.')
    @cf_common.user_guard(group='training')
    async def finish(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))

        ### check game running
        active = await self._getActiveTraining(ctx)
        self._checkTrainingActive(ctx, active)

        ### invalidate active problem and finish training
        await self._finishCurrentTraining(ctx, active)

        ### end game and post results
        await self._postTrainingStatistics(ctx, active, handle)

    @training.command(brief='Shows current status of your training session.')
    async def status(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))

        ### check game running
        active = await self._getActiveTraining(ctx)
        self._checkTrainingActive(ctx, active)

        await self._showActiveTrainingProblem(ctx, active, handle)

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