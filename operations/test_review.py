import hashlib
import json
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

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


PROBE = lambda _: dict(width=1080, height=1920, duration_seconds=30, codec='h264')
REAL_PREPARE = review.prepare


def write_bundle(base, name, video=b'bound-video-payload', title='Exact title'):
    """A minimal production bundle under `base` (inside BASE_DIR); returns (manifest_rel, asset_root_rel)."""
    from django.conf import settings
    assets = base / 'assets' / name
    assets.mkdir(parents=True, exist_ok=True)
    (assets / 'film').write_bytes(video)
    manifest = dict(schema='earnalism.production_bundle.v1', project_id=name, private=True,
        content=dict(text_sha256='a' * 64, language='en', voice_profile='en_tisha'),
        assets=[dict(id='film', path='film', bytes=len(video), sha256=hashlib.sha256(video).hexdigest(),
                     role='video', content_type='video/mp4')], evidence=dict(qa=[], rights=[]),
        social=[dict(platform='youtube', account_id='account1', video_asset_id='film', title=title,
                     description='Exact description', made_for_kids=False)])
    path = base / 'bundle' / (name + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))
    root = Path(settings.BASE_DIR)
    return str(path.relative_to(root)), str(assets.relative_to(root))


def post_summary(base, post_id, edition='a', **overrides):
    manifest, assets = write_bundle(base, post_id)
    summary = {'edition_slug': edition, 'bundle_manifest': manifest, 'asset_root': assets,
               'destination_key': 'youtube:account1', 'account_id': 'account1', 'post_id': post_id,
               'cover_sha256': 'c' * 64, 'exact_words': True, 'ai': False, 'ai_labelled': False, 'claims': [],
               'sponsored': False, 'new_author': False}
    summary.update(overrides)
    return summary


def candidate(summary):
    return review.post_candidate_sha256(summary)


def make_live_edition(slug='a', live=True):
    from library.models import Edition, Revision, Work
    work = Work.objects.create(slug=f'work-{slug}', title='T', creators=['A'])
    edition = Edition.objects.create(work=work, slug=slug, locale='bn')
    revision = Revision.objects.create(edition=edition, title='T', content_sha256='b' * 64,
                                       state='live' if live else 'draft', published_at=timezone.now() if live else None)
    if live:
        edition.live_revision = revision
        edition.save(update_fields=['live_revision'])
    return edition


def make_user(email, *, staff=True, verified=True, perm=True):
    user = User.objects.create_user(email, PASSWORD, is_staff=staff, is_verified=verified)
    if perm:
        user.user_permissions.add(Permission.objects.get(codename='decide_review', content_type__app_label='operations'))
    return User.objects.get(pk=user.pk)


