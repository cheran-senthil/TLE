import asyncio
import logging
import os

from discord.ext import commands

from tle.util import ansi, discord_common

root_logger = logging.getLogger()
logger = logging.getLogger(__name__)

_ANSI_BY_LEVEL = {
    logging.INFO: ansi.ANSI_GREEN,
    logging.WARNING: ansi.ANSI_YELLOW,
    logging.ERROR: ansi.ANSI_RED,
    logging.CRITICAL: ansi.ANSI_BOLD_RED,
}


class Logging(commands.Cog, logging.Handler):
    def __init__(self, bot: commands.Bot, channel_id: int) -> None:
        logging.Handler.__init__(self)
        self.bot = bot
        self.channel_id = channel_id
        self.queue: asyncio.Queue[logging.LogRecord] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.Cog.listener()
    @discord_common.once
    async def on_ready(self) -> None:
        self.task = asyncio.create_task(self._log_task())
        self.logger.log(level=100, msg='Bot running')

    async def _log_task(self) -> None:
        while True:
            record = await self.queue.get()
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                # Channel no longer exists.
                root_logger.removeHandler(self)
                self.logger.warning(
                    'Logging channel not available, disabling Discord log handler.'
                )
                break
            try:
                msg = self.format(record)
                message_content = getattr(record, 'message_content', None)
                jump_url = getattr(record, 'jump_url', None)
                if message_content or jump_url:
                    parts = []
                    if message_content:
                        parts.append(f'Original Command: {message_content}')
                    if jump_url:
                        parts.append(f'Jump Url: {jump_url}')
                    await channel.send('\n'.join(parts))
                color = _ANSI_BY_LEVEL.get(record.levelno, ansi.ANSI_WHITE)
                colored_msg = f'{color}{msg}{ansi.RESET}'
                discord_msg_char_limit = 2000
                wrapper = '```ansi\n```'
                char_limit = discord_msg_char_limit - len(wrapper)
                too_long = len(colored_msg) > char_limit
                colored_msg = colored_msg[:char_limit]
                await channel.send(f'```ansi\n{colored_msg}```')
                if too_long:
                    await channel.send('`Check logs for full stack trace`')
            except Exception:
                self.handleError(record)

    # logging.Handler overrides below.

    def emit(self, record: logging.LogRecord) -> None:
        self.queue.put_nowait(record)

    def close(self) -> None:
        if self.task:
            self.task.cancel()


async def setup(bot: commands.Bot) -> None:
    logging_cog_channel_id = os.environ.get('LOGGING_COG_CHANNEL_ID')
    if logging_cog_channel_id is None:
        logger.info(
            'Skipping installation of logging cog as logging channel is not provided.'
        )
        return

    logging_cog = Logging(bot, int(logging_cog_channel_id))
    logging_cog.setLevel(logging.WARNING)
    logging_cog.setFormatter(
        logging.Formatter(
            fmt='{asctime}:{levelname}:{name}:{message}',
            style='{',
            datefmt='%d-%m-%Y %H:%M:%S',
        )
    )
    root_logger.addHandler(logging_cog)
    await bot.add_cog(logging_cog)
