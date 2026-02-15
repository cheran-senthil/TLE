"""Component tests for tle.util.db.user_db_conn — async in-memory aiosqlite."""

import pytest

from tle.util.db.user_db_conn import (
    Duel,
    DuelType,
    Gitgud,
    UniqueConstraintFailed,
    Winner,
)


class TestTableCreation:
    async def test_tables_exist(self, user_db):
        cursor = await user_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}
        expected = {
            'user_handle',
            'cf_user_cache',
            'duelist',
            'duel',
            'challenge',
            'user_challenge',
            'reminder',
            'rankup',
            'auto_role_update',
            'rated_vcs',
            'rated_vc_users',
            'rated_vc_settings',
            'starboard_config_v1',
            'starboard_emoji_v1',
            'starboard_message_v1',
        }
        assert expected.issubset(table_names)


class TestHandleCRUD:
    async def test_set_and_get(self, user_db):
        await user_db.set_handle(123, 'guild1', 'tourist')
        handle = await user_db.get_handle(123, 'guild1')
        assert handle == 'tourist'

    async def test_not_found(self, user_db):
        handle = await user_db.get_handle(999, 'guild1')
        assert handle is None

    async def test_update_same_user(self, user_db):
        await user_db.set_handle(123, 'guild1', 'tourist')
        await user_db.set_handle(123, 'guild1', 'Petr')
        handle = await user_db.get_handle(123, 'guild1')
        assert handle == 'Petr'

    async def test_duplicate_raises(self, user_db):
        await user_db.set_handle(123, 'guild1', 'tourist')
        with pytest.raises(UniqueConstraintFailed):
            await user_db.set_handle(456, 'guild1', 'tourist')

    async def test_remove(self, user_db):
        await user_db.set_handle(123, 'guild1', 'tourist')
        rc = await user_db.remove_handle('tourist', 'guild1')
        assert rc == 1
        handle = await user_db.get_handle(123, 'guild1')
        assert handle is None

    async def test_remove_case_insensitive(self, user_db):
        await user_db.set_handle(123, 'guild1', 'Tourist')
        rc = await user_db.remove_handle('TOURIST', 'guild1')
        assert rc == 1

    async def test_get_handles_for_guild(self, user_db):
        await user_db.set_handle(1, 'guild1', 'alice')
        await user_db.set_handle(2, 'guild1', 'bob')
        await user_db.set_handle(3, 'guild2', 'charlie')
        handles = await user_db.get_handles_for_guild('guild1')
        handle_map = dict(handles)
        assert handle_map[1] == 'alice'
        assert handle_map[2] == 'bob'
        assert 3 not in handle_map

    async def test_get_user_id(self, user_db):
        await user_db.set_handle(123, 'guild1', 'Tourist')
        user_id = await user_db.get_user_id('tourist', 'guild1')
        assert user_id == 123

    async def test_get_user_id_not_found(self, user_db):
        user_id = await user_db.get_user_id('nonexistent', 'guild1')
        assert user_id is None


class TestHandleStatus:
    async def test_set_inactive(self, user_db):
        await user_db.set_handle(1, 'guild1', 'alice')
        await user_db.set_inactive([('guild1', 1)])
        handles = await user_db.get_handles_for_guild('guild1')
        assert len(handles) == 0

    async def test_reset_status(self, user_db):
        await user_db.set_handle(1, 'guild1', 'alice')
        await user_db.set_handle(2, 'guild1', 'bob')
        await user_db.reset_status('guild1')
        handles = await user_db.get_handles_for_guild('guild1')
        assert len(handles) == 0

    async def test_update_status(self, user_db):
        await user_db.set_handle(1, 'guild1', 'alice')
        await user_db.set_handle(2, 'guild1', 'bob')
        await user_db.reset_status('guild1')
        rc = await user_db.update_status('guild1', [1])
        assert rc == 1
        handles = await user_db.get_handles_for_guild('guild1')
        assert len(handles) == 1


