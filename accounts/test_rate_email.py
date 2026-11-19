"""Real SQL counters and deterministic Django email submission failure recovery."""
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from django.core import mail
from django.http import JsonResponse
from django.test import TestCase,RequestFactory,override_settings
from django.utils import timezone
from core.api import DomainError
from core.jobs import run_due_jobs
from core.models import OutboxJob
from core.rate_limits import MemberRateLimitMiddleware,_policy
from .models import User,RateLimitBucket,EmailActionToken
from . import services


class MemberRateTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('rate@example.test','A-strong-test-password47',is_verified=True)
        self.factory=RequestFactory();self.middleware=MemberRateLimitMiddleware(lambda request:JsonResponse({'ok':True}))
    def request(self,device='one',method='get',path='/api/v1/me/profile'):
        request=getattr(self.factory,method)(path);request.user=self.user;request.device=SimpleNamespace(pk=device);request.session={};return request
    def test_matches_contract_and_exempts_unknown_or_anonymous_routes(self):
        name,policy=_policy(self.request());self.assertEqual((name,policy['requests'],policy['window_seconds']),('member_read',180,60))
        self.assertEqual(_policy(self.request(method='put',path='/api/v1/me/progress/123/reader'))[0],'progress')
        request=self.request(path='/en/');self.assertEqual(self.middleware(request).status_code,200);self.assertFalse(RateLimitBucket.objects.exists())
        request=self.request();request.user=SimpleNamespace(is_authenticated=False);self.middleware(request);self.assertFalse(RateLimitBucket.objects.exists())
    def test_postgresql_fixed_window_headers_and_denial_counter_persist(self):
        with patch('core.rate_limits._policy',return_value=('member_read',{'requests':2,'window_seconds':60,'scope':'member'})),patch('accounts.services.time.time',return_value=120.25):
            first=self.middleware(self.request());self.assertEqual(first['RateLimit-Remaining'],'1')
            second=self.middleware(self.request('two'));self.assertEqual(second['RateLimit-Remaining'],'0')
            denied=self.middleware(self.request());self.assertEqual(denied.status_code,429);self.assertEqual(denied['Retry-After'],'60');self.assertEqual(denied['RateLimit-Reset'],'60')
            self.assertEqual(RateLimitBucket.objects.get().count,3)
        with patch('core.rate_limits._policy',return_value=('member_read',{'requests':2,'window_seconds':60,'scope':'member'})),patch('accounts.services.time.time',return_value=180.25):
            self.assertEqual(self.middleware(self.request()).status_code,200)
    def test_write_bucket_is_device_bound_and_read_bucket_is_member_bound(self):
        with patch('core.rate_limits._policy',return_value=('member_write',{'requests':1,'window_seconds':60,'scope':'member + device'})):
            self.assertEqual(self.middleware(self.request('one')).status_code,200)
            self.assertEqual(self.middleware(self.request('one')).status_code,429)
            self.assertEqual(self.middleware(self.request('two')).status_code,200)
        self.assertEqual(RateLimitBucket.objects.count(),2)

    def test_maintenance_removes_expired_buckets_in_bounded_batches(self):
        services.check_rate('test-cleanup','old-one');services.check_rate('test-cleanup','old-two');services.check_rate('test-cleanup','current')
        old=list(RateLimitBucket.objects.order_by('pk').values_list('pk',flat=True)[:2])
        RateLimitBucket.objects.filter(pk__in=old).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(services.cleanup_rate_buckets(limit=1),{'deleted':1});self.assertEqual(RateLimitBucket.objects.count(),2)
        self.assertEqual(services.cleanup_rate_buckets(),{'deleted':1});self.assertEqual(RateLimitBucket.objects.count(),1)

    @override_settings(LOCAL=False,ORIGIN_SHARED_SECRET='test-origin-secret-at-least-32-characters')
    def test_production_uses_origin_validated_client_ip_and_normalizes_ipv6(self):
        from operations.middleware import OriginMiddleware
        boundary=OriginMiddleware(self.middleware)
        policy=('media_grant',{'requests':1,'window_seconds':60,'scope':'member + device + IP'})
        def request(ip,peer='192.0.2.1',forwarded='198.51.100.1'):
            item=self.request(method='post',path='/api/v1/media/grants');item.request_id=str(uuid.uuid4())
            item.META.update(HTTP_X_MAISON_ORIGIN='test-origin-secret-at-least-32-characters',HTTP_X_MAISON_COUNTRY='IN',HTTP_CF_CONNECTING_IP=ip,REMOTE_ADDR=peer,HTTP_X_FORWARDED_FOR=forwarded)
            return item
        with patch('core.rate_limits._policy',return_value=policy):
            self.assertEqual(boundary(request('2001:db8:0:0:0:0:0:1')).status_code,200)
            denied=boundary(request('2001:db8::1',peer='192.0.2.99',forwarded='198.51.100.99'))
            self.assertEqual(denied.status_code,429)
            self.assertEqual(boundary(request('2001:db8::2')).status_code,200)
        self.assertEqual(RateLimitBucket.objects.count(),2)

    @override_settings(LOCAL=False)
    def test_production_missing_or_invalid_trusted_identity_never_falls_back(self):
        policy=('media_grant',{'requests':1,'window_seconds':60,'scope':'member + device + IP'})
        with patch('core.rate_limits._policy',return_value=policy):
            for trusted in [None,'invalid','198.51.100.1, 198.51.100.2']:
                item=self.request(method='post',path='/api/v1/media/grants');item.trusted_client_ip=trusted
                item.META.update(REMOTE_ADDR='127.0.0.1',HTTP_CF_CONNECTING_IP='203.0.113.1',HTTP_X_FORWARDED_FOR='203.0.113.2')
                response=self.middleware(item)
                self.assertEqual(response.status_code,503);self.assertEqual(__import__('json').loads(response.content)['code'],'client_context_unavailable')
        self.assertFalse(RateLimitBucket.objects.exists())

    @override_settings(LOCAL=True)
    def test_local_fallback_uses_valid_peer_and_ignores_forwarding_headers(self):
        policy=('media_grant',{'requests':1,'window_seconds':60,'scope':'member + device + IP'})
        with patch('core.rate_limits._policy',return_value=policy):
            first=self.request();first.META.update(REMOTE_ADDR='127.0.0.1',HTTP_CF_CONNECTING_IP='203.0.113.1')
            self.assertEqual(self.middleware(first).status_code,200)
            second=self.request();second.META.update(REMOTE_ADDR='127.0.0.1',HTTP_CF_CONNECTING_IP='203.0.113.99',HTTP_X_FORWARDED_FOR='198.51.100.99')
            self.assertEqual(self.middleware(second).status_code,429)
        self.assertEqual(RateLimitBucket.objects.count(),1)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',EMAIL_TIMEOUT=8)
class EmailRecoveryTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('mail-recovery@example.test','A-strong-test-password47',is_verified=True)
        services.request_password_reset(self.user.email)
        self.action=EmailActionToken.objects.get(user=self.user);self.job=OutboxJob.objects.get(kind='email_action')
    def retry(self):
        OutboxJob.objects.filter(pk=self.job.pk).update(not_before=timezone.now())
        run_due_jobs();self.job.refresh_from_db()
    def test_uncertain_submission_retries_same_message_token_and_expiry(self):
        attempted=[];original_expiry=self.action.expires_at
        def uncertain(message,*args,**kwargs):
            attempted.append((message.body,message.extra_headers['Message-ID']))
            raise TimeoutError('Synthetic timeout after possible SMTP acceptance')
        with patch('accounts.email_delivery.EmailMessage.send',autospec=True,side_effect=uncertain):run_due_jobs()
        self.job.refresh_from_db();self.assertEqual(self.job.status,'pending');self.assertEqual(self.job.error_code,'email_submission_uncertain')
        self.assertEqual(self.job.payload['email_outcome'],'unknown');self.assertNotIn('token',self.job.payload)
        self.retry();self.assertEqual(self.job.status,'done');self.assertEqual(self.job.result['status'],'submitted');self.assertFalse(self.job.result['delivery_confirmed'])
        message=mail.outbox[-1];self.assertEqual((message.body,message.extra_headers['Message-ID']),attempted[0])
        self.action.refresh_from_db();self.assertEqual(self.action.expires_at,original_expiry)
        self.assertEqual(self.action.token_sha256,services._digest(services._token_value(self.action)))
    def test_consumed_or_replaced_token_never_sends_on_retry(self):
        EmailActionToken.objects.filter(pk=self.action.pk).update(consumed_at=timezone.now())
        with patch('accounts.email_delivery.get_connection',side_effect=AssertionError('Must not send consumed token')):run_due_jobs()
        self.job.refresh_from_db();self.assertEqual(self.job.result['status'],'expired_without_send')
    def test_zero_acceptance_retries_and_connection_budget_is_bounded(self):
        with patch('accounts.email_delivery.EmailMessage.send',return_value=0):run_due_jobs()
        self.job.refresh_from_db();self.assertEqual(self.job.status,'pending');self.assertEqual(self.job.error_code,'email_not_accepted')
        self.job.status='claimed';self.job.lease_owner='test';self.job.locked_until=timezone.now()+timedelta(seconds=120);self.job.save()
        from .email_delivery import deliver_action
        with patch('accounts.email_delivery.get_connection') as connection,patch('accounts.email_delivery.EmailMessage.send',return_value=1):
            deliver_action(self.job,max_seconds=2)
            self.assertEqual(connection.call_args.kwargs['timeout'],2)
    def test_changed_account_email_suppresses_old_destination(self):
        self.user.email='updated@example.test';self.user.save()
        with patch('accounts.email_delivery.get_connection',side_effect=AssertionError('Must not send old destination')):run_due_jobs()
        self.job.refresh_from_db();self.assertEqual(self.job.result['status'],'invalidated_without_send')

    def test_old_email_or_inactive_account_cannot_consume_action(self):
        token=services._token_value(self.action)
        self.user.email='changed-consumption@example.test';self.user.save()
        with self.assertRaises(DomainError) as error:services.confirm_password_reset(token,'Another-strong-password-47')
        self.assertEqual(error.exception.status,410)
        self.user.email=self.action.email_normalized;self.user.is_active=False;self.user.save()
        with self.assertRaises(DomainError) as error:services.confirm_password_reset(token,'Another-strong-password-47')
        self.assertEqual(error.exception.status,410)

