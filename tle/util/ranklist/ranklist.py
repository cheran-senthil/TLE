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


class Ranklist:
    def __init__(self, contest, problems, standings, fetch_time, current_rating=None):
        self.contest = contest
        self.problems = problems
        self.standings = standings
        self.fetch_time = fetch_time

        # current_rating is a mapping from handle to rating for the handles
        # for whom the contest is rated.
        self.is_rated = current_rating is not None

        self.delta_by_handle = {}
        self.standing_by_id = {}
        for row in self.standings:
            id_ = row.party.teamId or row.party.members[0].handle
            self.standing_by_id[id_] = row

        if self.is_rated:
            self._prepare_predictions(current_rating)

    def _prepare_predictions(self, current_rating):
        standings = [(id_, row.points, row.penalty, current_rating[id_])
                     for id_, row in self.standing_by_id.items() if id_ in current_rating]
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
