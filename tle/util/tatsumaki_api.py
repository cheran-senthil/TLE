from os import environ
from discord.ext import commands

import aiohttp
import logging

API_BASE_URL = 'https://api.tatsumaki.xyz/'
API_KEY = environ.get('TATSU_TOKEN')

logger = logging.getLogger(__name__)

_session = None

async def initialize():
    global _session
    _session = aiohttp.ClientSession()

async def _query_api(path, params=None):
    url = API_BASE_URL + path
    try:
        logger.info(f'Querying Tatsu API at {url} with {params}')
        headers = {'Accept-Encoding': 'gzip', 'Authorization': API_KEY}
        async with _session.get(url, params=params, headers=headers) as resp:
            try:
                respjson = await resp.json()
            except aiohttp.ContentTypeError:
                logger.warning(f'Tatsu API did not respond with JSON, status {resp.status}.')
                raise commands.CommandError
            if resp.status == 200:
                return respjson
            comment = f'HTTP Error {resp.status}, {respjson.get("comment")}'
    except aiohttp.ClientError as e:
        logger.error(f'Request to CF API encountered error: {e!r}')
        raise commands.CommandError from e

async def leaderboard(guild):
    return await _query_api(f'guilds/{guild}/leaderboard')
