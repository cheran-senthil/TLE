import asyncio
import datetime
import json
import logging
import random

import discord
from discord.ext import commands

from tle.util import codeforces_common as cf_common
from tle.util import paginator

_RELOAD_INTERVAL = 60 * 60  # 1 hour
_CONTESTS_PER_PAGE = 5
_PAGINATE_WAIT_TIME = 5 * 60  # 5 minutes

_CF_COLORS = [0xFFCA1F, 0x198BCC, 0xFF2020]
_OK_GREEN = 0x00A000


def _parse_timezone(tz_string):
    if len(tz_string) != 6 or tz_string[0] not in '+-' or tz_string[3] != ':':
        raise ValueError()
    hours, minutes = int(tz_string[1:3]), int(tz_string[4:])
    tz = datetime.timezone(datetime.timedelta(hours=hours, minutes=minutes))
    return tz


def _get_formatted_contest_info(contest, tz):
    if tz == datetime.timezone.utc:
        start = datetime.datetime.utcfromtimestamp(contest.startTimeSeconds)
    else:
        start = datetime.datetime.fromtimestamp(contest.startTimeSeconds, tz)
    start = f'{start.strftime("%d %b %y, %H:%M")} {tz}'

    duration_days, rem_secs = divmod(contest.durationSeconds, 60 * 60 * 24)
    duration_hrs, rem_secs = divmod(rem_secs, 60 * 60)
    duration_mins, rem_secs = divmod(rem_secs, 60)
    duration = f'{duration_hrs}h {duration_mins}m'
    if duration_days > 0:
        duration = f'{duration_days}d ' + duration

    url = f'{cf_common.CONTESTS_BASE_URL}{contest.id}'
    return contest.name, str(contest.id), start, duration, url


def _get_formatted_contest_desc(id_str, start, duration, url, max_duration_len):
    em = '\N{EM QUAD}'
    sq = '\N{WHITE SQUARE WITH UPPER RIGHT QUADRANT}'
    desc = (f'`{em}{id_str}{em}|'
            f'{em}{start}{em}|'
            f'{em}{duration.rjust(max_duration_len, em)}{em}|'
            f'{em}`[`link {sq}`]({url} "Link to contest page")')
    return desc


def _embed_with_desc(desc, color=discord.Embed.Empty):
    return discord.Embed(description=desc, color=color)


class FutureContests(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.future_contests = None
        self.contest_id_map = {}
        self.role_converter = commands.RoleConverter()
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.Cog.listener()
    async def on_ready(self):
        await self._reload()
        asyncio.create_task(self._updater_task())

    async def _updater_task(self):
        while True:
            await asyncio.sleep(_RELOAD_INTERVAL)
            await self._reload()

    async def _reload(self):
        contests = await cf_common.cache.get_contests(duration=_RELOAD_INTERVAL)
        if contests is None:
            self.logger.warning('Could not update cache')
            return

        now = datetime.datetime.now().timestamp()
        self.future_contests = [contest for contest in contests if
                                contest.startTimeSeconds and now < contest.startTimeSeconds]

        self.future_contests.sort(key=lambda c: c.startTimeSeconds)
        self.contest_id_map = {c.id: c for c in self.future_contests}

    def _make_pages(self):
        pages = []
        chunks = [self.future_contests[i: i + _CONTESTS_PER_PAGE] for i in
                  range(0, len(self.future_contests), _CONTESTS_PER_PAGE)]
        for i, chunk in enumerate(chunks):
            infos = []
            for contest in chunk:
                info = _get_formatted_contest_info(contest, datetime.timezone.utc)
                infos.append(info)

            max_duration_len = max(len(duration) for _, _, _, duration, _ in infos)

            embed = discord.Embed(color=random.choice(_CF_COLORS))
            for name, id_str, start, duration, url in infos:
                value = _get_formatted_contest_desc(id_str, start, duration, url, max_duration_len)
                embed.add_field(name=name, value=value, inline=False)
            pages.append(('Future contests on Codeforces', embed))
        return pages

    @commands.command(brief='Show future contests')
    async def future(self, ctx, contest_id: int = None, timezone: str = None):
        """Show all future contests or a specific contest in your timezone."""
        if self.future_contests is None:
            await ctx.send(embed=_embed_with_desc('Unable to connect to Codeforces API'))
            return
        if len(self.future_contests) == 0:
            await ctx.send(embed=_embed_with_desc('No contests scheduled'))
            return
        if contest_id:
            if contest_id not in self.contest_id_map:
                await ctx.send(embed=_embed_with_desc('Contest ID not in contest list'))
                return
            try:
                tz = _parse_timezone(timezone)
            except ValueError:
                await ctx.send(embed=_embed_with_desc('Timezone should be in valid format such as `-0900` or `+0530`'))
                return
            contest = self.contest_id_map[contest_id]
            name, id_str, start, duration, url = _get_formatted_contest_info(contest, tz)
            desc = _get_formatted_contest_desc(id_str, start, duration, url, len(duration))
            embed = discord.Embed(color=random.choice(_CF_COLORS)).add_field(name=name, value=desc)
            await ctx.send(embed=embed)
        else:
            pages = self._make_pages()
            paginator.paginate(self.bot, ctx, pages, wait_time=_PAGINATE_WAIT_TIME, set_pagenum_footers=True)

    @commands.group(brief='Commands for contest reminders')
    async def remind(self, ctx):
        pass

    @remind.command(brief='Set reminder settings')
    @commands.has_role('Admin')
    async def here(self, ctx, role: discord.Role, *intervals: int):
        if not role.mentionable:
            await ctx.send(embed=_embed_with_desc('The role for reminders must be mentionable'))
            return
        cf_common.conn.set_reminder_settings(ctx.guild.id, ctx.channel.id, role.id, json.dumps(intervals))
        await ctx.send(embed=_embed_with_desc('Reminder settings saved successfully', color=_OK_GREEN))
        # self._reschedule_reminders(ctx.guild.id)

    @remind.command(brief='Clear all reminder settings')
    @commands.has_role('Admin')
    async def clear(self, ctx):
        cf_common.conn.clear_reminder_settings(ctx.guild.id)
        await ctx.send(embed=_embed_with_desc('Reminder settings cleared', color=_OK_GREEN))

    @remind.command(brief='Subscribe to or unsubscribe from contest reminders',
                    usage='[not]')
    async def me(self, ctx, arg: str = None):
        _, role_id, _ = cf_common.conn.get_reminder_settings(ctx.guild.id)
        if not role_id:
            await ctx.send(
                embed=_embed_with_desc('To use this command, the reminder role needs to be set first by an admin'))
            return
        try:
            role = await self.role_converter.convert(ctx, str(role_id))
        except commands.CommandError:
            await ctx.send(embed=_embed_with_desc('The role set as reminder role is no longer available'))
            return

        if arg is None:
            if role in ctx.author.roles:
                await ctx.send(embed=_embed_with_desc('You are already subscribed to contest reminders'))
                return
            await ctx.author.add_roles(role, reason='User subscribed to contest reminders')
            await ctx.send(embed=_embed_with_desc('Successfully subscribed to contest reminders', color=_OK_GREEN))
        elif arg == 'not':
            if role not in ctx.author.roles:
                await ctx.send(embed=_embed_with_desc('You are not subscribed to reminders'))
                return
            await ctx.author.remove_roles(role, reason='User unsubscribed from contest reminders')
            await ctx.send(embed=_embed_with_desc('Successfully unsubscribed from contest reminders', color=_OK_GREEN))


def setup(bot):
    bot.add_cog(FutureContests(bot))
