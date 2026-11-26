"""Cover thumbnails load a small reviewed width; the title page uses 480/800 (owner decision 26 Nov 2026)."""
import io
import re
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase, override_settings

from library.models import Edition

EN = '20000000-0000-4000-8000-000000000001'


class CoverSrcsetTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory(); self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name, MEDIA_STORAGE_BACKEND='local', LOCAL=True, MAISON_LOCAL_FIXTURES=True)
        override.enable(); self.addCleanup(override.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        asset = Edition.objects.get(pk=EN).live_revision.assets.get(kind='cover', state='ready')
        self.prefix = f'/api/v1/content/covers/{asset.id}/{asset.sha256}/'

    def images(self, path):
        response = self.client.get(path, follow=True)
        self.assertEqual(response.status_code, 200)
        return [tag for tag in re.findall(r'<img [^>]*>', response.content.decode()) if self.prefix in tag]

    def test_explore_cards_use_thumbnail_srcset(self):
        tags = self.images('/en/explore/')
        self.assertTrue(tags)
        for tag in tags:
            self.assertRegex(tag, 'src="[^"]*' + re.escape(self.prefix) + r'w160\.jpg"')
            self.assertRegex(tag, r'srcset="[^"]*w160\.jpg 160w, [^"]*w320\.jpg 320w"')
            self.assertIn('sizes="64px"', tag)
            self.assertNotIn('w800.jpg', tag)

    def test_home_shelf_uses_small_widths(self):
        tags = self.images('/en/')
        self.assertTrue(tags)
        for tag in tags:
            self.assertIn('w320.jpg"', tag)
            self.assertIn('160w', tag); self.assertIn('480w', tag); self.assertNotIn('800w', tag)

    def test_title_page_uses_480_and_800(self):
        tags = self.images(f'/en/titles/{EN}/')
        self.assertEqual(len(tags), 1)
        self.assertIn('w480.jpg"', tags[0])
        self.assertRegex(tags[0], r'srcset="[^"]*w480\.jpg 480w, [^"]*w800\.jpg 800w"')
        self.assertIn('sizes="', tags[0])
