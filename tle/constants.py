import os
from pathlib import Path

DATA_DIR = Path('data')
LOGS_DIR = Path('logs')

DB_DIR = DATA_DIR / 'db'
MISC_DIR = DATA_DIR / 'misc'
TEMP_DIR = DATA_DIR / 'temp'

USER_DB_FILE_PATH = DB_DIR / 'user.db'
CACHE_DB_FILE_PATH = DB_DIR / 'cache.db'

_SYSTEM_FONT_DIR = Path('/usr/share/fonts/opentype/noto')
NOTO_SANS_CJK_BOLD_FONT_PATH = _SYSTEM_FONT_DIR / 'NotoSansCJK-Bold.ttc'
NOTO_SANS_CJK_REGULAR_FONT_PATH = (
    _SYSTEM_FONT_DIR / 'NotoSansCJK-Regular.ttc'
)

CONTEST_WRITERS_JSON_FILE_PATH = MISC_DIR / 'contest_writers.json'

LOG_FILE_PATH = LOGS_DIR / 'tle.log'

ALL_DIRS = tuple(
    attrib_value
    for attrib_name, attrib_value in list(globals().items())
    if attrib_name.endswith('DIR')
)

ALLOW_DUEL_SELF_REGISTER = False


def _get_role_from_env(name: str, default: str) -> str | int:
    value = os.environ.get(name, default)
    # Try parsing as an int, which is a role id.
    try:
        return int(value)
    except ValueError:
        return value


TLE_ADMIN = _get_role_from_env('TLE_ADMIN', 'Admin')
TLE_MODERATOR = _get_role_from_env('TLE_MODERATOR', 'Moderator')
TLE_TRUSTED = _get_role_from_env('TLE_TRUSTED', 'Trusted')
TLE_PURGATORY = _get_role_from_env('TLE_PURGATORY', 'Purgatory')

_DEFAULT_COLOR = 0xFFAA10
_DEFAULT_STAR = '\N{WHITE MEDIUM STAR}'
