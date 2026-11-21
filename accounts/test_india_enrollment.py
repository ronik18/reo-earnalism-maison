"""Real PostgreSQL direct-declaration/subject-binding tests; no identity vendors."""
import json,uuid
from datetime import timedelta,datetime,timezone as datetime_timezone
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from core.models import AuditEvent,OperationReceipt,OutboxJob
from core.api import DomainError
from .models import User,GuardianAuthorization,EmailActionToken,Device,RateLimitBucket
from . import guardian,services
from .test_guardian_journey import GuardianJourneyTests,PASS
from .test_google import GoogleOIDCAcceptanceTests,CALLBACK
from .retention import cleanup_account_retention

ADULT={'account_capacity':'adult','account_notice_version':'india-account-v1','account_terms_consent':True}
PARENT={'parent_declared_adult':True,'guardian_permission':True,'account_notice_version':'india-account-v1','account_terms_consent':True}
PASSWORD={'password_purpose_consent':True,'password_purpose_version':'password-account-v1'}
POLICY={'enabled':True,'public_enabled':True,'lifetime':'until_withdrawn','record_retention_seconds':604800,'legal_review_ref':'india-direct-electronic-current-assessment','collection_route_ref':'india-first-qualified-recipient-notice'}
POLICIES={'IN:account_processing:india-parent-v1:india-parent-electronic-v1':POLICY}


