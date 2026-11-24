"""First-party signup attribution and the aggregate acquisition funnel."""
import html
import io
import json
import re
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from reader.models import Completion, Progress
from reader.test_journey import make_book
from . import attribution, services
from .models import SignupAttribution, User

PASSWORD = 'Attribution-Passphrase-2026'
CONSENT = {'password_purpose_consent': 'on', 'password_purpose_version': 'password-account-v1'}
INDIA_ADULT = {'account_capacity': 'adult', 'account_notice_version': 'india-account-v1', 'account_terms_consent': 'on'}


class ParseTests(TestCase):
    def test_allow_listed_values_are_kept_and_normalised(self):
        self.assertEqual(attribution.parse('/en/titles/selfish-giant/?utm_source=YouTube&utm_campaign=Selfish-Giant&utm_content=film'),
                         {'source': 'youtube', 'campaign': 'selfish-giant', 'content': 'film', 'landing_path': '/en/titles/selfish-giant/'})

    def test_unknown_source_collapses_and_free_text_is_dropped(self):
        values = attribution.parse('/en/?utm_source=someone@example.test&utm_campaign=Hello%20World&utm_content=' + 'a' * 65)
        self.assertEqual(values, {'source': 'other', 'campaign': '', 'content': '', 'landing_path': '/en/'})

    def test_untagged_external_or_malformed_paths_record_nothing(self):
        for value in ('/en/titles/x/', 'https://outside.example.test/en/?utm_source=youtube', '//outside.example.test/?utm_source=youtube',
                      None, 42, '/en/?' + 'x' * 2050):
            self.assertIsNone(attribution.parse(value), value)

    def test_landing_path_outside_the_product_is_not_stored(self):
        self.assertEqual(attribution.parse('/admin/?utm_source=youtube')['landing_path'], '')

    def test_database_rejects_values_the_parser_would_never_produce(self):
        user = User.objects.create_user('db-guard@example.test', PASSWORD)
        for bad in ({'source': 'tiktok-ads'}, {'source': 'youtube', 'campaign': 'Has Space'},
                    {'source': 'youtube', 'landing_path': 'https://outside.example.test/'}):
            with self.subTest(bad=bad), self.assertRaises(IntegrityError), transaction.atomic():
                SignupAttribution.objects.create(user=user, **bad)


@override_settings(INDIA_FIRST_LAUNCH_ENABLED=True, MAISON_ACCOUNT_MODES={'IN': 'adult_only'})
class SignupCaptureTests(TestCase):
    def test_tagged_title_link_survives_sign_up_without_any_cookie_of_its_own(self):
        destination = '/en/titles/selfish-giant/?' + urlencode({'utm_source': 'youtube', 'utm_campaign': 'selfish-giant', 'utm_content': 'film'})
        page = self.client.get('/en/sign-up/', {'return_to': destination})
        self.assertNotIn('utm', ' '.join(page.cookies.keys()))
        response = self.client.post('/en/sign-up/', {'email': 'tagged@example.test', 'display_name': 'Reader', 'password': PASSWORD,
                                                     'return_to': destination, **CONSENT, **INDIA_ADULT})
        self.assertEqual(response.status_code, 200)
        row = SignupAttribution.objects.get(user__email='tagged@example.test')
        self.assertEqual((row.source, row.campaign, row.content, row.landing_path),
                         ('youtube', 'selfish-giant', 'film', '/en/titles/selfish-giant/'))

    def test_real_chain_from_a_tagged_title_page_through_sign_in_to_sign_up(self):
        edition, _ = make_book(units=1)
        title = self.client.get(f'/en/titles/{edition.pk}/', {'utm_source': 'youtube', 'utm_campaign': 'selfish-giant', 'utm_content': 'reel-1'})
        self.assertEqual(title.status_code, 200)
        header_cta = html.unescape(re.search(r'class="room-cta" href="([^"]+)"', title.content.decode())[1])
        self.assertIn('utm_source%3Dyoutube', header_cta)
        untagged = self.client.get(f'/en/titles/{edition.pk}/').content.decode()
        self.assertIn('class="room-cta" href="/en/sign-up/?return_to=/en/explore/"', untagged)
        sign_in = html.unescape(re.search(r'href="(/en/sign-in/\?return_to=[^"]+)"', title.content.decode())[1])
        auth = self.client.get(sign_in)
        # The in-form "Sign up" link keeps return_to; the header CTA always points at Explore.
        sign_up = html.unescape(re.search(r'href="(/en/sign-up/\?return_to=[^"]*utm_source[^"]*)"', auth.content.decode())[1])
        form = self.client.get(sign_up).content.decode()
        return_to = html.unescape(re.search(r'name="return_to" value="([^"]+)"', form)[1])
        self.client.post('/en/sign-up/', {'email': 'chain@example.test', 'password': PASSWORD, 'return_to': return_to, **CONSENT, **INDIA_ADULT})
        row = SignupAttribution.objects.get(user__email='chain@example.test')
        self.assertEqual((row.source, row.campaign, row.content, row.landing_path),
                         ('youtube', 'selfish-giant', 'reel-1', f'/en/titles/{edition.pk}/'))

    def test_untagged_signup_and_repeat_registration_record_nothing_new(self):
        self.client.post('/en/sign-up/', {'email': 'plain@example.test', 'password': PASSWORD, 'return_to': '/en/explore/', **CONSENT, **INDIA_ADULT})
        self.assertTrue(User.objects.filter(email='plain@example.test').exists())
        self.assertFalse(SignupAttribution.objects.exists())
        services.register_member('first@example.test', PASSWORD, return_path='/en/?utm_source=instagram',
                                 account_capacity='adult', account_notice_version='india-account-v1', account_terms_consent=True, territory='IN')
        services.register_member('first@example.test', PASSWORD, return_path='/en/?utm_source=youtube',
                                 account_capacity='adult', account_notice_version='india-account-v1', account_terms_consent=True, territory='IN')
        self.assertEqual(list(SignupAttribution.objects.values_list('source', flat=True)), ['instagram'])


