"""Founding member Pass plans.

  python manage.py founding_pass create --by <staff email>
  python manage.py founding_pass status
  python manage.py founding_pass activate --by <staff email>
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from billing import founding
from billing.subscription_models import BillingPlan
from core.api import DomainError


class Command(BaseCommand):
    help = 'Create, inspect or activate the founding member Pass plans (audited).'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['create', 'status', 'activate'])
        parser.add_argument('--by')

    def handle(self, *args, action, by, **options):
        if action == 'status':
            self.stdout.write(f'audio titles: {founding.count_audio_titles()} (need {founding.MIN_AUDIO_TITLES})')
            codes = [s['code'] for s in founding.SPECS.values()]
            for plan in BillingPlan.objects.filter(offer__code__in=codes).select_related('offer').order_by('offer__code'):
                o = plan.offer
                self.stdout.write(f'{o.code}\t{o.price_minor}\tapproved={o.approved}\tactive={o.active}\tmerchant_approved={bool(plan.merchant_approved_at)}')
            return
        actor = get_user_model().objects.filter(email=(by or '').strip().casefold(), is_staff=True, is_active=True, is_verified=True).first()
        if not actor:
            raise CommandError('--by must be an active, verified staff account')
        try:
            if action == 'create':
                plans = founding.ensure_founding_plans(actor)
                self.stdout.write('Founding plans ready: ' + ', '.join(p.offer.code for p in plans.values()))
            else:
                founding.activate_founding_plans(actor, audio_titles=founding.count_audio_titles())
                self.stdout.write('Founding plans activated')
        except DomainError as error:
            raise CommandError(f'{error.code}: {error.message}')
