import random
from enum import IntEnum
import discord
from discord.ext import commands
import datetime
from tle import constants
from tle.util.db.user_db_conn import Duel, DuelType, Winner
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

    @commands.command(brief='Set the training channel to the current channel')
    @commands.has_role(constants.TLE_ADMIN)
    async def set_training_channel(self, ctx):
        """ Sets the training channel to the current channel.
        """
        cf_common.user_db.set_training_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(embed=discord_common.embed_success('Training channel saved successfully'))

    @commands.group(brief='Training commands',
                    invoke_without_command=True)
    async def training(self, ctx):
        """Group for commands pertaining trainings"""
        await ctx.send_help(ctx.command)

    def _validateTrainingStatus(self, ctx, rating):
        if rating is not None and rating % 100 != 0:
            raise TrainingCogError('Delta must be a multiple of 100.')
        if rating is not None and (rating < _TRAINING_MIN_RATING_VALUE or rating > _TRAINING_MAX_RATING_VALUE):
            raise TrainingCogError(f'Start rating must range from {_TRAINING_MIN_RATING_VALUE} to {_TRAINING_MAX_RATING_VALUE}.')
        
        user_id = ctx.message.author.id
        active = cf_common.user_db.check_training(user_id)
        if active is not None:
            _, _, name, contest_id, index, _ = active
            url = f'{cf.CONTEST_BASE_URL}{contest_id}/problem/{index}'
            raise TrainingCogError(f'You have an active training problem {name} at {url}')        

    async def _pickTrainingProblem(self, handle, rating):
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

    def _checkIfCorrectChannel(self, ctx): 
        training_channel_id = cf_common.user_db.get_training_channel(ctx.guild.id)
        if not training_channel_id or ctx.channel.id != training_channel_id:
            raise TrainingCogError('You must use this command in training channel.')

    async def _startTrainingAndAssignProblem(self, ctx, handle, problem, mode):
        # The caller of this function is responsible for calling `_validate_training_status` first.
        user_id = ctx.author.id

        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.new_training(user_id, issue_time, problem, mode, None, None)
        if rc != 1:
            raise TrainingCogError('Your training has already been added to the database!')

        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache2.contest_cache.get_contest(problem.contestId).name
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'Training problem for `{handle}`', embed=embed)

    async def _assignTrainingProblem(self, ctx, handle, problem, mode):
        # The caller of this function is responsible for calling `_validate_training_status` first.
        user_id = ctx.author.id

        issue_time = datetime.datetime.now().timestamp()
        rc = cf_common.user_db.new_training_problem(user_id, issue_time, problem, mode, None, None)
        if rc is None:
            raise TrainingCogError('You don\'t have an active training session!')
        if rc == 0:
            raise TrainingCogError('Your training has already been added to the database!')

        title = f'{problem.index}. {problem.name}'
        desc = cf_common.cache2.contest_cache.get_contest(problem.contestId).name
        embed = discord.Embed(title=title, url=problem.url, description=desc)
        embed.add_field(name='Rating', value=problem.rating)
        await ctx.send(f'Training problem for `{handle}`', embed=embed)

    def _checkTrainingActive(self, ctx):
        user_id = ctx.message.author.id
        active = cf_common.user_db.check_training(user_id)
        if not active:
            raise TrainingCogError(f'You do not have an active training')
        return active

    async def _checkIfSolved(self, ctx, active):
        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        submissions = await cf.user.status(handle=handle)
        solved = {sub.problem.name for sub in submissions if sub.verdict == 'OK'}

        challenge_id, issue_time, name, contestId, index, delta = active
        if not name in solved:
            raise TrainingCogError('You haven\'t completed your challenge.')
        return handle

    async def _completeCurrentTrainingProblem(ctx, active, handle):
        challenge_id, issue_time, name, contestId, index, rating = active
        user_id = ctx.message.author.id
        #get AC submission time
        finish_time = int(datetime.datetime.now().timestamp())
        rc = cf_common.user_db.complete_training_problem(user_id, challenge_id, finish_time, rating)
        if rc == 1:
            duration = cf_common.pretty_time_format(finish_time - issue_time)
            rating = min(rating + 100, 3500)
            await ctx.send(f'Problem solved in {duration}. {handle} will be assigned a new problem with rating {rating}. (current lives: {lives})')
            return duration
        else: 
            TrainingCogError("You already completed your training problem!")

    @training.command(brief='Start a training session')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)    
    async def start(self, ctx, *args):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        handle, = await cf_common.resolve_handles(ctx, self.converter, ('!' + str(ctx.author),))
        user = cf_common.user_db.fetch_cf_user(handle)
        rating = 800
        for arg in args:
            if arg.isdigit():
                rating = int(arg)
        await self._validateTrainingStatus(ctx, rating)

        ### Picking a new problem with a certain rating
        problem = self._pickTrainingProblem(handle, rating)  

        #assign new problem
        await self._startTrainingAndAssignProblem(ctx, handle, problem, TrainingMode.NORMAL)

    @training.command(brief='Do this command if you have solved your current problem')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)    
    async def solved(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        ### check game running
        active = self._checkTrainingActive(ctx)

        ### check if solved
        handle = self._checkIfSolved(ctx, active)

        ### check game state 
        duration = self._completeCurrentTrainingProblem(active, handle, ctx.message.author.id)

        ### Picking a new problem with a certain rating
        challenge_id, issue_time, name, contestId, index, rating = active
        problem = self._pickTrainingProblem(handle, rating)  
        await self._assignTrainingProblem(ctx, handle, problem, rating)

    @training.command(brief='Do this command if you want to skip your current problem. ') #This reduces your life by 1 (if not in Unlimited Mode).
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)    
    async def skip(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        ### check game running
        active = self._checkTrainingActive(ctx)
        
        ### check if solved


        ### check game state

        ### assign new problem        
        pass

    @training.command(brief='Do this command if you want to end your training session.')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)    
    async def end(self, ctx):
        ### check if we are in the correct channel
        self._checkIfCorrectChannel(ctx)

        ### check game running
        active = self._checkTrainingActive(ctx)

        ### check if solved


        ### end game and post results
        pass

    

    

def setup(bot):
    bot.add_cog(Training(bot))