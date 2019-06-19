import logging

import aiohttp
from lxml import html


class CSESError(Exception):
    pass


session = aiohttp.ClientSession()


async def _fetch(url):
    async with session.get(url) as response:
        if response.status != 200:
            raise CSESError(f"Bad response from CSES, status code {status}")
        tree = html.fromstring(await response.read())
    return tree


async def get_problems():
    tree = await _fetch('https://cses.fi/problemset/list/')
    links = [
        a.get('href') for table in tree.xpath('//table')[2:]
        for a in table.xpath('tr/td/a')
    ]
    ids = sorted(int(x.split('/')[-1]) for x in links)
    return ids


async def get_problem_leaderboard(num):
    tree = await _fetch(f'https://cses.fi/problemset/stats/{num}/')
    _, _, fastest_table, shortest_table = tree.xpath('//table')

    fastest = [tr[1].text_content() for tr in fastest_table]
    shortest = [tr[1].text_content() for tr in shortest_table]
    return fastest, shortest
