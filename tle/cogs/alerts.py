import asyncio
import json
import logging
import os
import time
import datetime
import aiohttp
import discord
from discord.ext import commands, tasks
from tle import constants

# Import TLE Codeforces utilities
try:
    from tle.util import codeforces_api as cf
    from tle.util import codeforces_common as cf_common
except ImportError:
    from tle.util import codeforces_common as cf
    import tle.util.codeforces_common as cf_common

logger = logging.getLogger(__name__)

ALERTS_FILE = 'data/alerts.json'
PROCESSED_FILE = 'data/processed_contests.json'
KONTESTS_URL = "https://kontests.net/api/v1/all"

class Alerts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.subscriptions = self.load_json(ALERTS_FILE, {'codeforces': [], 'atcoder': [], 'codechef': [], 'leetcode': [], 'ratings': []})
        self.processed_contests = self.load_json(PROCESSED_FILE, [])
        self.already_alerted = set()
        
        self.watcher_task = self.watch_contests.start()
        self.rating_task = self.watch_rating_changes.start()

    def cog_unload(self):
        self.watcher_task.cancel()
        self.rating_task.cancel()

    def load_json(self, filename, default):
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for key in default:
                            if key not in data:
                                data[key] = []
                    return data
            except:
                return default
        return default

    def save_json(self, filename, data):
        with open(filename, 'w') as f:
            json.dump(data, f)

    async def _add_sub(self, ctx, key):
        if ctx.channel.id not in self.subscriptions[key]:
            self.subscriptions[key].append(ctx.channel.id)
            self.save_json(ALERTS_FILE, self.subscriptions)
            await ctx.send(f'✅ Subscribed `{ctx.channel.name}` to **{key.title()}**.')
        else:
            await ctx.send(f'⚠️ Already subscribed to {key.title()}.')

    # --- COMMANDS ---
    @commands.group(brief='Subscribe to alerts', invoke_without_command=True)
    async def subscribe(self, ctx):
        await ctx.send_help(ctx.command)

    @subscribe.command(brief='Codeforces Contest Reminders')
    @commands.has_role(constants.TLE_ADMIN)
    async def codeforces(self, ctx):
        await self._add_sub(ctx, 'codeforces')

    @subscribe.command(brief='AtCoder/LC/CodeChef Reminders')
    @commands.has_role(constants.TLE_ADMIN)
    async def others(self, ctx):
        await self._add_sub(ctx, 'atcoder')
        await self._add_sub(ctx, 'leetcode')
        await self._add_sub(ctx, 'codechef')
        await ctx.send("✅ Subscribed to AtCoder, LeetCode, and CodeChef.")

    @subscribe.command(brief='Ranklist & Rating Updates')
    @commands.has_role(constants.TLE_ADMIN)
    async def ratings(self, ctx):
        """Subscribes this channel to automatic ranklists and rating updates."""
        await self._add_sub(ctx, 'ratings')
        await ctx.send("✅ This channel will show **Ranklists** and **Rating Changes** after CF rounds.")

    @subscribe.command(brief='Subscribe to ALL')
    @commands.has_role(constants.TLE_ADMIN)
    async def all(self, ctx):
        for key in self.subscriptions:
            if ctx.channel.id not in self.subscriptions[key]:
                self.subscriptions[key].append(ctx.channel.id)
        self.save_json(ALERTS_FILE, self.subscriptions)
        await ctx.send(f'✅ Subscribed `{ctx.channel.name}` to **EVERYTHING**.')

    # --- WATCHER: CONTEST REMINDERS (10 mins) ---
    @tasks.loop(minutes=10)
    async def watch_contests(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(KONTESTS_URL) as resp:
                    if resp.status != 200: return
                    all_contests = await resp.json()

            current_time = datetime.datetime.now(datetime.timezone.utc)
            site_map = {'CodeForces': 'codeforces', 'AtCoder': 'atcoder', 'CodeChef': 'codechef', 'LeetCode': 'leetcode'}

            for c in all_contests:
                site_name = c.get('site')
                if site_name not in site_map: continue
                sub_key = site_map[site_name]
                if not self.subscriptions[sub_key]: continue 

                try:
                    start_time = datetime.datetime.fromisoformat(c['start_time'].replace('Z', '+00:00'))
                except: continue

                diff = (start_time - current_time).total_seconds()
                is_1hr = 3000 < diff < 4200
                is_10min = 300 < diff < 900
                c_id = c.get('name', '') + c.get('start_time', '')
                alert_key = f"{c_id}_{'1h' if is_1hr else '10m'}"

                if (is_1hr or is_10min) and alert_key not in self.already_alerted:
                    self.already_alerted.add(alert_key)
                    embed = discord.Embed(title=f"🏆 {c['name']}", url=c.get('url', ''), description=f"**Site:** {site_name}\n**Starting in:** {'1 hour' if is_1hr else '10 minutes'}", color=0x00FF00)
                    for ch_id in self.subscriptions[sub_key]:
                        ch = self.bot.get_channel(ch_id)
                        if ch: 
                            try: await ch.send(embed=embed)
                            except: pass
        except Exception as e:
            logger.error(f'Error in watch_contests: {e}')

    # --- WATCHER: RANKLIST & RATINGS (15 mins) ---
    @tasks.loop(minutes=15)
    async def watch_rating_changes(self):
        if not self.subscriptions['ratings']: return
        
        try:
            try:
                contests = await cf_common.cf_api.contest.list(gym=False)
            except:
                return 

            # Check FINISHED contests from last 3 days not yet processed
            recent_finished = [c for c in contests if c.phase == 'FINISHED' and c.id not in self.processed_contests]
            recent_finished = recent_finished[:5] 

            for contest in recent_finished:
                # Check API for changes
                try:
                    changes = await cf_common.cf_api.contest.ratingChanges(contestId=contest.id)
                except:
                    continue 

                if not changes: continue 

                # Ratings are OUT.
                await self.announce_results(contest, changes)
                
                # Mark processed
                self.processed_contests.append(contest.id)
                self.save_json(PROCESSED_FILE, self.processed_contests)
                
                # --- AUTO UPDATE ROLES ---
                # We attempt to find the Codeforces Cog and trigger a role update
                try:
                    cf_cog = self.bot.get_cog('Codeforces')
                    if cf_cog:
                        # This triggers the cache refresh which updates roles
                        await cf_common.cache2.contest_cache.reload_now()
                        logger.info(f"Triggered cache reload for role updates after contest {contest.id}")
                except Exception as e:
                    logger.warning(f"Could not trigger instant role update: {e}")

        except Exception as e:
            logger.error(f'Error in watch_ratings: {e}')

    async def announce_results(self, contest, changes):
        for channel_id in self.subscriptions['ratings']:
            channel = self.bot.get_channel(channel_id)
            if not channel: continue
            
            # Get handles for this guild
            guild_handles = cf_common.user_db.get_handles_for_guild(channel.guild.id)
            server_handles = {h.handle.lower(): h.user_id for h in guild_handles}

            server_updates = []
            for change in changes:
                handle_lower = change.handle.lower()
                if handle_lower in server_handles:
                    delta = change.newRating - change.oldRating
                    icon = "📈" if delta >= 0 else "📉"
                    if delta == 0: icon = "➖"
                    
                    user_mention = f"<@{server_handles[handle_lower]}>"
                    rank = getattr(change, 'rank', '?')
                    
                    # Format: #52 Tourist: 3500 (+10)
                    line = f"**#{rank}** {user_mention} (**{change.handle}**): {change.newRating} ({'+' if delta>=0 else ''}{delta}) {icon}"
                    server_updates.append((change.newRating, line))

            if server_updates:
                # Sort by new rating (Highest rating on top)
                server_updates.sort(key=lambda x: x[0], reverse=True)
                final_lines = [item[1] for item in server_updates]
                
                desc = "\n".join(final_lines)
                if len(desc) > 4000: desc = desc[:4000] + "\n...and more"

                embed = discord.Embed(
                    title=f"📊 Ranklist & Changes: {contest.name}",
                    url=f"https://codeforces.com/contest/{contest.id}/standings",
                    description=desc,
                    color=0xFFD700
                )
                embed.set_footer(text="Roles/Colors will update automatically shortly.")
                try: await channel.send(embed=embed)
                except: pass

    @watch_contests.before_loop
    @watch_rating_changes.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

def setup(bot):
    bot.add_cog(Alerts(bot))
