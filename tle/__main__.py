import argparse
import logging
import os
import asyncio
from os import environ
from pathlib import Path

import seaborn as sns
from discord.ext import commands
from matplotlib import pyplot as plt

from tle import constants
from tle import font_downloader
from tle.util import codeforces_common as cf_common
from tle.util import discord_common


def setup():
    # logging
    logging.basicConfig(format='{asctime}:{levelname}:{name}:{message}', style='{',
                        datefmt='%d-%m-%Y %H:%M:%S', level=logging.INFO)

    # matplotlib and seaborn
    plt.rcParams['figure.figsize'] = 7.0, 3.5
    sns.set()
    options = {
        'axes.edgecolor': '#A0A0C5',
        'axes.spines.top': False,
        'axes.spines.right': False,
    }
    sns.set_style('darkgrid', options)

    # Make dirs
    os.makedirs(constants.FILEDIR, exist_ok=True)
    if not os.path.isfile(constants.NOTO_SANS_CJK_FONT_PATH):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(font_downloader.main())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--nodb', action='store_true')
    args = parser.parse_args()

    token = environ.get('BOT_TOKEN')
    if not token:
        logging.error('Token required')
        return

    setup()

    bot = commands.Bot(command_prefix=commands.when_mentioned_or(';'))
    cogs = [file.stem for file in Path('tle', 'cogs').glob('*.py')]
    for extension in cogs:
        try:
            bot.load_extension(f'tle.cogs.{extension}')
        except Exception as e:
            logging.error(f'Failed to load extension {extension}: {e})')

    logging.info(f'Cogs loaded...')

    def no_dm_check(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage('Private messages not permitted.')
        return True

    # Restrict bot usage to inside guild channels only.
    bot.add_check(no_dm_check)

    @bot.event
    async def on_ready():
        await cf_common.initialize(args.nodb)

    bot.add_listener(discord_common.bot_error_handler, name='on_command_error')

    bot.run(token)


if __name__ == '__main__':
    main()
