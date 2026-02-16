"""Tests for DuelChallengeView in tle.cogs.duel."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord

from tle.cogs.duel import DuelChallengeView
from tle.util.db.user_db_conn import Duel


def _make_view(timeout=300):
    bot = MagicMock()
    bot.user_db = AsyncMock()
    view = DuelChallengeView(
        bot=bot,
        duelid=42,
        challenger_id=1001,
        challengee_id=2002,
        problem_name='A. Test Problem',
        timeout=timeout,
    )
    return view


def _make_interaction(user_id, guild=None, channel=None):
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    interaction.guild = guild or MagicMock()
    interaction.channel = channel or AsyncMock()
    return interaction


class TestDuelChallengeViewInit:
    async def test_initialization_stores_state(self):
        view = _make_view()
        assert view.duelid == 42
        assert view.challenger_id == 1001
        assert view.challengee_id == 2002
        assert view.problem_name == 'A. Test Problem'
        assert view.message is None

    async def test_has_three_buttons(self):
        view = _make_view()
        assert len(view.children) == 3

    async def test_all_buttons_enabled_on_init(self):
        view = _make_view()
        for item in view.children:
            assert item.disabled is False

    async def test_button_labels(self):
        view = _make_view()
        labels = {item.label for item in view.children}
        assert labels == {'Accept', 'Decline', 'Withdraw'}

    async def test_button_styles(self):
        view = _make_view()
        styles = {item.label: item.style for item in view.children}
        assert styles['Accept'] == discord.ButtonStyle.success
        assert styles['Decline'] == discord.ButtonStyle.danger
        assert styles['Withdraw'] == discord.ButtonStyle.secondary


class TestAcceptButton:
    async def test_rejects_wrong_user(self):
        view = _make_view()
        interaction = _make_interaction(user_id=9999)

        await view.accept_button.callback(interaction)

        interaction.response.send_message.assert_awaited_once_with(
            'Only the challenged user can accept.',
            ephemeral=True,
        )

    async def test_rejects_challenger(self):
        view = _make_view()
        interaction = _make_interaction(user_id=1001)

        await view.accept_button.callback(interaction)

        interaction.response.send_message.assert_awaited_once_with(
            'Only the challenged user can accept.',
            ephemeral=True,
        )

    async def test_accepts_and_disables_buttons(self):
        view = _make_view()
        view.bot.user_db.start_duel.return_value = 1
        problem = MagicMock()
        problem.index = 'A'
        problem.name = 'Test Problem'
        problem.url = 'https://example.com'
        problem.rating = 1500
        problem.contestId = 100
        contest = MagicMock()
        contest.name = 'Test Contest'
        view.bot.cf_cache.problem_cache.problem_by_name = {
            'A. Test Problem': problem,
        }
        view.bot.cf_cache.contest_cache.get_contest.return_value = contest

        guild = MagicMock()
        guild.get_member.return_value = MagicMock(mention='@user')
        channel = AsyncMock()
        interaction = _make_interaction(
            user_id=2002,
            guild=guild,
            channel=channel,
        )

        with patch('tle.cogs.duel.asyncio.sleep', new_callable=AsyncMock):
            await view.accept_button.callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        for item in view.children:
            assert item.disabled is True

    async def test_handles_start_duel_failure(self):
        view = _make_view()
        view.bot.user_db.start_duel.return_value = 0

        guild = MagicMock()
        guild.get_member.return_value = MagicMock(mention='@user')
        channel = AsyncMock()
        interaction = _make_interaction(
            user_id=2002,
            guild=guild,
            channel=channel,
        )

        with patch('tle.cogs.duel.asyncio.sleep', new_callable=AsyncMock):
            await view.accept_button.callback(interaction)

        # Should send error about unable to start
        calls = channel.send.call_args_list
        assert any('Unable to start' in str(call) for call in calls)


class TestDeclineButton:
    async def test_rejects_wrong_user(self):
        view = _make_view()
        interaction = _make_interaction(user_id=9999)

        await view.decline_button.callback(interaction)

        interaction.response.send_message.assert_awaited_once_with(
            'Only the challenged user can decline.',
            ephemeral=True,
        )

    async def test_rejects_challenger(self):
        view = _make_view()
        interaction = _make_interaction(user_id=1001)

        await view.decline_button.callback(interaction)

        interaction.response.send_message.assert_awaited_once_with(
            'Only the challenged user can decline.',
            ephemeral=True,
        )

    async def test_decline_cancels_duel(self):
        view = _make_view()
        view.bot.user_db.cancel_duel.return_value = 1

        guild = MagicMock()
        guild.get_member.return_value = MagicMock(mention='@user')
        channel = AsyncMock()
        interaction = _make_interaction(
            user_id=2002,
            guild=guild,
            channel=channel,
        )

        await view.decline_button.callback(interaction)

        view.bot.user_db.cancel_duel.assert_awaited_once_with(42, Duel.DECLINED)
        interaction.response.edit_message.assert_awaited_once()
        for item in view.children:
            assert item.disabled is True

    async def test_decline_already_resolved(self):
        view = _make_view()
        view.bot.user_db.cancel_duel.return_value = 0

        guild = MagicMock()
        guild.get_member.return_value = MagicMock(mention='@user')
        channel = AsyncMock()
        interaction = _make_interaction(
            user_id=2002,
            guild=guild,
            channel=channel,
        )

        await view.decline_button.callback(interaction)

        channel.send.assert_awaited_with('This duel has already been resolved.')


class TestWithdrawButton:
    async def test_rejects_wrong_user(self):
        view = _make_view()
        interaction = _make_interaction(user_id=9999)

        await view.withdraw_button.callback(interaction)

        interaction.response.send_message.assert_awaited_once_with(
            'Only the challenger can withdraw.',
            ephemeral=True,
        )

    async def test_rejects_challengee(self):
        view = _make_view()
        interaction = _make_interaction(user_id=2002)

        await view.withdraw_button.callback(interaction)

        interaction.response.send_message.assert_awaited_once_with(
            'Only the challenger can withdraw.',
            ephemeral=True,
        )

    async def test_withdraw_cancels_duel(self):
        view = _make_view()
        view.bot.user_db.cancel_duel.return_value = 1

        guild = MagicMock()
        guild.get_member.return_value = MagicMock(mention='@user')
        channel = AsyncMock()
        interaction = _make_interaction(
            user_id=1001,
            guild=guild,
            channel=channel,
        )

        await view.withdraw_button.callback(interaction)

        view.bot.user_db.cancel_duel.assert_awaited_once_with(42, Duel.WITHDRAWN)
        interaction.response.edit_message.assert_awaited_once()
        for item in view.children:
            assert item.disabled is True

    async def test_withdraw_already_resolved(self):
        view = _make_view()
        view.bot.user_db.cancel_duel.return_value = 0

        guild = MagicMock()
        guild.get_member.return_value = MagicMock(mention='@user')
        channel = AsyncMock()
        interaction = _make_interaction(
            user_id=1001,
            guild=guild,
            channel=channel,
        )

        await view.withdraw_button.callback(interaction)

        channel.send.assert_awaited_with('This duel has already been resolved.')


class TestOnTimeout:
    async def test_disables_buttons_and_expires_duel(self):
        view = _make_view()
        view.bot.user_db.cancel_duel.return_value = 1
        message = AsyncMock()
        message.guild = MagicMock()
        message.guild.get_member.return_value = MagicMock(mention='@user')
        message.channel = AsyncMock()
        view.message = message

        await view.on_timeout()

        for item in view.children:
            assert item.disabled is True
        message.edit.assert_awaited_once_with(view=view)
        view.bot.user_db.cancel_duel.assert_awaited_once_with(42, Duel.EXPIRED)
        message.channel.send.assert_awaited_once()

    async def test_timeout_no_message(self):
        view = _make_view()
        view.bot.user_db.cancel_duel.return_value = 0

        # Should not raise when message is None
        await view.on_timeout()

        for item in view.children:
            assert item.disabled is True

    async def test_timeout_handles_not_found(self):
        view = _make_view()
        view.bot.user_db.cancel_duel.return_value = 0
        message = AsyncMock()
        message.edit.side_effect = discord.NotFound(
            MagicMock(status=404),
            'Not found',
        )
        view.message = message

        # Should not raise
        await view.on_timeout()

    async def test_timeout_already_resolved_no_alert(self):
        view = _make_view()
        view.bot.user_db.cancel_duel.return_value = 0
        message = AsyncMock()
        message.guild = MagicMock()
        message.channel = AsyncMock()
        view.message = message

        await view.on_timeout()

        # cancel_duel returned 0, so no expiry alert
        message.channel.send.assert_not_awaited()
