import asyncio
import datetime
import json
import logging
import time
from collections import defaultdict

import discord
from discord.ext import commands

from tle.util import codeforces_common as cf_common
from tle.util import discord_common
from tle.util import paginator

_CONTEST_RELOAD_INTERVAL = 60 * 60  # 1 hour
_CONTEST_RELOAD_ACCEPTABLE_DELAY = 15 * 60  # 15 mins
_CONTESTS_PER_PAGE = 5
_PAGINATE_WAIT_TIME = 5 * 60  # 5 minutes


def _parse_timezone(tz_string):
    if len(tz_string) != 6 or tz_string[0] not in '+-' or tz_string[3] != ':':
        raise ValueError()
    hours, minutes = int(tz_string[1:3]), int(tz_string[4:])
    tz = datetime.timezone(datetime.timedelta(hours=hours, minutes=minutes))
    return tz


def _secs_to_days_hrs_mins_secs(secs):
    days, secs = divmod(secs, 60 * 60 * 24)
    hrs, secs = divmod(secs, 60 * 60)
    mins, secs = divmod(secs, 60)
    return days, hrs, mins, secs


def _get_formatted_contest_info(contest, tz):
    start = datetime.datetime.fromtimestamp(contest.startTimeSeconds, tz)
    start = f'{start.strftime("%d %b %y, %H:%M")} {tz}'

    duration_days, duration_hrs, duration_mins, _ = _secs_to_days_hrs_mins_secs(contest.durationSeconds)
    duration = f'{duration_hrs}h {duration_mins}m'
    if duration_days > 0:
        duration = f'{duration_days}d ' + duration

    return contest.name, str(contest.id), start, duration, contest.register_url


def _get_formatted_contest_desc(id_str, start, duration, url, max_duration_len):
    em = '\N{EM QUAD}'
    sq = '\N{WHITE SQUARE WITH UPPER RIGHT QUADRANT}'
    desc = (f'`{em}{id_str}{em}|'
            f'{em}{start}{em}|'
            f'{em}{duration.rjust(max_duration_len, em)}{em}|'
            f'{em}`[`link {sq}`]({url} "Link to contest page")')
    return desc


def _get_embed_fields_from_contests(contests):
    infos = []
    for contest in contests:
        info = _get_formatted_contest_info(contest, datetime.timezone.utc)
        infos.append(info)

    max_duration_len = max(len(duration) for _, _, _, duration, _ in infos)

    fields = []
    for name, id_str, start, duration, url in infos:
        value = _get_formatted_contest_desc(id_str, start, duration, url, max_duration_len)
        fields.append((name, value))
    return fields


async def _send_reminder_at(channel, role, contests, before_secs, send_time):
    delay = send_time - time.time()
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    values = _secs_to_days_hrs_mins_secs(before_secs)
    labels = 'days hrs mins secs'.split()
    before_str = ' '.join(f'{value} {label}' for label, value in zip(labels, values) if value > 0)
    desc = f'About to start in {before_str}'
    embed = discord_common.cf_color_embed(description=desc)
    for name, value in _get_embed_fields_from_contests(contests):
        embed.add_field(name=name, value=value)
    await channel.send(role.mention, embed=embed)


