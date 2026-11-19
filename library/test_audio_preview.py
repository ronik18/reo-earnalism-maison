"""Separate-object sample gates. Synthetic bytes are NOT measured/released media."""
import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError,transaction
from django.test import TestCase,RequestFactory,override_settings
from django.utils import timezone
from . import services as svc,storage,views
from .models import Asset,Rights,Revision,Unit
from . import test_media_providers as media_fixtures
from .audio_preview import descriptor
from .validation import validate_schema


class PublicAudioPreviewTests(TestCase):
    def setUp(self):
        media_fixtures.MeasuredAudioTests.setUp(self)
        self.raw=b'Physically separate synthetic fixture; NOT actual measured MP3 content.'
        self.clip=Asset.objects.create(revision=self.revision,unit=self.unit,kind='preview_audio',state='ready',provider='r2',
            storage_key=f'revisions/{self.revision.id}/{uuid.uuid4()}.mp3',sha256=svc.digest(self.raw),bytes=len(self.raw),
            content_type='audio/mpeg',duration_ms=1500)
        storage.put_private(self.clip.storage_key,self.raw,'audio/mpeg')
        self.proof={'asset_id':str(self.clip.id),'unit_id':str(self.unit.id),'sha256':self.clip.sha256,'duration_ms':1500,
            'quality_kbps':96,'prepared':True,'measurement_evidence':'Synthetic gate fixture only; not real measurement or release approval'}
        self.revision.validation_evidence['audio_preview']=self.proof
        Rights.objects.create(revision=self.revision,format='audio',action='preview',territories=['IN'],
            starts_at=timezone.now()-timedelta(days=1),ends_at=timezone.now()+timedelta(days=1),approved=True,test_only=True,evidence='Synthetic local-only preview')
        self.revision.state='live';self.revision.published_at=timezone.now();self.revision.save()
        self.revision.edition.live_revision=self.revision;self.revision.edition.save()

    def request(self,path=None,**headers):
        request=RequestFactory().get(path or '/api/v1/content/previews/'+str(self.revision.id)+'?locale=en&territory=IN',**headers)
        request.user=AnonymousUser();request.territory='IN'
        return request

    def test_preview_package_exposes_only_the_separate_bounded_sample_and_real_unit(self):
        response=views.preview(self.request(),self.revision.id)
        self.assertEqual(response.status_code,200)
        data=json.loads(response.content);validate_schema(data,'PreviewPackage')
        audio=data['audio'];self.assertEqual(audio['asset_id'],str(self.clip.id));self.assertEqual(audio['unit_id'],str(self.unit.id))
        self.assertEqual(audio['sha256'],self.clip.sha256);self.assertEqual(audio['duration_ms'],1500)
        self.assertEqual(data['boundary']['audio_end_ms'],1500);self.assertFalse(data['full_content_included'])
        self.assertNotIn(str(self.asset.id),response.content.decode())
        self.assertNotIn(self.asset.storage_key,response.content.decode());self.assertNotIn('measurement_evidence',response.content.decode())

    def test_anonymous_local_range_never_falls_back_to_a_full_chapter(self):
        url=descriptor(self.revision,'IN')['url'];target=urlsplit(url)
        request=self.request(target.path+'?'+target.query,HTTP_RANGE='bytes=2-8')
        response=views.audio_preview(request,self.clip.id)
        self.assertEqual(response.status_code,206);self.assertEqual(response.content,self.raw[2:9])
        self.assertEqual(response['Content-Range'],f'bytes 2-8/{len(self.raw)}')
        self.assertIn('no-store',response['Cache-Control'])
        for byte_range in [f'bytes={len(self.raw)}-','bytes=0-9999999','bytes='+'9'*5000+'-']:
            response=views.audio_preview(self.request(HTTP_RANGE=byte_range),self.clip.id)
            self.assertEqual(response.status_code,416);self.assertEqual(response['Content-Range'],f'bytes */{len(self.raw)}')
        self.assertEqual(views.audio_preview(self.request(),self.asset.id).status_code,404)

    def test_missing_or_stale_measurement_and_withdrawn_rights_remove_sample(self):
        self.revision.validation_evidence['audio_preview']['sha256']='0'*64;self.revision.save()
        self.assertIsNone(descriptor(self.revision,'IN'))
        self.assertEqual(views.audio_preview(self.request(),self.clip.id).status_code,409)
        self.revision.validation_evidence['audio_preview']['sha256']=self.clip.sha256;self.revision.save()
        Rights.objects.filter(revision=self.revision,format='audio',action='preview').update(approved=False)
        self.assertEqual(views.audio_preview(self.request(),self.clip.id).status_code,403)
        self.assertNotIn('audio',json.loads(views.preview(self.request(),self.revision.id).content))

    def test_real_mode_requires_exact_whitelist_publication_and_clip_delivery_clearance(self):
        regions=list(settings.MAISON_PUBLICATION_TERRITORIES)
        with override_settings(LOCAL=False):
            self.assertIsNone(descriptor(self.revision,'IN'))
        Rights.objects.create(revision=self.revision,format='audio',action='preview',territories=regions,
            starts_at=timezone.now()-timedelta(days=1),ends_at=timezone.now()+timedelta(seconds=5),approved=True,test_only=False,evidence='Synthetic authority predicate test; NOT legal clearance')
        self.revision.validation_evidence['publication_clearance']={'status':'pass','sha256':self.revision.content_sha256,
            'territories':regions,'formats':['reader','audio'],'asset_sha256':{str(a.id):a.sha256 for a in self.revision.assets.filter(state='ready')},
            'evidence_ref':'Synthetic predicate test only'}
        self.revision.save()
        self.assertNotIn('public_delivery_clearance',self.revision.validation_evidence['audio_preview'])
        with override_settings(LOCAL=False,MEDIA_STORAGE_BACKEND='r2'),patch('library.storage.private_url',return_value='https://private.example.test/only-sample?synthetic-token') as sign:
            response=views.audio_preview(self.request(),self.clip.id)
            self.assertEqual(response.status_code,307);self.assertEqual(response.content,b'')
            self.assertIn('no-store',response['Cache-Control'])
            self.assertEqual(sign.call_args.args[0],self.clip.storage_key)
            self.assertGreaterEqual(sign.call_args.args[1],1);self.assertLessEqual(sign.call_args.args[1],5)
            self.assertNotIn(self.asset.storage_key,response['Location'])
        self.revision.validation_evidence['publication_clearance']['territories']=regions[:-1];self.revision.save()
        with override_settings(LOCAL=False):self.assertIsNone(descriptor(self.revision,'IN'))

    def test_database_enforces_physical_sample_bounds_even_without_model_clean(self):
        draft=Revision.objects.create(edition=self.revision.edition,title='Synthetic bounded sample draft')
        unit=Unit.objects.create(revision=draft,title='Fixture unit',ordinal=1)
        for overrides in [{'duration_ms':None},{'duration_ms':120001},{'bytes':2097153},{'unit':None},{'content_type':'video/mp4'}]:
            values={'revision':draft,'unit':unit,'kind':'preview_audio','state':'ready','provider':'r2','duration_ms':1000,
                'storage_key':f'revisions/{draft.id}/{uuid.uuid4()}.mp3','sha256':'a'*64,'bytes':10,'content_type':'audio/mpeg',**overrides}
            with self.subTest(overrides=overrides),self.assertRaises(IntegrityError),transaction.atomic():Asset.objects.bulk_create([Asset(**values)])

    def test_unpublished_revision_and_disabled_audio_never_offer_sample(self):
        with override_settings(FEATURES={**settings.FEATURES,'audio':False}):
            self.assertIsNone(descriptor(self.revision,'IN'))
            self.assertEqual(views.audio_preview(self.request(),self.clip.id).status_code,404)
        self.revision.edition.live_revision=None;self.revision.edition.save()
        self.assertIsNone(descriptor(self.revision,'IN'))
        self.assertEqual(views.audio_preview(self.request(),self.clip.id).status_code,404)

    def test_existing_upload_and_verify_command_accept_only_exact_prepared_sample(self):
        import io
        from django.core.management import call_command
        from django.core.management.base import CommandError
        draft=Revision.objects.create(edition=self.revision.edition,title='Synthetic sample intake')
        unit=Unit.objects.create(revision=draft,title='Actual sample unit',ordinal=1)
        raw=b'Separate synthetic onboarding bytes; not real MP3 measurement.'
        data={'edition_revision_id':str(draft.id),'kind':'preview_audio','unit_id':str(unit.id),'duration_ms':1000,
            'content_type':'audio/mpeg','bytes':len(raw),'sha256':svc.digest(raw),'file_name':'sample.mp3'}
        oversized=RequestFactory().post('/api/v1/staff/assets/uploads',{**data,'kind':'audio','duration_ms':10**30},content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        oversized.user=self.user;self.assertEqual(views.upload(oversized).status_code,422)
        request=RequestFactory().post('/api/v1/staff/assets/uploads',data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        request.user=self.user
        response=views.upload(request);self.assertEqual(response.status_code,201,response.content)
        intent=json.loads(response.content);asset=Asset.objects.get(pk=intent['asset_id'])
        self.assertEqual(asset.unit_id,unit.id);self.assertEqual(asset.duration_ms,1000)
        storage.put_private(asset.storage_key,raw,'audio/mpeg')
        request=RequestFactory().post(f'/api/v1/staff/assets/{asset.id}/complete',{'sha256':asset.sha256,'bytes':asset.bytes},
            content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),HTTP_IF_MATCH=f'"v{asset.version}"')
        request.user=self.user
        response=views.complete_upload(request,asset.id);self.assertEqual(response.status_code,200,response.content)
        asset.refresh_from_db();self.assertEqual(asset.state,'processing')
        with self.assertRaises(CommandError):call_command('verify_media_asset',str(asset.id),stdout=io.StringIO())
        asset.refresh_from_db();self.assertEqual(asset.state,'processing')
        draft.refresh_from_db();draft.validation_evidence={'audio_preview':{'asset_id':str(asset.id),'unit_id':str(unit.id),
            'sha256':asset.sha256,'duration_ms':1000,'quality_kbps':96,'prepared':True,'measurement_evidence':'Synthetic gate fixture only'}};draft.save()
        call_command('verify_media_asset',str(asset.id),stdout=io.StringIO())
        asset.refresh_from_db();draft.refresh_from_db()
        self.assertEqual(asset.state,'ready');self.assertEqual(draft.state,'draft')
        self.assertIsNone(descriptor(draft,'IN'))

    def test_preproduced_stream_adoption_is_read_only_and_clone_rejects_before_object_writes(self):
        import io
        from django.core.management import call_command
        from core.api import DomainError
        draft=Revision.objects.create(edition=self.revision.edition,title='Synthetic pre-produced video')
        unit=Unit.objects.create(revision=draft,title='Video unit',ordinal=1,duration_ms=3000)
        asset=Asset.objects.create(revision=draft,unit=unit,kind='video',provider='stream',state='processing',
            storage_key=uuid.uuid4().hex,duration_ms=3000,sha256='b'*64,bytes=100,content_type='video/mp4')
        measured={'uid':asset.storage_key,'duration_ms':3000,'require_signed_urls':True,'ready_to_stream':True}
        with patch('library.stream.verify_video_metadata',return_value=measured) as verify:
            call_command('verify_media_asset',str(asset.id),stdout=io.StringIO())
            verify.assert_called_once()
        asset.refresh_from_db();draft.refresh_from_db()
        self.assertEqual(asset.state,'ready');self.assertEqual(draft.state,'draft')
        proof=draft.validation_evidence['media_assets'][str(asset.id)]
        self.assertEqual(proof['source_sha256'],asset.sha256);self.assertEqual(proof['uid'],asset.storage_key)
        with patch('library.storage.copy_verified',side_effect=AssertionError('No object writes before rejecting Stream clone')), patch('library.services.prepare_reader_package',side_effect=AssertionError('No package writes before rejecting Stream clone')):
            with self.assertRaises(DomainError) as error:svc.clone_revision(draft.id)
        self.assertEqual(error.exception.code,'stream_reimport_required')
