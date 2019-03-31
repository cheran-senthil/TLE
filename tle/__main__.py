import logging
from os import environ
from pathlib import Path

from discord.ext import commands

BOT_TOKEN = environ.get('BOT_TOKEN')

logging.basicConfig(level=logging.INFO)


def main():
    if not BOT_TOKEN:
        logging.error('Token required')
        return
    bot = commands.Bot(command_prefix=commands.when_mentioned_or(';'))
    cogs = [file.stem for file in Path('tle', 'cogs').glob('*.py')]
    for extension in cogs:
        try:
            bot.load_extension(f'tle.cogs.{extension}')
        except Exception as e:
            logging.error(f'Failed to load extension {extension}: {e})')

    logging.info(f'Cogs loaded...')
    bot.run(BOT_TOKEN)
    logging.info(f'Bot running...')


if __name__ == '__main__':
    main()
