import asyncio
import logging

import discord
from discord.ext import commands

from tle import constants
from tle.util import discord_common


class StarboardCogError(commands.CommandError):
    pass


class Starboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.locks: dict[int, asyncio.Lock] = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        guild_id = payload.guild_id
        if guild_id is None:
            return
        emoji = str(payload.emoji)
        entry = await self.bot.user_db.get_starboard_entry(guild_id, emoji)
        if entry is None:
            return
        channel_id, threshold, color = entry
        try:
            await self.check_and_add_to_starboard(
                channel_id, threshold, color, emoji, payload
            )
        except StarboardCogError as e:
            self.logger.info(f'Failed to starboard: {e!r}')

    @commands.Cog.listener()
    async def on_raw_message_delete(
        self, payload: discord.RawMessageDeleteEvent
    ) -> None:
        if payload.guild_id is None:
            return
        removed = await self.bot.user_db.remove_starboard_message(
            starboard_msg_id=payload.message_id
        )
        if removed:
            self.logger.info(
                f'Removed starboard record for deleted message {payload.message_id}'
            )

    @staticmethod
    def prepare_embed(message: discord.Message, color: int) -> discord.Embed:
        embed = discord.Embed(color=color, timestamp=message.created_at)
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
                embed.add_field(
                    name='Attachment',
                    value=f'[{file.filename}]({file.url})',
                    inline=False,
                )

        embed.set_footer(
            text=str(message.author),
            icon_url=message.author.display_avatar.url,
        )
        return embed

    async def check_and_add_to_starboard(
        self,
        channel_id: int,
        threshold: int,
        color: int | None,
        emoji: str,
        payload: discord.RawReactionActionEvent,
    ) -> None:
        guild = self.bot.get_guild(payload.guild_id)
        starboard_channel = guild.get_channel(channel_id)
        if starboard_channel is None:
            raise StarboardCogError('Starboard channel not found')

        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        if message.type != discord.MessageType.default or (
            not message.content and not message.attachments
        ):
            raise StarboardCogError('Cannot starboard this message')

        count = sum(r.count for r in message.reactions if str(r) == emoji)
        if count < threshold:
            return

        lock = self.locks.setdefault(payload.guild_id, asyncio.Lock())
        async with lock:
            if await self.bot.user_db.check_exists_starboard_message(message.id, emoji):
                return
            embed = self.prepare_embed(message, color or constants._DEFAULT_COLOR)
            star_msg = await starboard_channel.send(embed=embed)
            await self.bot.user_db.add_starboard_message(
                message.id, star_msg.id, payload.guild_id, emoji
            )
            self.logger.info(f'Added message {message.id} to starboard under {emoji}')

    @commands.hybrid_group(brief='Starboard commands', fallback='show')
    async def starboard(self, ctx: commands.Context) -> None:
        """Group for commands involving the starboard."""
        await ctx.send_help(ctx.command)

    @starboard.command(brief='Add an emoji to starboard list')
    @commands.has_role(constants.TLE_ADMIN)
    async def add(
        self,
        ctx: commands.Context,
        emoji: str,
        threshold: int,
        color: str | None = None,
    ) -> None:
        """Register an emoji with a reaction threshold and optional hex color."""
        clr = int(color, 16) if color else constants._DEFAULT_COLOR
        await self.bot.user_db.add_starboard_emoji(ctx.guild.id, emoji, threshold, clr)
        await ctx.send(
            embed=discord_common.embed_success(
                f'Added {emoji}: threshold={threshold}, color={hex(clr)}'
            )
        )

    @starboard.command(brief='Delete an emoji from starboard list')
    @commands.has_role(constants.TLE_ADMIN)
    async def delete(self, ctx: commands.Context, emoji: str) -> None:
        """Unregister an emoji from starboard."""
        await self.bot.user_db.remove_starboard_emoji(ctx.guild.id, emoji)
        await self.bot.user_db.clear_starboard_channel(ctx.guild.id, emoji)
        await ctx.send(embed=discord_common.embed_success(f'Removed {emoji}'))

    @starboard.command(brief='Edit threshold for an emoji')
    @commands.has_role(constants.TLE_ADMIN)
    async def edit_threshold(
        self, ctx: commands.Context, emoji: str, threshold: int
    ) -> None:
        """Update reaction threshold for an emoji."""
        await self.bot.user_db.update_starboard_threshold(
            ctx.guild.id, emoji, threshold
        )
        await ctx.send(
            embed=discord_common.embed_success(
                f'Updated {emoji} threshold to {threshold}'
            )
        )

    @starboard.command(brief='Edit embed color for an emoji')
    @commands.has_role(constants.TLE_ADMIN)
    async def edit_color(self, ctx: commands.Context, emoji: str, color: str) -> None:
        """Update embed color (hex) for an emoji."""
        clr = int(color, 16)
        await self.bot.user_db.update_starboard_color(ctx.guild.id, emoji, clr)
        await ctx.send(
            embed=discord_common.embed_success(f'Updated {emoji} color to {hex(clr)}')
        )

    @starboard.command(brief='Set starboard channel (and optional color) for an emoji')
    @commands.has_role(constants.TLE_ADMIN)
    async def here(self, ctx: commands.Context, emoji: str) -> None:
        """Set the channel and optional color for an emoji."""
        await self.bot.user_db.set_starboard_channel(
            ctx.guild.id, emoji, ctx.channel.id
        )
        msg = f'Set {emoji} channel to {ctx.channel.mention}'
        await ctx.send(embed=discord_common.embed_success(msg))

    @starboard.command(brief='Clear starboard channel for an emoji')
    @commands.has_role(constants.TLE_ADMIN)
    async def clear(self, ctx: commands.Context, emoji: str) -> None:
        """Remove the starboard channel (and color) setting for an emoji."""
        await self.bot.user_db.clear_starboard_channel(ctx.guild.id, emoji)
        await ctx.send(
            embed=discord_common.embed_success(f'Cleared channel for {emoji}')
        )

    @starboard.command(brief='Remove a message from starboard')
    @commands.has_role(constants.TLE_ADMIN)
    async def remove(
        self, ctx: commands.Context, emoji: str, original_message_id: int
    ) -> None:
        """Remove a particular message from the starboard database."""
        rc = await self.bot.user_db.remove_starboard_message(
            original_msg_id=original_message_id, emoji=emoji
        )
        if rc:
            await ctx.send(embed=discord_common.embed_success('Successfully removed'))
        else:
            await ctx.send(embed=discord_common.embed_alert('Not found'))

    @discord_common.send_error_if(StarboardCogError)
    async def cog_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Starboard(bot))
