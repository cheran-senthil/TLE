import os
import subprocess
import sys
import time
import textwrap

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
    out = subprocess.Popen(cmd, stdout = subprocess.PIPE, env=env).communicate()[0]
    return out

def git_history():
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
    except OSError as error:
        return f'Fetching git info failed with error: {error}'

def git_set_origin(origin_uri):
    try:
        out = _minimal_ext_cmd(['git', 'remote', 'set-url', 'origin', origin_uri])
        return out.strip().decode('ascii')
    except OSError as error:
        return f'Setting Origin URI to {origin_uri} failed with error: {error}'

def git_pull():
    try:
        out = _minimal_ext_cmd(['git', 'pull'])
        return out.strip().decode('ascii')
    except OSError as error:
        return f'Git Pull failed with error: {error}'

def git_fetch():
    try:
        out = _minimal_ext_cmd(['git', 'fetch', 'origin'])
        return out.strip().decode('ascii')
    except OSError as error:
        return f'Git fetch failed with error: {error}'

def git_reset(commit_hash):
    try:
        out = _minimal_ext_cmd(['git', 'reset', '--hard', commit_hash])
        return out.strip().decode('ascii')
    except OSError as error:
        return f'Git reset failed with error: {error}'

class Git(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    @commands.group(brief='Git commands', invoke_without_command=True)
    async def git(self, ctx):
        """Do git commands in the bot repo."""
        await ctx.send_help(ctx.command)

    @git.command(brief='git remote set-url origin $https_origin_uri', usage='[https_origin_uri]')
    @commands.has_role('Admin')
    async def set_origin_uri(self, ctx, origin_uri):
        await git_set_origin(origin_uri)
        await ctx.send(f'Set the origin uri to be {origin_uri}.')

    @git.command(brief='git reset --hard $commit_hash', usage='[commit_hash]')
    @commands.has_role('Admin')
    async def reset_to_commit(self, ctx, commit_hash):
        """Sets the env var COMMIT_HASH to be used for next deployment."""
        await git_reset(commit_hash)
        await ctx.send(f'Reset to the commit: {commit_hash}.')
    
    @git.command(brief='Get git information')
    @commands.has_role('Admin')
    async def history(self, ctx):
        """Replies with git information."""
        await ctx.send('```yaml\n' + git_history() + '```')

def setup(bot):
    bot.add_cog(Git(bot))
