"""Public live covers: content-addressed immutable renditions; drafts and staff stay private (owner decision 26 Nov 2026)."""
import io
import json
import tempfile
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from PIL import Image

from .cover_renditions import (COVER_WIDTHS, IMMUTABLE_CACHE_CONTROL, UNVERSIONED_CACHE_CONTROL, clear_memo,
                               rendition, rendition_path, rendition_url)
from .models import Edition

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

    def test_rendition_url_only_rewrites_content_addressed_cover_urls(self):
        url = 'https://maison.example' + rendition_path(self.asset.pk, self.asset.sha256)
        self.assertTrue(url.endswith('/w800.jpg'))
        self.assertTrue(rendition_url(url, 160).endswith(f'/{self.asset.sha256}/w160.jpg'))
        bare = '/api/v1/staff/draft-covers/' + self.asset.pk
        self.assertEqual(rendition_url(bare, 160), bare)


class PublicCoverHeaderTests(TestCase):
    def setUp(self):
        clear_memo(); self.addCleanup(clear_memo)
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MEDIA_STORAGE_BACKEND='local', MAISON_LOCAL_FIXTURES=True,
                                     LOCAL=True, PUBLIC_BASE_URL='https://maison.example')
        override.enable(); self.addCleanup(override.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.revision = Edition.objects.get(pk=EN).live_revision
        self.asset = self.revision.assets.get(kind='cover', state='ready')

    def login(self, email, password):
        client = Client(enforce_csrf_checks=True)
        token = client.get('/api/v1/session').json()['csrf_token']
        result = client.post('/api/v1/auth/login', json.dumps({'email': email, 'password': password,
                             'password_purpose_consent': True, 'password_purpose_version': 'password-account-v1'}),
                             content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(result.status_code, 200)
        return client

    def get(self, path, client=None, **headers):
        return (client or self.client).get(path, **headers)

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

    def test_signed_in_reader_gets_the_same_public_bytes(self):
        member = get_user_model().objects.create_user('cover-reader@example.test', 'Ordinary-Password-47', is_verified=True)
        client = self.login(member.email, 'Ordinary-Password-47')
        response = self.get(rendition_path(self.asset.id, self.asset.sha256, 160), client=client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], IMMUTABLE_CACHE_CONTROL)

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
