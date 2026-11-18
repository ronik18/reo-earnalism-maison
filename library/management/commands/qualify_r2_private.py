"""Explicit operator-run provider qualification, never called by tests or deployment."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from core.api import DomainError
from library.r2_qualification import qualify_r2

class Command(BaseCommand):
    help='Opt-in synthetic private R2 canary upload/copy/delivery/range/CORS/expiry checks and cleanup. No public book or account changes.'
    def add_arguments(self,parser):
        parser.add_argument('--execute',action='store_true',help='Explicitly permit private synthetic canary provider requests.')
        parser.add_argument('--origin',required=True,help='Configured HTTPS PUBLIC_BASE_URL, or explicit http://127.0.0.1:<port> in LOCAL mode only.')
        parser.add_argument('--output',required=True,help='Private evidence JSON path; never contains signed URLs or credentials.')
        parser.add_argument('--expiry-seconds',type=int,default=2)
    def handle(self,*args,**options):
        if not options['execute']:raise CommandError('No provider requests made. Add --execute only for an authorized qualification run.')
        destination=Path(options['output']);destination.parent.mkdir(parents=True,exist_ok=True)
        # Never overwrite previous evidence; create private evidence before any provider request.
        try:descriptor=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except OSError:raise CommandError('Choose a new writable private evidence path. No provider requests made.') from None
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            def record(report):
                stream.seek(0);json.dump(report,stream,indent=2);stream.write('\n');stream.truncate();stream.flush();os.fsync(stream.fileno())
            record({'schema_version':1,'status':'not_started','provider_requests_made':False})
            try:report=qualify_r2(options['origin'],options['expiry_seconds'],on_prepared=record)
            except DomainError as exc:
                raise CommandError(f'{exc.code}: {exc.message}; inspect private evidence if a run had started.') from None
            record(report)
        self.stdout.write(f"Private synthetic R2 HTTP checks: {report['status']}; local_origin_only={report['local_origin_only']}; browser/CDN qualification remains separate. Evidence: {destination}")
        if report['status']!='pass':raise CommandError('Private canary qualification failed; inspect redacted evidence and cleanup status.')
