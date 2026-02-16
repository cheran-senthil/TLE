import asyncio
import functools
import logging
import random
from collections.abc import Callable
from typing import Any

import discord
from discord.ext import commands

from tle import constants
from tle.util import codeforces_api as cf, db, tasks

logger = logging.getLogger(__name__)

_CF_COLORS = (0xFFCA1F, 0x198BCC, 0xFF2020)
_SUCCESS_GREEN = 0x28A745
_ALERT_AMBER = 0xFFBF00


def embed_neutral(desc: object, color: int | None = None) -> discord.Embed:
    return discord.Embed(description=str(desc), color=color)


def embed_success(desc: object) -> discord.Embed:
    return discord.Embed(description=str(desc), color=_SUCCESS_GREEN)


def embed_alert(desc: object) -> discord.Embed:
    return discord.Embed(description=str(desc), color=_ALERT_AMBER)


def random_cf_color() -> int:
    return random.choice(_CF_COLORS)


def cf_color_embed(**kwargs: Any) -> discord.Embed:
    return discord.Embed(**kwargs, color=random_cf_color())


def set_same_cf_color(embeds: list[discord.Embed]) -> None:
    color = random_cf_color()
    for embed in embeds:
        embed.color = color


def attach_image(embed: discord.Embed, img_file: discord.File) -> None:
    embed.set_image(url=f'attachment://{img_file.filename}')


def set_author_footer(
    embed: discord.Embed, user: discord.Member | discord.User
) -> None:
    embed.set_footer(text=f'Requested by {user}', icon_url=user.display_avatar.url)


def get_role(guild: discord.Guild, role_identifier: str | int) -> discord.Role | None:
    """Look up a role by name (str) or ID (int)."""
    if isinstance(role_identifier, int):
        return guild.get_role(role_identifier)
    return discord.utils.get(guild.roles, name=role_identifier)


def has_role(member: discord.Member, role_identifier: str | int) -> bool:
    """Check if member has a role identified by name (str) or ID (int)."""
    if isinstance(role_identifier, int):
        return any(role.id == role_identifier for role in member.roles)
    return any(role.name == role_identifier for role in member.roles)


def send_error_if(*error_cls: type[Exception]) -> Callable[..., Any]:
    """Decorator for `cog_command_error` methods.

    Decorated methods send the error in an alert embed when the error is an
    instance of one of the specified errors, otherwise the wrapped function is
    invoked.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(cog: Any, ctx: commands.Context, error: Exception) -> None:
            if isinstance(error, error_cls):
                await ctx.send(embed=embed_alert(error))
                error.handled = True  # type: ignore[attr-defined]
            else:
                await func(cog, ctx, error)

        return wrapper

    return decorator


async def bot_error_handler(ctx: commands.Context, exception: Exception) -> None:
    if getattr(exception, 'handled', False):
        # Errors already handled in cogs should have .handled = True
        return

    if isinstance(exception, db.DatabaseDisabledError):
        await ctx.send(
            embed=embed_alert(
                'Sorry, the database is not available. Some features are disabled.'
            )
        )
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
            'message_content': ctx.message.content,
            'jump_url': ctx.message.jump_url,
        }
        logger.exception(msg, exc_info=exc_info, extra=extra)


def once(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that wraps a coroutine such that it is executed only once."""
    first = True

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> None:
        nonlocal first
        if first:
            first = False
            await func(*args, **kwargs)

    return wrapper


async def presence(bot: Any) -> None:
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening, name='your commands'
        )
    )
    await asyncio.sleep(60)

    @tasks.task(name='OrzUpdate', waiter=tasks.Waiter.fixed_delay(10 * 60))
    async def presence_task(_: Any) -> None:
        target = random.choice(
            [
                member
                for member in bot.get_all_members()
                if not has_role(member, constants.TLE_PURGATORY)
            ]
        )
        await bot.change_presence(
            activity=discord.Game(name=f'{target.display_name} orz')
        )

    presence_task.start()
