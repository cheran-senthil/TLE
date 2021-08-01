import datetime as dt
from time import time

from discord.ext import commands
import discord

from tle.util import clist_api as clist
from tle.util import codeforces_common as cf_common
from tle.util.ranklist.ranklist import CRanklist


class Resources:
    CODEFORCES = 'codeforces.com'
    CODECHEF = 'codechef.com'
    ATCODER = 'atcoder.jp'
    GOOGLE = 'codingcompetitions.withgoogle.com'
    CODEDRILLS = 'codedrills.io'


_SUPPORTED_RESOURCES = (Resources.CODEFORCES, Resources.CODECHEF, Resources.ATCODER, Resources.GOOGLE)
_RESOURCE_SHORT_FORMS = {
    'cc':Resources.CODECHEF,
    'codechef':Resources.CODECHEF, 
    
    'cf':Resources.CODEFORCES,
    'codeforces':Resources.CODEFORCES,
    
    'ac':Resources.ATCODER, 
    'atcoder':Resources.ATCODER, 

    'google':Resources.GOOGLE
}
_RANKLIST_PATTERNS = {
    'abc': Resources.ATCODER,
    'arc': Resources.ATCODER,
    'agc': Resources.ATCODER,

    'kickstart': Resources.GOOGLE,
    'codejam': Resources.GOOGLE,
    
    'lunchtime': Resources.CODECHEF,
    'long': Resources.CODECHEF,
    'cookoff': Resources.CODECHEF,
    'starters': Resources.CODECHEF
}

class ContestNotFoundError(commands.CommandError):
    pass

class InvalidContestID(commands.CommandError):
    pass

class RanklistNotFound(commands.CommandError):
    pass

class InvalidResource(commands.CommandError):
    pass

def parse_date(arg):
    try:
        if len(arg) == 8:
            fmt = '%d%m%Y'
        elif len(arg) == 6:
            fmt = '%m%Y'
        elif len(arg) == 4:
            fmt = '%Y'
        else:
            raise ValueError
        return dt.datetime.strptime(arg, fmt)
    except ValueError:
        raise clist.ClistApiError(f'{arg} is an invalid date argument')

async def resolve_handles(ctx, converter, handles, *, mincnt=1, maxcnt=5, default_to_all_server=False, resource=Resources.CODEFORCES):
    if resource==Resources.CODEFORCES:
        return await cf_common.resolve_handles(ctx, converter, handles, mincnt=mincnt, maxcnt=maxcnt, default_to_all_server=default_to_all_server)
    # Resolve handles for resources other than CodeForces
    handles = set(handles)
    if default_to_all_server and not handles:
        handles.add('+server')
    account_ids = set()
    if '+server' in handles:
        handles.remove('+server')
        guild_account_ids = {account_id for discord_id, account_id in 
                cf_common.user_db.get_account_ids_for_guild(ctx.guild.id, resource=resource)}
        account_ids.update(guild_account_ids)
    count = len(account_ids) + len(handles)
    if count < mincnt or (maxcnt and maxcnt < count):
        raise cf_common.HandleCountOutOfBoundsError(mincnt, maxcnt)
    unresolved_handles = set()
    for handle in handles:
        if handle.startswith('!'):
            # ! denotes Discord user
            member_identifier = handle[1:]
            try:
                member = await converter.convert(ctx, member_identifier)
            except commands.errors.CommandError:
                raise cf_common.FindMemberFailedError(member_identifier)
            account_id = cf_common.user_db.get_account_id(member.id, ctx.guild.id, resource=resource)
            if account_id is None:
                raise cf_common.HandleNotRegisteredError(member, resource=resource)
            else:
                account_ids.add(account_id)
        else:
            account_id = cf_common.user_db.get_account_id_from_handle(handle=handle, resource=resource)
            if account_id:
                account_ids.add(account_id)
            else:
                unresolved_handles.add(handle)
        if handle in cf_common.HandleIsVjudgeError.HANDLES:
            raise cf_common.HandleIsVjudgeError(handle)
    if len(unresolved_handles)!=0:
        clist_users = await clist.fetch_user_info(resource=resource, handles=list(unresolved_handles))
        if clist_users!=None:
            for user in clist_users:
                account_ids.add(int(user['id']))
    return list(account_ids)

