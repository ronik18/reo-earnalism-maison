import json,uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import IntegrityError,transaction,close_old_connections,connections
from django.test import TestCase,RequestFactory,TransactionTestCase
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from .models import Offer,Entitlement
from .subscription_models import BillingPlan,Mandate,Subscription
from . import subscriptions as svc

class SubscriptionLifecycleTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('subscription@example.test','Local-Fixture-Password-47',is_verified=True)
        self.other=get_user_model().objects.create_user('other-subscription@example.test','Local-Fixture-Password-47',is_verified=True)
        now=timezone.now()
        self.offer=Offer.objects.create(code='recurring-fixture',name='Existing fixture only',price_minor=100,currency='INR',duration_seconds=86400,terms_version='test')
        self.plan=BillingPlan.objects.create(offer=self.offer,interval_unit='month')
        self.mandate=Mandate.objects.create(user=self.user,status='authorized',provider_mandate_id='mandate-fixture',max_amount_minor=100,authorized_at=now)
        self.subscription=Subscription.objects.create(user=self.user,plan=self.plan,mandate=self.mandate,status='active',provider_status='active',current_period_start=now-timedelta(days=1),current_period_end=now+timedelta(days=29),paid_through=now+timedelta(days=29),next_charge_at=now+timedelta(days=29))
        self.entitlement=Entitlement.objects.create(grant_key='subscription-existing-fixture',user=self.user,source='subscription_invoice',scope='platform',formats=['reader'],valid_from=now-timedelta(days=1),valid_until=now+timedelta(days=29))
    def request(self,method,path,body=None,version=1,key=None,fresh=True,user=None):
        factory=RequestFactory();request=factory.get(path) if method=='get' else getattr(factory,method)(path,data=json.dumps(body or {}),content_type='application/json',HTTP_IF_MATCH=f'"v{version}"',HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))
        request.user=user or self.user;request.session={'reauthenticated_at':timezone.now().isoformat()} if fresh else {};request.territory='IN';return request
    def cancel(self,base=1,key=None):return svc.cancel_existing(self.user,self.subscription.pk,{'at_period_end':True},base,key or uuid.uuid4())
    def test_cancel_is_versioned_receipted_and_preserves_paid_access_and_provider_status(self):
        key=uuid.uuid4();result=self.cancel(key=key);self.assertEqual(result[1]['version'],2)
        self.assertEqual(result[1]['status'],'active');self.assertEqual(result[1]['provider_status'],'active')
        self.assertTrue(result[1]['cancel_at_period_end']);self.assertEqual(self.cancel(key=key),result)
        self.entitlement.refresh_from_db();self.assertEqual(self.entitlement.status,'active');self.assertIsNone(self.entitlement.revoked_at)
        job=OutboxJob.objects.get();self.assertEqual(job.status,'blocked');self.assertEqual(job.error_code,'provider_not_qualified')
        self.assertEqual(result[1]['paid_through'],svc.iso(self.entitlement.valid_until))
    def test_stale_cancel_and_reused_key_cannot_change_outcome(self):
        key=uuid.uuid4();self.cancel(key=key)
        with self.assertRaises(DomainError) as error:self.cancel(base=1)
        self.assertEqual(error.exception.status,412)
        with self.assertRaises(DomainError) as error:self.cancel(base=2,key=key)
        self.assertEqual(error.exception.code,'idempotency_key_reused');self.assertEqual(OutboxJob.objects.count(),1)
    def test_cross_owner_is_not_found(self):
        with self.assertRaises(DomainError) as error:svc.cancel_existing(self.other,self.subscription.pk,{'at_period_end':True},1,uuid.uuid4())
        self.assertEqual(error.exception.status,404)
        with self.assertRaises(DomainError) as error:svc.revoke_existing(self.other,self.mandate.pk,uuid.uuid4())
        self.assertEqual(error.exception.status,404)
    def test_revoke_is_pending_not_external_confirmation_and_does_not_remove_paid_access(self):
        key=uuid.uuid4();status,result=svc.revoke_existing(self.user,self.mandate.pk,key)
        self.assertTrue(result['revocation_pending']);self.assertEqual(result['status'],'authorized');self.assertIsNone(result['revoked_at'])
        self.assertEqual(svc.revoke_existing(self.user,self.mandate.pk,key)[1],result)
        self.subscription.refresh_from_db();self.assertTrue(self.subscription.cancel_at_period_end)
        self.entitlement.refresh_from_db();self.assertEqual(self.entitlement.status,'active');self.assertEqual(OutboxJob.objects.count(),1)
    def test_routes_require_fresh_reauthentication_and_creation_remains_disabled(self):
        response=svc.cancel(self.request('post','/',{'at_period_end':True},fresh=False),self.subscription.pk)
        self.assertEqual(response.status_code,403)
        response=svc.revoke(self.request('delete','/',fresh=False),self.mandate.pk);self.assertEqual(response.status_code,403)
        response=svc.subscriptions(self.request('post','/'));self.assertEqual(response.status_code,409)
        response=svc.cancel(self.request('post','/',{'at_period_end':False}),self.subscription.pk);self.assertEqual(response.status_code,422)
    def test_list_cursor_cannot_be_reused_by_another_member_or_filter(self):
        Subscription.objects.create(user=self.user,plan=self.plan)
        response=svc.subscriptions(self.request('get','/?limit=1'));data=json.loads(response.content);self.assertTrue(data['has_more'])
        token=data['next_cursor']
        response=svc.subscriptions(self.request('get','/?limit=1&cursor='+token,user=self.other));self.assertEqual(response.status_code,422)
        response=svc.subscriptions(self.request('get','/?limit=1&cursor='+token));self.assertEqual(len(json.loads(response.content)['items']),1)
    def test_database_guards_reject_cross_owner_and_cancel_undo(self):
        with self.assertRaises(IntegrityError),transaction.atomic():Subscription.objects.create(user=self.other,plan=self.plan,mandate=self.mandate)
        self.cancel()
        with self.assertRaises(IntegrityError),transaction.atomic():Subscription.objects.filter(pk=self.subscription.pk).update(cancel_at_period_end=False)
        svc.revoke_existing(self.user,self.mandate.pk,uuid.uuid4())
        with self.assertRaises(IntegrityError),transaction.atomic():Mandate.objects.filter(pk=self.mandate.pk).update(revocation_pending=False)
    def test_existing_plan_and_terms_cannot_be_repriced_by_raw_updates(self):
        with self.assertRaises(IntegrityError),transaction.atomic():BillingPlan.objects.filter(pk=self.plan.pk).update(interval_count=2)
        with self.assertRaises(IntegrityError),transaction.atomic():Offer.objects.filter(pk=self.offer.pk).update(price_minor=200)
    def test_subscription_contract_response_has_no_checkout_or_provider_identifiers(self):
        response=svc.subscription(self.request('get','/'),self.subscription.pk);data=json.loads(response.content)
        self.assertIsNone(data['checkout']);self.assertNotIn('provider_subscription_id',data);self.assertNotIn('user_id',data)


