"""Tests for tle.util.paginator — chunkify, errors, PaginatorView, paginate."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from tle.util.paginator import (
    NoPagesError,
    PaginatorError,
    PaginatorView,
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


# --- PaginatorView ---


class TestPaginatorView:
    async def test_initialization(self):
        pages = [('c1', 'e1'), ('c2', 'e2')]
        view = PaginatorView(pages, timeout=60)
        assert view.cur_page == 0
        assert view.message is None
        assert len(view.children) == 4

    async def test_buttons_disabled_on_first_page(self):
        pages = [('c1', 'e1'), ('c2', 'e2'), ('c3', 'e3')]
        view = PaginatorView(pages, timeout=60)
        # On first page: first/prev disabled, next/last enabled
        assert view.first_button.disabled is True
        assert view.prev_button.disabled is True
        assert view.next_button.disabled is False
        assert view.last_button.disabled is False

    async def test_buttons_disabled_on_last_page(self):
        pages = [('c1', 'e1'), ('c2', 'e2'), ('c3', 'e3')]
        view = PaginatorView(pages, timeout=60)
        view.cur_page = 2
        view._update_buttons()
        # On last page: first/prev enabled, next/last disabled
        assert view.first_button.disabled is False
        assert view.prev_button.disabled is False
        assert view.next_button.disabled is True
        assert view.last_button.disabled is True

    async def test_buttons_middle_page(self):
        pages = [('c1', 'e1'), ('c2', 'e2'), ('c3', 'e3')]
        view = PaginatorView(pages, timeout=60)
        view.cur_page = 1
        view._update_buttons()
        # On middle page: all enabled
        assert view.first_button.disabled is False
        assert view.prev_button.disabled is False
        assert view.next_button.disabled is False
        assert view.last_button.disabled is False

    async def test_single_page_all_disabled(self):
        pages = [('c1', 'e1')]
        view = PaginatorView(pages, timeout=60)
        assert view.first_button.disabled is True
        assert view.prev_button.disabled is True
        assert view.next_button.disabled is True
        assert view.last_button.disabled is True

    async def test_on_timeout_disables_buttons(self):
        pages = [('c1', 'e1'), ('c2', 'e2')]
        view = PaginatorView(pages, timeout=60)
        view.message = AsyncMock()

        await view.on_timeout()

        for item in view.children:
            assert item.disabled is True
        view.message.edit.assert_awaited_once_with(view=view)

    async def test_on_timeout_handles_not_found(self):
        pages = [('c1', 'e1'), ('c2', 'e2')]
        view = PaginatorView(pages, timeout=60)
        view.message = AsyncMock()
        view.message.edit.side_effect = discord.NotFound(
            MagicMock(status=404), 'Not found'
        )

        # Should not raise
        await view.on_timeout()

    async def test_on_timeout_no_message(self):
        pages = [('c1', 'e1'), ('c2', 'e2')]
        view = PaginatorView(pages, timeout=60)
        # message is None by default, should not raise
        await view.on_timeout()


# --- paginate function ---


class TestPaginateFunction:
    async def test_empty_pages_raises_no_pages_error(self):
        with pytest.raises(NoPagesError):
            await paginate(MagicMock(), [], wait_time=60)

    async def test_sets_page_footers(self):
        channel = AsyncMock()
        embed1 = MagicMock()
        embed2 = MagicMock()
        pages = [('c1', embed1), ('c2', embed2)]

        await paginate(channel, pages, wait_time=60, set_pagenum_footers=True)

        embed1.set_footer.assert_called_once_with(text='Page 1 / 2')
        embed2.set_footer.assert_called_once_with(text='Page 2 / 2')

    async def test_single_page_no_footers(self):
        channel = AsyncMock()
        embed = MagicMock()
        pages = [('c1', embed)]

        await paginate(channel, pages, wait_time=60, set_pagenum_footers=True)

        # Single page, set_pagenum_footers condition (len > 1) is false
        embed.set_footer.assert_not_called()

    async def test_single_page_sends_without_view(self):
        channel = AsyncMock()
        embed = MagicMock()
        pages = [('content', embed)]

        await paginate(channel, pages, wait_time=60)

        channel.send.assert_awaited_once_with('content', embed=embed, delete_after=None)

    async def test_single_page_with_ctx(self):
        channel = AsyncMock()
        ctx = AsyncMock()
        embed = MagicMock()
        pages = [('content', embed)]

        await paginate(channel, pages, wait_time=60, ctx=ctx)

        ctx.send.assert_awaited_once_with('content', embed=embed, delete_after=None)
        channel.send.assert_not_awaited()

    async def test_multi_page_sends_with_view(self):
        channel = AsyncMock()
        embed1 = MagicMock()
        embed2 = MagicMock()
        pages = [('c1', embed1), ('c2', embed2)]

        await paginate(channel, pages, wait_time=60)

        # Should send with view kwarg
        channel.send.assert_awaited_once()
        call_kwargs = channel.send.call_args.kwargs
        assert 'view' in call_kwargs
        assert isinstance(call_kwargs['view'], PaginatorView)

    async def test_multi_page_with_ctx(self):
        ctx = AsyncMock()
        channel = AsyncMock()
        embed1 = MagicMock()
        embed2 = MagicMock()
        pages = [('c1', embed1), ('c2', embed2)]

        await paginate(channel, pages, wait_time=60, ctx=ctx)

        ctx.send.assert_awaited_once()
        call_kwargs = ctx.send.call_args.kwargs
        assert 'view' in call_kwargs
        assert isinstance(call_kwargs['view'], PaginatorView)
        channel.send.assert_not_awaited()
