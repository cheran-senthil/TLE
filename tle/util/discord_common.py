import asyncio
import logging
import functools
import random

import discord
from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import db
from tle.util import tasks

logger = logging.getLogger(__name__)

_CF_COLORS = (0xFFCA1F, 0x198BCC, 0xFF2020)
_SUCCESS_GREEN = 0x28A745
_ALERT_AMBER = 0xFFBF00


def embed_neutral(desc, color=discord.Embed.Empty):
    return discord.Embed(description=str(desc), color=color)


def embed_success(desc):
    return discord.Embed(description=str(desc), color=_SUCCESS_GREEN)


def embed_alert(desc):
    return discord.Embed(description=str(desc), color=_ALERT_AMBER)


def random_cf_color():
    return random.choice(_CF_COLORS)


def cf_color_embed(**kwargs):
    return discord.Embed(**kwargs, color=random_cf_color())


def set_same_cf_color(embeds):
    color = random_cf_color()
    for embed in embeds:
        embed.color=color


def attach_image(embed, img_file):
    embed.set_image(url=f'attachment://{img_file.filename}')


def set_author_footer(embed, user):
    embed.set_footer(text=f'Requested by {user}', icon_url=user.avatar_url)


def send_error_if(*error_cls):
    """Decorator for `cog_command_error` methods. Decorated methods send the error in an alert embed
    when the error is an instance of one of the specified errors, otherwise the wrapped function is
    invoked.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(cog, ctx, error):
            if isinstance(error, error_cls):
                await ctx.send(embed=embed_alert(error))
                error.handled = True
            else:
                await func(cog, ctx, error)
        return wrapper
    return decorator


async def bot_error_handler(ctx, exception):
    if getattr(exception, 'handled', False):
        # Errors already handled in cogs should have .handled = True
        return

    if isinstance(exception, db.DatabaseDisabledError):
        await ctx.send(embed=embed_alert('Sorry, the database is not available. Some features are disabled.'))
    elif isinstance(exception, commands.NoPrivateMessage):
        await ctx.send(embed=embed_alert('Commands are disabled in private channels'))
    elif isinstance(exception, commands.DisabledCommand):
        await ctx.send(embed=embed_alert('Sorry, this command is temporarily disabled'))
    elif isinstance(exception, (cf.CodeforcesApiError, commands.UserInputError)):
        await ctx.send(embed=embed_alert(exception))
    else:
        msg = 'Ignoring exception in command {}:'.format(ctx.command)
        exc_info = type(exception), exception, exception.__traceback__
        extra = {
            "message_content": ctx.message.content,
            "jump_url": ctx.message.jump_url
        }
        logger.exception(msg, exc_info=exc_info, extra=extra)


def once(func):
    """Decorator that wraps the given async function such that it is executed only once."""
    first = True

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            await func(*args, **kwargs)

    return wrapper


def on_ready_event_once(bot):
    """Decorator that uses bot.event to set the given function as the bot's on_ready event handler,
    but does not execute it more than once.
    """
    def register_on_ready(func):
        @bot.event
        @once
        async def on_ready():
            await func()

    return register_on_ready


async def presence(bot):
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name='your commands'))
    await asyncio.sleep(60)

    @tasks.task(name='OrzUpdate',
               waiter=tasks.Waiter.fixed_delay(5*60))
    async def presence_task(_):
        while True:
            target = random.choice([
                member for member in bot.get_all_members()
                if 'Purgatory' not in {role.name for role in member.roles}
            ])
            await bot.change_presence(activity=discord.Game(
                name=f'{target.display_name} orz'))
            await asyncio.sleep(10 * 60)

    presence_task.start()
