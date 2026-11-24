"""Video page boot for private R2 films: provider, hash, captions, and no Stream host."""
import uuid
from datetime import timedelta
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from library import test_media_providers as fixtures
from library.models import Asset, Unit, Rights


@override_settings(VIDEO_PROVIDER='r2')
class VideoFilmBootTests(TestCase):
    def setUp(self):
        fixtures.MeasuredAudioTests.setUp(self)
        self.revision.access_policy['video'] = 'free'
        self.revision.save()
        self.unit.duration_ms = 6000
        self.unit.save()
        self.second = Unit.objects.create(revision=self.revision, title='Original fixture chapter 2', ordinal=2, duration_ms=6000)
        # The film's own length differs from the unit's: it carries its own end card.
        self.film = Asset.objects.create(revision=self.revision, unit=self.unit, kind='video', provider='r2', state='ready', storage_key=f'revisions/{self.revision.id}/{uuid.uuid4().hex}', sha256='b'*64, bytes=100, content_type='video/mp4', duration_ms=9000)
        self.film2 = Asset.objects.create(revision=self.revision, unit=self.second, kind='video', provider='r2', state='ready', storage_key=f'revisions/{self.revision.id}/{uuid.uuid4().hex}', sha256='c'*64, bytes=100, content_type='video/mp4', duration_ms=6000)
        self.captions = Asset.objects.create(revision=self.revision, unit=self.unit, kind='video_captions', provider='r2', state='ready', storage_key=f'revisions/{self.revision.id}/{uuid.uuid4().hex}', sha256='d'*64, bytes=10, content_type='text/vtt')
        self.third = Unit.objects.create(revision=self.revision, title='Original fixture chapter 3', ordinal=3, duration_ms=6000)
        self.film3 = Asset.objects.create(revision=self.revision, unit=self.third, kind='video', provider='r2', state='ready', storage_key=f'revisions/{self.revision.id}/{uuid.uuid4().hex}', sha256='e'*64, bytes=100, content_type='video/mp4', duration_ms=6000)
        Asset.objects.create(revision=self.revision, unit=self.third, kind='video_captions', provider='r2', state='processing', storage_key=f'revisions/{self.revision.id}/{uuid.uuid4().hex}', sha256='f'*64, bytes=10, content_type='text/vtt')
        Rights.objects.create(revision=self.revision, format='video', action='read', territories=['IN'], starts_at=timezone.now()-timedelta(days=1), ends_at=timezone.now()+timedelta(days=1), approved=True, test_only=True, evidence='Synthetic UI fixture only')
        self.revision.state = 'live'; self.revision.published_at = timezone.now(); self.revision.save()
        self.revision.edition.live_revision = self.revision; self.revision.edition.save()
        self.path = f'/en/watch/{self.revision.edition_id}/'
        override = override_settings(FEATURES={**settings.FEATURES, 'video': True})
        override.enable(); self.addCleanup(override.disable)
        self.client.post('/en/sign-in/', {'email': self.user.email, 'password': 'Test-Only-Password-47', 'password_purpose_consent': 'on', 'password_purpose_version': 'password-account-v1'})

    def boot(self, **query):
        return self.client.get(self.path, query).context['bootstrap']

    def test_r2_film_listed_when_duration_differs_from_unit(self):
        boot = self.boot()
        self.assertTrue(boot['enabled'])
        self.assertIn(str(self.film.id), [c['asset_id'] for c in boot['chapters']])
        self.assertEqual(boot['chapters'][0]['duration_ms'], 9000)

    def test_boot_chapter_has_provider_sha_and_captions_url(self):
        chapters = {c['asset_id']: c for c in self.boot()['chapters']}
        first = chapters[str(self.film.id)]
        self.assertEqual(first['provider'], 'r2')
        self.assertEqual(first['sha256'], 'b'*64)
        self.assertEqual(first['captions_url'], f'/api/v1/content/video-captions/{self.film.id}')
        self.assertEqual(set(first), {'asset_id', 'unit_id', 'duration_ms', 'title', 'provider', 'sha256', 'captions_url'})
        self.assertIsNone(chapters[str(self.film2.id)]['captions_url'])

    def test_unready_captions_give_no_url(self):
        chapters = {c['asset_id']: c for c in self.boot()['chapters']}
        self.assertIsNone(chapters[str(self.film3.id)]['captions_url'])

    @override_settings(STREAM_CUSTOMER_HOST='customer-fixture.cloudflarestream.com')
    def test_no_stream_host_in_boot_for_r2(self):
        from unittest import mock
        with mock.patch('library.stream.customer_host', side_effect=AssertionError('Stream host read for r2')):
            boot = self.boot()
        self.assertTrue(boot['enabled'])
        self.assertNotIn('stream_customer_host', boot)

    @override_settings(VIDEO_PROVIDER='stream', STREAM_CUSTOMER_HOST='customer-fixture.cloudflarestream.com')
    def test_r2_only_rows_are_inert_when_stream_is_chosen(self):
        self.assertFalse(self.boot()['enabled'])  # only r2 rows exist
