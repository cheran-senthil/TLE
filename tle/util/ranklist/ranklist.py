from discord.ext import commands

from tle.util.ranklist.rating_calculator import CodeforcesRatingCalculator


class RanklistError(commands.CommandError):
    pass


class ContestNotRatedError(RanklistError):
    def __init__(self, contest):
        super().__init__(f'`{contest.name}` is not rated')
        self.contest = contest


class HandleNotPresentError(RanklistError):
    def __init__(self, contest, handle):
        super().__init__(f'Handle `{handle}`` not present in standings of `{contest.name}`')
        self.contest = contest
        self.handle = handle


_DEFAULT_RATED_RANGE = range(-10000, 10000)


class Ranklist:
    def __init__(self, contest, problems, standings, fetch_time, get_current_rating, *,
                 is_rated, rated_range=None):
        self.contest = contest
        self.type = contest.type
        self.problems = problems
        self.standings = standings
        self.fetch_time = fetch_time

        self.is_rated = is_rated
        self.rated_range = rated_range
        if is_rated:
            # Cannot have teams
            assert not any(row.party.teamId for row in standings)
            if rated_range is None:
                self.rated_range = _DEFAULT_RATED_RANGE
            else:
                # Rated range cannot be empty
                assert rated_range
        else:
            assert self.rated_range is None

        self.delta_by_handle = {}
        self.standing_by_id = {}
        for row in self.standings:
            id_ = row.party.teamId or row.party.members[0].handle
            self.standing_by_id[id_] = row

        self._prepare_predictions(get_current_rating)

    def _prepare_predictions(self, get_current_rating):
        if not self.is_rated:
            return
        standings = [(row.party.members[0].handle,
                      row.points,
                      row.penalty,
                      get_current_rating(row.party.members[0].handle))
                     for row in self.standings]
        standings = [(handle, points, penalty, rating) for handle, points, penalty, rating
                     in standings if rating in self.rated_range]
        if standings:
            self.delta_by_handle = CodeforcesRatingCalculator(standings).calculate_rating_changes()

    def get_delta(self, handle):
        if not self.is_rated:
            raise ContestNotRatedError(self.contest)
        if handle not in self.standing_by_id:
            raise HandleNotPresentError(self.contest, handle)
        return self.delta_by_handle.get(handle)

    def get_standing_row(self, handle):
        try:
            return self.standing_by_id[handle]
        except KeyError:
            raise HandleNotPresentError(self.contest, handle)
