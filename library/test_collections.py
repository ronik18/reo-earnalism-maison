"""PostgreSQL-backed Series/collection persistence and access regressions."""
import io
import tempfile
import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError,transaction
from django.test import TestCase,RequestFactory,override_settings
from django.utils import timezone
from core.api import DomainError
from library.collection_models import CatalogCollection,CatalogItem
from library.collections import collection_detail,list_collections,get_collection,series_member_state
from library.models import Work,Edition,Revision,Unit,Asset,Rights
from reader.models import Progress


class CollectionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media=tempfile.TemporaryDirectory(prefix='maison-series-test-')
        cls.profile=override_settings(MEDIA_ROOT=cls.media.name,MAISON_LOCAL_FIXTURES=True)
        cls.profile.enable();super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass();cls.profile.disable();cls.media.cleanup()

    @classmethod
    def setUpTestData(cls):
        call_command('seed_local_pilot',stdout=io.StringIO())
        cls.series=CatalogCollection.objects.create(slug='observations',title_en='Observations',title_bn='পর্যবেক্ষণ',kind='series',house='series',published=True)
        cls.en=Edition.objects.get(pk='20000000-0000-4000-8000-000000000001')
        cls.bn=Edition.objects.get(pk='20000000-0000-4000-8000-000000000002')
        CatalogItem.objects.create(collection=cls.series,edition=cls.en,sort_order=2)
        CatalogItem.objects.create(collection=cls.series,edition=cls.bn,sort_order=1)
        cls.user=get_user_model().objects.create_user('series-a@example.test','Series-test-password47',is_verified=True)
        cls.other=get_user_model().objects.create_user('series-b@example.test','Series-test-password47',is_verified=True)

    def request(self,**query):
        request=RequestFactory().get('/api/v1/catalog/collections',query);request.territory='IN';request.user=self.user
        return request

    def test_slug_uuid_order_locale_and_missing_states(self):
        self.assertEqual(get_collection('observations',series_only=True).id,self.series.id)
        self.assertEqual(get_collection(self.series.id).slug,'observations')
        data=collection_detail(self.request(),'observations','en','IN')
        self.assertEqual([x['edition_id'] for x in data['items']],[str(self.en.id)])
        bn=collection_detail(self.request(),self.series.id,'bn','IN')
        self.assertEqual(bn['title'],'পর্যবেক্ষণ');self.assertEqual(bn['items'][0]['edition_id'],str(self.bn.id))
        empty=collection_detail(self.request(),self.series.id,'en','US')
        self.assertEqual(empty['items'],[])
        self.series.published=False;self.series.save()
        for identifier in ('observations',self.series.id,'missing'):
            with self.assertRaises(DomainError) as error:get_collection(identifier)
            self.assertEqual(error.exception.status,404)

    def test_real_publication_and_territory_checks_not_membership_or_file_presence(self):
        revision=self.en.live_revision
        Rights.objects.filter(revision=revision,format='reader',action='read').update(approved=False)
        data=collection_detail(self.request(),self.series.id,'en','IN')
        self.assertEqual(data['items'],[])
        self.assertEqual(list_collections(self.request(),'en','IN',kind='series')['items'][0]['kind'],'series')
        with self.assertRaises(DomainError):collection_detail(self.request(),self.series.id,'en','ZZ')

    def test_item_changes_increment_collection_version_and_constraints_are_real(self):
        self.series.refresh_from_db();version=self.series.version
        CatalogItem.objects.filter(collection=self.series,edition=self.en).update(sort_order=3)
        self.series.refresh_from_db();self.assertGreater(self.series.version,version)
        version=self.series.version
        CatalogItem.objects.filter(collection=self.series,edition=self.bn).delete()
        self.series.refresh_from_db();self.assertGreater(self.series.version,version)
        with self.assertRaises(IntegrityError),transaction.atomic():CatalogItem.objects.create(collection=self.series,edition=self.en,sort_order=4)
        with self.assertRaises(IntegrityError),transaction.atomic():CatalogItem.objects.create(collection=self.series,edition=self.bn,sort_order=-1)

    def test_private_resume_is_account_revision_and_current_format_scoped(self):
        location={'format':'reader','unit_id':str(self.en.live_revision.units.first().id),'anchor_id':str(self.en.live_revision.units.first().paragraphs.first().anchor_id),'offset_chars':0}
        Progress.objects.create(user=self.other,edition=self.en,revision=self.en.live_revision,format='reader',location=location,last_operation_id=uuid.uuid4())
        state=series_member_state(self.user,self.series,'en','IN')
        self.assertEqual(state['items'][0]['progress'],[])
        Progress.objects.create(user=self.user,edition=self.en,revision=self.en.live_revision,format='reader',location=location,last_operation_id=uuid.uuid4())
        state=series_member_state(self.user,self.series,'en','IN')
        self.assertEqual(state['items'][0]['progress'][0]['location'],location)
        public=collection_detail(self.request(),self.series.id,'en','IN')
        self.assertNotIn('progress',public);self.assertNotIn('progress',public['items'][0])

    def test_more_than_one_hundred_items_are_paged_without_truncation(self):
        now=timezone.now()
        work=Work.objects.create(slug='series-many',title='Many episodes')
        for index in range(102):
            edition=Edition.objects.create(work=work,slug=f'series-episode-{index}',locale='en')
            revision=Revision.objects.create(edition=edition,title=f'Episode {index}',access_policy={'reader':'free'},download_policy={'reader':False},content_sha256='0'*64)
            unit=Unit.objects.create(revision=revision,title='One',ordinal=1)
            Asset.objects.create(revision=revision,unit=unit,kind='reader_package',state='ready',storage_key=f'revisions/{revision.id}/{uuid.uuid4()}.json',sha256='0'*64,bytes=1,content_type='application/json')
            Rights.objects.create(revision=revision,format='reader',action='read',territories=['IN'],starts_at=now-timedelta(days=1),ends_at=now+timedelta(days=1),approved=True,test_only=True,evidence='Synthetic collection pagination test only')
            revision.state='live';revision.published_at=now;revision.save();edition.live_revision=revision;edition.save()
            CatalogItem.objects.create(collection=self.series,edition=edition,sort_order=index+10)
        self.series.refresh_from_db()
        first=collection_detail(self.request(limit=100),self.series.id,'en','IN')
        self.assertEqual(len(first['items']),100);self.assertIsNotNone(first['next_cursor'])
        second=collection_detail(self.request(limit=100,cursor=first['next_cursor']),self.series.id,'en','IN')
        self.assertEqual(len(second['items']),3);self.assertIsNone(second['next_cursor'])
        self.assertEqual(len({x['edition_id'] for x in first['items']+second['items']}),103)
        with self.assertRaises(DomainError):collection_detail(self.request(limit=99,cursor=first['next_cursor']),self.series.id,'en','IN')

    def test_bounded_scan_can_traverse_more_than_five_hundred_unavailable_items(self):
        series=CatalogCollection.objects.create(slug='withdrawn-prefix',title_en='Prefix',title_bn='আগের অংশ',kind='series',house='series',published=True)
        work=Work.objects.create(slug='unavailable-many',title='Unavailable test episodes')
        editions=Edition.objects.bulk_create([Edition(work=work,slug=f'unavailable-{index}',locale='en') for index in range(501)])
        # No live revision/rights/assets: every prefix item must remain nondeliverable.
        CatalogItem.objects.bulk_create([CatalogItem(collection=series,edition=edition,sort_order=index) for index,edition in enumerate(editions)])
        CatalogItem.objects.create(collection=series,edition=self.en,sort_order=501)
        first=collection_detail(self.request(limit=100),series.id,'en','IN')
        self.assertEqual(first['items'],[]);self.assertIsNotNone(first['next_cursor'])
        second=collection_detail(self.request(limit=100,cursor=first['next_cursor']),series.id,'en','IN')
        self.assertEqual([x['edition_id'] for x in second['items']],[str(self.en.id)])
        self.assertIsNone(second['next_cursor'])

    def test_work_related_collections_use_published_eligible_memberships_without_global_scan(self):
        import json
        from unittest.mock import patch
        from library.views import work
        from library.services import catalog_card
        hidden=CatalogCollection.objects.create(slug='hidden-series',title_en='Hidden',title_bn='অপ্রকাশিত',kind='series',published=False)
        CatalogItem.objects.create(collection=hidden,edition=self.en,sort_order=0)
        with patch('library.services.catalog_cards',side_effect=AssertionError('Whole-catalog scan forbidden for a single card/work')):
            self.assertEqual(catalog_card(self.en,territory='IN')['edition_id'],str(self.en.id))
            response=work(self.request(locale='en'),self.en.work_id)
        self.assertEqual(response.status_code,200)
        data=json.loads(response.content)
        ids={row['collection_id'] for row in data['related_collections']}
        self.assertIn(str(self.series.id),ids)
        self.assertNotIn(str(hidden.id),ids)
        self.assertLessEqual(len(data['related_collections']),20)
        self.series.published=False;self.series.save()
        self.assertNotIn(str(self.series.id),{row['collection_id'] for row in json.loads(work(self.request(locale='en'),self.en.work_id).content)['related_collections']})
