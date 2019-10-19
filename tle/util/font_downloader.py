import logging
import os
import urllib.request

from zipfile import ZipFile
from io import BytesIO

from tle import constants

URL_BASE = 'https://noto-website-2.storage.googleapis.com/pkgs/'
FONTS = [constants.NOTO_SANS_CJK_BOLD_FONT_PATH,
         constants.NOTO_SANS_CJK_REGULAR_FONT_PATH]

logger = logging.getLogger(__name__)


def _unzip(font, archive):
    with ZipFile(archive) as zipfile:
        if font not in zipfile.namelist():
            raise KeyError(f'Expected font file {font} not present in downloaded zip archive.')
        zipfile.extract(font, constants.FONTS_DIR)


def _download(font_path):
    font = os.path.basename(font_path)
    logger.info(f'Downloading font `{font}`.')
    with urllib.request.urlopen(f'{URL_BASE}{font}.zip') as resp:
        _unzip(font, BytesIO(resp.read()))


def maybe_download():
    for font_path in FONTS:
        if not os.path.isfile(font_path):
            _download(font_path)
