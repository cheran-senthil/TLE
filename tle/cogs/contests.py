import asyncio
import functools
import json
import logging
import time
import datetime as dt

from collections import defaultdict

import discord
from discord.ext import commands

from tle.util import codeforces_common as cf_common
from tle.util import cache_system2
from tle.util import db
from tle.util import discord_common
from tle.util import events
from tle.util import paginator
from tle.util import ranklist as rl
from tle.util import table
from tle.util import tasks

_CONTESTS_PER_PAGE = 5
_CONTEST_PAGINATE_WAIT_TIME = 5 * 60
_STANDINGS_PER_PAGE = 15
_STANDINGS_PAGINATE_WAIT_TIME = 2 * 60
_FINISHED_CONTESTS_LIMIT = 5


class ContestCogError(commands.CommandError):
    pass


def _contest_start_time_format(contest, tz):
    start = dt.datetime.fromtimestamp(contest.startTimeSeconds, tz)
    return f'{start.strftime("%d %b %y, %H:%M")} {tz}'


def _contest_duration_format(contest):
    duration_days, duration_hrs, duration_mins, _ = cf_common.time_format(contest.durationSeconds)
    duration = f'{duration_hrs}h {duration_mins}m'
    if duration_days > 0:
        duration = f'{duration_days}d ' + duration
    return duration


def _get_formatted_contest_desc(id_str, start, duration, url, max_duration_len):
    em = '\N{EN SPACE}'
    sq = '\N{WHITE SQUARE WITH UPPER RIGHT QUADRANT}'
    desc = (f'`{em}{id_str}{em}|'
            f'{em}{start}{em}|'
            f'{em}{duration.rjust(max_duration_len, em)}{em}|'
            f'{em}`[`link {sq}`]({url} "Link to contest page")')
    return desc


def _get_embed_fields_from_contests(contests):
    infos = [(contest.name, str(contest.id), _contest_start_time_format(contest, dt.timezone.utc),
              _contest_duration_format(contest), contest.register_url)
             for contest in contests]

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
    values = cf_common.time_format(before_secs)

    def make(value, label):
        tmp = f'{value} {label}'
        return tmp if value == 1 else tmp + 's'

    labels = 'day hr min sec'.split()
    before_str = ' '.join(make(value, label) for label, value in zip(labels, values) if value > 0)
    desc = f'About to start in {before_str}'
    embed = discord_common.cf_color_embed(description=desc)
    for name, value in _get_embed_fields_from_contests(contests):
        embed.add_field(name=name, value=value)
    await channel.send(role.mention, embed=embed)


