import asyncio
import datetime
import functools
import itertools
import json
import logging
import math
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

import discord
from discord.ext import commands

from tle import constants
from tle.util import codeforces_api as cf, db, events
from tle.util.cache import CacheSystem, ContestNotFound

logger = logging.getLogger(__name__)

# Connection to database
user_db: Any = None

# Cache system
cf_cache: Any = None

# Event system
event_sys = events.EventSystem()

_contest_id_to_writers_map: dict[int, list[str]] | None = None

active_groups: defaultdict[str, set[int]] = defaultdict(set)


async def initialize(bot: Any, nodb: bool) -> None:
    global cf_cache
    global user_db
    global event_sys
    global _contest_id_to_writers_map

    await cf.initialize()

    if nodb:
        user_db = db.DummyUserDbConn()
    else:
        user_db = db.UserDbConn(str(constants.USER_DB_FILE_PATH))
        await user_db.connect()

    cache_db = db.CacheDbConn(str(constants.CACHE_DB_FILE_PATH))
    await cache_db.connect()
    cf_cache = CacheSystem(cache_db)
    await cf_cache.run()

    # Attach services to bot for cog access via self.bot
    bot.user_db = user_db
    bot.cf_cache = cf_cache
    bot.event_sys = event_sys

    try:
        with open(constants.CONTEST_WRITERS_JSON_FILE_PATH) as f:
            data = json.load(f)
        _contest_id_to_writers_map = {
            contest['id']: [s.lower() for s in contest['writers']] for contest in data
        }
        logger.info('Contest writers loaded from JSON file')
    except FileNotFoundError:
        logger.warning('JSON file containing contest writers not found')


# algmyr's guard idea:
def user_guard(
    *, group: str, get_exception: Callable[[], Exception] | None = None
) -> Callable[..., Any]:
    active = active_groups[group]

    def guard(fun: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fun)
        async def f(
            self: Any, ctx: commands.Context, *args: Any, **kwargs: Any
        ) -> None:
            user = ctx.message.author.id
            if user in active:
                logger.info(f'{user} repeatedly calls {group} group')
                if get_exception is not None:
                    raise get_exception()
                return
            active.add(user)
            try:
                await fun(self, ctx, *args, **kwargs)
            finally:
                active.remove(user)

        return f

    return guard


def is_contest_writer(contest_id: int, handle: str) -> bool:
    if _contest_id_to_writers_map is None:
        return False
    writers = _contest_id_to_writers_map.get(contest_id)
    return bool(writers and handle.lower() in writers)


_NONSTANDARD_CONTEST_INDICATORS = [
    'wild',
    'fools',
    'unrated',
    'surprise',
    'unknown',
    'friday',
    'q#',
    'testing',
    'marathon',
    'kotlin',
    'onsite',
    'experimental',
    'abbyy',
    'icpc',
]


def is_nonstandard_contest(contest: cf.Contest) -> bool:
    return any(
        string in contest.name.lower() for string in _NONSTANDARD_CONTEST_INDICATORS
    )


def is_nonstandard_problem(problem: cf.Problem) -> bool:
    return is_nonstandard_contest(
        cf_cache.contest_cache.get_contest(problem.contestId)
    ) or problem.matches_all_tags(['*special'])


async def get_visited_contests(handles: list[str]) -> set[int]:
    """Returns a set of contest ids of contests that any of the given handles
    has at least one non-CE submission.
    """
    user_submissions = await asyncio.gather(
        *(cf.user.status(handle=handle) for handle in handles)
    )
    problem_to_contests = cf_cache.problemset_cache.problem_to_contests

    contest_ids = []
    for sub in itertools.chain.from_iterable(user_submissions):
        if sub.verdict == 'COMPILATION_ERROR':
            continue
        try:
            contest = cf_cache.contest_cache.get_contest(sub.problem.contestId)
            problem_id = (sub.problem.name, contest.startTimeSeconds)
            contest_ids += problem_to_contests[problem_id]
        except ContestNotFound:
            pass
    return set(contest_ids)


# These are special rated-for-all contests which have a combined ranklist for
# onsite and online participants. The onsite participants have their
# submissions marked as out of competition. Just Codeforces things.
_RATED_FOR_ONSITE_CONTEST_IDS = [
    86,  # Yandex.Algorithm 2011 Round 2 https://codeforces.com/contest/86
    173,  # Croc Champ 2012 - Round 1 https://codeforces.com/contest/173
    335,  # MemSQL start[c]up Round 2 - online version https://codeforces.com/contest/335
]


def is_rated_for_onsite_contest(contest: cf.Contest) -> bool:
    return contest.id in _RATED_FOR_ONSITE_CONTEST_IDS


class ResolveHandleError(commands.CommandError):
    pass


class HandleCountOutOfBoundsError(ResolveHandleError):
    def __init__(self, mincnt: int, maxcnt: int) -> None:
        super().__init__(f'Number of handles must be between {mincnt} and {maxcnt}')


