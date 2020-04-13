"""This script scrapes contests and their writers from Codeforces and saves
them to a JSON file. This exists because there is no way to do this through
the official API :(
"""

import json
import urllib.request

from lxml import html

URL = 'https://codeforces.com/contests/page/{}'
JSONFILE = 'contest_writers.json'

def get_page(pagenum):
    url = URL.format(pagenum)
    with urllib.request.urlopen(url) as f:
        text = f.read().decode()
    return html.fromstring(text)

def get_contests(doc):
    contests = []
    rows = doc.xpath('//div[@class="contests-table"]//table[1]//tr')[1:]
    for row in rows:
        contest_id = int(row.get('data-contestid'))
        name, writers, start, length, standings, registrants = row.xpath('td')
        writers = writers.text_content().split()
        contests.append({'id': contest_id, 'writers': writers})
    return contests


print('Fetching page 1')
page1 = get_page(1)
lastpage = int(page1.xpath('//span[@class="page-index"]')[-1].get('pageindex'))

contests = get_contests(page1)
print(f'Found {len(contests)} contests')

for pagenum in range(2, lastpage + 1):
    print(f'Fetching page {pagenum}')
    page = get_page(pagenum)
    page_contests = get_contests(page)
    print(f'Found {len(page_contests)} contests')
    contests.extend(page_contests)

print(f'Found total {len(contests)} contests')

with open(JSONFILE, 'w') as f:
    json.dump(contests, f)
print(f'Data written to {JSONFILE}')
