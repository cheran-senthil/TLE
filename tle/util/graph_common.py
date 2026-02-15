import io
from collections.abc import Sequence

import discord
import matplotlib
import matplotlib.font_manager

matplotlib.use('agg')  # Explicitly set the backend to avoid issues

from cycler import cycler
from matplotlib import pyplot as plt

from tle import constants
from tle.util import codeforces_api as cf

rating_color_cycler = cycler(
    'color', ['#5d4dff', '#009ccc', '#00ba6a', '#b99d27', '#cb2aff']
)

fontprop = matplotlib.font_manager.FontProperties(
    fname=constants.NOTO_SANS_CJK_REGULAR_FONT_PATH
)


# String wrapper to avoid the underscore behavior in legends
#
# In legends, matplotlib ignores labels that begin with _
# https://matplotlib.org/api/pyplot_api.html#matplotlib.pyplot.legend
# However, this check is only done for actual string objects.
class StrWrap:
    def __init__(self, s: str) -> None:
        self.string = s

    def __str__(self) -> str:
        return self.string


def get_current_figure_as_file() -> discord.File:
    buffer = io.BytesIO()
    plt.savefig(
        buffer,
        format='png',
        facecolor=plt.gca().get_facecolor(),
        bbox_inches='tight',
        pad_inches=0.25,
    )
    plt.close()
    buffer.seek(0)
    return discord.File(buffer, filename='plot.png')


def plot_rating_bg(ranks: Sequence[cf.Rank]) -> None:
    ymin, ymax = plt.gca().get_ylim()
    bgcolor = plt.gca().get_facecolor()
    for rank in ranks:
        plt.axhspan(
            rank.low,
            rank.high,
            facecolor=rank.color_graph,
            alpha=0.8,
            edgecolor=bgcolor,
            linewidth=0.5,
        )

    locs, labels = plt.xticks()
    for loc in locs:
        plt.axvline(loc, color=bgcolor, linewidth=0.5)
    plt.ylim(ymin, ymax)
