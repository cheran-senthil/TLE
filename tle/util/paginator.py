from collections.abc import Sequence
from typing import Any

import discord
from discord.ext import commands

Page = tuple[str | None, discord.Embed]


def chunkify(sequence: Sequence[Any], chunk_size: int) -> list[Sequence[Any]]:
    """Utility method to split a sequence into fixed size chunks."""
    return [sequence[i : i + chunk_size] for i in range(0, len(sequence), chunk_size)]


class PaginatorError(Exception):
    pass


class NoPagesError(PaginatorError):
    pass


class PaginatorView(discord.ui.View):
    def __init__(self, pages: Sequence[Page], *, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self.cur_page = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        on_first = self.cur_page == 0
        on_last = self.cur_page == len(self.pages) - 1
        self.first_button.disabled = on_first
        self.prev_button.disabled = on_first
        self.next_button.disabled = on_last
        self.last_button.disabled = on_last

    async def _show_page(self, interaction: discord.Interaction) -> None:
        content, embed = self.pages[self.cur_page]
        self._update_buttons()
        await interaction.response.edit_message(content=content, embed=embed, view=self)

    @discord.ui.button(
        emoji='\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}',
        style=discord.ButtonStyle.secondary,
    )
    async def first_button(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        self.cur_page = 0
        await self._show_page(interaction)

    @discord.ui.button(
        emoji='\N{BLACK LEFT-POINTING TRIANGLE}',
        style=discord.ButtonStyle.secondary,
    )
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        self.cur_page = max(0, self.cur_page - 1)
        await self._show_page(interaction)

    @discord.ui.button(
        emoji='\N{BLACK RIGHT-POINTING TRIANGLE}',
        style=discord.ButtonStyle.secondary,
    )
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        self.cur_page = min(len(self.pages) - 1, self.cur_page + 1)
        await self._show_page(interaction)

    @discord.ui.button(
        emoji='\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}',
        style=discord.ButtonStyle.secondary,
    )
    async def last_button(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        self.cur_page = len(self.pages) - 1
        await self._show_page(interaction)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass


async def paginate(
    channel: discord.abc.Messageable,
    pages: Sequence[Page],
    *,
    wait_time: float,
    set_pagenum_footers: bool = False,
    delete_after: float | None = None,
    ctx: commands.Context | None = None,
) -> None:
    if not pages:
        raise NoPagesError()
    if len(pages) > 1 and set_pagenum_footers:
        for i, (_content, embed) in enumerate(pages):
            embed.set_footer(text=f'Page {i + 1} / {len(pages)}')

    content, embed = pages[0]
    if len(pages) == 1:
        if ctx is not None:
            await ctx.send(content, embed=embed, delete_after=delete_after)
        else:
            await channel.send(content, embed=embed, delete_after=delete_after)
    else:
        view = PaginatorView(pages, timeout=wait_time)
        if ctx is not None:
            view.message = await ctx.send(
                content, embed=embed, view=view, delete_after=delete_after
            )
        else:
            view.message = await channel.send(
                content, embed=embed, view=view, delete_after=delete_after
            )