class ReviewQueueTests(TestCase):
    def setUp(self):
        from django.conf import settings
        self.tmp = tempfile.TemporaryDirectory(dir=settings.BASE_DIR, prefix='.review-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.prefix = self.base.name
        self.owner = make_user('owner@example.test')
        patcher = patch.object(review, 'prepare', lambda m, r: REAL_PREPARE(m, r, probe=PROBE))
        patcher.start()
        self.addCleanup(patcher.stop)

    def file_item(self, kind='clearance', slug='a', body=b'{"ok": 1}'):
        rel = f'{self.prefix}/docs/evidence/publication-clearance-{slug}.json'
        path = self.base.parent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        item = review.queue(kind, rel, hashlib.sha256(body).hexdigest(), {'edition_slug': slug})
        return item, path

    def post(self, post_id='p1', **summary):
        base = post_summary(self.base, post_id, **summary)
        return review.queue('post', f'social/a/{post_id}', candidate(base), base)

    def test_queue_is_idempotent(self):
        first, _ = self.file_item('cover', slug='idem')
        second, _ = self.file_item('cover', slug='idem')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ReviewItem.objects.count(), 1)
        self.assertEqual(second.status, 'pending')

    def test_decide_requires_permission_and_audits(self):
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
        item, _ = self.file_item()
        self.assertEqual(review.decide(self.owner, [item.pk], 'approved'), 1)
        self.assertEqual(review.decide(self.owner, [item.pk], 'rejected'), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertEqual(AuditEvent.objects.filter(action='review.decided').count(), 1)

    def test_changed_file_cannot_be_approved(self):
        item, path = self.file_item()
        path.write_bytes(b'{"ok": 2}')
        with self.assertRaises(DomainError) as ctx:
            review.decide(self.owner, [item.pk], 'approved')
        self.assertEqual(ctx.exception.code, 'REVIEW_ITEM_CHANGED')
        self.assertEqual(ctx.exception.details['refs'], [item.ref])
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')
        self.assertFalse(AuditEvent.objects.filter(action='review.decided').exists())
        path.unlink()  # a missing file also cannot be approved, but can be rejected, with a healthy item in the batch
        good, _ = self.file_item('cover', slug='good')
        with self.assertRaises(DomainError) as ctx:
            review.decide(self.owner, [good.pk, item.pk], 'approved')
        self.assertIn(item.ref, ctx.exception.message)
        self.assertEqual(review.decide(self.owner, [good.pk, item.pk], 'rejected'), 2)
        item.refresh_from_db()
        self.assertEqual(item.status, 'rejected')

    def test_requeue_with_new_hash_supersedes_old_pending(self):
        old, path = self.file_item('clearance', slug='sup')
        new, _ = self.file_item('clearance', slug='sup', body=b'{"ok": 3}')
        old.refresh_from_db()
        self.assertNotEqual(old.pk, new.pk)
        self.assertEqual((old.status, old.decision_note, old.decided_by), ('rejected', 'superseded', None))
        self.assertEqual(new.status, 'pending')
        self.assertEqual(AuditEvent.objects.filter(action='review.decided', entity_id=str(old.pk), actor=None).count(), 1)

    def test_queue_validates_file_refs_and_hashes(self):
        good = hashlib.sha256(b'{"ok": 1}').hexdigest()
        _, path = self.file_item('cover', slug='v')
        for ref in ('/etc/passwd', '../outside.json'):
            with self.assertRaises(DomainError) as ctx:
                review.queue('cover', ref, good, {})
            self.assertEqual(ctx.exception.code, 'REVIEW_REF_INVALID')
        for sha in ('zz', 'A' * 64, '0' * 64):
            with self.assertRaises(DomainError) as ctx:
                review.queue('cover', f'{self.prefix}/docs/evidence/publication-clearance-v.json', sha, {})
            self.assertEqual(ctx.exception.code, 'REVIEW_HASH_INVALID')

    def test_standing_checks_fail_closed(self):
        make_live_edition('a')
        with override_settings(MAISON_REVIEW_STANDING_FROM=STANDING):
            clearance, _ = self.file_item('clearance', slug='a')
            review.decide(self.owner, [clearance.pk], 'approved')
            for pid, drop, code in [('q1', 'ai', 'AI_NOT_LABELLED'), ('q2', 'claims', 'HAS_CLAIMS'), ('q3', 'exact_words', 'NOT_EXACT_WORDS')]:
                summary = post_summary(self.base, pid)
                summary.pop(drop)
                with self.assertRaises(DomainError) as ctx:  # queue refuses an incomplete summary outright
                    review.queue('post', f'social/a/{pid}', candidate(summary), summary)
                self.assertEqual(ctx.exception.code, 'REVIEW_SUMMARY_INVALID')
                item = ReviewItem(kind='post', ref=f'social/a/{pid}', summary=summary)  # e.g. a hand-made row
                self.assertEqual(review.auto_checks(item), [code])

    def test_standing_permission_never_applies_to_clearance_or_edition(self):
        with override_settings(MAISON_REVIEW_STANDING_FROM=STANDING):
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
        with override_settings(MAISON_REVIEW_STANDING_FROM=STANDING):
            self.assertEqual(self.post('p0').status, 'pending')
            self.assertEqual(review.auto_checks(ReviewItem.objects.get(ref='social/a/p0')), ['EDITION_NOT_CLEARED', 'EDITION_NOT_LIVE'])
            clearance, _ = self.file_item('clearance', slug='a')
            review.decide(self.owner, [clearance.pk], 'approved')
            self.assertEqual(self.post('p00').status, 'pending')
            self.assertEqual(review.auto_checks(ReviewItem.objects.get(ref='social/a/p00')), ['EDITION_NOT_LIVE'])
            make_live_edition('a')
            ok = self.post('p1')
            self.assertEqual((ok.status, ok.standing), ('approved', True))
            self.assertIsNone(ok.decided_by)
            self.assertIsNotNone(ok.decided_at)
            for pid, extra, code in [('p2', {'cover_sha256': ''}, 'NO_OWNER_COVER'), ('p3', {'exact_words': False}, 'NOT_EXACT_WORDS'),
                                     ('p4', {'ai': True}, 'AI_NOT_LABELLED'), ('p5', {'claims': ['best']}, 'HAS_CLAIMS'),
                                     ('p8', {'sponsored': True}, 'SPONSORED'), ('p9', {'new_author': True}, 'NEW_AUTHOR')]:
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
        response = self.client.post(url, {'item': [str(item.pk)], 'decision': 'approved'})
        self.assertRedirects(response, url + '?decided=1', fetch_redirect_response=False)
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertNotContains(self.client.get(url), 'publication-clearance-lst.json')

    def test_page_needs_verified_staff_with_permission(self):
        url = reverse('web:staff-review', args=['en'])
        for user in (make_user('uv@example.test', verified=False), make_user('np2@example.test', perm=False)):
            client = Client()
            login(client, user)
            self.assertEqual(client.get(url).status_code, 404, user.email)
            self.assertEqual(client.post(url, {'decision': 'approved'}).status_code, 404, user.email)

    def test_page_confirms_count_and_empty_selection(self):
        item, _ = self.file_item('cover', slug='conf')
        login(self.client, self.owner)
        url = reverse('web:staff-review', args=['en'])
        response = self.client.post(url, {'item': [str(item.pk)], 'decision': 'rejected'}, follow=True)
        self.assertContains(response, 'Items decided: 1')
        response = self.client.post(url, {'decision': 'approved'}, follow=True)
        self.assertContains(response, 'Nothing was decided')

    def test_page_post_needs_csrf(self):
        item, _ = self.file_item('cover', slug='csrf')
        client = Client(enforce_csrf_checks=True)
        login(client, self.owner)
        url = reverse('web:staff-review', args=['en'])
        self.assertEqual(client.post(url, {'item': [str(item.pk)], 'decision': 'approved'}).status_code, 403)

    def test_standing_exclusions_fail_closed_on_missing_flags(self):
        make_live_edition('a')
        clearance, _ = self.file_item('clearance', slug='a')
        review.decide(self.owner, [clearance.pk], 'approved')
        for drop, code in (('sponsored', 'SPONSORED'), ('new_author', 'NEW_AUTHOR')):
            summary = post_summary(self.base, 'x-' + drop)
            summary.pop(drop)
            self.assertEqual(review.auto_checks(ReviewItem(kind='post', summary=summary)), [code])
        draft_only = post_summary(self.base, 'x-draft', edition='draft-only')
        make_live_edition('draft-only', live=False)
        ReviewItem.objects.filter(pk=clearance.pk).update(summary={'edition_slug': 'draft-only'})
        self.assertEqual(review.auto_checks(ReviewItem(kind='post', summary=draft_only)), ['EDITION_NOT_LIVE'])

    def test_weekly_report_marks_standing_items(self):
        make_live_edition('a')
        with override_settings(MAISON_REVIEW_STANDING_FROM=STANDING):
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


class PostBindingTests(TestCase):
    """A post approval binds the exact prepared bundle (candidate_sha256) and one summary schema."""
    def setUp(self):
        from django.conf import settings
        self.tmp = tempfile.TemporaryDirectory(dir=settings.BASE_DIR, prefix='.review-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.owner = make_user('owner@example.test')
        patcher = patch.object(review, 'prepare', lambda m, r: REAL_PREPARE(m, r, probe=PROBE))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_post_sha256_must_be_the_prepared_candidate(self):
        summary = post_summary(self.base, 'b1')
        for sha in (hashlib.sha256(b'b1').hexdigest(), '0' * 64):
            with self.assertRaises(DomainError) as ctx:
                review.queue('post', 'social/a/b1', sha, summary)
            self.assertEqual(ctx.exception.code, 'REVIEW_HASH_INVALID')
        item = review.queue('post', 'social/a/b1', candidate(summary), summary)
        self.assertEqual(item.sha256, REAL_PREPARE(json.loads((Path(settings_base()) / summary['bundle_manifest']).read_text()),
                                                   Path(settings_base()) / summary['asset_root'], probe=PROBE)['candidate_sha256'])

    def test_post_summary_schema_is_required(self):
        good = post_summary(self.base, 'b2')
        sha = candidate(good)
        for key, value in [('edition_slug', None), ('account_id', ''), ('post_id', 3), ('cover_sha256', None),
                           ('exact_words', 'yes'), ('ai', None), ('ai_labelled', 1), ('claims', 'none'),
                           ('sponsored', None), ('new_author', 'no'), ('destination_key', None)]:
            summary = dict(good)
            if value is None:
                summary.pop(key)
            else:
                summary[key] = value
            with self.assertRaises(DomainError) as ctx:
                review.queue('post', 'social/a/b2', sha, summary)
            self.assertEqual(ctx.exception.code, 'REVIEW_SUMMARY_INVALID', key)
            self.assertIn(key, ctx.exception.details['fields'])
        for key, value in [('bundle_manifest', '/etc/passwd'), ('asset_root', '../../outside')]:
            with self.assertRaises(DomainError) as ctx:
                review.queue('post', 'social/a/b2', sha, dict(good, **{key: value}))
            self.assertEqual(ctx.exception.code, 'REVIEW_REF_INVALID', key)
        with self.assertRaises(DomainError) as ctx:
            review.queue('post', 'social/other/b2', sha, good)
        self.assertEqual(ctx.exception.code, 'REVIEW_REF_INVALID')
        self.assertFalse(ReviewItem.objects.exists())

    def test_changed_bundle_cannot_be_approved(self):
        summary = post_summary(self.base, 'b3')
        item = review.queue('post', 'social/a/b3', candidate(summary), summary)
        write_bundle(self.base, 'b3', title='A different title')
        with self.assertRaises(DomainError) as ctx:
            review.decide(self.owner, [item.pk], 'approved')
        self.assertEqual(ctx.exception.code, 'REVIEW_ITEM_CHANGED')
        self.assertEqual(ctx.exception.details['refs'], ['social/a/b3'])
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')
        write_bundle(self.base, 'b3', video=b'another-video')
        with self.assertRaises(DomainError):
            review.decide(self.owner, [item.pk], 'approved')
        self.assertEqual(review.decide(self.owner, [item.pk], 'rejected'), 1)

    def test_unchanged_bundle_is_approved(self):
        summary = post_summary(self.base, 'b4')
        item = review.queue('post', 'social/a/b4', candidate(summary), summary)
        self.assertEqual(review.decide(self.owner, [item.pk], 'approved'), 1)


def settings_base():
    from django.conf import settings
    return settings.BASE_DIR


class ReviewPageContentTests(TestCase):
    """The Monday page shows what is being approved: clearance facts, the cover pair, the post's video and caption."""
    def setUp(self):
        from django.conf import settings
        self.tmp = tempfile.TemporaryDirectory(dir=settings.BASE_DIR, prefix='.review-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.owner = make_user('owner@example.test')
        patcher = patch.object(review, 'prepare', lambda m, r: REAL_PREPARE(m, r, probe=PROBE))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.url = reverse('web:staff-review', args=['en'])

    def write(self, rel, body):
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def clearance(self):
        body = json.dumps({'status': 'DRAFT_PENDING_OWNER_APPROVAL', 'territories': ['IN', 'US'], 'formats': ['reader']}).encode()
        path = self.write('docs/evidence/publication-clearance-cl-draft.json', body)
        return review.queue_files([('clearance', path, {'edition_slug': 'cl', 'title': 'Clear title'})])[0], path

    def cover(self):
        front, back = b'\xff\xd8\xff front-bytes', b'\xff\xd8\xff back-bytes'
        self.write('library/intake/cv/front.jpg', front)
        self.write('library/intake/cv/back.jpg', back)
        provenance = {'sides': {side: {'delivery': {'sha256': hashlib.sha256(raw).hexdigest()}}
                                for side, raw in (('front', front), ('back', back))}}
        path = self.write('library/intake/cv/cover_provenance.json', json.dumps(provenance).encode())
        return review.queue_files([('cover', path, {'edition_slug': 'cv', 'title': 'Cover title'})])[0], front

    def test_clearance_facts_are_shown(self):
        self.clearance()
        login(self.client, self.owner)
        html = self.client.get(self.url).content.decode()
        for text in ('DRAFT_PENDING_OWNER_APPROVAL', 'IN, US', 'reader', 'Clear title'):
            self.assertIn(text, html)

    def test_cover_pair_is_shown_through_a_staff_only_view(self):
        item, front = self.cover()
        front_url = reverse('web:staff-review-cover', args=['en', item.pk, 'front'])
        self.assertEqual(self.client.get(front_url).status_code, 404)  # anonymous
        login(self.client, make_user('plain-c@example.test', staff=False))
        self.assertEqual(self.client.get(front_url).status_code, 404)
        login(self.client, self.owner)
        self.assertIn(f'src="{front_url}"', self.client.get(self.url).content.decode())
        response = self.client.get(front_url)
        self.assertEqual((response.status_code, response['Content-Type'], response.content), (200, 'image/jpeg', front))
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get(reverse('web:staff-review-cover', args=['en', item.pk, 'spine'])).status_code, 404)
        self.write('library/intake/cv/front.jpg', b'\xff\xd8\xff other')  # not the bytes the provenance names
        self.assertEqual(self.client.get(front_url).status_code, 404)

    def test_changed_cover_provenance_is_flagged_and_not_served(self):
        item, _ = self.cover()
        self.write('library/intake/cv/cover_provenance.json', b'{}')
        login(self.client, self.owner)
        self.assertContains(self.client.get(self.url), 'Changed since it was queued')
        self.assertEqual(self.client.get(reverse('web:staff-review-cover', args=['en', item.pk, 'front'])).status_code, 404)

    def test_post_shows_bundle_video_and_caption(self):
        summary = post_summary(self.base, 'pv')
        review.queue('post', 'social/a/pv', candidate(summary), summary)
        login(self.client, self.owner)
        html = self.client.get(self.url).content.decode()
        self.assertIn(summary['bundle_manifest'], html)
        self.assertIn(summary['asset_root'] + '/film', html)
        self.assertIn('Exact title — Exact description', html)

    def test_select_all_checks_one_group_only(self):
        clearance, _ = self.clearance()
        cover, _ = self.cover()
        login(self.client, self.owner)
        plain = self.client.get(self.url).content.decode()
        self.assertNotRegex(plain, r'<input[^>]*\bchecked\b')
        self.assertIn('?select=cover', plain)
        html = self.client.get(self.url + '?select=cover').content.decode()
        self.assertRegex(html, rf'value="{cover.pk}" checked')
        self.assertNotRegex(html, rf'value="{clearance.pk}" checked')
        self.assertIn('Clear selection', html)
