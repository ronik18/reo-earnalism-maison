import time
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Run bounded due local outbox work without a separate worker stack.'

    def add_arguments(self, parser):
        parser.add_argument('--max-seconds', type=int, default=45)
        parser.add_argument('--batch-size', type=int, default=25)

    def handle(self, *args, **options):
        from core.jobs import run_due_jobs
        started = time.monotonic()
        budget = max(1, min(45, options['max_seconds']))
        result = run_due_jobs(limit=max(1, min(100, options['batch_size'])),
                              max_seconds=max(1, budget - 10))
        remaining = budget - (time.monotonic() - started)
        if remaining > 0:
            from accounts.privacy import cleanup_expired_exports
            result['expired_exports'] = cleanup_expired_exports(limit=20, max_seconds=min(10, remaining))
        from accounts.services import cleanup_rate_buckets
        result['rate_counters'] = cleanup_rate_buckets(limit=1000)
        from operations.cache import cleanup_expired_references
        result['cache_references'] = cleanup_expired_references(limit=1000)
        self.stdout.write(str(result))