@override_settings(LOCAL=True,INDIA_FIRST_LAUNCH_ENABLED=True,GUARDIAN_AUTHORIZATION_ENABLED=True,GUARDIAN_AUTHORIZATION_POLICIES=POLICIES)
class IndiaEnrollmentTests(TestCase):
    setUp=GuardianJourneyTests.setUp
    client_for=GuardianJourneyTests.client_for
    post=GuardianJourneyTests.post

    def request_permission(self,**overrides):
        d={'jurisdiction':'IN','purpose':'account_processing','notice_version':'india-parent-v1','method':'india-parent-electronic-v1',**PARENT,**overrides}
        return self.post('/me/guardian/authorizations',d)

    def child(self):
        r=self.request_permission();self.assertEqual(r.status_code,201,r.content);aid=r.json()['authorization_id'];prospect=r.json()['prospective_subject_id']
        token=self.post(f'/me/guardian/authorizations/{aid}/claim-capability',{}).json()['capability']
        d={'email':'india-reader@example.test','password':PASS,'display_name':'Private reader',**PASSWORD,'subject_confirmed':prospect,'guardian_permission':True,'account_notice_version':'india-account-v1'}
        r=self.post(f'/me/guardian/authorizations/{aid}/claim',d,HTTP_X_GUARDIAN_CLAIM=token);self.assertEqual(r.status_code,202,r.content)
        child=User.objects.get(email=d['email']);return aid,child,token,d

    def test_signup_strict_declaration_rejects_before_email_or_password_processing(self):
        data={'email':'new-india@example.test','password':PASS,'display_name':'Adult',**PASSWORD}
        for change in ({},{**ADULT,'account_terms_consent':'true'},{**ADULT,'account_capacity':'minor'},{**ADULT,'account_notice_version':'old'}):
            RateLimitBucket.objects.all().delete() # Separate invalid-input cases from the independently tested IP budget.
            with patch('accounts.services._email',side_effect=AssertionError('No account identity before declaration')):
                r=self.client.post('/api/v1/auth/register',{**data,**change},content_type='application/json')
            self.assertEqual(r.status_code,422,r.content);self.assertEqual(r.json()['code'],'account_permission_required')
        self.assertFalse(User.objects.filter(email=data['email']).exists())
        RateLimitBucket.objects.all().delete()
        r=self.client.post('/api/v1/auth/register',{**data,**ADULT},content_type='application/json');self.assertEqual(r.status_code,202,r.content)
        user=User.objects.get(email=data['email']);self.assertFalse(user.guardian_managed)
        event=AuditEvent.objects.get(actor=user,action='account.capacity_declared');self.assertEqual(event.detail['assurance'],'self_declaration')
        self.assertEqual(event.detail['purpose'],'registration')

    def test_parent_permission_is_direct_not_fake_staff_review_and_no_child_data(self):
        for field in PARENT:
            d={field:False} if field!='account_notice_version' else {field:'old'}
            r=self.request_permission(**d);self.assertEqual(r.status_code,422,r.content)
        self.assertFalse(GuardianAuthorization.objects.exists())
        r=self.request_permission();self.assertEqual(r.status_code,201,r.content);row=GuardianAuthorization.objects.get(pk=r.json()['authorization_id'])
        self.assertEqual(row.status,'authorized');self.assertIsNone(row.reviewer_id);self.assertIsNone(row.child_id)
        self.assertLessEqual(row.expires_at,timezone.now()+timedelta(days=7));self.assertIsNotNone(row.retain_until)
        self.assertEqual(row.evidence_sha256,guardian._direct_evidence(row));guardian._current(row)
        self.assertTrue(AuditEvent.objects.filter(actor=self.guardian,action='guardian.electronic_permission',entity_id=str(row.pk)).exists())
        self.assertFalse(User.objects.filter(guardian_managed=True).exists())
        self.assertFalse(OutboxJob.objects.filter(actor=self.guardian).exists())

    def test_missing_or_tampered_actual_permission_proof_cannot_authorize(self):
        r=self.request_permission();row=GuardianAuthorization.objects.get(pk=r.json()['authorization_id'])
        AuditEvent.objects.filter(action='guardian.electronic_permission',entity_id=str(row.pk)).delete()
        with self.assertRaises(DomainError) as e:guardian._current(row)
        self.assertEqual(e.exception.code,'guardian_authority_unavailable')
        self.assertEqual(self.post(f'/me/guardian/authorizations/{row.pk}/claim-capability',{}).status_code,403)

    def test_claim_requires_current_permission_exact_subject_and_one_time_capability(self):
        r=self.request_permission();aid=r.json()['authorization_id'];subject=r.json()['prospective_subject_id']
        token=self.post(f'/me/guardian/authorizations/{aid}/claim-capability',{}).json()['capability']
        d={'email':'unbound-india@example.test','password':PASS,'display_name':'Reader',**PASSWORD,'subject_confirmed':subject,'guardian_permission':True,'account_notice_version':'india-account-v1'}
        for override in ({'subject_confirmed':str(uuid.uuid4())},{'guardian_permission':'true'},{'account_notice_version':'old'}):
            with patch('accounts.services.register_member',side_effect=AssertionError('Cannot persist unbound child')):
                r=self.post(f'/me/guardian/authorizations/{aid}/claim',{**d,**override},HTTP_X_GUARDIAN_CLAIM=token)
            self.assertEqual(r.status_code,422,r.content)
        r=self.post(f'/me/guardian/authorizations/{aid}/claim',d,HTTP_X_GUARDIAN_CLAIM=token);self.assertEqual(r.status_code,202,r.content)
        child=User.objects.get(email=d['email']);self.assertTrue(child.guardian_managed);self.assertFalse(child.is_verified)
        row=GuardianAuthorization.objects.get(pk=aid);self.assertNotEqual(row.expires_at.year,9999);self.assertIsNotNone(row.retain_until)
        event=AuditEvent.objects.get(action='guardian.subject_bound',entity_id=aid);self.assertEqual(event.detail['prospective_subject_id'],subject)
        self.assertNotIn(child.email,json.dumps(event.detail));self.assertNotIn(token,json.dumps(list(OperationReceipt.objects.values('response'))))
        self.assertEqual(self.post(f'/me/guardian/authorizations/{aid}/claim',d,HTTP_X_GUARDIAN_CLAIM=token).status_code,403)
        with self.assertRaises(DomainError):services.login_member(self.parent.get('/api/v1/session').wsgi_request,email=child.email,password=PASS)

    def test_actual_mailbox_verification_then_withdrawal_revokes_managed_device(self):
        aid,child,_,_=self.child();action=EmailActionToken.objects.get(user=child,purpose='verify_email')
        services.confirm_email_verification(services._token_value(action));child.refresh_from_db();self.assertTrue(child.is_verified)
        row=GuardianAuthorization.objects.get(pk=aid);self.assertEqual(row.expires_at.year,9999);self.assertIsNone(guardian._data(row)['expires_at']);self.assertIsNone(row.retain_until)
        cc=self.client_for(child);self.assertTrue(cc.get('/api/v1/session').json()['authenticated'])
        row=GuardianAuthorization.objects.get(pk=aid)
        r=self.post(f'/me/guardian/authorizations/{aid}/withdraw',{'expected_version':row.version});self.assertEqual(r.status_code,200,r.content)
        row.refresh_from_db();self.assertLessEqual(row.expires_at,timezone.now());self.assertIsNotNone(row.retain_until)
        self.assertFalse(cc.get('/api/v1/session').json()['authenticated']);self.assertFalse(Device.objects.filter(user=child,revoked_at=None).exists())

    def test_permission_does_not_autoauthorize_parent_export_or_delete(self):
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified'])
        for purpose in ['privacy_access','privacy_delete']:
            r=self.request_permission(purpose=purpose,source_authorization_id=aid)
            self.assertEqual(r.status_code,409,r.content)
        r=self.post(f'/me/guardian/authorizations/{aid}/privacy-requests',{'kind':'export','confirm':True})
        self.assertEqual(r.status_code,403,r.content);self.assertFalse(OutboxJob.objects.filter(kind='privacy_export').exists())

    def test_independent_capacity_preserves_same_account_and_ends_old_guardian_power(self):
        aid,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified']);cc=self.client_for(child)
        pk=child.pk;row=GuardianAuthorization.objects.get(pk=aid)
        GuardianAuthorization.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(days=1))
        self.assertFalse(cc.get('/api/v1/session').json()['authenticated'])
        d={'email':child.email,'password':PASS,**PASSWORD,**ADULT}
        r=self.client.post('/api/v1/auth/account-capacity',d,content_type='application/json');self.assertEqual(r.status_code,202,r.content)
        child.refresh_from_db();self.assertEqual(child.pk,pk);self.assertFalse(child.guardian_managed)
        row.refresh_from_db();self.assertEqual(row.status,'withdrawn');self.assertIsNotNone(row.retain_until)
        self.assertTrue(self.client_for(child).get('/api/v1/session').json()['authenticated'])
        self.assertEqual(self.request_permission(source_authorization_id=aid).status_code,403)
        self.assertEqual(self.parent.get(f'/api/v1/me/guardian/authorizations/{aid}').json()['status'],'withdrawn')
        self.assertTrue(AuditEvent.objects.filter(actor=child,action='account.independent_capacity').exists())

    def test_independence_wrong_unknown_credentials_are_uniform_and_child_unchanged(self):
        _,child,_,_=self.child();child.is_verified=True;child.save(update_fields=['is_verified'])
        responses=[]
        for email in [child.email,'unknown-india@example.test']:
            r=self.client.post('/api/v1/auth/account-capacity',{'email':email,'password':'Wrong-Independent-Passphrase',**PASSWORD,**ADULT},content_type='application/json')
            self.assertEqual(r.status_code,403);responses.append(r.json()['code'])
        self.assertEqual(responses,['invalid_credentials','invalid_credentials']);child.refresh_from_db();self.assertTrue(child.guardian_managed)

    def test_independent_ssr_and_api_share_ip_budget_when_emails_rotate(self):
        RateLimitBucket.objects.all().delete()
        with patch('django.contrib.auth.authenticate',return_value=None):
            for number in range(30):
                route='/en/independent-account/' if number%2 else '/api/v1/auth/account-capacity'
                d={'email':f'unknown-capacity-{number}@example.test','password':PASS,**PASSWORD,**ADULT}
                if route.startswith('/api/'):
                    r=self.client.post(route,d,content_type='application/json')
                else:
                    d.update(password_purpose_consent='on',account_terms_consent='on')
                    r=self.client.post(route,d)
                self.assertEqual(r.status_code,403,r.content)
            r=self.client.post('/en/independent-account/',{'email':'unknown-capacity-last@example.test','password':PASS,**PASSWORD,**ADULT,'password_purpose_consent':'on','account_terms_consent':'on'})
            self.assertEqual(r.status_code,429,r.content);self.assertIn('RateLimit-Limit',r)
        self.assertFalse(User.objects.filter(email__startswith='unknown-capacity-').exists())

    def test_unclaimed_permissions_expire_and_cleanup_without_parent_or_child_erasure(self):
        r=self.request_permission();row=GuardianAuthorization.objects.get(pk=r.json()['authorization_id'])
        GuardianAuthorization.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(days=8),retain_until=timezone.now()-timedelta(days=1))
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['guardian_authorizations'],1)
        self.assertTrue(User.objects.filter(pk=self.guardian.pk,is_active=True).exists());self.assertFalse(User.objects.filter(guardian_managed=True).exists())

    def test_active_permission_proof_survives_security_audit_cleanup_and_tampering_fails(self):
        aid,child,_,_=self.child()
        action=EmailActionToken.objects.get(user=child,purpose='verify_email');services.confirm_email_verification(services._token_value(action))
        event=AuditEvent.objects.get(action='guardian.electronic_permission',entity_id=aid)
        AuditEvent.objects.filter(pk=event.pk).update(created_at=timezone.now()-timedelta(days=400))
        cleanup_account_retention(dry_run=False)
        self.assertTrue(AuditEvent.objects.filter(pk=event.pk).exists())
        row=GuardianAuthorization.objects.get(pk=aid);guardian._current(row)
        detail=event.detail;detail['guardian_permission']=False
        AuditEvent.objects.filter(pk=event.pk).update(detail=detail)
        with self.assertRaises(DomainError):guardian._current(row)

    def test_expired_or_unbound_permission_is_not_revived_by_actual_email_verification(self):
        aid,child,_,_=self.child();row=GuardianAuthorization.objects.get(pk=aid)
        expired=timezone.now()-timedelta(minutes=1)
        GuardianAuthorization.objects.filter(pk=aid).update(expires_at=expired)
        action=EmailActionToken.objects.get(user=child,purpose='verify_email')
        services.confirm_email_verification(services._token_value(action));child.refresh_from_db();row.refresh_from_db()
        self.assertTrue(child.is_verified);self.assertEqual(row.expires_at,expired);self.assertFalse(guardian.account_available(child))
        # A new affirmative permission over the exact owned verified relation works.
        r=self.request_permission(source_authorization_id=aid);self.assertEqual(r.status_code,201,r.content)
        fresh=GuardianAuthorization.objects.get(pk=r.json()['authorization_id']);self.assertEqual(fresh.expires_at.year,9999)
        guardian._current(fresh)
        AuditEvent.objects.filter(action='guardian.subject_bound',entity_id=str(fresh.pk)).delete()
        with self.assertRaises(DomainError):guardian._current(fresh)

    def test_parent_renews_only_exact_owned_unverified_relation_without_duplicate_child(self):
        aid,child,_,_=self.child()
        original=EmailActionToken.objects.get(user=child,purpose='verify_email')
        GuardianAuthorization.objects.filter(pk=aid).update(expires_at=timezone.now()-timedelta(minutes=1))
        r=self.request_permission(source_authorization_id=aid);self.assertEqual(r.status_code,201,r.content)
        row=GuardianAuthorization.objects.get(pk=r.json()['authorization_id'])
        self.assertTrue(r.json()['claim_submitted']);self.assertFalse(r.json()['child_bound'])
        self.assertEqual(row.child_id,child.pk);self.assertNotEqual(row.expires_at.year,9999)
        self.assertEqual(User.objects.filter(email=child.email).count(),1)
        original.refresh_from_db();self.assertIsNotNone(original.consumed_at)
        action=EmailActionToken.objects.get(user=child,purpose='verify_email',consumed_at=None);services.confirm_email_verification(services._token_value(action))
        row.refresh_from_db();self.assertEqual(row.expires_at.year,9999)

    def test_expired_unverified_claim_scaffolding_is_removed_after_permission_retention(self):
        from .models import Preferences,Consent
        aid,child,_,_=self.child();old=timezone.now()-timedelta(days=30)
        User.objects.filter(pk=child.pk).update(date_joined=old)
        Preferences.objects.filter(user=child).update(updated_at=old);Consent.objects.filter(user=child).update(updated_at=old)
        for event in AuditEvent.objects.filter(actor=child):
            detail=event.detail
            if event.action=='password.purpose_consented':detail['collected_at']=old.isoformat()
            AuditEvent.objects.filter(pk=event.pk).update(created_at=old+timedelta(seconds=1),detail=detail)
        EmailActionToken.objects.filter(user=child).update(created_at=old,expires_at=old+timedelta(days=1))
        for job in OutboxJob.objects.filter(actor=child):
            payload={**job.payload,'email_outcome':'submitted'}
            OutboxJob.objects.filter(pk=job.pk).update(status='done',payload=payload,result={'status':'submitted'},completed_at=old+timedelta(seconds=1))
        GuardianAuthorization.objects.filter(pk=aid).update(expires_at=old+timedelta(days=7),retain_until=old+timedelta(days=14))
        report=cleanup_account_retention(dry_run=False)['eligible']
        self.assertEqual(report['guardian_authorizations'],1);self.assertEqual(report['abandoned_signups'],1)
        self.assertFalse(User.objects.filter(pk=child.pk).exists());self.assertTrue(User.objects.filter(pk=self.guardian.pk).exists())
        self.assertTrue(all(event.detail=={'retention_cleaned':True} for event in AuditEvent.objects.filter(entity_kind='GuardianAuthorization',entity_id=aid,action__in=['guardian.electronic_permission','guardian.subject_bound'])))

    def test_own_privacy_delete_ends_indefinite_permission_then_hold_aware_proof_cleanup(self):
        from .privacy import delete_account
        aid,child,_,_=self.child()
        action=EmailActionToken.objects.get(user=child,purpose='verify_email');services.confirm_email_verification(services._token_value(action))
        child.refresh_from_db()
        job=OutboxJob.objects.create(actor=child,kind='privacy_delete',dedupe_key=str(uuid.uuid4()),payload={'session_epoch':child.session_epoch},not_before=timezone.now())
        result=delete_account(job);self.assertEqual(result['status'],'anonymised')
        row=GuardianAuthorization.objects.get(pk=aid);self.assertEqual(row.status,'withdrawn');self.assertLessEqual(row.expires_at,timezone.now());self.assertIsNotNone(row.retain_until)
        proof=AuditEvent.objects.get(action='guardian.electronic_permission',entity_id=aid)
        GuardianAuthorization.objects.filter(pk=aid).update(expires_at=timezone.now()-timedelta(days=8),retain_until=timezone.now()-timedelta(days=1))
        hold=AuditEvent.objects.create(actor=self.guardian,action='legal.hold',entity_kind='AuditEvent',entity_id=str(proof.pk))
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['guardian_authorizations'],0)
        proof.refresh_from_db();self.assertIn('guardian_permission',proof.detail)
        hold.delete()
        self.assertEqual(cleanup_account_retention(dry_run=False)['eligible']['guardian_authorizations'],1)
        proof.refresh_from_db();self.assertEqual(proof.detail,{'retention_cleaned':True})


