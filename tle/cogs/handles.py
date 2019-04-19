import logging
import io

import aiohttp
import discord
from discord.ext import commands
from tabulate import tabulate

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common
from tle.util import discord_common
from tle.util import paginator

from PIL import Image, ImageFont, ImageDraw

_HANDLES_PER_PAGE = 15
_PAGINATE_WAIT_TIME = 5 * 60  # 5 minutes


def rating_to_color(rating):
    """returns (r, g, b) pixels values corresponding to rating"""
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
            name = name[:14] + "..."
        if len(handle) > 17:
            handle = handle[:14] + "..."
        s = f"{f'#{pos}':<4}{name:<18}{handle:<18}{rating:>6}"

        color = rating_to_color(rating)
        if rating >= 3000:  # nutella
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
    if mode == 'set':
        desc = f'Handle for **{member.display_name}** successfully set to **[{user.handle}]({user.url})**'
    elif mode == 'get':
        desc = f'Handle for **{member.display_name}** is currently set to **[{user.handle}]({user.url})**'
    else:
        return None
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
    chunks = [users[i: i + _HANDLES_PER_PAGE] for i in range(0, len(users), _HANDLES_PER_PAGE)]
    pages = []
    done = 0
    for chunk in chunks:
        table = []
        for i, (member, handle, rating) in enumerate(chunk):
            rank = cf.rating2rank(rating)
            rating_str = 'N/A' if rating is None else str(rating)
            table.append((i + done, member.display_name, handle, rating_str, rank.title))
        table_str = '```\n{}\n```'.format(
            tabulate(table, headers=('#', 'Name', 'Handle', 'Rating', 'Rank'), numalign='left'))
        embed = discord_common.cf_color_embed(description=table_str)
        pages.append(('Handles of server members', embed))
        done += len(chunk)
    return pages


