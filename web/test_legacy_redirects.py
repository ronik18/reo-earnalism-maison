"""Old theearnalism.com addresses land on a Maison page, or an honest 410 Gone."""
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase

SITEMAP = Path(__file__).with_name('legacy_sitemap_paths.txt').read_text().split()


class LegacyRedirectTests(TestCase):
    def test_static_pages_redirect_301(self):
        for old, new in [('/privacy', '/en/privacy/'), ('/terms', '/en/terms/'), ('/contact', '/en/contact/'),
                         ('/pricing', '/en/pass/'), ('/about', '/en/'), ('/copyright', '/en/terms/'),
                         ('/journal', '/en/'), ('/micro-story', '/en/')]:
            with self.subTest(old=old):
                response = self.client.get(old)
                self.assertEqual((response.status_code, response['Location']), (301, new))

    def test_library_category_query_is_dropped(self):
        response = self.client.get('/library', {'category': 'gothic-fiction'})
        self.assertEqual((response.status_code, response['Location']), (301, '/en/explore/'))

    def test_unknown_book_slug_is_410(self):
        for path in ['/book/dracula', '/reader/dracula', '/book/bn-035']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 410)

    def test_republished_book_slug_redirects_to_title(self):
        with patch.dict('web.legacy_redirects.LEGACY_TITLES', {'the-selfish-giant': '20000000-0000-4000-8000-0000000000aa'}):
            for path in ['/book/the-selfish-giant', '/reader/the-selfish-giant']:
                response = self.client.get(path)
                self.assertEqual((response.status_code, response['Location']),
                                 (301, '/en/titles/20000000-0000-4000-8000-0000000000aa/'))

    def test_every_legacy_sitemap_path_has_an_answer(self):
        for path in SITEMAP:
            with self.subTest(path=path):
                self.assertIn(self.client.get(path).status_code, {301, 302, 410}, path)

    def test_maison_routes_unaffected(self):
        self.assertEqual(self.client.get('/en/privacy/').status_code, 200)
