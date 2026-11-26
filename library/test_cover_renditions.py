"""Public live covers: content-addressed renditions, rights-capped and purge-recorded; drafts and staff stay private (owner decision 26 Nov 2026)."""
import io
import json
import re
import tempfile
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image

from core.api import DomainError
from core.models import OutboxJob
from operations.models import PublicCacheReference
from operations.providers import _urls
from .cover_renditions import (COVER_WIDTHS, IMMUTABLE_CACHE_CONTROL, UNVERSIONED_CACHE_CONTROL, all_cover_paths,
                               browser_cache_control, clear_memo, rendition, rendition_path, rendition_url)
from .models import Edition, Rights

EN = '20000000-0000-4000-8000-000000000001'


def jpeg(width=800, height=1200):
    out = io.BytesIO()
    Image.new('RGB', (width, height), (120, 40, 60)).save(out, 'JPEG', quality=90)
    return out.getvalue()


class RenditionSizeTests(SimpleTestCase):
    def setUp(self):
        clear_memo(); self.addCleanup(clear_memo)
        self.raw = jpeg()
        self.asset = SimpleNamespace(pk='00000000-0000-4000-8000-0000000000aa', sha256='a' * 64, content_type='image/jpeg')
        self.reads = 0

    def read(self, asset):
        self.reads += 1
        return self.raw

    def test_each_width_keeps_two_by_three_and_the_original_is_untouched(self):
        for width in COVER_WIDTHS:
            with self.subTest(width=width):
                raw, content_type = rendition(self.asset, width, self.read)
                image = Image.open(io.BytesIO(raw))
                self.assertEqual(image.size, (width, width * 3 // 2))
                self.assertEqual(content_type, 'image/jpeg')
        # 800 is the original's width: its exact bytes are served, never re-encoded.
        self.assertEqual(rendition(self.asset, 800, self.read)[0], self.raw)
        self.assertLess(len(rendition(self.asset, 160, self.read)[0]), len(self.raw))

    def test_derived_widths_are_memoized_and_other_widths_refused(self):
        rendition(self.asset, 320, self.read); rendition(self.asset, 320, self.read)
        self.assertEqual(self.reads, 1)
        with self.assertRaises(ValueError):
            rendition(self.asset, 333, self.read)
        with self.assertRaises(ValueError):
            rendition_path(self.asset.pk, self.asset.sha256, 1600)

    def test_corrupt_original_is_an_integrity_failure_not_a_crash(self):
        with self.assertRaises(DomainError) as raised:
            rendition(self.asset, 160, lambda asset: b'not an image')
        self.assertEqual(raised.exception.status, 503)

    def test_rendition_url_only_rewrites_content_addressed_cover_urls(self):
        url = 'https://maison.example' + rendition_path(self.asset.pk, self.asset.sha256)
        self.assertTrue(url.endswith('/w800.jpg'))
        self.assertTrue(rendition_url(url, 160).endswith(f'/{self.asset.sha256}/w160.jpg'))
        bare = '/api/v1/staff/draft-covers/' + self.asset.pk
        self.assertEqual(rendition_url(bare, 160), bare)

    def test_browser_policy_never_outlives_rights(self):
        far = 10 * 31536000
        self.assertEqual(browser_cache_control(True, far), IMMUTABLE_CACHE_CONTROL)
        self.assertEqual(browser_cache_control(False, far), UNVERSIONED_CACHE_CONTROL)
        self.assertEqual(browser_cache_control(True, 500), 'public, max-age=500, immutable')
        self.assertEqual(browser_cache_control(False, 86400 + 604800 - 1), 'public, max-age=86400')
        self.assertEqual(browser_cache_control(False, 500), 'public, max-age=500')


@override_settings(MAISON_PUBLICATION_TERRITORIES=('IN',))
class PublicCoverHeaderTests(TestCase):
    def setUp(self):
        clear_memo(); self.addCleanup(clear_memo)
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MEDIA_STORAGE_BACKEND='local', MAISON_LOCAL_FIXTURES=True,
                                     LOCAL=True, PUBLIC_BASE_URL='https://maison.example',
                                     ALLOWED_HOSTS=['maison.example', 'testserver'])
        override.enable(); self.addCleanup(override.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.revision = Edition.objects.get(pk=EN).live_revision
        self.asset = self.revision.assets.get(kind='cover', state='ready')
        self.rights_until(timedelta(days=800))

    def rights_until(self, delta):
        Rights.objects.filter(revision=self.revision).update(ends_at=timezone.now() + delta)

    def login(self, email, password):
        client = Client(enforce_csrf_checks=True)
        token = client.get('/api/v1/session').json()['csrf_token']
        result = client.post('/api/v1/auth/login', json.dumps({'email': email, 'password': password,
                             'password_purpose_consent': True, 'password_purpose_version': 'password-account-v1'}),
                             content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(result.status_code, 200)
        return client

    def get(self, path, client=None, **headers):
        if client is not None:
            return client.get(path, **headers)
        # An anonymous edge request on the configured public origin.
        return self.client.get(path, HTTP_HOST='maison.example', secure=True, **headers)

    def max_age(self, response):
        return int(re.search(r'max-age=(\d+)', response['Cache-Control'])[1])

    def test_live_rendition_is_public_immutable_with_bounded_edge(self):
        for width in COVER_WIDTHS:
            with self.subTest(width=width):
                response = self.get(rendition_path(self.asset.id, self.asset.sha256, width))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Cache-Control'], IMMUTABLE_CACHE_CONTROL)
                self.assertEqual(response['ETag'], f'"{self.asset.sha256}-w{width}"')
                self.assertEqual(response['Cloudflare-CDN-Cache-Control'], 'public, max-age=3600, stale-while-revalidate=0, stale-if-error=0')
                self.assertNotIn('Cookie', response.get('Vary', ''))
                image = Image.open(io.BytesIO(response.content))
                # The local fixture original is 600x900 PNG: smaller widths are resized, larger ones serve it as is.
                self.assertEqual(image.size, (width, width * 3 // 2) if width < 600 else (600, 900))
        again = self.get(rendition_path(self.asset.id, self.asset.sha256, 320), HTTP_IF_NONE_MATCH=f'"{self.asset.sha256}-w320"')
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again['Cache-Control'], IMMUTABLE_CACHE_CONTROL)

    def test_signed_in_reader_gets_public_bytes_but_no_edge_copy(self):
        member = get_user_model().objects.create_user('cover-reader@example.test', 'Ordinary-Password-47', is_verified=True)
        client = self.login(member.email, 'Ordinary-Password-47')
        response = self.get(rendition_path(self.asset.id, self.asset.sha256, 160), client=client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], IMMUTABLE_CACHE_CONTROL)
        self.assertEqual(response['CDN-Cache-Control'], 'no-store')
        self.assertFalse(PublicCacheReference.objects.exists())

    def test_unversioned_live_cover_is_public_but_not_immutable(self):
        response = self.get(f'/api/v1/content/covers/{self.asset.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], UNVERSIONED_CACHE_CONTROL)
        self.assertEqual(response.content, (self.get(rendition_path(self.asset.id, self.asset.sha256, 800))).content)

    def test_wrong_version_or_width_is_not_found_and_private(self):
        for path in [rendition_path(self.asset.id, 'b' * 64, 320),
                     f'/api/v1/content/covers/{self.asset.id}/{self.asset.sha256}/w333.jpg']:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertIn('no-store', response['Cache-Control'])

    def test_query_strings_and_noncanonical_widths_are_not_found(self):
        """I3: the cacheable cover keys are exactly the five query-less paths per asset."""
        rendition_160 = rendition_path(self.asset.id, self.asset.sha256, 160)
        for path in [rendition_160 + '?x=1', rendition_160 + '?locale=en&territory=IN',
                     f'/api/v1/content/covers/{self.asset.id}?locale=en&territory=IN',
                     f'/api/v1/content/covers/{self.asset.id}/{self.asset.sha256}/w0160.jpg',
                     f'/api/v1/content/covers/{self.asset.id}/{self.asset.sha256}/w000160.jpg']:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertIn('no-store', response['Cache-Control'])
        self.assertFalse(PublicCacheReference.objects.exists())

    def test_browser_and_edge_freshness_are_capped_by_rights_end(self):
        """I2: never fresh, immutable or stale-served beyond the known rights end."""
        self.rights_until(timedelta(days=2))
        response = self.get(rendition_path(self.asset.id, self.asset.sha256, 320))
        self.assertTrue(response['Cache-Control'].endswith(', immutable'))
        self.assertLessEqual(self.max_age(response), 2 * 86400)
        self.assertGreater(self.max_age(response), 86400)
        self.assertEqual(response['Cloudflare-CDN-Cache-Control'], 'public, max-age=3600, stale-while-revalidate=0, stale-if-error=0')
        bare = self.get(f'/api/v1/content/covers/{self.asset.id}')
        self.assertEqual(bare['Cache-Control'], 'public, max-age=86400')  # SWR would outlive the deadline
        self.rights_until(timedelta(seconds=90))
        for path in [rendition_path(self.asset.id, self.asset.sha256, 160), f'/api/v1/content/covers/{self.asset.id}']:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertLessEqual(self.max_age(response), 90)
                self.assertNotIn('stale-while-revalidate', response['Cache-Control'])
                edge = int(re.search(r'max-age=(\d+)', response['Cloudflare-CDN-Cache-Control'])[1])
                self.assertLessEqual(edge, 90)

    @override_settings(MAISON_PUBLICATION_TERRITORIES=('IN', 'US'))
    def test_cover_not_cleared_in_every_territory_stays_private(self):
        """I4: the shared key has no territory, so every active territory must be cleared."""
        response = self.get(rendition_path(self.asset.id, self.asset.sha256, 320))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['CDN-Cache-Control'], 'no-store')
        self.assertFalse(PublicCacheReference.objects.exists())
        now = timezone.now()
        for action in ('read', 'preview', 'download'):
            Rights.objects.create(revision=self.revision, format='reader', action=action, territories=['US'],
                                  starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=3), approved=True,
                                  test_only=True, evidence='Local cover clearance fixture only')
        response = self.get(rendition_path(self.asset.id, self.asset.sha256, 320))
        self.assertTrue(response['Cache-Control'].startswith('public, max-age='))
        self.assertLessEqual(self.max_age(response), 3 * 86400)  # earliest rights end across territories

    def test_emitted_cover_urls_are_recorded_and_purged_on_withdrawal(self):
        """I1: each recorded cover URL, its sibling widths and unversioned path are purged on withdrawal."""
        self.get(rendition_path(self.asset.id, self.asset.sha256, 160))
        self.get(f'/api/v1/content/covers/{self.asset.id}')
        base = 'https://maison.example'
        self.assertEqual({row.url for row in PublicCacheReference.objects.all()},
                         {base + rendition_path(self.asset.id, self.asset.sha256, 160),
                          base + f'/api/v1/content/covers/{self.asset.id}'})
        for row in PublicCacheReference.objects.all():
            self.assertIn('revision:' + str(self.revision.id), row.dependencies)
            self.assertIn('asset:' + str(self.asset.id), row.dependencies)
        staff = get_user_model().objects.create_superuser('withdraw-staff@example.test', 'Local-Intake-Password-47')
        from .services import transition_revision
        transition_revision(staff, self.revision.id, 'withdraw', self.revision.version, self.revision.content_sha256,
                            'Rights pulled early in this local test.')
        urls = {url for job in OutboxJob.objects.filter(kind='catalog_cache_purge') for url in job.payload['urls']}
        expected = sorted(base + path for path in all_cover_paths(self.asset.id, self.asset.sha256))
        self.assertTrue(set(expected).issubset(urls), urls)
        self.assertEqual(_urls({'urls': expected}, 'maison.example'), expected)
        self.assertEqual(self.get(rendition_path(self.asset.id, self.asset.sha256, 160)).status_code, 404)

    def ledger_writes(self, path, **headers):
        with CaptureQueriesContext(connection) as queries:
            response = self.get(path, **headers)
        writes = [q['sql'] for q in queries.captured_queries
                  if 'maison_public_cache_' in q['sql'] and re.search(r'^\s*(INSERT|UPDATE)|FOR (UPDATE|SHARE)', q['sql'])]
        return response, writes

    def test_repeat_requests_and_revalidations_do_not_rewrite_the_ledger(self):
        """Ledger load: two consecutive anonymous requests write once; a 304 never writes."""
        path = rendition_path(self.asset.id, self.asset.sha256, 160)
        first, writes = self.ledger_writes(path)
        self.assertEqual(first.status_code, 200); self.assertTrue(writes)
        expires = PublicCacheReference.objects.get().expires_at
        second, writes = self.ledger_writes(path)
        self.assertEqual(second.status_code, 200); self.assertEqual(writes, [])
        self.assertTrue(second['CDN-Cache-Control'].startswith('public, max-age='))
        revalidated, writes = self.ledger_writes(path, HTTP_IF_NONE_MATCH=f'"{self.asset.sha256}-w160"')
        self.assertEqual(revalidated.status_code, 304); self.assertEqual(writes, [])
        self.assertTrue(revalidated['CDN-Cache-Control'].startswith('public, max-age='))
        self.assertEqual(PublicCacheReference.objects.get().expires_at, expires)

    def test_unrecorded_conditional_request_gets_full_response_and_one_write(self):
        path = rendition_path(self.asset.id, self.asset.sha256, 320)
        response, writes = self.ledger_writes(path, HTTP_IF_NONE_MATCH=f'"{self.asset.sha256}-w320"')
        self.assertEqual(response.status_code, 200); self.assertTrue(writes)
        self.assertEqual(PublicCacheReference.objects.count(), 1)

    def test_epoch_change_after_recording_refuses_the_edge_copy(self):
        path = rendition_path(self.asset.id, self.asset.sha256, 160)
        self.get(path)
        from .services import queue_catalog_purge
        queue_catalog_purge(self.revision)  # bumps the generation epoch; the row remains for the purge
        response = self.get(path)
        self.assertTrue(response['CDN-Cache-Control'].startswith('public, max-age='))  # a new request starts in the new epoch

    def test_draft_cover_is_not_public_and_staff_copy_stays_no_store(self):
        from .services import clone_revision
        draft = clone_revision(self.revision.id)
        asset = draft.assets.get(kind='cover', state='ready')
        for path in [rendition_path(asset.id, asset.sha256, 320), f'/api/v1/content/covers/{asset.id}']:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertIn('no-store', response['Cache-Control'])
        staff = get_user_model().objects.create_superuser('cover-staff@example.test', 'Local-Intake-Password-47')
        client = self.login(staff.email, 'Local-Intake-Password-47')
        response = client.get(f'/api/v1/staff/draft-covers/{asset.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['CDN-Cache-Control'], 'no-store')

    def test_withdrawn_revision_cover_rendition_is_gone(self):
        self.revision.state = 'retired'; self.revision.save(update_fields=['state'])
        response = self.get(rendition_path(self.asset.id, self.asset.sha256, 160))
        self.assertEqual(response.status_code, 404)
        self.assertIn('no-store', response['Cache-Control'])
