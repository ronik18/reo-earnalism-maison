import uuid
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from core.api import DomainError
from core.models import AuditEvent
from library.models import Edition, Revision, Work
from .models import Offer
from .subscription_models import BillingPlan, Subscription
from . import founding


class FoundingPlanTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user('staff-founding@example.test', 'Local-Fixture-Password-47', is_staff=True, is_verified=True)

    def test_plans_created_once_inactive(self):
        first = founding.ensure_founding_plans(self.staff)
        second = founding.ensure_founding_plans(self.staff)
        self.assertEqual(set(first), {'month', 'year'})
        self.assertEqual({k: p.pk for k, p in first.items()}, {k: p.pk for k, p in second.items()})
        self.assertEqual(BillingPlan.objects.count(), 2)
        month, year = first['month'], first['year']
        self.assertEqual((month.offer.code, month.offer.price_minor, month.interval_unit, month.offer.duration_seconds), ('founding-pass-month', 9900, 'month', 2592000))
        self.assertEqual((year.offer.code, year.offer.price_minor, year.interval_unit, year.offer.duration_seconds), ('founding-pass-year', 99900, 'year', 31536000))
        for plan in first.values():
            o = plan.offer
            self.assertEqual((o.currency, o.formats, o.approved, o.active, o.kind, o.terms_version), ('INR', ['audio', 'reader'], False, False, 'one_time_pass', 'founding-pass-v1'))
        self.assertEqual(month.offer.name, 'Earnalism Pass — founding member (monthly)')
        self.assertEqual(year.offer.name, 'Earnalism Pass — founding member (yearly)')
        self.assertEqual(AuditEvent.objects.filter(action='billing.founding_plans_created').count(), 1)

    def test_actor_must_be_active_verified_staff(self):
        User = get_user_model()
        plain = User.objects.create_user('plain-founding@example.test', 'Local-Fixture-Password-47', is_verified=True)
        unverified = User.objects.create_user('unv-founding@example.test', 'Local-Fixture-Password-47', is_staff=True)
        for actor in (plain, unverified):
            with self.assertRaises(DomainError):
                founding.ensure_founding_plans(actor)
        self.assertEqual(BillingPlan.objects.count(), 0)

    def test_activation_needs_eight_audio_titles_and_merchant_approval(self):
        plans = founding.ensure_founding_plans(self.staff)
        with self.assertRaises(DomainError) as e:
            founding.activate_founding_plans(self.staff, audio_titles=7)
        self.assertEqual(e.exception.code, 'FOUNDING_START_CONDITION')
        with self.assertRaises(DomainError) as e:
            founding.activate_founding_plans(self.staff, audio_titles=8)
        self.assertEqual(e.exception.code, 'FOUNDING_MERCHANT_UNAPPROVED')
        self.assertFalse(Offer.objects.filter(active=True).exists())
        BillingPlan.objects.filter(pk=plans['month'].pk).update(merchant_approved_at=timezone.now())
        with self.assertRaises(DomainError) as e:
            founding.activate_founding_plans(self.staff, audio_titles=8)
        self.assertEqual(e.exception.code, 'FOUNDING_MERCHANT_UNAPPROVED')
        BillingPlan.objects.update(merchant_approved_at=timezone.now())
        founding.activate_founding_plans(self.staff, audio_titles=8)
        self.assertEqual(Offer.objects.filter(active=True, approved=True).count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action='billing.founding_plans_activated').count(), 1)

    def test_activation_without_plans_is_refused(self):
        with self.assertRaises(DomainError) as e:
            founding.activate_founding_plans(self.staff, audio_titles=9)
        self.assertEqual(e.exception.code, 'FOUNDING_MERCHANT_UNAPPROVED')

    def test_price_change_leaves_existing_subscribers_on_founding_plan(self):
        plans = founding.ensure_founding_plans(self.staff)
        member = get_user_model().objects.create_user('member-founding@example.test', 'Local-Fixture-Password-47', is_verified=True)
        sub = Subscription.objects.create(user=member, plan=plans['month'])
        new_offer = Offer.objects.create(code='pass-month-2', name='New price', kind='one_time_pass', formats=['audio', 'reader'], price_minor=12900, currency='INR', duration_seconds=2592000, terms_version='pass-v2')
        BillingPlan.objects.create(offer=new_offer, interval_unit='month')
        sub.refresh_from_db()
        self.assertEqual(sub.plan.offer.price_minor, 9900)

    def _edition(self, slug, policy, live=True):
        work = Work.objects.create(slug=f'w-{slug}', title=slug)
        edition = Edition.objects.create(work=work, slug=slug, locale='en')
        revision = Revision.objects.create(edition=edition, title=slug, access_policy=policy, state='live' if live else 'draft')
        if live:
            edition.live_revision = revision
            edition.save()
        return edition

    def test_command_create_status_activate(self):
        call_command('founding_pass', 'create', '--by', self.staff.email)
        self.assertEqual(BillingPlan.objects.count(), 2)
        with self.assertRaises(CommandError):
            call_command('founding_pass', 'create', '--by', 'nobody@example.test')
        with self.assertRaises(CommandError):
            call_command('founding_pass', 'activate', '--by', self.staff.email)
        call_command('founding_pass', 'status')

    def test_count_audio_titles_with_no_editions(self):
        self.assertEqual(founding.count_audio_titles(), 0)

    def test_count_audio_titles_counts_live_free_or_paid_audio_only(self):
        self._edition('a-free', {'audio': 'free'})
        self._edition('a-paid', {'audio': 'paid', 'reader': 'paid'})
        self._edition('a-deny', {'audio': 'deny'})
        self._edition('reader-only', {'reader': 'free'})
        self._edition('unpublished', {'audio': 'paid'}, live=False)
        self.assertEqual(founding.count_audio_titles(), 2)
