import os
import urllib.request

from zipfile import ZipFile
from io import BytesIO

FONT_DIR = 'tle/assets/fonts'
URL_BASE = 'https://noto-website-2.storage.googleapis.com/pkgs/'
FONTS = ['NotoSansCJK-Bold.ttc', 'NotoSansCJK-Regular.ttc']

def _unzip(font, archive):
    with ZipFile(archive, 'r') as zipfile:
        zipfile.extract(font, FONT_DIR)

def _download(font):
    with urllib.request.urlopen(f'{URL_BASE}{font}.zip') as resp:
        _unzip(font, BytesIO(resp.read()))

def maybe_download():
    os.makedirs(FONT_DIR, exist_ok=True)
    for font in FONTS:
        if not os.path.isfile(os.path.join(FONT_DIR, font)):
            _download(font)
