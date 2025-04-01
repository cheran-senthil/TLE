import asyncio
import logging

import discord
from discord.ext import commands

from tle import constants
from tle.util import codeforces_common as cf_common
from tle.util import discord_common

# Define all reaction boards here
# Format: (emoji, name, color, threshold)
REACTION_BOARDS = [
    ('\N{WHITE MEDIUM STAR}', 'star', 0xffaa10, 5),  # Starboard
    ('\N{PILL}', 'pill', 0x1068da, 5)                # Pillboard
    # Add more boards here as needed:
    # ('\N{FIRE}', 'fire', 0xff4500, 5),             # Fireboard example
]


class ReactionBoardError(commands.CommandError):
    pass


class ReactionBoards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.locks = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Initialize locks for each board type
        for _, name, _, _ in REACTION_BOARDS:
            self.locks[name] = {}

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id is None:
            return

        emoji = str(payload.emoji)
        
        # Check if this emoji matches any configured boards
        for react_emoji, board_name, color, threshold in REACTION_BOARDS:
            if emoji == react_emoji:
                # Find channel with the corresponding name
                guild = self.bot.get_guild(payload.guild_id)
                board_channel = discord.utils.get(guild.text_channels, name=f"{board_name}board")
                
                if board_channel is None:
                    # No channel found for this board
                    continue
                
                try:
                    await self.check_and_add_to_board(board_name, board_channel.id, payload, 
                                                     color, threshold)
                except ReactionBoardError as e:
                    self.logger.info(f'Failed to add to {board_name}board: {e!r}')
                break

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id is None:
            return
            
        # Check if this is a message in any reaction board channel
        guild = self.bot.get_guild(payload.guild_id)
        for _, name, _, _ in REACTION_BOARDS:
            board_channel = discord.utils.get(guild.text_channels, name=f"{name}board")
            
            if board_channel and payload.channel_id == board_channel.id:
                # This is a message in a board channel that was deleted
                cf_common.user_db.remove_reaction_board_message(board_type=name, board_msg_id=payload.message_id)
                self.logger.info(f'Removed message {payload.message_id} from {name}board')

    def get_board_emoji(self, board_name):
        """Get the emoji for a board type"""
        for emoji, name, _, _ in REACTION_BOARDS:
            if name == board_name:
                return emoji
        return None

    def prepare_embed(self, message, color):
        """Prepare an embed for the reaction board."""
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
                embed.add_field(name='Attachment', value=f'[{file.filename}]({file.url})', inline=False)

        embed.set_footer(text=str(message.author), icon_url=message.author.avatar_url)
        return embed

    async def check_and_add_to_board(self, board_name, board_channel_id, payload, color, threshold):
        """Process reactions and add messages to the appropriate board."""
        emoji = self.get_board_emoji(board_name)
        
        guild = self.bot.get_guild(payload.guild_id)
        board_channel = guild.get_channel(board_channel_id)
        if board_channel is None:
            raise ReactionBoardError(f'{board_name.capitalize()}board channel not found')

        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        if (message.type != discord.MessageType.default or
                len(message.content) == 0 and len(message.attachments) == 0):
            raise ReactionBoardError(f'Cannot add to {board_name}board: Invalid message type')

        reaction_count = sum(reaction.count for reaction in message.reactions
                             if str(reaction) == emoji)
        if reaction_count < threshold:
            return

        # Get or create lock for this guild and board
        if guild.id not in self.locks[board_name]:
            self.locks[board_name][guild.id] = asyncio.Lock()
        lock = self.locks[board_name][guild.id]

        async with lock:
            # Check if message already exists in the board's database
            if cf_common.user_db.check_exists_reaction_board_message(board_type=board_name, original_msg_id=message.id):
                return
            
            # Create and send the embed
            embed = self.prepare_embed(message, color)
            board_message = await board_channel.send(embed=embed)
            
            # Store the message in the database
            cf_common.user_db.add_reaction_board_message(
                board_type=board_name, 
                original_msg_id=message.id, 
                board_msg_id=board_message.id, 
                guild_id=guild.id
            )
            
            self.logger.info(f'Added message {message.id} to {board_name}board')

    @commands.command(brief='Remove a message from a reaction board')
    @commands.has_role(constants.TLE_ADMIN)
    async def remove_from_board(self, ctx, board_name: str, message_id: int):
        """Remove a message from a reaction board.
        
        Example:
        !remove_from_board star 123456789
        !remove_from_board pill 123456789
        """
        # Normalize board name
        board_name = board_name.lower().strip()
        if board_name.endswith('board'):
            board_name = board_name[:-5]  # Remove 'board' suffix
            
        # Check if this board exists in our config
        valid_board = False
        for _, name, _, _ in REACTION_BOARDS:
            if name == board_name:
                valid_board = True
                break
                
        if not valid_board:
            board_names = [name for _, name, _, _ in REACTION_BOARDS]
            await ctx.send(f"Unknown board: '{board_name}'. Available boards: {', '.join(board_names)}")
            return
            
        # Remove the message
        removed = cf_common.user_db.remove_reaction_board_message(
            board_type=board_name, 
            original_msg_id=message_id
        )
        
        if removed:
            await ctx.send(embed=discord_common.embed_success("Message removed successfully"))
        else:
            await ctx.send(embed=discord_common.embed_alert("Message not found in that board"))

    @discord_common.send_error_if(ReactionBoardError)
    async def cog_command_error(self, ctx, error):
        pass


def setup(bot):
    bot.add_cog(ReactionBoards(bot))
