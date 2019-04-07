from functools import lru_cache
from collections import namedtuple

import aiohttp
import logging
import json
import time

from tle.util import handle_conn as hc
from tle.util import codeforces_api as cf

ContestInfo = namedtuple('ContestInfo', 'name start_time')

class CacheSystem:
    # """
    #     Explanation: a pair of 'problems' returned from cf api may
    #     be the same (div 1 vs div 2). we pick one of them and call
    #     it 'base_problem' which will be used below:
    # """
    """
        ^ for now, we won't pick problems with the same name the user has solved
        there isn't a good way to do this with the current API
    """
    def __init__(self):
        self.contest_dict = None    # id => ContestInfo
        self.problem_dict = None    # name => problem
        self.problem_start = None   # id => start_time

        # self.problems = None
        # self.base_problems = None
        # this dict looks up a problem identifier and returns that of the base problem
        # self.problem_to_base = None

    async def cache_contests(self):
        try:
            contests = await cf.contest.list()
        except aiohttp.ClientConnectionError as e:
            print(e)
            return
        except cf.CodeforcesApiError as e:
            print(e)
            return
        self.contest_dict = {
            c.id : ContestInfo(c.name, c.startTimeSeconds)
            for c in contests
        }
        rc = hc.conn.cache_contests(contests)
        logging.info(f'{rc} contests cached')

    async def cache_problems(self):
        if self.contest_dict is None: 
            await self.cache_contests()            
        try:
            problems, _ = await cf.problemset.problems()
        except aiohttp.ClientConnectionError as e:
            print(e)
            return
        except cf.CodeforcesApiError as e:
            print(e)
            return
        banned_tags = ['*special']
        self.problem_dict = {
            prob.name : prob    # this will discard some valid problems
            for prob in problems 
            if prob.has_metadata() and not prob.tag_matches(banned_tags)
        }
        self.problem_start = {
            prob.contest_identifier : self.contest_dict[prob.contestId].start_time
            for prob in self.problem_dict.values()
        }    
        rc = hc.conn.cache_problems([
                (   
                    prob.name, prob.contestId, prob.index, 
                    self.contest_dict[prob.contestId].start_time,
                    prob.rating, json.dumps(prob.tags)
                )
                for prob in self.problem_dict.values()
            ])        
        logging.info(f'{rc} problems cached')

    # async def cache_problems(self):
    #     if self.contest_dict is None: 
    #         await self.cache_contests()            
    #     try:
    #         problems, _ = await cf.problemset.problems()
    #     except aiohttp.ClientConnectionError as e:
    #         print(e)
    #         return
    #     except cf.CodeforcesApiError as e:
    #         print(e)
    #         return
    #     banned_tags = ['*special']
    #     self.problem_dict = {
    #         prob.contest_identifier : prob
    #         for prob in problems
    #         if prob.has_metadata() and not prob.tag_matches(banned_tags)
    #     }
    #     self.problem_start = {
    #         pid : self.contest_dict[prob.contestId].start_time
    #         for pid, prob in self.problem_dict.items()
    #     }

    #     repeat_dict = dict()
    #     self.problem_to_base = dict()
    #     base_ids = set()
    #     for pid, prob in self.problem_dict.items():
    #         rep_elem = (prob.name, self.problem_start[pid])
    #         identifier = repeat_dict.get(rep_elem)
    #         if identifier is None:
    #             identifier = pid
    #             repeat_dict[rep_elem] = identifier
    #             base_ids.add(pid)
    #         self.problem_to_base[pid] = identifier
        
    #     self.base_problems = [self.problem_dict[base_id] for base_id in base_ids]                
    #     rc = hc.conn.cache_problems([
    #             (
    #                 pid, self.problem_to_base[pid],
    #                 prob.contestId, prob.index, prob.name, 
    #                 self.problem_start[pid], prob.rating, json.dumps(prob.tags)
    #             )
    #             for pid, prob in self.problem_dict.items()
    #         ])        
    #     logging.info(f'{rc} problems cached')

    async def fetch_rating_solved(self, handle: str):
        try:
            info = await cf.user.info(handles=[handle])
            subs = await cf.user.status(handle=handle)
            info = info[0]
            solved = [sub.problem for sub in subs if sub.verdict == 'OK']
            solved = { prob.name for prob in solved if prob.has_metadata() }
            stamp = time.time()
            hc.conn.cache_cfuser_full(info + (json.dumps(list(solved)), stamp))
            return stamp, info.rating, solved
        except aiohttp.ClientConnectionError as e:
            logging.error(e)
        except cf.CodeforcesApiError as e: 
            logging.error(e)
        return [None, None, None]
    
    async def retrieve_rating_solved(self, handle: str):
        res = hc.conn.fetch_rating_solved(handle)
        if res and res[0] is not None and res[1] is not None:
            return time.time(), res[0], set(json.loads(res[1]))
        return await self.fetch_rating_solved(handle)
        
    @lru_cache(maxsize=15)
    def user_rating_solved(self, handle: str):
        # this works. it will actually return a reference
        # the cache is for repeated requests and maxsize limits RAM usage
        return [None, None, None]





