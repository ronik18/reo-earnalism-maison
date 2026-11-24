"""Revenue plan Step 3.1: the Pass split needs no new access code, only configuration.

Reading stays free; audio is 'paid'. While the free rollout flag is on, everything live is free.
With the flag off, a platform-scope Pass entitlement (what a Pass subscription grants) opens the
paid format, and its end date bounds access.
"""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from billing.models import Entitlement
from core.api import DomainError
from reader.test_journey import make_book
from library.models import Rights
from library.services import access_ends, authorize_revision


class PassSplitTests(TestCase):
    def setUp(self):
        self.edition, self.revision = make_book(units=1, durations=[60_000], policy={'reader': 'free', 'audio': 'paid'})
        self.member = get_user_model().objects.create_user('pass@example.test', 'Pass-Split-Passphrase-26', is_verified=True)

    def pass_entitlement(self, days=30):
        now = timezone.now()
        return Entitlement.objects.create(grant_key=f'pass:{uuid.uuid4()}', user=self.member, source='subscription_invoice',
                                          scope='platform', formats=['reader', 'audio'], valid_from=now - timedelta(minutes=1),
                                          valid_until=now + timedelta(days=days))

    @override_settings(FREE_ACCESS_ENABLED=True)
    def test_free_rollout_keeps_everything_free(self):
        authorize_revision(self.member, self.revision, 'reader')
        authorize_revision(self.member, self.revision, 'audio')

    @override_settings(FREE_ACCESS_ENABLED=False)
    def test_after_rollout_reading_stays_free_and_audio_needs_the_pass(self):
        authorize_revision(self.member, self.revision, 'reader')
        with self.assertRaises(DomainError) as caught:
            authorize_revision(self.member, self.revision, 'audio')
        self.assertEqual(caught.exception.code, 'entitlement_required')
        grant = self.pass_entitlement()
        authorize_revision(self.member, self.revision, 'audio')
        self.assertLessEqual(access_ends(self.member, self.revision, 'audio'), grant.valid_until)
        grant.revoked_at = timezone.now(); grant.status = 'revoked'; grant.save()
        with self.assertRaises(DomainError):
            authorize_revision(self.member, self.revision, 'audio')

    @override_settings(FREE_ACCESS_ENABLED=False)
    def test_the_pass_never_overrides_rights(self):
        self.pass_entitlement()
        Rights.objects.filter(revision=self.revision, format='audio').delete()
        with self.assertRaises(DomainError) as caught:
            authorize_revision(self.member, self.revision, 'audio')
        self.assertEqual(caught.exception.code, 'rights_unavailable')
