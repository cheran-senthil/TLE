import os
import subprocess
import sys
import time
import textwrap

from discord.ext import commands
from tle.util.codeforces_common import pretty_time_format

RESTART = 42


class Meta(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    @commands.group(brief='Bot control', invoke_without_command=True)
    async def meta(self, ctx):
        """Command the bot or get information about the bot."""
        await ctx.send_help(ctx.command)

    @meta.command(brief='Restarts TLE')
    @commands.has_role('Admin')
    async def restart(self, ctx):
        """Restarts the bot."""
        # Really, we just exit with a special code
        # the magic is handled elsewhere
        await ctx.send('Restarting...')
        os._exit(RESTART)

    @meta.command(brief='Kill TLE')
    @commands.has_role('Admin')
    async def kill(self, ctx):
        """Restarts the bot."""
        await ctx.send('Dying...')
        os._exit(0)

    @meta.command(brief='Is TLE up?')
    async def ping(self, ctx):
        """Replies to a ping."""
        start = time.perf_counter()
        message = await ctx.send(':ping_pong: Pong!')
        end = time.perf_counter()
        duration = (end - start) * 1000
        await message.edit(content=f'REST API latency: {int(duration)}ms\n'
                                   f'Gateway API latency: {int(self.bot.latency * 1000)}ms')

    @meta.command(brief='Prints bot uptime')
    async def uptime(self, ctx):
        """Replies with how long TLE has been up."""
        await ctx.send('TLE has been running for ' +
                       pretty_time_format(time.time() - self.start_time))

    @meta.command(brief='Print bot guilds')
    @commands.has_role('Admin')
    async def guilds(self, ctx):
        "Replies with info on the bot's guilds"
        msg = [f'Guild ID: {guild.id} | Name: {guild.name} | Owner: {guild.owner.id} | Icon: {guild.icon_url}'
                for guild in self.bot.guilds]
        await ctx.send('```' + '\n'.join(msg) + '```')


def setup(bot):
    bot.add_cog(Meta(bot))
