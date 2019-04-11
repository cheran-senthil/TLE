import random

import discord

_CF_COLORS = (0xFFCA1F, 0x198BCC, 0xFF2020)
_SUCCESS_GREEN = 0x00A000
_ALERT_AMBER = 0xFFBF00


def simple_embed(desc, color=discord.Embed.Empty):
    return discord.Embed(description=desc, color=color)


def embed_success(desc):
    return simple_embed(desc, _SUCCESS_GREEN)


def embed_alert(desc):
    return simple_embed(desc, _ALERT_AMBER)


def cf_color_embed(**kwargs):
    return discord.Embed(**kwargs, color=random.choice(_CF_COLORS))


def attach_image(embed, img_file):
    embed.set_image(url=f'attachment://{img_file.filename}')


def set_author_footer(embed, user):
    embed.set_footer(text=f'Requested by {user}')
