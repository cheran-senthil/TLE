import logging

import aiohttp
import discord
from discord.ext import commands
from tabulate import tabulate

from tle.util import codeforces_api as cf
from tle.util.handle_conn import HandleConn

PROFILE_BASE_URL = 'https://codeforces.com/profile/'


def make_profile_embed(member, handle, rating, photo, *, mode):
    if mode == 'set':
        desc = f'Handle for **{member.display_name}** successfully set to [**{handle}**]({PROFILE_BASE_URL}{handle})'
    elif mode == 'get':
        desc = f'Handle for **{member.display_name}** is currently set to [**{handle}**]({PROFILE_BASE_URL}{handle})'
    else:
        return None
    rating = rating or 'Unrated'
    embed = discord.Embed(description=desc)
    embed.add_field(name='Rating', value=rating, inline=True)
    embed.add_field(name='Rank', value=cf.RankHelper.rating2rank(rating), inline=True)
    embed.set_thumbnail(url=f'http:{photo}')
    return embed


class Handles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = HandleConn('handles.db')

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

        self.conn.cache_cfuser(user)
        self.conn.sethandle(member.id, handle)

        embed = make_profile_embed(member, handle, user.rating, user.titlePhoto, mode='set')
        await ctx.send(embed=embed)

    @commands.command(brief='gethandle [name]')
    async def gethandle(self, ctx, member: discord.Member):
        """Show Codeforces handle of a user"""
        handle = self.conn.gethandle(member.id)
        if not handle:
            await ctx.send(f'Handle for user {member.display_name} not found in database')
            return
        user = self.conn.fetch_cfuser(handle)
        if user is None:
            # Not cached, should not happen
            logging.error(f'Handle info for {handle} not cached')
            return

        embed = make_profile_embed(member, handle, user.rating, user.titlePhoto, mode='get')
        await ctx.send(embed=embed)

    @commands.command(brief='removehandle [name] (admin-only)')
    @commands.has_role('Admin')
    async def removehandle(self, ctx, member: discord.Member):
        """ remove handle """
        if not member:
            await ctx.send('Member not found!')
            return
        try:
            r = self.conn.removehandle(member.id)
            if r == 1:
                msg = f'removehandle: {member.name} removed'
            else:
                msg = f'removehandle: {member.name} not found'
        except:
            msg = 'removehandle error!'
        await ctx.send(msg)

    @commands.command(brief="show all handles")
    async def showhandles(self, ctx):
        try:
            converter = commands.MemberConverter()
            res = self.conn.getallhandleswithrating()
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

    @commands.command(brief='show cache (admin only)', hidden=True)
    @commands.has_role('Admin')
    async def showcache(self, ctx):
        cache = self.conn.getallcache()
        msg = '```\n{}\n```'.format(tabulate(cache, headers=('handle', 'rating', 'titlePhoto')))
        await ctx.send(msg)


def setup(bot):
    bot.add_cog(Handles(bot))
