import os
import aiohttp
import asyncio

from zipfile import ZipFile
from io import BytesIO

FONT_DIR = 'tle/assets/fonts'
URL_BASE = 'https://noto-website-2.storage.googleapis.com/pkgs/'
FONTS = ['NotoSansCJK-Bold.ttc', 'NotoSansCJK-Regular.ttc']

def unzip(font, archive):
    with ZipFile(archive, 'r') as zipfile:
        zipfile.extract(font, FONT_DIR)

async def main():
    if not os.path.exists(FONT_DIR):
        os.makedirs(FONT_DIR)

    async with aiohttp.ClientSession() as session:
        for font in FONTS:
            async with session.get(f'{URL_BASE}{font}.zip') as resp:
                if resp.status == 200:
                    unzip(font, BytesIO(await resp.read()))
                else:
                    print('Download failed')

if __name__ == '__main__':
    asyncio.run(download())
