import asyncio
import builtins
import contextlib
import datetime as dt
import html
import io
import logging
from typing import Any

import cairo
import discord
import gi
from discord.ext import commands

from tle import constants
from tle.util import (
    ansi,
    codeforces_api as cf,
    codeforces_common as cf_common,
    db,
    discord_common,
    events,
    oauth,
    paginator,
    table,
    tasks,
)
from tle.util.cache import ContestNotFound

gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo

_HANDLES_PER_PAGE = 15
_NAME_MAX_LEN = 20
_PAGINATE_WAIT_TIME = 5 * 60  # 5 minutes
_TOP_DELTAS_COUNT = 10
_MAX_RATING_CHANGES_PER_EMBED = 15
_UPDATE_HANDLE_STATUS_INTERVAL = 6 * 60 * 60  # 6 hours


class HandleCogError(commands.CommandError):
    pass


def rating_to_color(rating: int | str | None) -> tuple[int, int, int]:
    """returns (r, g, b) pixels values corresponding to rating"""
    # TODO: Integrate these colors with the ranks in codeforces_api.py
    BLACK = (10, 10, 10)
    RED = (255, 20, 20)
    BLUE = (0, 0, 200)
    GREEN = (0, 140, 0)
    ORANGE = (250, 140, 30)
    PURPLE = (160, 0, 120)
    CYAN = (0, 165, 170)
    GREY = (70, 70, 70)
    if rating is None or rating == 'N/A':
        return BLACK
    rating = int(rating)
    if rating < 1200:
        return GREY
    if rating < 1400:
        return GREEN
    if rating < 1600:
        return CYAN
    if rating < 1900:
        return BLUE
    if rating < 2100:
        return PURPLE
    if rating < 2400:
        return ORANGE
    return RED


FONTS = [
    'Noto Sans',
    'Noto Sans CJK JP',
    'Noto Sans CJK SC',
    'Noto Sans CJK TC',
    'Noto Sans CJK HK',
    'Noto Sans CJK KR',
]


def get_gudgitters_image(
    rankings: list[tuple[int, str, str, int | None, int]],
) -> discord.File:
    """return PIL image for rankings"""
    SMOKE_WHITE = (250, 250, 250)
    BLACK = (0, 0, 0)

    DISCORD_GRAY = (0.212, 0.244, 0.247)

    ROW_COLORS = ((0.95, 0.95, 0.95), (0.9, 0.9, 0.9))

    WIDTH = 900
    HEIGHT = 450
    BORDER_MARGIN = 20
    COLUMN_MARGIN = 10
    HEADER_SPACING = 1.25
    WIDTH_RANK = 0.08 * WIDTH
    WIDTH_NAME = 0.38 * WIDTH
    LINE_HEIGHT = (HEIGHT - 2 * BORDER_MARGIN) / (10 + HEADER_SPACING)

    # Cairo+Pango setup
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    context = cairo.Context(surface)
    context.set_line_width(1)
    context.set_source_rgb(*DISCORD_GRAY)
    context.rectangle(0, 0, WIDTH, HEIGHT)
    context.fill()
    layout = PangoCairo.create_layout(context)
    layout.set_font_description(
        Pango.font_description_from_string(','.join(FONTS) + ' 20')
    )
    layout.set_ellipsize(Pango.EllipsizeMode.END)

    def draw_bg(y: float, color_index: int) -> None:
        nxty = y + LINE_HEIGHT

        # Simple
        context.move_to(BORDER_MARGIN, y)
        context.line_to(WIDTH, y)
        context.line_to(WIDTH, nxty)
        context.line_to(0, nxty)
        context.set_source_rgb(*ROW_COLORS[color_index])
        context.fill()

    def draw_row(
        pos: str,
        username: str,
        handle: str,
        rating: str,
        color: tuple[int, int, int],
        y: float,
        bold: bool = False,
    ) -> None:
        context.set_source_rgb(*[x / 255.0 for x in color])

        context.move_to(BORDER_MARGIN, y)

        def draw(text: str, width: float = -1) -> None:
            text = html.escape(text)
            if bold:
                text = f'<b>{text}</b>'
            layout.set_width((width - COLUMN_MARGIN) * 1000)  # pixel = 1000 pango units
            layout.set_markup(text, -1)
            PangoCairo.show_layout(context, layout)
            context.rel_move_to(width, 0)

        draw(pos, WIDTH_RANK)
        draw(username, WIDTH_NAME)
        draw(handle, WIDTH_NAME)
        draw(rating)

    #

    y: float = BORDER_MARGIN

    # draw header
    draw_row('#', 'Name', 'Handle', 'Points', SMOKE_WHITE, y, bold=True)
    y += LINE_HEIGHT * HEADER_SPACING

    for i, (pos, name, handle, rating, score) in enumerate(rankings):
        color = rating_to_color(rating)
        draw_bg(y, i % 2)
        draw_row(
            str(pos),
            f'{name} ({rating if rating else "N/A"})',
            handle,
            str(score),
            color,
            y,
        )
        if rating and rating >= 3000:  # nutella
            draw_row('', name[0], handle[0], '', BLACK, y)
        y += LINE_HEIGHT

    image_data = io.BytesIO()
    surface.write_to_png(image_data)
    image_data.seek(0)
    discord_file = discord.File(image_data, filename='gudgitters.png')
    return discord_file


