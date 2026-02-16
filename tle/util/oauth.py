import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import aiohttp
import jwt
from aiohttp import web

from tle.util import codeforces_api as cf

logger = logging.getLogger(__name__)

_CF_AUTHORIZE_URL = 'https://codeforces.com/oauth/authorize'
_CF_TOKEN_URL = 'https://codeforces.com/oauth/token'
_CF_ISSUER = 'https://codeforces.com'

_STATE_TTL = 5 * 60  # 5 minutes


@dataclass
class OAuthPending:
    user_id: int
    guild_id: int
    channel_id: int
    created_at: float


class OAuthStateStore:
    """In-memory store mapping state tokens to pending OAuth requests."""

    def __init__(self) -> None:
        self._pending: dict[str, OAuthPending] = {}

    def create(self, user_id: int, guild_id: int, channel_id: int) -> str:
        self._prune()
        state = secrets.token_urlsafe(32)
        self._pending[state] = OAuthPending(
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            created_at=time.monotonic(),
        )
        return state

    def consume(self, state: str) -> OAuthPending | None:
        self._prune()
        return self._pending.pop(state, None)

    def has_pending(self, user_id: int) -> bool:
        self._prune()
        return any(p.user_id == user_id for p in self._pending.values())

    def revoke(self, user_id: int) -> None:
        """Remove all pending states for a user, invalidating old links."""
        to_remove = [s for s, p in self._pending.items() if p.user_id == user_id]
        for s in to_remove:
            del self._pending[s]

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [
            s for s, p in self._pending.items() if now - p.created_at > _STATE_TTL
        ]
        for s in expired:
            del self._pending[s]


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': 'openid',
        'state': state,
    }
    return f'{_CF_AUTHORIZE_URL}?{urlencode(params)}'


async def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    session: aiohttp.ClientSession,
) -> dict[str, Any]:
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
    }
    async with session.post(_CF_TOKEN_URL, data=data) as resp:
        body = await resp.json()
        if resp.status != 200:
            raise ValueError(f'Token exchange failed: {body}')
        return body  # type: ignore[no-any-return]


def decode_id_token(
    id_token: str,
    client_secret: str,
    client_id: str,
) -> dict[str, Any]:
    return jwt.decode(  # type: ignore[no-any-return]
        id_token,
        client_secret,
        algorithms=['HS256'],
        audience=client_id,
        issuer=_CF_ISSUER,
    )


_SUCCESS_HTML = """\
<!DOCTYPE html>
<html><head><title>Success</title></head>
<body style="font-family:sans-serif;text-align:center;padding-top:80px">
<h1>&#10004; Account linked!</h1>
<p>You can close this tab.</p>
</body></html>"""

_ERROR_HTML = """\
<!DOCTYPE html>
<html><head><title>Error</title></head>
<body style="font-family:sans-serif;text-align:center;padding-top:80px">
<h1>Something went wrong</h1>
<p>{message}</p>
</body></html>"""


class OAuthServer:
    def __init__(self, bot: Any, state_store: OAuthStateStore, port: int) -> None:
        self.bot = bot
        self.state_store = state_store
        self.port = port
        self._session: aiohttp.ClientSession | None = None
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()
        app = web.Application()
        app.router.add_get('/callback', self._handle_callback)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, '0.0.0.0', self.port)
        await site.start()
        logger.info('OAuth callback server listening on port %d', self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        if self._session:
            await self._session.close()

    async def _handle_callback(self, request: web.Request) -> web.Response:
        from tle import constants

        state = request.query.get('state')
        code = request.query.get('code')
        error = request.query.get('error')

        if error:
            return web.Response(
                text=_ERROR_HTML.format(message=f'Authorization denied: {error}'),
                content_type='text/html',
            )

        if not state or not code:
            return web.Response(
                text=_ERROR_HTML.format(message='Missing state or code parameter.'),
                content_type='text/html',
            )

        pending = self.state_store.consume(state)
        if pending is None:
            return web.Response(
                text=_ERROR_HTML.format(
                    message='Link expired or already used.'
                    ' Please run the command again.'
                ),
                content_type='text/html',
            )

        channel = self.bot.get_channel(pending.channel_id)

        try:
            assert constants.OAUTH_CLIENT_ID is not None
            assert constants.OAUTH_CLIENT_SECRET is not None
            assert constants.OAUTH_REDIRECT_URI is not None
            assert self._session is not None
            tokens = await exchange_code(
                code,
                constants.OAUTH_CLIENT_ID,
                constants.OAUTH_CLIENT_SECRET,
                constants.OAUTH_REDIRECT_URI,
                self._session,
            )
            claims = decode_id_token(
                tokens['id_token'],
                constants.OAUTH_CLIENT_SECRET,
                constants.OAUTH_CLIENT_ID,
            )
            handle = claims['handle']

            (user,) = await cf.user.info(handles=[handle])

            guild = self.bot.get_guild(pending.guild_id)
            if guild is None:
                raise ValueError('Guild not found')
            member = guild.get_member(pending.user_id)
            if member is None:
                raise ValueError('Member not found in guild')

            handles_cog = self.bot.get_cog('Handles')
            if handles_cog is None:
                raise ValueError('Handles cog not loaded')

            await handles_cog._set_from_oauth(guild, member, user)

            if channel:
                from tle.cogs.handles import _make_profile_embed

                embed = _make_profile_embed(member, user, mode='set')
                await channel.send(embed=embed)

            return web.Response(text=_SUCCESS_HTML, content_type='text/html')

        except Exception:
            logger.exception('OAuth callback error')
            if channel:
                import discord

                embed = discord.Embed(
                    description=(
                        'Something went wrong during Codeforces'
                        ' account linking. Please try again.'
                    ),
                    color=discord.Color.red(),
                )
                await channel.send(f'<@{pending.user_id}>', embed=embed)
            return web.Response(
                text=_ERROR_HTML.format(
                    message='An error occurred.'
                    ' Please try the command again in Discord.'
                ),
                content_type='text/html',
            )
