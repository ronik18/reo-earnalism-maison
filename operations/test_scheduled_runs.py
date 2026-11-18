import io
from unittest.mock import patch
from django.core.management import call_command
from django.db import connection
from django.utils import timezone
from datetime import timedelta
from django.test import TestCase
from core.models import OutboxJob
from operations.scheduled_runs import start_run, finish_run


class ScheduledRunTests(TestCase):
    def receipt(self):
        return OutboxJob.objects.get(dedupe_key='scheduled-run:maintenance:v1')

    def test_single_control_row_source_counts_and_failure_preserves_success(self):
        with patch.dict('os.environ', {'RENDER_GIT_COMMIT':'a'*40}):
            first=start_run(source='scheduled')
        self.assertTrue(finish_run('maintenance',first,'success',{'processed':2,'retention':{'eligible':{'devices':3,'audit_outcomes':4,'support_payloads':5,'email':6}},'email':'private@example.test','token':123}))
        second=start_run();self.assertNotEqual(first,second)
        self.assertTrue(finish_run('maintenance',second,'failure',{'processed':0},'maintenance_failed'))
        row=self.receipt();self.assertEqual(OutboxJob.objects.count(),1);self.assertEqual(row.status,'done')
        self.assertEqual(row.payload['last_success']['run_id'],first)
        self.assertEqual(row.payload['last_success']['commit'],'a'*40)
        self.assertEqual(row.payload['last_success']['counts'],{'processed':2,'retention':{'eligible':{'devices':3,'audit_outcomes':4,'support_payloads':5}}})
        self.assertEqual(row.payload['latest']['source'],'manual');self.assertEqual(row.payload['latest']['outcome'],'failure')
        self.assertNotIn('private@example.test',str(row.payload));self.assertNotIn('token',str(row.payload))
        self.assertTrue(row.payload['latest']['finished_at'])

    def test_late_result_does_not_clobber_newer_run_or_duplicate_finish(self):
        first=start_run()
        OutboxJob.objects.filter(dedupe_key='scheduled-run:maintenance:v1').update(locked_until=timezone.now()-timedelta(seconds=1))
        second=start_run()
        self.assertFalse(finish_run('maintenance',first,'success',{'processed':99}))
        self.assertTrue(finish_run('maintenance',second,'success',{'processed':1}))
        self.assertFalse(finish_run('maintenance',second,'failure',{},'maintenance_failed'))
        row=self.receipt();self.assertEqual(row.payload['latest']['counts'],{'processed':1})
        self.assertEqual(row.payload['last_failure']['outcome'],'incomplete')
        self.assertIsNone(row.payload['last_failure']['finished_at'])

    def test_invalid_source_and_invalid_commit_are_not_recorded(self):
        with self.assertRaises(ValueError):start_run(source='private-token')
        self.assertEqual(OutboxJob.objects.count(),0)
        with patch.dict('os.environ', {'RENDER_GIT_COMMIT':'not-a-commit-private'}):run=start_run()
        finish_run('maintenance',run,'failure',{},'private secret URL')
        row=self.receipt();self.assertEqual(row.payload['latest']['commit'],'');self.assertEqual(row.payload['latest']['error_code'],'')

    def test_command_records_result_without_receipt_transaction_around_work(self):
        from operations.management.commands.run_maintenance import Command
        # TestCase itself has a wrapping transaction; command must add none
        # around its work after start_run's short receipt transaction returns.
        depth=len(connection.atomic_blocks)
        def work(self,options,result):
            self_test.assertEqual(len(connection.atomic_blocks),depth)
            result['processed']=4
        self_test=self
        with patch.object(Command,'_run',work):
            call_command('run_maintenance','--run-source=scheduled','--apply-retention',stdout=io.StringIO())
        row=self.receipt();self.assertEqual(row.payload['latest']['outcome'],'success')
        self.assertEqual(row.payload['latest']['counts'],{'processed':4})

    def test_command_failure_is_redacted_and_original_exception_reraised(self):
        from operations.management.commands.run_maintenance import Command
        def work(self,options,result):
            result['processed']=1
            raise RuntimeError('private-database-password-must-not-be-recorded')
        with patch.object(Command,'_run',work),self.assertRaises(RuntimeError):
            call_command('run_maintenance',stdout=io.StringIO())
        row=self.receipt();self.assertEqual(row.payload['latest']['outcome'],'failure')
        self.assertEqual(row.payload['latest']['counts'],{'processed':1})
        self.assertEqual(row.payload['latest']['error_code'],'maintenance_failed')
        self.assertNotIn('private-database-password',str(row.payload))

    def test_lease_blocks_manual_and_scheduled_then_expiry_recovers(self):
        first=start_run(source='manual')
        self.assertIsNone(start_run(source='scheduled'))
        self.assertIsNone(start_run(source='manual'))
        row=self.receipt();self.assertEqual(row.lease_owner,first)
        self.assertEqual(row.payload['latest']['run_id'],first)
        OutboxJob.objects.filter(pk=row.pk).update(locked_until=timezone.now()-timedelta(seconds=1))
        self.assertFalse(finish_run('maintenance',first,'success',{'processed':99}))
        second=start_run(source='scheduled');self.assertTrue(second)
        self.assertFalse(finish_run('maintenance',first,'failure',{},'maintenance_failed'))
        self.assertTrue(finish_run('maintenance',second,'success',{'processed':2}))
        row.refresh_from_db();self.assertEqual(row.lease_owner,'');self.assertIsNone(row.locked_until)
        self.assertEqual(row.payload['last_success']['run_id'],second)
        self.assertEqual(row.payload['last_failure']['run_id'],first)

    def test_command_busy_does_not_process_work(self):
        from operations.management.commands.run_maintenance import Command
        start_run()
        output=io.StringIO()
        with patch.object(Command,'_run') as work:
            call_command('run_maintenance','--run-source=scheduled',stdout=output)
        work.assert_not_called();self.assertIn("'busy': True",output.getvalue())

    def test_command_lost_completion_lease_is_nonzero_without_success_output(self):
        from django.core.management.base import CommandError
        from operations.management.commands.run_maintenance import Command
        output=io.StringIO()
        def work(self,options,result):
            result['processed']=1
            OutboxJob.objects.filter(dedupe_key='scheduled-run:maintenance:v1').update(locked_until=timezone.now()-timedelta(seconds=1))
        with patch.object(Command,'_run',work),self.assertRaises(CommandError):
            call_command('run_maintenance',stdout=output)
        self.assertEqual(output.getvalue(),'')
        row=self.receipt();self.assertEqual(row.payload['latest']['outcome'],'running')
        self.assertNotIn('last_success',row.payload)


from threading import Barrier, Thread
from django.db import close_old_connections, connections
from django.test import TransactionTestCase


class ConcurrentScheduledRunTests(TransactionTestCase):
    def test_manual_and_scheduled_claim_only_one_lease(self):
        # Existing control row avoids testing unrelated first-insert contention.
        run=start_run();finish_run('maintenance',run,'success',{})
        ready=Barrier(2);results=[];errors=[]
        def claim(source):
            close_old_connections()
            try:
                ready.wait(timeout=5)
                results.append(start_run(source=source))
            except Exception as error:errors.append(error)
            finally:connections.close_all()
        workers=[Thread(target=claim,args=(source,)) for source in ('manual','scheduled')]
        for worker in workers:worker.start()
        for worker in workers:worker.join(timeout=10)
        self.assertTrue(all(not worker.is_alive() for worker in workers));self.assertEqual(errors,[])
        self.assertEqual(len([value for value in results if value]),1)
        self.assertEqual(results.count(None),1)
        self.assertEqual(OutboxJob.objects.count(),1)