class Handles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(brief='sethandle [name] [handle] (admin-only)')
    @commands.has_role('Admin')
    async def sethandle(self, ctx, member: discord.Member, handle: str):
        """Set Codeforces handle of a user"""
        try:
            users = await cf.user.info(handles=[handle])
            user = users[0]
        except aiohttp.ClientConnectionError:
            await ctx.send('Could not connect to CF API to verify handle')
            return
        except cf.NotFoundError:
            await ctx.send(f'Handle not found: `{handle}`')
            return
        except cf.InvalidParamError:
            await ctx.send(f'Not a valid Codeforces handle: `{handle}`')
            return
        except cf.CodeforcesApiError:
            await ctx.send('Codeforces API error.')
            return

        # CF API returns correct handle ignoring case, update to it
        handle = user.handle

        cf_common.conn.cache_cfuser(user)
        cf_common.conn.sethandle(member.id, handle)

        embed = _make_profile_embed(member, user, mode='set')
        await ctx.send(embed=embed)

    @commands.command(brief='gethandle [name]')
    async def gethandle(self, ctx, member: discord.Member):
        """Show Codeforces handle of a user"""
        handle = cf_common.conn.gethandle(member.id)
        if not handle:
            await ctx.send(f'Handle for user {member.display_name} not found in database')
            return
        user = cf_common.conn.fetch_cfuser(handle)
        if user is None:
            # Not cached, should not happen
            logging.error(f'Handle info for {handle} not cached')
            return

        embed = _make_profile_embed(member, user, mode='get')
        await ctx.send(embed=embed)

    @commands.command(brief='removehandle [name] (admin-only)')
    @commands.has_role('Admin')
    async def removehandle(self, ctx, member: discord.Member):
        """ remove handle """
        if not member:
            await ctx.send('Member not found!')
            return
        try:
            r = cf_common.conn.removehandle(member.id)
            if r == 1:
                msg = f'removehandle: {member.name} removed'
            else:
                msg = f'removehandle: {member.name} not found'
        except Exception as e:
            print(e)
            msg = 'removehandle error!'
        await ctx.send(msg)

    @commands.command(brief="show gudgitters", aliases=["gitgudders"])
    async def gudgitters(self, ctx):
        try:
            converter = commands.MemberConverter()
            res = cf_common.conn.get_gudgitters()
            res.sort(key=lambda r: r[1], reverse=True)
            table = []
            index = 0
            for user_id, score in res:
                try:  # in case the person has left the server
                    member = await converter.convert(ctx, user_id)
                    name = member.nick if member.nick else member.name
                    handle_display = f'{name} ({score})'
                    table.append((index, handle_display))
                    index = index + 1
                except Exception as e:
                    print(e)
            msg = '```\n{}\n```'.format(tabulate(table, headers=('#', 'name')))
        except Exception as e:
            print(e)
            msg = 'showhandles error!'
        await ctx.send(msg)

    @commands.command(brief="Show all handles")
    async def showhandles(self, ctx):
        """Shows all members of the server who have registered their handles and
        their Codeforces ratings.
        """
        res = cf_common.conn.getallhandleswithrating()
        users = [(ctx.guild.get_member(int(user_id)), handle, rating) for user_id, handle, rating in res]
        users = [(member, handle, rating) for member, handle, rating in users if member is not None]
        users.sort(key=lambda x: (1 if x[2] is None else -x[2], x[1]))  # Sorting by (-rating, handle)
        pages = _make_pages(users)
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=_PAGINATE_WAIT_TIME, set_pagenum_footers=True)

    @commands.command(brief=";prettyhandles [page number]  (color handles ^_^")
    async def prettyhandles(self, ctx: discord.ext.commands.Context, page_no: int = None):
        try:
            converter = commands.MemberConverter()
            res = cf_common.conn.getallhandleswithrating()
            res.sort(key=lambda r: r[2] if r[2] is not None else -1, reverse=True)
            rankings = []
            pos = 0
            author_pos = 0
            for user_id, handle, rating in res:
                try:  # in case the person has left the server
                    member = await converter.convert(ctx, user_id)
                    if member == ctx.author:
                        author_pos = pos
                    if rating is None:
                        rating = 'N/A'
                    name = member.nick if member.nick else member.name
                    rankings.append((pos, name, handle, rating))
                    pos += 1
                except Exception as e:
                    print(e)

            if isinstance(page_no, int):
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
        except Exception as e:
            logging.error(f"prettyhandles error: {e}")
            await ctx.send(f"prettyhandles error!")

    async def make_rank2role(self, ctx):
        converter = commands.RoleConverter()
        rank2role = {}
        for rank in cf.RATED_RANKS:
            rank2role[rank.title.lower()] = await converter.convert(ctx, rank.title)
        return rank2role

    @commands.command(brief='update roles (admin-only)')
    @commands.has_role('Admin')
    async def _updateroles(self, ctx):
        """update roles"""
        # TODO: Add permission check for manage roles
        try:
            rank2role = await self.make_rank2role(ctx)
        except Exception as e:
            print(e)
            await ctx.send('error fetching roles!')
            return

        try:
            res = cf_common.conn.getallhandles()
            handles = [handle for _, handle in res]
            users = await cf.user.info(handles=handles)
            await ctx.send('caching handles...')
            try:
                for user in users:
                    cf_common.conn.cache_cfuser(user)
            except Exception as e:
                print(e)
        except Exception as e:
            print(e)
            await ctx.send('error getting data from cf')
            return

        await ctx.send('updating roles...')
        try:
            converter = commands.MemberConverter()
            for (user_id, handle), user in zip(res, users):
                try:
                    member = await converter.convert(ctx, user_id)
                    rank = user.rank.title.lower()
                    rm_list = []
                    add = True
                    for role in member.roles:
                        name = role.name.lower()
                        if name == rank:
                            add = False
                        elif name in rank2role:
                            rm_list.append(role)
                    if rm_list:
                        await member.remove_roles(*rm_list)
                    if add:
                        await member.add_roles(rank2role[rank])
                except Exception as e:
                    print(e)
            msg = 'Update roles completed.'
        except Exception as e:
            msg = 'updateroles error!'
            print(e)
        await ctx.send(msg)


def setup(bot):
    bot.add_cog(Handles(bot))
