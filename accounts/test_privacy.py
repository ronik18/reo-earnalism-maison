import json,tempfile,uuid
from unittest.mock import patch
from django.conf import settings
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from core.jobs import run_due_jobs
from core.models import OutboxJob,OperationReceipt
from core.api import DomainError
from library.validation import validate_schema
from library import storage
from .models import User
from . import services
from .privacy import delete_account

PASS='Privacy-Test-Passphrase-47'

class PrivacyAcceptanceTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.o=override_settings(MEDIA_ROOT=self.tmp.name,LOCAL=True,MEDIA_STORAGE_BACKEND='local');self.o.enable();self.addCleanup(self.o.disable)
        self.user=User.objects.create_user('privacy@example.test',PASS,is_verified=True)
        self.other=User.objects.create_user('other-private@example.test',PASS,is_verified=True)
        self.client=Client();self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
    def request_export(self):
        response=self.client.post('/api/v1/me/privacy/requests',{'kind':'export','confirm':True},content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(response.status_code,202,response.content);return OutboxJob.objects.get(pk=response.json()['privacy_request_id'])
    def test_export_is_complete_owned_private_and_short_lived(self):
        from reader.models import PersonalList
        for n in range(105):PersonalList.objects.create(user=self.user,name=f'Owned list{n:03d}')
        PersonalList.objects.create(user=self.other,name='Other private list')
        job=self.request_export();run_due_jobs();job.refresh_from_db();self.assertEqual(job.status,'done',job.error_code)
        self.assertTrue(job.result['storage_key'].startswith(f'exports/{self.user.public_id}/'))
        raw=storage.verify_private(job.result['storage_key'],job.result['bytes'],job.result['sha256'],'application/json',return_bytes=True)
        body=json.loads(raw);self.assertEqual(len(body['lists']),105);self.assertNotIn('Other private list',raw.decode());self.assertNotIn(self.user.password,raw.decode());self.assertNotIn('scoring_snapshot',raw.decode())
        response=self.client.post(f'/api/v1/me/privacy/requests/{job.id}/download',{},content_type='application/json');self.assertEqual(response.status_code,200,response.content);validate_schema(response.json(),'PrivateFileGrant')
        result=self.client.get(response.json()['url']);self.assertEqual(result.status_code,200);self.assertEqual(result['Cache-Control'],'private, no-store')
        other=Client();other.post('/api/v1/auth/login',{'email':self.other.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
        self.assertEqual(other.post(f'/api/v1/me/privacy/requests/{job.id}/download',{},content_type='application/json').status_code,404)
    def test_export_unknown_outcome_reuses_verified_prepared_artifact(self):
        job=self.request_export();job.status='claimed';job.lease_owner='test-worker';job.save()
        first=services.process_outbox_job(job);job.refresh_from_db();self.assertIn('prepared_export',job.payload)
        self.user.display_name='Changed after upload';self.user.save()
        with patch('library.storage.put_private_file',side_effect=AssertionError('Must not upload twice')):
            second=services.process_outbox_job(job)
        self.assertEqual(first,second)
    def test_deletion_revokes_account_removes_personal_receipts_and_exports(self):
        from reader.models import PersonalList
        PersonalList.objects.create(user=self.user,name='Delete me')
        OperationReceipt.objects.create(actor=self.user,operation_id=uuid.uuid4(),kind='annotation.create',request_sha256='a'*64,http_status=201,response={'note_text':'private note'},expires_at=timezone.now()+__import__('datetime').timedelta(days=1))
        exported=self.request_export();run_due_jobs();exported.refresh_from_db();key=exported.result['storage_key'];self.assertTrue(storage.private_exists(key))
        response=self.client.post('/api/v1/me/privacy/requests',{'kind':'delete','confirm':True},content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()));self.assertEqual(response.status_code,202)
        run_due_jobs();job=OutboxJob.objects.get(pk=response.json()['privacy_request_id']);self.assertEqual(job.status,'done',job.error_code)
        self.user.refresh_from_db();self.assertFalse(self.user.is_active);self.assertFalse(self.user.has_usable_password());self.assertFalse(PersonalList.objects.filter(user=self.user).exists());self.assertFalse(OperationReceipt.objects.filter(actor=self.user,kind='annotation.create').exists());self.assertFalse(storage.private_exists(key))
        self.assertFalse(self.client.get('/api/v1/session').json()['authenticated'])
    def test_unresolved_refund_blocks_account_deletion(self):
        job=OutboxJob.objects.create(kind='privacy_delete',actor=self.user,dedupe_key='test-delete-refund',not_before=timezone.now())
        with patch('billing.models.Refund.objects.filter') as refunds:
            refunds.return_value.exists.return_value=True
            with self.assertRaises(DomainError) as caught:delete_account(job)
        self.assertEqual(caught.exception.code,'awaiting_resolution');self.user.refresh_from_db();self.assertTrue(self.user.is_active)

    def test_private_history_uses_signed_member_bound_keysets(self):
        stamp=timezone.now()
        for n in range(5):
            job=OutboxJob.objects.create(kind='privacy_export',actor=self.user,dedupe_key=f'privacy-page-{n}',not_before=stamp)
            OutboxJob.objects.filter(pk=job.pk).update(created_at=stamp)
        first=self.client.get('/api/v1/me/privacy/requests?limit=2');self.assertEqual(first.status_code,200)
        body=first.json();self.assertTrue(body['has_more']);self.assertEqual(len(body['items']),2)
        seen=[x['privacy_request_id'] for x in body['items']]
        cursor=body['next_cursor']
        while cursor:
            response=self.client.get('/api/v1/me/privacy/requests',{'limit':2,'cursor':cursor});self.assertEqual(response.status_code,200,response.content)
            page=response.json();seen.extend(x['privacy_request_id'] for x in page['items']);cursor=page['next_cursor']
        self.assertEqual(len(seen),5);self.assertEqual(len(set(seen)),5)
        self.assertEqual(self.client.get('/api/v1/me/privacy/requests',{'limit':3,'cursor':body['next_cursor']}).status_code,400)
        other=Client();other.post('/api/v1/auth/login',{'email':self.other.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
        self.assertEqual(other.get('/api/v1/me/privacy/requests',{'limit':2,'cursor':body['next_cursor']}).status_code,400)
        self.assertEqual(self.client.get('/api/v1/me/privacy/requests?limit=0').status_code,422)

    def test_export_grant_never_outlives_artifact(self):
        from datetime import timedelta,datetime
        job=self.request_export();run_due_jobs();job.refresh_from_db()
        end=timezone.now()+timedelta(seconds=20);job.result['expires_at']=end.isoformat().replace('+00:00','Z');job.save()
        with patch('library.storage.is_r2',return_value=True),patch('library.storage.private_url',return_value='https://synthetic.example.test/private') as sign:
            response=self.client.post(f'/api/v1/me/privacy/requests/{job.id}/download',{},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertLessEqual(datetime.fromisoformat(response.json()['expires_at'].replace('Z','+00:00')),end)
        self.assertLessEqual(sign.call_args.args[1],20)

    def test_expired_cleanup_revokes_before_storage_and_retries_exact_keys(self):
        from datetime import timedelta
        from .privacy import cleanup_expired_exports
        job=self.request_export();run_due_jobs();job.refresh_from_db();key=job.result['storage_key']
        job.result['expires_at']=(timezone.now()-timedelta(seconds=1)).isoformat().replace('+00:00','Z');job.save()
        def unavailable(target):
            current=OutboxJob.objects.get(pk=job.pk)
            self.assertEqual(target,key);self.assertTrue(current.payload['export_cleanup_pending'])
            self.assertIn(key,current.payload['export_cleanup_keys'])
            self.assertLessEqual(__import__('datetime').datetime.fromisoformat(current.result['delivery_until'].replace('Z','+00:00')),timezone.now())
            raise DomainError('storage_unavailable','Synthetic unavailable provider.',503)
        with patch('library.storage.delete_private',side_effect=unavailable):self.assertEqual(cleanup_expired_exports(limit=1),{'cleaned':0,'failed':1})
        self.assertTrue(storage.private_exists(key))
        self.assertEqual(self.client.post(f'/api/v1/me/privacy/requests/{job.id}/download',{},content_type='application/json').status_code,410)
        self.assertEqual(cleanup_expired_exports(limit=1),{'cleaned':1,'failed':0});self.assertFalse(storage.private_exists(key))
        job.refresh_from_db();self.assertTrue(job.payload['export_cleanup_completed']);self.assertNotIn('export_cleanup_keys',job.payload)
        self.assertEqual(cleanup_expired_exports(limit=1),{'cleaned':0,'failed':0})
