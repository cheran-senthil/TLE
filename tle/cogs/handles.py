import io
import asyncio

import discord
import random
from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common
from tle.util import paginator
from tle.util import table

from PIL import Image, ImageFont, ImageDraw

_HANDLES_PER_PAGE = 15
_NAME_MAX_LEN = 20
_PAGINATE_WAIT_TIME = 5 * 60  # 5 minutes


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


def get_prettyhandles_image(rankings):
    """return PIL image for rankings"""
    SMOKE_WHITE = (250, 250, 250)
    BLACK = (0, 0, 0)
    img = Image.new("RGB", (900, 450), color=SMOKE_WHITE)

    font = ImageFont.truetype("tle/assets/fonts/Cousine-Regular.ttf", size=30)
    draw = ImageDraw.Draw(img)
    x = 20
    y = 20
    y_inc, _ = font.getsize("hg")

    header = f"{'#':<4}{'Username':<18}{'Handle':<18}{'Rating':>7}"
    draw.text((x, y), header, fill=BLACK, font=font)
    y += int(y_inc * 1.5)
    for pos, name, handle, rating in rankings:
        if len(name) > 17:
            name = name[:16] + "…"
        if len(handle) > 17:
            handle = handle[:16] + "…"
        s = f"{pos:<4}{name:<18}{handle:<18}{rating:>6}"

        color = rating_to_color(rating)
        if rating!='N/A' and rating >= 3000:  # nutella
            draw.text((x, y), s[:22], fill=color, font=font)
            z = x + font.getsize(s[:22])[0]
            draw.text((z, y), s[22], fill=BLACK, font=font)
            z += font.getsize((s[22]))[0]
            draw.text((z, y), s[23:], fill=color, font=font)
        else:
            draw.text((x, y), s, fill=color, font=font)
        y += y_inc

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

    @commands.group(brief='Commands that have to do with handles', invoke_without_command=True)
    async def handle(self, ctx):
        """Change or collect information about specific handles on Codeforces"""
        await ctx.send_help(ctx.command)

    async def update_member_rank_role(self, member, role_to_assign):
        role_names_to_remove = {rank.title for rank in cf.RATED_RANKS} - {role_to_assign.name}
        if role_to_assign.name not in ['Newbie', 'Pupil', 'Specialist', 'Expert']:
            role_names_to_remove.add('Purgatory')
        to_remove = [role for role in member.roles if role.name in role_names_to_remove]
        if to_remove:
            await member.remove_roles(*to_remove, reason='Codeforces rank update')
        if role_to_assign not in member.roles:
            await member.add_roles(role_to_assign, reason='Codeforces rank update')

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
        embed = _make_profile_embed(member, user, mode='set')
        await ctx.send(embed=embed)

        if user.rank == cf.UNRATED_RANK:
            return
        roles = [role for role in ctx.guild.roles if role.name == user.rank.title]
        if not roles:
            raise HandleCogError(f'Role for rank `{user.rank.title}` not present in the server')
        await self.update_member_rank_role(member, roles[0])

    @handle.command(brief='Identify yourself', usage='[handle]')
    @cf_common.user_guard(group='handle')
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
        embed = discord_common.embed_success(f'Removed handle for {member.mention}')
        await ctx.send(embed=embed)

    @commands.command(brief="Show gudgitters", aliases=["gitgudders"])
    async def gudgitters(self, ctx):
        """Show the list of users of gitgud with their scores."""
        res = cf_common.user_db.get_gudgitters()
        res.sort(key=lambda r: r[1], reverse=True)

        style = table.Style('{:>}  {:<}')
        t = table.Table(style)
        t += table.Header('#', 'Name')
        t += table.Line()
        index = 0
        for user_id, score in res:
            member = ctx.guild.get_member(int(user_id))
            if member is None:
                continue
            if score > 0:
                handle_display = f'{member.display_name} ({score})'
                t += table.Data(index, handle_display)
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

        img = get_prettyhandles_image(rankings)
        buffer = io.BytesIO()
        img.save(buffer, 'png')
        buffer.seek(0)
        await ctx.send(file=discord.File(buffer, "handles.png"))

    @commands.command(brief='Update Codeforces rank roles')
    @commands.has_role('Admin')
    async def updateroles(self, ctx):
        """Update Codeforces rank roles for everyone."""
        res = cf_common.user_db.getallhandles()
        member_handles = [(ctx.guild.get_member(int(user_id)), handle) for user_id, handle in res]
        member_handles = [(member, handle) for member, handle in member_handles if member is not None]
        if not member_handles:
            raise HandleCogError('Handles not set for any user')
        members, handles = zip(*member_handles)
        users = await cf.user.info(handles=handles)
        for user in users:
            cf_common.user_db.cache_cfuser(user)

        required_roles = {user.rank.title for user in users if user.rank != cf.UNRATED_RANK}
        rank2role = {role.name: role for role in ctx.guild.roles if role.name in required_roles}
        missing_roles = required_roles - rank2role.keys()
        if missing_roles:
            roles_str = ', '.join(f'`{role}`' for role in missing_roles)
            plural = 's' if len(missing_roles) > 1 else ''
            raise HandleCogError(f'Role{plural} for rank{plural} {roles_str} not present in the server')

        for member, user in zip(members, users):
            if user.rank != cf.UNRATED_RANK:
                await self.update_member_rank_role(member, rank2role[user.rank.title])

        await ctx.send(embed=discord_common.embed_success('Roles updated successfully'))

    async def cog_command_error(self, ctx, error):
        if isinstance(error, HandleCogError):
            await ctx.send(embed=discord_common.embed_alert(error))
            error.handled = True


def setup(bot):
    bot.add_cog(Handles(bot))
