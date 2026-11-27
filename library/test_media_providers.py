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
            self.assertEqual(args['Params']['ResponseCacheControl'],'private, no-store, max-age=0')
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

class ServingRenditionsTests(TestCase):
    """64 kbps audiobooks, one player entry per unit, sentence-first timing."""
    def setUp(self):
        MeasuredAudioTests.setUp(self)
        from accounts.models import Device
        self.device=Device.objects.create(user=self.user,token_binding_sha256='0'*64,expires_at=timezone.now()+timedelta(days=1))

    def live(self):
        self.revision.state='live';self.revision.published_at=timezone.now();self.revision.save()
        self.revision.edition.live_revision=self.revision;self.revision.edition.save()

    def set_kbps(self,kbps,asset=None):
        asset=asset or self.asset
        self.revision.validation_evidence['media_assets'][str(asset.id)]['quality_kbps']=kbps;self.revision.save()

    def add_rendition(self,kbps):
        raw=('rendition %d'%kbps).encode()
        asset=Asset.objects.create(revision=self.revision,unit=self.unit,kind='audio_chapter',state='ready',storage_key=f'revisions/{self.revision.id}/{uuid.uuid4()}',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),content_type='audio/mpeg')
        storage.put_private(asset.storage_key,raw,'audio/mpeg')
        self.revision.validation_evidence['media_assets'][str(asset.id)]={'sha256':asset.sha256,'unit_id':str(self.unit.id),'duration_ms':self.unit.duration_ms,'quality_kbps':kbps,'prepared':True,'measurement_evidence':'synthetic isolated test only'}
        self.revision.save();return asset

    def prefer(self,kbps):
        from accounts.models import Preferences
        prefs,_=Preferences.objects.get_or_create(user=self.user);prefs.audio_quality_kbps=kbps;prefs.save()
        self.user=get_user_model().objects.get(pk=self.user.pk)

    def test_64k_only_unit_plays_for_96_preference(self):
        self.set_kbps(64);self.prefer(96);self.live()
        chapters=svc.media_chapters(self.user,self.revision.id)
        self.assertEqual([(c['asset_id'],c['quality_kbps']) for c in chapters],[(str(self.asset.id),64)])
        self.assertEqual(svc.prepared_audio(self.asset)['quality_kbps'],64)
        grant=svc.media_grant(self.user,{'asset_id':str(self.asset.id),'device_id':str(self.device.pk),'purpose':'online','quality_kbps':64})
        self.assertEqual(grant['quality_kbps'],64)
        with self.assertRaises(DomainError) as error:svc.media_grant(self.user,{'asset_id':str(self.asset.id),'device_id':str(self.device.pk),'purpose':'online','quality_kbps':96})
        self.assertEqual(error.exception.code,'quality_unavailable')

    def test_other_bitrates_are_still_refused(self):
        self.set_kbps(32)
        with self.assertRaises(DomainError):svc.prepared_audio(self.asset)

    def test_media_chapters_lists_each_unit_once(self):
        low=self.add_rendition(64);self.set_kbps(96);self.prefer(96);self.live()
        chapters=svc.media_chapters(self.user,self.revision.id)
        self.assertEqual(len(chapters),1);self.assertEqual(chapters[0]['unit_id'],str(self.unit.id))
        self.assertEqual(chapters[0]['asset_id'],str(self.asset.id));self.assertEqual(chapters[0]['quality_kbps'],96)
        self.prefer(48)  # nearest to 48 among {64,96} is 64
        chapters=svc.media_chapters(self.user,self.revision.id)
        self.assertEqual((len(chapters),chapters[0]['asset_id'],chapters[0]['quality_kbps']),(1,str(low.id),64))
        self.assertEqual(chapters[0]['title'],self.unit.title)

    def test_media_chapters_omit_markers_without_chapters(self):
        self.live()
        self.assertNotIn('markers',svc.media_chapters(self.user,self.revision.id)[0])

    def test_media_chapters_carry_paragraph_map_markers(self):
        markers=[{'title':'One','start_ms':0},{'title':'Two','start_ms':500}]
        self.map.chapters=markers;self.map.save();self.live()
        self.assertEqual(svc.media_chapters(self.user,self.revision.id)[0]['markers'],markers)

    def test_media_chapters_prefer_sentence_map_markers(self):
        self.map.chapters=[{'title':'P','start_ms':0}];self.map.save()
        TimingMap.objects.create(revision=self.revision,asset=self.asset,text_sha256=self.map.text_sha256,asset_sha256=self.asset.sha256,measured=True,precision='sentence',segments=self.map.segments,chapters=[{'title':'S','start_ms':0}])
        self.live()
        self.assertEqual(svc.media_chapters(self.user,self.revision.id)[0]['markers'],[{'title':'S','start_ms':0}])

    def sentence_map(self):
        segments=[]
        for i,p in enumerate(self.paragraphs):
            mid=max(1,len(p.text)//2)
            segments+=[{'anchor_id':str(p.anchor_id),'sentence_index':0,'start_offset_chars':0,'end_offset_chars':mid,'start_ms':i*1000,'end_ms':i*1000+500},
                       {'anchor_id':str(p.anchor_id),'sentence_index':1,'start_offset_chars':mid,'end_offset_chars':len(p.text),'start_ms':i*1000+500,'end_ms':(i+1)*1000}]
        return TimingMap.objects.create(revision=self.revision,asset=self.asset,text_sha256=self.map.text_sha256,asset_sha256=self.asset.sha256,measured=True,precision='sentence',segments=segments)

    def test_mappings_include_sentence_index(self):
        sentence=self.sentence_map();self.live()
        result=mappings(self.user,self.revision.id)
        self.assertEqual(result['status'],'mapped');self.assertEqual(len(result['maps']),1)
        row=result['maps'][0];self.assertEqual(row['precision'],'sentence');self.assertEqual(row['map_id'],str(sentence.id))
        self.assertEqual([s['sentence_index'] for s in row['segments'][:2]],[0,1])

    def test_paragraph_only_map_emits_no_sentence_index(self):
        self.live();row=mappings(self.user,self.revision.id)['maps'][0]
        self.assertEqual(row['precision'],'paragraph');self.assertTrue(all('sentence_index' not in s for s in row['segments']))

    def test_switch_position_prefers_sentence_map(self):
        sentence=self.sentence_map();p=self.paragraphs[0];self.live()
        loc={'format':'reader','unit_id':str(self.unit.id),'anchor_id':str(p.anchor_id),'offset_chars':len(p.text)-1}
        result=switch_position(self.user,{'edition_revision_id':str(self.revision.id),'from_location':loc,'to_format':'audio'})
        self.assertEqual((result['map_id'],result['precision'],result['to_location']['position_ms']),(str(sentence.id),'sentence',500))

    def test_48_assets_unchanged(self):self.check_unchanged(48)

    def test_48_96_assets_unchanged(self):self.check_unchanged(96)

    def check_unchanged(self,kbps):
        self.set_kbps(kbps);self.prefer(kbps);self.live()
        chapters=svc.media_chapters(self.user,self.revision.id)
        self.assertEqual([(c['asset_id'],c['quality_kbps'],c['duration_ms'],c['sha256']) for c in chapters],[(str(self.asset.id),kbps,self.unit.duration_ms,self.asset.sha256)])
        self.assertEqual(svc.media_grant(self.user,{'asset_id':str(self.asset.id),'device_id':str(self.device.pk),'purpose':'online'})['quality_kbps'],kbps)
        self.assertNotIn('markers',chapters[0])
        self.assertEqual([r['quality_kbps'] for r in chapters[0]['renditions']],[kbps])

    def two_renditions(self,preference):
        """Unit with 48 (self.asset) and 96 renditions, each with its own paragraph map."""
        self.set_kbps(48);high=self.add_rendition(96)
        TimingMap.objects.create(revision=self.revision,asset=high,text_sha256=self.map.text_sha256,asset_sha256=high.sha256,measured=True,segments=self.map.segments)
        self.prefer(preference);self.live();return high

    def test_48_and_96_unit_picks_the_preferred_rendition_exactly(self):
        high=self.two_renditions(48)
        chapter=svc.media_chapters(self.user,self.revision.id)[0]
        self.assertEqual((chapter['asset_id'],chapter['quality_kbps']),(str(self.asset.id),48))
        self.assertEqual([(r['asset_id'],r['quality_kbps']) for r in chapter['renditions']],[(str(self.asset.id),48),(str(high.id),96)])
        self.assertEqual(set(chapter['renditions'][0]),{'asset_id','quality_kbps','duration_ms','sha256'})
        self.prefer(96)
        chapter=svc.media_chapters(self.user,self.revision.id)[0]
        self.assertEqual((chapter['asset_id'],chapter['quality_kbps']),(str(high.id),96))
        self.assertEqual(len(chapter['renditions']),2)

    def test_64k_only_unit_lists_one_rendition(self):
        self.set_kbps(64);self.live()
        self.assertEqual([r['quality_kbps'] for r in svc.media_chapters(self.user,self.revision.id)[0]['renditions']],[64])

    def test_mappings_cap_and_choice_follow_the_chosen_rendition(self):
        high=self.two_renditions(96)
        result=mappings(self.user,self.revision.id)
        self.assertEqual([m['asset_id'] for m in result['maps']],[str(high.id)])

    def test_mappings_asset_id_returns_that_renditions_map(self):
        high=self.two_renditions(96)
        low=mappings(self.user,self.revision.id,asset_id=self.asset.id)
        self.assertEqual([m['asset_id'] for m in low['maps']],[str(self.asset.id)])
        both=mappings(self.user,self.revision.id,asset_id=high.id)
        self.assertEqual([m['asset_id'] for m in both['maps']],[str(high.id)])
        import uuid
        unknown=mappings(self.user,self.revision.id,asset_id=uuid.uuid4())
        self.assertEqual([m['asset_id'] for m in unknown['maps']],[str(high.id)])  # unknown asset: the chosen rendition, as before

    def test_unexpected_preference_error_propagates(self):
        from unittest.mock import PropertyMock
        self.live()
        with patch.object(type(self.user),'preferences',new_callable=PropertyMock,side_effect=RuntimeError('db down')):
            with self.assertRaises(RuntimeError):svc.media_chapters(self.user,self.revision.id)

    def test_missing_preferences_row_defaults_to_96(self):
        from accounts.models import Preferences
        self.set_kbps(48);high=self.add_rendition(96)
        Preferences.objects.filter(user=self.user).delete();self.live()
        user=get_user_model().objects.get(pk=self.user.pk)
        self.assertEqual(svc.media_chapters(user,self.revision.id)[0]['asset_id'],str(high.id))

    def test_audio_preview_accepts_64_kbps_clip(self):
        from .audio_preview import prepared_clip
        raw=b'clip'
        clip=Asset.objects.create(revision=self.revision,unit=self.unit,kind='preview_audio',state='ready',provider='r2',storage_key=f'revisions/{self.revision.id}/{uuid.uuid4()}.mp3',sha256=svc.digest(raw),bytes=len(raw),content_type='audio/mpeg',duration_ms=1500)
        proof={'asset_id':str(clip.id),'unit_id':str(self.unit.id),'sha256':clip.sha256,'duration_ms':1500,'quality_kbps':64,'prepared':True,'measurement_evidence':'synthetic'}
        self.revision.validation_evidence['audio_preview']=proof;self.revision.save();clip.revision=self.revision
        self.assertEqual(prepared_clip(clip)['quality_kbps'],64)
        proof['quality_kbps']=32
        with self.assertRaises(DomainError):prepared_clip(clip)


class ImmutableWriteRecoveryTests(SimpleTestCase):
    @override_settings(MEDIA_STORAGE_BACKEND='r2',R2_PRIVATE_BUCKET='private-test')
    def test_unknown_small_write_reconciles_exact_bytes_without_overwrite(self):
        raw=b'canary';expected={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        client=Mock();client.put_object.side_effect=TimeoutError('do not expose signed request')
        with patch('library.storage._client',return_value=client),patch('library.storage.private_exists',return_value=True),patch('library.storage.verify_private',return_value=expected) as verify:
            self.assertEqual(storage.put_private('exports/test/object',raw),expected)
            self.assertEqual(client.put_object.call_args.kwargs['IfNoneMatch'],'*')
            verify.assert_called_once_with('exports/test/object',len(raw),expected['sha256'],'application/octet-stream')
        with patch('library.storage._client',return_value=client),patch('library.storage.private_exists',return_value=False):
            with self.assertRaises(DomainError) as error:storage.put_private('exports/test/object',raw)
            self.assertEqual(error.exception.code,'storage_unavailable')

    @override_settings(MEDIA_STORAGE_BACKEND='r2',R2_PRIVATE_BUCKET='private-test')
    def test_unknown_multipart_completion_reconciles_and_never_uses_overwriting_copy(self):
        raw=b'private canary';sha=hashlib.sha256(raw).hexdigest();client=Mock()
        class Missing(Exception):response={'Error':{'Code':'404'}}
        client.head_object.side_effect=Missing();client.create_multipart_upload.return_value={'UploadId':'test'}
        client.upload_part.return_value={'ETag':'not-used-as-content-hash'};client.complete_multipart_upload.side_effect=TimeoutError()
        expected={'bytes':len(raw),'sha256':sha}
        with patch('library.storage._client',return_value=client),patch('library.storage.private_exists',return_value=True),patch('library.storage.verify_private',return_value=expected):
            self.assertEqual(storage.put_private_file('exports/test/object',io.BytesIO(raw),'application/octet-stream',len(raw),sha),expected)
        self.assertEqual(client.complete_multipart_upload.call_args.kwargs['IfNoneMatch'],'*');client.copy_object.assert_not_called()

    def test_copy_existing_destination_is_verified_and_never_replaced(self):
        raw=b'original';source=Mock(storage_key='revisions/test/source',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),content_type='application/octet-stream')
        with tempfile.TemporaryDirectory() as directory,override_settings(LOCAL=True,MEDIA_STORAGE_BACKEND='local',MEDIA_ROOT=directory):
            storage.put_private(source.storage_key,raw)
            storage.put_private('revisions/test/destination',b'different')
            with self.assertRaises(DomainError):storage.copy_verified(source,'revisions/test/destination')
            self.assertEqual(storage._local_path('revisions/test/destination').read_bytes(),b'different')
            result=storage.copy_verified(source,'revisions/test/new-destination')
            self.assertEqual(result['sha256'],source.sha256)


class ExhaustedSocketRegressionTests(SimpleTestCase):
    class ClosedAfterBody(io.BytesIO):
        def __init__(self,raw):super().__init__(raw);self.socket_open=True;self.timeout_calls=0;self.length=len(raw)
        def set_socket_timeout(self,value):
            if not self.socket_open:raise AttributeError('exhausted HTTPResponse has no socket')
            self.timeout_calls+=1
        def read(self,size=-1):
            value=super().read(size)
            if self.tell()==self.length:self.socket_open=False
            return value

    def test_verify_does_not_touch_socket_after_exact_content_length(self):
        for size in [65536,storage.CHUNK_BYTES,storage.CHUNK_BYTES+7]:
            raw=b'x'*size;stream=self.ClosedAfterBody(raw);sha=hashlib.sha256(raw).hexdigest()
            with self.subTest(size=size),patch('library.storage._open',return_value=(stream,size,'application/octet-stream')):
                result=storage.verify_private('exports/test/object',size,sha,'application/octet-stream')
            self.assertEqual(result['sha256'],sha);self.assertTrue(stream.closed)
            self.assertEqual(stream.timeout_calls,(size+storage.CHUNK_BYTES-1)//storage.CHUNK_BYTES)

    def test_copy_does_not_touch_exhausted_source_socket(self):
        raw=b'x'*65536;stream=self.ClosedAfterBody(raw);sha=hashlib.sha256(raw).hexdigest()
        source=Mock(storage_key='exports/test/source',bytes=len(raw),sha256=sha,content_type='application/octet-stream')
        def upload(key,fileobj,content_type,size,expected_sha,**kwargs):
            self.assertEqual(fileobj.read(),raw);self.assertEqual(expected_sha,sha)
            return {'bytes':size,'sha256':sha}
        with patch('library.storage.private_exists',return_value=False),patch('library.storage._open',return_value=(stream,len(raw),'application/octet-stream')),patch('library.storage.put_private_file',side_effect=upload):
            self.assertEqual(storage.copy_verified(source,'exports/test/copy')['sha256'],sha)
        self.assertEqual(stream.timeout_calls,1);self.assertTrue(stream.closed)