class TestCfUserCache:
    async def test_cache_and_fetch(self, user_db):
        user_tuple = (
            'Tourist',
            'Gennady',
            'Korotkevich',
            'Belarus',
            'Gomel',
            'ITMO University',
            100,
            3800,
            3800,
            1000,
            2000,
            500,
            'https://example.com/photo.jpg',
        )
        await user_db.cache_cf_user(user_tuple)
        fetched = await user_db.fetch_cf_user('Tourist')
        assert fetched is not None
        assert fetched.handle == 'Tourist'
        assert fetched.rating == 3800

    async def test_not_found(self, user_db):
        fetched = await user_db.fetch_cf_user('nonexistent')
        assert fetched is None

    async def test_case_insensitive(self, user_db):
        user_tuple = (
            'Tourist',
            'Gennady',
            'Korotkevich',
            'Belarus',
            'Gomel',
            'ITMO University',
            100,
            3800,
            3800,
            1000,
            2000,
            500,
            'https://example.com/photo.jpg',
        )
        await user_db.cache_cf_user(user_tuple)
        fetched = await user_db.fetch_cf_user('tourist')
        assert fetched is not None

    async def test_url_fixing(self, user_db):
        user_tuple = (
            'test',
            None,
            None,
            None,
            None,
            None,
            0,
            1500,
            1500,
            0,
            0,
            0,
            '//example.com/photo.jpg',
        )
        await user_db.cache_cf_user(user_tuple)
        fetched = await user_db.fetch_cf_user('test')
        assert fetched.titlePhoto.startswith('https:')


class TestChallenge:
    async def test_new_challenge(self, user_db, make_problem):
        prob = make_problem(name='Test Problem', contestId=1, index='A')
        rc = await user_db.new_challenge('user1', 1000.0, prob, 100)
        assert rc == 1

    async def test_check_challenge(self, user_db, make_problem):
        prob = make_problem(name='Test Problem', contestId=1, index='A')
        await user_db.new_challenge('user1', 1000.0, prob, 100)
        result = await user_db.check_challenge('user1')
        assert result is not None
        c_id, issue_time, name, contest_id, p_index, delta = result
        assert name == 'Test Problem'
        assert delta == 100

    async def test_check_challenge_none(self, user_db):
        result = await user_db.check_challenge('nonexistent')
        assert result is None

    async def test_double_challenge_fails(self, user_db, make_problem):
        prob = make_problem(name='Problem 1', contestId=1, index='A')
        rc1 = await user_db.new_challenge('user1', 1000.0, prob, 100)
        assert rc1 == 1
        prob2 = make_problem(name='Problem 2', contestId=2, index='B')
        rc2 = await user_db.new_challenge('user1', 2000.0, prob2, 200)
        assert rc2 == 0

    async def test_complete_challenge(self, user_db, make_problem):
        prob = make_problem(name='Test Problem', contestId=1, index='A')
        await user_db.new_challenge('user1', 1000.0, prob, 100)
        result = await user_db.check_challenge('user1')
        c_id = result[0]
        rc = await user_db.complete_challenge('user1', c_id, 2000.0, 100)
        assert rc == 1
        # After completion, no active challenge
        result = await user_db.check_challenge('user1')
        assert result is None or result[0] is None

    async def test_skip_challenge(self, user_db, make_problem):
        prob = make_problem(name='Test Problem', contestId=1, index='A')
        await user_db.new_challenge('user1', 1000.0, prob, 100)
        result = await user_db.check_challenge('user1')
        c_id = result[0]
        rc = await user_db.skip_challenge('user1', c_id, Gitgud.NOGUD)
        assert rc == 1

    async def test_get_gudgitters(self, user_db, make_problem):
        prob = make_problem(name='Test Problem', contestId=1, index='A')
        await user_db.new_challenge('user1', 1000.0, prob, 100)
        gudgitters = await user_db.get_gudgitters()
        assert len(gudgitters) >= 1

    async def test_gitlog(self, user_db, make_problem):
        prob = make_problem(name='Test Problem', contestId=1, index='A')
        await user_db.new_challenge('user1', 1000.0, prob, 100)
        result = await user_db.check_challenge('user1')
        c_id = result[0]
        await user_db.complete_challenge('user1', c_id, 2000.0, 100)
        log = await user_db.gitlog('user1')
        assert len(log) >= 1