class PublicAuthRateTests(TestCase):
    def setUp(self):
        self.factory=RequestFactory();self.called=0
        def downstream(request):self.called+=1;return JsonResponse({'ok':True})
        self.middleware=MemberRateLimitMiddleware(downstream)
    def request(self,path,email='member@example.test',ip='192.0.2.1'):
        from django.contrib.auth.models import AnonymousUser
        request=self.factory.post(path,{'email':email,'password':'not-used-by-test','locale':'en'},content_type='application/json',REMOTE_ADDR=ip)
        request.user=AnonymousUser();request.session={};return request
    @override_settings(LOCAL=True)
    def test_login_identity_limit_and_ip_limit_apply_to_anonymous_clients(self):
        for n in range(5):self.assertEqual(self.middleware(self.request('/api/v1/auth/login')).status_code,200)
        denied=self.middleware(self.request('/api/v1/auth/login'));self.assertEqual(denied.status_code,429);self.assertEqual(denied['RateLimit-Limit'],'5')
        self.assertEqual(self.called,5)
        form=self.factory.post('/bn/sign-in/',{'email':'member@example.test','password':'not-used'},REMOTE_ADDR='192.0.2.1')
        from django.contrib.auth.models import AnonymousUser
        form.user=AnonymousUser();form.session={}
        self.assertEqual(self.middleware(form).status_code,429)
        for n in range(23):self.assertEqual(self.middleware(self.request('/api/v1/auth/login',email=f'different{n}@example.test')).status_code,200)
        denied=self.middleware(self.request('/api/v1/auth/login',email='last@example.test'));self.assertEqual(denied.status_code,429);self.assertEqual(denied['RateLimit-Limit'],'30')
    @override_settings(LOCAL=True)
    def test_email_and_registration_ip_limits_cannot_be_evaded_by_changing_email(self):
        for n in range(20):self.assertEqual(self.middleware(self.request('/api/v1/auth/email-links/request',email=f'email{n}@example.test')).status_code,200)
        self.assertEqual(self.middleware(self.request('/api/v1/auth/password-resets/request',email='extra@example.test')).status_code,429)
        for n in range(3):self.assertEqual(self.middleware(self.request('/api/v1/auth/register',email=f'register{n}@example.test')).status_code,200)
        self.assertEqual(self.middleware(self.request('/api/v1/auth/register',email='register-last@example.test')).status_code,429)
    @override_settings(LOCAL=False)
    def test_public_auth_requires_attested_production_ip(self):
        request=self.request('/api/v1/auth/login');request.META['HTTP_CF_CONNECTING_IP']='198.51.100.1'
        self.assertEqual(self.middleware(request).status_code,503);self.assertEqual(self.called,0)
        request.trusted_client_ip='2001:db8::1';self.assertEqual(self.middleware(request).status_code,200)
