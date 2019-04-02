import discord
from discord.ext import commands
from db_utils.handle_conn import HandleConn
from tabulate import tabulate


class Handles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.url = 'https://codeforces.com/profile/{}'
        self.conn = HandleConn('handles.db')

    @commands.command(brief='sethandle [name] [handle] (admin-only)')
    @commands.has_role('Admin')
    async def sethandle(self, ctx, member: discord.Member, handle: str):
        """set handle"""
        if not handle:
            await ctx.send('syntax: sethandle [name] [handle]')
            return
        if not member:
            await ctx.send('Member not found!')
            return
        try:
            r = self.conn.sethandle(member.id, handle)
            if r == 1:
                url = self.url.format(handle)
                msg = f'sethandle: {member.name} set to {url}'
            else:
                msg = 'sethandle: 0 rows affected'
        except:
            msg = 'sethandle error!'
        await ctx.send(msg)

    @commands.command(brief='gethandle [name]')
    async def gethandle(self, ctx, member: discord.Member):
        """get handle"""
        if not member:
            await ctx.send('Member not found!')
            return
        try:
            res = self.conn.gethandle(member.id)
            if res:
                url = self.url.format(res)
                msg = f'gethandle: {member.name} at {url}'
            else:
                msg = f'gethandle: {member.name} not found'
        except:
            msg = 'gethandle error!'
        await ctx.send(msg)

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
            for id, handle, rating in res:
                try: # in case the person has left the server
                    member = await converter.convert(ctx, id)
                    if rating is None: rating = 'N/A'
                    hdisp = f'{handle} ({rating})'
                    name = member.nick if member.nick else member.name
                    table.append((name, hdisp))
                except Exception as e:
                    print(e)
            msg = '```\n{}\n```'.format(
                tabulate(table, headers=('name', 'handle'))
                )
        except Exception as e:
            print(e)
            msg = 'showhandles error!'
        await ctx.send(msg)

    @commands.command(brief='clear cache (admin-only)', hidden=True)
    @commands.has_role('Admin')
    async def clearcache(self, ctx):
        try:
            self.conn.clearcache()
            msg = 'clear cache success'
        except:
            msg = 'clear cache error'
        await ctx.send(msg)
        
    @commands.command(brief='show cache (admin only)', hidden=True)
    @commands.has_role('Admin')
    async def showcache(self, ctx):
        cache = self.conn.getallcache()
        msg = '```\n{}\n```'.format(tabulate(cache), headers=('handle','rating','photo'))
        await ctx.send(msg)


def setup(bot):
    bot.add_cog(Handles(bot))
