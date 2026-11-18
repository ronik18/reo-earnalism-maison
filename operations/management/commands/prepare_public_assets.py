import json
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from django.test.utils import override_settings
from core.api import DomainError
from operations.static_assets import tree_manifest,write_private_manifest,CHUNK_BYTES


class Command(BaseCommand):
    help='Prepare a deterministic Maison-only static release locally. Never contacts a provider.'
    def add_arguments(self,parser):
        parser.add_argument('--collected-directory')
        parser.add_argument('--output')
        parser.add_argument('--max-files',type=int,default=2000)
        parser.add_argument('--max-file-bytes',type=int,default=20*CHUNK_BYTES)
        parser.add_argument('--max-total-bytes',type=int,default=100*CHUNK_BYTES)
        parser.add_argument('--max-seconds',type=int,default=30)
    def handle(self,*args,**options):
        private=(Path(settings.BASE_DIR)/'.local').resolve();output=Path(options['output'] or private/'public-assets/manifest.json').resolve()
        if private not in output.parents:raise CommandError('Write the private manifest under the ignored .local directory.')
        collected=Path(options['collected_directory'] or private/'public-assets/collected')
        if not options['collected_directory']:
            with override_settings(STATIC_ROOT=collected):call_command('collectstatic',interactive=False,clear=True,verbosity=0)
        try:
            manifest=tree_manifest(collected,**{key:options[key] for key in ['max_files','max_file_bytes','max_total_bytes','max_seconds']})
            write_private_manifest(manifest,output)
        except (DomainError,OSError) as error:raise CommandError(str(error)) from None
        self.stdout.write(json.dumps({'status':'prepared','release_id':manifest['release_id'],'file_count':manifest['file_count'],'bytes_total':manifest['bytes_total']}))
