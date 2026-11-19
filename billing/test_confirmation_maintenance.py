"""Real maintenance/outbox state transitions with mocked merchant operations only."""
import hashlib
import hmac
import io
import json
from datetime import timedelta
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase,override_settings
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from . import test_subscription_worker as fixtures

@override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture',MERCHANT_ENTITY_CONFIG_VERSION='fixture',RAZORPAY_WEBHOOK_SECRETS=['fixture-webhook-secret'])
class ProviderConfirmationMaintenanceTests(TestCase):
    setUp=fixtures.MandateIdentityTests.setUp
    bind=fixtures.MandateIdentityTests.bind
    provider=fixtures.MandateIdentityTests.provider
    revoke_job=fixtures.MandateIdentityTests.revoke_job
    queue=fixtures.ExistingCancellationWorkerTests.queue
    def maintenance(self):call_command('run_maintenance',batch_size=1,max_seconds=20,stdout=io.StringIO())
    def isolate(self,job):OutboxJob.objects.exclude(pk=job.pk).update(status='done')
    def due(self,job):OutboxJob.objects.filter(pk=job.pk).update(not_before=timezone.now()-timedelta(seconds=1))
    def missing_token(self):
        error=DomainError('provider_request_failed','Generic provider failure',422);error.provider_http_status=404;return error
    def assert_pending(self,job):
        job.refresh_from_db();self.assertEqual(job.status,'pending');self.assertEqual(job.attempts,0)
        self.assertEqual(job.error_code,'provider_confirmation_pending');self.assertIsNone(job.completed_at)
        self.assertGreaterEqual(job.not_before,timezone.now()+timedelta(seconds=55))
    def test_upi_confirmation_survives_more_than_failure_budget_then_get_converges(self):
        job=self.revoke_job('upi');self.isolate(job)
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            client=self.provider(provider);client.cancel_customer_token.return_value={'status':'cancellation_initiated'}
            self.maintenance();self.assert_pending(job)
            client.fetch_customer_token.return_value['recurring_details']['status']='cancellation_initiated'
            for _ in range(8):
                self.due(job);self.maintenance();self.assert_pending(job)
            client.cancel_customer_token.assert_called_once();client.delete_customer_token.assert_not_called()
            client.fetch_customer_token.return_value['recurring_details']['status']='cancelled'
            self.due(job);self.maintenance();job.refresh_from_db();self.assertEqual(job.status,'done');self.assertEqual(job.error_code,'')
        self.mandate.refresh_from_db();self.assertEqual(self.mandate.status,'cancelled')
        self.entitlement.refresh_from_db();self.assertIsNone(self.entitlement.revoked_at)
    def test_emandate_404_after_ack_remains_pending_until_signed_event_then_job_finishes(self):
        job=self.revoke_job('emandate');self.isolate(job)
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            client=self.provider(provider,'emandate');client.delete_customer_token.return_value={'deleted':True}
            self.maintenance();self.assert_pending(job)
            client.fetch_customer_token.side_effect=self.missing_token()
            for _ in range(8):
                self.due(job);self.maintenance();self.assert_pending(job)
            self.mandate.refresh_from_db();self.assertTrue(self.mandate.revocation_pending);self.assertIsNone(self.mandate.revoked_at)
            client.delete_customer_token.assert_called_once()
            raw=json.dumps({'event':'token.cancelled','payload':{'token':{'entity':{'id':'token_fixture','customer_id':'cust_fixture'}}}}).encode()
            signature=hmac.new(b'fixture-webhook-secret',raw,hashlib.sha256).hexdigest()
            response=self.client.post('/api/v1/webhooks/razorpay',raw,content_type='application/json',HTTP_X_RAZORPAY_SIGNATURE=signature,HTTP_X_RAZORPAY_EVENT_ID='evt_final_bank_fixture')
            self.assertEqual(response.status_code,200);self.maintenance()
            self.mandate.refresh_from_db();self.assertIsNotNone(self.mandate.revoked_at)
            reads=client.fetch_customer_token.call_count
            self.due(job);self.maintenance();job.refresh_from_db();self.assertEqual(job.status,'done')
            self.assertEqual(client.fetch_customer_token.call_count,reads)
    def test_unknown_404_retains_normal_failure_budget_and_never_mutates_or_revokes(self):
        job=self.revoke_job('emandate');self.isolate(job)
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            client=self.provider(provider,'emandate');client.fetch_customer_token.side_effect=self.missing_token()
            for _ in range(7):self.due(job);self.maintenance()
            job.refresh_from_db();self.assertEqual(job.status,'dead');self.assertEqual(job.attempts,7)
            client.delete_customer_token.assert_not_called();client.cancel_customer_token.assert_not_called()
        self.mandate.refresh_from_db();self.assertTrue(self.mandate.revocation_pending);self.assertIsNone(self.mandate.revoked_at)
    def test_uncertain_put_never_reposts_and_retains_review_obligation(self):
        job=self.revoke_job('upi');self.isolate(job)
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            client=self.provider(provider);client.cancel_customer_token.side_effect=DomainError('provider_outcome_unknown','Fixture timeout',503)
            self.maintenance();job.refresh_from_db();self.assertEqual(job.status,'pending');self.assertEqual(job.attempts,1)
            self.due(job);self.maintenance();job.refresh_from_db();self.assertEqual(job.status,'blocked');self.assertEqual(job.error_code,'awaiting_resolution')
            client.cancel_customer_token.assert_called_once()
    def test_cycle_end_cancellation_waits_until_due_then_get_confirms_without_reposting(self):
        job=self.queue();self.isolate(job);end=self.subscription.current_period_end;paid=self.subscription.paid_through
        with patch('billing.subscription_worker.RazorpayClient') as provider:
            client=provider.return_value;client.fetch_subscription.return_value={'id':'sub_fixture','status':'active'};client.cancel_subscription.return_value={'id':'sub_fixture','status':'active'}
            self.maintenance();self.assert_pending(job);self.assertGreaterEqual(job.not_before,end+timedelta(seconds=60))
            self.maintenance();self.assertEqual(client.fetch_subscription.call_count,1)
            client.fetch_subscription.return_value={'id':'sub_fixture','status':'cancelled'}
            with patch('django.utils.timezone.now',return_value=job.not_before+timedelta(seconds=1)):self.maintenance()
            job.refresh_from_db();self.assertEqual(job.status,'done');client.cancel_subscription.assert_called_once()
            self.assertEqual(client.fetch_subscription.call_count,2)
        self.subscription.refresh_from_db();self.assertEqual(self.subscription.status,'cancelled');self.assertEqual(self.subscription.paid_through,paid)
        self.entitlement.refresh_from_db();self.assertIsNone(self.entitlement.revoked_at)
