"""Representative catalog query budget and rights-before-limit acceptance."""
import re
import uuid
from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.api import DomainError
from .catalog_query import catalog_page, catalog_queryset, card_from_edition
from .models import Asset, Edition, Revision, Rights, Unit, Work

# Any statement reading the edition table, as FROM or as a JOIN ("maison_edition_revision" does not match).
EDITION_READ = re.compile(r'(?:FROM|JOIN) "maison_edition"')
from .search import refresh_revision_search
from .validation import validate_schema


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=False, PUBLIC_BASE_URL='https://example.test')
class CatalogQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.expiry = timezone.now()+timedelta(days=2)
        cls.valid = []
        # More rows than a page. Ineligible titles sort BEFORE eligible ones, so
        # post-LIMIT rights filtering would return the wrong page or lose titles.
        for n in range(100):
            edition, revision = cls.make_edition(f'Garden journey {n:03d}')
            cls.valid.append(edition.pk)
        cls.make_edition('AAA denied rights', approved=False)
        cls.make_edition('AAA expired', ends_at=timezone.now()-timedelta(seconds=1))
        cls.make_edition('AAA wrong region', territories=['GB'])
        cls.make_edition('AAA forbidden policy', policy='deny')
        cls.make_edition('AAA missing asset', asset=False)
        cls.make_edition('AAA draft only', live=False)
        cls.make_edition('AAA test rights', test_only=True)
        cls.make_edition('AAA malformed rights', territories=['IN', 'invalid'])
        cls.make_edition('AAA nonarray rights', territories={'IN': True})

    @classmethod
    def make_edition(cls, title, *, approved=True, ends_at=None, territories=None, policy='free', asset=True, live=True, test_only=False):
        key = uuid.uuid4().hex
        work=Work.objects.create(slug='catalog-'+key, title=title, house='golpo', creators=['A writer'])
        edition=Edition.objects.create(work=work, slug='catalog-'+key, locale='en')
        revision=Revision.objects.create(edition=edition, title=title, access_policy={'reader':policy})
        Unit.objects.create(revision=revision, ordinal=1, title='Chapter', duration_ms=600000)
        if asset:
            Asset.objects.create(revision=revision, kind='reader_package', state='ready', storage_key=f'revisions/{revision.pk}/{uuid.uuid4()}',
                                 sha256='0'*64, bytes=20, content_type='application/json')
        Rights.objects.create(revision=revision, format='reader', action='read', territories=['IN'] if territories is None else territories,
                              starts_at=timezone.now()-timedelta(days=2), ends_at=ends_at or cls.expiry,
                              approved=approved, test_only=test_only)
        if live:
            revision.state='live'; revision.save(); edition.live_revision=revision; edition.save()
        refresh_revision_search(revision)
        return edition, revision

    def request(self, **params):
        request=RequestFactory().get('/api/v1/search', params)
        request.user=AnonymousUser(); request.territory='IN'
        return request

    def test_page_budget_limits_source_before_serializing_and_has_no_n_plus_one(self):
        with CaptureQueriesContext(connection) as measured:
            result, ttl=catalog_page(self.request(limit=20), 'en', 'IN')
        self.assertEqual(len(result['items']),20)
        self.assertTrue(result['has_more'])
        self.assertTrue(all(card['title'].startswith('Garden') for card in result['items']))
        self.assertGreater(ttl,0); self.assertLessEqual(ttl,30)
        self.assertLessEqual(len(measured),8, [q['sql'] for q in measured])
        outer=[q['sql'] for q in measured if EDITION_READ.search(q['sql'])]
        self.assertEqual(len(outer),1)
        self.assertIn('LIMIT 21',outer[0])
        self.assertNotIn('OFFSET',outer[0])
        for card in result['items']: validate_schema(card,'CatalogCard')

    def test_signed_keyset_visits_all_eligible_rows_without_drafts_or_duplicates(self):
        seen=[];cursor=None
        while True:
            params={'limit':20}
            if cursor:params['cursor']=cursor
            result,_=catalog_page(self.request(**params),'en','IN')
            seen.extend(card['edition_id'] for card in result['items'])
            if not result['has_more']:break
            cursor=result['next_cursor']
        self.assertEqual(len(seen),100); self.assertEqual(len(set(seen)),100)
        self.assertEqual(set(seen),{str(pk) for pk in self.valid})
        first,_=catalog_page(self.request(limit=20),'en','IN')
        with self.assertRaises(DomainError):
            catalog_page(self.request(limit=20,house='classics',cursor=first['next_cursor']),'en','IN',house='classics')

    def test_search_score_cursor_is_bounded_and_preserves_tie_order(self):
        with CaptureQueriesContext(connection) as measured:
            first,_=catalog_page(self.request(limit=20,q='garden'),'en','IN',query='garden')
        second,_=catalog_page(self.request(limit=20,q='garden',cursor=first['next_cursor']),'en','IN',query='garden')
        self.assertEqual(len(first['items']),20);self.assertEqual(len(second['items']),20)
        self.assertFalse({r['edition_id'] for r in first['items']}&{r['edition_id'] for r in second['items']})
        self.assertLessEqual(len(measured),8)
        edition_reads=[q['sql'] for q in measured if EDITION_READ.search(q['sql'])]  # FROM or JOIN: every one page-bounded
        self.assertTrue(edition_reads)
        self.assertTrue(all('LIMIT 21' in sql for sql in edition_reads), edition_reads)

    def test_access_duration_filters_and_territory_are_applied_in_sql(self):
        self.assertEqual(catalog_queryset('en','IN',duration_min='11').count(),0)
        self.assertEqual(catalog_queryset('en','IN',duration_min='10',duration_max='10',access='free').count(),100)
        self.assertEqual(catalog_queryset('en','IN',access='paid').count(),0)
        self.assertEqual(catalog_queryset('en','AE').count(),0)
        for filters in ({'recency_days':'9'*100},{'duration_min':'11','duration_max':'10'}):
            with self.assertRaises(DomainError): catalog_queryset(**filters)

    def test_cards_and_deadline_serialization_do_not_fetch_after_prefetch(self):
        rows=list(catalog_queryset('en','IN')[:3])
        with self.assertNumQueries(0):
            cards=[card_from_edition(row) for row in rows]
        self.assertEqual(len(cards),3)

    def test_whitespace_query_uses_normal_catalog_cursor(self):
        result,_=catalog_page(self.request(limit=20,q='   '),'en','IN',query='   ')
        self.assertEqual(len(result['items']),20)
        second,_=catalog_page(self.request(limit=20,q='   ',cursor=result['next_cursor']),'en','IN',query='   ')
        self.assertEqual(len(second['items']),20)

    def test_search_response_honors_strict_contract_and_50_item_cap(self):
        result,_=catalog_page(self.request(limit=20,q='garden'),'en','IN',query='garden')
        validate_schema(result,'SearchResults')
        self.assertEqual(result['match_mode'],'prefix')
        with self.assertRaises(DomainError):
            catalog_page(self.request(limit=51,q='garden'),'en','IN',query='garden')

    def test_video_candidates_require_configured_provider_in_both_listing_and_format_filter(self):
        editions={}
        for provider in ('r2','stream'):
            key=uuid.uuid4().hex
            work=Work.objects.create(slug='provider-'+key,title='Provider video '+provider)
            edition=Edition.objects.create(work=work,slug=work.slug,locale='en')
            revision=Revision.objects.create(edition=edition,title=work.title,access_policy={'video':'free'})
            unit=Unit.objects.create(revision=revision,ordinal=1,title='Video unit',duration_ms=1000)
            Asset.objects.create(revision=revision,unit=unit,kind='video',state='ready',provider=provider,duration_ms=1000,
                                 storage_key=key if provider=='stream' else f'revisions/{revision.pk}/{key}',
                                 sha256='0'*64,bytes=0,content_type='application/vnd.apple.mpegurl' if provider=='stream' else 'video/mp4')
            Rights.objects.create(revision=revision,format='video',action='read',territories=['IN'],
                                  starts_at=timezone.now()-timedelta(days=1),ends_at=self.expiry,approved=True,test_only=False)
            revision.state='live';revision.save();edition.live_revision=revision;edition.save()
            editions[provider]=edition
        from .services import available_formats
        for configured,other in (('stream','r2'),('r2','stream')):
            with self.subTest(configured=configured),override_settings(VIDEO_PROVIDER=configured):
                video=list(catalog_queryset('en','IN',format='video'))
                self.assertEqual([row.pk for row in video],[editions[configured].pk])
                self.assertEqual(card_from_edition(video[0])['formats'],['video'])
                all_ids=set(catalog_queryset('en','IN').values_list('id',flat=True))
                self.assertIn(editions[configured].pk,all_ids)
                self.assertNotIn(editions[other].pk,all_ids)
                self.assertEqual(available_formats(Revision.objects.get(pk=editions[other].live_revision_id),'IN'),[])
                self.assertEqual(available_formats(Revision.objects.get(pk=editions[configured].live_revision_id),'IN'),['video'])
