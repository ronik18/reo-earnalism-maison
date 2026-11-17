from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Run bounded due local outbox work without a separate worker stack.'

    def add_arguments(self, parser):
        parser.add_argument('--max-seconds', type=int, default=45)
        parser.add_argument('--batch-size', type=int, default=25)

    def handle(self, *args, **options):
        from core.jobs import run_due_jobs
        result = run_due_jobs(limit=max(1, min(100, options['batch_size'])),
                              max_seconds=max(1, min(45, options['max_seconds'])))
        self.stdout.write(str(result))
