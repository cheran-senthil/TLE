import discord
from discord.ext import commands
from handle_conn.handle_conn import HandleConn
from tabulate import tabulate

import aiohttp

class Handles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.url = 'https://codeforces.com/profile/{}'
        self.conn = HandleConn('handles.db')
        self.session = aiohttp.ClientSession()

    # shitty copy paste by okarinn :nauseated_face:
    async def query_api(self, path, params=None):
        API_BASE_URL = 'http://codeforces.com/api/'
        url = API_BASE_URL + path
        try:
            async with self.session.get(url, params=params) as resp:
                return await resp.json()
        except aiohttp.ClientConnectionError as e:
            logging.error(f'Request to CF API encountered error: {e}')
            return None

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
            try: 
                handleq = ';'.join(t[1] for t in res)
                infojson = await self.query_api('user.info', {'handles': handleq})
                result = infojson['result']
                stuff = [(result[i]['rating'], handle, id) for i, (id, handle) in enumerate(res)]
                stuff.sort(key = lambda t: (-t[0], t[1]))
            except:
                stuff = [('N/A', handle, id) for id, handle in res]
            table = []
            for rating, handle, id in stuff:
                try:  # in case the person has left the server
                    member = await converter.convert(ctx, id)
                    handledisp = "{} ({})".format(handle, rating)
                    if member.nick: table.append((member.nick, handledisp))
                    else: table.append((member.name, handledisp))
                except:
                    pass
            msg = '```\n{}\n```'.format(
                tabulate(table, headers=('name', 'handle')))            
        except:
            msg = 'showhandles error!'
        await ctx.send(msg)

def setup(bot):
    bot.add_cog(Handles(bot))
