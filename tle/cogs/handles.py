import io
import asyncio
import logging

import discord
import random
from discord.ext import commands

from tle.util import cache_system2
from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common
from tle.util import events
from tle.util import paginator
from tle.util import table
from tle import constants

from PIL import Image, ImageFont, ImageDraw

_HANDLES_PER_PAGE = 15
_NAME_MAX_LEN = 20
_PAGINATE_WAIT_TIME = 5 * 60  # 5 minutes
_TOP_DELTAS_SHOW_COUNT = 5


class HandleCogError(commands.CommandError):
    pass


def rating_to_color(rating):
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


def get_prettyhandles_image(rankings, font):
    """return PIL image for rankings"""
    SMOKE_WHITE = (250, 250, 250)
    BLACK = (0, 0, 0)
    img = Image.new('RGB', (900, 450), color=SMOKE_WHITE)
    draw = ImageDraw.Draw(img)

    START_X, START_Y = 20, 20
    Y_INC = 32
    WIDTH_RANK = 64
    WIDTH_NAME = 340

    def draw_row(pos, username, handle, rating, color, y):
        x = START_X
        draw.text((x, y), pos, fill=color, font=font)
        x += WIDTH_RANK
        draw.text((x, y), username, fill=color, font=font)
        x += WIDTH_NAME
        draw.text((x, y), handle, fill=color, font=font)
        x += WIDTH_NAME
        draw.text((x, y), rating, fill=color, font=font)

    y = START_Y
    # draw header
    draw_row('#', 'Username', 'Handle', 'Rating', BLACK, y)
    y += int(Y_INC * 1.5)

    # trim name to fit in the column width
    def _trim(name):
        width = WIDTH_NAME - 10
        while font.getsize(name)[0] > width:
            name = name[:-4] + '...'  # "…" is printed as floating dots
        return name

    for pos, name, handle, rating in rankings:
        name = _trim(name)
        handle = _trim(handle)
        color = rating_to_color(rating)
        draw_row(str(pos), name, handle, str(rating), color, y)
        if rating != 'N/A' and rating >= 3000:  # nutella
            nutella_x = START_X + WIDTH_RANK
            draw.text((nutella_x, y), name[0], fill=BLACK, font=font)
            nutella_x += WIDTH_NAME
            draw.text((nutella_x, y), handle[0], fill=BLACK, font=font)
        y += Y_INC

    return img


def _make_profile_embed(member, user, *, mode):
    assert mode in ('set', 'get')
    if mode == 'set':
        desc = f'Handle for {member.mention} successfully set to **[{user.handle}]({user.url})**'
    else:
        desc = f'Handle for {member.mention} is currently set to **[{user.handle}]({user.url})**'
    if user.rating is None:
        embed = discord.Embed(description=desc)
        embed.add_field(name='Rating', value='Unrated', inline=True)
    else:
        embed = discord.Embed(description=desc, color=user.rank.color_embed)
        embed.add_field(name='Rating', value=user.rating, inline=True)
        embed.add_field(name='Rank', value=user.rank.title, inline=True)
    embed.set_thumbnail(url=f'https:{user.titlePhoto}')
    return embed


def _make_pages(users):
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
                name = name[:_NAME_MAX_LEN - 1] + '…'
            rank = cf.rating2rank(rating)
            rating_str = 'N/A' if rating is None else str(rating)
            t += table.Data(i + done, name, handle, f'{rating_str} ({rank.title_abbr})')
        table_str = '```\n'+str(t)+'\n```'
        embed = discord_common.cf_color_embed(description=table_str)
        pages.append(('Handles of server members', embed))
        done += len(chunk)
    return pages


