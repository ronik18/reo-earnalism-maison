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

    def test_sign_in_offers_recovery_and_sign_up_but_not_itself(self):
        links = self.links('/en/sign-in/')
        self.assertIn('/en/password-reset/', links)
        self.assertIn('/en/sign-up/', links)
        self.assertNotIn('/en/sign-in/', links)

    def test_other_pages_offer_sign_in_and_never_link_to_themselves(self):
        self.assertEqual(self.links('/en/sign-up/'), ['/en/sign-in/'])
        self.assertEqual(self.links('/en/password-reset/'), ['/en/sign-in/', '/en/sign-up/'])
