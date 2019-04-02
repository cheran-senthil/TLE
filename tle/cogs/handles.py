import discord
from discord.ext import commands
from handle_conn.handle_conn import HandleConn
from tabulate import tabulate


class Handles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.url = 'https://codeforces.com/profile/{}'
        self.conn = HandleConn('handles.db')

    @commands.command(brief='sethandle [name] [handle]')
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

    @commands.command(brief='removehandle [name]')
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
        """ show all handles """
        try:
            converter = commands.MemberConverter()
            res = self.conn.getallhandles()
            table = []
            for id, handle in res:
                try:  # in case the person has left the server
                    member = await converter.convert(ctx, id)
                    if member.nick: table.append((member.nick, handle))
                    else: table.append((member.name, handle))
                except:
                    pass
            msg = '```\n{}\n```'.format(
                tabulate(table, headers=('name', 'handle')))
        except:
            msg = 'showhandles error!'
        await ctx.send(msg)


def setup(bot):
    bot.add_cog(Handles(bot))
