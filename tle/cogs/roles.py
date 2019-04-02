import aiohttp
import discord
from discord.ext import commands
from handle_conn.handle_conn import HandleConn


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ranks = [
            'Expert', 'Candidate Master', 'Master', 'International Master',
            'Grandmaster', 'International Grandmaster', 'Legendary Grandmaster'
        ]
        self.url = 'http://codeforces.com/api/user.info'

    async def query(self, session: aiohttp.ClientSession, handles):
        params = {'handles': ';'.join(handles)}
        async with session.get(self.url, params=params) as resp:
            res = await resp.json()
            return res['result']

    async def FetchRoles(self, ctx):
        converter = commands.RoleConverter()
        rank2role = {}
        for r in self.ranks:
            rank2role[r.lower()] = await converter.convert(ctx, r)
        return rank2role

    @commands.command(brief='update roles')
    @commands.has_role('Admin')
    async def updateroles(self, ctx):
        """update roles"""
        try:
            rank2role = await self.FetchRoles(ctx)
        except:
            await ctx.send('error fetching roles!')
            return
        await ctx.send('updating roles...')
        try:
            conn = HandleConn('handles.db')
            session = aiohttp.ClientSession()
            converter = commands.MemberConverter()
            res = conn.getallhandles()
            handle2id = dict((t[1].lower(), t[0]) for t in res)
            qres = await self.query(session, [t[1] for t in res])
            for r in qres:
                handle = r['handle'].lower()
                id = handle2id[handle]
                try:
                    member = await converter.convert(ctx, id)
                    rank = r['rank'].lower()
                    rm_list = []
                    add = True
                    for role in member.roles:
                        name = role.name.lower()
                        if name == rank: add = False
                        elif name in rank2role: rm_list.append(role)
                    if rm_list:
                        await member.remove_roles(*rm_list)
                    if add:
                        await member.add_roles(rank2role[rank])
                    # await ctx.send(f'{member} to {rank}')
                except Exception as e:
                    print(e)
                    pass
            msg = 'update roles completed'
        except Exception as e:
            msg = 'updateroles error!'
            print(e)
        conn.close()
        await session.close()
        await ctx.send(msg)


def setup(bot):
    bot.add_cog(Roles(bot))


"""
{'expert': '555971731232391179', 'candidate master': '555972443693383700', 'master': '555972496558653441', 'international master': '555973490407243786', 'grandmaster': '555972556088279040', 'international grandmaster': '555972612245946380', 'legendary grandmaster': '555972689869668382'}
"""
