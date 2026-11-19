import uuid
import io
from django.core.management import call_command
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from core.jobs import run_due_jobs


class QualifiedWorkerDispatchTests(TestCase):
    def test_scheduled_and_payment_recovery_jobs_dispatch_only_in_worker(self):
        handlers={
            'scheduled_publication':'operations.publication.process_scheduled_publication',
            'payment_event_reconcile':'billing.checkout.process_payment_event',
            'order_payment_reconcile':'billing.checkout.process_order_reconcile',
        }
        for kind,handler in handlers.items():
            with self.subTest(kind=kind):
                job=OutboxJob.objects.create(kind=kind,dedupe_key=str(uuid.uuid4()),payload={'reference_id':str(uuid.uuid4())},not_before=timezone.now())
                with patch(handler,return_value={'status':'synthetic_handler_result'}) as process:
                    self.assertEqual(run_due_jobs(limit=1)['processed'],1)
                    self.assertEqual(process.call_args.args[0].pk,job.pk)
                job.refresh_from_db();self.assertEqual(job.status,'done');self.assertEqual(job.result,{'status':'synthetic_handler_result'})
    def test_schedule_failure_requires_staff_review_not_automatic_retry(self):
        for code in ['scheduled_publication_invalid','scheduled_publication_held']:
            with self.subTest(code=code):
                job=OutboxJob.objects.create(kind='scheduled_publication',dedupe_key=str(uuid.uuid4()),not_before=timezone.now())
                with patch('operations.publication.process_scheduled_publication',side_effect=DomainError(code,'Synthetic release hold.',409)):
                    run_due_jobs(limit=1)
                job.refresh_from_db();self.assertEqual(job.status,'blocked');self.assertEqual(job.attempts,1)
                self.assertEqual(run_due_jobs(limit=1)['processed'],0)


class FinancialMaintenanceDispatchTests(TestCase):
    def maintain(self):
        output=io.StringIO();call_command('run_maintenance',batch_size=1,max_seconds=15,stdout=output)
        return output.getvalue()
    def job(self,kind):return OutboxJob.objects.create(kind=kind,dedupe_key=str(uuid.uuid4()),payload={'reference_id':str(uuid.uuid4())},not_before=timezone.now())
    def test_actual_maintenance_dispatches_refund_and_subscription_handlers(self):
        handlers={'refund_review':'billing.refunds.process_refund_job','refund_reconcile':'billing.refunds.process_refund_job','subscription_reconcile':'billing.subscription_worker.process_subscription_job'}
        for kind,handler in handlers.items():
            with self.subTest(kind=kind):
                job=self.job(kind)
                def process(claimed):
                    current=OutboxJob.objects.get(pk=claimed.pk)
                    self.assertEqual(current.pk,job.pk);self.assertEqual(current.status,'claimed');self.assertTrue(current.lease_owner)
                    return {'status':'synthetic_qualified_handler_result'}
                with patch(handler,side_effect=process) as provider:
                    self.maintain();provider.assert_called_once()
                job.refresh_from_db();self.assertEqual(job.status,'done');self.assertEqual(job.result,{'status':'synthetic_qualified_handler_result'})
                checkpoint=OutboxJob.objects.get(dedupe_key='scheduled-run:maintenance:v1')
                self.assertEqual(checkpoint.payload['latest']['outcome'],'success');self.assertEqual(checkpoint.payload['latest']['counts']['processed'],1)
    def test_actual_maintenance_blocks_unreviewed_or_unqualified_financial_jobs(self):
        cases=[('refund_review','refund_review_required','billing.refunds.process_refund_job'),
            ('refund_reconcile','provider_not_qualified','billing.refunds.process_refund_job'),
            ('subscription_reconcile','provider_token_identity_missing','billing.subscription_worker.process_subscription_job')]
        for kind,code,handler in cases:
            with self.subTest(code=code):
                job=self.job(kind)
                with patch(handler,side_effect=DomainError(code,'Synthetic operator resolution required.',409)) as provider:
                    self.maintain();self.maintain();provider.assert_called_once()
                job.refresh_from_db();self.assertEqual(job.status,'blocked');self.assertEqual(job.error_code,code);self.assertEqual(job.attempts,1)
    def test_actual_maintenance_retries_pending_refund_without_reclaiming_early(self):
        job=self.job('refund_reconcile');job.payload={'refund_id':str(uuid.uuid4())};job.save(update_fields=['payload']);before=timezone.now()
        with patch('billing.refunds.process_refund_job',return_value={'status':'pending','awaiting_provider_confirmation':True}) as provider:
            self.maintain();self.maintain();provider.assert_called_once()
        job.refresh_from_db();self.assertEqual(job.status,'pending');self.assertEqual(job.error_code,'provider_confirmation_pending');self.assertGreater(job.not_before,before);self.assertEqual(job.attempts,0)
