"""Mocked existing-agreement cancellation; never contacts a provider."""
import uuid
from unittest.mock import patch
from django.test import TestCase,override_settings
from core.api import DomainError
from core.models import OutboxJob
from . import test_subscriptions as fixtures,subscriptions
from .subscription_worker import process_subscription_job

@override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture',MERCHANT_ENTITY_CONFIG_VERSION='fixture')
class ExistingCancellationWorkerTests(TestCase):
    setUp=fixtures.SubscriptionLifecycleTests.setUp
    def queue(self):
        self.subscription.provider_subscription_id='sub_fixture';self.subscription.save()
        subscriptions.cancel_existing(self.user,self.subscription.pk,{'at_period_end':True},1,uuid.uuid4())
        job=OutboxJob.objects.get(dedupe_key=f'subscription.cancel:{self.subscription.pk}')
        self.assertEqual(job.status,'pending');return job
    def facts(self,status='active',**extra):return {'id':'sub_fixture','status':status,**extra}
    def test_acknowledged_cycle_end_cancel_preserves_paid_access_and_replays_without_post(self):
        job=self.queue();paid=self.subscription.paid_through
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            provider.return_value.fetch_subscription.return_value=self.facts()
            provider.return_value.cancel_subscription.return_value=self.facts()
            result=process_subscription_job(job);self.assertTrue(result['cycle_end_request_accepted'])
            self.assertEqual(process_subscription_job(job),result)
            provider.return_value.cancel_subscription.assert_called_once_with('sub_fixture')
        self.subscription.refresh_from_db();self.assertEqual(self.subscription.status,'active');self.assertEqual(self.subscription.paid_through,paid)
        self.entitlement.refresh_from_db();self.assertIsNone(self.entitlement.revoked_at)
    def test_timeout_reconciles_get_only_active_never_proves_acceptance(self):
        job=self.queue()
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            provider.return_value.fetch_subscription.return_value=self.facts()
            provider.return_value.cancel_subscription.side_effect=DomainError('provider_outcome_unknown','Fixture timeout',503)
            with self.assertRaises(DomainError):process_subscription_job(job)
            with self.assertRaises(DomainError) as error:process_subscription_job(job)
            self.assertEqual(error.exception.code,'awaiting_resolution')
            provider.return_value.cancel_subscription.assert_called_once()
            provider.return_value.fetch_subscription.return_value=self.facts('cancelled')
            result=process_subscription_job(job);self.assertEqual(result['status'],'cancelled')
            provider.return_value.cancel_subscription.assert_called_once()
        self.subscription.refresh_from_db();self.assertIsNone(self.subscription.next_charge_at)
        self.entitlement.refresh_from_db();self.assertIsNone(self.entitlement.revoked_at)
    def test_identity_mismatch_never_calls_mutation(self):
        job=self.queue()
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            provider.return_value.fetch_subscription.return_value=self.facts(id='sub_other')
            with self.assertRaises(DomainError):process_subscription_job(job)
            provider.return_value.cancel_subscription.assert_not_called()
    def test_revoke_queues_cancellation_but_never_claims_token_revocation(self):
        self.subscription.provider_subscription_id='sub_fixture';self.subscription.save()
        subscriptions.revoke_existing(self.user,self.mandate.pk,uuid.uuid4())
        cancel=OutboxJob.objects.get(dedupe_key=f'subscription.cancel:{self.subscription.pk}');self.assertEqual(cancel.status,'pending')
        revoke=OutboxJob.objects.get(dedupe_key=f'mandate.revoke:{self.mandate.pk}')
        self.assertEqual(revoke.status,'blocked');self.assertEqual(revoke.error_code,'provider_token_identity_missing')
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            with self.assertRaises(DomainError) as error:process_subscription_job(revoke)
            self.assertEqual(error.exception.code,'provider_token_identity_missing');provider.assert_not_called()
        self.mandate.refresh_from_db();self.assertTrue(self.mandate.revocation_pending);self.assertEqual(self.mandate.status,'authorized')
    def test_offer_flag_mutation_cannot_switch_queued_merchant_mode(self):
        job=self.queue();self.assertEqual(job.payload['provider_mode'],'test')
        self.offer.test_only=False;self.offer.save()
        with override_settings(RAZORPAY_MODE='live',RAZORPAY_KEY_ID='rzp_live_fixture',RAZORPAY_LIVE_APPROVED=True),patch('billing.subscription_worker.RazorpayClient') as provider:
            with self.assertRaises(DomainError) as error:process_subscription_job(job)
            self.assertEqual(error.exception.code,'provider_not_qualified');provider.assert_not_called()
        job.payload.pop('provider_mode');job.save(update_fields=['payload'])
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            with self.assertRaises(DomainError):process_subscription_job(job)
            provider.assert_not_called()
    def test_provider_reference_change_cannot_retarget_queued_cancellation(self):
        job=self.queue()
        self.subscription.provider_subscription_id='sub_different';self.subscription.save(update_fields=['provider_subscription_id'])
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            with self.assertRaises(DomainError) as error:process_subscription_job(job)
            self.assertEqual(error.exception.code,'provider_not_qualified');provider.assert_not_called()