class ConcurrentSubscriptionIntentTests(TransactionTestCase):
    def setUp(self):
        # Reuse fixture construction, never its TestCase transaction wrapper.
        SubscriptionLifecycleTests.setUp(self)

    def test_concurrent_cancel_and_revoke_converge_without_losing_paid_access(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2)
        user_id=self.user.pk;subscription_id=self.subscription.pk;mandate_id=self.mandate.pk
        paid_until=self.entitlement.valid_until
        def write(action):
            close_old_connections()
            try:
                actor=get_user_model().objects.get(pk=user_id)
                barrier.wait(timeout=5)
                try:
                    if action=='cancel':
                        return svc.cancel_existing(actor,subscription_id,{'at_period_end':True},1,uuid.uuid4())[0]
                    return svc.revoke_existing(actor,mandate_id,uuid.uuid4())[0]
                except DomainError as error:
                    return error.status
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(write,action) for action in ('cancel','revoke')]
            results=[future.result(timeout=15) for future in futures]
        self.assertEqual(results[1],200)
        self.assertIn(results[0],(200,412))
        self.subscription.refresh_from_db();self.mandate.refresh_from_db();self.entitlement.refresh_from_db()
        self.assertTrue(self.subscription.cancel_at_period_end)
        self.assertTrue(self.mandate.revocation_pending)
        self.assertEqual(self.subscription.version,2);self.assertEqual(self.mandate.version,2)
        self.assertEqual(self.subscription.provider_status,'active')
        self.assertEqual(self.entitlement.valid_until,paid_until);self.assertEqual(self.entitlement.status,'active')
        self.assertEqual(OutboxJob.objects.filter(dedupe_key=f'mandate.revoke:{mandate_id}').count(),1)
        self.assertEqual(OutboxJob.objects.filter(dedupe_key=f'subscription.cancel:{subscription_id}').count(),int(results[0]==200))
        self.assertFalse(OutboxJob.objects.exclude(status='blocked').exists())
