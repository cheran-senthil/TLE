import os
import subprocess
import sys
import time
import textwrap

from discord.ext import commands
from tle.util.codeforces_common import pretty_time_format

RESTART = 42


async def overwrite_file(file_name, line):
    """ Overwrites the file with the given line."""
    os.system(f'rm {file_name}')
    os.system(f'echo {line} >> {file_name}')

# Adapted from numpy sources.
# https://github.com/numpy/numpy/blob/master/setup.py#L64-85
def git_history():
    def _minimal_ext_cmd(cmd):
        # construct minimal environment
        env = {}
        for k in ['SYSTEMROOT', 'PATH']:
            v = os.environ.get(k)
            if v is not None:
                env[k] = v
        # LANGUAGE is used on win32
        env['LANGUAGE'] = 'C'
        env['LANG'] = 'C'
        env['LC_ALL'] = 'C'
        out = subprocess.Popen(cmd, stdout = subprocess.PIPE, env=env).communicate()[0]
        return out
    try:
        out = _minimal_ext_cmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        branch = out.strip().decode('ascii')
        out = _minimal_ext_cmd(['git', 'log', '--oneline', '-5'])
        history = out.strip().decode('ascii')
        return (
            'Branch:\n' +
            textwrap.indent(branch, '  ') +
            '\nCommits:\n' +
            textwrap.indent(history, '  ')
        )
    except OSError:
        return "Fetching git info failed"


class Meta(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    @commands.group(brief='Bot control', invoke_without_command=True)
    async def meta(self, ctx):
        """Command the bot or get information about the bot."""
        await ctx.send_help(ctx.command)

    @meta.command(brief='Restarts TLE and deploys the specified version according to the env vars. Check run.sh for details.')
    @commands.has_role('Admin')
    async def restart(self, ctx):
        """Restarts the bot."""
        # Really, we just exit with a special code
        # the magic is handled elsewhere
        await ctx.send('Restarting...')
        os._exit(RESTART)

    @meta.command(brief='Sets the origin uri to be used for next deployment', usage='[https_origin_uri]')
    @commands.has_role('Admin')
    async def set_origin_uri(self, ctx, origin_uri):
        """Sets the env var ORIGIN_URI to be used for next deployment."""
        await overwrite_file(file_name='ORIGIN_URI', line=origin_uri)
        await ctx.send(f'Set the origin uri to be {origin_uri}.')

    @meta.command(brief='Sets the commit hash to be used for next deployment.', usage='[commit_hash]')
    @commands.has_role('Admin')
    async def set_commit_hash(self, ctx, commit_hash):
        """Sets the env var COMMIT_HASH to be used for next deployment."""
        await overwrite_file(file_name='COMMIT_HASH', line=commit_hash)
        await ctx.send(f'Set the commit hash to be {commit_hash}.')
    

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

    @meta.command(brief='Get git information')
    async def git(self, ctx):
        """Replies with git information."""
        await ctx.send('```yaml\n' + git_history() + '```')

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
