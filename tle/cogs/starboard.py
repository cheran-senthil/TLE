# starboard.py
import asyncio
import logging

import discord
from discord.ext import commands

from tle import constants
from tle.util import codeforces_common as cf_common
from tle.util import discord_common

class StarboardCogError(commands.CommandError):
    pass


class Starboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.locks = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        guild_id = payload.guild_id
        if guild_id is None:
            return
        emoji = str(payload.emoji)
        entry = cf_common.user_db.get_starboard_entry(guild_id, emoji)
        if entry is None:
            return
        channel_id, threshold = entry
        try:
            await self.check_and_add_to_starboard(channel_id, threshold, emoji, payload)
        except StarboardCogError as e:
            self.logger.info(f'Failed to starboard: {e!r}')

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id is None:
            return
        removed = cf_common.user_db.remove_starboard_message(starboard_msg_id=payload.message_id)
        if removed:
            self.logger.info(f'Removed starboard record for deleted message {payload.message_id}')

    @staticmethod
    def prepare_embed(message):
        # Adapted from https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/stars.py
        embed = discord.Embed(color=_STAR_ORANGE, timestamp=message.created_at)
        embed.add_field(name='Channel', value=message.channel.mention)
        embed.add_field(name='Jump to', value=f'[Original]({message.jump_url})')

        if message.content:
            embed.add_field(name='Content', value=message.content, inline=False)

        if message.embeds:
            data = message.embeds[0]
            if data.type == 'image':
                embed.set_image(url=data.url)

        if message.attachments:
            file = message.attachments[0]
            if file.filename.lower().endswith(('png', 'jpeg', 'jpg', 'gif', 'webp')):
                embed.set_image(url=file.url)
            else:
                embed.add_field(name='Attachment', value=f'[{file.filename}]({file.url})', inline=False)

        embed.set_footer(text=str(message.author), icon_url=message.author.avatar_url)
        return embed

    async def check_and_add_to_starboard(self, starboard_channel_id, threshold, emoji, payload):
        guild = self.bot.get_guild(payload.guild_id)
        starboard_channel = guild.get_channel(starboard_channel_id)
        if starboard_channel is None:
            raise StarboardCogError('Starboard channel not found')

        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        if message.type != discord.MessageType.default or (not message.content and not message.attachments):
            raise StarboardCogError('Cannot starboard this message')

        reaction_count = sum(r.count for r in message.reactions if str(r) == emoji)
        if reaction_count < threshold:
            return

        lock = self.locks.get(payload.guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[payload.guild_id] = lock

        async with lock:
            if cf_common.user_db.check_exists_starboard_message(message.id, emoji):
                return
            embed = self.prepare_embed(message)
            star_msg = await starboard_channel.send(embed=embed)
            cf_common.user_db.add_starboard_message(message.id, star_msg.id, payload.guild_id, emoji)
            self.logger.info(f'Added message {message.id} to starboard under {emoji}')

    @commands.group(brief='Starboard commands',
                    invoke_without_command=True)
    async def starboard(self, ctx):
        """Group for commands involving the starboard."""
        await ctx.send_help(ctx.command)

    @starboard.command(brief='Set starboard channel for an emoji')
    @commands.has_role(constants.TLE_ADMIN)
    async def here(self, ctx, emoji: str):
        """Set the channel to post starred messages for an emoji."""
        cf_common.user_db.set_starboard_channel(ctx.guild.id, emoji, ctx.channel.id)
        await ctx.send(embed=discord_common.embed_success(
            f'Set {emoji} starboard channel to {ctx.channel.mention}'))

    @starboard.command(brief='Clear starboard channel for an emoji')
    @commands.has_role(constants.TLE_ADMIN)
    async def clear(self, ctx, emoji: str):
        """Remove the starboard channel setting for an emoji."""
        cf_common.user_db.clear_starboard_channel(ctx.guild.id, emoji)
        await ctx.send(embed=discord_common.embed_success(
            f'Cleared starboard channel for {emoji}'))

    @starboard.command(brief='Add an emoji to starboard list')
    @commands.has_role(constants.TLE_ADMIN)
    async def add(self, ctx, emoji: str, threshold: int):
        """Register an emoji with a reaction threshold."""
        cf_common.user_db.add_starboard_emoji(ctx.guild.id, emoji, threshold)
        await ctx.send(embed=discord_common.embed_success(
            f'Added emoji {emoji} with threshold {threshold}'))

    @starboard.command(brief='Delete an emoji from starboard list')
    @commands.has_role(constants.TLE_ADMIN)
    async def delete(self, ctx, emoji: str):
        """Unregister an emoji from starboard."""
        cf_common.user_db.remove_starboard_emoji(ctx.guild.id, emoji)
        await ctx.send(embed=discord_common.embed_success(
            f'Removed emoji {emoji}'))

    @starboard.command(brief='Remove a message from starboard')
    @commands.has_role(constants.TLE_ADMIN)
    async def remove(self, ctx, emoji: str, original_message_id: int):
        """Remove a particular message from the starboard database for a given emoji."""
        rc = cf_common.user_db.remove_starboard_message(original_msg_id=(original_message_id, emoji))
        if rc:
            await ctx.send(embed=discord_common.embed_success('Successfully removed'))
        else:
            await ctx.send(embed=discord_common.embed_alert('Not found in database'))

    @starboard.command(brief='Edit threshold for an emoji')
    @commands.has_role(constants.TLE_ADMIN)
    async def edit(self, ctx, emoji: str, threshold: int):
        """Update reaction threshold for an emoji."""
        cf_common.user_db.update_starboard_threshold(ctx.guild.id, emoji, threshold)
        await ctx.send(embed=discord_common.embed_success(
            f'Updated {emoji} threshold to {threshold}'))

    @discord_common.send_error_if(StarboardCogError)
    async def cog_command_error(self, ctx, error):
        pass


def setup(bot):
    bot.add_cog(Starboard(bot))
