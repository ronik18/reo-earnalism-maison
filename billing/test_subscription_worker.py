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


@override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture',MERCHANT_ENTITY_CONFIG_VERSION='fixture')
class MandateIdentityTests(TestCase):
    setUp=fixtures.SubscriptionLifecycleTests.setUp
    def bind(self,method='upi'):
        from django.utils import timezone
        self.user.is_staff=True;self.user.is_superuser=True;self.user.save()
        self.subscription.provider_subscription_id='sub_fixture';self.subscription.save()
        self.mandate.method=method;self.mandate.save()
        data={'provider_customer_id':'cust_fixture','provider_token_id':'token_fixture','provider_payment_id':'pay_fixture','evidence_ref':'review:fixture'}
        subscriptions.request_mandate_identity(self.user,self.mandate.pk,data,self.mandate.version,uuid.uuid4())
        job=OutboxJob.objects.get(pk=__import__('billing.subscription_models',fromlist=['Mandate']).Mandate.objects.get(pk=self.mandate.pk).identity_verification_job_id)
        return job
    def provider(self,provider,method='upi'):
        c=provider.return_value
        c.fetch_subscription.return_value={'id':'sub_fixture','customer_id':'cust_fixture'}
        c.fetch_payment.return_value={'id':'pay_fixture','customer_id':'cust_fixture','token_id':'token_fixture','invoice_id':'inv_fixture','status':'captured','currency':'INR','method':method}
        c.fetch_invoice.return_value={'id':'inv_fixture','subscription_id':'sub_fixture','payment_id':'pay_fixture'}
        c.fetch_customer_token.return_value={'id':'token_fixture','method':method,'recurring':True,'recurring_details':{'status':'confirmed'}}
        return c
    def test_read_verified_binding_and_database_immutability(self):
        from django.db import IntegrityError,transaction
        job=self.bind()
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            c=self.provider(provider);self.assertTrue(process_subscription_job(job)['verified']);c.cancel_customer_token.assert_not_called()
        self.mandate.refresh_from_db();self.assertEqual(self.mandate.provider_invoice_id,'inv_fixture')
        with self.assertRaises(IntegrityError),transaction.atomic():
            type(self.mandate).objects.filter(pk=self.mandate.pk).update(provider_token_id='token_other')
    def test_cross_subscription_payment_cannot_bind(self):
        job=self.bind()
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            c=self.provider(provider);c.fetch_invoice.return_value['subscription_id']='sub_other'
            with self.assertRaises(DomainError):process_subscription_job(job)
        self.mandate.refresh_from_db();self.assertIsNone(self.mandate.identity_verified_at)
    def revoke_job(self,method):
        job=self.bind(method)
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            self.provider(provider,method);process_subscription_job(job)
        subscriptions.revoke_existing(self.user,self.mandate.pk,uuid.uuid4())
        return OutboxJob.objects.get(dedupe_key=f'mandate.revoke:{self.mandate.pk}')
    def test_upi_ack_is_pending_then_signed_cancel_event_confirms(self):
        from .models import PaymentEvent
        from .subscription_worker import process_token_cancelled_event
        job=self.revoke_job('upi')
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            c=self.provider(provider);c.cancel_customer_token.return_value={'status':'cancellation_initiated'}
            self.assertFalse(process_subscription_job(job)['revoked'])
            c.fetch_customer_token.return_value['recurring_details']['status']='cancellation_initiated'
            self.assertFalse(process_subscription_job(job)['revoked']);c.cancel_customer_token.assert_called_once()
        event=PaymentEvent.objects.create(provider='razorpay',provider_event_id='evt_fixture',body_sha256='a'*64)
        payload={'provider_mode':'test','event_name':'token.cancelled','body_sha256':'a'*64,'provider_customer_id':'cust_fixture','provider_token_id':'token_fixture'}
        self.assertTrue(process_token_cancelled_event(event,payload)['revoked'])
        self.mandate.refresh_from_db();self.assertFalse(self.mandate.revocation_pending)
        self.entitlement.refresh_from_db();self.assertIsNone(self.entitlement.revoked_at)
    def test_card_delete_is_final_but_emandate_delete_is_not(self):
        job=self.revoke_job('card')
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            c=self.provider(provider,'card');c.delete_customer_token.return_value={'deleted':True}
            self.assertTrue(process_subscription_job(job)['revoked']);c.cancel_customer_token.assert_not_called()
    def test_emandate_requires_bank_confirmation_and_unknown_outcome_is_not_reposted(self):
        job=self.revoke_job('emandate')
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            c=self.provider(provider,'emandate');c.delete_customer_token.return_value={'deleted':True}
            self.assertFalse(process_subscription_job(job)['revoked'])
            self.assertFalse(process_subscription_job(job)['revoked'])
            c.delete_customer_token.assert_called_once()
        self.mandate.refresh_from_db();self.assertTrue(self.mandate.revocation_pending)

    def test_unknown_upi_mutation_is_not_reposted(self):
        job=self.revoke_job('upi')
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            c=self.provider(provider);c.cancel_customer_token.side_effect=DomainError('provider_outcome_unknown','Fixture timeout',503)
            with self.assertRaises(DomainError):process_subscription_job(job)
            with self.assertRaises(DomainError) as error:process_subscription_job(job)
            self.assertEqual(error.exception.code,'awaiting_resolution');c.cancel_customer_token.assert_called_once()
        self.mandate.refresh_from_db();self.assertTrue(self.mandate.revocation_pending)
    def test_signed_event_wrong_mode_cannot_revoke(self):
        from .models import PaymentEvent
        from .subscription_worker import process_token_cancelled_event
        self.revoke_job('upi')
        event=PaymentEvent.objects.create(provider='razorpay',provider_event_id='evt_wrongmode',body_sha256='b'*64)
        with self.assertRaises(DomainError):process_token_cancelled_event(event,{'event_name':'token.cancelled','provider_mode':'live','body_sha256':'b'*64,'provider_customer_id':'cust_fixture','provider_token_id':'token_fixture'})
        self.mandate.refresh_from_db();self.assertIsNone(self.mandate.revoked_at)
