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
        await self._add_sub(ctx, 'ratings')
        await ctx.send("✅ This channel will show **Ranklists** and **Rating Changes** automatically.")

    @subscribe.command(brief='Subscribe to ALL')
    @commands.has_role(constants.TLE_ADMIN)
    async def all(self, ctx):
        for key in self.subscriptions:
            if ctx.channel.id not in self.subscriptions[key]:
                self.subscriptions[key].append(ctx.channel.id)
        self.save_json(ALERTS_FILE, self.subscriptions)
        await ctx.send(f'✅ Subscribed `{ctx.channel.name}` to **EVERYTHING**.')
        
    @commands.command(brief='Force trigger a rating alert')
    @commands.has_role(constants.TLE_ADMIN)
    async def trigger_alert(self, ctx, contest_id: int):
        await ctx.send(f"🔄 Force checking Contest {contest_id}...")
        try:
            contests = await cf_common.cf_api.contest.list(gym=False)
            contest = next((c for c in contests if c.id == contest_id), None)
            if not contest:
                await ctx.send("❌ Contest not found.")
                return
            changes = await cf_common.cf_api.contest.ratingChanges(contestId=contest_id)
            if not changes:
                await ctx.send("⚠️ Ratings are not out yet (or contest is unrated).")
                return
            await self.announce_results(contest, changes)
            await ctx.send("✅ Done.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    # --- WATCHER: CONTEST REMINDERS (10 mins) ---
    @tasks.loop(minutes=10)
    async def watch_contests(self):
        current_time = datetime.datetime.now(datetime.timezone.utc)
        if self.subscriptions['codeforces']:
            try:
                cf_contests = await cf_common.cf_api.contest.list(gym=False)
                upcoming_cf = [c for c in cf_contests if c.phase == 'BEFORE']
                for c in upcoming_cf:
                    start_time = datetime.datetime.fromtimestamp(c.startTimeSeconds, datetime.timezone.utc)
                    diff = (start_time - current_time).total_seconds()
                    await self.process_alert(c.id, c.name, "codeforces", diff, f"https://codeforces.com/contests/{c.id}")
            except Exception as e:
                logger.error(f"CF Alert Error: {e}")

        if any(self.subscriptions[k] for k in ['atcoder', 'leetcode', 'codechef']):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(KONTESTS_URL, ssl=False, timeout=10) as resp:
                        if resp.status == 200:
                            all_contests = await resp.json()
                            site_map = {'AtCoder': 'atcoder', 'CodeChef': 'codechef', 'LeetCode': 'leetcode'}
                            for c in all_contests:
                                site_name = c.get('site')
                                if site_name not in site_map: continue
                                sub_key = site_map[site_name]
                                if not self.subscriptions[sub_key]: continue
                                try:
                                    start_time = datetime.datetime.fromisoformat(c['start_time'].replace('Z', '+00:00'))
                                    diff = (start_time - current_time).total_seconds()
                                    c_id = c.get('name', 'unk') + c.get('start_time', '')
                                    await self.process_alert(c_id, c['name'], sub_key, diff, c.get('url', ''))
                                except: continue
            except: pass

    async def process_alert(self, uid, name, site_key, diff, url):
        is_1hr = 3000 < diff < 4200
        is_10min = 300 < diff < 900
        alert_key = f"{uid}_{'1h' if is_1hr else '10m'}"

        if (is_1hr or is_10min) and alert_key not in self.already_alerted:
            self.already_alerted.add(alert_key)
            embed = discord.Embed(title=f"🏆 {name}", url=url, description=f"**Site:** {site_key.title()}\n**Starting in:** {'1 hour' if is_1hr else '10 minutes'}", color=0x00FF00)
            for ch_id in self.subscriptions[site_key]:
                ch = self.bot.get_channel(ch_id)
                if ch: 
                    try: await ch.send(embed=embed)
                    except: pass

    # --- WATCHER: RATINGS (15 mins) ---
    @tasks.loop(minutes=15)
    async def watch_rating_changes(self):
        if not self.subscriptions['ratings']: return
        try:
            try: contests = await cf_common.cf_api.contest.list(gym=False)
            except: return 

            # Check contests from last 14 days
            now = time.time()
            two_weeks_ago = now - (14 * 24 * 60 * 60)
            three_days_ago = now - (3 * 24 * 60 * 60)
            
            candidates = [
                c for c in contests 
                if c.phase == 'FINISHED' 
                and c.startTimeSeconds > two_weeks_ago
                and c.id not in self.processed_contests
            ]

            for contest in candidates:
                # Attempt to get changes
                try: 
                    changes = await cf_common.cf_api.contest.ratingChanges(contestId=contest.id)
                except Exception:
                    # API Failed? Just skip this loop, try again later.
                    continue 
                
                # Handling Unrated Contests (Empty List)
                if not changes:
                    # If the contest is older than 3 days and still no ratings,
                    # assume it's unrated and stop checking it forever.
                    if contest.startTimeSeconds < three_days_ago:
                        self.processed_contests.append(contest.id)
                        self.save_json(PROCESSED_FILE, self.processed_contests)
                    continue 

                # If we get here, Ratings are OUT!
                await self.announce_results(contest, changes)
                self.processed_contests.append(contest.id)
                self.save_json(PROCESSED_FILE, self.processed_contests)
                
                try:
                    cf_cog = self.bot.get_cog('Codeforces')
                    if cf_cog: await cf_common.cache2.contest_cache.reload_now()
                except: pass
        except Exception as e:
            logger.error(f'Error in watch_ratings: {e}')

    async def announce_results(self, contest, changes):
        for channel_id in self.subscriptions['ratings']:
            channel = self.bot.get_channel(channel_id)
            if not channel: continue
            
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
                    line = f"**#{rank}** {user_mention} (**{change.handle}**): {change.newRating} ({'+' if delta>=0 else ''}{delta}) {icon}"
                    server_updates.append((change.newRating, line))

            if server_updates:
                server_updates.sort(key=lambda x: x[0], reverse=True)
                final_lines = [item[1] for item in server_updates]
                desc = "\n".join(final_lines)
                if len(desc) > 4000: desc = desc[:4000] + "\n...and more"

                embed = discord.Embed(title=f"📊 Ranklist: {contest.name}", url=f"https://codeforces.com/contest/{contest.id}/standings", description=desc, color=0xFFD700)
                embed.set_footer(text="Roles/Colors will update automatically shortly.")
                try: await channel.send(embed=embed)
                except: pass

    @watch_contests.before_loop
    @watch_rating_changes.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

def setup(bot):
    bot.add_cog(Alerts(bot))
