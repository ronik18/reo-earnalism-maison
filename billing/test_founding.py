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

    def _edition(self, slug, policy, live=True, locale='bn', units=1, audio=None, cleared=True):
        """A live edition with `units` units; `audio` = how many units get a ready audio_chapter (default all)."""
        from django.conf import settings
        from library.models import Asset, Unit
        work = Work.objects.create(slug=f'w-{slug}', title=slug)
        edition = Edition.objects.create(work=work, slug=slug, locale=locale)
        revision = Revision.objects.create(edition=edition, title=slug, access_policy=policy, content_sha256='d' * 64)
        audio = units if audio is None else audio
        for n in range(units):
            unit = Unit.objects.create(revision=revision, ordinal=n + 1, title=f'Chapter {n + 1}')
            if n < audio:
                Asset.objects.create(revision=revision, unit=unit, kind='audio_chapter', state='ready', sha256='a' * 64,
                                     storage_key=f'revisions/{revision.pk}/{uuid.uuid4()}', bytes=10, content_type='audio/mpeg')
        if cleared:
            formats = [f for f in ('reader', 'audio', 'video') if policy.get(f, 'deny') != 'deny']
            revision.validation_evidence = {'publication_clearance': {
                'status': 'pass', 'sha256': revision.content_sha256, 'formats': formats, 'evidence_ref': 'x#sha256=1',
                'territories': list(settings.MAISON_PUBLICATION_TERRITORIES),
                'asset_sha256': {str(a.id): a.sha256 for a in revision.assets.filter(state='ready')}}}
            Revision.objects.filter(pk=revision.pk).update(validation_evidence=revision.validation_evidence)
        if live:
            Revision.objects.filter(pk=revision.pk).update(state='live', published_at=timezone.now())
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

    def test_count_audio_titles_counts_full_cleared_bengali_audio_only(self):
        self._edition('a-free', {'reader': 'free', 'audio': 'free'}, units=2)
        self._edition('a-paid', {'audio': 'paid', 'reader': 'paid'})
        self._edition('a-deny', {'audio': 'deny', 'reader': 'free'})
        self._edition('reader-only', {'reader': 'free'})
        self._edition('unpublished', {'audio': 'paid'}, live=False)
        self._edition('english', {'audio': 'free', 'reader': 'free'}, locale='en')  # English narration is not a start condition
        self._edition('partial', {'audio': 'free', 'reader': 'free'}, units=3, audio=2)  # one chapter without audio
        self._edition('no-units', {'audio': 'free', 'reader': 'free'}, units=0)
        self._edition('uncleared', {'audio': 'free', 'reader': 'free'}, cleared=False)
        self.assertEqual(founding.count_audio_titles(), 2)

    def _open_plans(self, **offer):
        plans = founding.ensure_founding_plans(self.staff)
        BillingPlan.objects.update(merchant_approved_at=timezone.now())
        Offer.objects.update(approved=True, active=True, **offer)
        return plans

    def test_plans_open_only_when_purchasable_in_production(self):
        self.assertFalse(founding.founding_plans_open())
        self._open_plans()  # created test_only (Offer default); activation never changes that
        self.assertFalse(founding.founding_plans_open())
        Offer.objects.update(test_only=False)
        self.assertTrue(founding.founding_plans_open())

    def test_plans_open_matches_the_latest_offer_version_per_code(self):
        self._open_plans(test_only=False)
        # A newer, not yet approved version of the monthly offer supersedes the open one: closed until it is ready.
        newer = Offer.objects.create(code='founding-pass-month', version=2, name='Earnalism Pass — founding member (monthly)',
                                     kind='one_time_pass', formats=['audio', 'reader'], price_minor=9900, currency='INR',
                                     duration_seconds=2592000, terms_version='founding-pass-v2', test_only=False)
        self.assertFalse(founding.founding_plans_open())
        plan = BillingPlan.objects.create(offer=newer, interval_unit='month', merchant_approved_at=timezone.now())
        Offer.objects.filter(pk=newer.pk).update(approved=True, active=True)
        self.assertTrue(founding.founding_plans_open())
        self.assertEqual(founding.latest_founding_plans()['month'].pk, plan.pk)
        # An extra, unrelated plan never confuses the match (no count-of-rows check).
        other = Offer.objects.create(code='founding-pass-year-extra', name='x', kind='one_time_pass', formats=['reader'],
                                     price_minor=100, duration_seconds=10, terms_version='x', test_only=False)
        BillingPlan.objects.create(offer=other, interval_unit='year')
        self.assertTrue(founding.founding_plans_open())
