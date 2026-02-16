"""Tests for tle.util.handledict — case-insensitive dictionary."""

import pytest

from tle.util.handledict import HandleDict


class TestHandleDict:
    def test_set_get(self):
        d = HandleDict()
        d['Tourist'] = 3000
        assert d['Tourist'] == 3000

    def test_case_insensitive_get(self):
        d = HandleDict()
        d['Tourist'] = 3000
        assert d['tourist'] == 3000
        assert d['TOURIST'] == 3000

    def test_case_insensitive_delete(self):
        d = HandleDict()
        d['Tourist'] = 3000
        del d['TOURIST']
        with pytest.raises(KeyError):
            d['Tourist']

    def test_case_preservation_on_iteration(self):
        d = HandleDict()
        d['Tourist'] = 3000
        d['Petr'] = 2800
        keys = list(d)
        assert 'Tourist' in keys
        assert 'Petr' in keys

    def test_items(self):
        d = HandleDict()
        d['Tourist'] = 3000
        d['Petr'] = 2800
        items = dict(d.items())
        assert items['Tourist'] == 3000
        assert items['Petr'] == 2800

    def test_overwrite_preserves_latest_case(self):
        d = HandleDict()
        d['tourist'] = 3000
        d['TOURIST'] = 3100
        keys = list(d)
        assert 'TOURIST' in keys
        assert d['tourist'] == 3100

    def test_repr(self):
        d = HandleDict()
        d['Tourist'] = 3000
        r = repr(d)
        assert 'Tourist' in r
        assert '3000' in r

    def test_non_string_keys(self):
        d = HandleDict()
        d[42] = 'numeric'
        assert d[42] == 'numeric'
