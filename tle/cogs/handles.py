import logging

import aiohttp
import discord
from discord.ext import commands
from tabulate import tabulate

from tle.util import codeforces_api as cf
from tle.util import codeforces_common as cf_common


def make_profile_embed(member, user, *, mode):
    if mode == 'set':
        desc = f'Handle for **{member.display_name}** successfully set to **[{user.handle}]({user.url})**'
    elif mode == 'get':
        desc = f'Handle for **{member.display_name}** is currently set to **[{user.handle}]({user.url})**'
    else:
        return None
    rating = 'Unrated' if user.rating is None else user.rating
    rank = user.rank

    embed = discord.Embed(description=desc, color=rank.color_embed)
    embed.add_field(name='Rating', value=rating, inline=True)
    embed.add_field(name='Rank', value=rank.title, inline=True)
    embed.set_thumbnail(url=f'https:{user.titlePhoto}')
    return embed


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

        embed = make_profile_embed(member, user, mode='set')
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

        embed = make_profile_embed(member, user, mode='get')
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
            for id, score in res:
                try:  # in case the person has left the server
                    member = await converter.convert(ctx, id)
                    name = member.nick if member.nick else member.name
                    hdisp = f'{name} ({score})'
                    table.append((index, hdisp))
                    index = index + 1
                except Exception as e:
                    print(e)
            msg = '```\n{}\n```'.format(tabulate(table, headers=('#', 'name')))
        except Exception as e:
            print(e)
            msg = 'showhandles error!'
        await ctx.send(msg)

    @commands.command(brief="show all handles")
    async def showhandles(self, ctx):
        try:
            converter = commands.MemberConverter()
            res = cf_common.conn.getallhandleswithrating()
            res.sort(key=lambda r: r[2] if r[2] is not None else -1, reverse=True)
            table = []
            for i, (id, handle, rating) in enumerate(res):
                try:  # in case the person has left the server
                    member = await converter.convert(ctx, id)
                    if rating is None:
                        rating = 'N/A'
                    hdisp = f'{handle} ({rating})'
                    name = member.nick if member.nick else member.name
                    table.append((i, name, hdisp))
                except Exception as e:
                    print(e)
            msg = '```\n{}\n```'.format(tabulate(table, headers=('#', 'name', 'handle')))
        except Exception as e:
            print(e)
            msg = 'showhandles error!'
        await ctx.send(msg)

    @commands.command(brief='show cache (admin only)')
    @commands.has_role('Admin')
    async def _showcache(self, ctx):
        cache = cf_common.conn.getallcache()
        msg = '```\n{}\n```'.format(tabulate(cache, headers=('handle', 'rating', 'titlePhoto')))
        await ctx.send(msg)

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
            for (discord_userid, handle), user in zip(res, users):
                try:
                    member = await converter.convert(ctx, discord_userid)
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
