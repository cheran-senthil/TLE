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
    links = [li.get('href') for li in tree.xpath('//*[@class="task"]/a')]
    ids = sorted(int(x.split('/')[-1]) for x in links)
    return ids


async def get_problem_leaderboard(num):
    tree = await _fetch(f'https://cses.fi/problemset/stats/{num}/')
    fastest_table, shortest_table = tree.xpath(
        '//table[@class!="summary-table" and @class!="bot-killer"]')

    fastest = [a.text for a in fastest_table.xpath('.//a')]
    shortest = [a.text for a in shortest_table.xpath('.//a')]
    return fastest, shortest
