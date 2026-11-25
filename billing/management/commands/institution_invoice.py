"""Issue one yearly per-class institution invoice.

  python manage.py institution_invoice --institution "Greenfield School" --classes 3 --students 90 --period-start 2027-04-01 --by <staff email>
"""
from datetime import date
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from billing.institution import issue_institution_invoice
from core.api import DomainError

DEFAULT_PRICE_MINOR = 20000  # pilot price hypothesis (INR minor units per student per year); a command default only


class Command(BaseCommand):
    help = f'Issue a yearly institution invoice (audited). Default price per student: {DEFAULT_PRICE_MINOR} minor units.'

    def add_arguments(self, parser):
        parser.add_argument('--institution', required=True)
        parser.add_argument('--classes', type=int, required=True)
        parser.add_argument('--students', type=int, required=True)
        parser.add_argument('--price-per-student-minor', type=int, default=DEFAULT_PRICE_MINOR, help=f'default {DEFAULT_PRICE_MINOR}')
        parser.add_argument('--period-start', required=True, help='YYYY-MM-DD')
        parser.add_argument('--by', required=True)

    def handle(self, *args, institution, classes, students, price_per_student_minor, period_start, by, **options):
        actor = get_user_model().objects.filter(email=by.strip().casefold(), is_staff=True, is_active=True, is_verified=True).first()
        if not actor:
            raise CommandError('--by must be an active verified staff account.')
        try:
            start = date.fromisoformat(period_start)
        except ValueError:
            raise CommandError('--period-start must be YYYY-MM-DD.')
        try:
            invoice = issue_institution_invoice(actor, institution=institution, classes=classes, students=students, price_per_student_minor=price_per_student_minor, period_start=start)
        except DomainError as exc:
            raise CommandError(f'{exc.code}: {exc.message}')
        self.stdout.write(f'{invoice.number}\t{invoice.institution.name}\t{invoice.currency} {invoice.amount_minor}\t{invoice.period_start.date()}..{invoice.period_end.date()}')
