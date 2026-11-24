"""Aggregate acquisition funnel by signup week and campaign source.

  python manage.py funnel_report [--weeks 8] [--by-campaign] [--json] [--min-cell 5]

Read-only. Counts come from existing account, reading, completion and subscription rows plus
first-party signup attribution (accounts.attribution). Cells below --min-cell print as "<N"
so the report never singles out a member. Members without a tagged link appear as "direct".
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.attribution import STAGES, default_window, funnel


class Command(BaseCommand):
    help = 'Print the aggregate acquisition funnel (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--weeks', type=int, default=8)
        parser.add_argument('--by-campaign', action='store_true')
        parser.add_argument('--json', action='store_true', dest='as_json')
        parser.add_argument('--min-cell', type=int, default=5)

    def handle(self, *args, weeks, by_campaign, as_json, min_cell, **options):
        if not 1 <= weeks <= 104:
            raise CommandError('--weeks must be between 1 and 104')
        if min_cell < 5:
            raise CommandError('--min-cell may not be lower than 5')
        since, until = default_window(timezone.now(), weeks)
        rows = funnel(since, until, by_campaign=by_campaign, min_cell=min_cell)
        if as_json:
            self.stdout.write(json.dumps({'since': since.isoformat(), 'until': until.isoformat(),
                                         'min_cell': min_cell, 'rows': rows}, indent=2))
            return
        keys = ['week', 'source'] + (['campaign'] if by_campaign else []) + list(STAGES)
        self.stdout.write('\t'.join(keys))
        for row in rows:
            self.stdout.write('\t'.join(f'<{min_cell}' if row[k] is None else str(row[k]) for k in keys))
        if not rows:
            self.stdout.write(f'No member signups between {since:%Y-%m-%d} and {until:%Y-%m-%d}.')
