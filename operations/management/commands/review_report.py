"""List review items decided in an ISO week, for the owner's weekly report.

  python manage.py review_report --week 2026-W48
"""
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from operations.models import ReviewItem


class Command(BaseCommand):
    help = 'Print one line per review item decided in an ISO week (standing approvals marked).'

    def add_arguments(self, parser):
        parser.add_argument('--week', required=True, help='ISO week, e.g. 2026-W48')

    def handle(self, *args, week, **options):
        match = re.fullmatch(r'(\d{4})-W(\d{2})', week)
        if not match:
            raise CommandError('--week must look like 2026-W48')
        try:
            start = date.fromisocalendar(int(match[1]), int(match[2]), 1)
            end = date.fromisocalendar(int(match[1]), int(match[2]), 7)
        except ValueError:
            raise CommandError('--week is not a valid ISO week')
        for item in ReviewItem.objects.filter(decided_at__date__gte=start, decided_at__date__lte=end).order_by('decided_at', 'ref'):
            self.stdout.write(f"{item.decided_at.date().isoformat()}\t{item.kind}\t{item.ref}\t{item.status}\t{'standing' if item.standing else '-'}")