class FutureContests(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.future_contests = None
        self.contest_id_map = {}
        self.start_time_map = defaultdict(list)
        self.task_map = defaultdict(list)
        self.role_converter = commands.RoleConverter()
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.Cog.listener()
    async def on_ready(self):
        # Initial fetch of ccntests
        await self._reload()

        # Schedule contest refresh for future
        asyncio.create_task(self._updater_task())

    async def _updater_task(self):
        while True:
            await asyncio.sleep(_CONTEST_RELOAD_INTERVAL)
            await self._reload()

    async def _reload(self, acceptable_delay=_CONTEST_RELOAD_ACCEPTABLE_DELAY):
        contest_dict = await cf_common.cache.get_contests(acceptable_delay)
        if contest_dict is None:
            self.logger.warning('Could not update cache')
            return
        contests = contest_dict.values()

        now = time.time()
        self.future_contests = [contest for contest in contests if
                                contest.startTimeSeconds and now < contest.startTimeSeconds]
        logging.info(f'Refreshed cache with {len(self.future_contests)} contests')
        self.future_contests.sort(key=lambda c: c.startTimeSeconds)
        self.contest_id_map = {c.id: c for c in self.future_contests}
        self.start_time_map.clear()
        for contest in self.future_contests:
            self.start_time_map[contest.startTimeSeconds].append(contest)
        self._reschedule_all_tasks()

    def _reschedule_all_tasks(self):
        for guild in self.bot.guilds:
            self._reschedule_tasks(guild.id)

    def _reschedule_tasks(self, guild_id):
        for task in self.task_map[guild_id]:
            task.cancel()
        self.task_map[guild_id].clear()
        self.logger.info(f'Tasks for guild {guild_id} cleared')
        if not self.start_time_map:
            return
        settings = cf_common.conn.get_reminder_settings(guild_id)
        if settings is None:
            return
        channel_id, role_id, before = settings
        before = json.loads(before)
        guild = self.bot.get_guild(guild_id)
        channel, role = guild.get_channel(channel_id), guild.get_role(role_id)
        for start_time, contests in self.start_time_map.items():
            for before_mins in before:
                before_secs = 60 * before_mins
                task = asyncio.create_task(
                    _send_reminder_at(channel, role, contests, before_secs, start_time - before_secs))
                self.task_map[guild_id].append(task)
        self.logger.info(f'{len(self.task_map[guild_id])} tasks scheduled for guild {guild_id}')

    def _make_pages(self):
        pages = []
        chunks = [self.future_contests[i: i + _CONTESTS_PER_PAGE]
                  for i in range(0, len(self.future_contests), _CONTESTS_PER_PAGE)]
        for chunk in chunks:
            embed = discord_common.cf_color_embed()
            for name, value in _get_embed_fields_from_contests(chunk):
                embed.add_field(name=name, value=value, inline=False)
            pages.append(('Future contests on Codeforces', embed))
        return pages

    @commands.command(brief='Force contest recache')
    @commands.has_role('Admin')
    async def _recachecontests(self, ctx):
        await self._reload(acceptable_delay=0)
        await ctx.send('Recached contests')

    @commands.command(brief='Show future contests')
    async def future(self, ctx, contest_id: int = None, timezone: str = None):
        """Show all future contests or a specific contest in your timezone."""
        if self.future_contests is None:
            await ctx.send(embed=discord_common.embed_alert('Unable to connect to Codeforces API'))
            return
        if len(self.future_contests) == 0:
            await ctx.send(embed=discord_common.embed_neutral('No contests scheduled'))
            return
        if contest_id is None:
            pages = self._make_pages()
            paginator.paginate(self.bot, ctx.channel, pages, wait_time=_PAGINATE_WAIT_TIME, set_pagenum_footers=True)
        else:
            if contest_id not in self.contest_id_map:
                await ctx.send(embed=discord_common.embed_alert(f'Contest ID `{contest_id}` not in contest list'))
                return
            try:
                tz = _parse_timezone(timezone)
            except ValueError:
                await ctx.send(embed=discord_common.embed_alert('Timezone should be in valid format such as `-09:00`'))
                return
            contest = self.contest_id_map[contest_id]
            name, id_str, start, duration, url = _get_formatted_contest_info(contest, tz)
            desc = _get_formatted_contest_desc(id_str, start, duration, url, len(duration))
            embed = discord_common.cf_color_embed().add_field(name=name, value=desc)
            await ctx.send(embed=embed)

    @commands.group(brief='Commands for contest reminders')
    async def remind(self, ctx):
        pass

    @remind.command(brief='Set reminder settings')
    @commands.has_role('Admin')
    async def here(self, ctx, role: discord.Role, *before: int):
        """Sets reminder channel to current channel, role to the given role, and reminder
        times to the given values in minutes."""
        if not role.mentionable:
            await ctx.send(embed=discord_common.embed_alert('The role for reminders must be mentionable'))
            return
        if not before or any(before_mins <= 0 for before_mins in before):
            return
        cf_common.conn.set_reminder_settings(ctx.guild.id, ctx.channel.id, role.id, json.dumps(before))
        await ctx.send(embed=discord_common.embed_success('Reminder settings saved successfully'))
        self._reschedule_tasks(ctx.guild.id)

    @remind.command(brief='Clear all reminder settings')
    @commands.has_role('Admin')
    async def clear(self, ctx):
        cf_common.conn.clear_reminder_settings(ctx.guild.id)
        await ctx.send(embed=discord_common.embed_success('Reminder settings cleared'))
        self._reschedule_tasks(ctx.guild.id)

    @remind.command(brief='Show reminder settings')
    async def settings(self, ctx):
        """Shows the role, channel and before time settings."""
        settings = cf_common.conn.get_reminder_settings(ctx.guild.id)
        if settings is None:
            await ctx.send(embed=discord_common.embed_neutral('Reminder not set'))
            return
        channel_id, role_id, before = settings
        before = json.loads(before)
        channel, role = ctx.guild.get_channel(channel_id), ctx.guild.get_role(role_id)
        if channel is None:
            await ctx.send(embed=discord_common.embed_alert('The channel set for reminders is no longer available'))
            return
        if role is None:
            await ctx.send(embed=discord_common.embed_alert('The role set for reminders is no longer available'))
            return
        before_str = ', '.join(str(before_mins) for before_mins in before)
        embed = discord_common.embed_success('Current reminder settings')
        embed.add_field(name='Channel', value=channel.mention)
        embed.add_field(name='Role', value=role.mention)
        embed.add_field(name='Before', value=f'At {before_str} mins before contest')
        await ctx.send(embed=embed)

    @remind.command(brief='Subscribe to or unsubscribe from contest reminders',
                    usage='[not]')
    async def me(self, ctx, arg: str = None):
        settings = cf_common.conn.get_reminder_settings(ctx.guild.id)
        if settings is None:
            await ctx.send(
                embed=discord_common.embed_alert('To use this command, reminder settings must be set by an admin'))
            return
        _, role_id, _ = settings
        role = ctx.guild.get_role(role_id)
        if role is None:
            await ctx.send(embed=discord_common.embed_alert('The role set for reminders is no longer available'))
            return

        if arg is None:
            if role in ctx.author.roles:
                await ctx.send(embed=discord_common.embed_neutral('You are already subscribed to contest reminders'))
                return
            await ctx.author.add_roles(role, reason='User subscribed to contest reminders')
            await ctx.send(embed=discord_common.embed_success('Successfully subscribed to contest reminders'))
        elif arg == 'not':
            if role not in ctx.author.roles:
                await ctx.send(embed=discord_common.embed_neutral('You are not subscribed to contest reminders'))
                return
            await ctx.author.remove_roles(role, reason='User unsubscribed from contest reminders')
            await ctx.send(embed=discord_common.embed_success('Successfully unsubscribed from contest reminders'))


def setup(bot):
    bot.add_cog(FutureContests(bot))