class TestDuel:
    async def test_register_and_is_duelist(self, user_db):
        await user_db.register_duelist(1)
        result = await user_db.is_duelist(1)
        assert result is not None

    async def test_is_not_duelist(self, user_db):
        result = await user_db.is_duelist(999)
        assert result is None

    async def test_create_duel(self, user_db, make_problem):
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        assert duel_id is not None
        assert duel_id > 0

    async def test_check_duel_challenge(self, user_db, make_problem):
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        result = await user_db.check_duel_challenge(1)
        assert result is not None

    async def test_check_duel_accept(self, user_db, make_problem):
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        result = await user_db.check_duel_accept(2)
        assert result is not None

    async def test_check_duel_decline(self, user_db, make_problem):
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        result = await user_db.check_duel_decline(2)
        assert result is not None

    async def test_check_duel_withdraw(self, user_db, make_problem):
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        result = await user_db.check_duel_withdraw(1)
        assert result is not None

    async def test_start_duel(self, user_db, make_problem):
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        rc = await user_db.start_duel(duel_id, 2000.0)
        assert rc == 1

    async def test_cancel_duel(self, user_db, make_problem):
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        rc = await user_db.cancel_duel(duel_id, Duel.DECLINED)
        assert rc == 1

    async def test_complete_duel_challenger_wins(self, user_db, make_problem):
        await user_db.register_duelist(1)
        await user_db.register_duelist(2)
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        await user_db.start_duel(duel_id, 2000.0)
        rc = await user_db.complete_duel(
            duel_id,
            Winner.CHALLENGER,
            3000.0,
            winner_id=1,
            loser_id=2,
            delta=50,
            dtype=DuelType.OFFICIAL,
        )
        assert rc == 1

    async def test_complete_duel_draw(self, user_db, make_problem):
        await user_db.register_duelist(1)
        await user_db.register_duelist(2)
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        await user_db.start_duel(duel_id, 2000.0)
        rc = await user_db.complete_duel(
            duel_id,
            Winner.DRAW,
            3000.0,
            dtype=DuelType.UNOFFICIAL,
        )
        assert rc == 1

    async def test_invalidate_duel(self, user_db, make_problem):
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        await user_db.start_duel(duel_id, 2000.0)
        rc = await user_db.invalidate_duel(duel_id)
        assert rc == 1

    async def test_get_duel_rating(self, user_db):
        await user_db.register_duelist(1)
        rating = await user_db.get_duel_rating(1)
        assert rating == 1500

    async def test_update_duel_rating(self, user_db):
        await user_db.register_duelist(1)
        await user_db.update_duel_rating(1, 50)
        rating = await user_db.get_duel_rating(1)
        assert rating == 1550

    async def test_get_duels(self, user_db, make_problem):
        await user_db.register_duelist(1)
        await user_db.register_duelist(2)
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        await user_db.start_duel(duel_id, 2000.0)
        await user_db.complete_duel(
            duel_id,
            Winner.CHALLENGER,
            3000.0,
            winner_id=1,
            loser_id=2,
            delta=50,
            dtype=DuelType.OFFICIAL,
        )
        duels = await user_db.get_duels(1)
        assert len(duels) == 1

    async def test_get_duel_wins(self, user_db, make_problem):
        await user_db.register_duelist(1)
        await user_db.register_duelist(2)
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        await user_db.start_duel(duel_id, 2000.0)
        await user_db.complete_duel(
            duel_id,
            Winner.CHALLENGER,
            3000.0,
            winner_id=1,
            loser_id=2,
            delta=50,
            dtype=DuelType.OFFICIAL,
        )
        wins = await user_db.get_duel_wins(1)
        assert len(wins) == 1

    async def test_get_recent_duels(self, user_db, make_problem):
        await user_db.register_duelist(1)
        await user_db.register_duelist(2)
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        await user_db.start_duel(duel_id, 2000.0)
        await user_db.complete_duel(
            duel_id,
            Winner.CHALLENGER,
            3000.0,
            winner_id=1,
            loser_id=2,
            delta=50,
            dtype=DuelType.OFFICIAL,
        )
        recent = await user_db.get_recent_duels()
        assert len(recent) >= 1

    async def test_get_num_duel_completed(self, user_db, make_problem):
        await user_db.register_duelist(1)
        await user_db.register_duelist(2)
        prob = make_problem(name='Duel Problem', contestId=1, index='A')
        duel_id = await user_db.create_duel(1, 2, 1000.0, prob, DuelType.OFFICIAL)
        await user_db.start_duel(duel_id, 2000.0)
        await user_db.complete_duel(
            duel_id,
            Winner.CHALLENGER,
            3000.0,
            winner_id=1,
            loser_id=2,
            delta=50,
            dtype=DuelType.OFFICIAL,
        )
        count = await user_db.get_num_duel_completed(1)
        assert count == 1