@override_settings(INDIA_FIRST_LAUNCH_ENABLED=True)
class IndiaGoogleEnrollmentTests(TestCase):
    setUp=GoogleOIDCAcceptanceTests.setUp
    claims=GoogleOIDCAcceptanceTests.claims
    provider=GoogleOIDCAcceptanceTests.provider
    finish=GoogleOIDCAcceptanceTests.finish

    @classmethod
    def setUpTestData(cls):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'India synthetic OIDC')]);now=datetime.now(datetime_timezone.utc)
        cls.cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(cls.key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).sign(cls.key,hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode())

    def start(self,**extra):
        r=self.client.get('/api/v1/auth/google',{'intent':'sign_in','return_path':'/en/vault/',**extra},HTTP_HOST='localhost')
        self.assertEqual(r.status_code,302,r.content)
        return {k:v[0] for k,v in parse_qs(urlsplit(r['Location']).query).items()}

    def test_default_google_login_never_creates_unclassified_user(self):
        params=self.start();r,_=self.finish(params);self.assertEqual(r.status_code,403,r.content)
        self.assertFalse(User.objects.filter(email='google-member@example.test').exists())
        from allauth.socialaccount.models import SocialAccount
        self.assertFalse(SocialAccount.objects.exists())

    def test_google_signup_requires_declaration_before_provider_redirect_and_records_it(self):
        with patch('accounts.google.get_adapter',side_effect=AssertionError('No provider flow before permission')):
            r=self.client.get('/api/v1/auth/google',{'create_account':'true','intent':'sign_in'},HTTP_HOST='localhost')
        self.assertEqual(r.status_code,422,r.content)
        params=self.start(create_account='true',**{**ADULT,'account_terms_consent':'true'})
        r,_=self.finish(params);self.assertEqual(r.status_code,302,r.content)
        user=User.objects.get(email='google-member@example.test')
        self.assertTrue(AuditEvent.objects.filter(actor=user,action='account.capacity_declared',detail__purpose='google_registration').exists())
        # A returning linked adult can sign in with the existing-account action.
        self.client.post('/api/v1/session',HTTP_HOST='localhost')
        params=self.start();r,_=self.finish(params);self.assertEqual(r.status_code,302,r.content)
        self.assertEqual(User.objects.filter(pk=user.pk).count(),1)
