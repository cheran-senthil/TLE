import io
import asyncio
import contextlib
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
from tle.util import db
from tle import constants

from PIL import Image, ImageFont, ImageDraw

_HANDLES_PER_PAGE = 15
_NAME_MAX_LEN = 20
_PAGINATE_WAIT_TIME = 5 * 60  # 5 minutes
_TOP_DELTAS_COUNT = 5


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

        async def update_for_guild(guild):
            if cf_common.user_db.has_auto_role_update_enabled(guild.id):
                with contextlib.suppress(HandleCogError):
                    await self._update_ranks(guild)
            channel_id = cf_common.user_db.get_rankup_channel(guild.id)
            channel = guild.get_channel(channel_id)
            if channel is not None:
                with contextlib.suppress(HandleCogError):
                    embed = self._make_rankup_embed(guild, contest, change_by_handle)
                    await channel.send(embed=embed)

        await asyncio.gather(*(update_for_guild(guild) for guild in self.bot.guilds),
                             return_exceptions=True)
        self.logger.info(f'All guilds updated for contest {contest.id}.')

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
        try:
            cf_common.user_db.set_handle(member.id, ctx.guild.id, handle)
        except db.UniqueConstraintFailed:
            raise HandleCogError(f'The handle `{handle}` is already associated with another user.')
        cf_common.user_db.cache_cf_user(user)

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
        if cf_common.user_db.get_handle(ctx.author.id, ctx.guild.id):
            raise HandleCogError(f'{ctx.author.mention}, you cannot identify when your handle is '
                                 'already set. Ask an Admin if you wish to change it')

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
        handle = cf_common.user_db.get_handle(member.id, ctx.guild.id)
        if not handle:
            raise HandleCogError(f'Handle for {member.mention} not found in database')
        user = cf_common.user_db.fetch_cf_user(handle)
        embed = _make_profile_embed(member, user, mode='get')
        await ctx.send(embed=embed)

    @handle.command(brief='Get Discord username by cf handle')
    async def rget(self, ctx, handle: str):
        """Show Discord username of a cf handle."""
        user_id = cf_common.user_db.get_user_id(handle, ctx.guild.id)
        if not user_id:
            raise HandleCogError(f'Discord username for `{handle}` not found in database')
        user = cf_common.user_db.fetch_cf_user(handle)
        member = ctx.guild.get_member(int(user_id))
        embed = _make_profile_embed(member, user, mode='get')
        await ctx.send(embed=embed)

    @handle.command(brief='Remove handle for a user')
    @commands.has_role('Admin')
    async def remove(self, ctx, member: discord.Member):
        """Remove Codeforces handle of a user."""
        rc = cf_common.user_db.remove_handle(member.id, ctx.guild.id)
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
                handle = cf_common.user_db.get_handle(user_id, ctx.guild.id)
                user = cf_common.user_db.fetch_cf_user(handle)
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
        res = cf_common.user_db.get_cf_users_for_guild(ctx.guild.id)
        users = [(ctx.guild.get_member(int(user_id)), cf_user.handle, cf_user.rating)
                 for user_id, cf_user in res]
        users = [(member, handle, rating) for member, handle, rating in users if member is not None]
        users.sort(key=lambda x: (1 if x[2] is None else -x[2], x[1]))  # Sorting by (-rating, handle)
        pages = _make_pages(users)
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=_PAGINATE_WAIT_TIME, set_pagenum_footers=True)

    @handle.command(brief="Show colour handles")
    async def pretty(self, ctx: discord.ext.commands.Context, page_no: int = None):
        res = cf_common.user_db.get_cf_users_for_guild(ctx.guild.id)
        res.sort(key=lambda pair: pair[1].rating if pair[1].rating is not None else -1,
                 reverse=True)
        rankings = []
        pos = 0
        author_pos = 0
        for user_id, cf_user in res:
            member = ctx.guild.get_member(int(user_id))
            if member is None:
                continue
            if member == ctx.author:
                author_pos = pos
            rating = cf_user.rating
            if rating is None:
                rating = 'N/A'
            rankings.append((pos, member.display_name, cf_user.handle, rating))
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
            cf_common.user_db.cache_cf_user(user)

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
            raise HandleCogError(f'Contest `{contest.id} | {contest.name}` was not rated for any '
                                 'member of this server.')

        member_change_pairs.sort(key=lambda pair: pair[1].newRating, reverse=True)
        rank_to_role = {role.name: role for role in guild.roles}

        def rating_to_displayable_rank(rating):
            rank = cf.rating2rank(rating).title
            role = rank_to_role.get(rank)
            return role.mention if role else rank

        rank_changes_str = []
        for member, change in member_change_pairs:
            cache = cf_common.cache2.rating_changes_cache
            if (change.oldRating == 1500
                    and len(cache.get_rating_changes_for_handle(change.handle)) == 1):
                # If this is the user's first rated contest.
                old_role = 'Unrated'
            else:
                old_role = rating_to_displayable_rank(change.oldRating)
            new_role = rating_to_displayable_rank(change.newRating)
            if new_role != old_role:
                rank_change_str = (f'{member.mention} (`{change.handle}`): {old_role} '
                                   f'\N{LONG RIGHTWARDS ARROW} {new_role}')
                rank_changes_str.append(rank_change_str)

        member_change_pairs.sort(key=lambda pair: pair[1].newRating - pair[1].oldRating,
                                 reverse=True)
        top_increases_str = []
        for member, change in member_change_pairs[:_TOP_DELTAS_COUNT]:
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

    @commands.group(brief='Commands for role updates',
                    invoke_without_command=True)
    async def roleupdate(self, ctx):
        """Group for commands involving role updates."""
        await ctx.send_help(ctx.command)

    @roleupdate.command(brief='Update Codeforces rank roles')
    @commands.has_role('Admin')
    async def now(self, ctx):
        """Updates Codeforces rank roles for every member in this server."""
        await self._update_ranks(ctx.guild)
        await ctx.send(embed=discord_common.embed_success('Roles updated successfully.'))

    @roleupdate.command(brief='Enable or disable auto role updates',
                        usage='on|off')
    @commands.has_role('Admin')
    async def auto(self, ctx, arg):
        """Auto role update refers to automatic updating of rank roles when rating
        changes are released on Codeforces. 'on'/'off' disables or enables auto role
        updates.
        """
        if arg == 'on':
            rc = cf_common.user_db.enable_auto_role_update(ctx.guild.id)
            if not rc:
                raise HandleCogError('Auto role update is already enabled.')
            await ctx.send(embed=discord_common.embed_success('Auto role updates enabled.'))
        elif arg == 'off':
            rc = cf_common.user_db.disable_auto_role_update(ctx.guild.id)
            if not rc:
                raise HandleCogError('Auto role update is already disabled.')
            await ctx.send(embed=discord_common.embed_success('Auto role updates disabled.'))
        else:
            raise ValueError(f"arg must be 'on' or 'off', got '{arg}' instead.")

    @roleupdate.command(brief='Publish a rank update for the given contest',
                        usage='here|off|contest_id')
    @commands.has_role('Admin')
    async def publish(self, ctx, arg):
        """This is a feature to publish a summary of rank changes and top rating
        increases in a particular contest for members of this server. 'here' will
        automatically publish the summary to this channel whenever rating changes on
        Codeforces are released. 'off' will disable auto publishing. Specifying a
        contest id will publish the summary immediately.
        """
        if arg == 'here':
            cf_common.user_db.set_rankup_channel(ctx.guild.id, ctx.channel.id)
            await ctx.send(
                embed=discord_common.embed_success('Auto rank update publishing enabled.'))
        elif arg == 'off':
            rc = cf_common.user_db.clear_rankup_channel(ctx.guild.id)
            if not rc:
                raise HandleCogError('Rank update publishing is already disabled.')
            await ctx.send(embed=discord_common.embed_success('Rank update publishing disabled.'))
        else:
            try:
                contest_id = int(arg)
            except ValueError:
                raise ValueError(f"arg must be 'here', 'off' or a contest ID, got '{arg}' instead.")
            await self._publish_now(ctx, contest_id)

    async def _publish_now(self, ctx, contest_id):
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
        await ctx.channel.send(embed=self._make_rankup_embed(ctx.guild, contest, change_by_handle))

    @discord_common.send_error_if(HandleCogError)
    async def cog_command_error(self, ctx, error):
        pass


def setup(bot):
    bot.add_cog(Handles(bot))
