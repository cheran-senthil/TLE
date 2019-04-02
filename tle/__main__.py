import logging
from os import environ
from pathlib import Path

import seaborn as sns
from discord.ext import commands
from matplotlib import pyplot as plt


def setglobaldefaults():
    # logging
    logging.basicConfig(level=logging.INFO)

    # matplotlib and seaborn
    plt.rcParams['figure.figsize'] = 7.0, 3.5
    sns.set()
    options = {
        'axes.edgecolor': '#A0A0C5',
        'axes.spines.top': False,
        'axes.spines.right': False,
    }
    sns.set_style('darkgrid', options)


def main():
    token = environ.get('BOT_TOKEN')
    if not token:
        logging.error('Token required')
        return

    setglobaldefaults()

    bot = commands.Bot(command_prefix=commands.when_mentioned_or(';'))
    cogs = [file.stem for file in Path('tle', 'cogs').glob('*.py')]
    for extension in cogs:
        try:
            bot.load_extension(f'tle.cogs.{extension}')
        except Exception as e:
            logging.error(f'Failed to load extension {extension}: {e})')

    logging.info(f'Cogs loaded...')
    bot.run(token)
    logging.info(f'Bot running...')


if __name__ == '__main__':
    main()
