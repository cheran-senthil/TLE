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

# APIs
KONTESTS_URL = "https://kontests.net/api/v1/all"
CF_API_URL = "https://codeforces.com/api"
ATCODER_API_URL = "https://kenkoooo.com/atcoder/resources/contests.json"

# CF Ranks (Descending Order)
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
                            if key not in data: data[key] = []
                    return data
            except: return default
        return default

    def save_json(self, filename, data):
        with open(filename, 'w') as f: json.dump(data, f)

    async def _add_sub(self, ctx, key):
        if ctx.channel.id not in self.subscriptions[key]:
            self.subscriptions[key].append(ctx.channel.id)
            self.save_json(ALERTS_FILE, self.subscriptions)
            await ctx.send(f'✅ Subscribed `{ctx.channel.name}` to **{key.title()}**.')
        else: await ctx.send(f'⚠️ Already subscribed to {key.title()}.')

    async def _remove_sub(self, ctx, key):
        if ctx.channel.id in self.subscriptions[key]:
            self.subscriptions[key].remove(ctx.channel.id)
            self.save_json(ALERTS_FILE, self.subscriptions)
            await ctx.send(f'❌ Unsubscribed `{ctx.channel.name}` from **{key.title()}**.')
        else: await ctx.send(f'⚠️ `{ctx.channel.name}` is not subscribed to {key.title()}.')

    # --- SUBSCRIBE COMMANDS ---
    @commands.group(brief='Subscribe to alerts', invoke_without_command=True)
    async def subscribe(self, ctx): await ctx.send_help(ctx.command)

    @subscribe.command(brief='Codeforces Contest Reminders')
    @commands.has_role(constants.TLE_ADMIN)
    async def codeforces(self, ctx): await self._add_sub(ctx, 'codeforces')

    @subscribe.command(brief='AtCoder/LC/CodeChef Reminders')
    @commands.has_role(constants.TLE_ADMIN)
    async def others(self, ctx):
        await self._add_sub(ctx, 'atcoder')
        await self._add_sub(ctx, 'leetcode')
        await self._add_sub(ctx, 'codechef')
        await ctx.send("✅ Subscribed to AtCoder, LeetCode, and CodeChef.")

    @subscribe.command(brief='Ranklist & Rating Updates')
    @commands.has_role(constants.TLE_ADMIN)
    async def ratings(self, ctx): await self._add_sub(ctx, 'ratings')

    @subscribe.command(brief='Milestones (Rank Ups)')
    @commands.has_role(constants.TLE_ADMIN)
    async def milestones(self, ctx):
        await self._add_sub(ctx, 'milestones')
        await ctx.send("🎉 This channel will celebrate new **Codeforces Rank Ups** with graphs!")

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
                if ch: guild_channels.append(ch.mention)
            if guild_channels:
                found_any = True
                embed.add_field(name=f"**{category.title()}**", value=", ".join(guild_channels), inline=False)
        
        if not found_any: embed.description = "❌ No channels in this server are subscribed to any alerts."
        else: embed.set_footer(text=f"Managed by role: {get_role_name()}")
        await ctx.send(embed=embed)

    # --- UNSUBSCRIBE COMMANDS ---
    @commands.group(brief='Unsubscribe from alerts', invoke_without_command=True)
    async def unsubscribe(self, ctx): await ctx.send_help(ctx.command)

    @unsubscribe.command(name='codeforces')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_cf(self, ctx): await self._remove_sub(ctx, 'codeforces')

    @unsubscribe.command(name='others')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_others(self, ctx):
        await self._remove_sub(ctx, 'atcoder')
        await self._remove_sub(ctx, 'leetcode')
        await self._remove_sub(ctx, 'codechef')
        await ctx.send("❌ Unsubscribed from AtCoder, LeetCode, and CodeChef.")

    @unsubscribe.command(name='ratings')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_ratings(self, ctx): await self._remove_sub(ctx, 'ratings')

    @unsubscribe.command(name='milestones')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_milestones(self, ctx): await self._remove_sub(ctx, 'milestones')

    @unsubscribe.command(name='all')
    @commands.has_role(constants.TLE_ADMIN)
    async def unsub_all(self, ctx):
        for key in self.subscriptions:
            if ctx.channel.id in self.subscriptions[key]:
                self.subscriptions[key].remove(ctx.channel.id)
        self.save_json(ALERTS_FILE, self.subscriptions)
        await ctx.send(f'❌ Unsubscribed `{ctx.channel.name}` from **EVERYTHING**.')

    # --- HELPER: FETCH PROFILE PIC ---
    async def get_user_avatar(self, handle):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{CF_API_URL}/user.info?handles={handle}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data['status'] == 'OK':
                            return data['result'][0].get('titlePhoto')
        except: return None
        return None

    # --- DEBUG / TEST COMMAND ---
    @commands.command(brief='Simulate a rank up alert (Debug)')
    @commands.has_role(constants.TLE_ADMIN)
    async def test_milestone(self, ctx, handle: str, rating: int):
        """Simulate what happens when 'handle' reaches 'rating'."""
        await ctx.send(f"🧪 **DEBUG MODE:** Simulating {handle} reaching rating {rating}...")
        
        avatar = await self.get_user_avatar(handle)

        class FakeChange:
            def __init__(self, h, r):
                self.handle = h
                self.newRating = r
                self.oldRating = r - 100 
        
        change = FakeChange(handle, rating)
        new_rank = self.get_rank_name(rating)
        
        await self.send_milestone(ctx.channel, change, new_rank, ctx.author.id, avatar)
        
        # Trigger graph
        plot_cmd = self.bot.get_command('plot rating')
        if plot_cmd:
            try: await ctx.invoke(plot_cmd, handles=[handle])
            except: await ctx.send("*(Graph command failed to invoke automatically)*")

    # --- WATCHER LOOP ---
    @tasks.loop(minutes=5)
    async def watch_contests(self):
        current_time = datetime.datetime.now(datetime.timezone.utc)
        if self.subscriptions['codeforces']:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{CF_API_URL}/contest.list?gym=false") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data['status'] == 'OK':
                                upcoming_cf = [c for c in data['result'] if c['phase'] == 'BEFORE']
                                for c in upcoming_cf:
                                    start_time = datetime.datetime.fromtimestamp(c['startTimeSeconds'], datetime.timezone.utc)
                                    diff = (start_time - current_time).total_seconds()
                                    await self.process_alert(c['id'], c['name'], "codeforces", diff, f"https://codeforces.com/contests/{c['id']}")
            except: pass

        if self.subscriptions['atcoder']:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(ATCODER_API_URL) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            now_ts = current_time.timestamp()
                            upcoming_ac = [c for c in data if c['start_epoch_second'] > now_ts]
                            for c in upcoming_ac:
                                diff = c['start_epoch_second'] - now_ts
                                c_url = f"https://atcoder.jp/contests/{c['id']}"
                                await self.process_alert(c['id'], c['title'], "atcoder", diff, c_url)
            except: pass

        if any(self.subscriptions[k] for k in ['leetcode', 'codechef']):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(KONTESTS_URL, ssl=False, timeout=10) as resp:
                        if resp.status == 200:
                            all_contests = await resp.json()
                            site_map = {'CodeChef': 'codechef', 'LeetCode': 'leetcode'}
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
                    try: await ch.send(embed=embed)
                    except: pass

    # --- WATCHER: RATINGS ---
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

            # Ranklist
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
                    try: await channel.send(embed=embed)
                    except: pass

            # Milestones
            if channel_id in self.subscriptions['milestones']:
                for change in changes:
                    handle_lower = change.handle.lower()
                    if handle_lower in server_handles:
                        old_rank = self.get_rank_name(change.oldRating)
                        new_rank = self.get_rank_name(change.newRating)
                        if old_rank != new_rank and change.newRating > change.oldRating:
                            avatar = await self.get_user_avatar(change.handle)
                            await self.send_milestone(channel, change, new_rank, server_handles[handle_lower], avatar)
                            
                            # Graph Trigger
                            plot_cmd = self.bot.get_command('plot rating')
                            if plot_cmd:
                                ctx = await self.bot.get_context(await channel.send("Generating graph..."))
                                try: await ctx.invoke(plot_cmd, handles=[change.handle])
                                except: pass

    def get_rank_name(self, rating):
        # Descending order check
        for limit, name, color in CF_RANKS:
            if rating >= limit: return name
        return "Newbie"

    async def send_milestone(self, channel, change, new_rank, user_id, avatar_url=None):
        color = 0x000000
        for limit, name, c in CF_RANKS:
            if name == new_rank:
                color = c
                break
        
        user_mention = f"<@{user_id}>"
        embed = discord.Embed(
            title=f"🎉 Congratulations {change.handle}!",
            description=f"{user_mention} has become a **{new_rank}**!\n\nRating: **{change.newRating}**",
            color=color
        )
        if avatar_url: embed.set_thumbnail(url=avatar_url)
        else: embed.set_thumbnail(url="https://media1.tenor.com/m/n_X5gYfV2XAAAAAC/party-confetti.gif")
        try: await channel.send(embed=embed)
        except: pass

    @watch_contests.before_loop
    @watch_rating_changes.before_loop
    async def before_loops(self): await self.bot.wait_until_ready()

def setup(bot): bot.add_cog(Alerts(bot))
