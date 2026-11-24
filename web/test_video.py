"""Real SSR video selection/keyset behavior, using original local fixture metadata."""
import uuid
from datetime import timedelta
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from library import test_media_providers as fixtures
from library.models import Asset, Unit, Rights

class VideoScreensTests(TestCase):
    def setUp(self):
        fixtures.MeasuredAudioTests.setUp(self)
        self.revision.access_policy['video'] = 'free'
        self.revision.save()
        self.video_assets=[]
        for i in range(3):
            unit = self.unit if i==0 else Unit.objects.create(revision=self.revision,title=f'Original fixture chapter {i+1}',ordinal=i+2,duration_ms=6000)
            self.video_assets.append(Asset.objects.create(revision=self.revision,unit=unit,kind='video',provider='stream',state='ready',storage_key=uuid.uuid4().hex,sha256='a'*64,bytes=100,content_type='video/mp4',duration_ms=6000))
        Rights.objects.create(revision=self.revision,format='video',action='read',territories=['IN'],starts_at=timezone.now()-timedelta(days=1),ends_at=timezone.now()+timedelta(days=1),approved=True,test_only=True,evidence='Synthetic UI fixture only')
        self.revision.state='live';self.revision.published_at=timezone.now();self.revision.save()
        self.revision.edition.live_revision=self.revision;self.revision.edition.save()
        self.path=f'/en/watch/{self.revision.edition_id}/'
        self.override_video=override_settings(VIDEO_PROVIDER='stream',FEATURES={**settings.FEATURES,'video':True},STREAM_CUSTOMER_HOST='customer-fixture.cloudflarestream.com')
        self.override_video.enable();self.addCleanup(self.override_video.disable)

    def login(self):
        self.client.post('/en/sign-in/',{'email':self.user.email,'password':'Test-Only-Password-47','password_purpose_consent':'on','password_purpose_version':'password-account-v1'})

    def test_guest_signin_fallback_and_disabled_video_have_no_fake_chapter(self):
        boot=self.client.get(self.path).context['bootstrap']
        self.assertFalse(boot['enabled']);self.assertIn('/en/sign-in/',boot['sign_in_url']);self.assertNotIn('chapters',boot)
        self.login()
        with override_settings(FEATURES={**settings.FEATURES,'video':False}):
            boot=self.client.get(self.path).context['bootstrap'];self.assertFalse(boot['enabled']);self.assertNotIn('chapters',boot)

    def test_video_keyset_and_selected_actual_unit_are_bound_to_this_revision(self):
        self.login()
        first=self.client.get(self.path,{'limit':1});boot=first.context['bootstrap']
        self.assertTrue(boot['enabled']);self.assertEqual(boot['stream_customer_host'],'customer-fixture.cloudflarestream.com')
        self.assertEqual(boot['chapters'][0]['unit_id'],str(self.unit.id));self.assertEqual(len(boot['chapters']),1)
        second=self.client.get(first.context['next_page_url']);self.assertEqual(len(second.context['bootstrap']['chapters']),1)
        self.assertNotEqual(boot['chapters'][0]['asset_id'],second.context['bootstrap']['chapters'][0]['asset_id'])
        selected=self.video_assets[-1]
        response=self.client.get(self.path,{'limit':1,'unit_id':str(selected.unit_id)})
        self.assertEqual(response.context['bootstrap']['start_asset_id'],str(selected.id))
        self.assertIn(str(selected.unit_id),[c['unit_id'] for c in response.context['bootstrap']['chapters']])
        self.assertEqual(self.client.get(self.path,{'limit':101}).status_code,422)
