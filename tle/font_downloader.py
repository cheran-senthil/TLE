import os
import urllib.request

from zipfile import ZipFile
from io import BytesIO

FONT_DIR = 'tle/assets/fonts'
URL_BASE = 'https://noto-website-2.storage.googleapis.com/pkgs/'
FONTS = ['NotoSansCJK-Bold.ttc', 'NotoSansCJK-Regular.ttc']

def unzip(font, archive):
    with ZipFile(archive, 'r') as zipfile:
        zipfile.extract(font, FONT_DIR)

def main():
    if not os.path.exists(FONT_DIR):
        os.makedirs(FONT_DIR)

    for font in FONTS:
        with urllib.request.urlopen(f'{URL_BASE}{font}.zip') as resp:
            unzip(font, BytesIO(resp.read()))

if __name__ == '__main__':
    main()
