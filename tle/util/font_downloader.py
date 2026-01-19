import logging
import os
import urllib.request
from tle import constants

# We define the direct links here because the Google zip links are broken
FONT_URLS = {
    "NotoSansCJK-Bold.ttc": "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTC/NotoSansCJK-Bold.ttc",
    "NotoSansCJK-Regular.ttc": "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTC/NotoSansCJK-Regular.ttc"
}

# Keep the original list reference
FONTS = [
    constants.NOTO_SANS_CJK_BOLD_FONT_PATH,
    constants.NOTO_SANS_CJK_REGULAR_FONT_PATH,
]

logger = logging.getLogger(__name__)

def maybe_download():
    # Create the folder if it doesn't exist
    if not os.path.exists(constants.FONTS_DIR):
        os.makedirs(constants.FONTS_DIR)

    for font_path in FONTS:
        if not os.path.isfile(font_path):
            font_name = os.path.basename(font_path)
            
            if font_name in FONT_URLS:
                url = FONT_URLS[font_name]
                logger.info(f'Downloading font `{font_name}` from GitHub...')
                try:
                    # Direct download instead of unzipping
                    urllib.request.urlretrieve(url, font_path) 
                    logger.info(f'Successfully downloaded `{font_name}`')
                except Exception as e:
                    logger.error(f'Failed to download `{font_name}`: {e}')
                    raise
            else:
                logger.warning(f"No download URL known for {font_name}")
