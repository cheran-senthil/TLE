"""Tests for tle.util.paginator — chunkify, errors, Paginated, paginate."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tle.util.paginator import (
    InsufficientPermissionsError,
    NoPagesError,
    Paginated,
    PaginatorError,
    chunkify,
    paginate,
)


# --- chunkify ---


class TestChunkify:
    def test_exact_division(self):
        assert chunkify([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_remainder(self):
        assert chunkify([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    def test_single_chunk(self):
        assert chunkify([1, 2, 3], 5) == [[1, 2, 3]]

    def test_empty(self):
        assert chunkify([], 3) == []

    def test_chunk_size_one(self):
        assert chunkify([1, 2, 3], 1) == [[1], [2], [3]]

    def test_string_sequence(self):
        assert chunkify('abcde', 2) == ['ab', 'cd', 'e']


# --- Errors ---


class TestErrors:
    def test_no_pages_is_paginator_error(self):
        assert issubclass(NoPagesError, PaginatorError)

    def test_insufficient_permissions_is_paginator_error(self):
        assert issubclass(InsufficientPermissionsError, PaginatorError)


# --- Paginated ---


class TestPaginated:
    def test_initialization(self):
        pages = [('c1', 'e1'), ('c2', 'e2')]
        p = Paginated(pages)
        assert len(p.reaction_map) == 4
        assert p.cur_page is None
        assert p.message is None

    async def test_show_page_valid(self):
        pages = [('c1', 'e1'), ('c2', 'e2'), ('c3', 'e3')]
        p = Paginated(pages)
        p.message = AsyncMock()
        p.cur_page = 1

        await p.show_page(2)
        assert p.cur_page == 2
        p.message.edit.assert_awaited_once_with(content='c2', embed='e2')

    async def test_show_page_out_of_range_low(self):
        pages = [('c1', 'e1'), ('c2', 'e2')]
        p = Paginated(pages)
        p.message = AsyncMock()
        p.cur_page = 1

        await p.show_page(0)
        assert p.cur_page == 1
        p.message.edit.assert_not_awaited()

    async def test_show_page_out_of_range_high(self):
        pages = [('c1', 'e1'), ('c2', 'e2')]
        p = Paginated(pages)
        p.message = AsyncMock()
        p.cur_page = 1

        await p.show_page(3)
        assert p.cur_page == 1
        p.message.edit.assert_not_awaited()

    async def test_prev_page(self):
        pages = [('c1', 'e1'), ('c2', 'e2'), ('c3', 'e3')]
        p = Paginated(pages)
        p.message = AsyncMock()
        p.cur_page = 2

        await p.prev_page()
        assert p.cur_page == 1

    async def test_next_page(self):
        pages = [('c1', 'e1'), ('c2', 'e2'), ('c3', 'e3')]
        p = Paginated(pages)
        p.message = AsyncMock()
        p.cur_page = 1

        await p.next_page()
        assert p.cur_page == 2

    async def test_paginate_single_page(self):
        pages = [('content', 'embed')]
        p = Paginated(pages)
        channel = AsyncMock()
        bot = MagicMock()

        await p.paginate(bot, channel, wait_time=1)
        channel.send.assert_awaited_once_with('content', embed='embed', delete_after=None)
        # Single page: no reactions added
        assert p.message.add_reaction.await_count == 0

    async def test_paginate_multi_page(self):
        pages = [('c1', 'e1'), ('c2', 'e2')]
        p = Paginated(pages)

        mock_message = AsyncMock()
        channel = AsyncMock()
        channel.send.return_value = mock_message

        bot = MagicMock()
        # Immediately timeout to exit the loop
        bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError)

        await p.paginate(bot, channel, wait_time=1)

        # 4 reactions should be added
        assert mock_message.add_reaction.await_count == 4
        # On timeout, clear_reactions should be called
        mock_message.clear_reactions.assert_awaited_once()


# --- paginate function ---


class TestPaginateFunction:
    def test_empty_pages_raises_no_pages_error(self):
        with pytest.raises(NoPagesError):
            paginate(MagicMock(), MagicMock(), [], wait_time=60)

    def test_no_manage_messages_raises_insufficient_permissions(self):
        bot = MagicMock()
        channel = MagicMock()
        permissions = MagicMock()
        permissions.manage_messages = False
        channel.permissions_for.return_value = permissions

        pages = [('c1', MagicMock())]
        with pytest.raises(InsufficientPermissionsError):
            paginate(bot, channel, pages, wait_time=60)

    def test_sets_page_footers(self):
        bot = MagicMock()
        channel = MagicMock()
        permissions = MagicMock()
        permissions.manage_messages = True
        channel.permissions_for.return_value = permissions

        embed1 = MagicMock()
        embed2 = MagicMock()
        pages = [('c1', embed1), ('c2', embed2)]

        with patch('tle.util.paginator.asyncio.create_task'):
            paginate(bot, channel, pages, wait_time=60, set_pagenum_footers=True)

        embed1.set_footer.assert_called_once_with(text='Page 1 / 2')
        embed2.set_footer.assert_called_once_with(text='Page 2 / 2')

    def test_single_page_no_footers(self):
        bot = MagicMock()
        channel = MagicMock()
        permissions = MagicMock()
        permissions.manage_messages = True
        channel.permissions_for.return_value = permissions

        embed = MagicMock()
        pages = [('c1', embed)]

        with patch('tle.util.paginator.asyncio.create_task'):
            paginate(bot, channel, pages, wait_time=60, set_pagenum_footers=True)

        # Single page, set_pagenum_footers condition (len > 1) is false
        embed.set_footer.assert_not_called()

    def test_creates_task(self):
        bot = MagicMock()
        channel = MagicMock()
        permissions = MagicMock()
        permissions.manage_messages = True
        channel.permissions_for.return_value = permissions

        pages = [('c1', MagicMock())]

        with patch('tle.util.paginator.asyncio.create_task') as mock_create_task:
            paginate(bot, channel, pages, wait_time=60)
            mock_create_task.assert_called_once()
