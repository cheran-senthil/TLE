import datetime as dt

from discord.ext import commands


class FilterError(commands.CommandError):
    pass


class ParamParseError(FilterError):
    pass


class TypeFilter:
    def __init__(self, types):
        self.types = types or ['CONTESTANT', 'OUT_OF_COMPETITION', 'VIRTUAL', 'PRACTICE']

    @classmethod
    def parse_from(cls, args):
        types = set()
        leftovers = []
        for arg in args:
            if arg == '+contest':
                types.add('CONTESTANT')
            elif arg == '+outof':
                types.add('OUT_OF_COMPETITION')
            elif arg == '+practice':
                types.add('PRACTICE')
            elif arg == '+virtual':
                types.add('VIRTUAL')
            else:
                leftovers.append(arg)
        return cls(types), leftovers

    def __call__(self, submission):
        return submission.author.participantType in self.types


class TeamFilter:
    def __init__(self, *, solo_ok=True, team_ok):
        self.solo_ok = solo_ok
        self.team_ok = team_ok

    @classmethod
    def parse_from(cls, args):
        team_ok = False
        leftovers = []
        for arg in args:
            if arg == '+team':
                team_ok = True
            else:
                leftovers.append(arg)
        return cls(team_ok=team_ok), leftovers

    def __call__(self, submission):
        is_solo = len(submission.author.members) == 1
        return self.solo_ok if is_solo else self.team_ok


class RatingFilter:
    def __init__(self, *, low=None, high=None, missing_ok=False):
        if low is not None and high is not None and high < low:
            raise FilterError(f'Invalid rating range [{low}..{high}].')
        self.low = low if low is not None else 0
        self.high = high if high is not None else 5000
        self.missing_ok = missing_ok

    @classmethod
    def parse_from(cls, args):
        low = high = None
        leftovers = []
        for arg in args:
            if arg.startswith('r>='):
                if len(arg) == 3:
                    raise ParamParseError('Missing rating value in `r>=`.')
                low = int(arg[3:])
            elif arg.startswith('r<='):
                if len(arg) == 3:
                    raise ParamParseError('Missing rating value in `r<=`.')
                high = int(arg[3:])
            else:
                leftovers.append(arg)
        return cls(low=low, high=high, missing_ok=low is None and high is None), leftovers

    def __call__(self, submission):
        problem = submission.problem
        if problem.rating is None:
            return self.missing_ok
        return self.low <= problem.rating <= self.high


class TimeFilter:
    def __init__(self, *, low=None, high=None):
        self.low = low if low is not None else 0
        self.high = high if high is not None else 10 ** 10

    @staticmethod
    def _parse_date(arg):
        try:
            if len(arg) == 8:
                fmt = '%d%m%Y'
            elif len(arg) == 6:
                fmt = '%m%Y'
            elif len(arg) == 4:
                fmt = '%Y'
            else:
                raise ValueError
            return dt.datetime.strptime(arg, fmt).timestamp()
        except ValueError:
            raise ParamParseError(f'`{arg}` is an invalid date argument.')

    @classmethod
    def parse_from(cls, args):
        low = high = None
        leftovers = []
        for arg in args:
            if arg.startswith('t>='):
                low = cls._parse_date(arg[3:])
            elif arg.startswith('t<'):
                high = cls._parse_date(arg[2:])
            else:
                leftovers.append(arg)
        return cls(low=low, high=high), leftovers

    def __call__(self, submission):
        return self.low <= submission.creationTimeSeconds < self.high


class TagFilter:
    def __init__(self, tags):
        self.tags = tags

    @classmethod
    def parse_from(cls, args):
        tags = set()
        leftovers = []
        for arg in args:
            if arg.startswith('+'):
                tags.add(arg[1:])
            else:
                leftovers.append(arg)
        return cls(tags), leftovers

    def __call__(self, submission):
        return not self.tags or submission.problem.tag_matches(self.tags)


class ProblemRatedFilter:
    def __call__(self, submission):
        return submission.problem.rating is not None


def filter_solved_submissions(submissions, contests, *, strict=True):
    """Filters and keeps only solved submissions. If a problem is solved multiple times the first
    accepted submission is kept. The unique ID for a problem is (problem name, contest start time)
    where the contest start time is obtained from the given list of contests. If strict is true,
    problems with contest ids not present in given contests will be rejected, else they will be kept
    with their name as unique ID. Returned submissions are in increasing order of time.
    """
    submissions.sort(key=lambda sub: sub.creationTimeSeconds)
    contest_id_map = {contest.id: contest for contest in contests}
    problems = set()
    solved_subs = []

    for submission in submissions:
        problem = submission.problem
        contest = contest_id_map.get(problem.contestId)
        if submission.verdict == 'OK' and (contest or not strict):
            # Assume (name, contest start time) is a unique identifier for problems
            problem_key = (problem.name, contest.startTimeSeconds if contest else None)
            if problem_key not in problems:
                solved_subs.append(submission)
                problems.add(problem_key)
    return solved_subs


def parse_all_from(args, *filter_types):
    predicates = []
    for cls in filter_types:
        predicate, args = cls.parse_from(args)
        predicates.append(predicate)
    return predicates, args


def filter(objs, *predicates):
    return [obj for obj in objs if all(predicate(obj) for predicate in predicates)]
