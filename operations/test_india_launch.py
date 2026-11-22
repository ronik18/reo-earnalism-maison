"""India-first service placement is separate from edition publication rights."""
from unittest.mock import Mock,patch
from django.http import HttpResponse
from django.test import SimpleTestCase,RequestFactory,override_settings
from .middleware import OriginMiddleware

@override_settings(LOCAL=False,INDIA_FIRST_LAUNCH_ENABLED=True,MAISON_SERVICE_TERRITORIES=('IN',),ORIGIN_SHARED_SECRET='synthetic-origin-only')
class IndiaFirstServiceTests(SimpleTestCase):
    def request(self,path='/api/v1/auth/register',country='IN',origin='synthetic-origin-only'):
        r=RequestFactory().post(path,data=b'{"password":"never parsed"}',content_type='application/json',HTTP_X_MAISON_ORIGIN=origin,HTTP_X_MAISON_COUNTRY=country)
        r.request_id='synthetic-trace';r.territory='ZZ'
        return r

    def test_only_trusted_india_reaches_session_and_body_handling(self):
        for country in ['IN','GB','US','ZZ','XX','in','IN,GB','']:
            with self.subTest(country=country):
                handler=Mock(return_value=HttpResponse('application'))
                r=self.request(country=country)
                # Any attempt to read the body by the rejecting middleware fails.
                r._stream=Mock();r._stream.read.side_effect=AssertionError('Do not collect rejected account data')
                response=OriginMiddleware(handler)(r)
                self.assertEqual(response.status_code,200 if country=='IN' else 403)
                self.assertEqual(handler.call_count,1 if country=='IN' else 0)
                r._stream.read.assert_not_called()
                if country!='IN':
                    self.assertEqual(response['Cache-Control'],'private, no-store')
                    self.assertIn(b'service_region_unavailable',response.content)

    def test_forged_origin_cannot_choose_india(self):
        handler=Mock();response=OriginMiddleware(handler)(self.request(origin='forged'))
        self.assertEqual(response.status_code,403);self.assertIn(b'origin_forbidden',response.content);handler.assert_not_called()

    def test_legal_help_and_health_keep_their_original_authorization(self):
        for path in ['/en/privacy/','/en/terms/','/en/contact/','/bn/privacy/','/api/v1/health/ready','/api/v1/health/live']:
            with self.subTest(path=path):
                handler=Mock(return_value=HttpResponse('unchanged endpoint authorization'))
                self.assertEqual(OriginMiddleware(handler)(self.request(path,country='GB')).status_code,200)
                handler.assert_called_once()
        handler=Mock();self.assertEqual(OriginMiddleware(handler)(self.request('/api/v1/health/ready',origin='forged')).status_code,403)
        handler.assert_not_called()

    def test_html_unavailable_response_has_no_account_form_or_redirect(self):
        with patch('django.shortcuts.render',return_value=HttpResponse('India-first',status=403)) as render:
            handler=Mock();response=OriginMiddleware(handler)(self.request('/en/sign-up/',country='GB'))
        self.assertEqual(response.status_code,403);self.assertNotIn('Location',response)
        self.assertEqual(render.call_args.args[1],'web/region_unavailable.html');handler.assert_not_called()

    @override_settings(INDIA_FIRST_LAUNCH_ENABLED=False)
    def test_historical_local_fixture_scope_is_not_silently_rewritten(self):
        handler=Mock(return_value=HttpResponse('existing fixture scope'))
        self.assertEqual(OriginMiddleware(handler)(self.request(country='GB')).status_code,200)
        handler.assert_called_once()