class TestReminder:
    async def test_set_and_get(self, user_db):
        await user_db.set_reminder_settings('guild1', 'chan1', 'role1', '15')
        result = await user_db.get_reminder_settings('guild1')
        assert result is not None
        assert result[0] == 'chan1'
        assert result[1] == 'role1'

    async def test_not_found(self, user_db):
        result = await user_db.get_reminder_settings('nonexistent')
        assert result is None

    async def test_clear(self, user_db):
        await user_db.set_reminder_settings('guild1', 'chan1', 'role1', '15')
        await user_db.clear_reminder_settings('guild1')
        result = await user_db.get_reminder_settings('guild1')
        assert result is None


class TestRankup:
    async def test_set_and_get(self, user_db):
        await user_db.set_rankup_channel('guild1', '123456')
        channel_id = await user_db.get_rankup_channel('guild1')
        assert channel_id == 123456

    async def test_not_found(self, user_db):
        channel_id = await user_db.get_rankup_channel('nonexistent')
        assert channel_id is None

    async def test_clear(self, user_db):
        await user_db.set_rankup_channel('guild1', '123456')
        rc = await user_db.clear_rankup_channel('guild1')
        assert rc == 1
        channel_id = await user_db.get_rankup_channel('guild1')
        assert channel_id is None


class TestAutoRoleUpdate:
    async def test_enable_and_check(self, user_db):
        await user_db.enable_auto_role_update('guild1')
        assert await user_db.has_auto_role_update_enabled('guild1') is True

    async def test_not_enabled(self, user_db):
        assert await user_db.has_auto_role_update_enabled('guild1') is False

    async def test_disable(self, user_db):
        await user_db.enable_auto_role_update('guild1')
        await user_db.disable_auto_role_update('guild1')
        assert await user_db.has_auto_role_update_enabled('guild1') is False


