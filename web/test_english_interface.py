"""One English interface over a library of every language; readers choose the book language."""
import io
import tempfile
from django.core.management import call_command
from django.test import TestCase, override_settings

EN = '20000000-0000-4000-8000-000000000001'
BN = '20000000-0000-4000-8000-000000000002'


class EnglishInterfaceTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True)
        override.enable(); self.addCleanup(override.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())

    def test_bengali_ui_routes_redirect_to_english(self):
        for old, new in [('/bn/', '/en/'), ('/bn/explore/?q=river', '/en/explore/?q=river'), (f'/bn/titles/{EN}/', f'/en/titles/{EN}/')]:
            with self.subTest(old=old):
                response = self.client.get(old)
                # 302 + no-store on purpose: email action links carry one-time tokens.
                self.assertEqual((response.status_code, response['Location']), (302, new))
                self.assertIn('no-store', response['Cache-Control'])

    def test_home_lists_books_in_all_languages_by_default(self):
        page = self.client.get('/en/').content.decode()
        self.assertIn(EN, page)
        self.assertIn(BN, page)

    def test_content_language_filter_is_optional_reader_choice(self):
        page = self.client.get('/en/explore/', {'content_locale': 'bn'}).content.decode()
        self.assertIn(BN, page)
        self.assertNotIn(f'/en/titles/{EN}/', page)
        self.assertIn('<html lang="en"', page)

    def test_interface_is_english(self):
        self.assertIn('<html lang="en"', self.client.get('/en/').content.decode())