class FunnelTests(TestCase):
    def member(self, source=None, campaign='', verified=True, joined=None):
        user = User.objects.create_user(f'{uuid.uuid4().hex}@example.test', PASSWORD, is_verified=verified)
        if joined:
            User.objects.filter(pk=user.pk).update(date_joined=joined)
        if source:
            SignupAttribution.objects.create(user=user, source=source, campaign=campaign)
        return user

    def test_cohort_stages_are_counted_from_existing_records(self):
        edition, revision = make_book(units=1)
        youtube = [self.member('youtube', 'selfish-giant') for _ in range(6)]
        for user in youtube[:5]:
            Progress.objects.create(user=user, edition=edition, revision=revision, format='reader', last_operation_id=uuid.uuid4())
        for user in youtube[:5]:
            Completion.objects.create(user=user, edition=edition, revision=revision, format='reader', is_complete=True, completed_at=timezone.now())
        for _ in range(5):
            self.member(verified=False)
        now = timezone.now()
        rows = attribution.funnel(now - timedelta(days=7), now + timedelta(minutes=1))
        by_source = {row['source']: row for row in rows}
        self.assertEqual({k: by_source['youtube'][k] for k in attribution.STAGES},
                         {'signed_up': 6, 'verified': 6, 'started_reading': 5, 'completed_story': 5, 'pass_started': None})
        self.assertEqual(by_source['direct']['signed_up'], 5)
        self.assertIsNone(by_source['direct']['verified'])

    def test_small_cells_are_suppressed_and_excluded_accounts_never_count(self):
        now = timezone.now()
        for _ in range(4):
            self.member('school')
        User.objects.create_user('staff@example.test', PASSWORD, is_staff=True)
        gone = self.member('school'); gone.is_active = False; gone.save()
        child = self.member('school'); child.guardian_managed = True; child.save()
        self.member('school', joined=now - timedelta(days=60))
        rows = attribution.funnel(now - timedelta(days=7), now + timedelta(minutes=1))
        self.assertEqual(rows[0]['source'], 'school')
        self.assertTrue(all(rows[0][stage] is None for stage in attribution.STAGES))

    def test_command_prints_suppressed_cells_and_refuses_weaker_thresholds(self):
        for _ in range(5):
            self.member('youtube', 'selfish-giant')
        self.member('instagram')
        out = io.StringIO()
        call_command('funnel_report', '--weeks', '2', '--by-campaign', stdout=out)
        text = out.getvalue()
        self.assertIn('youtube\tselfish-giant\t5\t5\t<5\t<5\t<5', text)
        self.assertIn('instagram\t\t<5', text)
        out = io.StringIO()
        call_command('funnel_report', '--json', stdout=out)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload['min_cell'], 5)
        self.assertNotIn('email', out.getvalue())
        with self.assertRaises(CommandError):
            call_command('funnel_report', '--min-cell', '1')


class AttributionLifecycleTests(TestCase):
    def test_abandoned_tagged_signup_is_still_cleaned_with_its_attribution(self):
        from core.models import OutboxJob
        from .models import EmailActionToken
        from .retention import cleanup_account_retention
        now = timezone.now()
        user = User.objects.create_user('abandoned-tagged@example.test')
        User.objects.filter(pk=user.pk).update(date_joined=now - timedelta(days=10))
        SignupAttribution.objects.create(user=user, source='youtube', campaign='selfish-giant')
        action = EmailActionToken.objects.create(user=user, email_normalized='abandoned-tagged@example.test', purpose='verify_email',
                                                 token_sha256=uuid.uuid4().hex, expires_at=now - timedelta(days=9))
        EmailActionToken.objects.filter(pk=action.pk).update(created_at=now - timedelta(days=10))
        OutboxJob.objects.create(kind='email_action', actor=user, dedupe_key=uuid.uuid4().hex, payload={'action_id': str(action.pk)},
                                 status='done', not_before=now, result={'status': 'submitted'}, completed_at=now - timedelta(days=9))
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['abandoned_signups'], 1)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(SignupAttribution.objects.exists())

    def test_export_includes_and_deletion_removes_the_record(self):
        import tempfile, time
        from core.models import OutboxJob
        from .privacy import _write_export, delete_account
        user = User.objects.create_user('lifecycle@example.test', PASSWORD, is_verified=True)
        SignupAttribution.objects.create(user=user, source='newsletter', campaign='week-1', content='story')
        with tempfile.TemporaryFile() as handle:
            _write_export(user, handle, time.monotonic() + 30)
            exported = json.loads(handle.read())
        self.assertEqual([{k: row[k] for k in ('source', 'campaign', 'content')} for row in exported['signup_attribution']],
                         [{'source': 'newsletter', 'campaign': 'week-1', 'content': 'story'}])
        job = OutboxJob.objects.create(kind='privacy_delete', actor=user, dedupe_key=uuid.uuid4().hex, payload={}, not_before=timezone.now())
        self.assertEqual(delete_account(job)['status'], 'anonymised')
        self.assertFalse(SignupAttribution.objects.filter(user=user).exists())
