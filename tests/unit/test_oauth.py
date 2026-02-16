"""Tests for tle.util.oauth module."""

import time
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from tle.util.oauth import (
    OAuthStateStore,
    build_auth_url,
    decode_id_token,
    exchange_code,
)


class TestOAuthStateStore:
    def test_create_returns_unique_states(self):
        store = OAuthStateStore()
        s1 = store.create(1, 100, 200)
        s2 = store.create(2, 100, 200)
        assert s1 != s2

    def test_consume_returns_pending_and_removes(self):
        store = OAuthStateStore()
        state = store.create(1, 100, 200)
        pending = store.consume(state)
        assert pending is not None
        assert pending.user_id == 1
        assert pending.guild_id == 100
        assert pending.channel_id == 200
        # Second consume returns None (single-use)
        assert store.consume(state) is None

    def test_consume_invalid_state_returns_none(self):
        store = OAuthStateStore()
        assert store.consume('nonexistent') is None

    def test_expired_state_returns_none(self):
        store = OAuthStateStore()
        state = store.create(1, 100, 200)
        # Manually expire the entry
        store._pending[state].created_at = time.monotonic() - 600
        assert store.consume(state) is None

    def test_has_pending(self):
        store = OAuthStateStore()
        assert not store.has_pending(1)
        store.create(1, 100, 200)
        assert store.has_pending(1)
        assert not store.has_pending(2)

    def test_has_pending_false_after_consume(self):
        store = OAuthStateStore()
        state = store.create(1, 100, 200)
        store.consume(state)
        assert not store.has_pending(1)

    def test_revoke_invalidates_old_state(self):
        store = OAuthStateStore()
        old_state = store.create(1, 100, 200)
        store.revoke(1)
        assert store.consume(old_state) is None
        assert not store.has_pending(1)

    def test_revoke_does_not_affect_other_users(self):
        store = OAuthStateStore()
        store.create(1, 100, 200)
        state2 = store.create(2, 100, 200)
        store.revoke(1)
        assert not store.has_pending(1)
        assert store.consume(state2) is not None

    def test_prune_removes_expired(self):
        store = OAuthStateStore()
        state = store.create(1, 100, 200)
        store._pending[state].created_at = time.monotonic() - 600
        # Creating another entry triggers prune
        store.create(2, 100, 200)
        assert state not in store._pending


class TestBuildAuthUrl:
    def test_contains_required_params(self):
        url = build_auth_url('my_client', 'https://example.com/callback', 'abc123')
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert params['response_type'] == ['code']
        assert params['client_id'] == ['my_client']
        assert params['redirect_uri'] == ['https://example.com/callback']
        assert params['scope'] == ['openid']
        assert params['state'] == ['abc123']

    def test_base_url(self):
        url = build_auth_url('id', 'https://example.com/cb', 'state')
        assert url.startswith('https://codeforces.com/oauth/authorize?')


class TestDecodeIdToken:
    def _make_token(self, claims, secret='my_secret'):
        return jwt.encode(claims, secret, algorithm='HS256')

    def test_valid_token(self):
        token = self._make_token(
            {
                'sub': '12345',
                'iss': 'https://codeforces.com',
                'aud': 'my_client',
                'exp': time.time() + 300,
                'iat': time.time(),
                'handle': 'tourist',
            }
        )
        claims = decode_id_token(token, 'my_secret', 'my_client')
        assert claims['handle'] == 'tourist'
        assert claims['iss'] == 'https://codeforces.com'

    def test_expired_token_rejected(self):
        token = self._make_token(
            {
                'sub': '12345',
                'iss': 'https://codeforces.com',
                'aud': 'my_client',
                'exp': time.time() - 300,
                'iat': time.time() - 600,
                'handle': 'tourist',
            }
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_id_token(token, 'my_secret', 'my_client')

    def test_wrong_audience_rejected(self):
        token = self._make_token(
            {
                'sub': '12345',
                'iss': 'https://codeforces.com',
                'aud': 'wrong_client',
                'exp': time.time() + 300,
                'iat': time.time(),
                'handle': 'tourist',
            }
        )
        with pytest.raises(jwt.InvalidAudienceError):
            decode_id_token(token, 'my_secret', 'my_client')

    def test_wrong_issuer_rejected(self):
        token = self._make_token(
            {
                'sub': '12345',
                'iss': 'https://evil.com',
                'aud': 'my_client',
                'exp': time.time() + 300,
                'iat': time.time(),
                'handle': 'tourist',
            }
        )
        with pytest.raises(jwt.InvalidIssuerError):
            decode_id_token(token, 'my_secret', 'my_client')


class TestExchangeCode:
    @pytest.mark.asyncio
    async def test_successful_exchange(self):
        expected = {'id_token': 'abc', 'access_token': 'xyz'}
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=expected)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=mock_resp)

        result = await exchange_code('code123', 'cid', 'csecret', 'https://cb', session)
        assert result == expected
        session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_response_raises(self):
        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.json = AsyncMock(return_value={'error': 'invalid_grant'})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=mock_resp)

        with pytest.raises(ValueError, match='Token exchange failed'):
            await exchange_code('bad', 'cid', 'csecret', 'https://cb', session)
