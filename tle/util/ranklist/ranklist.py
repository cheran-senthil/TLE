from discord.ext import commands

from tle.util.ranklist.rating_calculator import CodeforcesRatingCalculator
from tle.util.handledict import HandleDict


class RanklistError(commands.CommandError):
    def __init__(self, contest, message=None):
        if message is not None:
            super().__init__(message)
        self.contest = contest


class ContestNotRatedError(RanklistError):
    def __init__(self, contest):
        super().__init__(contest, f'`{contest.name}` is not rated')


class HandleNotPresentError(RanklistError):
    def __init__(self, contest, handle):
        super().__init__(contest, f'Handle `{handle}`` not present in standings of `{contest.name}`')
        self.handle = handle


class DeltasNotPresentError(RanklistError):
    def __init__(self, contest):
        super().__init__(contest, f'Rating changes for `{contest.name}` not calculated or set.')


class Ranklist:
    def __init__(self, contest, problems, standings, fetch_time, *, is_rated):
        self.contest = contest
        self.problems = problems
        self.standings = standings
        self.fetch_time = fetch_time

        self.is_rated = is_rated

        self.standing_by_id = HandleDict()
        for row in self.standings:
            if row.party.ghost:
                # Apparently ghosts don't have team ID.
                id_ = row.party.teamName
            else:
                id_ = row.party.teamId or row.party.members[0].handle
            self.standing_by_id[id_] = row

        self.delta_by_handle = None
        self.deltas_status = None

    def set_deltas(self, delta_by_handle):
        if not self.is_rated:
            raise ContestNotRatedError(self.contest)
        self.delta_by_handle = delta_by_handle.copy()
        self.deltas_status = 'Final'

    def predict(self, current_rating):
        if not self.is_rated:
            raise ContestNotRatedError(self.contest)
        standings = [(id_, row.points, row.penalty, current_rating[id_])
                     for id_, row in self.standing_by_id.items() if id_ in current_rating]
        if standings:
            self.delta_by_handle = CodeforcesRatingCalculator(standings).calculate_rating_changes()
        self.deltas_status = 'Predicted'

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
