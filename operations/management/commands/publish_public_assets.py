import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from core.api import DomainError
from operations.static_assets import publish_manifest,CHUNK_BYTES


class Command(BaseCommand):
    help='Plan static publication; --execute explicitly uploads the prepared release to the existing public R2 bucket.'
    def add_arguments(self,parser):
        parser.add_argument('--manifest')
        parser.add_argument('--collected-directory')
        parser.add_argument('--execute',action='store_true')
        parser.add_argument('--max-files',type=int,default=2000)
        parser.add_argument('--max-file-bytes',type=int,default=20*CHUNK_BYTES)
        parser.add_argument('--max-total-bytes',type=int,default=100*CHUNK_BYTES)
        parser.add_argument('--max-seconds',type=int,default=300)
    def handle(self,*args,**options):
        private=Path(settings.BASE_DIR)/'.local/public-assets'
        try:
            path=Path(options['manifest'] or private/'manifest.json')
            if path.stat().st_size>4*CHUNK_BYTES:raise CommandError('Static manifest exceeds4MiB.')
            manifest=json.loads(path.read_text())
            result=publish_manifest(options['collected_directory'] or private/'collected',manifest,execute=options['execute'],
                **{key:options[key] for key in ['max_files','max_file_bytes','max_total_bytes','max_seconds']})
        except (DomainError,OSError,ValueError) as error:raise CommandError(str(error)) from None
        self.stdout.write(json.dumps(result))
