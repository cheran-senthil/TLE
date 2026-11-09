"""Integration tests for tle.cogs.hints — the ;hint command."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from tle.cogs.hints import Hints, HintsCogError

pytestmark = pytest.mark.integration


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


def _session(status, payload=None):
    """A stand-in for aiohttp.ClientSession whose GET answers with `status`."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload)
    session = MagicMock()
    session.get.return_value.__aenter__.return_value = resp
    return session


@pytest.fixture
def cog_env():
    cog = Hints(MagicMock())
    ctx = MagicMock()
    ctx.send = AsyncMock()
    return cog, ctx


class TestFetchHints:
    async def test_returns_hints(self, cog_env):
        cog, _ = cog_env
        cog._session = _session(200, _hints_response())
        data = await cog._fetch_hints(1850, 'A')
        assert len(data['hints']) == 3
        url = cog._session.get.call_args.args[0]
        assert url.endswith('/v1/problems/1850/A/hints')
        assert cog._session.get.call_args.kwargs['params'] == {'client': 'tle-bot'}

    async def test_not_found_is_none(self, cog_env):
        cog, _ = cog_env
        cog._session = _session(404)
        assert await cog._fetch_hints(1, 'A') is None

    async def test_answers_are_cached(self, cog_env):
        cog, _ = cog_env
        cog._session = _session(200, _hints_response())
        await cog._fetch_hints(1850, 'A')
        await cog._fetch_hints(1850, 'A')
        assert cog._session.get.call_count == 1

    @pytest.mark.parametrize('status', [429, 500, 503])
    async def test_error_status_raises(self, cog_env, status):
        cog, _ = cog_env
        cog._session = _session(status)
        with pytest.raises(HintsCogError):
            await cog._fetch_hints(1850, 'A')

    async def test_network_error_raises(self, cog_env):
        cog, _ = cog_env
        cog._session = MagicMock()
        cog._session.get.side_effect = aiohttp.ClientConnectionError('down')
        with pytest.raises(HintsCogError):
            await cog._fetch_hints(1850, 'A')

    async def test_errors_are_not_cached(self, cog_env):
        cog, _ = cog_env
        cog._session = _session(503)
        with pytest.raises(HintsCogError):
            await cog._fetch_hints(1850, 'A')
        cog._session = _session(200, _hints_response())
        assert await cog._fetch_hints(1850, 'A') is not None


class TestHintCommand:
    async def test_sends_requested_hint(self, cog_env):
        cog, ctx = cog_env
        cog._session = _session(200, _hints_response())
        await cog.hint.callback(cog, ctx, '1850A', '2')
        embed = ctx.send.call_args.kwargs['embed']
        assert embed.description == '**Hint 2 of 3**\n||Hint text 2||'

    async def test_no_hints_yet(self, cog_env):
        cog, ctx = cog_env
        cog._session = _session(404)
        with pytest.raises(HintsCogError, match='No hints for 2284C1 yet'):
            await cog.hint.callback(cog, ctx, '2284', 'C1')
        ctx.send.assert_not_called()

    async def test_level_past_last_hint(self, cog_env):
        cog, ctx = cog_env
        cog._session = _session(200, _hints_response(3))
        with pytest.raises(HintsCogError, match='has 3 hints'):
            await cog.hint.callback(cog, ctx, '1850A', '4')
        ctx.send.assert_not_called()