async def resolve_contest(contest_id, resource):
    contest = None
    if resource==None:
        contest = await clist.contest(contest_id)
    elif resource==Resources.ATCODER:
        prefix = contest_id[:3]
        if prefix=='abc':
            prefix = 'AtCoder Beginner Contest '
        if prefix=='arc':
            prefix = 'AtCoder Regular Contest '
        if prefix=='agc':
            prefix = 'AtCoder Grand Contest '
        suffix = contest_id[3:]
        try:
            suffix = int(suffix)
        except:
            raise ContestNotFoundError('Invalid contest_id provided.') 
        contest_name = prefix+str(suffix)
        contests = await clist.search_contest(regex=contest_name, resource=resource)
        if contests==None or len(contests)==0:
            raise ContestNotFoundError('Contest not found.')
        contest = contests[0] 
    elif resource==Resources.CODECHEF:
        contest_name = None
        if 'lunchtime' in contest_id:
            date = parse_date(contest_id[9:])
            contest_name = str(date.strftime('%B'))+' Lunchtime '+str(date.strftime('%Y'))
        elif 'cookoff' in contest_id:
            date = parse_date(contest_id[7:])
            contest_name = str(date.strftime('%B'))+' Cook-Off '+str(date.strftime('%Y'))
        elif 'long' in contest_id:
            date = parse_date(contest_id[4:])
            contest_name = str(date.strftime('%B'))+' Challenge '+str(date.strftime('%Y'))
        elif 'starters' in contest_id:
            date = parse_date(contest_id[8:])
            contest_name = str(date.strftime('%B'))+' CodeChef Starters '+str(date.strftime('%Y'))
        contests = await clist.search_contest(regex=contest_name, resource=resource)
        if contests==None or len(contests)==0:
            raise ContestNotFoundError('Contest not found.')
        contest = contests[0] 
    elif resource==Resources.GOOGLE:
        year,round = None,None
        contest_name = None
        if 'kickstart' in contest_id:
            year = contest_id[9:11]
            round = contest_id[11:]
            contest_name = 'Kick Start.*Round '+round
        elif 'codejam' in contest_id:
            year = contest_id[7:9]
            round = contest_id[9:]
            if round=='WF':
                round = 'Finals'
                contest_name = 'Code Jam.*Finals'
            elif round=='QR':
                round = 'Qualification Round'
                contest_name = 'Code Jam.*Qualification Round'
            else:
                contest_name = 'Code Jam.*Round '+round
        if not round:
                raise ContestNotFoundError('Invalid contest_id provided.') 
        try:
            year = int(year)
        except:
            raise ContestNotFoundError('Invalid contest_id provided.') 
        start = dt.datetime(int('20'+str(year)), 1, 1)
        end = dt.datetime(int('20'+str(year+1)), 1, 1)
        date_limit = (start.strftime('%Y-%m-%dT%H:%M:%S'), end.strftime('%Y-%m-%dT%H:%M:%S'))
        contests = await clist.search_contest(regex=contest_name, resource=resource, date_limits=date_limit)
        if contests==None or len(contests)==0:
            raise ContestNotFoundError('Contest not found.')
        contest = contests[0]
    return contest

def is_int(id):
    try:
        id = int(id)
        return True
    except:
        return False

def resource_from_contest_id(contest_id):
    if is_int(contest_id):
        contest_id = int(contest_id)
        if contest_id<0:
            contest_id = -1*contest_id
            return None
        else:
            return Resources.CODEFORCES
    resource = None
    for pattern in _RANKLIST_PATTERNS:
        if pattern in contest_id:
            resource = _RANKLIST_PATTERNS[pattern]
            break
    if resource==None:
        raise InvalidContestID("Invalid Contest Id")
    return resource

async def get_contest(contest_id):
    resource = resource_from_contest_id(contest_id)
    if resource in [Resources.CODEFORCES, None]:
        try:
            contest_id = abs(int(contest_id))
        except:
            raise InvalidContestID("Invalide Contest Id")
    if resource==Resources.CODEFORCES:
        # Getting Contest from CodeForces
        return cf_common.cache2.contest_cache.get_contest(contest_id)
    # Getting contest from Clist API
    return await resolve_contest(contest_id, resource)

async def get_ranklist(contest, handles = None):
    ranklist = None
    if contest.resource==Resources.CODEFORCES:
        if contest.type=='CLIST':
            raise ContestNotFoundError('Please use codeforces contest id')
        # Getting ranklist from CodeForces
        try:
            ranklist = cf_common.cache2.ranklist_cache.get_ranklist(contest)
        except cf_common.cache_system2.RanklistNotMonitored:
            if contest.phase == 'BEFORE':
                raise RanklistNotFound(f'Contest `{contest.id} | {contest.name}` has not started')
            ranklist = await cf_common.cache2.ranklist_cache.generate_ranklist(contest.id, fetch_changes=True)
        return ranklist
    # Getting ranklist from Clist API
    statistics = await clist.statistics(contest_id=contest.id, account_ids=handles, with_problems=True)
    rated = False
    deltas = {}
    indexes = set()
    for statistic in statistics:
        if not statistic['place'] or not statistic['handle']:
            continue
        if statistic['new_rating']:
            deltas[statistic['handle']] = statistic['rating_change']
            rated = True
        if 'problems' in statistic:
            indexes.update(statistic['problems'].keys())
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    index_map = {}
    indexes = sorted(list(indexes))
    for i, id in enumerate(indexes):
        index_map[letters[i]] = id
        indexes[i] = letters[i]
    standings = clist.format_standings(statistics, index_map, indexes)
    ranklist = CRanklist(contest, standings, deltas=deltas if rated else None, problems_indexes=indexes)
    return ranklist

def resource_from_handle_notation(handle):
    resource = Resources.CODEFORCES
    if ':' in handle:
        index = handle.index(':')
        resource = handle[0: index]
        handle = handle[index+1:]
    if resource=='all':
        resource = None
    if resource in _RESOURCE_SHORT_FORMS:
        resource = _RESOURCE_SHORT_FORMS[resource]
    if resource not in _SUPPORTED_RESOURCES:
        raise InvalidResource(f'The resource `{resource}` is not supported!')
    return resource, handle
    
def detect_loose_resource(values):
    resource = Resources.CODEFORCES
    for value in values:
        if value in _SUPPORTED_RESOURCES:
            resource = value
            break
        elif value in _RESOURCE_SHORT_FORMS:
            resource = _RESOURCE_SHORT_FORMS[value]
            break
    return resource