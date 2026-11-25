"""Queue the committed intake packets on the Monday review page of the database this runs against (production).

The intake commands queue what they write into the developer's own database; production only receives the packet files
by deployment. Run `python manage.py queue_intake_packets` there (a Render one-off job). For every library/intake/<slug>/
packet it queues, idempotently and bound to each file's current sha256 (operations.review.queue):
the clearance draft (kind 'clearance') unless the record is already owner-approved in the file, cover_provenance.json
(kind 'cover'), and for a translation manifest.json and translation.json (kind 'edition'). Never writes files.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.api import DomainError
from operations import review
from operations.models import ReviewItem


def _json(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


class Command(BaseCommand):
    help = 'Queue committed library/intake packets (clearance, cover, translation edition files) for owner review.'

    def add_arguments(self, parser):
        parser.add_argument('--slug', action='append', default=[], help='Only this packet (repeatable).')
        parser.add_argument('--dry-run', action='store_true', help='Report only; queue nothing.')

    def handle(self, *args, **o):
        root = Path(settings.BASE_DIR)
        intake = root / 'library' / 'intake'
        folders = sorted(p for p in intake.glob('*/') if (p / 'manifest.json').is_file()) if intake.is_dir() else []
        wanted = set(o['slug'])
        unknown = wanted - {p.name for p in folders}
        if unknown:
            raise CommandError(f"PACKET_NOT_FOUND: {', '.join(sorted(unknown))}")
        for folder in folders:
            if wanted and folder.name not in wanted:
                continue
            self._packet(root, folder, o['dry_run'])

    def _packet(self, root, folder, dry_run):
        slug = folder.name
        manifest = _json(folder / 'manifest.json') or {}
        edition = manifest.get('edition') or {}
        summary = {'edition_slug': edition.get('slug') or slug, 'title': edition.get('title') or slug}
        clearance = root / 'docs' / 'evidence' / f'publication-clearance-{slug}-draft.json'
        entries = []
        if clearance.is_file():
            record = _json(clearance) or {}
            approval = record.get('approval') or {}
            if (record.get('status') == 'OWNER_APPROVED' and approval.get('approved') is True
                    and not approval.get('still_required')):
                self.stdout.write(f'{slug}: clearance skipped (already owner-approved in the file)')
            else:
                entries.append(('clearance', clearance))
        else:
            self.stdout.write(f'{slug}: clearance skipped (no draft record)')
        if (folder / 'cover_provenance.json').is_file():
            entries.append(('cover', folder / 'cover_provenance.json'))
        else:
            self.stdout.write(f'{slug}: cover skipped (no cover_provenance.json)')
        if (folder / 'translation.json').is_file():  # a plain source packet's manifest is not an edition review item
            entries += [('edition', folder / 'manifest.json'), ('edition', folder / 'translation.json')]
        for kind, path in entries:
            try:
                ref = review.review_ref(path)
                sha = review._file_sha256(ref)
                if ReviewItem.objects.filter(kind=kind, ref=ref, sha256=sha).exists():
                    self.stdout.write(f'{slug}: {kind} {ref} already queued')
                elif dry_run:
                    self.stdout.write(f'{slug}: {kind} {ref} would queue')
                else:
                    review.queue(kind, ref, sha, summary)
                    self.stdout.write(f'{slug}: {kind} {ref} queued')
            except DomainError as error:
                self.stdout.write(f'{slug}: {kind} {path.name} skipped ({error.code})')
