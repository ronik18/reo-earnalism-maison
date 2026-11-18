import time
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = 'Run bounded due local outbox work without a separate worker stack.'

    def add_arguments(self, parser):
        parser.add_argument('--max-seconds', type=int, default=45)
        parser.add_argument('--batch-size', type=int, default=25)
        parser.add_argument('--run-source', choices=['manual', 'scheduled'], default='manual', help='Invocation label; provider history independently proves automatic scheduling.')
        parser.add_argument('--apply-retention', action='store_true', help='Apply approved bounded retention cleanup; otherwise report candidates only.')

    def handle(self, *args, **options):
        from operations.scheduled_runs import start_run, finish_run
        from core.api import DomainError
        run_id = start_run(source=options['run_source'])
        if run_id is None:
            self.stdout.write(str({'busy': True}))
            return
        result = {}
        try:
            self._run(options, result)
        except BaseException as error:
            code = error.code if isinstance(error, DomainError) else 'maintenance_interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'maintenance_failed'
            try:
                finish_run('maintenance', run_id, 'failure', result, code)
            except Exception:
                # Keep the original failure; an unfinished receipt is truthful
                # when the same database outage also prevents finalization.
                pass
            raise
        if not finish_run('maintenance', run_id, 'success', result):
            raise CommandError('Maintenance completion was not recorded because the run lease was lost or expired.')
        self.stdout.write(str(result))

    def _run(self, options, result):
        from core.jobs import run_due_jobs
        started = time.monotonic()
        budget = max(1, min(45, options['max_seconds']))
        result.update(run_due_jobs(limit=max(1, min(100, options['batch_size'])),
                                   max_seconds=max(1, budget - 10)))
        remaining = budget - (time.monotonic() - started)
        if remaining > 0:
            from accounts.privacy import cleanup_expired_exports
            result['expired_exports'] = cleanup_expired_exports(limit=20, max_seconds=min(10, remaining))
        from accounts.services import cleanup_rate_buckets
        result['rate_counters'] = cleanup_rate_buckets(limit=1000)
        from operations.cache import cleanup_expired_references
        result['cache_references'] = cleanup_expired_references(limit=1000)
        remaining = budget - (time.monotonic() - started)
        if remaining > 0:
            from accounts.retention import cleanup_account_retention
            result['retention'] = cleanup_account_retention(
                limit=max(1, min(100, options['batch_size'])), max_seconds=min(5, remaining),
                dry_run=not options['apply_retention'])
        return result
