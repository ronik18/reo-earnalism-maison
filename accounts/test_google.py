"""No provider traffic: real RS256/X509 signatures exercise maintained allauth OIDC."""
import base64
import hashlib
import io
import json
import time
from datetime import datetime,timedelta,timezone as datetime_timezone
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch
import jwt
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase,TestCase,TransactionTestCase,Client,override_settings
from django.utils import timezone
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount,SocialToken
from .models import User,Preferences

CLIENT_ID='synthetic.apps.googleusercontent.com'
SECRET='synthetic-google-secret-not-real'
CALLBACK='http://localhost/api/v1/auth/google/callback'
PASS='Strong-Google-Fixture-Passphrase-47'
PROVIDERS={'google':{'APP':{'client_id':CLIENT_ID,'secret':SECRET},'SCOPE':['openid','email','profile'],'OAUTH_PKCE_ENABLED':True}}


class GoogleOIDCAcceptanceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic Google OIDC fixture')]);now=datetime.now(datetime_timezone.utc)
        cls.cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(cls.key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).sign(cls.key,hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode())
    def setUp(self):
        self.override=override_settings(LOCAL=True,PUBLIC_BASE_URL='http://localhost',GOOGLE_CLIENT_ID=CLIENT_ID,GOOGLE_CLIENT_SECRET=SECRET,GOOGLE_REDIRECT_URI=CALLBACK,
            FEATURES={**settings.FEATURES,'google_oauth':True},SOCIALACCOUNT_PROVIDERS=PROVIDERS,EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
        self.override.enable();self.addCleanup(self.override.disable);cache.clear();self.client=Client()
    def start(self,client=None,intent='sign_in',return_path='/en/vault/'):
        client=client or self.client
        result=client.get('/api/v1/auth/google',{'intent':intent,'return_path':return_path},HTTP_HOST='localhost')
        self.assertEqual(result.status_code,302,result.content);self.assertEqual(result['Referrer-Policy'],'no-referrer')
        params=parse_qs(urlsplit(result['Location']).query)
        self.assertEqual(params['redirect_uri'],[CALLBACK]);self.assertEqual(params['code_challenge_method'],['S256'])
        self.assertIn('openid',params['scope'][0]);self.assertGreaterEqual(len(params['state'][0]),32)
        return {key:value[0] for key,value in params.items()}
    def claims(self,params,**overrides):
        now=int(time.time())
        return {'iss':'https://accounts.google.com','aud':CLIENT_ID,'iat':now,'exp':now+300,'nonce':params['nonce'],
            'sub':'synthetic-subject','email':'google-member@example.test','email_verified':True,**overrides}
    def provider(self,claims,params,key=None,before_token=None):
        credential=jwt.encode(claims,key or self.key,algorithm='RS256',headers={'kid':'fixture'})
        seen=[]
        class Raw(io.BytesIO):
            def read(self,amount=-1,decode_content=None):return super().read(amount)
        def request(session,method,url,**kwargs):
            seen.append(url)
            if url=='https://oauth2.googleapis.com/token':
                if before_token:before_token()
                data=kwargs['data'];self.assertEqual(data['redirect_uri'],CALLBACK)
                challenge=base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).rstrip(b'=').decode()
                self.assertEqual(challenge,params['code_challenge'])
                payload={'access_token':'synthetic-access-not-real','token_type':'Bearer','expires_in':300,'id_token':credential}
            elif url=='https://www.googleapis.com/oauth2/v1/certs':payload={'fixture':self.cert}
            else:raise AssertionError('Unexpected provider URL')
            raw=json.dumps(payload).encode();response=requests.Response();response.status_code=200
            response.headers.update({'Content-Type':'application/json','Content-Length':str(len(raw))});response.raw=Raw(raw);return response
        return patch('requests.sessions.Session.request',autospec=True,side_effect=request),seen
    def finish(self,params,claims=None,client=None,key=None):
        mock,seen=self.provider(claims or self.claims(params),params,key)
        with mock:result=(client or self.client).get('/api/v1/auth/google/callback',{'state':params['state'],'code':'synthetic-code'},HTTP_HOST='localhost')
        self.assertEqual(result['Referrer-Policy'],'no-referrer')
        return result,seen
    def test_new_verified_subject_creates_framework_identity_and_rotates_session(self):
        params=self.start();before=self.client.session.session_key
        response,seen=self.finish(params);self.assertEqual(response.status_code,302,response.content);self.assertEqual(response['Location'],'/en/vault/')
        self.assertEqual(seen,['https://oauth2.googleapis.com/token','https://www.googleapis.com/oauth2/v1/certs'])
        user=User.objects.get(email='google-member@example.test');self.assertTrue(user.is_verified);self.assertFalse(user.has_usable_password())
        self.assertEqual(SocialAccount.objects.get(user=user).uid,'synthetic-subject');self.assertTrue(EmailAddress.objects.get(user=user,email=user.email).verified)
        self.assertFalse(SocialToken.objects.exists());self.assertTrue(Preferences.objects.filter(user=user).exists());self.assertNotEqual(self.client.session.session_key,before)
        self.assertTrue(self.client.get('/api/v1/session',HTTP_HOST='localhost').json()['authenticated'])
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Replay must not exchange code')):
            self.assertEqual(self.client.get('/api/v1/auth/google/callback',{'state':params['state'],'code':'synthetic-code'},HTTP_HOST='localhost').status_code,403)
    def test_email_collision_requires_explicit_fresh_link_and_subject_stays_authoritative(self):
        user=User.objects.create_user('google-member@example.test',PASS,is_verified=True)
        params=self.start();response,_=self.finish(params);self.assertEqual(response.status_code,409,response.content);self.assertFalse(SocialAccount.objects.exists())
        self.client.post('/api/v1/auth/login',{'email':user.email,'password':PASS},content_type='application/json',HTTP_HOST='localhost')
        params=self.start(intent='link',return_path='/en/settings/');response,_=self.finish(params)
        self.assertEqual(response.status_code,302,response.content);self.assertEqual(SocialAccount.objects.get().user_id,user.pk)
        self.client.delete('/api/v1/session',HTTP_HOST='localhost')
        params=self.start();response,_=self.finish(params,self.claims(params,email='new-provider-email@example.test'))
        self.assertEqual(response.status_code,302,response.content);user.refresh_from_db();self.assertEqual(user.email,'google-member@example.test')
        self.assertEqual(User.objects.count(),1)
    def test_nonce_signature_issuer_audience_expiry_and_verified_email_are_enforced(self):
        variants=[{'nonce':'wrong'}, {'iss':'https://invalid.example'}, {'aud':'wrong-client'}, {'exp':int(time.time())-1}, {'email_verified':False}, {'email':'invalid-email'}, {'azp':'wrong-authorized-party'}]
        for override in variants:
            with self.subTest(override=list(override)):
                params=self.start();response,_=self.finish(params,self.claims(params,**override));self.assertEqual(response.status_code,403,response.content)
                self.assertFalse(SocialAccount.objects.exists())
        params=self.start();other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        response,_=self.finish(params,key=other);self.assertEqual(response.status_code,403,response.content)
    def test_expired_wrong_browser_state_and_link_without_reauth_do_not_call_provider(self):
        params=self.start()
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Must not contact provider')):
            self.assertEqual(Client().get('/api/v1/auth/google/callback',{'state':params['state'],'code':'code'},HTTP_HOST='localhost').status_code,403)
            session=self.client.session;states=session['socialaccount_states'];state=states[params['state']];state[1]=time.time()-601;session['socialaccount_states']=states;session.save()
            self.assertEqual(self.client.get('/api/v1/auth/google/callback',{'state':params['state'],'code':'code'},HTTP_HOST='localhost').status_code,403)
            self.assertEqual(self.client.get('/api/v1/auth/google',{'intent':'link'},HTTP_HOST='localhost').status_code,403)
    def test_disabled_flow_and_external_return_path_have_no_protocol_side_effect(self):
        with override_settings(FEATURES={**settings.FEATURES,'google_oauth':False}),patch('requests.sessions.Session.request',side_effect=AssertionError('No provider calls')):
            self.assertEqual(self.client.get('/api/v1/auth/google',HTTP_HOST='localhost').status_code,409)
        self.assertEqual(self.client.get('/api/v1/auth/google',{'return_path':'https://invalid.example/'},HTTP_HOST='localhost').status_code,422)

    def test_reauthentication_requires_the_linked_subject_and_keeps_member_device(self):
        user=User.objects.create_user('google-member@example.test',PASS,is_verified=True)
        SocialAccount.objects.create(user=user,provider='google',uid='synthetic-subject')
        self.client.post('/api/v1/auth/login',{'email':user.email,'password':PASS},content_type='application/json',HTTP_HOST='localhost')
        before=self.client.get('/api/v1/session',HTTP_HOST='localhost').json()['device_id']
        session=self.client.session;session['reauthenticated_at']=(timezone.now()-timedelta(minutes=6)).isoformat();session.save()
        self.assertEqual(self.client.get('/api/v1/auth/google',{'intent':'link'},HTTP_HOST='localhost').status_code,403)
        params=self.start(intent='reauthenticate',return_path='/en/settings/');response,_=self.finish(params)
        self.assertEqual(response.status_code,302,response.content)
        identity=self.client.get('/api/v1/session',HTTP_HOST='localhost').json();self.assertEqual(identity['device_id'],before)
        self.assertIsNotNone(identity['reauthenticated_at'])
        params=self.start(intent='reauthenticate');response,_=self.finish(params,self.claims(params,sub='different-subject'))
        self.assertEqual(response.status_code,403,response.content);self.assertEqual(SocialAccount.objects.count(),1)

    def test_link_cannot_take_other_member_identity_or_revive_a_used_session_state(self):
        user=User.objects.create_user('google-member@example.test',PASS,is_verified=True)
        self.client.post('/api/v1/auth/login',{'email':user.email,'password':PASS},content_type='application/json',HTTP_HOST='localhost')
        params=self.start(intent='link');old_states=json.loads(json.dumps(self.client.session['socialaccount_states']))
        response,_=self.finish(params);self.assertEqual(response.status_code,302,response.content)
        session=self.client.session;session['socialaccount_states']=old_states;session.save()
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Revived state must not call provider')):
            self.assertEqual(self.client.get('/api/v1/auth/google/callback',{'state':params['state'],'code':'another-code'},HTTP_HOST='localhost').status_code,403)
        other=User.objects.create_user('other-member@example.test',PASS,is_verified=True)
        params=self.start(intent='link');response,_=self.finish(params,self.claims(params,sub='new-subject',email=other.email))
        self.assertEqual(response.status_code,409,response.content);self.assertEqual(SocialAccount.objects.count(),1)

    def test_http_adapter_rejects_wrong_hosts_oversized_and_expired_budgets(self):
        from .google import BoundedGoogleSession
        from allauth.socialaccount.providers.oauth2.client import OAuth2Error
        with patch('requests.sessions.Session.request',side_effect=AssertionError('No provider request expected')):
            with self.assertRaises(OAuth2Error):BoundedGoogleSession(time.monotonic()+8).get('https://invalid.example/token')
            with self.assertRaises(OAuth2Error):BoundedGoogleSession(time.monotonic()-1).get('https://oauth2.googleapis.com/token')
        response=requests.Response();response.status_code=200;response.headers['Content-Length']='131073';response.raw=io.BytesIO(b'')
        with patch('requests.sessions.Session.request',return_value=response):
            with self.assertRaises(OAuth2Error):BoundedGoogleSession(time.monotonic()+8).get('https://oauth2.googleapis.com/token')
        self.assertTrue(response.raw.closed)

    def test_provider_timeout_is_retryable_and_does_not_persist_identity(self):
        params=self.start()
        with patch('requests.sessions.Session.request',side_effect=requests.Timeout('synthetic provider timeout, no secrets')):
            result=self.client.get('/api/v1/auth/google/callback',{'state':params['state'],'code':'synthetic-code'},HTTP_HOST='localhost')
        self.assertEqual(result.status_code,503,result.content);self.assertEqual(result.json()['code'],'google_provider_unavailable')
        self.assertFalse(SocialAccount.objects.exists());self.assertFalse(User.objects.exists())

    def test_native_email_collision_recovers_in_saved_locale_without_secret_query(self):
        user=User.objects.create_user('google-member@example.test',PASS,is_verified=True)
        params=self.start(return_path='/bn/vault/')
        mocked,_=self.provider(self.claims(params),params)
        with mocked:
            response=self.client.get('/api/v1/auth/google/callback',{'state':params['state'],'code':'synthetic-code'},HTTP_HOST='localhost',HTTP_ACCEPT='text/html,application/xhtml+xml;q=0.9')
        self.assertEqual(response.status_code,303,response.content)
        self.assertEqual(response['Location'],'/bn/sign-in/?google_error=identity_link_required')
        self.assertEqual(response['Referrer-Policy'],'no-referrer');self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertNotIn(params['state'],response['Location']);self.assertNotIn(user.email,response['Location']);self.assertNotIn('synthetic-code',response['Location'])
        params=self.start(return_path='/bn/vault/');response,_=self.finish(params)
        self.assertEqual(response.status_code,409,response.content);self.assertEqual(response.json()['code'],'identity_link_required')

    def test_native_start_domain_error_redirects_but_api_keeps_json_status(self):
        with override_settings(FEATURES={**settings.FEATURES,'google_oauth':False}),patch('requests.sessions.Session.request',side_effect=AssertionError('No provider calls')):
            native=self.client.get('/api/v1/auth/google',{'return_path':'/bn/vault/'},HTTP_HOST='localhost',HTTP_ACCEPT='text/html')
            self.assertEqual(native.status_code,303);self.assertEqual(native['Location'],'/en/sign-in/?google_error=feature_disabled')
            self.assertEqual(native['Referrer-Policy'],'no-referrer');self.assertEqual(native['Cache-Control'],'private, no-store')
            api=self.client.get('/api/v1/auth/google',HTTP_HOST='localhost',HTTP_ACCEPT='application/json')
            self.assertEqual(api.status_code,409);self.assertEqual(api.json()['code'],'feature_disabled')


