from typing import Any

from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util.codeforces_api import RanklistRow, make_from_dict
from tle.util.handledict import HandleDict
from tle.util.ranklist.rating_calculator import CodeforcesRatingCalculator


class RanklistError(commands.CommandError):
    def __init__(self, contest: Any, message: str | None = None) -> None:
        if message is not None:
            super().__init__(message)
        self.contest = contest


class ContestNotRatedError(RanklistError):
    def __init__(self, contest: Any) -> None:
        super().__init__(contest, f'`{contest.name}` is not rated')


class HandleNotPresentError(RanklistError):
    def __init__(self, contest: Any, handle: str) -> None:
        super().__init__(
            contest, f'Handle `{handle}`` not present in standings of `{contest.name}`'
        )
        self.handle = handle


class DeltasNotPresentError(RanklistError):
    def __init__(self, contest: Any) -> None:
        super().__init__(
            contest, f'Rating changes for `{contest.name}` not calculated or set.'
        )


class Ranklist:
    def __init__(
        self,
        contest: cf.Contest,
        problems: list[cf.Problem],
        standings: list[cf.RanklistRow],
        fetch_time: float,
        *,
        is_rated: bool,
    ) -> None:
        self.contest = contest
        self.problems = problems
        self.standings = standings
        self.fetch_time = fetch_time
        self.is_rated = is_rated
        self.delta_by_handle: dict[str, int] | None = None
        self.deltas_status: str | None = None
        self.standing_by_id: HandleDict | None = None
        self._create_inverse_standings()

    def _create_inverse_standings(self) -> None:
        self.standing_by_id = HandleDict()
        for row in self.standings:
            id_ = self.get_ranklist_lookup_key(row)
            self.standing_by_id[id_] = row

    def remove_unofficial_contestants(self) -> None:
        """Remove unofficial contestants from the ranklist.

        To be used for cases when official ranklist contains unofficial
        contestants Currently this is seen is Educational Contests ranklist
        where div1 contestants are marked official in api result
        """

        if self.delta_by_handle is None:
            raise DeltasNotPresentError(self.contest)

        official_standings = []
        current_rated_rank = 1
        last_rated_rank = 0
        last_rated_score: tuple[float, int] = (-1, -1)
        for contestant in self.standings:
            handle = self.get_ranklist_lookup_key(contestant)
            if handle in self.delta_by_handle:
                current_score = (contestant.points, contestant.penalty)
                assert self.standing_by_id is not None
                standings_row = self.standing_by_id[handle]._asdict()
                standings_row['rank'] = (
                    current_rated_rank
                    if current_score != last_rated_score
                    else last_rated_rank
                )
                official_standings.append(make_from_dict(RanklistRow, standings_row))
                last_rated_rank = standings_row['rank']
                last_rated_score = current_score
                current_rated_rank += 1

        self.standings = official_standings
        self._create_inverse_standings()

    def set_deltas(self, delta_by_handle: dict[str, int]) -> None:
        if not self.is_rated:
            raise ContestNotRatedError(self.contest)
        self.delta_by_handle = delta_by_handle.copy()
        self.deltas_status = 'Final'

    def predict(self, current_rating: dict[str, int]) -> None:
        if not self.is_rated:
            raise ContestNotRatedError(self.contest)
        assert self.standing_by_id is not None
        standings = [
            (id_, row.points, row.penalty, current_rating[id_])
            for id_, row in self.standing_by_id.items()
            if id_ in current_rating
        ]
        if standings:
            self.delta_by_handle = CodeforcesRatingCalculator(
                standings
            ).calculate_rating_changes()
        self.deltas_status = 'Predicted'

    def get_delta(self, handle: str) -> int | None:
        if not self.is_rated:
            raise ContestNotRatedError(self.contest)
        assert self.standing_by_id is not None
        if handle not in self.standing_by_id:
            raise HandleNotPresentError(self.contest, handle)
        assert self.delta_by_handle is not None
        return self.delta_by_handle.get(handle)

    def get_standing_row(self, handle: str) -> cf.RanklistRow:
        assert self.standing_by_id is not None
        try:
            return self.standing_by_id[handle]  # type: ignore[no-any-return]
        except KeyError:
            raise HandleNotPresentError(self.contest, handle)

    @staticmethod
    def get_ranklist_lookup_key(contestant: cf.RanklistRow) -> str:
        return contestant.party.teamName or contestant.party.members[0].handle
