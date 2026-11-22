"""Service availability is a configured list of trusted edge territories."""
from unittest.mock import Mock
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from config.territories import parse_service_territories
from .middleware import OriginMiddleware


class ParseServiceTerritoriesTests(SimpleTestCase):
    def test_default_is_india_only(self):
        self.assertEqual(parse_service_territories('', settings.MAISON_PUBLICATION_TERRITORIES), ('IN',))

    def test_list_is_normalized_and_deduplicated(self):
        self.assertEqual(parse_service_territories(' in, BR ,IN', ('IN', 'BR')), ('IN', 'BR'))

    def test_env_list_must_be_subset_of_publication_whitelist(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_service_territories('IN,VN', ('IN', 'BR'))

    def test_malformed_code_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_service_territories('IN,BRA', ('IN', 'BR'))


@override_settings(LOCAL=False, INDIA_FIRST_LAUNCH_ENABLED=True, MAISON_SERVICE_TERRITORIES=('IN', 'BR'),
                   ORIGIN_SHARED_SECRET='synthetic-origin-only')
class ServiceGateTests(SimpleTestCase):
    def request(self, country, path='/api/v1/auth/register'):
        r = RequestFactory().post(path, data=b'{}', content_type='application/json',
                                  HTTP_X_MAISON_ORIGIN='synthetic-origin-only', HTTP_X_MAISON_COUNTRY=country)
        r.request_id = 'synthetic-trace'; r.territory = 'ZZ'
        return r

    def test_listed_territory_reaches_app(self):
        handler = Mock(return_value=HttpResponse('application'))
        self.assertEqual(OriginMiddleware(handler)(self.request('BR')).status_code, 200)
        handler.assert_called_once()

    def test_unlisted_territory_is_refused_before_session(self):
        handler = Mock()
        response = OriginMiddleware(handler)(self.request('FR'))
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'service_region_unavailable', response.content)
        self.assertFalse(response.has_header('Set-Cookie'))
        handler.assert_not_called()

    def test_refusal_copy_is_territory_neutral(self):
        response = OriginMiddleware(Mock())(self.request('FR'))
        self.assertNotIn(b'India', response.content)
        self.assertIn(b'not yet available in your country', response.content)
        page = render_to_string('web/region_unavailable.html')
        self.assertNotIn('India', page)
        self.assertIn('not yet available in your country', page)
