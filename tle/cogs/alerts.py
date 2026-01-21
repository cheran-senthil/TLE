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
import tle.util.codeforces_common as cf_common

logger = logging.getLogger(__name__)

ALERTS_FILE = 'data/alerts.json'
PROCESSED_FILE = 'data/processed_contests.json'

# --- CONFIGURATION ---
CF_API_URL = "https://codeforces.com/api"
CLIST_API_URL = "https://clist.by/api/v4/contest/"
CLIST_USER = os.environ.get("CLIST_USERNAME")
CLIST_KEY = os.environ.get("CLIST_API_KEY")

RESOURCE_IDS = {'codeforces.com': 1, 'codechef.com': 2, 'atcoder.jp': 93, 'leetcode.com': 102}

# CF Ranks (Strict Descending Order)
CF_RANKS = [
    (3000, "Legendary Grandmaster", 0xFF0000),
    (2600, "International Grandmaster", 0xFF0000),
    (2400, "Grandmaster", 0xFF0000),
    (2300, "International Master", 0xFF8C00),
    (2100, "Master", 0xFF8C00),
    (1900, "Candidate Master", 0xAA00AA),
    (1600, "Expert", 0x0000FF),
    (1400, "Specialist", 0x03A89E),
    (1200, "Pupil", 0x77FF77),
    (0,    "Newbie", 0x808080)
]

RANK_ORDER = [
    "Newbie", "Pupil", "Specialist", "Expert", "Candidate Master",
    "Master", "International Master", "Grandmaster", 
    "International Grandmaster", "Legendary Grandmaster"
]

# --- DUMMY CONTEXT FOR GRAPH GENERATION ---
class DuckContext:
    def __init__(self, channel, bot):
        self.channel = channel
        self.bot = bot
        self.guild = channel.guild
        self.author = bot.user
        self.message = None
        self.command = None
    
    async def send(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)
        
    def typing(self):
        return self.channel.typing()

class SimpleContest:
    def __init__(self, data):
        self.id = data.get('id')
        self.name = data.get('name')
        self.startTimeSeconds = data.get('startTimeSeconds')
        self.phase = data.get('phase')

class SimpleRatingChange:
    def __init__(self, data):
        self.handle = data.get('handle')
        self.newRating = data.get('newRating')
        self.oldRating = data.get('oldRating')
        self.rank = data.get('rank')

