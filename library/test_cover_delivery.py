"""Public covers revalidate with a strong content validator instead of re-sending bytes."""
import io
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from .models import Edition

EN = '20000000-0000-4000-8000-000000000001'


class CoverRevalidationTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True,
                                     PUBLIC_BASE_URL='https://maison.example', ALLOWED_HOSTS=['maison.example'])
        override.enable(); self.addCleanup(override.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.asset = Edition.objects.get(pk=EN).live_revision.assets.get(kind='cover', state='ready')
        self.path = f'/api/v1/content/covers/{self.asset.id}?locale=en&territory=IN'

    def get(self, **headers):
        # An anonymous public edge request, as the CDN forwards it.
        return self.client.get(self.path, HTTP_HOST='maison.example', secure=True, **headers)

    def test_cover_carries_its_content_hash_as_strong_etag(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['ETag'], f'"{self.asset.sha256}"')
        self.assertIn('public', response['Cache-Control'])

    def test_matching_validator_returns_not_modified_without_body(self):
        response = self.get(HTTP_IF_NONE_MATCH=f'"{self.asset.sha256}"')
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b'')
        self.assertEqual(response['ETag'], f'"{self.asset.sha256}"')
        self.assertTrue(response['Cloudflare-CDN-Cache-Control'].startswith('public, max-age='))
