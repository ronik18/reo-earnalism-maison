"""Content languages are explicit filters, never inferred from UI/account locale."""
import io,json,tempfile,uuid
from datetime import timedelta
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.test import TestCase,RequestFactory,override_settings
from django.utils import timezone
from core.api import DomainError
from . import services,views
from .models import Edition,Revision,Work,Asset,Unit,Rights
from .catalog_query import catalog_page,catalog_queryset
from .collection_models import CatalogCollection,CatalogItem
from .collections import collection_detail
from .search import refresh_revision_search
from .search_models import SearchAlias
from django.contrib.auth import get_user_model

@override_settings(LOCAL=True,MAISON_LOCAL_FIXTURES=True,FREE_ACCESS_ENABLED=True)
class ContentLanguageDiscoveryTests(TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.o=override_settings(MEDIA_ROOT=self.tmp.name);self.o.enable();self.addCleanup(self.o.disable)
  call_command('seed_local_pilot',stdout=io.StringIO())
  self.en=Edition.objects.get(pk='20000000-0000-4000-8000-000000000001');self.bn=Edition.objects.get(pk='20000000-0000-4000-8000-000000000002')
  self.factory=RequestFactory()
 def request(self,path='/api/v1/catalog/editions',**params):
  r=self.factory.get(path,params);r.user=AnonymousUser();r.territory='IN';return r
 def original_edition(self,title,locale='en'):
  key=uuid.uuid4().hex;w=Work.objects.create(slug='original-mixed-'+key,title=title)
  e=Edition.objects.create(work=w,slug='original-mixed-'+key,locale=locale);r=Revision.objects.create(edition=e,title=title,access_policy={'reader':'free'})
  u=Unit.objects.create(revision=r,title='Original chapter',ordinal=1)
  Asset.objects.create(revision=r,unit=u,kind='reader_package',state='ready',storage_key=f'revisions/{r.id}/{uuid.uuid4()}.json',sha256='0'*64,bytes=1,content_type='application/json')
  Rights.objects.create(revision=r,format='reader',action='read',territories=['IN'],starts_at=timezone.now()-timedelta(days=1),ends_at=timezone.now()+timedelta(days=1),approved=True,test_only=True,evidence='Original local language fixture only')
  r.state='live';r.save();e.live_revision=r;e.save();refresh_revision_search(r);return e
 def test_default_catalog_and_work_include_both_languages_with_safe_filters(self):
  response=views.catalog(self.request());self.assertEqual(response.status_code,200)
  self.assertEqual({x['locale'] for x in json.loads(response.content)['items']},{'en','bn'})
  for locale in ['en','bn']:
   response=views.catalog(self.request(locale=locale));self.assertEqual({x['locale'] for x in json.loads(response.content)['items']},{locale})
  for locale in ['', 'all']:
   self.assertEqual({x['locale'] for x in catalog_page(self.request(locale=locale),locale,'IN')[0]['items']},{'en','bn'})
  response=views.work(self.request('/api/v1/catalog/works'),self.en.work_id);self.assertEqual(response.status_code,200)
  self.assertEqual({x['locale'] for x in json.loads(response.content)['editions']},{'en','bn'})
  self.assertEqual(catalog_page(self.request(),None,'AE')[0]['items'],[])
  request=self.request(locale='../en');self.assertEqual(views.catalog(request).status_code,422)
 def test_mixed_keyset_is_stable_and_cannot_switch_language_filters(self):
  first,_=catalog_page(self.request(limit=1),None,'IN');self.assertTrue(first['has_more'])
  earlier=self.original_edition('AAA original inserted before the cursor')
  second,_=catalog_page(self.request(limit=1,cursor=first['next_cursor']),None,'IN')
  self.assertEqual({x['edition_id'] for x in first['items']+second['items']},{str(self.en.id),str(self.bn.id)})
  with self.assertRaises(DomainError):catalog_page(self.request(limit=1,locale='en',cursor=first['next_cursor']),'en','IN')
  filtered,_=catalog_page(self.request(limit=1,locale='en'),'en','IN');self.assertEqual(len(filtered['items']),1);self.assertTrue(filtered['has_more'])
 def test_collection_has_english_editorial_text_and_all_content_by_default(self):
  c=CatalogCollection.objects.create(slug='original-mixed-series',kind='series',published=True,title_en='Original mixed series',title_bn='মূল ধারাবাহিক',description_en='An English interface heading',description_bn='বাংলা বিবরণ')
  CatalogItem.objects.create(collection=c,edition=self.bn,sort_order=1);CatalogItem.objects.create(collection=c,edition=self.en,sort_order=2)
  result=collection_detail(self.request(),c.pk,None,'IN');self.assertEqual([x['locale'] for x in result['items']],['bn','en']);self.assertEqual(result['title'],c.title_en)
  result=collection_detail(self.request(locale='bn'),c.pk,'bn','IN');self.assertEqual([x['locale'] for x in result['items']],['bn']);self.assertEqual(result['title'],c.title_en)
  first=collection_detail(self.request(limit=1),c.pk,None,'IN')
  with self.assertRaises(DomainError):collection_detail(self.request(limit=1,locale='bn',cursor=first['next_cursor']),c.pk,'bn','IN')
 def test_search_all_languages_preserves_language_scoped_reviewed_aliases(self):
  staff=get_user_model().objects.create_superuser('original-language-operator@example.test','Original-Language-Operator-47')
  # One reviewed alias per language must not grant its target match to the other language.
  for edition in [self.en,self.bn]:
   SearchAlias.objects.create(locale=edition.locale,alias_normalized='originallookup',target_normalized=edition.live_revision.title,reviewed_by=staff,reviewed_at=timezone.now()-timedelta(seconds=1))
  response=views.catalog(self.request('/api/v1/search',q='originallookup'));self.assertEqual(response.status_code,200,response.content)
  self.assertEqual({x['locale'] for x in json.loads(response.content)['items']},{'en','bn'})
  result,_=catalog_page(self.request('/api/v1/search',q='originallookup',locale='bn'),'bn','IN',query='originallookup');self.assertEqual([x['locale'] for x in result['items']],['bn'])
  # Bengali original Unicode text must be searchable without a UI-locale parameter.
  result,_=catalog_page(self.request('/api/v1/search',q=self.bn.live_revision.title),None,'IN',query=self.bn.live_revision.title);self.assertIn(str(self.bn.id),[x['edition_id'] for x in result['items']])
  self.assertIsNone(result['locale'])
 def test_draft_or_denied_language_never_leaks_into_all_content(self):
  draft=services.clone_revision(self.bn.live_revision_id)
  self.assertNotIn(str(draft.id),json.dumps(catalog_page(self.request(),None,'IN')[0]))
  Rights.objects.filter(revision=self.bn.live_revision,format='reader',action='read').update(approved=False)
  result,_=catalog_page(self.request(),None,'IN');self.assertEqual([x['locale'] for x in result['items']],['en'])
 def test_published_language_options_are_extension_ready_without_draft_metadata(self):
  self.assertEqual(services.published_content_languages('IN'),[{'code':'en','label':'English'},{'code':'bn','label':'Bengali'}])
  # Current schema still only qualifies en/bn publication/indexing; discovery can
  # recognize a future two-letter published code without hard-coded UI languages.
  key=uuid.uuid4().hex;work=Work.objects.create(slug='original-future-'+key,title='Original future language')
  e=Edition.objects.create(work=work,slug='original-future-'+key,locale='fr');r=Revision.objects.create(edition=e,title=work.title,access_policy={'reader':'free'})
  unit=Unit.objects.create(revision=r,title='Original',ordinal=1)
  Asset.objects.create(revision=r,unit=unit,kind='reader_package',state='ready',storage_key=f'revisions/{r.id}/{uuid.uuid4()}.json',sha256='0'*64,bytes=1,content_type='application/json')
  Rights.objects.create(revision=r,format='reader',action='read',territories=['IN'],starts_at=timezone.now()-timedelta(days=1),ends_at=timezone.now()+timedelta(days=1),approved=True,test_only=True,evidence='Original local extension discovery only')
  self.assertNotIn('fr',[x['code'] for x in services.published_content_languages('IN')])
  r.state='live';r.save();e.live_revision=r;e.save()
  self.assertIn({'code':'fr','label':'FR'},services.published_content_languages('IN'))
  self.assertEqual(services.published_content_languages('AE'),[])
 def test_home_cache_lifetime_includes_bengali_shelf_rights(self):
  Rights.objects.filter(revision=self.bn.live_revision,format='reader',action='read').update(ends_at=timezone.now()+timedelta(seconds=10))
  response=views.home(self.request('/api/v1/home'));self.assertEqual(response.status_code,200)
  body=json.loads(response.content);self.assertIsNone(body['locale']);self.assertTrue(any(x['locale']=='bn' for shelf in body['shelves'] for x in shelf['items']))
  ttl=int(response['Cache-Control'].split('s-maxage=')[1].split(',')[0]);self.assertLessEqual(ttl,10)

 def test_bengali_alias_never_matches_an_english_edition_with_the_same_target_title(self):
  staff=get_user_model().objects.create_superuser('alias-scope-operator@example.test','Original-Alias-Scope-47')
  mirror=self.original_edition(self.bn.live_revision.title,'en')
  SearchAlias.objects.create(locale='bn',alias_normalized='bengalialiasfixture',target_normalized=self.bn.live_revision.title,reviewed_by=staff,reviewed_at=timezone.now()-timedelta(seconds=1))
  result,_=catalog_page(self.request('/api/v1/search',q='bengalialiasfixture'),None,'IN',query='bengalialiasfixture')
  self.assertIn(str(self.bn.id),[x['edition_id'] for x in result['items']]);self.assertNotIn(str(mirror.id),[x['edition_id'] for x in result['items']])
