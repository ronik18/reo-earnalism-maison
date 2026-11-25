import hashlib
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.api import DomainError
from core.models import AuditEvent
from operations import review
from operations.models import ReviewItem

User = get_user_model()
STANDING = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)


PASSWORD = 'pw-Test-12345-Review'


def login(client, user):
    from django.conf import settings
    if user.is_staff:
        path, data = '/admin/login/', {'username': user.email, 'next': '/admin/'}
    else:
        path, data = '/en/sign-in/', {'email': user.email, 'return_to': '/en/vault/'}
    client.get(path)
    data.update(password=PASSWORD, password_purpose_consent='on', password_purpose_version='password-account-v1')
    if settings.CSRF_COOKIE_NAME in client.cookies:
        data['csrfmiddlewaretoken'] = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert client.post(path, data).status_code in (200, 302)


def make_user(email, *, staff=True, verified=True, perm=True):
    user = User.objects.create_user(email, PASSWORD, is_staff=staff, is_verified=verified)
    if perm:
        user.user_permissions.add(Permission.objects.get(codename='decide_review', content_type__app_label='operations'))
    return User.objects.get(pk=user.pk)


class ReviewQueueTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.owner = make_user('owner@example.test')

    def file_item(self, kind='clearance', slug='a', body=b'{"ok": 1}'):
        rel = f'docs/evidence/publication-clearance-{slug}.json'
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        item = review.queue(kind, rel, hashlib.sha256(body).hexdigest(), {'edition_slug': slug})
        return item, path

    def post(self, post_id='p1', **summary):
        base = {'edition_slug': 'a', 'cover_sha256': 'c' * 64, 'exact_words': True, 'claims': []}
        base.update(summary)
        sha = hashlib.sha256(post_id.encode()).hexdigest()
        return review.queue('post', f'social/a/{post_id}', sha, base)

    def test_queue_is_idempotent(self):
        first = review.queue('cover', 'x.json', 'a' * 64, {'n': 1})
        second = review.queue('cover', 'x.json', 'a' * 64, {'n': 2})
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ReviewItem.objects.count(), 1)
        self.assertEqual(second.status, 'pending')

    def test_decide_requires_permission_and_audits(self):
        with override_settings(BASE_DIR=self.base):
            item, _ = self.file_item()
            for bad in (make_user('np@example.test', perm=False), make_user('ns@example.test', staff=False),
                        make_user('nv@example.test', verified=False)):
                with self.assertRaises(DomainError) as ctx:
                    review.decide(bad, [item.pk], 'approved')
                self.assertEqual(ctx.exception.code, 'ACCESS_DENIED')
            self.assertEqual(review.decide(self.owner, [item.pk], 'approved', 'ok'), 1)
        item.refresh_from_db()
        self.assertEqual((item.status, item.decided_by, item.decision_note, item.standing), ('approved', self.owner, 'ok', False))
        self.assertIsNotNone(item.decided_at)
        event = AuditEvent.objects.get(action='review.decided')
        self.assertEqual(event.entity_id, str(item.pk))
        self.assertEqual(event.detail['decision'], 'approved')

    def test_second_decision_is_a_no_op(self):
        with override_settings(BASE_DIR=self.base):
            item, _ = self.file_item()
            self.assertEqual(review.decide(self.owner, [item.pk], 'approved'), 1)
            self.assertEqual(review.decide(self.owner, [item.pk], 'rejected'), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertEqual(AuditEvent.objects.filter(action='review.decided').count(), 1)

    def test_changed_file_cannot_be_approved(self):
        with override_settings(BASE_DIR=self.base):
            item, path = self.file_item()
            path.write_bytes(b'{"ok": 2}')
            with self.assertRaises(DomainError) as ctx:
                review.decide(self.owner, [item.pk], 'approved')
        self.assertEqual(ctx.exception.code, 'REVIEW_ITEM_CHANGED')
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')
        self.assertFalse(AuditEvent.objects.filter(action='review.decided').exists())

    def test_standing_permission_never_applies_to_clearance_or_edition(self):
        with override_settings(BASE_DIR=self.base, MAISON_REVIEW_STANDING_FROM=STANDING):
            self.assertTrue(review.standing_permission_active(STANDING + timedelta(days=1)))
            self.assertFalse(review.standing_permission_active(STANDING - timedelta(days=1)))
            for kind in ('clearance', 'cover', 'edition'):
                item, _ = self.file_item(kind, slug=kind)
                self.assertEqual(item.status, 'pending')
                self.assertFalse(item.standing)
                self.assertEqual(review.auto_checks(item), ['NOT_ELIGIBLE_FOR_STANDING'])
        with override_settings(MAISON_REVIEW_STANDING_FROM=None):
            self.assertFalse(review.standing_permission_active(timezone.now()))

    def test_standing_post_requires_passing_checks(self):
        with override_settings(BASE_DIR=self.base, MAISON_REVIEW_STANDING_FROM=STANDING):
            self.assertEqual(self.post('p0').status, 'pending')
            self.assertEqual(review.auto_checks(ReviewItem.objects.get(ref='social/a/p0')), ['EDITION_NOT_CLEARED'])
            clearance, _ = self.file_item('clearance', slug='a')
            review.decide(self.owner, [clearance.pk], 'approved')
            ok = self.post('p1')
            self.assertEqual((ok.status, ok.standing), ('approved', True))
            self.assertIsNone(ok.decided_by)
            self.assertIsNotNone(ok.decided_at)
            for pid, extra, code in [('p2', {'cover_sha256': ''}, 'NO_OWNER_COVER'), ('p3', {'exact_words': False}, 'NOT_EXACT_WORDS'),
                                     ('p4', {'ai': True}, 'AI_NOT_LABELLED'), ('p5', {'claims': ['best']}, 'HAS_CLAIMS')]:
                bad = self.post(pid, **extra)
                self.assertEqual(bad.status, 'pending', pid)
                self.assertEqual(review.auto_checks(bad), [code])
            self.assertEqual(self.post('p6', ai=True, ai_labelled=True).status, 'approved')
        with override_settings(MAISON_REVIEW_STANDING_FROM=None):
            self.assertEqual(self.post('p7').status, 'pending')

    def test_post_item_is_decided_without_rehash(self):
        item = self.post('p8')
        self.assertEqual(review.decide(self.owner, [item.pk], 'rejected'), 1)

    def test_page_is_staff_only_and_lists_pending(self):
        item, _ = self.file_item('cover', slug='lst')
        url = reverse('web:staff-review', args=['en'])
        self.assertEqual(self.client.get(url).status_code, 404)
        login(self.client, make_user('plain@example.test', staff=False))
        self.assertEqual(self.client.get(url).status_code, 404)
        login(self.client, self.owner)
        response = self.client.get(url)
        self.assertContains(response, 'publication-clearance-lst.json')
        self.assertContains(response, 'name="item"')
        self.assertContains(response, 'csrfmiddlewaretoken')
        with override_settings(BASE_DIR=self.base):
            response = self.client.post(url, {'item': [str(item.pk)], 'decision': 'approved'})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertNotContains(self.client.get(url), 'publication-clearance-lst.json')

    def test_page_post_needs_csrf(self):
        item, _ = self.file_item('cover', slug='csrf')
        client = Client(enforce_csrf_checks=True)
        login(client, self.owner)
        url = reverse('web:staff-review', args=['en'])
        self.assertEqual(client.post(url, {'item': [str(item.pk)], 'decision': 'approved'}).status_code, 403)

    def test_weekly_report_marks_standing_items(self):
        with override_settings(BASE_DIR=self.base, MAISON_REVIEW_STANDING_FROM=STANDING):
            clearance, _ = self.file_item('clearance', slug='a')
            review.decide(self.owner, [clearance.pk], 'approved')
            standing = self.post('p1')
        when = datetime(2026, 11, 24, 10, tzinfo=dt_timezone.utc)  # ISO week 2026-W48
        ReviewItem.objects.filter(pk__in=[clearance.pk, standing.pk]).update(decided_at=when)
        out = StringIO()
        call_command('review_report', week='2026-W48', stdout=out)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(any('social/a/p1' in line and 'approved' in line and 'standing' in line for line in lines))
        self.assertTrue(any(clearance.ref in line and 'standing' not in line for line in lines))
        out = StringIO()
        call_command('review_report', week='2026-W47', stdout=out)
        self.assertEqual(out.getvalue().strip(), '')
