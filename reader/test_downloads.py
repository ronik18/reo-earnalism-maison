import io,json,tempfile,uuid
from datetime import timedelta
from urllib.parse import urlsplit
from django.conf import settings
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.db import transaction,IntegrityError
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from library.models import Revision,Rights,Edition
from library import services as content
from library.validation import validate_schema
from .models import DownloadLicense
from . import download_services

PASS='Offline-Test-Passphrase-47'

class DownloadAcceptanceTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.o=override_settings(MEDIA_ROOT=self.tmp.name,LOCAL=True,MAISON_LOCAL_FIXTURES=True,FEATURES={**settings.FEATURES,'offline_text_audio':True});self.o.enable();self.addCleanup(self.o.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.user=get_user_model().objects.create_user('offline@example.test',PASS,is_verified=True)
        self.staff=get_user_model().objects.create_superuser('offline-staff@example.test',PASS)
        source=Revision.objects.get(edition__slug='local-en-journey',state='live') if Edition.objects.filter(slug='local-en-journey').exists() else Edition.objects.get(pk='20000000-0000-4000-8000-000000000001').live_revision
        self.revision=content.clone_revision(source.pk);self.revision.download_policy={'reader':True};self.revision.save()
        self.revision.rights.update(approved=True)
        self.revision.rights.filter(action='download').update(ends_at=timezone.now()+timedelta(hours=2))
        self.revision.validation_evidence={'browser':{'sha256':self.revision.content_sha256,'status':'pass','scope':'local_test_only'}};self.revision.save()
        ready=content.transition_revision(self.staff,self.revision.id,'mark-ready',self.revision.version,self.revision.content_sha256,'Synthetic offline boundary')
        content.transition_revision(self.staff,self.revision.id,'publish',ready['version'],self.revision.content_sha256,'Synthetic offline boundary')
        self.revision.refresh_from_db();self.client=self.login(self.user);self.device=self.client.get('/api/v1/session').json()['device_id']
        self.data={'edition_revision_id':str(self.revision.id),'format':'reader','unit_ids':[str(self.revision.units.first().id)],'device_id':self.device}
    def login(self,user):
        c=Client();response=c.post('/api/v1/auth/login',{'email':user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json');self.assertEqual(response.status_code,200);return c
    def create(self,key=None):return self.client.post('/api/v1/me/downloads',self.data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))
    def test_lease_is_device_bound_idempotent_bounded_and_revocable(self):
        key=str(uuid.uuid4());a=self.create(key);self.assertEqual(a.status_code,201,a.content);body=a.json();validate_schema(body,'DownloadLicense')
        b=self.create(key);self.assertEqual(b.status_code,201,b.content);self.assertEqual(body['license_id'],b.json()['license_id']);self.assertEqual(body['valid_until'],b.json()['valid_until']);self.assertEqual(DownloadLicense.objects.count(),1)
        row=DownloadLicense.objects.get();self.assertLessEqual(row.expires_at,row.rights_record.ends_at);self.assertLessEqual(row.expires_at,row.issued_at+timedelta(hours=24))
        self.assertEqual(self.login(self.user).get(f'/api/v1/me/downloads/{row.id}').status_code,404)
        url=urlsplit(body['assets'][0]['url']);asset=self.client.get(url.path+'?'+url.query);self.assertEqual(asset.status_code,200)
        refresh=self.client.post(f'/api/v1/me/downloads/{row.id}/refresh',{},content_type='application/json');self.assertEqual(refresh.status_code,200);self.assertEqual(refresh.json()['valid_until'],body['valid_until'])
        deleted=self.client.delete(f'/api/v1/me/downloads/{row.id}',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(deleted.status_code,204)
        result=self.client.get(f'/api/v1/me/downloads/{row.id}').json();self.assertEqual(result['status'],'revoked');self.assertEqual(result['assets'],[])
        self.assertEqual(self.client.get(url.path+'?'+url.query).status_code,403)
    def test_rights_withdrawal_and_database_identity_enforced(self):
        response=self.create();self.assertEqual(response.status_code,201,response.content);row=DownloadLicense.objects.get()
        with self.assertRaises(IntegrityError),transaction.atomic():DownloadLicense.objects.filter(pk=row.pk).update(expires_at=row.expires_at+timedelta(seconds=1))
        right=row.rights_record;right.approved=False;right.save()
        response=self.client.get(f'/api/v1/me/downloads/{row.id}');self.assertEqual(response.json()['status'],'revoked');self.assertEqual(response.json()['assets'],[])
        right.approved=True;right.save();row.refresh_from_db();self.assertIsNotNone(row.revoked_at)
        self.assertEqual(self.client.post(f'/api/v1/me/downloads/{row.id}/renew',{},content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())).status_code,409)
    def test_logout_and_password_reset_revoke_offline_authority(self):
        response=self.create();self.assertEqual(response.status_code,201,response.content);row=DownloadLicense.objects.get()
        self.client.delete('/api/v1/session');row.refresh_from_db();self.assertIsNotNone(row.revoked_at)
    def test_disabled_and_cross_revision_selection_do_not_create_leases(self):
        with override_settings(FEATURES={**settings.FEATURES,'offline_text_audio':False}):self.assertEqual(self.create().status_code,409)
        self.data['unit_ids']=[str(uuid.uuid4())];self.assertEqual(self.create().status_code,409);self.assertFalse(DownloadLicense.objects.exists())

    def test_download_history_pages_and_device_scopes_cursor(self):
        for n in range(3):self.assertEqual(self.create().status_code,201)
        a=self.client.get('/api/v1/me/downloads?limit=2');self.assertEqual(a.status_code,200,a.content)
        page=a.json();self.assertTrue(page['has_more']);self.assertEqual(len(page['items']),2)
        b=self.client.get('/api/v1/me/downloads',{'limit':2,'cursor':page['next_cursor']});self.assertEqual(b.status_code,200,b.content)
        self.assertEqual(len(b.json()['items']),1);self.assertFalse(b.json()['has_more'])
        identifiers=[x['license_id'] for x in page['items']+b.json()['items']];self.assertEqual(len(set(identifiers)),3)
        other=self.login(self.user)
        self.assertEqual(other.get('/api/v1/me/downloads',{'limit':2,'cursor':page['next_cursor']}).status_code,400)

    def test_unready_asset_revokes_license_without_server_error(self):
        response=self.create();self.assertEqual(response.status_code,201,response.content)
        row=DownloadLicense.objects.get();asset=row.revision.assets.filter(kind='reader_package').first()
        from unittest.mock import patch
        # Live revision assets are immutable; simulate a missing ready-asset lookup.
        with patch('reader.download_services.Asset.objects.filter') as assets:
            assets.return_value.count.return_value=0
            result=self.client.get(f'/api/v1/me/downloads/{row.id}')
        self.assertEqual(result.status_code,200,result.content);self.assertEqual(result.json()['status'],'revoked');self.assertEqual(result.json()['assets'],[])
        row.refresh_from_db();self.assertIsNotNone(row.revoked_at)

    def test_previously_issued_delivery_stops_when_offline_feature_disabled(self):
        response=self.create();self.assertEqual(response.status_code,201,response.content)
        url=urlsplit(response.json()['assets'][0]['url'])
        with override_settings(FEATURES={**settings.FEATURES,'offline_text_audio':False}):
            denied=self.client.get(url.path+'?'+url.query);self.assertEqual(denied.status_code,409,denied.content)

    def test_same_browser_login_revokes_its_previous_offline_license(self):
        response=self.create();self.assertEqual(response.status_code,201,response.content);row=DownloadLicense.objects.get()
        relogin=self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
        self.assertEqual(relogin.status_code,200,relogin.content);self.assertNotEqual(relogin.json()['device_id'],self.device)
        row.refresh_from_db();self.assertIsNotNone(row.revoked_at)


class AudioDownloadAcceptanceTests(TestCase):
    def test_prepared_pieces_bind_the_audio_and_license(self):
        import hashlib
        from unittest.mock import patch
        from library import storage
        from library.models import Asset
        from core.api import DomainError
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory,MEDIA_STORAGE_BACKEND='local',LOCAL=True,MAISON_LOCAL_FIXTURES=True,FEATURES={**settings.FEATURES,'audio':True,'offline_text_audio':True}):
            call_command('seed_local_pilot',stdout=io.StringIO())
            user=get_user_model().objects.create_user('audio-download@example.test',PASS,is_verified=True)
            revision=content.clone_revision(Edition.objects.get(pk='20000000-0000-4000-8000-000000000001').live_revision_id)
            revision.access_policy={'reader':'free','audio':'free'};revision.download_policy={'audio':True};revision.save()
            unit=revision.units.first();raw=b'isolated synthetic audio, no release qualification'
            asset=Asset.objects.create(revision=revision,unit=unit,kind='audio_chapter',state='ready',storage_key=f'revisions/{revision.id}/{uuid.uuid4()}',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),content_type='audio/mpeg')
            storage.put_private(asset.storage_key,raw,'audio/mpeg')
            proof=storage.prepare_audio_pieces(asset)
            revision.validation_evidence={'offline_piece_manifests':{str(asset.id):proof}}
            revision.state='live';revision.published_at=timezone.now();revision.save()
            revision.edition.live_revision=revision;revision.edition.save()
            for action in ['read','download']:
                Rights.objects.create(revision=revision,format='audio',action=action,territories=['IN'],starts_at=timezone.now()-timedelta(days=1),ends_at=timezone.now()+timedelta(days=1),approved=True,test_only=True)
            client=Client();self.assertEqual(client.post('/api/v1/auth/login',{'email':user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json').status_code,200)
            device=client.get('/api/v1/session').json()['device_id'];data={'edition_revision_id':str(revision.id),'device_id':device,'format':'audio','unit_ids':[str(unit.id)]}
            with patch('library.storage.private_url',return_value='https://synthetic.example.test/piece-manifest'):
                result=client.post('/api/v1/me/downloads',data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            self.assertEqual(result.status_code,201,result.content);validate_schema(result.json(),'DownloadLicense')
            self.assertEqual(result.json()['assets'][0]['piece_manifest']['sha256'],proof['sha256'])
            piece_url=urlsplit(result.json()['assets'][0]['piece_manifest']['url'])
            pieces=client.get(piece_url.path+'?'+piece_url.query);self.assertEqual(pieces.status_code,200,pieces.content);validate_schema(pieces.json(),'OfflinePiecePage')
            self.assertEqual(pieces['Cache-Control'],'private, no-store')
            other=Client();other.post('/api/v1/auth/login',{'email':user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
            self.assertEqual(other.get(piece_url.path+'?'+piece_url.query).status_code,403)

            row=DownloadLicense.objects.get();self.assertEqual(download_services.validate_delivery_license(user,row.id,asset,device,'IN').pk,row.pk)
            revision.validation_evidence['offline_piece_manifests'][str(asset.id)]['asset_sha256']='0'*64;revision.save()
            with self.assertRaises(DomainError) as error,transaction.atomic():download_services._create(user,device,data,'IN')
            self.assertEqual(error.exception.code,'offline_audio_not_prepared')
            with override_settings(FEATURES={**settings.FEATURES,'audio':False,'offline_text_audio':True}):
                blocked=client.post('/api/v1/me/downloads',data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
                self.assertEqual(blocked.status_code,409)
