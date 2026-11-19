import hashlib
import io
import json
import tempfile
import uuid
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier,Event
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.db import transaction,connection,connections,OperationalError
from django.http import JsonResponse,HttpResponse
from django.test import TestCase,TransactionTestCase,RequestFactory,override_settings
from django.utils import timezone
from library.models import Edition,Rights
from core.models import OutboxJob
from .cache import begin_public_response,finalize_public_response,queue_catalog_purge,_generation
from .models import PublicCacheReference,PublicCacheGeneration


@override_settings(PUBLIC_BASE_URL='https://maison.example',MAISON_PUBLICATION_TERRITORIES=['IN','US'],ALLOWED_HOSTS=['maison.example'])
class CacheReferenceTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.override=override_settings(LOCAL=True,MEDIA_ROOT=self.tmp.name,MAISON_LOCAL_FIXTURES=True);self.override.enable();self.addCleanup(self.override.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.revision=Edition.objects.get(pk='20000000-0000-4000-8000-000000000001').live_revision
        self.factory=RequestFactory()
    def request(self,path='/api/v1/home?locale=en&territory=IN',territory='IN',**kwargs):
        request=self.factory.get(path,HTTP_HOST='maison.example',secure=True,**kwargs);request.user=AnonymousUser();request.territory=territory;return request
    def response(self,ttl=30):
        response=JsonResponse({'items':[{'edition_id':str(self.revision.edition_id),'edition_revision_id':str(self.revision.id)}]})
        response['Cache-Control']=f'public, max-age=0, s-maxage={ttl}, must-revalidate';return response
    def capture(self,request=None,response=None):
        request=request or self.request();begin_public_response(request);return finalize_public_response(request,response or self.response())
    def test_actual_canonical_variants_recorded_and_invalidated_without_guesses(self):
        self.assertIn('public',self.capture()['Cache-Control'])
        request=self.request('/api/v1/home?locale=bn&territory=IN');self.capture(request)
        refs=list(PublicCacheReference.objects.all());self.assertEqual(len(refs),2)
        for ref in refs:self.assertEqual(hashlib.sha256(ref.url.encode()).hexdigest(),ref.url_sha256);self.assertIn('catalog:global',ref.dependencies)
        result=queue_catalog_purge(self.revision);self.assertEqual(result['status'],'queued');self.assertEqual(result['url_count'],2)
        urls=OutboxJob.objects.get(kind='catalog_cache_purge').payload['urls']
        self.assertEqual(set(urls),{ref.url for ref in refs});self.assertFalse(any('territory=US' in value for value in urls))
    def test_private_error_cookie_auth_and_noncanonical_responses_never_recorded(self):
        paths=['/api/v1/search?locale=en&territory=IN','/api/v1/home?territory=IN&locale=en','/api/v1/home?locale=en&territory=IN&q=secret','/api/v1/home?locale=en&territory=US']
        for path in paths:self.assertEqual(self.capture(self.request(path))['Cache-Control'],'private, no-store')
        for headers in [{'HTTP_COOKIE':'x=1'},{'HTTP_AUTHORIZATION':'Bearer private'}]:
            self.assertEqual(self.capture(self.request(**headers))['Cache-Control'],'private, no-store')
        request=self.request();request.user=SimpleNamespace(is_authenticated=True)
        self.assertEqual(self.capture(request)['Cache-Control'],'private, no-store')
        response=self.response();response.set_cookie('session','private')
        self.assertEqual(self.capture(response=response)['Cache-Control'],'private, no-store')
        response=self.response();response['Set-Cookie']='literal=private; Secure'
        self.assertEqual(self.capture(response=response)['Cache-Control'],'private, no-store')
        response=self.response();response['Vary']='Accept-Encoding, Authorization'
        self.assertEqual(self.capture(response=response)['Cache-Control'],'private, no-store')
        response=self.response();response.status_code=404
        self.assertEqual(self.capture(response=response)['Cache-Control'],'private, no-store')
        self.assertFalse(PublicCacheReference.objects.exists())
    def test_generation_change_or_capture_error_fails_closed(self):
        request=self.request();begin_public_response(request)
        self.assertEqual(queue_catalog_purge(self.revision)['status'],'not_needed')
        self.assertEqual(finalize_public_response(request,self.response())['Cache-Control'],'private, no-store')
        with patch('operations.cache.PublicCacheReference.objects.create',side_effect=RuntimeError('Synthetic database fault')):
            self.assertEqual(self.capture()['Cache-Control'],'private, no-store')
        self.assertFalse(PublicCacheReference.objects.exists())
    def test_revision_rights_and_class_ttl_caps_rechecked(self):
        request=self.request('/api/v1/content/previews/'+str(self.revision.id)+'?locale=en&territory=IN')
        result=self.capture(request,self.response(600));self.assertIn('s-maxage=60',result['Cache-Control'])
        Rights.objects.filter(revision=self.revision,action='preview').update(ends_at=timezone.now()+timedelta(seconds=9))
        result=self.capture(request,self.response(600));self.assertIn('s-maxage=8',result['Cache-Control'])
        self.revision.state='retired';self.revision.save(update_fields=['state'])
        self.assertEqual(self.capture()['Cache-Control'],'private, no-store')
    def test_cover_class_ttl_and_previous_residency_are_preserved(self):
        asset=self.revision.assets.filter(kind='cover',state='ready').first()
        request=self.request('/api/v1/content/covers/'+str(asset.id)+'?locale=en&territory=IN')
        response=HttpResponse(b'synthetic cover response',content_type='image/png');response['Cache-Control']='public, s-maxage=3600'
        self.assertIn('s-maxage=3600',self.capture(request,response)['Cache-Control'])
        initial=PublicCacheReference.objects.get().expires_at
        response=HttpResponse(b'synthetic cover response',content_type='image/png');response['Cache-Control']='public, s-maxage=5'
        self.assertIn('s-maxage=5',self.capture(request,response)['Cache-Control'])
        self.assertGreaterEqual(PublicCacheReference.objects.get().expires_at,initial)

    def test_only_affected_unexpired_refs_batched_at_thirty(self):
        now=timezone.now();expected=[]
        for n in range(31):
            url=f'https://maison.example/api/v1/catalog/collections/{uuid.uuid4()}?locale=en&territory=IN';expected.append(url)
            PublicCacheReference.objects.create(url=url,url_sha256=hashlib.sha256(url.encode()).hexdigest(),dependencies=['edition:'+str(self.revision.edition_id)],expires_at=now+timedelta(seconds=30))
        for dependency,expiry in [('edition:'+str(uuid.uuid4()),now+timedelta(seconds=30)),('catalog:global',now-timedelta(seconds=1))]:
            url='https://maison.example/en/titles/'+str(uuid.uuid4())+'/'
            PublicCacheReference.objects.create(url=url,url_sha256=hashlib.sha256(url.encode()).hexdigest(),dependencies=[dependency],expires_at=expiry)
        result=queue_catalog_purge(self.revision);self.assertEqual(result['batch_count'],2)
        batches=list(OutboxJob.objects.filter(kind='catalog_cache_purge').values_list('payload',flat=True))
        self.assertEqual(sorted(len(batch['urls']) for batch in batches),[1,30]);self.assertEqual({url for batch in batches for url in batch['urls']},set(expected))
        queue_catalog_purge(self.revision);self.assertEqual(OutboxJob.objects.filter(kind='catalog_cache_purge').count(),4)
    def test_distinct_invalidation_epoch_does_not_reuse_completed_job(self):
        self.capture();queue_catalog_purge(self.revision)
        first=OutboxJob.objects.get(kind='catalog_cache_purge');first.status='done';first.save()
        epoch=PublicCacheGeneration.objects.get(pk=1).epoch
        self.capture();queue_catalog_purge(self.revision)
        jobs=list(OutboxJob.objects.filter(kind='catalog_cache_purge').order_by('created_at'))
        self.assertEqual(len(jobs),2);self.assertNotEqual(jobs[0].dedupe_key,jobs[1].dedupe_key)
        self.assertEqual(jobs[0].payload['urls'],jobs[1].payload['urls'])
        self.assertEqual(jobs[1].payload['urls'],[PublicCacheReference.objects.get().url])
        self.assertEqual(PublicCacheGeneration.objects.get(pk=1).epoch,epoch+1)

    def test_html_requires_exact_rendered_dependencies(self):
        response=HttpResponse('<html>public catalog</html>',content_type='text/html');response['Cache-Control']='public, s-maxage=30'
        self.assertEqual(self.capture(self.request('/en/'),response)['Cache-Control'],'private, no-store')
        response=HttpResponse('<html>public catalog</html>',content_type='text/html');response['Cache-Control']='public, s-maxage=30'
        response._maison_cache_dependencies=['revision:'+str(self.revision.id)]
        self.assertEqual(self.capture(self.request('/en/'),response)['Cache-Control'],'private, no-store')
        response['Cache-Control']='public, s-maxage=30'
        self.assertIn('public',self.capture(self.request('/en/?locale=bn&territory=IN'),response)['Cache-Control'])
        response['Cache-Control']='public, s-maxage=30'
        self.assertEqual(self.capture(self.request('/en/?locale=en&territory=US'),response)['Cache-Control'],'private, no-store')
        response['Cache-Control']='public, s-maxage=30'
        self.assertIn('public',self.capture(self.request('/en/?locale=en&territory=IN'),response)['Cache-Control'])


class GenerationLockTests(TransactionTestCase):
    def setUp(self):PublicCacheGeneration.objects.get_or_create(pk=1)
    def test_captures_share_generation_lock_concurrently(self):
        barrier=Barrier(2)
        def capture():
            try:
                with transaction.atomic():
                    epoch=_generation(shared=True);barrier.wait(timeout=3);return epoch
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(capture) for _ in range(2)]
            self.assertEqual([f.result(timeout=5) for f in futures],[1,1])
    def test_writer_waits_for_capture_then_sees_exact_committed_reference(self):
        captured=Event();release=Event();identifier=uuid.uuid4();edition_id=uuid.uuid4();work_id=uuid.uuid4()
        revision=SimpleNamespace(id=identifier,edition_id=edition_id,edition=SimpleNamespace(work_id=work_id),version=1,state='retired')
        url='https://maison.example/en/'
        def capture():
            try:
                with transaction.atomic():
                    _generation(shared=True)
                    PublicCacheReference.objects.create(url=url,url_sha256=hashlib.sha256(url.encode()).hexdigest(),dependencies=['catalog:global'],expires_at=timezone.now()+timedelta(seconds=30))
                    captured.set();release.wait(timeout=5)
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(capture);self.assertTrue(captured.wait(timeout=3))
            try:
                with self.assertRaises(OperationalError),transaction.atomic():
                    with connection.cursor() as cursor:cursor.execute("SET LOCAL lock_timeout='200ms'")
                    queue_catalog_purge(revision)
            finally:release.set()
            future.result(timeout=5)
        self.assertEqual(queue_catalog_purge(revision)['url_count'],1)
        self.assertEqual(OutboxJob.objects.get(kind='catalog_cache_purge').payload['urls'],[url])
