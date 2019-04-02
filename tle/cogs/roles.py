import aiohttp
import discord
from discord.ext import commands
from db_utils.handle_conn import HandleConn
from tle.cogs.util import codeforces_api as cf

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ranks = [
            'Expert', 'Candidate Master', 'Master', 'International Master',
            'Grandmaster', 'International Grandmaster', 'Legendary Grandmaster'
        ]

    async def FetchRoles(self, ctx):
        converter = commands.RoleConverter()
        rank2role = {}
        for r in self.ranks:
            rank2role[r.lower()] = await converter.convert(ctx, r)
        return rank2role
      
    @commands.command(brief='update roles (admin-only)')
    @commands.has_role('Admin')
    async def updateroles(self, ctx):
        """update roles"""
        try:
            rank2role = await self.FetchRoles(ctx)
        except:
            await ctx.send('error fetching roles!')
            return
        
        try:
            conn = HandleConn('handles.db')
            res = conn.getallhandles()
            inforesp = await cf.user.info(handles=[t[1] for t in res])
            await ctx.send('caching handles...')
            try:
                for i, r in enumerate(inforesp):
                    conn.cachehandle(res[i][1], r['rating'], r['titlePhoto'])
            except Exception as e:
                print(e)
            conn.close()
        except:
            conn.close()
            await ctx.send('error getting data from cf')
            return        
    
        await ctx.send('updating roles...')        
        try:            
            converter = commands.MemberConverter()
            for i, r in enumerate(inforesp):
                try:
                    member = await converter.convert(ctx, res[i][0])
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
                except Exception as e:
                    print(e)                                
            msg = 'update roles completed'
        except Exception as e:
            msg = 'updateroles error!'
            print(e)
        await ctx.send(msg)

def setup(bot):
    bot.add_cog(Roles(bot))


"""
{'expert': '555971731232391179', 'candidate master': '555972443693383700', 'master': '555972496558653441', 'international master': '555973490407243786', 'grandmaster': '555972556088279040', 'international grandmaster': '555972612245946380', 'legendary grandmaster': '555972689869668382'}
"""
