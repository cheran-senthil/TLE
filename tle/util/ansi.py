"""ANSI escape code helpers for Discord ```ansi``` code blocks."""

from __future__ import annotations

from collections.abc import Callable

from tle.util import codeforces_api as cf

RESET = '\u001b[0m'

# Rank title -> ANSI escape code
_RANK_ANSI: dict[str, str] = {
    'Newbie': '\u001b[30m',
    'Pupil': '\u001b[32m',
    'Specialist': '\u001b[36m',
    'Expert': '\u001b[34m',
    'Candidate Master': '\u001b[35m',
    'Master': '\u001b[33m',
    'International Master': '\u001b[1;33m',
    'Grandmaster': '\u001b[31m',
    'International Grandmaster': '\u001b[1;31m',
    'Legendary Grandmaster': '\u001b[1;31m',
    'Unrated': '\u001b[30m',
}

# Log-level ANSI constants (used by tle/cogs/logging.py)
ANSI_GREEN = '\u001b[32m'
ANSI_YELLOW = '\u001b[33m'
ANSI_RED = '\u001b[31m'
ANSI_BOLD_RED = '\u001b[1;31m'
ANSI_WHITE = '\u001b[37m'


def make_cell_colors(
    rank: cf.Rank, ncols: int, handle_col: int
) -> list[Callable[[str], str]] | None:
    """Return per-cell color callables for a table row, or ``None``.

    For Legendary Grandmaster the first character of the handle cell
    keeps the default color while the rest is bold red.
    """
    code = _RANK_ANSI.get(rank.title, '')
    if not code:
        return None

    def wrap(s: str) -> str:
        return code + s + RESET

    colors: list[Callable[[str], str]] = [wrap] * ncols

    if rank.title == 'Legendary Grandmaster':

        def wrap_lgm(s: str) -> str:
            if s:
                return s[0] + code + s[1:] + RESET
            return wrap(s)

        colors[handle_col] = wrap_lgm

    return colors
