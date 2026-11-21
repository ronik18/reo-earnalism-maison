"""Actual local workflow with synthetic policy refs; no legal method qualification."""
import json,uuid,hashlib,tempfile
from datetime import timedelta
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from core.models import OutboxJob,OperationReceipt,AuditEvent
from .models import User,GuardianAuthorization
from . import services
from .retention import cleanup_account_retention

PASS='Original-Guardian-Journey-47'
BASE={'enabled':True,'public_enabled':True,'max_lifetime_seconds':3600,'record_retention_seconds':3600,'legal_review_ref':'synthetic-only-no-legal-clearance','collection_route_ref':'local-test-only'}
POLICIES={f'IN:{purpose}:notice-v1:synthetic-manual-v1':dict(BASE,**extra) for purpose,extra in [('account_processing',{}),('privacy_access',{'allowed_export_sections':['profile']}),('privacy_delete',{'allow_delete':True})]}


@override_settings(LOCAL=True,GUARDIAN_AUTHORIZATION_ENABLED=True,GUARDIAN_AUTHORIZATION_POLICIES=POLICIES,STAFF_MFA_REQUIRED=True)
class GuardianJourneyTests(TestCase):
    def setUp(self):
        media=self.enterContext(tempfile.TemporaryDirectory(prefix='guardian-original-fixture-'))
        self.enterContext(override_settings(MEDIA_ROOT=media))
        self.guardian=User.objects.create_user('journey-guardian@example.test',PASS,is_verified=True)
        self.reviewer=User.objects.create_superuser('journey-reviewer@example.test',PASS)
        self.parent=self.client_for(self.guardian);self.staff=self.client_for(self.reviewer,True)
    def client_for(self,user,mfa=False):
        c=Client();r=c.post('/api/v1/auth/login',{'email':user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json');self.assertEqual(r.status_code,200,r.content)
        if mfa:
            device=TOTPDevice.objects.create(user=user,confirmed=True);s=c.session;s['otp_device_id']=device.persistent_id;s.save()
        return c
    def post(self,path,data,client=None,**headers):
        return (client or self.parent).post('/api/v1'+path,data,content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),**headers)
    def request(self,purpose='account_processing',source=None):
        d={'jurisdiction':'IN','purpose':purpose,'notice_version':'notice-v1','method':'synthetic-manual-v1'}
        if source:d['source_authorization_id']=str(source)
        r=self.post('/me/guardian/authorizations',d);self.assertEqual(r.status_code,201,r.content);return r.json()['authorization_id']
    def approve(self,aid):
        r=self.post(f'/staff/guardian/authorizations/{aid}/review',{'approve':True,'evidence_sha256':'a'*64,'expected_version':1},self.staff);self.assertEqual(r.status_code,200,r.content)
    def child(self):
        aid=self.request();self.approve(aid)
        r=self.post(f'/me/guardian/authorizations/{aid}/claim-capability',{});self.assertEqual(r.status_code,200,r.content);token=r.json()['capability']
        d={'email':'journey-child@example.test','password':PASS,'display_name':'Original fixture child','locale':'en','password_purpose_consent':True,'password_purpose_version':'password-account-v1'}
        r=self.post(f'/me/guardian/authorizations/{aid}/claim',d,HTTP_X_GUARDIAN_CLAIM=token);self.assertEqual(r.status_code,202,r.content)
        child=User.objects.get(email=d['email'])
        return aid,child,token,d
    def test_no_child_intake_until_review_and_one_time_capability(self):
        aid=self.request();row=GuardianAuthorization.objects.get(pk=aid);self.assertIsNone(row.child_id);self.assertFalse(User.objects.filter(email='journey-child@example.test').exists())
        r=self.parent.post(f'/api/v1/me/guardian/authorizations/{aid}/claim','{invalid',content_type='application/json');self.assertEqual(r.status_code,403)
        self.approve(aid);token=self.post(f'/me/guardian/authorizations/{aid}/claim-capability',{}).json()['capability']
        row.refresh_from_db();self.assertEqual(row.claim_sha256,hashlib.sha256(token.encode()).hexdigest());self.assertNotIn(token,json.dumps(list(OperationReceipt.objects.values('response'))))
    def test_claim_is_atomic_one_use_no_child_impersonation(self):
        aid,child,token,data=self.child();self.assertTrue(child.guardian_managed);self.assertFalse(child.is_verified)
        self.assertEqual(self.parent.get('/api/v1/me/profile').json()['email'],self.guardian.email)
        r=self.post(f'/me/guardian/authorizations/{aid}/claim',data,HTTP_X_GUARDIAN_CLAIM=token);self.assertEqual(r.status_code,403);self.assertEqual(User.objects.filter(email=child.email).count(),1)
    def test_existing_account_never_bound_by_claim(self):
        aid=self.request();self.approve(aid);token=self.post(f'/me/guardian/authorizations/{aid}/claim-capability',{}).json()['capability']
        r=self.post(f'/me/guardian/authorizations/{aid}/claim',{'email':self.guardian.email,'password':PASS,'display_name':'Do not change','password_purpose_consent':True,'password_purpose_version':'password-account-v1'},HTTP_X_GUARDIAN_CLAIM=token)
        self.assertEqual(r.status_code,202,r.content);self.assertEqual(r.json(),{'status':'delivery_pending'});row=GuardianAuthorization.objects.get(pk=aid);self.assertIsNone(row.child_id);self.assertTrue(row.claimed_at);self.assertEqual(row.claim_sha256,'')
    def test_withdrawal_stops_managed_session_and_fresh_review_renews(self):
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);cc=self.client_for(child)
        row=GuardianAuthorization.objects.get(pk=aid)
        self.assertEqual(self.post(f'/me/guardian/authorizations/{aid}/withdraw',{'expected_version':row.version}).status_code,200)
        self.assertIsNone(cc.get('/api/v1/session').json()['member'])
        renewed=self.request(source=aid);self.assertFalse(self.parent.get(f'/api/v1/me/guardian/authorizations/{renewed}').json()['status']=='authorized')
        self.approve(renewed);self.client_for(User.objects.get(pk=child.pk))
    def test_scoped_export_uses_real_worker_and_revocation_blocks_download(self):
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);access=self.request('privacy_access',aid);self.approve(access)
        r=self.post(f'/me/guardian/authorizations/{access}/privacy-requests',{'kind':'export','confirm':True});self.assertEqual(r.status_code,202,r.content)
        job=OutboxJob.objects.get(pk=r.json()['privacy_request_id']);job.status='claimed';job.lease_owner='fixture-worker';job.locked_until=timezone.now()+timedelta(minutes=1);job.save()
        result=services.process_outbox_job(job);job.refresh_from_db();job.result=result;job.status='done';job.completed_at=timezone.now();job.save()
        from library import storage
        exported=json.loads(storage._local_path(result['storage_key']).read_text());self.assertEqual(set(exported),{'schema_version','profile'});self.assertEqual(exported['profile']['email'],child.email)
        url=f'/me/guardian/authorizations/{access}/privacy-requests/{job.id}/download';self.assertEqual(self.post(url,{}).status_code,200)
        row=GuardianAuthorization.objects.get(pk=access);self.assertEqual(self.post(f'/me/guardian/authorizations/{access}/withdraw',{'expected_version':row.version}).status_code,200)
        self.assertEqual(self.post(url,{}).status_code,403)
    def test_revoked_queue_never_processes_and_holds_still_apply(self):
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);delete=self.request('privacy_delete',aid);self.approve(delete)
        r=self.post(f'/me/guardian/authorizations/{delete}/privacy-requests',{'kind':'delete','confirm':True});self.assertEqual(r.status_code,202,r.content);job=OutboxJob.objects.get(pk=r.json()['privacy_request_id'])
        AuditEvent.objects.create(actor=child,action='legal.hold',entity_kind='User',entity_id=str(child.pk))
        from core.api import DomainError
        with self.assertRaises(DomainError) as e:services.process_outbox_job(job)
        self.assertEqual(e.exception.code,'privacy_hold');child.refresh_from_db();self.assertTrue(child.is_active)
        row=GuardianAuthorization.objects.get(pk=delete);self.post(f'/me/guardian/authorizations/{delete}/withdraw',{'expected_version':row.version})
        with self.assertRaises(DomainError):services.process_outbox_job(job)
    def test_retention_preview_apply_and_holds_preserve_records(self):
        aid=self.request();row=GuardianAuthorization.objects.get(pk=aid);GuardianAuthorization.objects.filter(pk=aid).update(expires_at=timezone.now()-timedelta(days=2),retain_until=timezone.now()-timedelta(days=1))
        self.assertEqual(cleanup_account_retention()['eligible']['guardian_authorizations'],1);self.assertTrue(GuardianAuthorization.objects.filter(pk=aid).exists())
        AuditEvent.objects.create(actor=self.guardian,action='legal.hold',entity_kind='GuardianAuthorization',entity_id=aid)
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['guardian_authorizations'],0)
        AuditEvent.objects.filter(action='legal.hold').delete();self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['guardian_authorizations'],1)
    def test_default_off_and_unqualified_policy_never_collect(self):
        with override_settings(GUARDIAN_AUTHORIZATION_ENABLED=False):self.assertEqual(self.post('/me/guardian/authorizations',{}).status_code,404)
        with override_settings(GUARDIAN_AUTHORIZATION_POLICIES={}):
            self.assertEqual(self.parent.get('/api/v1/me/guardian/policies').json()['items'],[])
            self.assertEqual(self.post('/me/guardian/authorizations',{'jurisdiction':'IN','purpose':'account_processing','notice_version':'notice-v1','method':'synthetic-manual-v1'}).status_code,409)

    def test_real_deletion_completes_with_minimal_guardian_status(self):
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);delete=self.request('privacy_delete',aid);self.approve(delete)
        r=self.post(f'/me/guardian/authorizations/{delete}/privacy-requests',{'kind':'delete','confirm':True});job=OutboxJob.objects.get(pk=r.json()['privacy_request_id'])
        result=services.process_outbox_job(job);job.refresh_from_db();job.result=result;job.status='done';job.completed_at=timezone.now();job.save()
        child.refresh_from_db();self.assertFalse(child.is_active);self.assertTrue(child.email.endswith('@invalid.local'))
        self.assertEqual(GuardianAuthorization.objects.get(pk=delete).evidence_sha256,'')
        r=self.parent.get(f'/api/v1/me/guardian/authorizations/{delete}/privacy-requests/{job.pk}');self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['status'],'completed');self.assertNotIn('email',r.json())
    def test_expired_claim_and_actor_bound_pagination(self):
        first=self.request();second=self.request()
        r=self.parent.get('/api/v1/me/guardian/authorizations?limit=1');self.assertEqual(len(r.json()['items']),1);self.assertTrue(r.json()['has_more'])
        cursor=r.json()['next_cursor'];r=self.staff.get('/api/v1/me/guardian/authorizations',{'limit':'1','cursor':cursor});self.assertEqual(r.status_code,400)
        self.approve(first);token=self.post(f'/me/guardian/authorizations/{first}/claim-capability',{}).json()['capability']
        GuardianAuthorization.objects.filter(pk=first).update(claim_expires_at=timezone.now()-timedelta(seconds=1))
        r=self.parent.post(f'/api/v1/me/guardian/authorizations/{first}/claim','{invalid',content_type='application/json',HTTP_X_GUARDIAN_CLAIM=token);self.assertEqual(r.status_code,403)
        self.assertFalse(User.objects.filter(guardian_managed=True).exists())

    def test_expiry_suspends_devices_before_evidence_retention_and_rights_can_be_reviewed(self):
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);cc=self.client_for(child)
        GuardianAuthorization.objects.filter(pk=aid).update(expires_at=timezone.now()-timedelta(seconds=1),retain_until=timezone.now()+timedelta(days=1))
        self.assertEqual(cleanup_account_retention()['eligible']['guardian_accounts_suspended'],1)
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['guardian_accounts_suspended'],1)
        self.assertIsNone(cc.get('/api/v1/session').json()['member'])
        access=self.request('privacy_access',aid)
        self.assertEqual(self.post(f'/me/guardian/authorizations/{access}/privacy-requests',{'kind':'export','confirm':True}).status_code,403)
        self.approve(access)
        self.assertEqual(self.post(f'/me/guardian/authorizations/{access}/privacy-requests',{'kind':'export','confirm':True}).status_code,202)


    def test_withdraw_during_upload_leaves_referenced_private_artifact_without_delivery(self):
        from unittest.mock import patch
        from library import storage
        from core.api import DomainError
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);access=self.request('privacy_access',aid);self.approve(access)
        r=self.post(f'/me/guardian/authorizations/{access}/privacy-requests',{'kind':'export','confirm':True});job=OutboxJob.objects.get(pk=r.json()['privacy_request_id'])
        job.status='claimed';job.lease_owner='fixture-worker';job.save()
        original=storage.put_private_file
        def put(*args,**kwargs):
            result=original(*args,**kwargs)
            row=GuardianAuthorization.objects.get(pk=access)
            self.assertEqual(self.post(f'/me/guardian/authorizations/{access}/withdraw',{'expected_version':row.version}).status_code,200)
            return result
        with patch.object(storage,'put_private_file',side_effect=put),self.assertRaises(DomainError):services.process_outbox_job(job)
        job.refresh_from_db();prepared=job.payload['prepared_export'];self.assertTrue(storage.private_exists(prepared['storage_key']))
        self.assertIn(prepared['storage_key'],job.payload['export_keys'])
        self.assertEqual(self.post(f'/me/guardian/authorizations/{access}/privacy-requests/{job.pk}/download',{}).status_code,403)

    def test_provider_cleanup_retries_after_committed_erasure_and_revoked_authority(self):
        from unittest.mock import patch
        from library import storage
        from core.api import DomainError
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);delete=self.request('privacy_delete',aid);self.approve(delete)
        key=f'exports/{child.public_id}/original-cleanup-fixture.json';storage.put_private(key,b'{}','application/json')
        OutboxJob.objects.create(kind='privacy_export',actor=child,status='done',dedupe_key='original-cleanup-existing-export',not_before=timezone.now(),payload={},result={'storage_key':key})
        r=self.post(f'/me/guardian/authorizations/{delete}/privacy-requests',{'kind':'delete','confirm':True});job=OutboxJob.objects.get(pk=r.json()['privacy_request_id'])
        with patch.object(storage,'delete_private',side_effect=DomainError('temporary_storage_failure','Original fixture failure.',503)),self.assertRaises(DomainError):services.process_outbox_job(job)
        child.refresh_from_db();self.assertFalse(child.is_active)
        job.refresh_from_db();self.assertIn(key,job.payload['delete_export_keys']);self.assertEqual(GuardianAuthorization.objects.get(pk=delete).status,'withdrawn')
        result=services.process_outbox_job(job);self.assertEqual(result['status'],'anonymised');self.assertFalse(storage.private_exists(key))


    def test_guardian_erasure_revokes_managed_child_sessions(self):
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);cc=self.client_for(child)
        job=OutboxJob.objects.create(kind='privacy_delete',actor=self.guardian,dedupe_key='original-guardian-delete',not_before=timezone.now(),payload={'session_epoch':self.guardian.session_epoch})
        result=services.process_outbox_job(job);self.assertEqual(result['status'],'anonymised')
        self.assertIsNone(cc.get('/api/v1/session').json()['member'])
        row=GuardianAuthorization.objects.get(pk=aid);self.assertEqual(row.status,'withdrawn');self.assertEqual(row.evidence_sha256,'')


    def test_completed_job_hold_preserves_its_authorization_evidence(self):
        aid=self.request();GuardianAuthorization.objects.filter(pk=aid).update(expires_at=timezone.now()-timedelta(days=2),retain_until=timezone.now()-timedelta(days=1))
        job=OutboxJob.objects.create(kind='privacy_export',actor=self.guardian,status='done',dedupe_key='original-guardian-related-hold',not_before=timezone.now(),payload={'guardian_authorization_id':aid})
        hold=AuditEvent.objects.create(action='legal.hold',entity_kind='OutboxJob',entity_id=str(job.pk))
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['guardian_authorizations'],0)
        self.assertTrue(GuardianAuthorization.objects.filter(pk=aid).exists());hold.delete()
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['guardian_authorizations'],1)


