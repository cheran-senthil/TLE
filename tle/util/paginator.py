import asyncio
import functools

_REACT_FIRST = '\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}'
_REACT_PREV = '\N{BLACK LEFT-POINTING TRIANGLE}'
_REACT_NEXT = '\N{BLACK RIGHT-POINTING TRIANGLE}'
_REACT_LAST = '\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}'


def chunkify(sequence, chunk_size):
    """Utility method to split a sequence into fixed size chunks."""
    return [sequence[i: i + chunk_size] for i in range(0, len(sequence), chunk_size)]


class PaginatorError(Exception):
    pass


class NoPagesError(PaginatorError):
    pass


class InsufficientPermissionsError(PaginatorError):
    pass


class Paginated:
    def __init__(self, pages):
        self.pages = pages
        self.cur_page = None
        self.message = None
        self.reaction_map = {
            _REACT_FIRST: functools.partial(self.show_page, 1),
            _REACT_PREV: self.prev_page,
            _REACT_NEXT: self.next_page,
            _REACT_LAST: functools.partial(self.show_page, len(pages))
        }

    async def show_page(self, page_num):
        if 1 <= page_num <= len(self.pages):
            content, embed = self.pages[page_num - 1]
            await self.message.edit(content=content, embed=embed)
            self.cur_page = page_num

    async def prev_page(self):
        await self.show_page(self.cur_page - 1)

    async def next_page(self):
        await self.show_page(self.cur_page + 1)

    async def paginate(self, bot, channel, wait_time):
        content, embed = self.pages[0]
        self.message = await channel.send(content, embed=embed)

        if len(self.pages) == 1:
            # No need to paginate.
            return

        self.cur_page = 1
        for react in self.reaction_map.keys():
            await self.message.add_reaction(react)

        def check(reaction, user):
            return (bot.user != user and
                    reaction.message.id == self.message.id and
                    reaction.emoji in self.reaction_map)

        while True:
            try:
                reaction, user = await bot.wait_for('reaction_add', timeout=wait_time, check=check)
                await reaction.remove(user)
                await self.reaction_map[reaction.emoji]()
            except asyncio.TimeoutError:
                await self.message.clear_reactions()
                break


def paginate(bot, channel, pages, *, wait_time, set_pagenum_footers=False):
    if not pages:
        raise NoPagesError()
    permissions = channel.permissions_for(channel.guild.me)
    if not permissions.manage_messages:
        raise InsufficientPermissionsError('Permission to manage messages required')
    if len(pages) > 1 and set_pagenum_footers:
        for i, (content, embed) in enumerate(pages):
            embed.set_footer(text=f'Page {i + 1} / {len(pages)}')
    paginated = Paginated(pages)
    asyncio.create_task(paginated.paginate(bot, channel, wait_time))