def _make_profile_embed(
    member: discord.Member, user: cf.User, *, mode: str
) -> discord.Embed:
    assert mode in ('set', 'get')
    if mode == 'set':
        desc = (
            f'Handle for {member.mention} successfully set to'
            f' **[{user.handle}]({user.url})**'
        )
    else:
        desc = (
            f'Handle for {member.mention} is currently set to'
            f' **[{user.handle}]({user.url})**'
        )
    if user.rating is None:
        embed = discord.Embed(description=desc)
        embed.add_field(name='Rating', value='Unrated', inline=True)
    else:
        embed = discord.Embed(description=desc, color=user.rank.color_embed)
        embed.add_field(name='Rating', value=user.rating, inline=True)
        embed.add_field(name='Rank', value=user.rank.title, inline=True)
    embed.set_thumbnail(url=f'{user.titlePhoto}')
    return embed


def _make_pages(
    users: list[tuple[discord.Member, str, int | None]], title: str
) -> list[tuple[str, discord.Embed]]:
    chunks = paginator.chunkify(users, _HANDLES_PER_PAGE)
    pages = []
    done = 0

    style = table.Style('{:>}  {:<}  {:<}  {:<}')
    for chunk in chunks:
        t = table.Table(style)
        t += table.Header('#', 'Name', 'Handle', 'Rating')
        t += table.Line()
        for i, (member, handle, rating) in enumerate(chunk):
            name = member.display_name
            if len(name) > _NAME_MAX_LEN:
                name = name[: _NAME_MAX_LEN - 1] + '…'
            rank = cf.rating2rank(rating)
            rating_str = 'N/A' if rating is None else str(rating)
            colors = ansi.make_cell_colors(rank, ncols=4, handle_col=2)
            t += table.Data(
                i + done,
                name,
                handle,
                f'{rating_str} ({rank.title_abbr})',
                colors=colors,
            )
        table_str = '```ansi\n' + str(t) + '\n```'
        embed = discord_common.cf_color_embed(description=table_str)
        pages.append((title, embed))
        done += len(chunk)
    return pages


