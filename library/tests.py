import io
import json
import tempfile
import uuid
from datetime import timedelta
from urllib.parse import urlsplit
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.db import connection,transaction,IntegrityError
from django.test import TestCase,SimpleTestCase,override_settings
from django.utils import timezone
from core.api import DomainError
from .models import Work,Edition,Revision,Unit,Paragraph,Asset,Rights
from . import services as svc
from .validation import validate_schema

EN='20000000-0000-4000-8000-000000000001'
BN='20000000-0000-4000-8000-000000000002'

class LibraryAcceptanceTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.override=override_settings(MEDIA_ROOT=self.directory.name,MAISON_LOCAL_FIXTURES=True,LOCAL=True)
        self.override.enable();self.addCleanup(self.override.disable);self.addCleanup(self.directory.cleanup)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.user=get_user_model().objects.create_user('reader@example.test','LocalReader-Passphrase-47',is_verified=True)
        self.admin=get_user_model().objects.create_superuser('staff@example.test','LocalStaff-Passphrase-47')
        self.edition=Edition.objects.select_related('live_revision').get(pk=EN)
        self.revision=self.edition.live_revision
        self.unit=self.revision.units.first()
        self.login()

    def login(self,user=None):
        user=user or self.user
        password='LocalStaff-Passphrase-47' if user==self.admin else 'LocalReader-Passphrase-47'
        response=self.client.post('/api/v1/auth/login',{'email':user.email,'password':password},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.device=response.json()['device_id']

    def test_catalog_numeric_filters_are_bounded_before_query_or_datetime_arithmetic(self):
        for field,value in [('recency_days','9'*100),('recency_days','-1'),('recency_days','3651'),('duration_min','1441'),('duration_max','not-an-integer')]:
            with self.subTest(field=field,value=value),self.assertRaises(DomainError) as error:svc.catalog_cards(**{field:value})
            self.assertEqual(error.exception.status,422)
        with self.assertRaises(DomainError):svc.catalog_cards(duration_min='60',duration_max='30')
        self.assertIsInstance(svc.catalog_cards(duration_min='0',duration_max='1440',recency_days='3650'),list)

    def test_requires_real_postgresql(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.assertIn(connection.pg_version//10000,(17,18))

    def test_response_rights_snapshot_matches_policy_without_caching_authorization(self):
        now=timezone.now()
        Rights.objects.create(revision=self.revision,format='reader',action='read',territories=['IN',123],
            starts_at=now-timedelta(days=1),ends_at=now+timedelta(days=500),approved=True,test_only=True,evidence='Malformed synthetic row')
        checks=[(format,action,region) for format in ('reader','audio') for action in ('read','preview','download') for region in ('IN','US')]
        expected={(format,action,region):getattr(svc.current_right(self.revision,format,action,region,at=now),'pk',None) for format,action,region in checks}
        with self.assertNumQueries(1):svc.prefetch_public_rights([self.revision])
        with self.assertNumQueries(0):
            for format,action,region in checks:
                self.assertEqual(getattr(svc.current_right(self.revision,format,action,region,at=now),'pk',None),expected[format,action,region])
            self.assertEqual(svc.public_ttl(self.revision,30,territory='IN'),30)
            self.assertIsNone(svc.current_right(self.revision,at=now+timedelta(days=600)))
            with override_settings(MAISON_LOCAL_FIXTURES=False):self.assertIsNone(svc.current_right(self.revision,at=now))
        Rights.objects.filter(revision=self.revision,action='read').update(approved=False)
        with self.assertRaises(DomainError):svc.authorize_revision(self.user,self.revision,territory='IN')
        # Refreshing the same response object must not preserve an older snapshot.
        svc.prefetch_public_rights([self.revision])
        self.assertIsNone(svc.current_right(self.revision,at=now))

    def test_default_deny_even_with_rights_and_no_offer(self):
        clone=svc.clone_revision(self.revision.id)
        Rights.objects.filter(revision=clone).update(approved=True)
        clone.access_policy={};clone.save()
        clone.state='live';clone.save()
        self.edition.live_revision=clone;self.edition.save()
        with self.assertRaises(DomainError) as error: svc.authorize_revision(self.user,clone)
        self.assertEqual(error.exception.code,'access_denied')

    def test_free_rights_member_and_territory_gates(self):
        self.assertEqual(svc.authorize_revision(self.user,self.revision).id,self.revision.id)
        for user,territory in [(AnonymousUser(),'IN'),(self.user,'US')]:
            with self.assertRaises(DomainError): svc.authorize_revision(user,self.revision,territory=territory)
        with override_settings(MAISON_LOCAL_FIXTURES=False):
            with self.assertRaises(DomainError): svc.authorize_revision(self.user,self.revision)

    def test_bound_preview_has_no_full_text_or_package_url(self):
        response=self.client.get(f'/api/v1/content/previews/{self.revision.id}')
        self.assertEqual(response.status_code,200,response.content)
        preview=response.json();validate_schema(preview,'PreviewPackage')
        self.assertFalse(preview['full_content_included'])
        self.assertEqual(sum(len(p['text']) for u in preview['units'] for p in u['paragraphs']),130)
        self.assertNotIn(self.unit.paragraphs.last().text,response.content.decode())
        self.assertNotIn('storage_key',response.content.decode());self.assertNotIn('evidence',response.content.decode())

    def test_real_bilingual_reader_and_exact_manifest_contract(self):
        for eid in (EN,BN):
            detail=svc.edition_detail(eid);validate_schema(detail,'Edition')
            manifest=svc.get_reader_manifest(self.user,detail['edition_revision_id']);validate_schema(manifest,'ReaderManifest')
            unit=Unit.objects.get(pk=manifest['units'][0]['unit_id'])
            doc=svc.get_reader_document(self.user,eid,unit.id)
            self.assertEqual(len(doc['paragraphs']),6)
            if eid==BN: self.assertIn('মীরা',doc['paragraphs'][0]['text'])

    def test_local_grant_bytes_are_verified_private_and_logout_denied(self):
        request={'edition_revision_id':str(self.revision.id),'unit_ids':[str(self.unit.id)],'device_id':self.device,'purpose':'online'}
        response=self.client.post('/api/v1/content/packages/grants',request,content_type='application/json')
        self.assertEqual(response.status_code,200,response.content);grant=response.json();validate_schema(grant,'PackageGrant')
        descriptor=grant['assets'][0];url=urlsplit(descriptor['url']);path=url.path+'?'+url.query
        result=self.client.get(path);self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result['Cache-Control'],'private, no-store');self.assertEqual(svc.digest(result.content),descriptor['sha256'])
        validate_schema(result.json(),'ReaderChunk')
        self.client.delete('/api/v1/session')
        self.assertEqual(self.client.get(path).status_code,401)

    def test_wrong_revision_units_and_raw_assets_cannot_receive_grants(self):
        other=Edition.objects.get(pk=BN).live_revision.units.first()
        with self.assertRaises(DomainError) as error:
            svc.package_grant(self.user,{'edition_revision_id':str(self.revision.id),'unit_ids':[str(other.id)],'device_id':self.device,'purpose':'online'})
        self.assertEqual(error.exception.code,'unit_revision_mismatch')
        clone=svc.clone_revision(self.revision.id)
        for kind in svc.RAW_KINDS:
            aid=uuid.uuid4();raw=b'private test evidence';key=f'revisions/{clone.id}/{aid}'
            path=svc.asset_path(key);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            asset=Asset.objects.create(id=aid,revision=clone,kind=kind,state='ready',storage_key=key,sha256=svc.digest(raw),bytes=len(raw),content_type='text/plain')
            with self.assertRaises(DomainError) as error: svc._asset_grant(self.user,asset,self.device)
            self.assertEqual(error.exception.code,'asset_not_deliverable')

    def test_grant_and_public_cache_ttl_cap_known_rights_expiry(self):
        expiry=timezone.now()+timedelta(seconds=8)
        Rights.objects.filter(revision=self.revision,action='read').update(ends_at=expiry)
        self.assertLessEqual(svc.public_ttl(self.revision,30),8)
        grant=svc.package_grant(self.user,{'edition_revision_id':str(self.revision.id),'unit_ids':[str(self.unit.id)],'device_id':self.device,'purpose':'online'})
        self.assertLessEqual(__import__('datetime').datetime.fromisoformat(grant['expires_at'].replace('Z','+00:00')),expiry)
        with patch('library.services.timezone.now',return_value=expiry+timedelta(seconds=1)):
            with self.assertRaises(DomainError): svc.authorize_revision(self.user,self.revision)

    def test_immutable_database_guards_and_revision_versions(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            Paragraph.objects.filter(unit=self.unit).update(text='Bypass must fail')
        clone=svc.clone_revision(self.revision.id);old=Revision.objects.get(pk=clone.id).version
        para=clone.units.first().paragraphs.first();Paragraph.objects.filter(pk=para.pk).update(text='New draft text')
        self.assertGreater(Revision.objects.get(pk=clone.id).version,old)
        with self.assertRaises(IntegrityError),transaction.atomic():
            Edition.objects.filter(pk=BN).update(live_revision=self.revision)
        another=svc.clone_revision(self.revision.id)
        asset=clone.assets.first()
        with self.assertRaises(IntegrityError),transaction.atomic():
            Asset.objects.filter(pk=asset.id).update(unit=another.units.first())

    def test_clone_uses_separate_verified_locators_and_fresh_packages(self):
        before={a.storage_key:a.sha256 for a in self.revision.assets.all()}
        clone=svc.clone_revision(self.revision.id)
        self.assertFalse(set(before)&set(clone.assets.values_list('storage_key',flat=True)))
        self.assertTrue(all(svc.digest(svc._asset_valid(a))==a.sha256 for a in clone.assets.all()))
        cover=clone.assets.get(kind='cover');self.assertEqual(cover.copy_verified_bytes,cover.bytes)
        package=json.loads(svc._asset_valid(clone.assets.get(kind='reader_package')))
        self.assertEqual(package['edition_revision_id'],str(clone.id));self.assertEqual(package['unit_id'],str(clone.units.first().id))
        self.assertEqual(clone.preview[0]['anchor_id'],str(clone.units.first().paragraphs.first().anchor_id))
        self.assertFalse(clone.rights.filter(approved=True).exists())
        self.assertEqual(before,{a.storage_key:a.sha256 for a in self.revision.assets.all()})

    def test_publication_requires_permission_exact_hash_cas_and_real_browser_evidence(self):
        clone=svc.clone_revision(self.revision.id)
        Rights.objects.filter(revision=clone).update(approved=True)
        clone.refresh_from_db()
        with self.assertRaises(DomainError) as err: svc.transition_revision(self.user,clone.id,'mark-ready',clone.version,clone.content_sha256,'test only')
        self.assertEqual(err.exception.code,'permission_denied')
        with self.assertRaises(DomainError) as err: svc.transition_revision(self.admin,clone.id,'mark-ready',clone.version,clone.content_sha256,'test only')
        self.assertEqual(err.exception.code,'publication_not_ready')
        # Explicit synthetic evidence belongs only to this test transaction, never seed/release evidence.
        clone.validation_evidence={'browser':{'status':'pass','sha256':clone.content_sha256,'scope':'local_test_only'}};clone.save()
        state=svc.transition_revision(self.admin,clone.id,'mark-ready',clone.version,clone.content_sha256,'Synthetic service acceptance only')
        self.assertEqual(state['state'],'ready')
        with self.assertRaises(DomainError) as err: svc.transition_revision(self.admin,clone.id,'publish',state['version']-1,clone.content_sha256,'stale test')
        self.assertEqual(err.exception.status,412)
        published=svc.transition_revision(self.admin,clone.id,'publish',state['version'],clone.content_sha256,'Synthetic service acceptance only')
        self.assertEqual(published['state'],'live');self.edition.refresh_from_db();self.assertEqual(self.edition.live_revision_id,clone.id)
        self.revision.refresh_from_db();self.assertEqual(self.revision.state,'retired')

    def test_schedule_outbox_is_exact_revision_version_actor_bound_and_reschedule_safe(self):
        from core.models import OutboxJob
        clone=svc.clone_revision(self.revision.id)
        Rights.objects.filter(revision=clone).update(approved=True)
        clone.refresh_from_db()
        clone.validation_evidence={'browser':{'status':'pass','sha256':clone.content_sha256,'scope':'local_test_only'}};clone.save()
        ready=svc.transition_revision(self.admin,clone.id,'mark-ready',clone.version,clone.content_sha256,'Synthetic schedule preparation')
        due=timezone.now()+timedelta(hours=1)
        scheduled=svc.transition_revision(self.admin,clone.id,'schedule',ready['version'],clone.content_sha256,'Synthetic scheduled publication',publish_at=due)
        job=OutboxJob.objects.get(kind='scheduled_publication')
        self.assertEqual(job.actor,self.admin);self.assertEqual(job.not_before,due)
        self.assertEqual(job.payload,{'actor_id':str(self.admin.pk),'revision_id':str(clone.id),'expected_version':scheduled['version'],
            'expected_sha256':clone.content_sha256,'scheduled_for':svc.iso(due),'reason':'Synthetic scheduled publication'})
        self.assertEqual(job.dedupe_key,f"scheduled-publication:{clone.id}:{scheduled['version']}")
        with self.assertRaises(DomainError) as error:
            svc.transition_revision(self.admin,clone.id,'schedule',ready['version'],clone.content_sha256,'Repeated stale schedule',publish_at=due)
        self.assertEqual(error.exception.status,412);self.assertEqual(OutboxJob.objects.filter(kind='scheduled_publication').count(),1)
        later=due+timedelta(hours=1)
        rescheduled=svc.transition_revision(self.admin,clone.id,'schedule',scheduled['version'],clone.content_sha256,'Synthetic reschedule',publish_at=later)
        self.assertGreater(rescheduled['version'],scheduled['version'])
        jobs=list(OutboxJob.objects.filter(kind='scheduled_publication').order_by('not_before'))
        self.assertEqual(len(jobs),2);self.assertNotEqual(jobs[0].dedupe_key,jobs[1].dedupe_key)
        self.assertEqual(jobs[0].payload['scheduled_for'],svc.iso(due));self.assertEqual(jobs[1].payload['scheduled_for'],svc.iso(later))
        clone.refresh_from_db();self.assertEqual(clone.state,'ready');self.assertEqual(clone.scheduled_for,later)
        self.edition.refresh_from_db();self.assertEqual(self.edition.live_revision_id,self.revision.id)

    def test_schedule_rolls_back_when_durable_job_cannot_be_written(self):
        clone=svc.clone_revision(self.revision.id)
        Rights.objects.filter(revision=clone).update(approved=True);clone.refresh_from_db()
        clone.validation_evidence={'browser':{'status':'pass','sha256':clone.content_sha256,'scope':'local_test_only'}};clone.save()
        ready=svc.transition_revision(self.admin,clone.id,'mark-ready',clone.version,clone.content_sha256,'Synthetic schedule preparation')
        with patch('core.models.OutboxJob.objects.create',side_effect=RuntimeError('Synthetic outbox unavailable')):
            with self.assertRaises(RuntimeError):
                svc.transition_revision(self.admin,clone.id,'schedule',ready['version'],clone.content_sha256,'Synthetic scheduled publication',publish_at=timezone.now()+timedelta(hours=1))
        clone.refresh_from_db();self.assertIsNone(clone.scheduled_for);self.assertEqual(clone.version,ready['version'])

    def test_publication_preparation_is_outside_locked_transition_and_rejects_stale_assets(self):
        from unittest.mock import patch
        clone=svc.clone_revision(self.revision.id)
        proof=svc.prepare_revision_validation(clone);clone.refresh_from_db()
        with patch('library.storage.verify_asset',side_effect=AssertionError('No provider I/O in transition')),patch('library.services._reader_package_coverage',side_effect=AssertionError('No package I/O in transition')):
            report=svc.transition_revision(self.admin,clone.id,'validate',clone.version,clone.content_sha256,prepared=proof)
            self.assertIn(report['status'],['pass','fail'])
        asset=clone.assets.first();asset.bytes+=1;asset.save();clone.refresh_from_db()
        with self.assertRaises(DomainError) as error:
            svc.transition_revision(self.admin,clone.id,'validate',clone.version,clone.content_sha256,prepared=proof)
        self.assertEqual(error.exception.code,'version_conflict')

    def test_readiness_rejects_missing_or_wrong_unit_reader_package(self):
        clone=svc.clone_revision(self.revision.id)
        Rights.objects.filter(revision=clone).update(approved=True)
        second=Unit.objects.create(revision=clone,title='Second original test unit',ordinal=2)
        Paragraph.objects.create(unit=second,ordinal=1,text='A second original local test paragraph requires its own verified package.')
        clone.refresh_from_db();clone.content_sha256=svc.revision_hash(clone)
        clone.validation_evidence={'browser':{'status':'pass','sha256':clone.content_sha256,'scope':'local_test_only'}};clone.save()
        # Two source units but only the first package: the other gates deliberately pass.
        report=svc.validate_revision(clone)
        self.assertEqual(report['status'],'fail')
        self.assertEqual([c['code'] for c in report['checks'] if c['status']=='fail'],['media'])
        with self.assertRaises(DomainError) as err:
            svc.transition_revision(self.admin,clone.id,'mark-ready',clone.version,clone.content_sha256,'Synthetic coverage regression')
        self.assertEqual(err.exception.code,'publication_not_ready')
        package=svc.write_reader_package(second)
        clone.refresh_from_db()
        self.assertEqual(svc.validate_revision(clone)['status'],'pass')
        raw=svc._asset_valid(package);original=json.loads(raw)
        first=clone.units.get(ordinal=1)
        for field,value in [('unit_id',str(first.id)),('edition_revision_id',str(self.revision.id)),
                            ('chunk_id',str(uuid.uuid4())),('anchor_revision',clone.anchor_revision+1)]:
            with self.subTest(field=field):
                wrong={**original,field:value};changed=svc.canonical_bytes(wrong)
                svc.asset_path(package.storage_key).write_bytes(changed)
                # Object bytes and stored SHA agree; semantic identity binding must still reject it.
                Asset.objects.filter(pk=package.pk).update(sha256=svc.digest(changed),bytes=len(changed))
                report=svc.validate_revision(clone)
                self.assertEqual(report['status'],'fail')
                self.assertEqual([c['code'] for c in report['checks'] if c['status']=='fail'],['media'])
        svc.asset_path(package.storage_key).write_bytes(raw)
        Asset.objects.filter(pk=package.pk).update(sha256=svc.digest(raw),bytes=len(raw))
        self.assertEqual(svc.validate_revision(clone)['status'],'pass')

    def test_raw_upload_lifecycle_cas_replay_and_narrow_cors_design(self):
        clone=svc.clone_revision(self.revision.id);self.login(self.admin)
        raw=b'Original private local fixture source';key=str(uuid.uuid4())
        data={'kind':'reader_source','edition_revision_id':str(clone.id),'content_type':'text/plain','bytes':len(raw),'sha256':svc.digest(raw),'file_name':'source.txt'}
        response=self.client.post('/api/v1/staff/assets/uploads',data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(response.status_code,201,response.content);intent=response.json();validate_schema(intent,'UploadIntent')
        self.assertEqual(intent['protocol'],'local_put')
        replay=self.client.post('/api/v1/staff/assets/uploads',data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(replay.json(),intent)
        uri=urlsplit(intent['upload_url']);upload=self.client.put(uri.path+'?'+uri.query,raw,content_type='text/plain')
        self.assertEqual(upload.status_code,200,upload.content)
        response=self.client.post(f'/api/v1/staff/assets/{intent["asset_id"]}/complete',{'sha256':svc.digest(raw),'bytes':len(raw)},content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),HTTP_IF_MATCH='"v1"')
        self.assertEqual(response.status_code,200,response.content);self.assertEqual(response.json()['state'],'ready');self.assertEqual(response.json()['version'],2)
        policy=json.loads((__import__('pathlib').Path(__file__).parent/'fixtures/r2_cors_policies.json').read_text())
        upload_policy=policy['private_staff_upload_bucket'][0]
        self.assertEqual(upload_policy['AllowedMethods'],['PUT']);self.assertNotIn('*',upload_policy['AllowedOrigins'])

    def test_bounded_search_rebuild_only_indexes_live_metadata_without_revision_edits(self):
        from .search_models import SearchDocument
        draft=svc.clone_revision(self.revision.id)
        before=dict(Revision.objects.values_list('id','version'))
        output=io.StringIO();call_command('rebuild_search_index',limit=1,stdout=output)
        result=json.loads(output.getvalue());self.assertEqual(result['indexed'],1);self.assertIsNotNone(result['next_cursor'])
        output=io.StringIO();call_command('rebuild_search_index',limit=1,after=result['next_cursor'],stdout=output)
        self.assertEqual(json.loads(output.getvalue())['indexed'],1)
        self.assertFalse(SearchDocument.objects.filter(revision=draft).exists())
        self.assertEqual(dict(Revision.objects.values_list('id','version')),before)

    def test_seed_is_idempotent_preserves_existing_frozen_content(self):
        before=(Revision.objects.count(),Asset.objects.count(),self.revision.content_sha256)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.assertEqual(before,(Revision.objects.count(),Asset.objects.count(),Revision.objects.get(pk=self.revision.pk).content_sha256))


@override_settings(PUBLIC_BASE_URL='https://maison.example',ALLOWED_HOSTS=['maison.example'],MAISON_PUBLICATION_TERRITORIES=['IN'],LOCAL=True)
class EmptyCatalogCacheTests(TestCase):
    def setUp(self):
        from django.test import RequestFactory
        self.factory=RequestFactory()
        work=Work.objects.create(slug='unreleased-cache-fixture',title='Unreleased cache fixture')
        self.edition=Edition.objects.create(work=work,slug='unreleased-cache-fixture-en',locale='en')
        self.draft=Revision.objects.create(edition=self.edition,title='Unreleased cache fixture')

    def request(self,**headers):
        request=self.factory.get('/api/v1/home?locale=en&territory=IN',HTTP_HOST='maison.example',secure=True,**headers)
        request.user=AnonymousUser();request.territory='IN'
        return request

    def test_empty_home_is_public_and_first_publication_purge_includes_it(self):
        from .views import home
        from operations.cache import begin_public_response,queue_catalog_purge
        from operations.middleware import cache_headers
        from operations.models import PublicCacheReference,PublicCacheGeneration
        from core.models import OutboxJob
        request=self.request();begin_public_response(request)
        response=cache_headers(request,home(request))
        self.assertEqual(response.status_code,200)
        data=json.loads(response.content)
        self.assertIsNone(data['hero']);self.assertEqual(data['shelves'],[])
        self.assertNotIn(self.draft.title,response.content.decode())
        self.assertEqual(response['Cache-Control'],'public, max-age=0, must-revalidate')
        self.assertIn('max-age=30',response['Cloudflare-CDN-Cache-Control'])
        reference=PublicCacheReference.objects.get()
        self.assertEqual(reference.dependencies,['catalog:global'])
        epoch=PublicCacheGeneration.objects.get(pk=1).epoch
        # This is the exact hook transition_revision calls on first publication;
        # testing it does not publish even this synthetic draft.
        result=queue_catalog_purge(self.draft)
        self.assertEqual(result['url_count'],1)
        self.assertEqual(OutboxJob.objects.get(kind='catalog_cache_purge').payload['urls'],[reference.url])
        self.assertEqual(PublicCacheGeneration.objects.get(pk=1).epoch,epoch+1)
        self.edition.refresh_from_db();self.draft.refresh_from_db()
        self.assertIsNone(self.edition.live_revision_id);self.assertEqual(self.draft.state,'draft')

    def test_empty_home_still_bypasses_cookie_and_unknown_territory(self):
        from .views import home
        from operations.cache import begin_public_response
        from operations.middleware import cache_headers
        request=self.request(HTTP_COOKIE='existing-session=opaque');begin_public_response(request)
        response=cache_headers(request,home(request))
        self.assertEqual(response['Cloudflare-CDN-Cache-Control'],'no-store')
        request=self.request();request.territory='ZZ';begin_public_response(request)
        response=cache_headers(request,home(request))
        self.assertEqual(response.status_code,403)
        self.assertEqual(response['Cloudflare-CDN-Cache-Control'],'no-store')

    def test_empty_response_cannot_cross_publication_epoch_and_nonempty_fails_closed(self):
        from .views import home,_catalog_ttl
        from operations.cache import begin_public_response,queue_catalog_purge
        from operations.middleware import cache_headers
        request=self.request();begin_public_response(request);response=home(request)
        queue_catalog_purge(self.draft)
        self.assertEqual(cache_headers(request,response)['Cloudflare-CDN-Cache-Control'],'no-store')
        self.assertEqual(_catalog_ttl([{'edition_id':str(self.edition.id)}],'IN'),0)


class ContractDatetimeTests(SimpleTestCase):
    def test_schedule_rejects_invalid_calendar_and_timezone_before_service_parse(self):
        base={'edition_revision_id':str(uuid.uuid4()),'expected_sha256':'a'*64,'reason':'Synthetic date validation'}
        for value in ['2026-02-30T12:00:00Z','2026-13-01T12:00:00Z','2026-11-19T25:00:00Z','2026-11-19T12:00:00',
                      '2026-11-19T12:00:00+24:00','2026-11-19T12:00:00+01:65','not-a-dateZ']:
            with self.subTest(value=value),self.assertRaises(DomainError) as error:validate_schema({**base,'publish_at':value},'ScheduleInput')
            self.assertEqual(error.exception.status,422)
        validate_schema({**base,'publish_at':'2026-11-20T12:00:00.123Z'},'ScheduleInput')
