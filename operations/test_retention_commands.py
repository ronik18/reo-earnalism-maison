import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class RetentionCommandTests(SimpleTestCase):
    def test_standalone_preview_does_not_process_jobs(self):
        output = io.StringIO()
        with patch('accounts.retention.cleanup_account_retention', return_value={'dry_run': True}) as cleanup, patch('core.jobs.run_due_jobs') as jobs:
            call_command('cleanup_retention', stdout=output)
        cleanup.assert_called_once_with(limit=100, max_seconds=5, dry_run=True)
        jobs.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), {'dry_run': True})

    def test_apply_is_explicit_and_bounds_are_clamped(self):
        with patch('accounts.retention.cleanup_account_retention', return_value={}) as cleanup:
            call_command('cleanup_retention', '--apply', '--batch-size=99999', '--max-seconds=999', stdout=io.StringIO())
        cleanup.assert_called_once_with(limit=1000, max_seconds=20, dry_run=False)

    def test_maintenance_previews_unless_apply_switch_is_provided(self):
        for apply in (False, True):
            with self.subTest(apply=apply), patch('core.jobs.run_due_jobs', return_value={'processed': 0}), patch('accounts.privacy.cleanup_expired_exports', return_value={}), patch('accounts.services.cleanup_rate_buckets', return_value={}), patch('operations.cache.cleanup_expired_references', return_value={}), patch('accounts.retention.cleanup_account_retention', return_value={}) as cleanup:
                call_command('run_maintenance', apply_retention=apply, stdout=io.StringIO())
                self.assertEqual(cleanup.call_args.kwargs['dry_run'], not apply)
                self.assertLessEqual(cleanup.call_args.kwargs['max_seconds'], 5)
