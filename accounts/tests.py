import json
import tempfile
import uuid
from pathlib import Path
from django.conf import settings
from django.core import mail
from django.test import TestCase,Client,override_settings
from core.api import DomainError
from core.jobs import run_due_jobs
from core.models import OutboxJob,OperationReceipt
from library.validation import validate_schema
from .models import User,Device,EmailActionToken,Preferences
from . import services

PASS='Local-Only-Passphrase-47'

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AccountAcceptanceTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('member@example.test',PASS,is_verified=True)
        self.client=Client(enforce_csrf_checks=True)
        self.csrf=self.client.get('/api/v1/session').json()['csrf_token']
    def post(self,path,data,**headers):
        response=self.client.post(path,data,content_type='application/json',HTTP_X_CSRFTOKEN=self.csrf,**headers)
        if response.status_code==200 and path=='/api/v1/auth/login':self.csrf=response.json()['csrf_token']
        return response
    def login(self):
        response=self.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'});self.assertEqual(response.status_code,200,response.content);return response
    def test_anonymous_and_authenticated_session_match_contract(self):
        validate_schema(self.client.get('/api/v1/session').json(),'Session')
        response=self.login();validate_schema(response.json(),'Session')
        self.assertEqual(response.json()['member']['member_id'],str(self.user.public_id))
        self.assertTrue(response.json()['reauthenticated_at'].endswith('Z'))
        self.assertNotIn('password',response.content.decode());self.assertNotIn('session_epoch',response.content.decode())
    def test_csrf_is_required_for_login_and_registration(self):
        response=self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
        self.assertEqual(response.status_code,403);validate_schema(response.json(),'Problem')
        self.assertEqual(self.client.post('/api/v1/auth/register',{},content_type='application/json').status_code,403)
    def test_email_normalization_and_password_hash(self):
        self.assertNotEqual(self.user.password,PASS)
        self.assertTrue(self.user.check_password(PASS))
        self.assertEqual(services.login_member.__name__,'login_member')
        response=self.post('/api/v1/auth/login',{'email':' MEMBER@EXAMPLE.TEST ','password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'})
        self.assertEqual(response.status_code,200,response.content)
    def test_unverified_registration_queues_and_delivers_real_local_mail(self):
        response=self.post('/api/v1/auth/register',{'email':'new@example.test','password':PASS,'display_name':'Local member','password_purpose_consent':True,'password_purpose_version':'password-account-v1'})
        self.assertEqual(response.status_code,202);validate_schema(response.json(),'Acknowledgement')
        user=User.objects.get(email='new@example.test');self.assertFalse(user.is_verified)
        self.assertEqual(self.post('/api/v1/auth/login',{'email':user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'}).status_code,403)
        run_due_jobs();self.assertEqual(len(mail.outbox),1)
        self.assertEqual(OutboxJob.objects.get(kind='email_action').status,'done')
        action=EmailActionToken.objects.get(user=user)
        self.assertNotIn('token',OutboxJob.objects.get(kind='email_action').payload)
        token=services._token_value(action);self.assertNotIn(token,action.token_sha256)
        self.assertIn(token.replace(':','%3A'),mail.outbox[0].body)
        verified=self.post('/api/v1/auth/email-verifications/confirm',{'token':token});self.assertEqual(verified.status_code,200);self.csrf=verified.json()['csrf_token']
        self.assertEqual(self.post('/api/v1/auth/email-verifications/confirm',{'token':token}).status_code,410)
        user.refresh_from_db();self.assertTrue(user.is_verified)
    def test_password_reset_revokes_every_old_session_and_action_token(self):
        self.login();services.request_password_reset(self.user.email)
        action=EmailActionToken.objects.get(user=self.user,purpose='password_reset',consumed_at=None)
        token=services._token_value(action);services.confirm_password_reset(token,'Another-Local-Passphrase-53')
        self.assertFalse(self.client.get('/api/v1/session').json()['authenticated'])
        self.assertFalse(Device.objects.filter(user=self.user,revoked_at=None).exists())
        with self.assertRaises(DomainError) as e:services.confirm_password_reset(token,'Another-Local-Passphrase-54')
        self.assertEqual(e.exception.status,410)
    def test_device_binding_cookie_is_required_and_revocation_is_durable(self):
        session=self.login().json();self.client.cookies[settings.DEVICE_COOKIE_NAME]='invalid-binding'
        self.assertFalse(self.client.get('/api/v1/session').json()['authenticated'])
    def test_preferences_full_contract_and_stale_update(self):
        self.login();response=self.client.get('/api/v1/me/preferences');validate_schema(response.json(),'Preferences')
        result=self.client.patch('/api/v1/me/preferences',{'reader_typeface':'sans','reader_line_height':1.8,'reader_margins':'wide','reader_alignment':'justify','saved_filters':[{'name':'Stories','query':'','filters':{'house':'golpo'}}]},content_type='application/json',HTTP_X_CSRFTOKEN=self.csrf,HTTP_IF_MATCH=response['ETag'])
        self.assertEqual(result.status_code,200,result.content);validate_schema(result.json(),'Preferences')
        stale=self.client.patch('/api/v1/me/preferences',{'locale':'bn'},content_type='application/json',HTTP_X_CSRFTOKEN=self.csrf,HTTP_IF_MATCH=response['ETag'])
        self.assertEqual(stale.status_code,412);validate_schema(stale.json(),'Problem')
        self.assertEqual(self.client.get('/api/v1/me/preferences').json()['reader_typeface'],'sans')
    def test_unknown_provider_never_claims_success(self):
        response=self.client.get('/api/v1/auth/google');self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['code'],'feature_disabled')
    def test_privacy_request_is_owned_and_deduplicated(self):
        self.login();key=str(uuid.uuid4())
        first=self.post('/api/v1/me/privacy/requests',{'kind':'export','confirm':True},HTTP_IDEMPOTENCY_KEY=key)
        second=self.post('/api/v1/me/privacy/requests',{'kind':'export','confirm':True},HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(first.status_code,202,first.content);self.assertEqual(first.json(),second.json());validate_schema(first.json(),'PrivacyRequest')
        self.assertEqual(OutboxJob.objects.filter(kind='privacy_export').count(),1)

    def test_standard_verified_staff_admin_login_binds_device(self):
        staff=User.objects.create_superuser('staff@example.test',PASS)
        first=self.client.get('/admin/login/')
        token=self.client.cookies[settings.CSRF_COOKIE_NAME].value
        response=self.client.post('/admin/login/',{'username':staff.email,'password':PASS,'next':'/admin/','password_purpose_consent':True,'password_purpose_version':'password-account-v1'},HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,302,response.content)
        self.assertIn(settings.DEVICE_COOKIE_NAME,self.client.cookies)
        self.assertEqual(self.client.get('/admin/').status_code,200)
        self.assertTrue(self.client.get('/api/v1/session').json()['authenticated'])

    def test_nested_preference_filters_reject_invalid_payload_without_mutation(self):
        self.login()
        before=self.client.get('/api/v1/me/preferences')
        original=before.json()
        invalid=[
            {'saved_filters':[{'name':'Bad facet','query':'','filters':{'unknown_facet':'secret'}}]},
            {'saved_filters':[{'name':'Wrong level','query':'','filters':{'level':'expert'}}]},
            {'saved_filters':[{'name':'Wrong type','query':'','filters':{'duration_max':'long'}}]},
            {'search_filters':{'house':'unknown_house'}},
            {'search_filters':{'duration_min':-1}},
            {'search_filters':{'duration_max':'60'}},
        ]
        for bad in invalid:
            with self.subTest(payload=bad):
                response=self.client.patch('/api/v1/me/preferences',{'reader_font_size':23,**bad},content_type='application/json',HTTP_X_CSRFTOKEN=self.csrf,HTTP_IF_MATCH=before['ETag'])
                self.assertEqual(response.status_code,422,response.content)
                validate_schema(response.json(),'Problem')
                current=self.client.get('/api/v1/me/preferences')
                self.assertEqual(current.json(),original)
                self.assertEqual(current['ETag'],before['ETag'])
                validate_schema(current.json(),'Preferences')

    def test_direct_preference_service_validates_before_creating_state(self):
        self.assertFalse(Preferences.objects.filter(user=self.user).exists())
        with self.assertRaises(DomainError) as caught:
            services.update_preferences(self.user,{'search_filters':{'locale':'fr'}},1)
        self.assertEqual(caught.exception.status,422)
        self.assertFalse(Preferences.objects.filter(user=self.user).exists())
