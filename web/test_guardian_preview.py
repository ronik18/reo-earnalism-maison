"""The unqualified guardian preview must never become a collection journey."""
from html.parser import HTMLParser
from django.test import SimpleTestCase, override_settings


class InputElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = []

    def handle_starttag(self, tag, attrs):
        if tag in {'form', 'input', 'select', 'textarea'}:
            self.inputs.append(tag)


class GuardianPreviewTests(SimpleTestCase):
    @override_settings(GUARDIAN_AUTHORIZATION_ENABLED=False)
    def test_disabled_preview_is_not_publicly_available(self):
        for path in ('/en/guardian/', '/bn/guardian/'):
            self.assertEqual(self.client.get(path, follow=True).status_code, 404)

    @override_settings(GUARDIAN_AUTHORIZATION_ENABLED=True)
    def test_enabled_preview_is_english_information_only_with_existing_rights_destinations(self):
        for path in ('/en/guardian/', '/bn/guardian/'):
            response = self.client.get(path, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Language'], 'en')
            self.assertIn('no-store', response['Cache-Control'])
            self.assertContains(response, 'Guardian permissions are not available yet.')
            self.assertContains(response, 'No guardian request or permission is recorded here.')
            self.assertContains(response, 'still under review')
            self.assertContains(response, 'href="/en/privacy/"')
            self.assertContains(response, 'href="/en/settings/"')
            self.assertContains(response, 'href="/en/contact/"')
            self.assertContains(response, 'Do not send a child')
            self.assertContains(response, 'A contact message is not verified guardian permission.')
            parser = InputElements()
            parser.feed(response.content.decode())
            self.assertEqual(parser.inputs, [])
            self.assertNotContains(response, 'guardian-bootstrap')

    @override_settings(GUARDIAN_AUTHORIZATION_ENABLED=True)
    def test_preview_rejects_submission_and_unknown_locale(self):
        response = self.client.post('/en/guardian/', {'child_email': 'not-collected@example.test'})
        self.assertEqual(response.status_code, 405)
        self.assertNotIn('not-collected@example.test', response.content.decode())
        self.assertEqual(self.client.get('/fr/guardian/').status_code, 404)