class Alerts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.subscriptions = self.load_json(ALERTS_FILE, {'codeforces': [], 'atcoder': [], 'codechef': [], 'leetcode': [], 'ratings': [], 'milestones': []})
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

    async def _remove_sub(self, ctx, key):
        if ctx.channel.id in self.subscriptions[key]:
            self.subscriptions[key].remove(ctx.channel.id)
            self.save_json(ALERTS_FILE, self.subscriptions)
            await ctx.send(f'❌ Unsubscribed `{ctx.channel.name}` from **{key.title()}**.')
        else:
            await ctx.send(f'⚠️ `{ctx.channel.name}` is not subscribed to {key.title()}.')

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

    @subscribe.command(brief='Milestones (Rank Ups)')
    @commands.has_role(constants.TLE_ADMIN)
    async def milestones(self, ctx):
        await self._add_sub(ctx, 'milestones')
        await ctx.send("🎉 This channel will celebrate new **First-Time Rank Ups**!")

    @subscribe.command(brief='Subscribe to ALL')
    @commands.has_role(constants.TLE_ADMIN)
    async def all(self, ctx):
        for key in self.subscriptions:
            if ctx.channel.id not in self.subscriptions[key]:
                self.subscriptions[key].append(ctx.channel.id)
        self.save_json(ALERTS_FILE, self.subscriptions)
        await ctx.send(f'✅ Subscribed `{ctx.channel.name}` to **EVERYTHING**.')

    @subscribe.command(brief='Show all active subscriptions')
    @commands.has_role(constants.TLE_ADMIN)
    async def list(self, ctx):
        embed = discord.Embed(title="📢 Active Alerts Configuration", color=0x3498db)
        found_any = False
        
        def get_role_name():
            role_id = constants.TLE_ADMIN
            role = ctx.guild.get_role(role_id) if isinstance(role_id, int) else None
            return role.mention if role else "Admin"

        for category, channel_ids in self.subscriptions.items():
            guild_channels = []
            for ch_id in channel_ids:
                ch = ctx.guild.get_channel(ch_id)
                if ch:
                    guild_channels.append(ch.mention)
            
            if guild_channels:
                found_any = True
                embed.add_field(name=f"**{category.title()}**", value=", ".join(guild_channels), inline=False)
        
        if not found_any:
            embed.description = "❌ No channels in this server are subscribed to any alerts."
        else:
            embed.set_footer(text=f"Managed by role: {get_role_name()}")
            
        await ctx.send(embed=embed)

    @commands.group(brief='Unsubscribe from alerts', invoke_without_command=True)
    async def unsubscribe(self, ctx):
        await ctx.send_help(ctx.command)

    @unsubscribe.command(name='codeforces')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_cf(self, ctx):
        await self._remove_sub(ctx, 'codeforces')

    @unsubscribe.command(name='others')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_others(self, ctx):
        await self._remove_sub(ctx, 'atcoder')
        await self._remove_sub(ctx, 'leetcode')
        await self._remove_sub(ctx, 'codechef')
        await ctx.send("❌ Unsubscribed from AtCoder, LeetCode, and CodeChef.")

    @unsubscribe.command(name='ratings')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_ratings(self, ctx):
        await self._remove_sub(ctx, 'ratings')

    @unsubscribe.command(name='milestones')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_milestones(self, ctx):
        await self._remove_sub(ctx, 'milestones')

    @unsubscribe.command(name='all')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_all(self, ctx):
        for key in self.subscriptions:
            if ctx.channel.id in self.subscriptions[key]:
                self.subscriptions[key].remove(ctx.channel.id)
        self.save_json(ALERTS_FILE, self.subscriptions)
        await ctx.send(f'❌ Unsubscribed `{ctx.channel.name}` from **EVERYTHING**.')

    # --- CLIST: UPCOMING CONTESTS ---
    @commands.command(brief='Show upcoming contests (Next 3 Days)')
    async def upcoming(self, ctx):
        if not CLIST_USER or not CLIST_KEY:
            await ctx.send("❌ Clist API credentials not set in .env")
            return

        async with ctx.typing():
            try:
                now = datetime.datetime.now(datetime.timezone.utc)
                end_time = now + datetime.timedelta(days=3)
                
                # --- FIXED: Removed 'resource_id__in' to allow ALL contests ---
                params = {
                    'username': CLIST_USER,
                    'api_key': CLIST_KEY,
                    'start__gte': now.strftime("%Y-%m-%dT%H:%M:%S"),
                    'start__lt': end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    'order_by': 'start',
                    'limit': 25  # Limit to 25 to fit in Discord Embed limits
                }

                async with aiohttp.ClientSession() as session:
                    async with session.get(CLIST_API_URL, params=params) as resp:
                        if resp.status != 200:
                            await ctx.send(f"❌ Clist API Error: {resp.status}")
                            return
                        data = await resp.json()
                
                if not data['objects']:
                    await ctx.send("📅 No contests found in the next 3 days.")
                    return

                embed = discord.Embed(title="📅 All Upcoming Contests (Next 3 Days)", color=0x0099FF)
                for c in data['objects']:
                    start_dt = datetime.datetime.fromisoformat(c['start']).replace(tzinfo=datetime.timezone.utc)
                    ts = int(start_dt.timestamp())
                    # Format site name nicely
                    site = c['resource'].replace('.com', '').replace('.jp', '').replace('codingcompetitions.withgoogle', 'Google').title()
                    if len(site) > 20: site = site[:20] + "..."
                    
                    embed.add_field(
                        name=f"{site}: {c['event']}",
                        value=f"🕒 <t:{ts}:F> (<t:{ts}:R>)\n[Link]({c['href']})",
                        inline=False
                    )
                
                embed.set_footer(text="Powered by Clist.by")
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"❌ Error: {e}")

    # --- ADMIN HELPERS ---
    @commands.command(brief='Force trigger a rating alert')
    @commands.has_role(constants.TLE_ADMIN)
    async def trigger_alert(self, ctx, contest_id: int):
        await ctx.send(f"🔄 Fetching data for Contest {contest_id}...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{CF_API_URL}/contest.standings?contestId={contest_id}&from=1&count=1") as resp:
                    if resp.status != 200:
                        await ctx.send(f"❌ Contest API Error: {resp.status}")
                        return
                    data = await resp.json()
                    contest = SimpleContest(data['result']['contest'])

                async with session.get(f"{CF_API_URL}/contest.ratingChanges?contestId={contest_id}") as resp:
                    if resp.status != 200:
                        await ctx.send("⚠️ Ratings are not out yet (or contest is unrated).")
                        return
                    data = await resp.json()
                    changes = [SimpleRatingChange(rc) for rc in data['result']]
            
            if not changes:
                await ctx.send("⚠️ Empty rating change list.")
                return

            await self.announce_results(contest, changes)
            await ctx.send("✅ Done.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @commands.command(brief='Simulate a rank up alert')
    @commands.has_role(constants.TLE_ADMIN)
    async def test_milestone(self, ctx, handle: str, rating: int):
        """Simulate what happens when 'handle' reaches 'rating'."""
        await ctx.send(f"🧪 **DEBUG:** Simulating {handle} @ {rating}...")
        avatar = await self.get_user_avatar(handle)
        target_id = ctx.author.id 
        try:
            guild_handles = cf_common.user_db.get_handles_for_guild(ctx.guild.id)
            for h in guild_handles:
                h_handle = h[1] if isinstance(h, tuple) else h.handle
                h_id = h[0] if isinstance(h, tuple) else h.user_id
                if h_handle.lower() == handle.lower():
                    target_id = h_id
                    break
        except:
            pass

        class FakeChange:
            def __init__(self, h, r):
                self.handle = h
                self.newRating = r
                self.oldRating = r - 100 
        
        change = FakeChange(handle, rating)
        new_rank = self.get_rank_name(rating)
        
        await self.send_milestone(ctx.channel, change, new_rank, target_id, avatar)
        await self.trigger_graph(ctx.channel, handle)

    # --- HELPERS ---
    async def get_user_avatar(self, handle):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{CF_API_URL}/user.info?handles={handle}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data['status'] == 'OK':
                            return data['result'][0].get('titlePhoto')
        except:
            return None
        return None

    async def trigger_graph(self, channel, handle):
        try:
            graphs_cog = self.bot.get_cog('Graphs')
            if not graphs_cog: return
            fake_ctx = DuckContext(channel, self.bot)
            if hasattr(graphs_cog, 'rating'):
                await graphs_cog.rating(fake_ctx, handle)
        except:
            pass

    # --- LOGIC ---
    def get_rank_name(self, rating):
        for limit, name, color in CF_RANKS:
            if rating >= limit: return name
        return "Newbie"

    def get_rank_index(self, rating):
        name = self.get_rank_name(rating)
        try: return RANK_ORDER.index(name)
        except: return -1

    async def check_first_time_milestone(self, handle, new_rating):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{CF_API_URL}/user.rating?handle={handle}") as resp:
                    if resp.status != 200: return False
                    data = await resp.json()
                    if data['status'] != 'OK': return False
                    history = data['result']
            
            if len(history) <= 1: return True 
            current_rank_idx = self.get_rank_index(new_rating)
            max_prev_rating = 0
            for i in range(len(history) - 1):
                max_prev_rating = max(max_prev_rating, history[i]['newRating'])
            prev_max_idx = self.get_rank_index(max_prev_rating)
            return current_rank_idx > prev_max_idx
        except:
            return False

    async def send_milestone(self, channel, change, new_rank, user_id, avatar_url=None):
        color = 0x000000
        for limit, name, c in CF_RANKS:
            if name == new_rank:
                color = c
                break
        
        user_mention = f"<@{user_id}>"
        embed = discord.Embed(
            title=f"🎉 Congratulations {change.handle}!",
            description=f"{user_mention} has become a **{new_rank}** for the **FIRST TIME**!\n\nRating: **{change.newRating}**",
            color=color
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)
        else:
            embed.set_thumbnail(url="https://media1.tenor.com/m/n_X5gYfV2XAAAAAC/party-confetti.gif")
            
        try:
            await channel.send(embed=embed)
        except:
            pass

    # --- WATCHERS ---
    @tasks.loop(minutes=15)
    async def watch_contests(self):
        if not CLIST_USER or not CLIST_KEY: return
        current_time = datetime.datetime.now(datetime.timezone.utc)
        try:
            end_time = current_time + datetime.timedelta(days=2)
            # Filter for automatic alerts (RESTRICTED)
            resource_ids = ",".join(str(i) for i in RESOURCE_IDS.values())
            params = {
                'username': CLIST_USER, 'api_key': CLIST_KEY,
                'resource_id__in': resource_ids,
                'start__gte': current_time.strftime("%Y-%m-%dT%H:%M:%S"),
                'start__lt': end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                'order_by': 'start'
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(CLIST_API_URL, params=params) as resp:
                    if resp.status != 200: return
                    data = await resp.json()

            for c in data['objects']:
                site = c['resource']
                sub_key = None
                if 'codeforces' in site: sub_key = 'codeforces'
                elif 'atcoder' in site: sub_key = 'atcoder'
                elif 'codechef' in site: sub_key = 'codechef'
                elif 'leetcode' in site: sub_key = 'leetcode'
                if not sub_key or not self.subscriptions[sub_key]: continue
                start_dt = datetime.datetime.fromisoformat(c['start']).replace(tzinfo=datetime.timezone.utc)
                diff = (start_dt - current_time).total_seconds()
                await self.process_alert(c['id'], c['event'], sub_key, diff, c['href'])
        except Exception as e:
            logger.error(f"Clist Alert Error: {e}")

    async def process_alert(self, uid, name, site_key, diff, url):
        is_24hr = 85500 < diff < 87300
        is_1hr = 3300 < diff < 3900
        is_15min = 600 < diff < 1200
        
        alert_key_24h = f"{uid}_24h"
        alert_key_1h = f"{uid}_1h"
        alert_key_15m = f"{uid}_15m"

        msg_time = ""
        final_key = ""

        if is_24hr and alert_key_24h not in self.already_alerted:
            msg_time = "1 day"
            final_key = alert_key_24h
        elif is_1hr and alert_key_1h not in self.already_alerted:
            msg_time = "1 hour"
            final_key = alert_key_1h
        elif is_15min and alert_key_15m not in self.already_alerted:
            msg_time = "15 minutes"
            final_key = alert_key_15m
        
        if msg_time:
            self.already_alerted.add(final_key)
            colors = {'codeforces': 0xFF0000, 'atcoder': 0x000000, 'codechef': 0xD06919, 'leetcode': 0xFFA116}
            embed = discord.Embed(title=f"🏆 {name}", url=url, description=f"**Site:** {site_key.title()}\n**Starting in:** {msg_time}", color=colors.get(site_key, 0x00FF00))
            for ch_id in self.subscriptions[site_key]:
                ch = self.bot.get_channel(ch_id)
                if ch: 
                    try:
                        await ch.send(embed=embed)
                    except:
                        pass

    @tasks.loop(minutes=15)
    async def watch_rating_changes(self):
        if not self.subscriptions['ratings'] and not self.subscriptions['milestones']: return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{CF_API_URL}/contest.list?gym=false") as resp:
                    if resp.status != 200: return
                    data = await resp.json()
                    contests = [SimpleContest(c) for c in data['result']]

                now = time.time()
                two_weeks_ago = now - (14 * 24 * 60 * 60)
                five_days_ago = now - (5 * 24 * 60 * 60)
                candidates = [c for c in contests if c.phase == 'FINISHED' and c.startTimeSeconds > two_weeks_ago and c.id not in self.processed_contests]

                for contest in candidates:
                    try:
                        async with session.get(f"{CF_API_URL}/contest.ratingChanges?contestId={contest.id}") as resp:
                            if resp.status != 200: continue
                            data = await resp.json()
                            raw_changes = data['result']
                    except: continue
                    
                    if not raw_changes:
                        if contest.startTimeSeconds < five_days_ago:
                            self.processed_contests.append(contest.id)
                            self.save_json(PROCESSED_FILE, self.processed_contests)
                        continue 

                    changes = [SimpleRatingChange(rc) for rc in raw_changes]
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
        all_subs = set(self.subscriptions['ratings'] + self.subscriptions['milestones'])
        for channel_id in all_subs:
            channel = self.bot.get_channel(channel_id)
            if not channel: continue
            
            try:
                guild_handles = cf_common.user_db.get_handles_for_guild(channel.guild.id)
                server_handles = {}
                for h in guild_handles:
                    if isinstance(h, tuple): server_handles[h[1].lower()] = h[0]
                    else: server_handles[h.handle.lower()] = h.user_id
            except: continue

            if channel_id in self.subscriptions['ratings']:
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
                    try:
                        await channel.send(embed=embed)
                    except:
                        pass

            if channel_id in self.subscriptions['milestones']:
                for change in changes:
                    handle_lower = change.handle.lower()
                    if handle_lower in server_handles:
                        old_rank = self.get_rank_name(change.oldRating)
                        new_rank = self.get_rank_name(change.newRating)
                        if old_rank != new_rank and change.newRating > change.oldRating:
                            is_first_time = await self.check_first_time_milestone(change.handle, change.newRating)
                            if is_first_time:
                                avatar = await self.get_user_avatar(change.handle)
                                await self.send_milestone(channel, change, new_rank, server_handles[handle_lower], avatar)
                                await self.trigger_graph(channel, change.handle)

    @watch_contests.before_loop
    @watch_rating_changes.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

def setup(bot):
    bot.add_cog(Alerts(bot))
