"""Revenue plan Step 3.2: the Reader's side-by-side bn/en toggle."""
import io
import re
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from billing.models import Entitlement
from library import services
from library.models import Edition, Paragraph

EN = '20000000-0000-4000-8000-000000000001'
BN = '20000000-0000-4000-8000-000000000002'
EN_UNIT = '40000000-0000-4000-8000-000000000001'
BN_UNIT = '40000000-0000-4000-8000-000000000002'


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=True, FREE_ACCESS_ENABLED=True)
class ParallelReaderTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name); media.enable(); self.addCleanup(media.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.member = get_user_model().objects.create_user('parallel@example.test', 'Parallel-Reader-Passphrase-26', is_verified=True)
        self.sign_in()
        self.bn_rows = list(Paragraph.objects.filter(unit_id=BN_UNIT).order_by('ordinal'))
        self.en_rows = list(Paragraph.objects.filter(unit_id=EN_UNIT).order_by('ordinal'))

    def sign_in(self):
        self.client.get(reverse('web:sign-in', args=['en']))
        response = self.client.post(reverse('web:sign-in', args=['en']), {
            'email': self.member.email, 'password': 'Parallel-Reader-Passphrase-26', 'return_to': '/en/vault/',
            'password_purpose_consent': 'on', 'password_purpose_version': 'password-account-v1'})
        self.assertEqual(response.status_code, 302)

    def translate(self, method='ai', credit=''):
        Edition.objects.filter(pk=EN).update(translated_from_id=BN, translation_method=method, translation_credit=credit)

    def read(self, edition=BN, unit=BN_UNIT):
        response = self.client.get(f'/en/read/{edition}/{unit}/')
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_pair_markup_from_the_original_has_both_columns_with_their_languages_and_anchors(self):
        self.translate()
        html = self.read()
        self.assertIn('<button id="parallel-toggle" type="button" aria-pressed="false" aria-controls="reading-text" hidden>Side by side</button>', html)
        self.assertIn('id="reading-text" lang="bn" data-parallel>', html)
        self.assertIn('<span id="parallel-caption" hidden>Original and translation, side by side</span>', html)
        self.assertRegex(html, r'<p class="parallel-label" data-parallel-head>Bengali · Original</p><p class="parallel-label" data-parallel-head>English · AI translation</p>')
        for bn, en in zip(self.bn_rows, self.en_rows):
            row = (f'<div class="parallel-row" data-parallel-row><div class="parallel-cell" lang="bn">'
                   f'<p id="anchor-{bn.anchor_id}" data-anchor="{bn.anchor_id}">{escape(bn.text)}</p></div>'
                   f'<div class="parallel-cell" lang="en" data-companion hidden>'
                   f'<p data-companion-anchor="{en.anchor_id}">{escape(en.text)}</p></div></div>')
            self.assertIn(row, html)
        self.assertEqual(html.count('data-anchor='), len(self.bn_rows), 'companion text never becomes a progress/annotation anchor')
        self.assertEqual(len(re.findall(r'id="anchor-', html)), len(self.bn_rows))

    def test_from_the_translation_the_original_stays_first_and_the_label_stays_visible(self):
        self.translate('ai_edited', 'Asha Rahman')
        html = self.read(EN, EN_UNIT)
        self.assertIn('<p class="fine">Translated with AI, edited by Asha Rahman</p>', html)
        self.assertIn('id="reading-text" lang="en" data-parallel', html)
        self.assertIn('<p class="parallel-label" data-parallel-head>Bengali · Original</p><p class="parallel-label" data-parallel-head>English · Translated with AI, edited by Asha Rahman</p>', html)
        bn, en = self.bn_rows[0], self.en_rows[0]
        self.assertIn(f'<div class="parallel-cell" lang="bn" data-companion hidden><p data-companion-anchor="{bn.anchor_id}">{escape(bn.text)}</p></div>'
                      f'<div class="parallel-cell" lang="en"><p id="anchor-{en.anchor_id}" data-anchor="{en.anchor_id}">{escape(en.text)}</p></div>', html)

    def test_no_toggle_without_a_translation(self):
        html = self.read()
        self.assertNotIn('parallel-toggle', html)
        self.assertNotIn('data-parallel', html)
        self.assertIn(f'<p id="anchor-{self.bn_rows[0].anchor_id}" data-anchor="{self.bn_rows[0].anchor_id}">', html)

    def test_no_toggle_when_the_service_finds_no_aligned_readable_pair(self):
        self.translate()
        with patch.object(services, 'parallel_companion', return_value=None):
            self.assertNotIn('parallel-toggle', self.read())

    def test_no_toggle_when_the_shown_document_differs_from_the_companion_structure(self):
        self.translate()
        real = services.get_reader_document
        def with_note(*args, **kwargs):
            document = real(*args, **kwargs)
            document['paragraphs'][1]['kind'] = 'note'
            return document
        with patch.object(services, 'get_reader_document', with_note):
            self.assertNotIn('parallel-toggle', self.read())

    def test_footnotes_render_in_both_columns(self):
        self.translate()
        real_document, real_companion = services.get_reader_document, services.parallel_companion
        def document(*args, **kwargs):
            value = real_document(*args, **kwargs); value['paragraphs'][2]['kind'] = 'note'; return value
        def companion(*args, **kwargs):
            value = real_companion(*args, **kwargs); value['paragraphs'][2]['kind'] = 'note'; return value
        with patch.object(services, 'get_reader_document', document), patch.object(services, 'parallel_companion', companion):
            html = self.read()
        bn, en = self.bn_rows[2], self.en_rows[2]
        self.assertIn(f'<p id="anchor-{bn.anchor_id}" data-anchor="{bn.anchor_id}" class="footnote" role="note">', html)
        self.assertIn(f'<p data-companion-anchor="{en.anchor_id}" class="footnote" role="note">', html)

    def test_anonymous_preview_has_no_toggle(self):
        self.translate()
        self.client.logout()
        html = self.read()
        self.assertNotIn('parallel-toggle', html)

    @override_settings(FREE_ACCESS_ENABLED=False)
    def test_after_the_free_rollout_the_toggle_needs_a_pass(self):
        self.translate()
        self.assertNotIn('parallel-toggle', self.read())
        now = timezone.now()
        Entitlement.objects.create(grant_key=f'pass:{uuid.uuid4()}', user=self.member, source='subscription_invoice', scope='platform',
                                   formats=['reader', 'audio'], valid_from=now - timedelta(minutes=1), valid_until=now + timedelta(days=30))
        self.assertIn('id="parallel-toggle"', self.read())
