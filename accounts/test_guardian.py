"""Synthetic operational policies only: these fixtures qualify no legal method."""
import uuid
from datetime import timedelta
from django.test import TestCase,Client,RequestFactory,override_settings
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from core.api import DomainError
from core.models import OperationReceipt
from .models import User,GuardianAuthorization,Device
from . import guardian

POLICY={'IN:privacy_access:notice-v1:synthetic-manual-v1':{'enabled':True,'max_lifetime_seconds':3600}}
PASS='Original-Guardian-Fixture-47'


@override_settings(LOCAL=True,GUARDIAN_AUTHORIZATION_ENABLED=True,GUARDIAN_AUTHORIZATION_POLICIES=POLICY,STAFF_MFA_REQUIRED=True)
class GuardianFoundationTests(TestCase):
    def setUp(self):
        self.child=User.objects.create_user('original-child@example.test',PASS,is_verified=True)
        self.guardian=User.objects.create_user('original-guardian@example.test',PASS,is_verified=True)
        self.reviewer=User.objects.create_superuser('original-reviewer@example.test',PASS)
        self.review_request=self.request(self.reviewer,mfa=True)
        self.guardian_request=self.request(self.guardian)
    def request(self,user,mfa=False):
        client=Client();response=client.post('/api/v1/auth/login',{'email':user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        if mfa:
            otp=TOTPDevice.objects.create(user=user,confirmed=True)
            session=client.session;session['otp_device_id']=otp.persistent_id;session.save()
        return client.get('/api/v1/session').wsgi_request
    def prepare(self,request=None,key=None,**changes):
        data={'jurisdiction':'IN','purpose':'privacy_access','notice_version':'notice-v1','method':'synthetic-manual-v1','operation_id':key or uuid.uuid4()};data.update(changes)
        return guardian.prepare(request or self.review_request,self.child.pk,self.guardian.pk,**data)
    def authorize(self):
        _,data=self.prepare();row=GuardianAuthorization.objects.get(pk=data['authorization_id'])
        guardian.review(self.review_request,row.pk,evidence_sha256='a'*64,approve=True,expected_version=1,operation_id=uuid.uuid4())
        row.refresh_from_db();return row
    def require(self,row,request=None,**changes):
        data={'child_id':self.child.pk,'jurisdiction':'IN','purpose':'privacy_access','notice_version':'notice-v1'};data.update(changes)
        return guardian.require_authority(request or self.guardian_request,row.pk,**data)
    def test_disabled_and_empty_policy_never_create_or_receipt(self):
        for settings in ({'GUARDIAN_AUTHORIZATION_ENABLED':False},{'GUARDIAN_AUTHORIZATION_POLICIES':{}}):
            with override_settings(**settings),self.assertRaises(DomainError):self.prepare()
        self.assertFalse(GuardianAuthorization.objects.exists());self.assertFalse(OperationReceipt.objects.exists())
    def test_operational_authorization_and_replay_bound_to_exact_purpose_notice_subject_region(self):
        key=uuid.uuid4();first=self.prepare(key=key);self.assertEqual(first,self.prepare(key=key));self.assertTrue(self.prepare(key=key).replayed)
        row=GuardianAuthorization.objects.get(pk=first[1]['authorization_id'])
        with self.assertRaises(DomainError):self.require(row)
        review_key=uuid.uuid4();kwargs={'evidence_sha256':'a'*64,'approve':True,'expected_version':1,'operation_id':review_key}
        result=guardian.review(self.review_request,row.pk,**kwargs);self.assertEqual(result,guardian.review(self.review_request,row.pk,**kwargs))
        self.assertTrue(self.require(row)['operational_only'])
        for changes in ({'purpose':'privacy_delete'},{'notice_version':'notice-v2'},{'child_id':self.guardian.pk},{'jurisdiction':'US'}):
            with self.subTest(changes=changes),self.assertRaises(DomainError):self.require(row,**changes)
        self.assertEqual(set(GuardianAuthorization.objects.get(pk=row.pk).evidence_sha256),{'a'})
    def test_unrelated_or_raw_unbound_actor_and_missing_mfa_cannot_review(self):
        for request in (self.guardian_request,self.request(self.reviewer),RequestFactory().get('/')):
            if not hasattr(request,'user'):request.user=self.reviewer
            with self.assertRaises(DomainError):self.prepare(request=request)
        self.assertFalse(GuardianAuthorization.objects.exists())
    def test_reviewer_cannot_be_guardian_or_child(self):
        with self.assertRaises(DomainError):
            guardian.prepare(self.review_request,self.child.pk,self.reviewer.pk,jurisdiction='IN',purpose='privacy_access',notice_version='notice-v1',method='synthetic-manual-v1',operation_id=uuid.uuid4())
    def test_current_permission_and_device_revocation_are_checked(self):
        User.objects.filter(pk=self.reviewer.pk).update(is_staff=False)
        with self.assertRaises(DomainError):self.prepare()
        User.objects.filter(pk=self.reviewer.pk).update(is_staff=True)
        Device.objects.filter(pk=self.review_request.device.pk).update(revoked_at=timezone.now())
        with self.assertRaises(DomainError):self.prepare()
        self.assertFalse(OperationReceipt.objects.exists())
    def test_expiry_withdrawal_and_policy_change_invalidate_authority_and_old_receipts(self):
        key=uuid.uuid4();prepared=self.prepare(key=key);row=GuardianAuthorization.objects.get(pk=prepared[1]['authorization_id'])
        review_key=uuid.uuid4();args={'evidence_sha256':'b'*64,'approve':True,'expected_version':1,'operation_id':review_key}
        guardian.review(self.review_request,row.pk,**args)
        changed={next(iter(POLICY)):{'enabled':True,'max_lifetime_seconds':1200}}
        with override_settings(GUARDIAN_AUTHORIZATION_POLICIES=changed):
            with self.assertRaises(DomainError):self.require(row)
            with self.assertRaises(DomainError):guardian.review(self.review_request,row.pk,**args)
        GuardianAuthorization.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(DomainError):self.require(row)
        with self.assertRaises(DomainError):self.prepare(key=key)
        GuardianAuthorization.objects.filter(pk=row.pk).update(expires_at=timezone.now()+timedelta(minutes=10))
        withdraw_key=uuid.uuid4();kwargs={'expected_version':2,'operation_id':withdraw_key}
        result=guardian.withdraw(self.guardian_request,row.pk,**kwargs)
        self.assertEqual(result,guardian.withdraw(self.guardian_request,row.pk,**kwargs))
        with self.assertRaises(DomainError):self.require(row)
        with self.assertRaises(DomainError):guardian.review(self.review_request,row.pk,**args)
    def test_subject_deactivation_or_unrelated_guardian_never_gets_authority(self):
        row=self.authorize()
        with self.assertRaises(DomainError):self.require(row,request=self.request(self.child))
        User.objects.filter(pk=self.child.pk).update(is_active=False)
        with self.assertRaises(DomainError):self.require(row)
    def test_reused_operation_input_and_bad_evidence_are_rejected(self):
        key=uuid.uuid4();data=self.prepare(key=key)[1]
        with self.assertRaises(DomainError):self.prepare(key=key,notice_version='different')
        with self.assertRaises(DomainError):guardian.review(self.review_request,data['authorization_id'],evidence_sha256='an email checkbox',approve=True,expected_version=1,operation_id=uuid.uuid4())
        self.assertEqual(GuardianAuthorization.objects.get(pk=data['authorization_id']).status,'pending')
    def test_no_public_guardian_endpoint_or_child_record_created_by_normal_signup(self):
        self.assertEqual(Client().post('/api/v1/guardian/authorizations',{},content_type='application/json').status_code,404)
        self.assertFalse(GuardianAuthorization.objects.exists())

    def test_reviewer_deletion_is_not_blocked_and_invalidates_remaining_grant(self):
        row=self.authorize();self.reviewer.delete()
        row.refresh_from_db();self.assertIsNone(row.reviewer_id)
        with self.assertRaises(DomainError):self.require(row)
    def test_subject_deletion_removes_operational_row_and_bad_jurisdiction_fails_closed(self):
        row=self.authorize();self.child.delete()
        self.assertFalse(GuardianAuthorization.objects.filter(pk=row.pk).exists())
        with self.assertRaises(DomainError):self.prepare(jurisdiction=[])

    def test_missing_record_prepare_receipt_and_unhashable_purpose_fail_controlled(self):
        key=uuid.uuid4();data=self.prepare(key=key)[1]
        GuardianAuthorization.objects.filter(pk=data['authorization_id']).delete()
        with self.assertRaises(DomainError) as denied:self.prepare(key=key)
        self.assertEqual(denied.exception.code,'guardian_authority_unavailable')
        with self.assertRaises(DomainError):self.prepare(purpose=[])