class Contests(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.future_contests = None
        self.active_contests = None
        self.finished_contests = None
        self.start_time_map = defaultdict(list)
        self.task_map = defaultdict(list)

        self.member_converter = commands.MemberConverter()
        self.role_converter = commands.RoleConverter()

        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.Cog.listener()
    async def on_ready(self):
        self._update_task.start()

    @tasks.task_spec(name='ContestCogUpdate',
                     waiter=tasks.Waiter.for_event(events.ContestListRefresh))
    async def _update_task(self, _):
        contest_cache = cf_common.cache2.contest_cache
        self.future_contests = contest_cache.get_contests_in_phase('BEFORE')
        self.active_contests = (contest_cache.get_contests_in_phase('CODING') +
                                contest_cache.get_contests_in_phase('PENDING_SYSTEM_TEST') +
                                contest_cache.get_contests_in_phase('SYSTEM_TEST'))
        self.finished_contests = contest_cache.get_contests_in_phase('FINISHED')

        # Future contests already sorted by start time.
        self.active_contests.sort(key=lambda contest: contest.startTimeSeconds)
        self.finished_contests.sort(key=lambda contest: contest.end_time, reverse=True)
        # Keep most recent _FINISHED_LIMIT
        self.finished_contests = self.finished_contests[:_FINISHED_CONTESTS_LIMIT]

        self.logger.info(f'Refreshed cache')
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

    @staticmethod
    def _make_contest_pages(contests, title):
        pages = []
        chunks = paginator.chunkify(contests, _CONTESTS_PER_PAGE)
        for chunk in chunks:
            embed = discord_common.cf_color_embed()
            for name, value in _get_embed_fields_from_contests(chunk):
                embed.add_field(name=name, value=value, inline=False)
            pages.append((title, embed))
        return pages

    async def _send_contest_list(self, ctx, contests, *, title, empty_msg):
        if contests is None:
            raise ContestCogError('Contest list not present')
        if len(contests) == 0:
            await ctx.send(embed=discord_common.embed_neutral(empty_msg))
            return
        pages = self._make_contest_pages(contests, title)
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=_CONTEST_PAGINATE_WAIT_TIME,
                           set_pagenum_footers=True)

    @commands.group(brief='Commands for listing contests',
                    invoke_without_command=True)
    async def clist(self, ctx):
        await ctx.send_help(ctx.command)

    @clist.command(brief='List future contests')
    async def future(self, ctx):
        """List future contests on Codeforces."""
        await self._send_contest_list(ctx, self.future_contests,
                                      title='Future contests on Codeforces',
                                      empty_msg='No future contests scheduled')

    @clist.command(brief='List active contests')
    async def active(self, ctx):
        """List active contests on Codeforces, namely those in coding phase, pending system
        test or in system test."""
        await self._send_contest_list(ctx, self.active_contests,
                                      title='Active contests on Codeforces',
                                      empty_msg='No contests currently active')

    @clist.command(brief='List recent finished contests')
    async def finished(self, ctx):
        """List recently concluded contests on Codeforces."""
        await self._send_contest_list(ctx, self.finished_contests,
                                      title='Recently finished contests on Codeforces',
                                      empty_msg='No finished contests found')

    @commands.group(brief='Commands for contest reminders',
                    invoke_without_command=True)
    async def remind(self, ctx):
        await ctx.send_help(ctx.command)

    @remind.command(brief='Set reminder settings')
    @commands.has_role('Admin')
    async def here(self, ctx, role: discord.Role, *before: int):
        """Sets reminder channel to current channel, role to the given role, and reminder
        times to the given values in minutes."""
        if not role.mentionable:
            raise ContestCogError('The role for reminders must be mentionable')
        if not before or any(before_mins <= 0 for before_mins in before):
            raise ContestCogError('Please provide valid `before` values')
        before = sorted(before, reverse=True)
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
            raise ContestCogError('The channel set for reminders is no longer available')
        if role is None:
            raise ContestCogError('The role set for reminders is no longer available')
        before_str = ', '.join(str(before_mins) for before_mins in before)
        embed = discord_common.embed_success('Current reminder settings')
        embed.add_field(name='Channel', value=channel.mention)
        embed.add_field(name='Role', value=role.mention)
        embed.add_field(name='Before', value=f'At {before_str} mins before contest')
        await ctx.send(embed=embed)

    @staticmethod
    def _get_remind_role(guild):
        settings = cf_common.user_db.get_reminder_settings(guild.id)
        if settings is None:
            raise ContestCogError('Reminders are not enabled.')
        _, role_id, _ = settings
        role = guild.get_role(int(role_id))
        if role is None:
            raise ContestCogError('The role set for reminders is no longer available.')
        return role

    @remind.command(brief='Subscribe to contest reminders')
    async def on(self, ctx):
        """Subscribes you to contest reminders. Use ';remind settings' to see the current
        settings.
        """
        role = self._get_remind_role(ctx.guild)
        if role in ctx.author.roles:
            embed = discord_common.embed_neutral('You are already subscribed to contest reminders')
        else:
            await ctx.author.add_roles(role, reason='User subscribed to contest reminders')
            embed = discord_common.embed_success('Successfully subscribed to contest reminders')
        await ctx.send(embed=embed)

    @remind.command(brief='Unsubscribe from contest reminders')
    async def off(self, ctx):
        """Unsubscribes you from contest reminders."""
        role = self._get_remind_role(ctx.guild)
        if role not in ctx.author.roles:
            embed = discord_common.embed_neutral('You are not subscribed to contest reminders')
        else:
            await ctx.author.remove_roles(role, reason='User unsubscribed from contest reminders')
            embed = discord_common.embed_success('Successfully unsubscribed from contest reminders')
        await ctx.send(embed=embed)

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

    @staticmethod
    def _make_contest_embed_for_ranklist(ranklist):
        contest = ranklist.contest
        assert contest.phase != 'BEFORE', f'Contest {contest.id} has not started.'
        embed = discord_common.cf_color_embed(title=contest.name, url=contest.url)
        phase = contest.phase.capitalize().replace('_', ' ')
        embed.add_field(name='Phase', value=phase)
        if ranklist.is_rated:
            embed.add_field(name='Deltas', value=ranklist.deltas_status)
        now = time.time()
        en = '\N{EN SPACE}'
        if contest.phase == 'CODING':
            elapsed = cf_common.pretty_time_format(now - contest.startTimeSeconds, shorten=True)
            remaining = cf_common.pretty_time_format(contest.end_time - now, shorten=True)
            msg = f'{elapsed} elapsed{en}|{en}{remaining} remaining'
            embed.add_field(name='Tick tock', value=msg, inline=False)
        else:
            start = _contest_start_time_format(contest, dt.timezone.utc)
            duration = _contest_duration_format(contest)
            since = cf_common.pretty_time_format(now - contest.end_time, only_most_significant=True)
            msg = f'{start}{en}|{en}{duration}{en}|{en}Ended {since} ago'
            embed.add_field(name='When', value=msg, inline=False)
        return embed

    @commands.command(brief='Show ranklist for given handles and/or server members')
    async def ranklist(self, ctx, contest_id: int, *handles: str):
        """Shows ranklist for the contest with given contest id. If handles contains
        '+server', all server members are included. No handles defaults to '+server'.
        """

        contest = cf_common.cache2.contest_cache.get_contest(contest_id)
        wait_msg = None
        try:
            ranklist = cf_common.cache2.ranklist_cache.get_ranklist(contest)
        except cache_system2.RanklistNotMonitored:
            if contest.phase == 'BEFORE':
                raise ContestCogError(f'Contest `{contest.id} | {contest.name}` has not started')
            wait_msg = await ctx.send('Please wait...')
            ranklist = await cf_common.cache2.ranklist_cache.generate_ranklist(contest.id,
                                                                               fetch_changes=True)

        handles = set(handles)
        if not handles:
            handles.add('+server')
        if '+server' in handles:
            handles.remove('+server')
            guild_handles = [handle for discord_id, handle
                             in cf_common.user_db.get_handles_for_guild(ctx.guild.id)]
            handles.update(guild_handles)
        handles = await cf_common.resolve_handles(ctx, self.member_converter, handles, maxcnt=None)

        handle_standings = []
        for handle in handles:
            try:
                standing = ranklist.get_standing_row(handle)
            except rl.HandleNotPresentError:
                continue
            handle_standings.append((handle, standing))

        if not handle_standings:
            raise ContestCogError(f'None of the handles are present in the ranklist of `{contest.name}`')

        handle_standings.sort(key=lambda data: data[1].rank)
        deltas = None
        if ranklist.is_rated:
            deltas = [ranklist.get_delta(handle) for handle, standing in handle_standings]

        problem_indices = [problem.index for problem in ranklist.problems]
        pages = self._make_standings_pages(contest, problem_indices, handle_standings, deltas)

        if wait_msg:
            try:
                await wait_msg.delete()
            except:
                pass

        await ctx.send(embed=self._make_contest_embed_for_ranklist(ranklist))
        paginator.paginate(self.bot, ctx.channel, pages, wait_time=_STANDINGS_PAGINATE_WAIT_TIME)

    @discord_common.send_error_if(ContestCogError, rl.RanklistError,
                                  cache_system2.CacheError,  cf_common.ResolveHandleError)
    async def cog_command_error(self, ctx, error):
        pass


def setup(bot):
    bot.add_cog(Contests(bot))