class Handles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot: commands.Bot = bot
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.converter: commands.MemberConverter = commands.MemberConverter()

    @commands.Cog.listener()
    @discord_common.once
    async def on_ready(self) -> None:
        self.bot.event_sys.add_listener(self._on_rating_changes)
        assert isinstance(self._set_ex_users_inactive_task, tasks.Task)
        self._set_ex_users_inactive_task.start()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self.bot.user_db.set_inactive([(member.guild.id, member.id)])

    @commands.hybrid_command(brief='update status, mark guild members as active')
    @commands.has_role(constants.TLE_ADMIN)
    async def _updatestatus(self, ctx: commands.Context) -> None:
        gid = ctx.guild.id
        active_ids = [m.id for m in ctx.guild.members]
        await self.bot.user_db.reset_status(gid)
        rc = 0
        for chunk in paginator.chunkify(active_ids, 100):
            rc += await self.bot.user_db.update_status(gid, chunk)
        await ctx.send(f'{rc} members active with handle')

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        rc = await self.bot.user_db.update_status(member.guild.id, [member.id])
        if rc == 1:
            handle = await self.bot.user_db.get_handle(member.id, member.guild.id)
            await self._update_ranks(member.guild, [(int(member.id), handle)])

    @tasks.task_spec(
        name='SetExUsersInactive',
        waiter=tasks.Waiter.fixed_delay(_UPDATE_HANDLE_STATUS_INTERVAL),
    )
    async def _set_ex_users_inactive_task(self, _: Any) -> None:
        # To set users inactive in case the bot was dead when they left.
        to_set_inactive = []
        for guild in self.bot.guilds:
            user_id_handle_pairs = await self.bot.user_db.get_handles_for_guild(
                guild.id
            )
            to_set_inactive += [
                (guild.id, user_id)
                for user_id, _ in user_id_handle_pairs
                if guild.get_member(user_id) is None
            ]
        await self.bot.user_db.set_inactive(to_set_inactive)

    @events.listener_spec(
        name='RatingChangesListener',
        event_cls=events.RatingChangesUpdate,
        with_lock=True,
    )
    async def _on_rating_changes(self, event: events.RatingChangesUpdate) -> None:
        contest, changes = event.contest, event.rating_changes
        change_by_handle = {change.handle: change for change in changes}

        async def update_for_guild(guild: discord.Guild) -> None:
            if await self.bot.user_db.has_auto_role_update_enabled(guild.id):
                with contextlib.suppress(HandleCogError):
                    await self._update_ranks_all(guild)
            channel_id = await self.bot.user_db.get_rankup_channel(guild.id)
            channel = guild.get_channel(channel_id)
            if channel is not None:
                with contextlib.suppress(HandleCogError):
                    embeds = await self._make_rankup_embeds(
                        guild, contest, change_by_handle
                    )
                    for embed in embeds:
                        await channel.send(embed=embed)

        await asyncio.gather(
            *(update_for_guild(guild) for guild in self.bot.guilds),
            return_exceptions=True,
        )
        self.logger.info(f'All guilds updated for contest {contest.id}.')

    @commands.hybrid_group(
        brief='Commands that have to do with handles', fallback='show'
    )
    async def handle(self, ctx: commands.Context) -> None:
        """Change or collect information about specific handles on Codeforces"""
        await ctx.send_help(ctx.command)

    async def maybe_add_trusted_role(self, member: discord.Member) -> None:
        """Add trusted role for eligible users.

        Condition: `member` has been 1900+ for any amount of time before o1 release.
        """
        handle = await self.bot.user_db.get_handle(member.id, member.guild.id)
        if not handle:
            self.logger.warning(
                'WARN: handle not found in guild'
                f' {member.guild.name} ({member.guild.id})'
            )
            return
        trusted_role = discord.utils.get(member.guild.roles, name=constants.TLE_TRUSTED)
        if not trusted_role:
            self.logger.warning(
                "WARN: 'Trusted' role not found in guild"
                f' {member.guild.name} ({member.guild.id})'
            )
            return

        if trusted_role not in member.roles:
            # o1 released sept 12 2024
            cutoff_timestamp = dt.datetime(
                2024, 9, 11, tzinfo=dt.timezone.utc
            ).timestamp()
            try:
                rating_changes = await cf.user.rating(handle=handle)
            except cf.HandleNotFoundError:
                # User rating info not found via API, ignore for trusted check
                self.logger.info(
                    'INFO: Rating history not found for'
                    f' handle {handle} during trusted check.'
                )
                return
            except cf.CodeforcesApiError as e:
                # Log API errors appropriately in a real scenario
                self.logger.warning(
                    f'WARN: API Error fetching rating for {handle}'
                    f' during trusted check: {e}'
                )
                return

            if any(
                change.newRating >= 1900
                and change.ratingUpdateTimeSeconds < cutoff_timestamp
                for change in rating_changes
            ):
                try:
                    await member.add_roles(
                        trusted_role, reason='Historical rating >= 1900 before Aug 2024'
                    )
                except discord.Forbidden:
                    self.logger.warning(
                        f'WARN: Missing permissions to add Trusted role to'
                        f' {member.display_name} in {member.guild.name}'
                    )
                except discord.HTTPException as e:
                    self.logger.warning(
                        f'WARN: Failed to add Trusted role to'
                        f' {member.display_name} in {member.guild.name}: {e}'
                    )

    async def update_member_rank_role(
        self,
        member: discord.Member,
        role_to_assign: discord.Role | None,
        *,
        reason: str,
    ) -> None:
        """Sets the `member` to only have the rank role of `role_to_assign`.

        All other rank roles on the member, if any, will be removed. If
        `role_to_assign` is None all existing rank roles on the member will be
        removed.
        """
        role_names_to_remove = {rank.title for rank in cf.RATED_RANKS}
        should_remove_purgatory = False
        if role_to_assign is not None:
            role_names_to_remove.discard(role_to_assign.name)
            if role_to_assign.name not in ['Newbie', 'Pupil', 'Specialist', 'Expert']:
                should_remove_purgatory = True
                await self.maybe_add_trusted_role(member)
        to_remove = [role for role in member.roles if role.name in role_names_to_remove]
        if should_remove_purgatory and discord_common.has_role(
            member, constants.TLE_PURGATORY
        ):
            purg_role = discord_common.get_role(member.guild, constants.TLE_PURGATORY)
            if purg_role:
                to_remove.append(purg_role)
        if to_remove:
            await member.remove_roles(*to_remove, reason=reason)
        if role_to_assign is not None and role_to_assign not in member.roles:
            await member.add_roles(role_to_assign, reason=reason)

    @handle.command(brief='Set Codeforces handle of a user', aliases=['link'])
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def set(
        self, ctx: commands.Context, member: discord.Member, handle: str
    ) -> None:
        """Set Codeforces handle of a user."""
        # CF API returns correct handle ignoring case, update to it
        (user,) = await cf.user.info(handles=[handle])
        await self._set(ctx, member, user)
        embed = _make_profile_embed(member, user, mode='set')
        await ctx.send(embed=embed)

    async def _set_from_oauth(
        self, guild: discord.Guild, member: discord.Member, user: cf.User
    ) -> None:
        handle = user.handle
        try:
            await self.bot.user_db.set_handle(member.id, guild.id, handle)
        except db.UniqueConstraintFailed:
            raise HandleCogError(
                f'When setting handle for {member}: '
                f'The handle `{handle}` is already associated with another user.'
            )
        await self.bot.user_db.cache_cf_user(user)

        if user.rank == cf.UNRATED_RANK:
            role_to_assign = None
        else:
            roles = [role for role in guild.roles if role.name == user.rank.title]
            if not roles:
                raise HandleCogError(
                    f'Role for rank `{user.rank.title}` not present in the server'
                )
            role_to_assign = roles[0]
        await self.update_member_rank_role(
            member, role_to_assign, reason='New handle set for user'
        )

    async def _set(
        self, ctx: commands.Context, member: discord.Member, user: cf.User
    ) -> None:
        await self._set_from_oauth(ctx.guild, member, user)

    @handle.command(brief='Identify yourself')
    async def identify(self, ctx: commands.Context) -> None:
        """Link your Codeforces account via OAuth.

        Opens a Codeforces authorization link so you can verify your handle.
        """
        if not constants.OAUTH_CONFIGURED:
            raise HandleCogError(
                'OAuth is not configured. An admin must set'
                ' OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, and OAUTH_REDIRECT_URI.'
            )

        if await self.bot.user_db.get_handle(ctx.author.id, ctx.guild.id):
            raise HandleCogError(
                f'{ctx.author.mention}, you cannot identify when your handle'
                ' is already set. Ask an Admin or Moderator if you wish to change it'
            )

        self.bot.oauth_state_store.revoke(ctx.author.id)

        state = self.bot.oauth_state_store.create(
            ctx.author.id, ctx.guild.id, ctx.channel.id
        )
        assert constants.OAUTH_CLIENT_ID is not None
        assert constants.OAUTH_REDIRECT_URI is not None
        auth_url = oauth.build_auth_url(
            constants.OAUTH_CLIENT_ID, constants.OAUTH_REDIRECT_URI, state
        )

        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label='Link Codeforces Account',
                url=auth_url,
            )
        )
        msg = (
            'Click the button below to link your Codeforces account.'
            ' The link expires in 5 minutes.'
        )
        if ctx.interaction:
            await ctx.send(msg, view=view, ephemeral=True)
        else:
            try:
                await ctx.author.send(msg, view=view)
                await ctx.send('Check your DMs for the link!')
            except discord.Forbidden:
                self.bot.oauth_state_store.revoke(ctx.author.id)
                await ctx.send(
                    f'{ctx.author.mention}, I could not DM you.'
                    ' Please enable DMs from server members'
                    ' and try again, or use the'
                    ' /handle identify slash command instead.'
                )

    @handle.command(brief='Get handle by Discord username')
    async def get(self, ctx: commands.Context, member: discord.Member) -> None:
        """Show Codeforces handle of a user."""
        handle = await self.bot.user_db.get_handle(member.id, ctx.guild.id)
        if not handle:
            raise HandleCogError(f'Handle for {member.mention} not found in database')
        user = await self.bot.user_db.fetch_cf_user(handle)
        embed = _make_profile_embed(member, user, mode='get')
        await ctx.send(embed=embed)

    @handle.command(brief='Get Discord username by cf handle')
    async def rget(self, ctx: commands.Context, handle: str) -> None:
        """Show Discord username of a cf handle."""
        user_id = await self.bot.user_db.get_user_id(handle, ctx.guild.id)
        if not user_id:
            raise HandleCogError(
                f'Discord username for `{handle}` not found in database'
            )
        user = await self.bot.user_db.fetch_cf_user(handle)
        member = ctx.guild.get_member(user_id)
        if member is None:
            raise HandleCogError(f'{user_id} not found in the guild')
        embed = _make_profile_embed(member, user, mode='get')
        await ctx.send(embed=embed)

    @handle.command(brief='Unlink handle', aliases=['unlink'])
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def remove(self, ctx: commands.Context, handle: str) -> None:
        """Remove Codeforces handle of a user."""
        (handle,) = await cf_common.resolve_handles(ctx, self.converter, [handle])
        user_id = await self.bot.user_db.get_user_id(handle, ctx.guild.id)
        if user_id is None:
            raise HandleCogError(f'{handle} not found in database')

        await self.bot.user_db.remove_handle(handle, ctx.guild.id)
        member = ctx.guild.get_member(user_id)
        await self.update_member_rank_role(
            member, role_to_assign=None, reason='Handle unlinked'
        )
        embed = discord_common.embed_success(f'Removed {handle} from database')
        await ctx.send(embed=embed)

    @handle.command(brief="Resolve redirect of a user's handle")
    async def unmagic(self, ctx: commands.Context) -> None:
        """Updates handle of the calling user if they have changed handles
        (typically new year's magic)"""
        member = ctx.author
        handle = await self.bot.user_db.get_handle(member.id, ctx.guild.id)
        await self._unmagic_handles(ctx, [handle], {handle: member})

    @handle.command(brief='Resolve handles needing redirection')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def unmagic_all(self, ctx: commands.Context) -> None:
        """Updates handles of all users that have changed handles
        (typically new year's magic)"""
        user_id_and_handles = await self.bot.user_db.get_handles_for_guild(ctx.guild.id)

        handles = []
        rev_lookup = {}
        for user_id, handle in user_id_and_handles:
            member = ctx.guild.get_member(user_id)
            handles.append(handle)
            rev_lookup[handle] = member
        await self._unmagic_handles(ctx, handles, rev_lookup)

    @handle.command(
        brief='Show handle resolution for the given handles',
        with_app_command=False,
    )
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def unmagic_debug(self, ctx: commands.Context, *args: str) -> None:
        """See what the resolve logic would do."""
        handles = list(args)
        skip_filter = False
        if '+skip_filter' in handles:
            handles.remove('+skip_filter')
            skip_filter = True
        handle_cf_user_mapping = await cf.resolve_redirects(handles, skip_filter)

        lines = ['Resolved handles:']
        for handle, cf_user in handle_cf_user_mapping.items():
            if cf_user:
                lines.append(f'{handle} -> {cf_user.handle}')
            else:
                lines.append(f'{handle} -> None')
        await ctx.send(embed=discord_common.embed_success('\n'.join(lines)))

    async def _unmagic_handles(
        self,
        ctx: commands.Context,
        handles: list[str],
        rev_lookup: dict[str, discord.Member | None],
    ) -> None:
        handle_cf_user_mapping = await cf.resolve_redirects(handles)
        mapping: dict[tuple[discord.Member | None, str], cf.User | None] = {
            (rev_lookup[handle], handle): cf_user
            for handle, cf_user in handle_cf_user_mapping.items()
        }
        summary_embed = await self._fix_and_report(ctx, mapping)
        await ctx.send(embed=summary_embed)

    async def _fix_and_report(
        self,
        ctx: commands.Context,
        redirections: dict[tuple[discord.Member | None, str], cf.User | None],
    ) -> discord.Embed:
        fixed = []
        failed = []
        for (member, handle), cf_user in redirections.items():
            if not cf_user:
                failed.append(handle)
            else:
                await self._set(ctx, member, cf_user)
                fixed.append((handle, cf_user.handle))

        # Return summary embed
        lines = []
        if not fixed and not failed:
            return discord_common.embed_success('No handles updated')
        if fixed:
            lines.append('**Fixed**')
            lines += (f'{old} -> {new}' for old, new in fixed)
        if failed:
            lines.append('**Failed**')
            lines += failed
        return discord_common.embed_success('\n'.join(lines))

    @commands.hybrid_command(brief='Show gudgitters', aliases=['gitgudders'])
    async def gudgitters(self, ctx: commands.Context) -> None:
        """Show the list of users of gitgud with their scores."""
        res = await self.bot.user_db.get_gudgitters()
        res.sort(key=lambda r: r[1], reverse=True)

        rankings = []
        index = 0
        for user_id, score in res:
            member = ctx.guild.get_member(int(user_id))
            if member is None:
                continue
            if score > 0:
                handle = await self.bot.user_db.get_handle(user_id, ctx.guild.id)
                user = await self.bot.user_db.fetch_cf_user(handle)
                if user is None:
                    continue
                discord_handle = member.display_name
                rating = user.rating
                rankings.append((index, discord_handle, handle, rating, score))
                index += 1
            if index == 10:
                break

        if not rankings:
            raise HandleCogError(
                'No one has completed a gitgud challenge,'
                ' send ;gitgud to request and ;gotgud to mark it as complete'
            )
        discord_file = get_gudgitters_image(rankings)
        await ctx.send(file=discord_file)

    @handle.command(brief='Show all handles', with_app_command=False)
    async def list(self, ctx: commands.Context, *countries: str) -> None:
        """Shows members of the server who have registered their handles and
        their Codeforces ratings. You can additionally specify a list of countries
        if you wish to display only members from those countries. Country data is
        sourced from codeforces profiles. e.g. ;handle list Croatia Slovenia
        """
        country_list = [country.title() for country in countries]
        res = await self.bot.user_db.get_cf_users_for_guild(ctx.guild.id)
        users = [
            (ctx.guild.get_member(user_id), cf_user.handle, cf_user.rating)
            for user_id, cf_user in res
            if not country_list or cf_user.country in country_list
        ]
        users = [
            (member, handle, rating)
            for member, handle, rating in users
            if member is not None
        ]
        if not users:
            raise HandleCogError('No members with registered handles.')

        users.sort(
            key=lambda x: (1 if x[2] is None else -x[2], x[1])
        )  # Sorting by (-rating, handle)
        title = 'Handles of server members'
        if country_list:
            title += ' from ' + ', '.join(f'`{country}`' for country in country_list)
        pages = _make_pages(users, title)
        await paginator.paginate(
            ctx.channel,
            pages,
            wait_time=_PAGINATE_WAIT_TIME,
            set_pagenum_footers=True,
            ctx=ctx,
        )

    async def _update_ranks_all(self, guild: discord.Guild) -> None:
        """For each member in the guild, fetches their current ratings and
        updates their role if required.
        """
        res = await self.bot.user_db.get_handles_for_guild(guild.id)
        await self._update_ranks(guild, res)

    async def _update_ranks(
        self, guild: discord.Guild, res: builtins.list[tuple[int, str]]
    ) -> None:
        member_handles = [
            (guild.get_member(user_id), handle) for user_id, handle in res
        ]
        member_handles = [
            (member, handle) for member, handle in member_handles if member is not None
        ]
        if not member_handles:
            raise HandleCogError('Handles not set for any user')
        members, handles = zip(*member_handles, strict=False)
        users = await cf.user.info(handles=handles)
        for user in users:
            await self.bot.user_db.cache_cf_user(user)

        required_roles = {
            user.rank.title for user in users if user.rank != cf.UNRATED_RANK
        }
        rank2role = {
            role.name: role for role in guild.roles if role.name in required_roles
        }
        missing_roles = required_roles - rank2role.keys()
        if missing_roles:
            roles_str = ', '.join(f'`{role}`' for role in missing_roles)
            plural = 's' if len(missing_roles) > 1 else ''
            raise HandleCogError(
                f'Role{plural} for rank{plural} {roles_str} not present in the server'
            )

        for member, user in zip(members, users, strict=False):
            role_to_assign = (
                None if user.rank == cf.UNRATED_RANK else rank2role[user.rank.title]
            )
            await self.update_member_rank_role(
                member, role_to_assign, reason='Codeforces rank update'
            )

    async def _make_rankup_embeds(
        self,
        guild: discord.Guild,
        contest: cf.Contest,
        change_by_handle: dict[str, cf.RatingChange],
    ) -> builtins.list[discord.Embed]:
        """Make an embed containing a list of rank changes and top rating
        increases for the members of this guild.
        """
        user_id_handle_pairs = await self.bot.user_db.get_handles_for_guild(guild.id)
        member_handle_pairs = [
            (guild.get_member(user_id), handle)
            for user_id, handle in user_id_handle_pairs
        ]

        def ispurg(member: discord.Member) -> bool:
            return discord_common.has_role(member, constants.TLE_PURGATORY)

        member_change_pairs = [
            (member, change_by_handle[handle])
            for member, handle in member_handle_pairs
            if member is not None and handle in change_by_handle and not ispurg(member)
        ]
        if not member_change_pairs:
            raise HandleCogError(
                f'Contest `{contest.id} | {contest.name}`'
                ' was not rated for any member of this server.'
            )

        member_change_pairs.sort(key=lambda pair: pair[1].newRating, reverse=True)
        rank_to_role = {role.name: role for role in guild.roles}

        def rating_to_displayable_rank(rating: int) -> str:
            rank = cf.rating2rank(rating).title
            role = rank_to_role.get(rank)
            return role.mention if role else rank

        rank_changes_str = []
        for member, change in member_change_pairs:
            cache = self.bot.cf_cache.rating_changes_cache
            if (
                change.oldRating == 1500
                and len(await cache.get_rating_changes_for_handle(change.handle)) == 1
            ):
                # If this is the user's first rated contest.
                old_role = 'Unrated'
            else:
                old_role = rating_to_displayable_rank(change.oldRating)
            new_role = rating_to_displayable_rank(change.newRating)
            if new_role != old_role:
                rank_change_str = (
                    f'{member.mention}'
                    f' [{change.handle}]({cf.PROFILE_BASE_URL}{change.handle}):'
                    f' {old_role} \N{LONG RIGHTWARDS ARROW} {new_role}'
                )
                rank_changes_str.append(rank_change_str)

        member_change_pairs.sort(
            key=lambda pair: pair[1].newRating - pair[1].oldRating, reverse=True
        )
        top_increases_str = []
        for member, change in member_change_pairs[:_TOP_DELTAS_COUNT]:
            delta = change.newRating - change.oldRating
            if delta <= 0:
                break
            increase_str = (
                f'{member.mention}'
                f' [{change.handle}]({cf.PROFILE_BASE_URL}{change.handle}):'
                f' {change.oldRating} \N{HORIZONTAL BAR} **{delta:+}**'
                f' \N{LONG RIGHTWARDS ARROW} {change.newRating}'
            )
            top_increases_str.append(increase_str)

        rank_changes_str = rank_changes_str or ['No rank changes']

        embed_heading = discord.Embed(
            title=contest.name, url=contest.url, description=''
        )
        embed_heading.set_author(name='Rank updates')
        embeds = [embed_heading]

        for rank_changes_chunk in paginator.chunkify(
            rank_changes_str, _MAX_RATING_CHANGES_PER_EMBED
        ):
            desc = '\n'.join(rank_changes_chunk)
            embed = discord.Embed(description=desc)
            embeds.append(embed)

        top_rating_increases_embed = discord.Embed(
            description='\n'.join(top_increases_str) or 'Nobody got a positive delta :('
        )
        top_rating_increases_embed.set_author(name='Top rating increases')

        embeds.append(top_rating_increases_embed)
        discord_common.set_same_cf_color(embeds)

        return embeds

    @commands.hybrid_group(brief='Commands for role updates', fallback='show')
    async def roleupdate(self, ctx: commands.Context) -> None:
        """Group for commands involving role updates."""
        await ctx.send_help(ctx.command)

    @roleupdate.command(brief='Update Codeforces rank roles')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def now(self, ctx: commands.Context) -> None:
        """Updates Codeforces rank roles for every member in this server."""
        await self._update_ranks_all(ctx.guild)
        await ctx.send(
            embed=discord_common.embed_success('Roles updated successfully.')
        )

    @roleupdate.command(brief='Enable or disable auto role updates', usage='on|off')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def auto(self, ctx: commands.Context, arg: str) -> None:
        """Auto role update refers to automatic updating of rank roles when rating
        changes are released on Codeforces. 'on'/'off' disables or enables auto role
        updates.
        """
        if arg == 'on':
            rc = await self.bot.user_db.enable_auto_role_update(ctx.guild.id)
            if not rc:
                raise HandleCogError('Auto role update is already enabled.')
            await ctx.send(
                embed=discord_common.embed_success('Auto role updates enabled.')
            )
        elif arg == 'off':
            rc = await self.bot.user_db.disable_auto_role_update(ctx.guild.id)
            if not rc:
                raise HandleCogError('Auto role update is already disabled.')
            await ctx.send(
                embed=discord_common.embed_success('Auto role updates disabled.')
            )
        else:
            raise ValueError(f"arg must be 'on' or 'off', got '{arg}' instead.")

    @roleupdate.command(
        brief='Publish a rank update for the given contest', usage='here|off|contest_id'
    )
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def publish(self, ctx: commands.Context, arg: str) -> None:
        """This is a feature to publish a summary of rank changes and top rating
        increases in a particular contest for members of this server. 'here' will
        automatically publish the summary to this channel whenever rating changes on
        Codeforces are released. 'off' will disable auto publishing. Specifying a
        contest id will publish the summary immediately.
        """
        if arg == 'here':
            await self.bot.user_db.set_rankup_channel(ctx.guild.id, ctx.channel.id)
            await ctx.send(
                embed=discord_common.embed_success(
                    'Auto rank update publishing enabled.'
                )
            )
        elif arg == 'off':
            rc = await self.bot.user_db.clear_rankup_channel(ctx.guild.id)
            if not rc:
                raise HandleCogError('Rank update publishing is already disabled.')
            await ctx.send(
                embed=discord_common.embed_success('Rank update publishing disabled.')
            )
        else:
            try:
                contest_id = int(arg)
            except ValueError:
                raise ValueError(
                    f"arg must be 'here', 'off' or a contest ID, got '{arg}' instead."
                )
            await self._publish_now(ctx, contest_id)

    async def _publish_now(self, ctx: commands.Context, contest_id: int) -> None:
        try:
            contest = self.bot.cf_cache.contest_cache.get_contest(contest_id)
        except ContestNotFound as e:
            raise HandleCogError(f'Contest with id `{e.contest_id}` not found.')
        if contest.phase != 'FINISHED':
            raise HandleCogError(
                f'Contest `{contest_id} | {contest.name}` has not finished.'
            )
        try:
            changes = await cf.contest.ratingChanges(contest_id=contest_id)
        except cf.RatingChangesUnavailableError:
            changes = None
        if not changes:
            raise HandleCogError(
                'Rating changes are not available for contest'
                f' `{contest_id} | {contest.name}`.'
            )

        change_by_handle = {change.handle: change for change in changes}
        rankup_embeds = await self._make_rankup_embeds(
            ctx.guild, contest, change_by_handle
        )
        for rankup_embed in rankup_embeds:
            await ctx.channel.send(embed=rankup_embed)

    async def _generic_remind(
        self, ctx: commands.Context, action: str, role_name: str, what: str
    ) -> None:
        roles = [role for role in ctx.guild.roles if role.name == role_name]
        if not roles:
            raise HandleCogError(f'Role `{role_name}` not present in the server')
        role = roles[0]
        if action == 'give':
            if role in ctx.author.roles:
                await ctx.send(
                    embed=discord_common.embed_neutral(
                        f'You are already subscribed to {what} reminders'
                    )
                )
                return
            await ctx.author.add_roles(
                role, reason=f'User subscribed to {what} reminders'
            )
            await ctx.send(
                embed=discord_common.embed_success(
                    f'Successfully subscribed to {what} reminders'
                )
            )
        elif action == 'remove':
            if role not in ctx.author.roles:
                await ctx.send(
                    embed=discord_common.embed_neutral(
                        f'You are not subscribed to {what} reminders'
                    )
                )
                return
            await ctx.author.remove_roles(
                role, reason=f'User unsubscribed from {what} reminders'
            )
            await ctx.send(
                embed=discord_common.embed_success(
                    f'Successfully unsubscribed from {what} reminders'
                )
            )
        else:
            raise HandleCogError(f'Invalid action {action}')

    @commands.hybrid_command(
        brief='Grants or removes the specified pingable role',
        usage='[give/remove] [vc/duel]',
    )
    async def role(self, ctx: commands.Context, action: str, which: str) -> None:
        """e.g. ;role remove duel"""
        if which == 'vc':
            await self._generic_remind(ctx, action, 'Virtual Contestant', 'vc')
        elif which == 'duel':
            await self._generic_remind(ctx, action, 'Duelist', 'duel')
        else:
            raise HandleCogError(f'Invalid role {which}')

    @discord_common.send_error_if(HandleCogError, cf_common.HandleIsVjudgeError)
    async def cog_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        pass

    @handle.command(brief='Give the Trusted role to another user')
    @commands.has_any_role(
        constants.TLE_ADMIN, constants.TLE_MODERATOR, constants.TLE_TRUSTED
    )
    async def refer(self, ctx: commands.Context, target_user: discord.Member) -> None:
        """Allows Trusted users to grant the Trusted role to other users.

        The command fails if the target user has the Purgatory role.
        """
        guild = ctx.guild
        trusted_role_name = constants.TLE_TRUSTED
        purgatory_role_name = constants.TLE_PURGATORY

        if target_user == ctx.author:
            raise HandleCogError('You cannot refer yourself.')

        # Find the Purgatory role
        purgatory_role = discord_common.get_role(guild, purgatory_role_name)
        if purgatory_role is None:
            # This case might indicate a server setup issue, but we proceed as
            # if the user is not in purgatory
            self.logger.warning(
                f"Role '{purgatory_role_name}'"
                f' not found in guild {guild.name} ({guild.id}).'
            )
        elif purgatory_role in target_user.roles:
            await ctx.send(
                embed=discord_common.embed_alert(
                    f'Cannot grant Trusted role to {target_user.mention}.'
                    f' User is currently in Purgatory.'
                )
            )
            return

        # Find the Trusted role
        trusted_role = discord_common.get_role(guild, trusted_role_name)
        if trusted_role is None:
            raise HandleCogError(
                f"The role '{trusted_role_name}' does not exist in this server."
            )

        # Check if target user already has the role
        if trusted_role in target_user.roles:
            await ctx.send(
                embed=discord_common.embed_neutral(
                    f'{target_user.mention} already has the Trusted role.'
                )
            )
            return

        # Grant the Trusted role
        try:
            await target_user.add_roles(
                trusted_role, reason=f'Referred by {ctx.author.name} ({ctx.author.id})'
            )
            await ctx.send(
                f'Trusted role granted to {target_user.mention}'
                f' by {ctx.author.mention}.'
            )
        except discord.Forbidden:
            raise HandleCogError(
                f"No permissions to assign the '{trusted_role_name}' role."
            )
        except discord.HTTPException as e:
            raise HandleCogError(
                f'Failed to assign the role due to an unexpected error: {e}'
            )

    @handle.command(brief='Grant Trusted role to old members without Purgatory role.')
    @commands.has_role(constants.TLE_ADMIN)
    async def grandfather(self, ctx: commands.Context) -> None:
        """Grants the Trusted role to all members who joined before April 21, 2025,
        and do not currently have the Purgatory role. April 20 was o3's first contest.
        """
        guild = ctx.guild
        trusted_role_name = constants.TLE_TRUSTED
        purgatory_role_name = constants.TLE_PURGATORY

        trusted_role = discord_common.get_role(guild, trusted_role_name)
        if trusted_role is None:
            raise HandleCogError(
                f"The role '{trusted_role_name}' does not exist in this server."
            )

        purgatory_role = discord_common.get_role(guild, purgatory_role_name)
        # If Purgatory role doesn't exist, we assume no one has it.
        if purgatory_role is None:
            self.logger.warning(
                f"Role '{purgatory_role_name}'"
                f' not found in guild {guild.name} ({guild.id}).'
                f' Proceeding without Purgatory check.'
            )

        # The date when this code was added.
        # April 20 was o3's first contest.
        cutoff_date = dt.datetime(2025, 4, 21, 0, 0, 0, tzinfo=dt.timezone.utc)

        added_count = 0
        skipped_purgatory = 0
        skipped_already_trusted = 0
        skipped_join_date = 0
        processed_count = 0
        http_failure_count = 0

        status_message = await ctx.send(
            'Processing members for grandfathering Trusted...'
        )

        # Create a list to avoid issues if members leave/join during processing
        members_to_process = list(guild.members)

        for i, member in enumerate(members_to_process):
            processed_count += 1
            if i % 100 == 0 and i > 0:
                await status_message.edit(
                    content=f'Processing members... ({i}/{len(members_to_process)})'
                )

            if purgatory_role is not None and purgatory_role in member.roles:
                # User has purgatory role so is not eligible, skip
                skipped_purgatory += 1
                continue

            if member.joined_at is None:
                # Cannot determine join date, skip
                skipped_join_date += 1
                continue

            # Make member.joined_at timezone-aware
            # (assuming it's UTC, which discord.py uses)
            member_joined_at_aware = member.joined_at.replace(tzinfo=dt.timezone.utc)

            if member_joined_at_aware >= cutoff_date:
                # User joined too late to be eligible, skip
                skipped_join_date += 1
                continue

            if trusted_role in member.roles:
                # User already trusted, skip
                skipped_already_trusted += 1
                continue

            # Eligible for Trusted role, try to grant it
            try:
                await member.add_roles(
                    trusted_role,
                    reason='Grandfather clause: Joined before 2025-04-21 and not in Purgatory',  # noqa: E501
                )
                added_count += 1
                # Short delay to avoid hitting rate limits on large servers
                await asyncio.sleep(0.1)
            except discord.Forbidden:
                await ctx.send(
                    embed=discord_common.embed_alert(
                        f"Missing permissions to assign the '{trusted_role_name}'"
                        f' role to {member.mention}. Stopping.'
                    )
                )
                return  # Stop processing if permissions are missing
            except discord.HTTPException as e:
                self.logger.warning(
                    f'Failed to assign {trusted_role_name} role to'
                    f' {member.display_name} ({member.id}): {e}'
                )
                http_failure_count += 1

        summary_message = (
            f'Grandfathering complete.\n'
            f'- Processed: {processed_count} members\n'
            f'- Granted Trusted: {added_count} members\n'
            f'- Skipped (Joined after cutoff): {skipped_join_date}\n'
            f'- Skipped (Already Trusted): {skipped_already_trusted}\n'
            f'- HTTP failure granting role: {http_failure_count}\n'
        )
        if purgatory_role:
            summary_message += f'- Skipped (Has Purgatory): {skipped_purgatory}\n'

        await status_message.edit(content=summary_message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Handles(bot))
