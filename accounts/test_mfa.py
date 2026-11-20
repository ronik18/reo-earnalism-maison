import time,uuid
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from .models import User,MFARecoveryCode

PASS='Staff-MFA-Test-Passphrase-47'

@override_settings(STAFF_MFA_REQUIRED=True)
class StaffMFAAcceptanceTests(TestCase):
    def setUp(self):
        self.staff=User.objects.create_superuser('mfa-staff@example.test',PASS)
        self.client=Client(enforce_csrf_checks=True);self.login()
    def login(self):
        csrf=self.client.get('/api/v1/session').json()['csrf_token']
        response=self.client.post('/api/v1/auth/login',{'email':self.staff.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code,200,response.content);self.csrf=response.json()['csrf_token']
    def post(self,path,data):return self.client.post(path,data,content_type='application/json',HTTP_X_CSRFTOKEN=self.csrf)
    def enroll(self):
        response=self.post('/api/v1/me/mfa/totp',{});self.assertEqual(response.status_code,201,response.content);self.assertTrue(response.json()['configuration_uri'].startswith('otpauth://totp/'))
        device=TOTPDevice.objects.get(user=self.staff,confirmed=False)
        code=str(totp(device.bin_key,device.step,device.t0,device.digits,device.drift)).zfill(6)
        response=self.post('/api/v1/me/mfa/totp/confirm',{'token':code});self.assertEqual(response.status_code,200,response.content)
        return device,response.json()['recovery_codes'],code
    def test_staff_requires_mfa_and_does_not_corrupt_email_verification(self):
        path=f'/api/v1/staff/drafts/{uuid.uuid4()}/document'
        blocked=self.client.get(path);self.assertEqual(blocked.status_code,403);self.assertEqual(blocked.json()['code'],'mfa_required')
        self.assertEqual(self.client.get('/admin/').status_code,302)
        device,codes,token=self.enroll();self.assertEqual(len(codes),10)
        hashes=set(MFARecoveryCode.objects.filter(user=self.staff).values_list('code_sha256',flat=True));self.assertFalse(hashes & set(codes))
        self.assertEqual(self.client.get(path).status_code,404);self.assertEqual(self.client.get('/admin/').status_code,200)
        session=self.client.get('/api/v1/session').json();self.assertIs(session['member']['email_verified'],True)
        self.staff.refresh_from_db();self.assertIs(self.staff.is_verified,True)
        status=self.client.get('/api/v1/me/mfa/totp').json();self.assertTrue(status['session_verified']);self.assertNotIn('configuration_uri',status);self.assertNotIn('recovery_codes',status)
    def test_totp_replay_is_rejected_and_throttle_failure_persists(self):
        device,codes,token=self.enroll()
        result=self.post('/api/v1/me/mfa/verify',{'token':token});self.assertEqual(result.status_code,403)
        device.refresh_from_db();self.assertGreater(device.throttling_failure_count,0)
        stamp=time.time()+61
        with patch('time.time',return_value=stamp),patch('django_otp.oath.time',return_value=stamp),patch('django_otp.models.timezone.now',return_value=timezone.now()+timedelta(seconds=61)):
            code=str(totp(device.bin_key,device.step,device.t0,device.digits,device.drift)).zfill(6)
            response=self.post('/api/v1/me/mfa/verify',{'token':code});self.assertEqual(response.status_code,200,response.content)
    def test_recovery_code_is_single_use_and_requires_recent_password(self):
        device,codes,token=self.enroll();self.client.delete('/api/v1/session',HTTP_X_CSRFTOKEN=self.csrf);self.login()
        session=self.client.session;session['reauthenticated_at']=(timezone.now()-timedelta(minutes=6)).isoformat();session.save()
        self.assertEqual(self.post('/api/v1/me/mfa/recovery',{'code':codes[0]}).status_code,403)
        self.assertEqual(self.post('/api/v1/me/reauthenticate',{'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'}).status_code,200)
        response=self.post('/api/v1/me/mfa/recovery',{'code':codes[0]});self.assertEqual(response.status_code,200,response.content);self.assertEqual(response.json()['recovery_codes_remaining'],9)
        self.assertEqual(self.post('/api/v1/me/mfa/recovery',{'code':codes[0]}).status_code,403)
        self.assertEqual(MFARecoveryCode.objects.filter(user=self.staff,used_at__isnull=False).count(),1)

    def test_enrollment_cooldown_reports_retry_after_and_preserves_setup(self):
        response=self.post('/api/v1/me/mfa/totp',{})
        self.assertEqual(response.status_code,201,response.content)
        device=TOTPDevice.objects.get(user=self.staff,confirmed=False)
        original_key=device.key
        now=timezone.now()
        device.throttling_failure_count=5
        device.throttling_failure_timestamp=now
        device.save(update_fields=['throttling_failure_count','throttling_failure_timestamp'])
        with patch('django_otp.models.timezone.now',return_value=now):
            code=str(totp(device.bin_key,device.step,device.t0,device.digits,device.drift)).zfill(6)
            response=self.post('/api/v1/me/mfa/totp/confirm',{'token':code})
        self.assertEqual(response.status_code,429,response.content)
        self.assertEqual(response.json()['code'],'mfa_retry_later')
        self.assertEqual(response['Retry-After'],'16')
        device.refresh_from_db()
        self.assertFalse(device.confirmed)
        self.assertEqual(device.key,original_key)
        self.assertEqual(device.throttling_failure_count,5)
        self.assertEqual(device.last_t,-1)
        later=now+timedelta(seconds=17)
        with patch('time.time',return_value=later.timestamp()),patch('django_otp.oath.time',return_value=later.timestamp()),patch('django_otp.models.timezone.now',return_value=later):
            code=str(totp(device.bin_key,device.step,device.t0,device.digits,device.drift)).zfill(6)
            response=self.post('/api/v1/me/mfa/totp/confirm',{'token':code})
        self.assertEqual(response.status_code,200,response.content)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(device.key,original_key)
        self.assertEqual(device.throttling_failure_count,0)

    def test_existing_authenticator_cooldown_is_not_reported_as_invalid_code(self):
        device,_,_=self.enroll()
        now=timezone.now()
        device.throttling_failure_count=6
        device.throttling_failure_timestamp=now
        device.save(update_fields=['throttling_failure_count','throttling_failure_timestamp'])
        with patch('django_otp.models.timezone.now',return_value=now):
            response=self.post('/api/v1/me/mfa/verify',{'token':'000000'})
        self.assertEqual(response.status_code,429,response.content)
        self.assertEqual(response.json()['code'],'mfa_retry_later')
        self.assertEqual(response['Retry-After'],'32')
        device.refresh_from_db()
        self.assertEqual(device.throttling_failure_count,6)

    def test_stale_authority_cannot_enroll_confirm_verify_or_consume_recovery(self):
        from . import mfa
        from .models import Device
        from .services import _digest
        from core.api import DomainError
        from django.test import RequestFactory
        actor=self.client.get('/api/v1/session').wsgi_request.user
        device_id=self.client.session['device_id']
        original_epoch=self.staff.session_epoch
        for state in ('inactive','reset','revoked','demoted'):
            for action in ('enroll','confirm','verify','recover'):
                with self.subTest(state=state,action=action):
                    User.objects.filter(pk=self.staff.pk).update(is_active=True,is_staff=True,session_epoch=original_epoch)
                    Device.objects.filter(pk=device_id).update(revoked_at=None)
                    TOTPDevice.objects.filter(user=self.staff).delete();MFARecoveryCode.objects.filter(user=self.staff).delete()
                    if action!='enroll':TOTPDevice.objects.create(user=self.staff,confirmed=action in ('verify','recover'))
                    recovery=MFARecoveryCode.objects.create(user=self.staff,code_sha256=_digest('mfa-recovery:original-code'))
                    before=list(TOTPDevice.objects.filter(user=self.staff).values())
                    if state=='inactive':User.objects.filter(pk=self.staff.pk).update(is_active=False)
                    elif state=='reset':User.objects.filter(pk=self.staff.pk).update(session_epoch=original_epoch+1)
                    elif state=='revoked':Device.objects.filter(pk=device_id).update(revoked_at=timezone.now())
                    else:User.objects.filter(pk=self.staff.pk).update(is_staff=False)
                    request=RequestFactory().post('/original-mfa-fixture');request.user=actor;request.session=self.client.session
                    request.session.pop('otp_device_id',None)
                    with patch('accounts.mfa._verify_token') as verify,patch('django_otp.login') as login:
                        with self.assertRaises(DomainError) as denied:
                            if action=='enroll':mfa.enroll(request)
                            else:getattr(mfa,action)(request,'original-code' if action=='recover' else '123456')
                        self.assertEqual(denied.exception.code,'permission_denied' if state=='demoted' else 'authentication_required')
                        verify.assert_not_called();login.assert_not_called()
                    self.assertEqual(list(TOTPDevice.objects.filter(user=self.staff).values()),before)
                    recovery.refresh_from_db();self.assertIsNone(recovery.used_at)
                    self.assertEqual(MFARecoveryCode.objects.filter(user=self.staff).count(),1)
                    self.assertNotIn('otp_device_id',request.session)
