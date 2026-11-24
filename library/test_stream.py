"""Synthetic Stream contract tests; signing is real, provider I/O is mocked."""
import base64
import io
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from core.api import DomainError
from . import stream
from .validation import validate_schema

UID='a'*32
ACCOUNT='b'*32
KEY_ID='c'*32
CUSTOMER='customer-test123.cloudflarestream.com'


class StreamAdapterTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.pem=cls.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()

    def setUp(self):
        self.override=override_settings(FEATURES={'video':True},STREAM_ACCOUNT_ID=ACCOUNT,STREAM_API_TOKEN='synthetic-read-token',
                                       STREAM_CUSTOMER_HOST=CUSTOMER,STREAM_SIGNING_KEY_ID=KEY_ID,STREAM_SIGNING_PRIVATE_KEY=self.pem)
        self.override.enable();self.addCleanup(self.override.disable)
        self.revision=SimpleNamespace(id=uuid.uuid4())
        self.asset=SimpleNamespace(id=uuid.uuid4(),provider='stream',kind='video',state='ready',storage_key=UID,duration_ms=65432,
                                   revision=self.revision,revision_id=self.revision.id,unit_id=uuid.uuid4(),
                                   unit=SimpleNamespace(revision_id=self.revision.id,duration_ms=65432))
        self.user=SimpleNamespace(public_id=uuid.uuid4())
        self.device=uuid.uuid4()
        self.expiry=timezone.now()+timedelta(minutes=10)
        self.auth=patch('library.services.authorize_revision',return_value=self.revision).start()
        self.until=patch('library.services.access_ends',side_effect=lambda *a,**kw:self.expiry).start()
        self.device_check=patch('library.services.validate_device',return_value=SimpleNamespace(id=self.device)).start()
        self.addCleanup(patch.stopall)

    def signed(self):
        result=stream.grant(self.user,self.asset,self.device,'IN')
        token=result['url'].split('/')[3]
        payload=jwt.decode(token,self.key.public_key(),algorithms=['RS256'],options={'require':['sub','kid','exp','nbf']})
        return result,token,payload

    def metadata(self):
        return {'uid':UID,'duration':65.432,'readyToStream':True,'requireSignedURLs':True,'status':{'state':'ready'},
                'playback':{'hls':f'https://{CUSTOMER}/{UID}/manifest/video.m3u8'}}

    def response(self,data=None,*,status=200,content_type='application/json',length=None):
        body=json.dumps({'success':True,'result':self.metadata()} if data is None else data).encode()
        response=MagicMock();response.status=status
        headers={'Content-Type':content_type,'Content-Length':str(len(body)) if length is None else length}
        response.getheader.side_effect=lambda name,default=None:headers.get(name,default)
        response.read.side_effect=io.BytesIO(body).read
        return response

    def test_real_rs256_token_has_exact_uid_country_no_download_and_contract(self):
        result,token,payload=self.signed()
        validate_schema(result,'MediaGrant')
        self.assertEqual(jwt.get_unverified_header(token)['alg'],'RS256')
        self.assertEqual(jwt.get_unverified_header(token)['kid'],KEY_ID)
        self.assertEqual(payload['sub'],UID);self.assertEqual(payload['kid'],KEY_ID)
        self.assertFalse(payload['downloadable'])
        self.assertEqual(payload['accessRules'],[{'type':'ip.geoip.country','action':'allow','country':['IN']},{'type':'any','action':'block'}])
        self.assertLessEqual(payload['exp']-payload['nbf'],120)
        self.assertTrue(result['url'].startswith(f'https://{CUSTOMER}/'))
        self.assertTrue(result['url'].endswith('/iframe'))
        self.assertIsNone(result['sha256']);self.assertIsNone(result['quality_kbps']);self.assertFalse(result['range_supported'])
        self.assertNotIn(str(self.user.public_id),token)
        self.auth.assert_called_once_with(self.user,self.revision,'video',territory='IN')
        self.device_check.assert_called_once_with(self.user,self.device)

    def test_expiry_capped_by_rights_entitlement_and_no_provider_call_during_grant(self):
        self.expiry=timezone.now()+timedelta(seconds=7)
        with patch('library.stream.http.client.HTTPSConnection') as network:
            result,_,payload=self.signed()
        network.assert_not_called()
        self.assertLessEqual(payload['exp'],self.expiry.timestamp())
        self.assertLessEqual(payload['exp']-payload['nbf'],7)
        self.assertEqual(int(__import__('datetime').datetime.fromisoformat(result['expires_at'].replace('Z','+00:00')).timestamp()),payload['exp'])
        self.expiry=timezone.now()-timedelta(seconds=1)
        with self.assertRaises(DomainError) as error:stream.grant(self.user,self.asset,self.device)
        self.assertEqual(error.exception.code,'rights_unavailable')

    def test_google_or_public_key_cannot_replace_private_rsa_signing_material(self):
        public=self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        for invalid in ['not-a-key',public,json.dumps({'kty':'oct','k':'c3ludGhldGlj'})]:
            with self.subTest(key_type=invalid[:15]),override_settings(STREAM_SIGNING_PRIVATE_KEY=invalid),self.assertRaises(DomainError) as err:
                stream.validate_configuration()
            self.assertEqual(err.exception.status,503)
            self.assertNotIn(invalid,str(err.exception))

    def test_official_base64_pem_and_jwk_private_key_encodings(self):
        jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key));jwk['kid']=KEY_ID;jwk['alg']='RS256'
        for material in [base64.b64encode(self.pem.encode()).decode(),json.dumps(jwk),base64.b64encode(json.dumps(jwk).encode()).decode()]:
            with self.subTest(encoding=material[:12]),override_settings(STREAM_SIGNING_PRIVATE_KEY=material):
                _,_,payload=self.signed();self.assertEqual(payload['sub'],UID)

    def test_configuration_and_provider_uid_guards(self):
        for field,invalid in [('STREAM_CUSTOMER_HOST','https://'+CUSTOMER),('STREAM_CUSTOMER_HOST',CUSTOMER+'.evil.test'),
                              ('STREAM_CUSTOMER_HOST',CUSTOMER+':443'),('STREAM_CUSTOMER_HOST','iframe.videodelivery.net'),
                              ('STREAM_ACCOUNT_ID','../other'),('STREAM_API_TOKEN','unsafe\r\nheader'),('STREAM_SIGNING_KEY_ID','not-a-key-id')]:
            with self.subTest(field=field,invalid=invalid),override_settings(**{field:invalid}),self.assertRaises(DomainError):
                stream.validate_configuration()
        for field,value in [('provider','r2'),('kind','reader_package'),('storage_key','../'+UID),('state','processing'),('duration_ms',None),('unit_id',None)]:
            old=getattr(self.asset,field);setattr(self.asset,field,value)
            with self.subTest(field=field),self.assertRaises(DomainError):stream.grant(self.user,self.asset,self.device)
            setattr(self.asset,field,old)
        self.asset.unit.duration_ms=None
        with self.assertRaises(DomainError):stream.grant(self.user,self.asset,self.device)
        self.asset.unit.duration_ms=65432
        self.asset.unit.revision_id=uuid.uuid4()
        with self.assertRaises(DomainError):stream.grant(self.user,self.asset,self.device)
        self.asset.unit.revision_id=self.revision.id
        with override_settings(FEATURES={'video':False}),self.assertRaises(DomainError):stream.grant(self.user,self.asset,self.device)

    def test_metadata_read_is_fixed_https_get_bounded_and_identity_checked(self):
        response=self.response()
        with patch('library.stream.http.client.HTTPSConnection') as factory:
            connection=factory.return_value;connection.getresponse.return_value=response
            result=stream.verify_video_metadata(self.asset)
        self.assertEqual(factory.call_args.args[0],'api.cloudflare.com')
        self.assertEqual(factory.call_args.kwargs['timeout'],3)
        self.assertEqual(connection.request.call_args.args[:2],('GET',f'/client/v4/accounts/{ACCOUNT}/stream/{UID}'))
        self.assertEqual(result,{'uid':UID,'duration_ms':65432,'require_signed_urls':True,'ready_to_stream':True})
        connection.close.assert_called_once()
        self.assertLessEqual(max(call.args[0] for call in response.read.call_args_list),65536)

    def test_metadata_privacy_readiness_uid_duration_and_origin_mismatch_fail_closed(self):
        for field,value in [('uid','d'*32),('readyToStream',False),('requireSignedURLs',False),('duration',-1),
                            ('duration',True),('duration',0),('status',{'state':'inprogress'}),
                            ('playback',{'hls':f'https://{CUSTOMER}.evil.test/{UID}/manifest/video.m3u8'})]:
            document=self.metadata();document[field]=value
            with self.subTest(field=field,value=value),patch('library.stream._metadata_request',return_value=document),self.assertRaises(DomainError):
                stream.verify_video_metadata(self.asset)
        self.asset.duration_ms+=1
        with patch('library.stream._metadata_request',return_value=self.metadata()),self.assertRaises(DomainError):stream.verify_video_metadata(self.asset)
        self.asset.duration_ms=None
        with patch('library.stream._metadata_request',return_value=self.metadata()),self.assertRaises(DomainError):stream.verify_video_metadata(self.asset)
        self.asset.duration_ms=65432
        self.asset.unit_id=uuid.uuid4();self.asset.unit=SimpleNamespace(duration_ms=60000)
        with patch('library.stream._metadata_request',return_value=self.metadata()),self.assertRaises(DomainError):stream.verify_video_metadata(self.asset)

    def test_metadata_time_size_type_status_and_network_errors_are_bounded_redacted(self):
        for response in [self.response(status=302),self.response(content_type='text/html'),self.response(length=str(stream.MAX_METADATA_BYTES+1)),
                         self.response({'success':False,'result':self.metadata()}),self.response({'success':True,'result':'wrong type'})]:
            with self.subTest(status=response.status),patch('library.stream.http.client.HTTPSConnection') as factory,self.assertRaises(DomainError) as error:
                factory.return_value.getresponse.return_value=response;stream.verify_video_metadata(self.asset)
            self.assertEqual(error.exception.status,503);factory.return_value.close.assert_called_once()
        with patch('library.stream.http.client.HTTPSConnection') as factory,self.assertRaises(DomainError) as error:
            factory.return_value.connect.side_effect=TimeoutError('Bearer synthetic-private-secret must not escape')
            stream.verify_video_metadata(self.asset)
        self.assertNotIn('synthetic-private-secret',str(error.exception))
        with patch('library.stream.http.client.HTTPSConnection') as factory,patch('library.stream.time.monotonic',side_effect=[0,9]),self.assertRaises(DomainError):
            stream.verify_video_metadata(self.asset)
        for invalid in [0,9,True,float('nan')]:
            with self.subTest(budget=invalid),self.assertRaises(DomainError):stream.verify_video_metadata(self.asset,max_seconds=invalid)

    def test_expired_rs256_token_is_rejected_by_actual_jwt_verifier(self):
        _,token,payload=self.signed()
        payload['exp']=int(timezone.now().timestamp())-1
        expired=jwt.encode(payload,self.key,algorithm='RS256',headers={'kid':KEY_ID})
        with self.assertRaises(jwt.ExpiredSignatureError):jwt.decode(expired,self.key.public_key(),algorithms=['RS256'])
        with self.assertRaises(jwt.InvalidSignatureError):
            other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            jwt.decode(token,other.public_key(),algorithms=['RS256'])


