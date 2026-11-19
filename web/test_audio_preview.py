"""Guest sample UI uses the real bounded-preview boundary, never chapter assets."""
from django.conf import settings
from django.test import TestCase, override_settings
from library import test_audio_preview as preview_fixtures


class PublicAudioPreviewScreensTests(TestCase):
    def setUp(self):
        preview_fixtures.PublicAudioPreviewTests.setUp(self)

    def test_guest_title_and_home_link_to_the_separate_sample(self):
        path = f'/en/listen/{self.revision.edition_id}/preview/'
        self.assertContains(self.client.get(f'/en/titles/{self.revision.edition_id}/'), path)
        self.assertContains(self.client.get('/en/'), path)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        boot = response.context['bootstrap']
        self.assertFalse(boot['authenticated'])
        self.assertFalse(boot['reader_available'])
        self.assertEqual(boot['preview']['asset_id'], str(self.clip.id))
        self.assertEqual(boot['preview']['unit_id'], str(self.unit.id))
        self.assertEqual(boot['chapters'][0]['asset_id'], str(self.clip.id))
        self.assertEqual(boot['preview']['duration_ms'], 1500)
        self.assertNotContains(response, str(self.asset.id))
        self.assertNotContains(response, self.asset.storage_key)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.get(f'/en/listen/{self.revision.edition_id}/').status_code, 302)

    @override_settings(FREE_ACCESS_ENABLED=True)
    def test_free_member_sample_can_continue_without_financial_entitlement(self):
        from django.contrib.auth import get_user_model
        from billing.models import Entitlement
        user=get_user_model().objects.create_user('free-sample-member@example.test','Local-Free-Sample-2026',is_verified=True)
        login=self.client.post('/en/sign-in/', {'email':user.email,'password':'Local-Free-Sample-2026','return_to':'/en/'})
        self.assertEqual(login.status_code,302)
        self.assertFalse(Entitlement.objects.filter(user=user).exists())
        response=self.client.get(f'/en/listen/{self.revision.edition_id}/preview/')
        self.assertEqual(response.status_code,200)
        boot=response.context['bootstrap']
        self.assertTrue(boot['free_access']);self.assertTrue(boot['authenticated'])
        self.assertEqual(boot['full_player_url'],f'/en/listen/{self.revision.edition_id}/?unit_id={self.unit.id}')
        self.assertNotIn(str(self.asset.id),response.content.decode())
        self.assertNotIn(self.asset.storage_key,response.content.decode())

    def test_unprepared_clip_has_no_sample_control_or_full_asset_fallback(self):
        self.revision.validation_evidence['audio_preview']['sha256'] = '0'*64
        self.revision.save()
        path = f'/bn/listen/{self.revision.edition_id}/preview/'
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertNotContains(self.client.get(f'/bn/titles/{self.revision.edition_id}/'), path)

    def test_disabled_audio_does_not_expose_a_sample_route(self):
        with override_settings(FEATURES={**settings.FEATURES, 'audio': False}):
            path = f'/en/listen/{self.revision.edition_id}/preview/'
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertNotContains(self.client.get(f'/en/titles/{self.revision.edition_id}/'), path)
