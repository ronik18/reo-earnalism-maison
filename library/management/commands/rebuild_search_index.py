"""Bounded repair of derived live public metadata, never publication or content edits."""
import json
from uuid import UUID
from django.core.management.base import BaseCommand,CommandError
from django.db.models import F
from library.models import Revision
from library.search import refresh_revision_search


class Command(BaseCommand):
    help='Refresh one bounded page of current live public metadata search indexes.'
    def add_arguments(self,parser):
        parser.add_argument('--limit',type=int,default=100)
        parser.add_argument('--after',default='')
    def handle(self,*args,**options):
        limit=options['limit']
        if not 1<=limit<=500:raise CommandError('Use a limit between1and500.')
        rows=Revision.objects.filter(state='live',edition__live_revision_id=F('id')).select_related('edition__work').order_by('id')
        if options['after']:
            try:after=UUID(options['after'])
            except (ValueError,TypeError):raise CommandError('The after cursor must be a revision UUID.')
            rows=rows.filter(id__gt=after)
        page=list(rows[:limit+1]);selected=page[:limit]
        for revision in selected:refresh_revision_search(revision)
        self.stdout.write(json.dumps({'indexed':len(selected),'next_cursor':str(selected[-1].id) if len(page)>limit else None}))
