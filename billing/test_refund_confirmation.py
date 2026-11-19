"""Business-pending refunds remain GET-reconcilable; providers are mocked."""
import io
from datetime import timedelta
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase,override_settings
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from . import test_refund_worker as fixtures

@override_settings(RAZORPAY_ENABLED=True,RAZORPAY_MODE='test',RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture',MERCHANT_ENTITY_CONFIG_VERSION='fixture')
class RefundConfirmationMaintenanceTests(TestCase):
    setUp=fixtures.RefundWorkerTests.setUp
    order=fixtures.RefundWorkerTests.order
    facts=fixtures.RefundWorkerTests.facts
    approved=fixtures.RefundWorkerTests.approved
    response=fixtures.RefundWorkerTests.response
    def maintain(self):call_command('run_maintenance',batch_size=1,max_seconds=20,stdout=io.StringIO())
    def due(self,job):OutboxJob.objects.filter(pk=job.pk).update(not_before=timezone.now()-timedelta(seconds=1))
    def test_more_than_seven_pending_polls_then_processed_use_one_post_and_preserve_amount_access(self):
        order,refund,job=self.approved(3000)
        with patch('billing.refunds.RazorpayClient') as provider:
            client=provider.return_value;client.create_refund.return_value=self.response(refund,'pending');client.fetch_refund.return_value=self.response(refund,'pending')
            self.maintain()
            for _ in range(8):
                self.due(job);self.maintain();job.refresh_from_db();refund.refresh_from_db()
                self.assertEqual(job.status,'pending');self.assertEqual(job.attempts,0);self.assertEqual(job.error_code,'provider_confirmation_pending')
                self.assertIsNone(job.completed_at);self.assertEqual(refund.status,'pending');self.assertEqual(refund.amount_minor,3000)
                self.assertIsNone(order.entitlements.get().revoked_at)
                self.assertGreater(job.not_before,timezone.now()+timedelta(seconds=55))
            client.create_refund.assert_called_once()
            client.fetch_refund.return_value=self.response(refund)
            self.due(job);self.maintain();job.refresh_from_db();self.assertEqual(job.status,'done');self.assertEqual(job.error_code,'')
            client.create_refund.assert_called_once()
        refund.refresh_from_db();self.assertEqual(refund.status,'processed');self.assertEqual(refund.amount_minor,3000)
        self.assertIsNone(order.entitlements.get().revoked_at)
    def test_acknowledged_pending_resets_old_failure_debt_but_transport_failures_remain_bounded(self):
        order,refund,job=self.approved(3000)
        OutboxJob.objects.filter(pk=job.pk).update(attempts=5)
        with patch('billing.refunds.RazorpayClient') as provider:
            client=provider.return_value;client.create_refund.return_value=self.response(refund,'pending')
            self.maintain();job.refresh_from_db();self.assertEqual(job.attempts,0)
            client.fetch_refund.side_effect=DomainError('provider_outcome_unknown','Fixture network unavailable',503)
            for _ in range(7):self.due(job);self.maintain()
            job.refresh_from_db();self.assertEqual(job.status,'dead');self.assertEqual(job.attempts,7)
            client.create_refund.assert_called_once()
        refund.refresh_from_db();self.assertEqual(refund.status,'pending');self.assertEqual(refund.amount_minor,3000)
        self.assertIsNone(order.entitlements.get().revoked_at)
    def test_review_job_with_exact_approved_refund_can_defer_and_reconcile_without_another_post(self):
        _,refund,job=self.approved(3000);job.kind='refund_review';job.save(update_fields=['kind'])
        with patch('billing.refunds.RazorpayClient') as provider:
            client=provider.return_value;client.create_refund.return_value=self.response(refund,'pending')
            self.maintain();job.refresh_from_db();self.assertEqual(job.status,'pending');self.assertEqual(job.attempts,0)
            client.fetch_refund.return_value=self.response(refund)
            self.due(job);self.maintain();job.refresh_from_db();self.assertEqual(job.status,'done')
            client.create_refund.assert_called_once();client.fetch_refund.assert_called_once()
