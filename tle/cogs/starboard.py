import asyncio
import logging

import discord
from discord.ext import commands

from tle.util import codeforces_common as cf_common
from tle.util import discord_common

_STAR = '\N{WHITE MEDIUM STAR}'
_STAR_ORANGE = 0xffaa10
_STAR_THRESHOLD = 3


class StarboardCogError(commands.CommandError):
    pass


class Starboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.locks = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if str(payload.emoji) != _STAR or payload.guild_id is None:
            return
        res = cf_common.user_db.get_starboard_settings(payload.guild_id)
        if res is None:
            return
        starboard_channel_id = int(res[0])
        try:
            await self.check_and_add_to_starboard(starboard_channel_id, payload)
        except StarboardCogError as e:
            self.logger.info(f'Failed to starboard: {e!r}')

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id is None:
            return
        res = cf_common.user_db.get_starboard_settings(payload.guild_id)
        if res is None:
            return
        starboard_channel_id = int(res[0])
        if payload.channel_id != starboard_channel_id:
            return
        cf_common.user_db.remove_starboard_message(payload.message_id)
        self.logger.info(f'Removed message {payload.message_id} from starboard')

    @staticmethod
    def prepare_embed(message):
        # Adapted from https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/stars.py
        embed = discord.Embed(color=_STAR_ORANGE, timestamp=message.created_at)
        if message.content:
            embed.add_field(name='Content', value=message.content, inline=False)

        if message.embeds:
            data = message.embeds[0]
            if data.type == 'image':
                embed.set_image(url=data.url)

        if message.attachments:
            file = message.attachments[0]
            if file.url.lower().endswith(('png', 'jpeg', 'jpg', 'gif', 'webp')):
                embed.set_image(url=file.url)
            else:
                embed.add_field(name='Attachment', value=f'[{file.filename}]({file.url})', inline=False)

        embed.add_field(name='Channel', value=message.channel.mention)
        embed.add_field(name='Jump to', value=f'[Original]({message.jump_url})')
        embed.set_footer(text=str(message.author), icon_url=message.author.avatar_url)
        return embed

    async def check_and_add_to_starboard(self, starboard_channel_id, payload):
        starboard_channel = self.bot.get_guild(payload.guild_id).get_channel(starboard_channel_id)
        if starboard_channel is None:
            raise StarboardCogError('Starboard channel not found')

        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        if (message.type != discord.MessageType.default or
                len(message.content) == 0 and len(message.attachments) == 0):
            raise StarboardCogError('Cannot starboard this message')

        is_admin = any(str(role) == 'Admin' for role in message.author.roles)
        reaction_count = sum(str(reaction) == _STAR for reaction in message.reactions)
        if not is_admin and reaction_count < _STAR_THRESHOLD:
            return

        lock = self.locks.get(payload.guild_id)
        if lock is None:
            self.locks[payload.guild_id] = lock = asyncio.Lock()

        async with lock:
            if cf_common.user_db.check_exists_starboard_message(message.id):
                return
            embed = self.prepare_embed(message)
            starboard_message = await starboard_channel.send(embed=embed)
            cf_common.user_db.add_starboard_message(message.id, starboard_message.id)
            self.logger.info(f'Added message {message.id} to starboard')

    @commands.group(brief='Starboard commands',
                    invoke_without_command=True)
    async def starboard(self, ctx):
        """Group for commands involving the starboard"""
        await ctx.send_help(ctx.command)

    @starboard.command(brief='Set starboard to current channel')
    @commands.has_role('Admin')
    async def here(self, ctx):
        """Set the current channel as starboard"""
        cf_common.user_db.set_starboard_settings(ctx.guild.id, ctx.channel.id)
        await ctx.send(embed=discord_common.embed_success('Starboard channel set'))

    @starboard.command(brief='Clear starboard settings')
    @commands.has_role('Admin')
    async def clear(self, ctx):
        """Remove the current starboard channel, if set, from starboard settings"""
        cf_common.user_db.clear_starboard_settings(ctx.guild.id)
        await ctx.send(embed=discord_common.embed_success('Starboard settings cleared'))

    @starboard.command(brief='Remove a message from starboard')
    @commands.has_role('Admin')
    async def remove(self, ctx, starboard_message_id: int):
        """Remove a particular message from the starboard database"""
        rc = cf_common.user_db.remove_starboard_message(starboard_message_id)
        if rc:
            await ctx.send(embed=discord_common.embed_success('Success'))
        else:
            await ctx.send(embed=discord_common.embed_alert('Not found in database'))


def setup(bot):
    bot.add_cog(Starboard(bot))
