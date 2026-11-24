"""Classroom pilot usage: projection sessions per teacher per week (staff-only, read-only).

  python manage.py classroom_report [--weeks 8]
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from learning.classroom import weekly_sessions


class Command(BaseCommand):
    help = 'Classroom sessions per pilot teacher per week (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--weeks', type=int, default=8)

    def handle(self, *args, weeks, **options):
        if not 1 <= weeks <= 104:
            raise CommandError('--weeks must be between 1 and 104')
        now = timezone.now()
        rows = weekly_sessions(now - timedelta(weeks=weeks), now)
        self.stdout.write('week\tteacher\tsessions\ttitles')
        for r in rows:
            self.stdout.write(f"{r['week']}\t{r['teacher']}\t{r['sessions']}\t{r['titles']}")
        if not rows:
            self.stdout.write('No classroom sessions in this window.')
