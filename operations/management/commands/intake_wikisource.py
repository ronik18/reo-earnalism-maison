"""Build a book intake packet from a saved MediaWiki API response (no network).

  manage.py intake_wikisource <slug> --api-json pages.json --title ... --source-ref ...
      --source-edition ... --house golpo --description ... --first-published 1895 --author-died 1941
      --creator "..." [--keep-hyphen-after <page label>]... [--write]

Without --write it only reports. With --write it writes library/intake/<slug>/{source,manifest}.json
and docs/evidence/publication-clearance-<slug>-draft.json (status DRAFT_PENDING_OWNER_APPROVAL).
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from operations.intake.wikisource import IntakeError, build_packet, source_bytes

ROOT = Path(__file__).resolve().parents[3]


def api_pages(data):
    pages = []
    try:
        for page in data['query']['pages']:
            revision = page['revisions'][0]
            pages.append({'page': page['title'].rsplit('/', 1)[-1], 'revision': revision['revid'],
                          'timestamp': revision.get('timestamp'),
                          'quality': (page.get('proofread') or {}).get('quality', 0),
                          'wikitext': revision['slots']['main']['content']})
    except (KeyError, IndexError, TypeError, AttributeError):
        raise IntakeError('API_RESPONSE_INVALID') from None
    return pages


class Command(BaseCommand):
    help = 'Build a Wikisource book intake packet and clearance draft from a saved API response.'

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--api-json', required=True)
        parser.add_argument('--title', required=True)
        parser.add_argument('--source-ref', required=True)
        parser.add_argument('--source-edition', required=True)
        parser.add_argument('--house', required=True)
        parser.add_argument('--description', required=True)
        parser.add_argument('--first-published', type=int, required=True)
        parser.add_argument('--author-died', type=int, required=True)
        parser.add_argument('--creator', action='append', required=True)
        parser.add_argument('--keep-hyphen-after', action='append', default=[], metavar='PAGE')
        parser.add_argument('--write', action='store_true')
        parser.add_argument('--root', default=str(ROOT), help='Repository root to write under (tests).')

    def handle(self, *args, **o):
        slug = o['slug']
        try:
            data = json.loads(Path(o['api_json']).read_text(encoding='utf-8'))
            packet = build_packet(
                slug, o['title'], api_pages(data), source_ref=o['source_ref'],
                source_edition=o['source_edition'], house=o['house'], description=o['description'],
                first_published=o['first_published'], author_died=o['author_died'],
                creators=o['creator'], keep_hyphen_after=frozenset(o['keep_hyphen_after']))
        except (IntakeError, ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        manifest = packet['manifest']
        self.stdout.write(
            f"{slug}: {len(packet['source']['units'][0]['paragraphs'])} paragraphs, "
            f"sha256 {manifest['source']['sha256']}, {manifest['source']['bytes']} bytes, "
            f"term screen {packet['clearance']['books'][slug]['term_screen_verdict']}")
        if not o['write']:
            self.stdout.write('Dry run; pass --write to write the packet and the clearance draft.')
            return
        root = Path(o['root'])
        packet_dir = root / 'library' / 'intake' / slug
        evidence = root / 'docs' / 'evidence' / f'publication-clearance-{slug}-draft.json'
        packet_dir.mkdir(parents=True, exist_ok=True)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        (packet_dir / 'source.json').write_bytes(source_bytes(packet['source']))
        for path, value in ((packet_dir / 'manifest.json', manifest), (evidence, packet['clearance'])):
            path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        self.stdout.write(f'Wrote {packet_dir} and {evidence}')
