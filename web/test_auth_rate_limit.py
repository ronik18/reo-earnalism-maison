"""A rate-limited sign-in says so, instead of claiming the password is wrong."""
from django.contrib.auth import get_user_model
from django.test import TestCase

PASSWORD = {'password_purpose_consent': 'on', 'password_purpose_version': 'password-account-v1'}


class SignInRateLimitMessageTests(TestCase):
    def test_sixth_attempt_in_window_says_wait(self):
        get_user_model().objects.create_user('limited@example.test', 'Original-Limited-Passphrase-47', is_verified=True)
        for _ in range(5):
            self.client.post('/en/sign-in/', {'email': 'limited@example.test', 'password': 'wrong-password-value', **PASSWORD})
        response = self.client.post('/en/sign-in/', {'email': 'limited@example.test', 'password': 'Original-Limited-Passphrase-47', **PASSWORD})
        self.assertEqual(response.status_code, 429)
        import re
        alert = re.search(r'role="alert">([^<]*)<', response.content.decode())
        self.assertIsNotNone(alert, 'the page shows an alert, not raw JSON')
        self.assertEqual(alert[1], 'Too many sign-in attempts. Wait a few minutes and try again.')
        self.assertTrue(response['Content-Type'].startswith('text/html'))


class GoogleAdultDeclarationMessageTests(TestCase):
    def test_sign_in_page_explains_missing_adult_declaration(self):
        response = self.client.get('/en/sign-in/', {'google_error': 'adult_declaration_required'})
        import re
        alert = re.search(r'role="alert">([^<]*)<', response.content.decode())
        self.assertIsNotNone(alert)
        self.assertEqual(alert[1], 'Please confirm that you are 18 or older to create an account here.')


class AuthLinksTests(TestCase):
    """Each auth page links only to the routes that make sense there, never to itself."""
    def links(self, path):
        import re
        html = self.client.get(path).content.decode()
        row = html.split('class="auth-links"', 1)[1].split('</div>', 1)[0]
        return re.findall(r'href="(/en/[a-z-]+/)', row)

    def test_sign_in_offers_sign_up_but_not_itself(self):
        links = self.links('/en/sign-in/')
        self.assertIn('/en/sign-up/', links)
        self.assertNotIn('/en/sign-in/', links)

    def test_other_pages_offer_sign_in_and_never_link_to_themselves(self):
        self.assertEqual(self.links('/en/sign-up/'), ['/en/sign-in/'])
        self.assertEqual(self.links('/en/password-reset/'), ['/en/sign-in/', '/en/sign-up/'])


from django.conf import settings
from django.test import override_settings


@override_settings(FEATURES={**settings.FEATURES, 'google_oauth': True, 'email_link': True})
class SimplifiedSignInTests(TestCase):
    """UI review 25 Nov 2026: one obvious path, then the alternatives."""
    def page(self, **params):
        return self.client.get('/en/sign-in/', params).content.decode()

    def test_form_comes_first_and_alternatives_follow_it(self):
        html = self.page()
        form, google, email_link = html.index('data-auth-form'), html.index('Continue with Google'), html.index('Email me a sign-in link')
        self.assertLess(form, google)
        self.assertLess(form, email_link)
        self.assertIn('Works after you connect Google in Settings.', html)
        self.assertNotIn('Google signs in an existing account here', html)
        self.assertLess(html.index('Email me a sign-in link'), html.index('id="auth-help-island"'))  # alternatives before the help island

    def test_forgot_password_sits_under_the_password_field(self):
        html = self.page()
        self.assertLess(html.index('id="auth-password"'), html.index('Forgot your password?'))
        self.assertLess(html.index('Forgot your password?'), html.index('type="submit"'))

    def test_sign_in_appears_only_as_heading_and_button_in_the_panel(self):
        panel = self.page().split('class="narrow auth-panel"', 1)[1].split('</section>', 1)[0]
        import re
        visible = re.sub(r'<[^>]+>', ' ', panel)
        self.assertEqual(len(re.findall(r'\bSign in\b', visible)), 2)

    def test_busy_label_error_focus_and_no_competing_header_cta(self):
        html = self.page(google_error='identity_link_required')
        self.assertIn('data-busy-label="Signing in…"', html)
        self.assertIn('class="error-notice" role="alert" tabindex="-1" autofocus', html)
        self.assertNotIn('class="room-cta"', html)
        self.assertIn('class="room-cta"', self.client.get('/en/explore/').content.decode())