# This fixture intentionally bypasses commercial publication in a disposable DB.
# It proves the shared API authority path, not provider/readiness/rights clearance.
from django.contrib.auth import get_user_model
from django.test import TestCase
from billing.models import Entitlement
from .models import Asset,Edition,Revision,Rights,Unit,Work


@override_settings(LOCAL=True,MAISON_LOCAL_FIXTURES=False,FEATURES={'video':True},VIDEO_PROVIDER='stream',
                   STREAM_ACCOUNT_ID=ACCOUNT,STREAM_API_TOKEN='synthetic-read-token',STREAM_CUSTOMER_HOST=CUSTOMER,
                   STREAM_SIGNING_KEY_ID=KEY_ID)
class StreamAuthorityIntegrationTests(TestCase):
    def test_paid_video_api_obeys_current_rights_entitlement_device_and_online_only(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        self.override=override_settings(STREAM_SIGNING_PRIVATE_KEY=pem)
        self.override.enable();self.addCleanup(self.override.disable)
        user=get_user_model().objects.create_user('stream-authority@example.test','Synthetic-Video-Passphrase-47',is_verified=True)
        login=self.client.post('/api/v1/auth/login',{'email':user.email,'password':'Synthetic-Video-Passphrase-47','password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
        self.assertEqual(login.status_code,200,login.content)
        device=login.json()['device_id']
        work=Work.objects.create(slug='synthetic-stream-authority',title='Synthetic video authority')
        edition=Edition.objects.create(work=work,slug=work.slug,locale='en')
        revision=Revision.objects.create(edition=edition,title=work.title,access_policy={'video':'paid'})
        unit=Unit.objects.create(revision=revision,ordinal=1,title='Synthetic video',duration_ms=65432)
        asset=Asset.objects.create(revision=revision,unit=unit,kind='video',provider='stream',duration_ms=65432,
                                   state='ready',storage_key=UID,sha256='0'*64,bytes=0,content_type='application/vnd.apple.mpegurl')
        now=timezone.now()
        right=Rights.objects.create(revision=revision,format='video',action='read',territories=['IN'],
                                    starts_at=now-timedelta(days=1),ends_at=now+timedelta(minutes=5),approved=True,test_only=False)
        revision.state='live';revision.save();edition.live_revision=revision;edition.save()
        body={'asset_id':str(asset.pk),'device_id':device,'purpose':'online'}
        def issue(data=None):
            return self.client.post('/api/v1/media/grants',body if data is None else data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        with patch('library.stream.http.client.HTTPSConnection') as provider:
            denied=issue();self.assertEqual(denied.status_code,403,denied.content)
            self.assertEqual(denied.json()['code'],'entitlement_required')
            expiry=timezone.now()+timedelta(seconds=20)
            entitlement=Entitlement.objects.create(grant_key='synthetic-stream-authority',user=user,edition=edition,formats=['video'],
                                                    source='one_time_order',scope='edition',valid_from=now-timedelta(seconds=1),valid_until=expiry)
            result=issue();self.assertEqual(result.status_code,200,result.content)
            grant=result.json();validate_schema(grant,'MediaGrant')
            payload=jwt.decode(grant['url'].split('/')[3],key.public_key(),algorithms=['RS256'])
            self.assertEqual(payload['sub'],UID);self.assertLessEqual(payload['exp'],expiry.timestamp())
            self.assertIsNone(grant['sha256']);self.assertFalse(payload['downloadable'])
            offline=issue({**body,'purpose':'offline'});self.assertEqual(offline.status_code,422,offline.content)
            entitlement.revoked_at=timezone.now();entitlement.status='revoked';entitlement.save()
            self.assertEqual(issue().status_code,403)
            entitlement.revoked_at=None;entitlement.status='active';entitlement.save()
            right.approved=False;right.save()
            self.assertEqual(issue().status_code,403)
            right.approved=True;right.save()
            from accounts.models import Device
            Device.objects.filter(pk=device).update(revoked_at=timezone.now())
            self.assertIn(issue().status_code,(401,403))
            provider.assert_not_called()


class StreamPreparationTests(TestCase):
    """Draft-only operator intake with local source bytes and mocked metadata."""
    def setUp(self):
        import hashlib,tempfile
        from pathlib import Path
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.source=Path(self.directory.name)/'synthetic-source.mp4'
        self.raw=b'Original synthetic source bytes for metadata acceptance only.'
        self.source.write_bytes(self.raw)
        self.actor=get_user_model().objects.create_superuser('stream-preparer@example.test','Synthetic-Preparation-Passphrase-47')
        self.work=Work.objects.create(slug='synthetic-private-stream-preparation',title='Synthetic private Stream preparation')
        self.edition=Edition.objects.create(work=self.work,slug=self.work.slug,locale='en')
        self.revision=Revision.objects.create(edition=self.edition,title=self.work.title,access_policy={'video':'free'})
        self.unit=Unit.objects.create(revision=self.revision,ordinal=1,title='Private preparation unit',duration_ms=65432)
        self.revision.refresh_from_db()
        self.manifest={'operation_id':str(uuid.uuid4()),'edition_revision_id':str(self.revision.id),
            'expected_revision_version':self.revision.version,'unit_id':str(self.unit.id),'video_uid':UID,
            'duration_ms':65432,'source_sha256':hashlib.sha256(self.raw).hexdigest(),'source_bytes':len(self.raw),
            'source_evidence_ref':'internal:synthetic-original-upload-association-and-duration'}
        self.metadata={'uid':UID,'duration':65.432,'readyToStream':True,'requireSignedURLs':True,
            'status':{'state':'ready'},'playback':{'hls':f'https://{CUSTOMER}/{UID}/manifest/video.m3u8'}}
        self.override=override_settings(LOCAL=True,STREAM_ACCOUNT_ID=ACCOUNT,STREAM_API_TOKEN='synthetic-read-token',STREAM_CUSTOMER_HOST=CUSTOMER)
        self.override.enable();self.addCleanup(self.override.disable)

    def prepare(self,manifest=None,source=None):
        return stream.prepare_stream_asset(self.actor,manifest or self.manifest,source or self.source)

    def test_verified_intake_is_draft_only_atomic_and_durably_replayable_without_io(self):
        from core.models import OperationReceipt
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            def metadata(*args):
                self.assertFalse(any('FOR UPDATE' in query['sql'] for query in queries))
                return self.metadata
            with patch('library.stream._metadata_request',side_effect=metadata) as provider:
                status,result=self.prepare()
        self.assertEqual(status,201);provider.assert_called_once()
        asset=Asset.objects.get(pk=result['asset_id']);self.assertEqual(asset.provider,'stream');self.assertEqual(asset.state,'ready')
        self.assertEqual(asset.unit_id,self.unit.id);self.assertEqual(asset.sha256,self.manifest['source_sha256'])
        self.revision.refresh_from_db();self.edition.refresh_from_db()
        self.assertEqual(self.revision.state,'draft');self.assertIsNone(self.edition.live_revision_id)
        self.assertEqual(self.revision.access_policy,{'video':'free'})
        self.assertEqual(self.revision.rights.count(),0)
        proof=self.revision.validation_evidence['media_assets'][str(asset.id)]
        self.assertTrue(proof['prepared']);self.assertEqual(proof['source_bytes'],len(self.raw))
        self.assertNotIn(str(self.source),json.dumps(proof))
        with patch('library.stream._metadata_request',side_effect=AssertionError('Replay must not contact provider')):
            self.assertEqual(self.prepare(source='/missing-source-after-success'),(201,result))
            OperationReceipt.objects.filter(actor=self.actor,operation_id=self.manifest['operation_id']).delete()
            self.assertEqual(self.prepare(source='/missing-source-after-success'),(201,result))
        self.assertEqual(Asset.objects.count(),1)
        changed={**self.manifest,'source_evidence_ref':'changed input'}
        with self.assertRaises(DomainError) as error:self.prepare(changed)
        self.assertEqual(error.exception.code,'idempotency_key_reused')

    def test_bad_source_stale_draft_wrong_unit_or_nonpublisher_never_calls_provider(self):
        cases=[({'source_sha256':'f'*64},'asset_integrity_failed'),({'expected_revision_version':self.revision.version-1},'version_conflict'),
               ({'duration_ms':65433},'unit_revision_mismatch')]
        for change,expected in cases:
            with self.subTest(change=change),patch('library.stream._metadata_request') as provider,self.assertRaises(DomainError) as error:
                self.prepare({**self.manifest,**change})
            self.assertEqual(error.exception.code,expected);provider.assert_not_called()
        member=get_user_model().objects.create_user('nonpublisher@example.test','Synthetic-Member-Passphrase-47',is_verified=True)
        with patch('library.stream._metadata_request') as provider,self.assertRaises(DomainError) as error:
            stream.prepare_stream_asset(member,self.manifest,self.source)
        self.assertEqual(error.exception.status,403);provider.assert_not_called()
        self.assertFalse(Asset.objects.exists())

    def test_provider_failure_and_post_verification_cas_do_not_mutate_draft(self):
        from core.models import OperationReceipt
        with patch('library.stream._metadata_request',return_value={**self.metadata,'requireSignedURLs':False}),self.assertRaises(DomainError):self.prepare()
        self.assertFalse(Asset.objects.exists());self.assertFalse(OperationReceipt.objects.exists())
        before=self.revision.version
        def changed(*args):
            self.revision.description='A concurrent draft correction';self.revision.save()
            return self.metadata
        with patch('library.stream._metadata_request',side_effect=changed),self.assertRaises(DomainError) as error:self.prepare()
        self.assertEqual(error.exception.code,'version_conflict');self.assertFalse(Asset.objects.exists())
        self.revision.refresh_from_db();self.assertGreater(self.revision.version,before)
        self.assertNotIn('media_assets',self.revision.validation_evidence)

    def test_publisher_revocation_during_provider_verification_prevents_local_commit(self):
        def demoted(*args):
            get_user_model().objects.filter(pk=self.actor.pk).update(is_staff=False)
            return self.metadata
        with patch('library.stream._metadata_request',side_effect=demoted),self.assertRaises(DomainError) as error:
            self.prepare()
        self.assertEqual(error.exception.code,'permission_denied')
        self.assertFalse(Asset.objects.exists())

    def test_management_manifest_prepares_existing_uid_without_upload_or_publish(self):
        from pathlib import Path
        from django.core.management import call_command
        from django.core.management.base import CommandError
        packet=Path(self.directory.name)/'private-manifest.json'
        packet.write_text(json.dumps({**self.manifest,'source_file':self.source.name}))
        output=io.StringIO()
        with patch('library.stream._metadata_request',return_value=self.metadata):
            call_command('verify_media_asset',stream_manifest=str(packet),actor_email=self.actor.email,stdout=output)
        result=json.loads(output.getvalue());self.assertEqual(result['revision_state'],'draft')
        self.assertEqual(result['asset_id'],self.manifest['operation_id'])
        self.assertEqual(Asset.objects.get(pk=result['asset_id']).storage_key,UID)
        with self.assertRaises(CommandError):
            call_command('verify_media_asset',stream_manifest=str(packet),stdout=io.StringIO())

    def test_private_draft_video_review_requires_publisher_mfa_rights_and_device(self):
        from . import services as svc
        from .catalog_query import catalog_queryset
        with patch('library.stream._metadata_request',return_value=self.metadata):_,result=self.prepare()
        asset=Asset.objects.get(pk=result['asset_id'])
        now=timezone.now()
        right=Rights.objects.create(revision=self.revision,format='video',action='read',territories=['IN'],
            starts_at=now-timedelta(days=1),ends_at=now+timedelta(minutes=5),approved=True,test_only=False)
        login=self.client.post('/api/v1/auth/login',{'email':self.actor.email,'password':'Synthetic-Preparation-Passphrase-47','password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
        self.assertEqual(login.status_code,200,login.content);device=login.json()['device_id']
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        with override_settings(FEATURES={'video':True},VIDEO_PROVIDER='stream',STAFF_MFA_REQUIRED=True,STREAM_SIGNING_KEY_ID=KEY_ID,STREAM_SIGNING_PRIVATE_KEY=pem):
            with self.assertRaises(DomainError):svc.authorize_revision(self.actor,self.revision,'video')
            self.actor.staff_mfa_verified=True
            self.assertEqual(svc.authorize_revision(self.actor,self.revision,'video').pk,self.revision.pk)
            self.assertIn('video',svc.edition_detail(self.edition.pk,user=self.actor)['formats'])
            with patch('library.stream.http.client.HTTPSConnection') as provider:
                validate_schema(stream.grant(self.actor,asset,device),'MediaGrant');provider.assert_not_called()
            member=get_user_model().objects.create_user('draft-viewer@example.test','Synthetic-Member-Passphrase-47',is_verified=True)
            with self.assertRaises(DomainError):svc.authorize_revision(member,self.revision,'video')
            with self.assertRaises(DomainError):svc.edition_detail(self.edition.pk)
            self.assertFalse(catalog_queryset('en','IN').filter(pk=self.edition.pk).exists())
            right.approved=False;right.save()
            with self.assertRaises(DomainError):stream.grant(self.actor,asset,device)
        self.edition.refresh_from_db();self.revision.refresh_from_db()
        self.assertIsNone(self.edition.live_revision_id);self.assertEqual(self.revision.state,'draft')
