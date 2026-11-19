import json
import uuid
from datetime import timedelta
from urllib.parse import quote
from django.conf import settings
from django.core import mail
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from .models import User,Device,EmailActionToken
from . import services
from core.jobs import run_due_jobs
from core.models import OutboxJob
from library.validation import validate_schema

PASS='Isolated-Magic-Passphrase-47'

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MagicAndDeviceAcceptanceTests(TestCase):
    def setUp(self):
        self.flags=override_settings(FEATURES={**settings.FEATURES,'email_link':True});self.flags.enable();self.addCleanup(self.flags.disable)
        self.user=User.objects.create_user('magic@example.test',PASS,is_verified=False)
        self.client=Client(enforce_csrf_checks=True);self.csrf=self.client.get('/api/v1/session').json()['csrf_token']
    def post(self,path,data):return self.client.post(path,data,content_type='application/json',HTTP_X_CSRFTOKEN=self.csrf)
    def request_magic(self):
        result=self.post('/api/v1/auth/email-links/request',{'email':self.user.email,'locale':'bn','return_path':'/bn/vault/'})
        self.assertEqual(result.status_code,202,result.content)
        return EmailActionToken.objects.filter(user=self.user,purpose='magic_signin').latest('created_at')
    def test_mailbox_proof_rotates_session_and_csrf_with_single_use(self):
        action=self.request_magic();before=self.client.session.session_key;token=services._token_value(action)
        run_due_jobs();self.assertEqual(len(mail.outbox),1)
        self.assertIn('/auth/sign-in/?token='+quote(token),mail.outbox[0].body);self.assertIn('&locale=bn',mail.outbox[0].body)
        self.assertLessEqual(action.expires_at-action.created_at,timedelta(seconds=600));self.assertGreater(action.expires_at-action.created_at,timedelta(seconds=599))
        denied=Client(enforce_csrf_checks=True).post('/api/v1/auth/email-links/consume',{'token':token},content_type='application/json')
        self.assertEqual(denied.status_code,403)
        self.assertEqual(self.client.get('/api/v1/auth/email-links/consume').status_code,405)
        action.refresh_from_db();self.assertIsNone(action.consumed_at)
        response=self.post('/api/v1/auth/email-links/consume',{'token':token});self.assertEqual(response.status_code,200,response.content)
        validate_schema(response.json(),'Session');self.assertTrue(response.json()['authenticated']);self.assertTrue(response.json()['member']['email_verified'])
        self.assertNotEqual(self.client.session.session_key,before);self.assertNotEqual(response.json()['csrf_token'],self.csrf)
        self.csrf=response.json()['csrf_token'];self.assertEqual(self.post('/api/v1/auth/email-links/consume',{'token':token}).status_code,410)
        self.assertEqual(Device.objects.filter(user=self.user,revoked_at=None).count(),1)
    def test_generic_unknown_request_disabled_flag_resend_and_wrong_purpose(self):
        response=self.post('/api/v1/auth/email-links/request',{'email':'unknown@example.test','locale':'en'});self.assertEqual(response.status_code,202);self.assertFalse(OutboxJob.objects.exists())
        first=self.request_magic();second=self.request_magic();first.refresh_from_db();self.assertIsNotNone(first.consumed_at)
        self.assertEqual(self.post('/api/v1/auth/email-links/consume',{'token':services._token_value(first)}).status_code,410)
        self.assertEqual(self.post('/api/v1/auth/email-verifications/confirm',{'token':services._token_value(second)}).status_code,410)
        with override_settings(FEATURES={**settings.FEATURES,'email_link':False}):
            self.assertEqual(self.post('/api/v1/auth/email-links/consume',{'token':services._token_value(second)}).status_code,409)
            self.assertEqual(self.post('/api/v1/auth/email-links/request',{'email':self.user.email,'locale':'en'}).status_code,409)
            run_due_jobs();self.assertEqual(len(mail.outbox),0)
    def test_locale_is_preserved_validated_and_unknown_action_is_not_verification(self):
        self.assertEqual(self.post('/api/v1/auth/email-links/request',{'email':self.user.email,'locale':'xx'}).status_code,422)
        self.assertEqual(self.post('/api/v1/auth/unknown/request',{'email':self.user.email}).status_code,404)
        self.assertEqual(self.post('/api/v1/auth/unknown/confirm',{'token':'not-a-token'}).status_code,404)
        self.assertFalse(EmailActionToken.objects.exists())
    def test_device_history_has_complete_member_bound_keyset_pages(self):
        self.user.is_verified=True;self.user.save()
        response=self.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS});self.assertEqual(response.status_code,200);self.csrf=response.json()['csrf_token']
        now=timezone.now();Device.objects.bulk_create([Device(user=self.user,token_binding_sha256='a'*64,expires_at=now+timedelta(days=1)) for _ in range(105)])
        Device.objects.filter(user=self.user).update(last_seen_at=now)
        ids=[];cursor=None
        while True:
            params={'limit':20}
            if cursor:params['cursor']=cursor
            response=self.client.get('/api/v1/me/devices',params);self.assertEqual(response.status_code,200,response.content)
            page=response.json();ids.extend(row['device_id'] for row in page['items']);cursor=page['next_cursor']
            if not cursor:break
        self.assertEqual(len(ids),106);self.assertEqual(len(set(ids)),106)

    def test_verification_rotates_anonymous_session_and_csrf(self):
        action=services._create_action(self.user,'verify_email',locale='en')
        before=self.client.session.session_key
        response=self.post('/api/v1/auth/email-verifications/confirm',{'token':services._token_value(action)})
        self.assertEqual(response.status_code,200,response.content);self.assertFalse(response.json()['authenticated'])
        self.assertNotEqual(self.client.session.session_key,before);self.assertNotEqual(response.json()['csrf_token'],self.csrf)
        self.user.refresh_from_db();self.assertTrue(self.user.is_verified)

    def test_verification_preserves_current_and_other_member_device_sessions(self):
        self.user.is_verified=True;self.user.save()
        response=self.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS});self.csrf=response.json()['csrf_token']
        current=response.json()['device_id'];before=self.client.session.session_key
        other=Client();other.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS},content_type='application/json')
        other_id=other.get('/api/v1/session').json()['device_id']
        action=services._create_action(self.user,'verify_email',locale='en')
        response=self.post('/api/v1/auth/email-verifications/confirm',{'token':services._token_value(action)})
        self.assertEqual(response.status_code,200,response.content);self.assertTrue(response.json()['authenticated'])
        self.assertEqual(response.json()['device_id'],current);self.assertNotEqual(self.client.session.session_key,before)
        self.assertEqual(Device.objects.get(pk=current).session_id,self.client.session.session_key)
        self.assertIsNone(Device.objects.get(pk=current).revoked_at)
        self.assertEqual(other.get('/api/v1/session').json()['device_id'],other_id)
        self.assertTrue(self.client.get('/api/v1/session').json()['authenticated'])

    def test_same_browser_relogin_replaces_only_its_validated_device(self):
        self.user.is_verified=True;self.user.save()
        response=self.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS});self.csrf=response.json()['csrf_token'];old=response.json()['device_id']
        other=Client();other.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS},content_type='application/json');other_id=other.get('/api/v1/session').json()['device_id']
        action=self.request_magic();response=self.post('/api/v1/auth/email-links/consume',{'token':services._token_value(action)})
        self.assertEqual(response.status_code,200,response.content);self.assertNotEqual(response.json()['device_id'],old)
        self.assertIsNotNone(Device.objects.get(pk=old).revoked_at);self.assertIsNone(Device.objects.get(pk=other_id).revoked_at)
        self.assertTrue(other.get('/api/v1/session').json()['authenticated'])