class GoogleCallbackConcurrencyTests(TransactionTestCase):
    start=GoogleOIDCAcceptanceTests.start
    claims=GoogleOIDCAcceptanceTests.claims
    provider=GoogleOIDCAcceptanceTests.provider
    def setUp(self):
        GoogleOIDCAcceptanceTests.setUp(self)
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic concurrency certificate')]);now=datetime.now(datetime_timezone.utc)
        self.cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(self.key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).sign(self.key,hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode())
    def test_single_use_state_commits_before_provider_exchange_without_network_db_lock(self):
        from threading import Event
        from concurrent.futures import ThreadPoolExecutor
        from django.db import transaction,connections
        from django.contrib.sessions.models import Session
        params=self.start();cookies={key:value.value for key,value in self.client.cookies.items()};session_key=self.client.session.session_key
        started=Event();release=Event()
        def pause():started.set();self.assertTrue(release.wait(timeout=5))
        mocked,seen=self.provider(self.claims(params),params,before_token=pause)
        def finish():
            try:
                client=Client()
                for name,value in cookies.items():client.cookies[name]=value
                response=client.get('/api/v1/auth/google/callback',{'state':params['state'],'code':'first'},HTTP_HOST='localhost')
                return response.status_code,response.content[:400]
            finally:connections.close_all()
        with mocked,ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(finish)
            try:
                self.assertTrue(started.wait(timeout=3),future.result(timeout=1) if future.done() else 'Callback has not reached provider yet')
                with transaction.atomic():Session.objects.select_for_update(nowait=True).get(pk=session_key)
                client=Client()
                for name,value in cookies.items():client.cookies[name]=value
                self.assertEqual(client.get('/api/v1/auth/google/callback',{'state':params['state'],'code':'second'},HTTP_HOST='localhost').status_code,403)
            finally:release.set()
            self.assertEqual(future.result(timeout=5)[0],302,future.result(timeout=5)[1])
        self.assertEqual(seen.count('https://oauth2.googleapis.com/token'),1);self.assertEqual(SocialAccount.objects.count(),1)