class TestRatedVC:
    async def test_create_and_get(self, user_db):
        vc_id = await user_db.create_rated_vc(
            42, 1000.0, 2000.0, 'guild1', ['u1', 'u2']
        )
        vc = await user_db.get_rated_vc(vc_id)
        assert vc is not None
        assert vc.contest_id == 42

    async def test_ongoing_ids(self, user_db):
        vc_id = await user_db.create_rated_vc(42, 1000.0, 2000.0, 'guild1', ['u1'])
        ids = await user_db.get_ongoing_rated_vc_ids()
        assert vc_id in ids

    async def test_finish(self, user_db):
        vc_id = await user_db.create_rated_vc(42, 1000.0, 2000.0, 'guild1', ['u1'])
        await user_db.finish_rated_vc(vc_id)
        ids = await user_db.get_ongoing_rated_vc_ids()
        assert vc_id not in ids

    async def test_user_ids(self, user_db):
        vc_id = await user_db.create_rated_vc(
            42, 1000.0, 2000.0, 'guild1', ['u1', 'u2']
        )
        user_ids = await user_db.get_rated_vc_user_ids(vc_id)
        assert set(user_ids) == {'u1', 'u2'}

    async def test_vc_rating_update_and_get(self, user_db):
        vc_id = await user_db.create_rated_vc(42, 1000.0, 2000.0, 'guild1', ['u1'])
        await user_db.update_vc_rating(vc_id, 'u1', 1600)
        rating = await user_db.get_vc_rating('u1')
        assert rating == 1600

    async def test_vc_rating_default(self, user_db):
        rating = await user_db.get_vc_rating('nonexistent', default_if_not_exist=True)
        assert rating == 1500

    async def test_vc_rating_no_default(self, user_db):
        rating = await user_db.get_vc_rating('nonexistent', default_if_not_exist=False)
        assert rating is None

    async def test_vc_rating_history(self, user_db):
        vc_id1 = await user_db.create_rated_vc(42, 1000.0, 2000.0, 'guild1', ['u1'])
        await user_db.update_vc_rating(vc_id1, 'u1', 1600)
        vc_id2 = await user_db.create_rated_vc(43, 3000.0, 4000.0, 'guild1', ['u1'])
        await user_db.update_vc_rating(vc_id2, 'u1', 1700)
        history = await user_db.get_vc_rating_history('u1')
        assert len(history) == 2

    async def test_channel_settings(self, user_db):
        await user_db.set_rated_vc_channel('guild1', '123456')
        channel = await user_db.get_rated_vc_channel('guild1')
        assert channel == 123456

    async def test_remove_last_participation(self, user_db):
        vc_id = await user_db.create_rated_vc(42, 1000.0, 2000.0, 'guild1', ['u1'])
        await user_db.update_vc_rating(vc_id, 'u1', 1600)
        rc = await user_db.remove_last_ratedvc_participation('u1')
        assert rc == 1


class TestStarboard:
    async def test_add_and_get_emoji(self, user_db):
        await user_db.add_starboard_emoji('guild1', 'star', 5, 0xFFAA10)
        await user_db.set_starboard_channel('guild1', 'star', '123456')
        entry = await user_db.get_starboard_entry('guild1', 'star')
        assert entry is not None
        channel_id, threshold, color = entry
        assert channel_id == 123456
        assert threshold == 5

    async def test_not_found(self, user_db):
        entry = await user_db.get_starboard_entry('guild1', 'nonexistent')
        assert entry is None

    async def test_remove_emoji(self, user_db):
        await user_db.add_starboard_emoji('guild1', 'star', 5, 0xFFAA10)
        rc = await user_db.remove_starboard_emoji('guild1', 'star')
        assert rc == 1

    async def test_update_threshold(self, user_db):
        await user_db.add_starboard_emoji('guild1', 'star', 5, 0xFFAA10)
        rc = await user_db.update_starboard_threshold('guild1', 'star', 10)
        assert rc == 1

    async def test_update_color(self, user_db):
        await user_db.add_starboard_emoji('guild1', 'star', 5, 0xFFAA10)
        rc = await user_db.update_starboard_color('guild1', 'star', 0xFF0000)
        assert rc == 1

    async def test_message_add_and_exists(self, user_db):
        await user_db.add_starboard_message('orig1', 'star1', 'guild1', 'star')
        exists = await user_db.check_exists_starboard_message('orig1', 'star')
        assert exists is True

    async def test_message_not_exists(self, user_db):
        exists = await user_db.check_exists_starboard_message('nonexistent', 'star')
        assert exists is False

    async def test_remove_message_by_original(self, user_db):
        await user_db.add_starboard_message('orig1', 'star1', 'guild1', 'star')
        rc = await user_db.remove_starboard_message(
            original_msg_id='orig1', emoji='star'
        )
        assert rc == 1

    async def test_remove_message_by_starboard_id(self, user_db):
        await user_db.add_starboard_message('orig1', 'star1', 'guild1', 'star')
        rc = await user_db.remove_starboard_message(starboard_msg_id='star1')
        assert rc == 1

    async def test_clear_channel(self, user_db):
        await user_db.set_starboard_channel('guild1', 'star', '123456')
        rc = await user_db.clear_starboard_channel('guild1', 'star')
        assert rc == 1
