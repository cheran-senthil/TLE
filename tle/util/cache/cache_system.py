from typing import TYPE_CHECKING

from tle.util.cache._common import getUsersEffectiveRating
from tle.util.cache.contest import ContestCache
from tle.util.cache.problem import ProblemCache
from tle.util.cache.problemset import ProblemsetCache
from tle.util.cache.ranklist import RanklistCache
from tle.util.cache.rating_changes import RatingChangesCache

if TYPE_CHECKING:
    from tle.util.db.cache_db_conn import CacheDbConn


class CacheSystem:
    def __init__(self, conn: 'CacheDbConn') -> None:
        self.conn = conn
        self.contest_cache = ContestCache(self)
        self.problem_cache = ProblemCache(self)
        self.rating_changes_cache = RatingChangesCache(self)
        self.ranklist_cache = RanklistCache(self)
        self.problemset_cache = ProblemsetCache(self)

    async def run(self) -> None:
        await self.rating_changes_cache.run()
        await self.ranklist_cache.run()
        await self.contest_cache.run()
        await self.problem_cache.run()
        await self.problemset_cache.run()

    getUsersEffectiveRating = staticmethod(getUsersEffectiveRating)
