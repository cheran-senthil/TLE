import logging
import random

import discord
from discord.ext import commands

from tle.util import handle_conn

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


def cf_color_embed(**kwargs):
    return discord.Embed(**kwargs, color=random.choice(_CF_COLORS))


def attach_image(embed, img_file):
    embed.set_image(url=f'attachment://{img_file.filename}')


def set_author_footer(embed, user):
    embed.set_footer(text=f'Requested by {user}', icon_url=user.avatar_url)


async def bot_error_handler(ctx, exception):
    if getattr(exception, 'handled', False):
        # Errors already handled in cogs should have .handled = True
        return

    if isinstance(exception, handle_conn.DatabaseDisabledError):
        await ctx.send(embed=embed_alert('Sorry, the database is not available. Some features are disabled.'))
    elif isinstance(exception, commands.NoPrivateMessage):
        await ctx.send(embed=embed_alert('Commands are disabled in private channels'))
    else:
        exc_info = type(exception), exception, exception.__traceback__
        logger.exception('Ignoring exception in command {}:'.format(ctx.command), exc_info=exc_info)