class Handles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        self.font = ImageFont.truetype(constants.NOTO_SANS_CJK_BOLD_FONT_PATH, size=26) # font for ;handle pretty

    @commands.Cog.listener()
    async def on_ready(self):
        cf_common.event_sys.add_listener(self._on_rating_changes)

    @events.listener_spec(name='RatingChangesListener',
                          event_cls=events.RatingChangesUpdate,
                          with_lock=True)
    async def _on_rating_changes(self, event):
        contest, changes = event.contest, event.rating_changes
        change_by_handle = {change.handle: change for change in changes}

        async def rank_update_for_guild(guild):
            channel_id = cf_common.user_db.get_rankup_channel(guild.id)
            channel = guild.get_channel(channel_id)
            if channel is None:
                return
            try:
                await self._update_ranks(guild)
                embed = self._make_rankup_embed(guild, contest, change_by_handle)
                await channel.send(embed=embed.set_footer(text='Roles updated!'))
            except HandleCogError:
                pass

        await asyncio.gather(*(rank_update_for_guild(guild) for guild in self.bot.guilds),
                             return_exceptions=True)
        self.logger.info(f'Roles updated for all guilds for contest {contest.id}.')

    @commands.group(brief='Commands that have to do with handles', invoke_without_command=True)
    async def handle(self, ctx):
        """Change or collect information about specific handles on Codeforces"""
        await ctx.send_help(ctx.command)

    @staticmethod
    async def update_member_rank_role(member, role_to_assign, *, reason):
        """Sets the `member` to only have the rank role of `role_to_assign`. All other rank roles
        on the member, if any, will be removed. If `role_to_assign` is None all existing rank roles
        on the member will be removed.
        """
        role_names_to_remove = {rank.title for rank in cf.RATED_RANKS}
        if role_to_assign is not None:
            role_names_to_remove.discard(role_to_assign.name)
            if role_to_assign.name not in ['Newbie', 'Pupil', 'Specialist', 'Expert']:
                role_names_to_remove.add('Purgatory')
        to_remove = [role for role in member.roles if role.name in role_names_to_remove]
        if to_remove:
            await member.remove_roles(*to_remove, reason=reason)
        if role_to_assign is not None and role_to_assign not in member.roles:
            await member.add_roles(role_to_assign, reason=reason)

    @handle.command(brief='Set Codeforces handle of a user')
    @commands.has_role('Admin')
    async def set(self, ctx, member: discord.Member, handle: str):
        """Set Codeforces handle of a user."""
        # CF API returns correct handle ignoring case, update to it
        users = await cf.user.info(handles=[handle])
        await self._set(ctx, member, users[0])

    async def _set(self, ctx, member, user):
        handle = user.handle
        cf_common.user_db.cache_cfuser(user)
        cf_common.user_db.sethandle(member.id, handle)

        if user.rank == cf.UNRATED_RANK:
            role_to_assign = None
        else:
            roles = [role for role in ctx.guild.roles if role.name == user.rank.title]
            if not roles:
                raise HandleCogError(f'Role for rank `{user.rank.title}` not present in the server')
            role_to_assign = roles[0]
        await self.update_member_rank_role(member, role_to_assign,
                                           reason='New handle set for user')
        embed = _make_profile_embed(member, user, mode='set')
        await ctx.send(embed=embed)

    @handle.command(brief='Identify yourself', usage='[handle]')
    @cf_common.user_guard(group='handle',
                          get_exception=lambda: HandleCogError('Identification is already running for you'))
    async def identify(self, ctx, handle: str):
        """Link a codeforces account to discord account by submitting a compile error to a random problem"""
        users = await cf.user.info(handles=[handle])
        invoker = str(ctx.author)
        handle = users[0].handle
        problems = [prob for prob in cf_common.cache2.problem_cache.problems
                    if prob.rating <= 1200]
        problem = random.choice(problems)
        await ctx.send(f'`{invoker}`, submit a compile error to <{problem.url}> within 60 seconds')
        await asyncio.sleep(60)

        subs = await cf.user.status(handle=handle, count=5)
        if any(sub.problem.name == problem.name and sub.verdict == 'COMPILATION_ERROR' for sub in subs):
            users = await cf.user.info(handles=[handle])
            await self._set(ctx, ctx.author, users[0])
        else:
            await ctx.send(f'Sorry `{invoker}`, can you try again?')

    @handle.command(brief='Get handle by Discord username')
    async def get(self, ctx, member: discord.Member):
        """Show Codeforces handle of a user."""
        handle = cf_common.user_db.gethandle(member.id)
        if not handle:
            raise HandleCogError(f'Handle for {member.mention} not found in database')
        user = cf_common.user_db.fetch_cfuser(handle)
        embed = _make_profile_embed(member, user, mode='get')
        await ctx.send(embed=embed)

    @handle.command(brief='Remove handle for a user')
    @commands.has_role('Admin')
    async def remove(self, ctx, member: discord.Member):
        """Remove Codeforces handle of a user."""
        rc = cf_common.user_db.removehandle(member.id)
        if not rc:
            raise HandleCogError(f'Handle for {member.mention} not found in database')
        await self.update_member_rank_role(member, role_to_assign=None,
                                           reason='Handle removed for user')
        embed = discord_common.embed_success(f'Removed handle for {member.mention}')
        await ctx.send(embed=embed)

    @commands.command(brief="Show gudgitters", aliases=["gitgudders"])
    async def gudgitters(self, ctx):
        """Show the list of users of gitgud with their scores."""
        res = cf_common.user_db.get_gudgitters()
        res.sort(key=lambda r: r[1], reverse=True)

        style = table.Style('{:>}  {:<}  {:<}  {:<}')
        t = table.Table(style)
        t += table.Header('#', 'Name', 'Handle', 'Rating')
        t += table.Line()
        index = 0
        for user_id, score in res:
            member = ctx.guild.get_member(int(user_id))
            if member is None:
                continue
            if score > 0:
                handle = cf_common.user_db.gethandle(user_id)
                user = cf_common.user_db.fetch_cfuser(handle)
                handle_display = f'{member.display_name} ({score})'
                rating = user.rating if user.rating is not None else 'Unrated'
                t += table.Data(index, handle_display, handle, rating)
                index += 1
            if index == 20:
                break
        if index > 0:
            msg = '```\n' + str(t) + '\n```'
        else:
            msg = '```No one has completed a gitgud challenge, send ;gitgud to request and ;gotgud to mark it as complete```'
        await ctx.send(msg)

    @handle.command(brief="Show all handles")
    async def list(self, ctx):
        """Shows all members of the server who have registered their handles and
        their Codeforces ratings.
        """
        res = cf_common.user_db.getallhandleswithrating()
        users = [(ctx.guild.get_member(int(user_id)), handle, rating) for user_id, handle, rating in res]
        users = [(member, handle, rating) for member, handle, rating in users if member is not None]
        users.sort(key=lambda x: (1 if x[2] is None else -x[2], x[1]))  # Sorting by (-rating, handle)
        pages = _make_pages(users)
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=_PAGINATE_WAIT_TIME, set_pagenum_footers=True)

    @handle.command(brief="Show colour handles")
    async def pretty(self, ctx: discord.ext.commands.Context, page_no: int = None):
        res = cf_common.user_db.getallhandleswithrating()
        res.sort(key=lambda r: r[2] if r[2] is not None else -1, reverse=True)
        rankings = []
        pos = 0
        author_pos = 0
        for user_id, handle, rating in res:
            member = ctx.guild.get_member(int(user_id))
            if member is None:
                continue
            if member == ctx.author:
                author_pos = pos
            if rating is None:
                rating = 'N/A'
            rankings.append((pos, member.display_name, handle, rating))
            pos += 1

        if page_no is not None:
            page_no = max(page_no + 1, 1)
            upto = page_no * 10
            if upto > len(rankings):
                await ctx.send(f"Page number should be at most {len(rankings) // 10} !\n"
                               f"Showing last 10 handles.")
            rankings = rankings[-10:] if len(rankings) < upto else rankings[upto - 10: upto]
        else:
            # Show rankings around invoker
            rankings = rankings[max(0, author_pos - 4): author_pos + 6]

        img = get_prettyhandles_image(rankings, self.font)
        buffer = io.BytesIO()
        img.save(buffer, 'png')
        buffer.seek(0)
        await ctx.send(file=discord.File(buffer, "handles.png"))

    async def _update_ranks(self, guild):
        """For each member in the guild, fetches their current ratings and updates their role if
        required.
        """
        res = cf_common.user_db.get_handles_for_guild(guild.id)
        member_handles = [(guild.get_member(int(user_id)), handle) for user_id, handle in res]
        member_handles = [(member, handle) for member, handle in member_handles if member is not None]
        if not member_handles:
            raise HandleCogError('Handles not set for any user')
        members, handles = zip(*member_handles)
        users = await cf.user.info(handles=handles)
        for user in users:
            cf_common.user_db.cache_cfuser(user)

        required_roles = {user.rank.title for user in users if user.rank != cf.UNRATED_RANK}
        rank2role = {role.name: role for role in guild.roles if role.name in required_roles}
        missing_roles = required_roles - rank2role.keys()
        if missing_roles:
            roles_str = ', '.join(f'`{role}`' for role in missing_roles)
            plural = 's' if len(missing_roles) > 1 else ''
            raise HandleCogError(f'Role{plural} for rank{plural} {roles_str} not present in the server')

        for member, user in zip(members, users):
            role_to_assign = None if user.rank == cf.UNRATED_RANK else rank2role[user.rank.title]
            await self.update_member_rank_role(member, role_to_assign,
                                               reason='Codeforces rank update')

    @staticmethod
    def _make_rankup_embed(guild, contest, change_by_handle):
        """Make an embed containing a list of rank changes and top rating increases for the members
        of this guild.
        """
        user_id_handle_pairs = cf_common.user_db.get_handles_for_guild(guild.id)
        member_handle_pairs = [(guild.get_member(int(user_id)), handle)
                               for user_id, handle in user_id_handle_pairs]
        member_change_pairs = [(member, change_by_handle[handle])
                               for member, handle in member_handle_pairs
                               if member is not None and handle in change_by_handle]
        if not member_change_pairs:
            raise HandleCogError(f'Contest `{contest.id} | {contest.name}` was not rated for any'
                                 'member of this server.')

        member_change_pairs.sort(key=lambda pair: pair[1].newRating, reverse=True)
        rank_to_role = {role.name: role for role in guild.roles}

        def rating_to_displayable_rank(rating):
            rank = cf.rating2rank(rating).title
            role = rank_to_role.get(rank)
            return role.mention if role else rank

        rank_changes_str = []
        for member, change in member_change_pairs:
            old_role = None
            if change.oldRating == 1500:
                # Check if this is the user's first rated contest.
                rating_changes = cf_common.cache2.rating_changes_cache.get_rating_changes_for_handle(change.handle)
                first = min(rating_changes, key=lambda change: change.ratingUpdateTimeSeconds)
                if first.contestId == change.contestId:
                    old_role = 'Unrated'
            if old_role is None:
                old_role = rating_to_displayable_rank(change.oldRating)
            new_role = rating_to_displayable_rank(change.newRating)
            if new_role != old_role:
                rank_change_str = (f'{member.mention} (`{change.handle}`): {old_role} '
                                   f'\N{LONG RIGHTWARDS ARROW} {new_role}')
                rank_changes_str.append(rank_change_str)

        member_change_pairs.sort(key=lambda pair: pair[1].newRating - pair[1].oldRating,
                                 reverse=True)
        top_increases_str = []
        for member, change in member_change_pairs[:_TOP_DELTAS_SHOW_COUNT]:
            delta = change.newRating - change.oldRating
            if delta <= 0:
                break
            increase_str = (f'{member.mention} (`{change.handle}`): {change.oldRating} '
                            f'\N{HORIZONTAL BAR} **{delta:+}** \N{LONG RIGHTWARDS ARROW} '
                            f'{change.newRating}')
            top_increases_str.append(increase_str)

        desc = '\n'.join(rank_changes_str) or 'No rank changes'
        embed = discord_common.cf_color_embed(title=contest.name, url=contest.url, description=desc)
        embed.set_author(name='Rank updates')
        embed.add_field(name='Top rating increases',
                        value='\n'.join(top_increases_str) or 'Nobody got a positive delta :(',
                        inline=False)
        return embed

    @commands.command(brief='Update Codeforces rank roles')
    @commands.has_role('Admin')
    async def updateroles(self, ctx):
        """Update Codeforces rank roles for every member in this server."""
        await self._update_ranks(ctx.guild)
        await ctx.send(embed=discord_common.embed_success('Roles updated successfully.'))

    @commands.group(brief='Commands for rank update publishing',
                    invoke_without_command=True)
    async def rankup(self, ctx):
        await ctx.send_help(ctx.command)

    @rankup.command(brief='Set rank update channel to current channel')
    @commands.has_role('Admin')
    async def here(self, ctx):
        """Set the current channel as channel to publish rank updates to."""
        cf_common.user_db.set_rankup_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(embed=discord_common.embed_success('Rank update channel set.'))

    @rankup.command(brief='Disable rank update publishing')
    @commands.has_role('Admin')
    async def clear(self, ctx):
        """Stop publishing rank updates and remove the currently set rank update channel
        from settings."""
        rc = cf_common.user_db.clear_rankup_channel(ctx.guild.id)
        if not rc:
            raise HandleCogError('Rank update channel not set.')
        await ctx.send(embed=discord_common.embed_success('Rank update channel cleared from '
                                                          'settings.'))

    @rankup.command(brief='Publish a rank update for the given contest')
    @commands.has_role('Admin')
    async def publish(self, ctx, contest_id: int):
        channel_id = cf_common.user_db.get_rankup_channel(ctx.guild.id)
        if channel_id is None:
            raise HandleCogError('Rank update channel not set.')
        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            raise HandleCogError('Channel set for rank update is no longer available.')

        try:
            contest = cf_common.cache2.contest_cache.get_contest(contest_id)
        except cache_system2.ContestNotFound as e:
            raise HandleCogError(f'Contest with id `{e.contest_id}` not found.')
        if contest.phase != 'FINISHED':
            raise HandleCogError(f'Contest `{contest_id} | {contest.name}` has not finished.')
        try:
            changes = await cf.contest.ratingChanges(contest_id=contest_id)
        except cf.RatingChangesUnavailableError:
            changes = None
        if not changes:
            raise HandleCogError(f'Rating changes are not available for contest `{contest_id} | '
                                 f'{contest.name}`.')

        change_by_handle = {change.handle: change for change in changes}
        await channel.send(embed=self._make_rankup_embed(ctx.guild, contest, change_by_handle))
        await ctx.send(embed=discord_common.embed_success(f'Rank updates published to '
                                                          f'{channel.mention}.'))

    async def cog_command_error(self, ctx, error):
        if isinstance(error, HandleCogError):
            await ctx.send(embed=discord_common.embed_alert(error))
            error.handled = True


def setup(bot):
    bot.add_cog(Handles(bot))
