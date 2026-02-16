import os
import subprocess
import sys
import textwrap
import time

from discord.ext import commands

from tle import constants
from tle.util.codeforces_common import pretty_time_format


# Adapted from numpy sources.
# https://github.com/numpy/numpy/blob/master/setup.py#L64-85
def git_history() -> str:
    def _minimal_ext_cmd(cmd: list[str]) -> bytes:
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
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env)
        out = proc.communicate(timeout=10)[0]
        return out

    try:
        out = _minimal_ext_cmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        branch = out.strip().decode('ascii')
        out = _minimal_ext_cmd(['git', 'log', '--oneline', '-5'])
        history = out.strip().decode('ascii')
        return (
            'Branch:\n'
            + textwrap.indent(branch, '  ')
            + '\nCommits:\n'
            + textwrap.indent(history, '  ')
        )
    except OSError:
        return 'Fetching git info failed'


class Meta(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.start_time = time.time()

    @commands.hybrid_group(brief='Bot control', fallback='show')
    async def meta(self, ctx: commands.Context) -> None:
        """Command the bot or get information about the bot."""
        await ctx.send_help(ctx.command)

    @meta.command(brief='Kill TLE')
    @commands.has_role(constants.TLE_ADMIN)
    async def kill(self, ctx: commands.Context) -> None:
        """Shuts down the bot gracefully."""
        await ctx.send('Shutting down...')
        await self.bot.close()
        sys.exit(0)

    @meta.command(brief='Is TLE up?')
    async def ping(self, ctx: commands.Context) -> None:
        """Replies to a ping."""
        start = time.perf_counter()
        message = await ctx.send(':ping_pong: Pong!')
        end = time.perf_counter()
        duration = (end - start) * 1000
        await message.edit(
            content=(
                f'REST API latency: {int(duration)}ms\n'
                f'Gateway API latency: {int(self.bot.latency * 1000)}ms'
            )
        )

    @meta.command(brief='Get git information')
    async def git(self, ctx: commands.Context) -> None:
        """Replies with git information."""
        await ctx.send('```yaml\n' + git_history() + '```')

    @meta.command(brief='Prints bot uptime')
    async def uptime(self, ctx: commands.Context) -> None:
        """Replies with how long TLE has been up."""
        await ctx.send(
            'TLE has been running for '
            + pretty_time_format(time.time() - self.start_time)
        )

    @meta.command(brief='Print bot guilds')
    @commands.has_role(constants.TLE_ADMIN)
    async def guilds(self, ctx: commands.Context) -> None:
        "Replies with info on the bot's guilds"
        msg = [
            ' | '.join(
                [
                    f'Guild ID: {guild.id}',
                    f'Name: {guild.name}',
                    f'Owner: {guild.owner.id}',
                    f'Icon: {guild.icon.url if guild.icon else None}',
                ]
            )
            for guild in self.bot.guilds
        ]
        await ctx.send('```' + '\n'.join(msg) + '```')


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meta(bot))
