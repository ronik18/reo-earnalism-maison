"""Sponsored tracks: always labelled on the page and the worksheet; never without a named approver."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from . import worksheet
from .models import Track
from .test_classroom import quiz_track


def printed(track_id, answers=False):
    """Every string the worksheet draws, captured at the font layer."""
    import billing.pdf_fonts as fonts
    drawn, original = [], fonts.draw_text
    def spy(pdf, text, *args, **kwargs):
        drawn.append(text)
        return original(pdf, text, *args, **kwargs)
    with mock.patch.object(fonts, 'draw_text', spy):
        assert worksheet.render(track_id, answers=answers).startswith(b'%PDF')
    return drawn


@override_settings(FREE_ACCESS_ENABLED=True)
class SponsorTests(TestCase):
    def setUp(self):
        self.approver = get_user_model().objects.create_user('approver@example.test', 'Sponsor-Passphrase-2026', is_staff=True, is_verified=True)

    def test_sponsor_label_on_page_and_worksheet(self):
        track = quiz_track('en')
        self.client.get('/en/sign-in/')
        self.client.post('/en/sign-in/', {'email': self.approver.email, 'password': 'Sponsor-Passphrase-2026', 'return_to': '/en/learn/',
                                          'password_purpose_consent': 'on', 'password_purpose_version': 'password-account-v1'})
        self.assertNotContains(self.client.get(f'/en/tracks/{track.pk}/'), '<p class="fine" lang="en">Sponsored by')
        Track.objects.filter(pk=track.pk).update(sponsor_name='Acme <Books>', sponsor_url='https://acme.example/read',
                                                 sponsor_approved_by=self.approver)
        page = self.client.get(f'/en/tracks/{track.pk}/')
        self.assertContains(page, '<p class="fine" lang="en">Sponsored by <a href="https://acme.example/read" rel="sponsored noopener">Acme &lt;Books&gt;</a></p>', html=False)
        self.assertContains(page, 'rel="sponsored noopener"')
        self.assertContains(page, 'href="https://acme.example/read"')
        self.assertContains(page, 'Acme &lt;Books&gt;')
        self.assertNotContains(page, 'target=')
        Track.objects.filter(pk=track.pk).update(sponsor_url='')
        page = self.client.get(f'/en/tracks/{track.pk}/')
        self.assertContains(page, 'Acme &lt;Books&gt;')
        self.assertNotContains(page, 'rel="sponsored noopener"')
        for answers in (False, True):
            self.assertIn('Sponsored by Acme <Books>', printed(track.pk, answers))
        bengali = quiz_track('bn')
        Track.objects.filter(pk=bengali.pk).update(sponsor_name='আলো', sponsor_approved_by=self.approver)
        self.assertIn('সৌজন্যে আলো', printed(bengali.pk))
        plain = quiz_track('en')
        self.assertFalse([t for t in printed(plain.pk) if 'Sponsored' in t])

    def test_unapproved_sponsor_rejected_by_database(self):
        track = quiz_track('en')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Track.objects.filter(pk=track.pk).update(sponsor_name='Acme')
        Track.objects.filter(pk=track.pk).update(sponsor_name='Acme', sponsor_approved_by=self.approver)
        with self.assertRaises(Exception), transaction.atomic():
            self.approver.delete()
