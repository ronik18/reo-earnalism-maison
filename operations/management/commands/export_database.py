"""Explicit encrypted logical export; scheduling/archive delivery are separate."""
import os
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from operations.database_export import ExportError,export_database


class Command(BaseCommand):
    help='Stream a direct PostgreSQL18 logical export through age encryption and write a private manifest. Does not upload.'

    def add_arguments(self,parser):
        parser.add_argument('--encrypted',action='store_true')
        parser.add_argument('--manifest',action='store_true')
        parser.add_argument('--output-dir',default=None)
        parser.add_argument('--max-seconds',type=int,default=900)
        parser.add_argument('--max-bytes',type=int,default=2*1024**3)

    def handle(self,*args,**options):
        if not options['encrypted'] or not options['manifest']:
            raise CommandError('Both --encrypted and --manifest are required; plaintext export is unsupported.')
        url=os.getenv('MAISON_BACKUP_DATABASE_URL','')
        recipient=os.getenv('BACKUP_AGE_RECIPIENT','')
        if not url:raise CommandError('Set the separate MAISON_BACKUP_DATABASE_URL credential in the job environment.')
        try:
            report=export_database(url,recipient,options['output_dir'] or settings.BACKUP_ROOT,local=settings.LOCAL,
                                   max_seconds=options['max_seconds'],max_bytes=options['max_bytes'])
        except ExportError as error:raise CommandError(str(error)) from None
        self.stdout.write(f"Encrypted export complete: {report['ciphertext_bytes']} bytes; SHA256 {report['ciphertext_sha256']}; provider upload and restore remain unverified.")
