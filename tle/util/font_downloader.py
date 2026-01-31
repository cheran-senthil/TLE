import logging
import os
import urllib.request

from tle import constants

URL_BASE = 'https://github.com/notofonts/noto-cjk/raw/main/Sans/OTC/'
FONTS = {
    constants.NOTO_SANS_CJK_BOLD_FONT_PATH,
    constants.NOTO_SANS_CJK_REGULAR_FONT_PATH,
}

logger = logging.getLogger(__name__)


def _download(font_path):
    font = os.path.basename(font_path)
    logger.info(f'Downloading font `{font}`.')
    with urllib.request.urlopen(f'{URL_BASE}{font}') as resp:
        if resp.status != 200:
            msg = f'Failed to download font `{font}`. HTTP status code: {resp.status}.'
            logger.error(msg)
            raise ConnectionError(msg)
        logger.info(f'Successfully downloaded font `{font}`.')
        data = resp.read()
        with open(font_path, 'wb') as f:
            f.write(data)


def maybe_download():
    for font_path in FONTS:
        if not os.path.isfile(font_path):
            _download(font_path)
