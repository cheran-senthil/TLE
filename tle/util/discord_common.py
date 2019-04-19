import random
import sys
import traceback

import discord

from tle.util import handle_conn

_CF_COLORS = (0xFFCA1F, 0x198BCC, 0xFF2020)
_SUCCESS_GREEN = 0x28A745
_ALERT_AMBER = 0xFFBF00


def embed_neutral(desc, color=discord.Embed.Empty):
    return discord.Embed(description=desc, color=color)


def embed_success(desc):
    return discord.Embed(description=desc, color=_SUCCESS_GREEN)


def embed_alert(desc):
    return discord.Embed(description=desc, color=_ALERT_AMBER)


def cf_color_embed(**kwargs):
    return discord.Embed(**kwargs, color=random.choice(_CF_COLORS))


def attach_image(embed, img_file):
    embed.set_image(url=f'attachment://{img_file.filename}')


def set_author_footer(embed, user):
    embed.set_footer(text=f'Requested by {user}', icon_url=user.avatar_url)


async def bot_error_handler(ctx, exception):
    # This is identical to the default error handler at
    # https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/bot.py
    # but it also handles DatabaseDisabledError.

    if hasattr(ctx.command, 'on_error'):
        return

    cog = ctx.cog
    if cog:
        attr = '_{0.__class__.__name__}__error'.format(cog)
        if hasattr(cog, attr):
            return

    if isinstance(exception, handle_conn.DatabaseDisabledError):
        await ctx.send(
            embed=embed_alert('Sorry, the database is not available. Some features are disabled.'))
        return

    print('Ignoring exception in command {}:'.format(ctx.command), file=sys.stderr)
    traceback.print_exception(type(exception), exception, exception.__traceback__, file=sys.stderr)
