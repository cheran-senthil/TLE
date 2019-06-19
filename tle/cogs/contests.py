import asyncio
import datetime
import functools
import json
import logging
import time
from collections import defaultdict

import discord
from discord.ext import commands

from tle.util import codeforces_common as cf_common
from tle.util import cache_system2
from tle.util import db
from tle.util import discord_common
from tle.util import paginator
from tle.util import ranklist as rl
from tle.util import table

_CONTESTS_PER_PAGE = 5
_CONTEST_PAGINATE_WAIT_TIME = 5 * 60
_STANDINGS_PER_PAGE = 15
_STANDINGS_PAGINATE_WAIT_TIME = 2 * 60


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


class Contests(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.future_contests = None
        self.contest_id_map = {}
        self.start_time_map = defaultdict(list)
        self.task_map = defaultdict(list)

        self.member_converter = commands.MemberConverter()
        self.role_converter = commands.RoleConverter()

        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self._updater_task())

    async def _updater_task(self):
        self.logger.info('Running Contests cog updater task')
        while True:
            try:
                await cf_common.event_sys.wait_for('EVENT_CONTEST_LIST_REFRESH')
                await self._reload()
            except Exception:
                self.logger.warning(f'Exception in Contests cog updater task, ignoring.', exc_info=True)

    async def _reload(self):
        self.future_contests = cf_common.cache2.contest_cache.get_contests_in_phase('BEFORE')
        self.logger.info(f'Refreshed cache with {len(self.future_contests)} contests')
        self.contest_id_map = {c.id: c for c in self.future_contests}
        self.start_time_map.clear()
        for contest in self.future_contests:
            if not cf_common.is_nonstandard_contest(contest):
                # Exclude non-standard contests from reminders.
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
        try:
            settings = cf_common.user_db.get_reminder_settings(guild_id)
        except db.DatabaseDisabledError:
            return
        if settings is None:
            return
        channel_id, role_id, before = settings
        channel_id, role_id, before = int(channel_id), int(role_id), json.loads(before)
        guild = self.bot.get_guild(guild_id)
        channel, role = guild.get_channel(channel_id), guild.get_role(role_id)
        for start_time, contests in self.start_time_map.items():
            for before_mins in before:
                before_secs = 60 * before_mins
                task = asyncio.create_task(
                    _send_reminder_at(channel, role, contests, before_secs, start_time - before_secs))
                self.task_map[guild_id].append(task)
        self.logger.info(f'{len(self.task_map[guild_id])} tasks scheduled for guild {guild_id}')

    def _make_contest_pages(self):
        pages = []
        chunks = paginator.chunkify(self.future_contests, _CONTESTS_PER_PAGE)
        for chunk in chunks:
            embed = discord_common.cf_color_embed()
            for name, value in _get_embed_fields_from_contests(chunk):
                embed.add_field(name=name, value=value, inline=False)
            pages.append(('Future contests on Codeforces', embed))
        return pages

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
            pages = self._make_contest_pages()
            paginator.paginate(self.bot, ctx.channel, pages, wait_time=_CONTEST_PAGINATE_WAIT_TIME,
                               set_pagenum_footers=True)
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

    @commands.group(brief='Commands for contest reminders',
                    invoke_without_command=True)
    async def remind(self, ctx):
        await ctx.send_help('remind')

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
        cf_common.user_db.set_reminder_settings(ctx.guild.id, ctx.channel.id, role.id, json.dumps(before))
        await ctx.send(embed=discord_common.embed_success('Reminder settings saved successfully'))
        self._reschedule_tasks(ctx.guild.id)

    @remind.command(brief='Clear all reminder settings')
    @commands.has_role('Admin')
    async def clear(self, ctx):
        cf_common.user_db.clear_reminder_settings(ctx.guild.id)
        await ctx.send(embed=discord_common.embed_success('Reminder settings cleared'))
        self._reschedule_tasks(ctx.guild.id)

    @remind.command(brief='Show reminder settings')
    async def settings(self, ctx):
        """Shows the role, channel and before time settings."""
        settings = cf_common.user_db.get_reminder_settings(ctx.guild.id)
        if settings is None:
            await ctx.send(embed=discord_common.embed_neutral('Reminder not set'))
            return
        channel_id, role_id, before = settings
        channel_id, role_id, before = int(channel_id), int(role_id), json.loads(before)
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
        settings = cf_common.user_db.get_reminder_settings(ctx.guild.id)
        if settings is None:
            await ctx.send(
                embed=discord_common.embed_alert('To use this command, reminder settings must be set by an admin'))
            return
        _, role_id, _ = settings
        role = ctx.guild.get_role(int(role_id))
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

    @staticmethod
    def _get_cf_or_ioi_standings_table(problem_indices, handle_standings, deltas=None, *, mode):
        assert mode in ('cf', 'ioi')

        def maybe_int(value):
            return int(value) if mode == 'cf' else value

        header_style = '{:>} {:<}    {:^}  ' + '  '.join(['{:^}'] * len(problem_indices))
        body_style = '{:>} {:<}    {:>}  ' + '  '.join(['{:>}'] * len(problem_indices))
        header = ['#', 'Handle', '='] + problem_indices
        if deltas:
            header_style += '  {:^}'
            body_style += '  {:>}'
            header += ['\N{INCREMENT}']

        body = []
        for handle, standing in handle_standings:
            virtual = '#' if standing.party.participantType == 'VIRTUAL' else ''
            tokens = [standing.rank, handle + ':' + virtual, maybe_int(standing.points)]
            for problem_result in standing.problemResults:
                score = ''
                if problem_result.points:
                    score = str(maybe_int(problem_result.points))
                tokens.append(score)
            body.append(tokens)

        if deltas:
            for tokens, delta in zip(body, deltas):
                tokens.append('' if delta is None else f'{delta:+}')
        return header_style, body_style, header, body

    @staticmethod
    def _get_icpc_standings_table(problem_indices, handle_standings, deltas=None):
        header_style = '{:>} {:<}    {:^}  {:^}  ' + '  '.join(['{:^}'] * len(problem_indices))
        body_style = '{:>} {:<}    {:>}  {:>}  ' + '  '.join(['{:<}'] * len(problem_indices))
        header = ['#', 'Handle', '=', '-'] + problem_indices
        if deltas:
            header_style += '  {:^}'
            body_style += '  {:>}'
            header += ['\N{INCREMENT}']

        body = []
        for handle, standing in handle_standings:
            virtual = '#' if standing.party.participantType == 'VIRTUAL' else ''
            tokens = [standing.rank, handle + ':' + virtual, int(standing.points), int(standing.penalty)]
            for problem_result in standing.problemResults:
                score = '+' if problem_result.points else ''
                if problem_result.rejectedAttemptCount:
                    penalty = str(problem_result.rejectedAttemptCount)
                    if problem_result.points:
                        score += penalty
                    else:
                        score = '-' + penalty
                tokens.append(score)
            body.append(tokens)

        if deltas:
            for tokens, delta in zip(body, deltas):
                tokens.append('' if delta is None else f'{delta:+}')
        return header_style, body_style, header, body

    def _make_standings_pages(self, contest, problem_indices, handle_standings, deltas=None):
        pages = []
        handle_standings_chunks = paginator.chunkify(handle_standings, _STANDINGS_PER_PAGE)
        num_chunks = len(handle_standings_chunks)
        delta_chunks = paginator.chunkify(deltas, _STANDINGS_PER_PAGE) if deltas else [None] * num_chunks

        if contest.type == 'CF':
            get_table = functools.partial(self._get_cf_or_ioi_standings_table, mode='cf')
        elif contest.type == 'ICPC':
            get_table = self._get_icpc_standings_table
        elif contest.type == 'IOI':
            get_table = functools.partial(self._get_cf_or_ioi_standings_table, mode='ioi')
        else:
            assert False, f'Unexpected contest type {contest.type}'

        num_pages = 1
        for handle_standings_chunk, delta_chunk in zip(handle_standings_chunks, delta_chunks):
            header_style, body_style, header, body = get_table(problem_indices,
                                                               handle_standings_chunk,
                                                               delta_chunk)
            t = table.Table(table.Style(header=header_style, body=body_style))
            t += table.Header(*header)
            t += table.Line('\N{EM DASH}')
            for row in body:
                t += table.Data(*row)
            t += table.Line('\N{EM DASH}')
            page_num_footer = f' # Page: {num_pages} / {num_chunks}' if num_chunks > 1 else ''

            # We use yaml to get nice colors in the ranklist.
            content = f'```yaml\n{t}\n{page_num_footer}```'
            pages.append((content, None))
            num_pages += 1

        return pages

    @commands.command(brief='Show ranklist for given handles and/or server members')
    async def ranklist(self, ctx, contest_id: int, *handles: str):
        """Shows ranklist for the contest with given contest id. If handles contains
        '+server', all server members are included. No handles defaults to '+server'.
        """

        contest = cf_common.cache2.contest_cache.get_contest(contest_id)
        wait_msg = None
        try:
            ranklist = cf_common.cache2.ranklist_cache.get_ranklist(contest)
            deltas_status = 'Predicted'
        except cache_system2.RanklistNotMonitored:
            wait_msg = await ctx.send('Please wait...')
            ranklist = await cf_common.cache2.ranklist_cache.generate_ranklist(contest.id,
                                                                               fetch_changes=True)
            deltas_status = 'Final'

        handles = set(handles)
        if not handles:
            handles.add('+server')
        if '+server' in handles:
            handles.remove('+server')
            guild_handles = [handle for discord_id, handle
                             in cf_common.user_db.get_handles_for_guild(ctx.guild.id)]
            handles.update(guild_handles)
        handles = await cf_common.resolve_handles(ctx, self.member_converter, handles, maxcnt=100)

        handle_standings = []
        for handle in handles:
            try:
                standing = ranklist.get_standing_row(handle)
            except rl.HandleNotPresentError:
                continue
            handle_standings.append((handle, standing))

        if not handle_standings:
            msg = f'None of the handles are present in the ranklist of `{contest.name}`'
            await ctx.send(embed=discord_common.embed_alert(msg))
            return

        handle_standings.sort(key=lambda data: data[1].rank)
        deltas = None
        if ranklist.is_rated:
            deltas = [ranklist.get_delta(handle) for handle, standing in handle_standings]

        problem_indices = [problem.index for problem in ranklist.problems]
        pages = self._make_standings_pages(contest, problem_indices, handle_standings, deltas)

        embed = discord_common.cf_color_embed(title=contest.name, url=contest.url)
        phase = contest.phase.lower().capitalize().replace('_', ' ')
        embed.add_field(name='Phase', value=phase)
        if ranklist.is_rated:
            embed.add_field(name='Deltas', value=deltas_status)

        if wait_msg:
            try:
                await wait_msg.delete()
            except:
                pass

        await ctx.send(embed=embed)
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=_STANDINGS_PAGINATE_WAIT_TIME)

    async def cog_command_error(self, ctx, error):
        await cf_common.cf_handle_error_handler(ctx, error)
        if isinstance(error, (rl.RanklistError, cache_system2.CacheError)):
            await ctx.send(embed=discord_common.embed_alert(str(error)))
            error.handled = True


def setup(bot):
    bot.add_cog(Contests(bot))
