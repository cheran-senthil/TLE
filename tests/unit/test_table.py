"""Tests for tle.util.table — pure functions, zero external deps."""

from tle.util.table import Content, Data, Header, Line, Style, Table, width


class TestWidth:
    def test_ascii(self):
        assert width('hello') == 5

    def test_empty(self):
        assert width('') == 0

    def test_east_asian_wide(self):
        # CJK characters are full-width: round(2 × 1.66667) = round(3.333) = 3
        assert width('你好') == 3

    def test_mixed(self):
        result = width('hi你')
        # 'h'=1, 'i'=1, '你'=1.66667 → round(3.66667) = 4
        assert result == 4


class TestContent:
    def test_sizes(self):
        c = Content('abc', 'de', 'f')
        assert c.sizes() == [3, 2, 1]

    def test_sizes_numeric(self):
        c = Content(1, 23, 456)
        assert c.sizes() == [1, 2, 3]

    def test_len(self):
        c = Content('a', 'b', 'c', 'd')
        assert len(c) == 4

    def test_len_empty(self):
        c = Content()
        assert len(c) == 0


class TestTable:
    def _make_style(self):
        return Style('{:>}')

    def test_header_and_data(self):
        style = Style('{:<}')
        t = Table(style)
        t + Header('Name')
        t + Data('Alice')
        t + Data('Bob')
        result = str(t)
        assert 'Name' in result
        assert 'Alice' in result
        assert 'Bob' in result

    def test_line_separator(self):
        style = Style('{:<}')
        t = Table(style)
        t + Header('X')
        t + Line()
        t + Data('Y')
        result = str(t)
        assert '-' in result

    def test_multi_column(self):
        style = Style('{:<}')
        t = Table(style)
        t + Header('H')
        t + Data('D')
        result = str(t)
        lines = result.split('\n')
        assert len(lines) == 2

    def test_chaining(self):
        style = Style('{:<}')
        t = Table(style)
        ret = t.append(Header('A'))
        assert ret is t

    def test_two_columns(self):
        style = Style('{:<} {:>}')
        t = Table(style)
        t + Header('Name', 'Score')
        t + Data('Alice', '100')
        t + Data('Bob', '95')
        result = str(t)
        assert 'Alice' in result
        assert '100' in result