class GoogleHTTPCompressionTests(SimpleTestCase):
    def response(self,body,wire_length=None):
        from urllib3.response import HTTPResponse
        response=requests.Response();response.status_code=200
        response.headers.update({'Content-Length':str(len(body) if wire_length is None else wire_length),'Content-Encoding':'gzip','Content-Type':'application/json'})
        response.raw=HTTPResponse(body=io.BytesIO(body),headers=response.headers,preload_content=False,decode_content=False,enforce_content_length=True)
        return response
    def test_valid_gzip_uses_decoded_eof_not_encoded_content_length(self):
        import gzip
        from .google import BoundedGoogleSession
        raw=json.dumps({'synthetic_certificate':'abc123'*100}).encode();encoded=gzip.compress(raw)
        self.assertNotEqual(len(encoded),len(raw));response=self.response(encoded)
        with patch('requests.sessions.Session.request',return_value=response):
            actual=BoundedGoogleSession(time.monotonic()+8).get('https://www.googleapis.com/oauth2/v1/certs')
        self.assertEqual(actual.content,raw);self.assertEqual(actual.json(),json.loads(raw));self.assertTrue(response.raw.closed)
    def test_truncated_gzip_wire_is_rejected_and_closed(self):
        import gzip
        from .google import BoundedGoogleSession,GoogleProviderUnavailable
        encoded=gzip.compress(json.dumps({'synthetic_certificate':'abc123'*100}).encode());response=self.response(encoded[:-8],len(encoded))
        with patch('requests.sessions.Session.request',return_value=response):
            with self.assertRaises(GoogleProviderUnavailable):BoundedGoogleSession(time.monotonic()+8).get('https://www.googleapis.com/oauth2/v1/certs')
        self.assertTrue(response.raw.closed)
    def test_compressed_decoded_size_cap_is_still_enforced(self):
        import gzip
        from .google import BoundedGoogleSession
        from allauth.socialaccount.providers.oauth2.client import OAuth2Error
        encoded=gzip.compress(b'x'*131073);response=self.response(encoded)
        with patch('requests.sessions.Session.request',return_value=response):
            with self.assertRaises(OAuth2Error):BoundedGoogleSession(time.monotonic()+8).get('https://www.googleapis.com/oauth2/v1/certs')
        self.assertTrue(response.raw.closed)
