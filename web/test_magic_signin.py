"""Browser-facing magic-link handoff; local outbox only, no email delivery."""
import html
import re
from urllib.parse import urlencode, parse_qs, urlsplit
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from accounts.models import EmailActionToken
from accounts.services import request_magic_signin, _token_value


@override_settings(FEATURES={**settings.FEATURES, 'email_link': True})
class MagicSigninScreensTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('magic-ui@example.test', 'Local-Magic-Fixture-2026', is_verified=True)

    def token(self, destination='/bn/vault/?tab=lists'):
        request_magic_signin(self.user.email, return_path=destination, locale='bn')
        action = EmailActionToken.objects.get(user=self.user, purpose='magic_signin', consumed_at__isnull=True)
        return action, _token_value(action)

    def test_request_is_localized_generic_and_preserves_safe_return(self):
        destination = '/bn/vault/?tab=lists'
        page = self.client.get('/bn/sign-in/', {'return_to': destination}, follow=True)
        self.assertContains(page, '/en/email-sign-in/')
        self.assertContains(page, 'Email me a sign-in link')
        path = '/en/email-sign-in/'
        missing = self.client.post(path, {'email': 'missing@example.test', 'return_to': destination})
        existing = self.client.post(path, {'email': self.user.email, 'return_to': destination})
        self.assertEqual(missing.status_code, existing.status_code)
        for response in (missing, existing):
            self.assertContains(response, '10 minutes')
            self.assertContains(response, 'If an active account matches this email')
            self.assertIn('no-store', response['Cache-Control'])
        action = EmailActionToken.objects.get(user=self.user, purpose='magic_signin')
        self.assertEqual(action.return_path, destination.replace("/bn/","/en/",1))

    def test_get_is_non_consuming_and_post_requires_csrf_then_token_bound_return(self):
        action, token = self.token()
        path = '/auth/sign-in/?' + urlencode({'token': token, 'locale': 'bn', 'return_to': '/en/settings/'})
        client = Client(enforce_csrf_checks=True)
        for _ in range(2):
            response = client.get(path)
            self.assertContains(response, 'Confirm sign in')
            self.assertEqual(response['Referrer-Policy'], 'strict-origin')
            self.assertIn('no-store', response['Cache-Control'])
        action.refresh_from_db()
        self.assertIsNone(action.consumed_at)
        self.assertFalse(client.get('/api/v1/session').json()['authenticated'])
        self.assertEqual(client.post(path).status_code, 403)
        action.refresh_from_db()
        self.assertIsNone(action.consumed_at)
        response = client.post(path, {'csrfmiddlewaretoken': client.cookies[settings.CSRF_COOKIE_NAME].value, 'return_to': '/en/settings/'})
        self.assertRedirects(response, '/en/vault/?tab=lists', fetch_redirect_response=False)
        self.assertEqual(response['Referrer-Policy'], 'strict-origin')
        self.assertTrue(client.get('/api/v1/session').json()['authenticated'])
        action.refresh_from_db()
        self.assertIsNotNone(action.consumed_at)
        replay = client.post(path, {'csrfmiddlewaretoken': client.cookies[settings.CSRF_COOKIE_NAME].value})
        self.assertContains(replay, 'link is expired', status_code=410)

    def test_legacy_token_locale_uses_english_without_consuming(self):
        action, token = self.token()
        response = self.client.get('/auth/sign-in/', {'token': token, 'locale': 'en'})
        self.assertNotContains(response, 'aria-label="Interface language"')
        self.assertContains(response, 'Confirm sign in')
        action.refresh_from_db()
        self.assertIsNone(action.consumed_at)

    @override_settings(FEATURES={**settings.FEATURES, 'email_link': False})
    def test_disabled_capability_has_no_active_link_or_confirmation(self):
        self.assertNotContains(self.client.get('/en/sign-in/'), '/en/email-sign-in/')
        self.assertNotContains(self.client.get('/en/sign-in/'), '/api/v1/auth/google?')
        self.assertEqual(self.client.get('/en/email-sign-in/').status_code, 409)
        self.assertEqual(self.client.get('/auth/sign-in/?token=unused').status_code, 409)


    @override_settings(FEATURES={**settings.FEATURES, 'google_oauth': True, 'email_link': False})
    def test_google_control_is_enabled_only_and_keeps_the_localized_destination(self):
        destination = '/bn/vault/?tab=lists'
        response = self.client.get('/bn/sign-in/', {'return_to': destination}, follow=True)
        self.assertContains(response, 'Continue with Google')
        match = re.search(r'href="(/api/v1/auth/google[^"]+)"', response.content.decode())
        self.assertIsNotNone(match)
        query = parse_qs(urlsplit(html.unescape(match[1])).query)
        self.assertEqual(query, {'intent': ['sign_in'], 'return_path': [destination.replace('/bn/','/en/',1)]})
        self.assertNotContains(self.client.get('/auth/sign-in/?locale=bn'), '/api/v1/auth/google?', status_code=409)

    def test_google_recovery_is_allowlisted_and_localized(self):
        response = self.client.get('/en/sign-in/', {'google_error': 'identity_link_required'})
        self.assertContains(response, 'then connect Google in Settings')
        self.assertContains(self.client.get('/bn/sign-in/', {'google_error': 'invalid_oauth_state'}, follow=True), 'Start again from this page')
        self.assertIsNone(self.client.get('/en/sign-in/', {'google_error': '<unsafe-provider-detail>'}).context['error_key'])

    @override_settings(FEATURES={**settings.FEATURES, 'google_oauth': True})
    def test_settings_connect_requires_fresh_identity_and_preserves_google_session_window(self):
        import json
        from django.utils import timezone
        self.client.post('/en/sign-in/', {'email': self.user.email, 'password': 'Local-Magic-Fixture-2026','password_purpose_consent':'on','password_purpose_version':'password-account-v1'})
        session = self.client.session
        session.pop('reauthenticated_at', None)
        session.save()
        response = self.client.get('/bn/settings/', follow=True)
        boot = json.loads(re.search(r'<script id="account-bootstrap" type="application/json">(.*?)</script>', response.content.decode())[1])
        self.assertTrue(boot['google_enabled'])
        self.assertFalse(boot['google_linked'])
        self.assertEqual(boot['fresh_until'], 0)
        session = self.client.session
        session['reauthenticated_at'] = timezone.now().isoformat()
        session.save()
        response = self.client.get('/bn/settings/', follow=True)
        boot = json.loads(re.search(r'<script id="account-bootstrap" type="application/json">(.*?)</script>', response.content.decode())[1])
        self.assertGreater(boot['fresh_until'], timezone.now().timestamp() * 1000)
