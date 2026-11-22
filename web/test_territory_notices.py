"""Every active territory has its own privacy section; availability names the active countries."""
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from config.territories import validate_territory_notices

ROWS = {'IN': {'name': 'India', 'sections': [{'heading': 'India', 'body': 'Indian rights text.'}]},
        'BR': {'name': 'Brazil', 'sections': [{'heading': 'Brazil (LGPD)', 'body': 'Encarregado contact: sales@reoenterprise.org.'}]}}


class TerritoryNoticeConfigTests(TestCase):
    def test_active_territory_without_notice_fails_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_territory_notices({'IN': ROWS['IN']}, ('IN', 'BR'))

    def test_notice_row_needs_sections(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_territory_notices({'IN': {'name': 'India', 'sections': []}}, ('IN',))

    def test_shipped_notices_cover_all_launch_territories(self):
        import json
        from django.conf import settings
        rows = json.loads((settings.BASE_DIR / 'contracts/territory-notices.json').read_text())
        launch = ('IN', 'US', 'GB', 'BR', 'SG', 'MY', 'ID', 'PH', 'TH')
        self.assertEqual(validate_territory_notices(rows, launch).keys() >= set(launch), True)


@override_settings(INDIA_FIRST_LAUNCH_ENABLED=True, MAISON_SERVICE_TERRITORIES=('IN', 'BR'), TERRITORY_NOTICES=ROWS)
class TerritoryNoticePageTests(TestCase):
    def test_privacy_page_renders_each_active_territory_section(self):
        response = self.client.get('/en/privacy/')
        self.assertContains(response, 'Brazil (LGPD)')
        self.assertContains(response, 'Encarregado contact')
        self.assertContains(response, 'Indian rights text.')

    def test_terms_name_the_active_countries(self):
        response = self.client.get('/en/terms/')
        self.assertContains(response, 'India and Brazil')
        self.assertNotContains(response, 'currently available from India')
