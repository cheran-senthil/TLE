from discord.ext import commands

from tle.util import codeforces_api as cf
from tle.util import handle_conn


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def make_rank2role(self, ctx):
        converter = commands.RoleConverter()
        rank2role = {}
        for rank in cf.RankHelper.get_ranks():
            rank2role[rank.lower()] = await converter.convert(ctx, rank)
        return rank2role

    @commands.command(brief='update roles (admin-only)')
    @commands.has_role('Admin')
    async def updateroles(self, ctx):
        """update roles"""
        try:
            rank2role = await self.make_rank2role(ctx)
        except Exception as e:
            print(e)
            await ctx.send('error fetching roles!')
            return

        try:
            res = handle_conn.conn.getallhandles()
            handles = [handle for _, handle in res]
            users = await cf.user.info(handles=handles)
            await ctx.send('caching handles...')
            try:
                for user in users:
                    handle_conn.conn.cache_cfuser(user)
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
                    rank = user.rank.lower()
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
            msg = 'Update roles completed. Note: Submissions data are cleared. Call forcecache_ to recache.'
        except Exception as e:
            msg = 'updateroles error!'
            print(e)
        await ctx.send(msg)


def setup(bot):
    bot.add_cog(Roles(bot))


"""
{'expert': '555971731232391179', 'candidate master': '555972443693383700', 'master': '555972496558653441', 'international master': '555973490407243786', 'grandmaster': '555972556088279040', 'international grandmaster': '555972612245946380', 'legendary grandmaster': '555972689869668382'}
"""
