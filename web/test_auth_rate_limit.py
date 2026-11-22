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
