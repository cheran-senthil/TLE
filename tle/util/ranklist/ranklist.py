from tle.util.clist_api import contest
from tle.util.codeforces_api import Rank
from discord.ext import commands

from abc import ABC, abstractmethod

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

class BaseRanklist(ABC):
    def __init__(self, contest, standings, is_rated=False):
        self.contest = contest
        self.standings = standings
        self.is_rated = is_rated
 
    @property
    def deltas_status(self):
        return self._deltas_status

    @deltas_status.setter
    def deltas_status(self, value):
        self._deltas_status = value

    @abstractmethod
    def get_handle_standings(self, handles, vc):
        pass

    @abstractmethod
    def get_problem_indexes(self):
        pass

    @abstractmethod
    def get_delta(self, handle):
        pass
    

class Ranklist(BaseRanklist):
    def __init__(self, contest, problems, standings, fetch_time, *, is_rated):
        super().__init__(contest, standings, is_rated)
        self.problems = problems
        self.fetch_time = fetch_time
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

    # overriding abstract method
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
    
    # overriding abstract method
    def get_handle_standings(self, handles, vc=False):
        handle_standings = []
        for handle in handles:
            try:
                standing = self.get_standing_row(handle)
            except HandleNotPresentError:
                continue

            # Database has correct handle ignoring case, update to it
            # TODO: It will throw an exception if this row corresponds to a team. At present ranklist doesnt show teams.
            # It should be fixed in https://github.com/cheran-senthil/TLE/issues/72
            handle = standing.party.members[0].handle
            if vc and standing.party.participantType != 'VIRTUAL':
                continue
            handle_standings.append((handle, standing))
        return handle_standings
    
    # overriding abstract method
    def get_problem_indexes(self):
        return [problem.index for problem in self.problems]

class CRanklist(BaseRanklist):
    def __init__(self, contest, standings, *, deltas=None, problems_indexes=None):
        super().__init__(contest, standings, deltas!=None)
        self._indexes =problems_indexes
        self.deltas = deltas
        self.deltas_status = 'Final' if deltas else None

    # overriding abstract method
    def get_handle_standings(self, handles, vc):
        # We won't filter by handles list because CLIST has already filtered the result
        # So we return all the standings
        handle_standings = []
        for standing in self.standings:
            handle = standing.party.members[0].handle
            handle_standings.append((handle, standing))
        return handle_standings

    # overriding abstract method
    def get_problem_indexes(self):
        return self._indexes
    
    # overriding abstract method
    def get_delta(self, handle):
        if not self.is_rated:
            raise ContestNotRatedError(self.contest)
        return self.deltas[handle]
