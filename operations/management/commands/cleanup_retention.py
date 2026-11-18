import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Preview approved retention candidates without processing or sending outbox jobs. Use --apply for bounded cleanup.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--batch-size', type=int, default=100)
        parser.add_argument('--max-seconds', type=int, default=5)

    def handle(self, *args, **options):
        from accounts.retention import cleanup_account_retention
        result = cleanup_account_retention(
            limit=max(1, min(1000, options['batch_size'])),
            max_seconds=max(1, min(20, options['max_seconds'])),
            dry_run=not options['apply'])
        self.stdout.write(json.dumps(result, sort_keys=True))
