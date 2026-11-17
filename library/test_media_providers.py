"""Provider-contract and exact-map tests. No external calls or release approval."""
import hashlib
import io
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import Mock,patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase,SimpleTestCase,override_settings
from django.utils import timezone
from core.api import DomainError
from . import services as svc,storage
from .models import Asset,Edition,Rights,TimingMap
from .timing import mappings,switch_position

class PrivateStorageContractTests(SimpleTestCase):
    @override_settings(MEDIA_STORAGE_BACKEND='r2',R2_PRIVATE_BUCKET='private-test')
    def test_direct_urls_bind_method_type_size_create_once_and_short_expiry(self):
        client=Mock();client.generate_presigned_url.return_value='https://test.r2.cloudflarestorage.com/private-test/object?signature=synthetic'
        asset=Mock(storage_key='revisions/test/object',content_type='audio/mpeg',bytes=512)
        with patch('library.storage._client',return_value=client):
            url,headers=storage.upload_url(asset,80)
            args=client.generate_presigned_url.call_args.kwargs
            self.assertEqual(args['Params']['IfNoneMatch'],'*');self.assertEqual(args['Params']['ContentLength'],512)
            self.assertEqual(headers,{'Content-Type':'audio/mpeg','If-None-Match':'*'})
            storage.private_url(asset.storage_key,75,'audio/mpeg')
            args=client.generate_presigned_url.call_args.kwargs
            self.assertEqual(args['ExpiresIn'],75);self.assertEqual(args['HttpMethod'],'GET')
            self.assertEqual(args['Params']['ResponseCacheControl'],'private, no-store')
        with self.assertRaises(DomainError):storage.private_url(asset.storage_key,121)

    def test_streamed_verifier_hashes_all_bytes_and_rejects_corruption(self):
        raw=b'a'*(2*storage.CHUNK_BYTES+7)
        class BoundedStream(io.BytesIO):
            def read(self,n=-1):
                if not 0<n<=storage.CHUNK_BYTES:raise AssertionError('Unbounded object read')
                return super().read(n)
        with patch('library.storage._open',return_value=(BoundedStream(raw),len(raw),'audio/mpeg')):
            result=storage.verify_private('revisions/test/object',len(raw),hashlib.sha256(raw).hexdigest(),'audio/mpeg')
            self.assertEqual(result['bytes'],len(raw))
        with patch('library.storage._open',return_value=(BoundedStream(raw),len(raw),'audio/mpeg')):
            with self.assertRaises(DomainError) as err:storage.verify_private('revisions/test/object',len(raw),'0'*64,'audio/mpeg')
            self.assertEqual(err.exception.code,'asset_integrity_failed')
        with self.assertRaises(DomainError):storage.delete_private('revisions/test/object')

class MeasuredAudioTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.directory.name,MEDIA_STORAGE_BACKEND='local',LOCAL=True,MAISON_LOCAL_FIXTURES=True,
            FEATURES={**settings.FEATURES,'audio':True});self.override.enable();self.addCleanup(self.override.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.user=get_user_model().objects.create_user('audio-test@example.test','Test-Only-Password-47',is_verified=True)
        self.revision=svc.clone_revision(Edition.objects.get(pk='20000000-0000-4000-8000-000000000001').live_revision_id)
        self.revision.access_policy={'reader':'free','audio':'free'};self.revision.save()
        self.revision.rights.update(approved=True)
        Rights.objects.create(revision=self.revision,format='audio',action='read',territories=['IN'],starts_at=timezone.now()-timedelta(days=1),ends_at=timezone.now()+timedelta(days=1),approved=True,test_only=True)
        self.unit=self.revision.units.first();self.paragraphs=list(self.unit.paragraphs.all())
        self.unit.duration_ms=1000*len(self.paragraphs);self.unit.save()
        raw=b'synthetic audio bytes for isolated test only'
        self.asset=Asset.objects.create(revision=self.revision,unit=self.unit,kind='audio_chapter',state='ready',storage_key=f'revisions/{self.revision.id}/{uuid.uuid4()}',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),content_type='audio/mpeg')
        storage.put_private(self.asset.storage_key,raw,'audio/mpeg')
        self.revision.validation_evidence={'media_assets':{str(self.asset.id):{'sha256':self.asset.sha256,'unit_id':str(self.unit.id),'duration_ms':self.unit.duration_ms,'quality_kbps':96,'prepared':True,'measurement_evidence':'synthetic isolated test only'}}};self.revision.save()
        self.map=TimingMap.objects.create(revision=self.revision,asset=self.asset,text_sha256=self.revision.content_sha256,asset_sha256=self.asset.sha256,measured=True,segments=[{'anchor_id':str(p.anchor_id),'start_offset_chars':0,'end_offset_chars':len(p.text),'start_ms':i*1000,'end_ms':(i+1)*1000} for i,p in enumerate(self.paragraphs)])
        self.user.is_staff=True;self.user.is_superuser=True;self.user.save()

    def test_switch_uses_measured_segment_start(self):
        self.revision.state='live';self.revision.published_at=timezone.now();self.revision.save()
        self.revision.edition.live_revision=self.revision;self.revision.edition.save()
        loc={'format':'reader','unit_id':str(self.unit.id),'anchor_id':str(self.paragraphs[0].anchor_id),'offset_chars':1}
        result=switch_position(self.user,{'edition_revision_id':str(self.revision.id),'from_location':loc,'to_format':'audio'})
        self.assertEqual(result['outcome'],'mapped');self.assertEqual(result['to_location']['position_ms'],0)
        result=switch_position(self.user,{'edition_revision_id':str(self.revision.id),'from_location':{'format':'audio','unit_id':str(self.unit.id),'position_ms':500},'to_format':'reader'})
        self.assertEqual(result['to_location']['offset_chars'],0)
        self.assertEqual(mappings(self.user,self.revision.id)['status'],'mapped')

    def test_stale_or_gapped_measured_maps_are_rejected(self):
        from .timing import validated_segments
        self.map.asset_sha256='0'*64
        with self.assertRaises(DomainError):validated_segments(self.map)
        self.map.asset_sha256=self.asset.sha256;self.map.segments=self.map.segments[:-1]
        with self.assertRaises(DomainError):validated_segments(self.map)

    def test_audio_piece_manifest_has_exact_complete_hash_coverage(self):
        proof=storage.prepare_audio_pieces(self.asset)
        from types import SimpleNamespace
        raw=storage.read_verified(SimpleNamespace(storage_key=proof['storage_key'],bytes=proof['bytes'],sha256=proof['sha256'],content_type='application/json'))
        import json
        doc=json.loads(raw);self.assertEqual(doc['asset_sha256'],self.asset.sha256)
        self.assertEqual(sum(p['bytes'] for p in doc['pieces']),self.asset.bytes)
        self.assertEqual(doc['pieces'][0]['offset_bytes'],0)
        self.revision.validation_evidence['media_assets'][str(self.asset.id)]['duration_ms']=1;self.revision.save()
        with self.assertRaises(DomainError):svc.prepared_audio(self.asset)
