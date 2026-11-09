"""Tests for tle.cogs.hints — argument parsing and formatting."""

import pytest

from tle.cogs.hints import (
    HintsCogError,
    format_hint,
    hint_embed,
    parse_args,
    parse_problem,
)


def _hints_response(levels=3):
    return {
        'problem': {
            'id': '1850_A',
            'contestId': 1850,
            'index': 'A',
            'name': 'To My Critics',
            'rating': 800,
            'tags': ['implementation', 'sortings'],
        },
        'duplicateOf': None,
        'hints': [
            {'level': level, 'content': f'Hint text {level}'}
            for level in range(1, levels + 1)
        ],
        'groundedInTutorial': True,
        'generatedAt': '2026-10-31T15:18:37Z',
    }


class TestParseProblem:
    @pytest.mark.parametrize(
        'text, expected',
        [
            ('1850A', (1850, 'A')),
            ('1850a', (1850, 'A')),
            ('1850 A', (1850, 'A')),
            ('1850/A', (1850, 'A')),
            ('2284C1', (2284, 'C1')),
            ('https://codeforces.com/problemset/problem/1850/A', (1850, 'A')),
            ('https://codeforces.com/contest/2284/problem/C1', (2284, 'C1')),
            ('codeforces.com/contest/1342/problem/D?locale=en', (1342, 'D')),
        ],
    )
    def test_accepted_forms(self, text, expected):
        assert parse_problem(text) == expected

    @pytest.mark.parametrize(
        'text',
        ['', 'hello', '1850', 'A1850', 'https://codeforces.com/gym/104114/problem/A'],
    )
    def test_rejects_other_text(self, text):
        with pytest.raises(HintsCogError):
            parse_problem(text)


class TestParseArgs:
    def test_defaults_to_first_hint(self):
        assert parse_args(('1850A',)) == (1850, 'A', 1)

    def test_last_number_is_hint_level(self):
        assert parse_args(('1850A', '3')) == (1850, 'A', 3)

    def test_split_problem_with_level(self):
        assert parse_args(('1850', 'A', '2')) == (1850, 'A', 2)

    def test_no_arguments(self):
        with pytest.raises(HintsCogError):
            parse_args(())

    def test_level_zero(self):
        with pytest.raises(HintsCogError):
            parse_args(('1850A', '0'))


class TestFormatHint:
    def test_math_becomes_inline_code(self):
        text = format_hint('Sort $a_i$ in $O(n \\log n)$.')
        assert text == 'Sort `a_i` in `O(n \\log n)`.'

    def test_display_math(self):
        assert format_hint('So $$x = 2$$ works') == 'So `x = 2` works'

    def test_plain_text_unchanged(self):
        assert format_hint('Think about parity.') == 'Think about parity.'

    def test_long_hint_is_cut_with_balanced_code(self):
        text = format_hint('word ' * 600 + '$a_i$ ' * 400)
        assert len(text) < 4000
        assert text.endswith('…')
        assert text.count('`') % 2 == 0


class TestHintEmbed:
    def test_first_hint(self):
        embed = hint_embed(_hints_response(3), 1850, 'A', 1)
        assert embed.title == '1850A - To My Critics'
        assert embed.url == 'https://codeforces.com/problemset/problem/1850/A'
        assert embed.description == '**Hint 1 of 3**\n||Hint text 1||'
        assert 'can be wrong' in embed.footer.text
        assert 'Next: ;hint 1850A 2' in embed.footer.text

    def test_last_hint_is_full_solution(self):
        embed = hint_embed(_hints_response(3), 1850, 'A', 3)
        assert embed.description.startswith('**Full solution (hint 3 of 3)**')
        assert '||Hint text 3||' in embed.description
        assert 'Next' not in embed.footer.text

    def test_hints_are_ordered_by_level(self):
        data = _hints_response(2)
        data['hints'].reverse()
        embed = hint_embed(data, 1850, 'A', 1)
        assert '||Hint text 1||' in embed.description