class FindMemberFailedError(ResolveHandleError):
    def __init__(self, member: str) -> None:
        super().__init__(f'Unable to convert `{member}` to a server member')


class HandleNotRegisteredError(ResolveHandleError):
    def __init__(self, member: discord.Member) -> None:
        super().__init__(
            f'Codeforces handle for {member.mention} not found in database'
        )


class HandleIsVjudgeError(ResolveHandleError):
    HANDLES = """
        vjudge1 vjudge2 vjudge3 vjudge4 vjudge5
        luogu_bot1 luogu_bot2 luogu_bot3 luogu_bot4 luogu_bot5
    """.split()

    def __init__(self, handle: str) -> None:
        super().__init__(f"`{handle}`? I'm not doing that!\n\n(╯°□°）╯︵ ┻━┻")


class FilterError(commands.CommandError):
    pass


class ParamParseError(FilterError):
    pass


def time_format(seconds: float) -> tuple[int, int, int, int]:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return days, hours, minutes, seconds


def pretty_time_format(
    seconds: float,
    *,
    shorten: bool = False,
    only_most_significant: bool = False,
    always_seconds: bool = False,
) -> str:
    days, hours, minutes, seconds = time_format(seconds)
    timespec = [
        (days, 'day', 'days'),
        (hours, 'hour', 'hours'),
        (minutes, 'minute', 'minutes'),
    ]
    timeprint = [(cnt, singular, plural) for cnt, singular, plural in timespec if cnt]
    if not timeprint or always_seconds:
        timeprint.append((seconds, 'second', 'seconds'))
    if only_most_significant:
        timeprint = [timeprint[0]]

    def format_(triple: tuple[int, str, str]) -> str:
        cnt, singular, plural = triple
        return (
            f'{cnt}{singular[0]}'
            if shorten
            else f'{cnt} {singular if cnt == 1 else plural}'
        )

    return ' '.join(map(format_, timeprint))


def days_ago(t: float) -> str:
    days = (time.time() - t) / (60 * 60 * 24)
    if days < 1:
        return 'today'
    if days < 2:
        return 'yesterday'
    return f'{math.floor(days)} days ago'


async def resolve_handles(
    ctx: commands.Context,
    converter: Any,
    handles: Iterable[str],
    *,
    mincnt: int = 1,
    maxcnt: int | None = 5,
    default_to_all_server: bool = False,
) -> list[str]:
    """Convert an iterable of strings to CF handles.

    A string beginning with ! indicates Discord username, otherwise it is a raw
    CF handle to be left unchanged.
    """
    handles = set(handles)
    if default_to_all_server and not handles:
        handles.add('+server')
    if '+server' in handles:
        handles.remove('+server')
        guild_handles = {
            handle
            for discord_id, handle in await user_db.get_handles_for_guild(ctx.guild.id)
        }
        handles.update(guild_handles)
    if len(handles) < mincnt or (maxcnt is not None and maxcnt < len(handles)):
        raise HandleCountOutOfBoundsError(mincnt, maxcnt or 0)
    resolved_handles = []
    for handle in handles:
        if handle.startswith('!'):
            # ! denotes Discord user
            member_identifier = handle[1:]
            try:
                member = await converter.convert(ctx, member_identifier)
            except commands.errors.CommandError:
                raise FindMemberFailedError(member_identifier)
            handle = await user_db.get_handle(member.id, ctx.guild.id)
            if handle is None:
                raise HandleNotRegisteredError(member)
        if handle in HandleIsVjudgeError.HANDLES:
            raise HandleIsVjudgeError(handle)
        resolved_handles.append(handle)
    return resolved_handles


async def members_to_handles(
    members: Iterable[discord.Member],
    guild_id: int,
) -> list[str]:
    handles = []
    for member in members:
        handle = await user_db.get_handle(member.id, guild_id)
        if handle is None:
            raise HandleNotRegisteredError(member)
        handles.append(handle)
    return handles


def filter_flags(
    args: Iterable[str], params: list[str]
) -> tuple[list[bool], list[str]]:
    args = list(args)
    flags = [False] * len(params)
    rest = []
    for arg in args:
        try:
            flags[params.index(arg)] = True
        except ValueError:
            rest.append(arg)
    return flags, rest


def negate_flags(*args: bool) -> list[bool]:
    return [not x for x in args]


def parse_date(arg: str) -> float:
    try:
        if len(arg) == 8:
            fmt = '%d%m%Y'
        elif len(arg) == 6:
            fmt = '%m%Y'
        elif len(arg) == 4:
            fmt = '%Y'
        else:
            raise ValueError
        return time.mktime(datetime.datetime.strptime(arg, fmt).timetuple())
    except ValueError:
        raise ParamParseError(f'{arg} is an invalid date argument')


def parse_tags(args: Iterable[str], *, prefix: str) -> list[str]:
    tags = [x[1:] for x in args if x[0] == prefix]
    return tags


def parse_rating(args: Iterable[str], default_value: int | None = None) -> int | None:
    for arg in args:
        if arg.isdigit():
            return int(arg)
    return default_value


