import os
import subprocess
import sys
import time
import textwrap
import logging

from discord.ext import commands
from tle.util.codeforces_common import pretty_time_format


# Make sure that running the following commands does not need credentials.
# You can store your credentials using: git config --global credential.helper store

# Adapted from numpy sources.
# https://github.com/numpy/numpy/blob/master/setup.py#L64-85
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
    out = subprocess.Popen(cmd, stdout = subprocess.PIPE, env=env, stderr = subprocess.STDOUT).communicate()[0]
    return out.strip().decode('ascii')

def _git_history():
    try:
        branch = _minimal_ext_cmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        history = _minimal_ext_cmd(['git', 'log', '--oneline', '-5'])
        return (
            'Branch:\n' +
            textwrap.indent(branch, '  ') +
            '\nCommits:\n' +
            textwrap.indent(history, '  ')
        )
    except OSError as error:
        return f'Fetching git info failed with error: {error}'

def _git_set_origin(origin_uri):
    try:
        return _minimal_ext_cmd(['git', 'remote', 'set-url', 'origin', origin_uri])
    except OSError as error:
        return f'Setting Origin URI to {origin_uri} failed with error: {error}'

def _git_fetch(branch_name):
    try:
        return _minimal_ext_cmd(['git', 'fetch', 'origin', f'{branch_name}'])
    except OSError as error:
        return f'Git fetch failed with error: {error}'

def _git_checkout(branch_name):
    try:
        return _minimal_ext_cmd(['git', 'checkout', f'origin/{branch_name}'])
    except OSError as error:
        return f'Git checkout failed with error: {error}'


class Git(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.group(brief='Git commands', invoke_without_command=True)
    async def git(self, ctx):
        """Do git commands in the bot repo."""
        await ctx.send_help(ctx.command)

    @git.command(brief='git remote set-url origin $https_origin_uri', usage='[https_origin_uri]')
    @commands.has_role('Admin')
    async def set_origin_uri(self, ctx, origin_uri):
        self.logger.info(f'Setting origin uri to {origin_uri}')
        _git_set_origin(origin_uri) # It doesn't have any output.
        await ctx.send(f'Set remote origin uri to {origin_uri}')

    @git.command(brief='git fetch origin $branch_name followed by git checkout origin/$branch_name', usage='[branch_name]')
    @commands.has_role('Admin')
    async def checkout(self, ctx, branch_name):
        self.logger.info(f'Fetching origin/{branch_name}')
        out = _git_fetch(branch_name)
        await ctx.send(f'Fetching {branch_name}, output:\n{out}')
        self.logger.info(f'Checking out to origin/{branch_name}')
        out = _git_checkout(branch_name)
        await ctx.send(f'Checking out to {branch_name}, output:\n{out}')
    
    @git.command(brief='Get git information')
    @commands.has_role('Admin')
    async def history(self, ctx):
        """Replies with git information."""
        await ctx.send('```yaml\n' + _git_history() + '```')

def setup(bot):
    bot.add_cog(Git(bot))
