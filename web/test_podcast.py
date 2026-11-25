import xml.etree.ElementTree as ET
from django.conf import settings
from django.test import TestCase
from library.store_export import audio_cleared_everywhere
from library import test_audio_preview as fixtures

NS = {'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'}


class PodcastFeedTests(TestCase):
    def setUp(self):
        fixtures.PublicAudioPreviewTests.setUp(self)
        self.clear()

    def clear(self, **changes):
        clearance = {'status': 'pass', 'sha256': self.revision.content_sha256, 'formats': ['reader', 'audio'],
                     'asset_sha256': {str(a.id): a.sha256 for a in self.revision.assets.filter(state='ready')},
                     'territories': list(settings.MAISON_PUBLICATION_TERRITORIES), 'evidence_ref': 'legal-ref-1'}
        clearance.update(changes)
        self.revision.validation_evidence['publication_clearance'] = clearance
        type(self.revision).objects.filter(pk=self.revision.pk).update(validation_evidence=self.revision.validation_evidence)

    def feed(self, locale='en'):
        return self.client.get(f'/podcast/{locale}.xml')

    def items(self, locale='en'):
        return ET.fromstring(self.feed(locale).content).findall('./channel/item')

    def test_feed_is_valid_xml_with_itunes_namespace(self):
        response = self.feed()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/rss+xml; charset=utf-8')
        # The view sets the same header as web.views.offline_shell; the stack's public-cache finalizer
        # (operations.cache, PUBLIC_PATH) downgrades unregistered paths to private, no-store.
        from django.test import RequestFactory
        from web import podcast
        self.assertEqual(podcast.feed(RequestFactory().get('/podcast/en.xml'), 'en')['Cache-Control'], 'public,max-age=0,must-revalidate')
        self.assertIn('no-store', response['Cache-Control'])
        root = ET.fromstring(response.content)
        channel = root.find('channel')
        self.assertEqual(channel.findtext('title'), 'Earnalism')
        self.assertEqual(channel.findtext('language'), 'en')
        self.assertEqual(channel.findtext('itunes:author', namespaces=NS), 'Earnalism')
        self.assertEqual(channel.findtext('itunes:explicit', namespaces=NS), 'false')
        self.assertEqual(channel.find('itunes:category', NS).get('text'), 'Arts')
        item = self.items()[0]
        self.assertEqual(item.findtext('title'), self.revision.title)
        self.assertEqual(item.find('guid').get('isPermaLink'), 'false')
        self.assertEqual(item.findtext('guid'), str(self.revision.edition_id))
        self.assertNotIn(self.asset.storage_key, response.content.decode())
        self.assertEqual(self.feed('fr').status_code, 404)

    def test_items_link_with_podcast_utm(self):
        link = self.items()[0].findtext('link')
        self.assertIn(f'/en/titles/{self.revision.edition.slug}/', link)
        self.assertIn('utm_source=podcast', link)
        self.assertIn('utm_medium=feed', link)
        self.assertIn(f'utm_campaign={self.revision.edition.slug}', link)

    def test_feed_lists_only_cleared_free_audio(self):
        self.assertEqual(len(self.items()), 1)
        self.assertEqual(self.items('bn'), [])
        self.clear(territories=list(settings.MAISON_PUBLICATION_TERRITORIES)[1:])
        self.assertEqual(self.items(), [])
        self.clear(formats=['reader'])
        self.assertEqual(self.items(), [])
        self.clear(sha256='0' * 64)
        self.assertEqual(self.items(), [])
        self.clear()
        self.assertEqual(len(self.items()), 1)
        type(self.revision.edition).objects.filter(pk=self.revision.edition_id).update(live_revision=None)
        self.assertEqual(self.items(), [])

    def test_audio_cleared_everywhere_requires_pass_and_exact_assets(self):
        self.assertTrue(audio_cleared_everywhere(self.revision))
        self.clear(status='fail')
        self.assertFalse(audio_cleared_everywhere(self.revision))
        self.clear(evidence_ref=' ')
        self.assertFalse(audio_cleared_everywhere(self.revision))
        self.clear(asset_sha256={})
        self.assertFalse(audio_cleared_everywhere(self.revision))

    def test_bn_edition_listed_only_in_bn_feed(self):
        type(self.revision.edition).objects.filter(pk=self.revision.edition_id).update(locale='bn')
        self.assertEqual(len(self.items('bn')), 1)
        self.assertEqual(self.items('en'), [])
        self.assertEqual(ET.fromstring(self.feed('bn').content).findtext('./channel/language'), 'bn')

    def _go_live_with(self, policy):
        from django.utils import timezone
        from library import services as svc
        from library.models import Revision
        draft = svc.clone_revision(self.revision.id)
        draft.access_policy = policy
        draft.save()
        Revision.objects.filter(pk=self.revision.pk).update(state='retired')
        Revision.objects.filter(pk=draft.pk).update(state='live', published_at=timezone.now())
        type(self.revision.edition).objects.filter(pk=self.revision.edition_id).update(live_revision=draft.pk)

    def test_paid_and_denied_audio_are_excluded(self):
        for audio in ('paid', 'deny'):
            self._go_live_with({'reader': 'free', 'audio': audio})
            self.assertEqual(self.items(), [], audio)

    def test_unpublished_edition_is_excluded(self):
        from library.models import Revision
        Revision.objects.filter(pk=self.revision.pk).update(published_at=None)
        self.assertEqual(self.items(), [])

    def drop_clip(self):
        self.revision.validation_evidence['audio_preview']['sha256'] = '0' * 64
        type(self.revision).objects.filter(pk=self.revision.pk).update(validation_evidence=self.revision.validation_evidence)

    def test_item_with_prepared_preview_has_enclosure_and_duration(self):
        item = self.items()[0]
        enclosure = item.find('enclosure')
        self.assertEqual(enclosure.get('url'), settings.PUBLIC_BASE_URL.rstrip('/') + f'/api/v1/content/audio-previews/{self.clip.id}')
        self.assertEqual(enclosure.get('length'), str(self.clip.bytes))
        self.assertEqual(enclosure.get('type'), 'audio/mpeg')
        self.assertEqual(item.findtext('itunes:duration', namespaces=NS), '2')
        self.assertEqual(item.findtext('itunes:episodeType', namespaces=NS), 'full')
        self.assertIn('Preview \u2014 listen to the full story on Earnalism.', item.findtext('description'))
        self.assertIn('utm_source=podcast', item.findtext('description'))

    def test_item_without_prepared_clip_has_no_enclosure(self):
        self.drop_clip()
        item = self.items()[0]
        self.assertIsNone(item.find('enclosure'))
        self.assertIsNone(item.find('itunes:duration', NS))
        self.assertNotIn('Preview', item.findtext('description'))
        self.assertIn('utm_source=podcast', item.findtext('link'))

    def test_enclosure_never_points_at_full_audio_or_storage(self):
        content = self.feed().content.decode()
        self.assertNotIn(str(self.asset.id), content)
        self.assertNotIn(self.asset.storage_key, content)
        self.assertNotIn(self.clip.storage_key, content)
        self.assertEqual(content.count('<enclosure'), 1)
        self.assertNotIn('X-Amz', content)