# Canonical implementation lives in codeforces_api, next to the User type.
fix_urls = cf.fix_urls


class SubFilter:
    def __init__(self, rated: bool = True) -> None:
        self.team = False
        self.rated = rated
        self.dlo: float = 0
        self.dhi: float = 10**10
        self.rlo, self.rhi = 500, 3800
        self.types: list[str] = []
        self.tags: list[str] = []
        self.bantags: list[str] = []
        self.contests: list[str] = []
        self.indices: list[str] = []

    def parse(self, args: Iterable[str]) -> list[str]:
        args = list(set(args))
        rest = []

        for arg in args:
            if arg == '+team':
                self.team = True
            elif arg == '+contest':
                self.types.append('CONTESTANT')
            elif arg == '+outof':
                self.types.append('OUT_OF_COMPETITION')
            elif arg == '+virtual':
                self.types.append('VIRTUAL')
            elif arg == '+practice':
                self.types.append('PRACTICE')
            elif arg[0:2] == 'c+':
                self.contests.append(arg[2:])
            elif arg[0:2] == 'i+':
                self.indices.append(arg[2:])
            elif arg[0] == '+':
                if len(arg) == 1:
                    raise ParamParseError('Problem tag cannot be empty.')
                self.tags.append(arg[1:])
            elif arg[0] == '~':
                if len(arg) == 1:
                    raise ParamParseError('Problem tag cannot be empty.')
                self.bantags.append(arg[1:])
            elif arg[0:2] == 'd<':
                self.dhi = min(self.dhi, parse_date(arg[2:]))
            elif arg[0:3] == 'd>=':
                self.dlo = max(self.dlo, parse_date(arg[3:]))
            elif arg[0:3] in ['r<=', 'r>=']:
                if len(arg) < 4:
                    raise ParamParseError(f'{arg} is an invalid rating argument')
                elif arg[1] == '>':
                    self.rlo = max(self.rlo, int(arg[3:]))
                else:
                    self.rhi = min(self.rhi, int(arg[3:]))
                self.rated = True
            else:
                rest.append(arg)

        self.types = self.types or [
            'CONTESTANT',
            'OUT_OF_COMPETITION',
            'VIRTUAL',
            'PRACTICE',
        ]
        return rest

    @staticmethod
    def filter_solved(submissions: list[cf.Submission]) -> list[cf.Submission]:
        """Filters and keeps only solved submissions.

        If a problem is solved multiple times the first accepted submission is
        kept. The unique id for a problem is
        (problem name, contest start time).
        """
        submissions.sort(key=lambda sub: sub.creationTimeSeconds)
        problems = set()
        solved_subs = []

        for submission in submissions:
            problem = submission.problem
            contest = cf_cache.contest_cache.contest_by_id.get(problem.contestId, None)
            if submission.verdict == 'OK':
                # Assume (name, contest start time) is a unique identifier for problems
                problem_key = (problem.name, contest.startTimeSeconds if contest else 0)
                if problem_key not in problems:
                    solved_subs.append(submission)
                    problems.add(problem_key)
        return solved_subs

    def filter_subs(self, submissions: list[cf.Submission]) -> list[cf.Submission]:
        submissions = SubFilter.filter_solved(submissions)
        filtered_subs = []
        for submission in submissions:
            problem = submission.problem
            contest = cf_cache.contest_cache.contest_by_id.get(problem.contestId, None)
            type_ok = submission.author.participantType in self.types
            date_ok = self.dlo <= submission.creationTimeSeconds < self.dhi
            tag_ok = problem.matches_all_tags(self.tags)
            bantag_ok = not problem.matches_any_tag(self.bantags)
            index_ok = not self.indices or any(
                index.lower() == problem.index.lower() for index in self.indices
            )
            contest_ok = not self.contests or (
                contest and contest.matches(self.contests)
            )
            team_ok = self.team or len(submission.author.members) == 1
            if self.rated:
                problem_ok = (
                    contest
                    and contest.id < cf.GYM_ID_THRESHOLD
                    and not is_nonstandard_problem(problem)
                )
                rating_ok = problem.rating and self.rlo <= problem.rating <= self.rhi
            else:
                # acmsguru and gym allowed
                problem_ok = (
                    not contest
                    or contest.id >= cf.GYM_ID_THRESHOLD
                    or not is_nonstandard_problem(problem)
                )
                rating_ok = True
            if (
                type_ok
                and date_ok
                and rating_ok
                and tag_ok
                and bantag_ok
                and team_ok
                and problem_ok
                and contest_ok
                and index_ok
            ):
                filtered_subs.append(submission)
        return filtered_subs

    def filter_rating_changes(
        self, rating_changes: list[cf.RatingChange]
    ) -> list[cf.RatingChange]:
        rating_changes = [
            change
            for change in rating_changes
            if self.dlo <= change.ratingUpdateTimeSeconds < self.dhi
        ]
        return rating_changes
