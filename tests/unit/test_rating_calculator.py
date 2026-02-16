"""Tests for tle.util.ranklist.rating_calculator — only imports numpy."""

from tle.util.ranklist.rating_calculator import (
    CodeforcesRatingCalculator,
    Contestant,
    intdiv,
)


class TestIntdiv:
    def test_positive(self):
        assert intdiv(7, 2) == 3

    def test_exact(self):
        assert intdiv(6, 3) == 2

    def test_negative_rounds_toward_zero(self):
        assert intdiv(-7, 2) == -3

    def test_zero(self):
        assert intdiv(0, 5) == 0

    def test_negative_exact(self):
        assert intdiv(-6, 3) == -2


class TestContestant:
    def test_creation(self):
        c = Contestant(party='tourist', points=100, penalty=0, rating=3000)
        assert c.party == 'tourist'
        assert c.points == 100
        assert c.rating == 3000

    def test_defaults(self):
        c = Contestant(party='tourist', points=100, penalty=0, rating=3000)
        assert c.need_rating == 0
        assert c.delta == 0
        assert c.rank == 0.0
        assert c.seed == 0.0

    def test_mutability(self):
        c = Contestant(party='tourist', points=100, penalty=0, rating=3000)
        c.delta = 50
        assert c.delta == 50


class TestCodeforcesRatingCalculator:
    def test_two_person(self):
        standings = [
            ('alice', 100, 0, 1500),
            ('bob', 50, 0, 1500),
        ]
        calc = CodeforcesRatingCalculator(standings)
        changes = calc.calculate_rating_changes()
        assert changes['alice'] > changes['bob']

    def test_bounded_deltas(self):
        standings = [(f'user{i}', 100 - i, i, 1500) for i in range(20)]
        calc = CodeforcesRatingCalculator(standings)
        changes = calc.calculate_rating_changes()
        for delta in changes.values():
            assert -1000 < delta < 1000

    def test_ties(self):
        standings = [
            ('alice', 100, 0, 1500),
            ('bob', 100, 0, 1500),
        ]
        calc = CodeforcesRatingCalculator(standings)
        changes = calc.calculate_rating_changes()
        assert changes['alice'] == changes['bob']

    def test_higher_rated_loser_effect(self):
        standings = [
            ('low_rated', 100, 0, 1200),
            ('high_rated', 50, 0, 2500),
        ]
        calc = CodeforcesRatingCalculator(standings)
        changes = calc.calculate_rating_changes()
        # Winner (low_rated) should gain, loser (high_rated) should lose
        assert changes['low_rated'] > changes['high_rated']

    def test_get_seed(self):
        standings = [
            ('alice', 100, 0, 1500),
            ('bob', 50, 0, 1500),
        ]
        calc = CodeforcesRatingCalculator(standings)
        seed = calc.get_seed(1500)
        assert seed > 0

    def test_get_seed_with_exclusion(self):
        standings = [
            ('alice', 100, 0, 1500),
            ('bob', 50, 0, 1500),
        ]
        calc = CodeforcesRatingCalculator(standings)
        contestant = calc.contestants[0]
        seed_with = calc.get_seed(1500, me=contestant)
        seed_without = calc.get_seed(1500)
        assert seed_with < seed_without