from django.test import TransactionTestCase
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections,connections


@override_settings(LOCAL=True,GUARDIAN_AUTHORIZATION_ENABLED=True,GUARDIAN_AUTHORIZATION_POLICIES=POLICIES,STAFF_MFA_REQUIRED=True)
class GuardianClaimConcurrencyTests(TransactionTestCase):
    setUp=GuardianJourneyTests.setUp
    client_for=GuardianJourneyTests.client_for
    post=GuardianJourneyTests.post
    request=GuardianJourneyTests.request
    approve=GuardianJourneyTests.approve

    def test_two_simultaneous_claims_create_exactly_one_bound_child(self):
        aid=self.request();self.approve(aid)
        token=self.post(f'/me/guardian/authorizations/{aid}/claim-capability',{}).json()['capability']
        cookies=dict((k,v.value) for k,v in self.parent.cookies.items());barrier=Barrier(2)
        def run(index):
            close_old_connections()
            try:
                c=Client()
                for k,v in cookies.items():c.cookies[k]=v
                barrier.wait(timeout=10)
                r=c.post(f'/api/v1/me/guardian/authorizations/{aid}/claim',{'email':f'concurrent-child-{index}@example.test','password':PASS,'display_name':'Original concurrency fixture','password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json',HTTP_X_GUARDIAN_CLAIM=token)
                return r.status_code
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(run,[1,2]))
        self.assertEqual(sorted(statuses),[202,403]);self.assertEqual(User.objects.filter(guardian_managed=True).count(),1)
        row=GuardianAuthorization.objects.get(pk=aid);self.assertTrue(row.child_id);self.assertEqual(row.claim_sha256,'')
