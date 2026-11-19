"""SSR search/Explore must traverse the same bounded catalog as the API."""
import io
from datetime import timedelta
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from library.models import Edition, Revision, Unit, Paragraph, Rights
from library.services import write_reader_package, revision_hash


class CatalogPaginationScreensTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings = override_settings(MEDIA_ROOT=self.media.name, MEDIA_STORAGE_BACKEND='local', LOCAL=True, MAISON_LOCAL_FIXTURES=True)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        first = Edition.objects.get(pk='20000000-0000-4000-8000-000000000001')
        second = Edition.objects.create(work=first.work, slug='river-next-local-en', locale='en')
        revision = Revision.objects.create(edition=second, title='Another river notebook', access_policy={'reader': 'free'})
        unit = Unit.objects.create(revision=revision, ordinal=1, title='Local pagination fixture')
        Paragraph.objects.create(unit=unit, ordinal=1, text='An original extra paragraph exercises local catalog pagination.')
        write_reader_package(unit)
        Rights.objects.create(revision=revision, format='reader', action='read', territories=['IN'], starts_at=timezone.now()-timedelta(days=1), ends_at=timezone.now()+timedelta(days=1), approved=True, test_only=True, evidence='Original local pagination fixture only')
        revision.content_sha256 = revision_hash(revision)
        revision.state = 'live'
        revision.published_at = timezone.now()
        revision.save()
        second.live_revision = revision
        second.save()

    def test_search_and_explore_follow_cursor_preserving_locale_and_filters(self):
        for path in ['/en/search/', '/bn/explore/']:
            with self.subTest(path=path):
                first = self.client.get(path, {'content_locale': 'en', 'house': 'golpo', 'limit': '1'},follow=True)
                self.assertEqual(first.status_code, 200)
                self.assertEqual(len(first.context['cards']), 1)
                next_url = first.context['next_page_url']
                self.assertTrue(next_url)
                query = parse_qs(urlsplit(next_url).query)
                self.assertEqual(query['limit'], ['1'])
                self.assertEqual(query['house'], ['golpo'])
                self.assertEqual(query['content_locale'], ['en'])
                self.assertTrue(query['cursor'][0])
                second = self.client.get(next_url)
                self.assertEqual(second.status_code, 200)
                self.assertEqual(len(second.context['cards']), 1)
                self.assertNotEqual(first.context['cards'][0]['edition_id'], second.context['cards'][0]['edition_id'])
                self.assertIsNone(second.context['next_page_url'])
                changed = self.client.get(path, {**{k: v[0] for k, v in query.items()}, 'house': 'classics'},follow=True)
                self.assertEqual(changed.status_code, 422)

    def test_author_control_and_search_page_limit_match_contract(self):
        response = self.client.get('/bn/search/', {'content_locale': 'en', 'author': 'Maison'}, follow=True)
        self.assertContains(response, 'name="author"')
        self.assertContains(response, 'value="Maison"')
        self.assertContains(response, 'max="3650"')
        self.assertEqual(self.client.get('/en/search/?limit=51').status_code, 422)
        self.assertEqual(self.client.get('/en/explore/?limit=51').status_code, 200)
