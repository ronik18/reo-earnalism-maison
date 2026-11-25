"""Build a translation intake packet from an already-written translated source file (no API calls).

  manage.py intake_translation <slug> --from <source slug> --source translated.json --method ai|ai_edited
      [--credit "Editor Name"] --model <model id> --title ... --description ... [--replace] [--root DIR]

The translated text is produced by Claude in-session and passed in as a book_source file. This writes
library/intake/<slug>/{source,manifest,translation}.json and
docs/evidence/publication-clearance-<slug>-draft.json (status DRAFT_PENDING_OWNER_APPROVAL). Nothing is approved
or published; the later publish step reads translation.json to set the Edition translation fields.
"""
import datetime
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from operations.book_source import MANIFEST_SCHEMA, SOURCE_SCHEMA, SourceError, read_source_bytes, validate_manifest
from operations.intake.wikisource import CLEARANCE_SCHEMA

ROOT = Path(__file__).resolve().parents[3]


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise CommandError(f'SOURCE_PACKET_UNREADABLE: {path}') from error


class Command(BaseCommand):
    help = 'Build an AI or editor-revised translation packet and clearance draft from a translated source file.'

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--from', dest='source_slug', required=True)
        parser.add_argument('--source', required=True, help='Translated book_source JSON file.')
        parser.add_argument('--method', required=True, choices=['ai', 'ai_edited'])
        parser.add_argument('--credit', default='', help='Credited human editor (required for ai_edited).')
        parser.add_argument('--model', required=True)
        parser.add_argument('--title', required=True)
        parser.add_argument('--description', required=True)
        parser.add_argument('--replace', action='store_true', help='Overwrite an existing packet or clearance draft.')
        parser.add_argument('--root', default=str(ROOT), help='Repository root to read and write under (tests).')

    def handle(self, *args, **o):
        slug, source_slug, method, credit = o['slug'], o['source_slug'], o['method'], o['credit'].strip()
        if method == 'ai_edited' and not credit:
            raise CommandError('CREDIT_REQUIRED: --credit is required for ai_edited')
        if method == 'ai' and credit:
            raise CommandError('CREDIT_NOT_ALLOWED: --credit applies only to ai_edited')
        if slug == source_slug:
            raise CommandError('SAME_SLUG: the translation slug must differ from its source slug')
        root = Path(o['root'])
        source_dir = root / 'library' / 'intake' / source_slug
        source_manifest = _load(source_dir / 'manifest.json')
        source_sha = source_manifest['source']['sha256']
        original = (source_dir / 'source.json').read_bytes()
        if hashlib.sha256(original).hexdigest() != source_sha:
            raise CommandError('SOURCE_PACKET_HASH_MISMATCH')
        clearance_path = next((p for p in (root / 'docs/evidence' / f'publication-clearance-{source_slug}.json',
                                           root / 'docs/evidence' / f'publication-clearance-{source_slug}-draft.json')
                               if p.is_file()), None)
        if clearance_path is None:
            raise CommandError(f'SOURCE_CLEARANCE_MISSING: no clearance record for {source_slug}')
        source_book = _load(clearance_path)['books'][source_slug]
        try:
            raw = Path(o['source']).read_bytes()
            translated = read_source_bytes(raw)
        except (OSError, SourceError) as error:
            raise CommandError(f'TRANSLATED_SOURCE_INVALID: {error}') from error
        language = translated['language']
        if language == source_manifest['edition']['language']:
            raise CommandError('SAME_LANGUAGE: the translation must be in a different language from its source')
        today = datetime.date.today().isoformat()
        sha = hashlib.sha256(raw).hexdigest()
        creators = source_manifest['work']['creators']
        credit_text = f'edited by {credit}' if method == 'ai_edited' else 'unedited'
        manifest = {
            'schema': MANIFEST_SCHEMA,
            'project_id': f'{slug}-translation-{today.replace("-", "")}',
            'work': {'slug': slug, 'title': o['title'], 'creators': list(creators), 'house': source_manifest['work']['house']},
            'edition': {'slug': slug, 'language': language, 'title': o['title'], 'description': o['description']},
            'source': {'sha256': sha, 'bytes': len(raw), 'content_type': 'application/json', 'format': SOURCE_SCHEMA},
            'provenance': {
                'source_ref': source_manifest['provenance']['source_ref'],
                'source_edition': (f'Translation of packet {source_slug} (source sha256 {source_sha}); method {method}; '
                                   f'model {o["model"]}; {today}. Source edition: {source_manifest["provenance"]["source_edition"]}'),
                'rights_note': (f'The translation is a new work by Earnalism (method {method}, {credit_text}; model {o["model"]}) '
                                f'of a public-domain source. Source rights: {source_manifest["provenance"]["rights_note"]} '
                                'Draft: owner approval of the clearance record and a cover with owner-held provenance are still required.'),
                'rights_evidence_refs': [f'reo-earnalism-maison:docs/evidence/publication-clearance-{slug}-draft.json']}}
        try:
            validate_manifest(manifest)
        except SourceError as error:
            raise CommandError(f'MANIFEST_INVALID: {error}') from error
        translation = {'translated_from': source_slug, 'method': method, 'credit': credit, 'model': o['model'],
                       'date': today, 'source_sha256': source_sha}
        source_facts = {key: source_book[key] for key in ('author', 'author_died', 'first_published', 'territory_terms')
                        if key in source_book}
        book = {key: value for key, value in source_book.items()
                if key not in ('review_notes', 'term_screen_verdict', 'territory_terms', 'author_died', 'first_published')}
        book.update(work=o['title'], source_sha256=sha, source_bytes=len(raw),
                    translated_from=source_slug, translation_method=method, translation_model=o['model'],
                    term_screen_verdict=None, term_screen_source_text=source_book.get('term_screen_verdict'),
                    source_text=source_facts,
                    review_notes=['Generated translation draft; a human must review it before approval.',
                                  'Translation is a new work; its own clearance needs owner review.'])
        source_licence = source_book.get('text_source_licence')
        if source_licence:
            book['text_source_licence'] = dict(source_licence, scope=f'{source_licence.get("scope", "")} Applies to the source text only; the translation is a new work by Earnalism.'.strip())
        clearance = {
            'schema': CLEARANCE_SCHEMA,
            'status': 'DRAFT_PENDING_OWNER_APPROVAL',
            'recorded_on': today,
            'owner_instruction': {'date': None, 'text': None,
                                  'effect': 'Draft generated by intake_translation. No owner decision is recorded; nothing is cleared.'},
            'approval': {'approved': False, 'approved_on': None, 'approved_by': None,
                         'still_required': ['owner approval of this clearance record',
                                            'front/back cover with owner-held provenance']},
            'territories': _load(clearance_path).get('territories', []),
            'formats': ['reader'],
            'actions': ['read', 'preview'],
            'downloads': False,
            'audio_video': 'Not covered. Audio and video need their own production record.',
            'books': {slug: book}}
        packet_dir = root / 'library' / 'intake' / slug
        evidence = root / 'docs' / 'evidence' / f'publication-clearance-{slug}-draft.json'
        if not o['replace'] and (packet_dir.exists() or evidence.exists()):
            raise CommandError(f'PACKET_EXISTS: {packet_dir} or {evidence} already exists; pass --replace to overwrite')
        packet_dir.mkdir(parents=True, exist_ok=True)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        (packet_dir / 'source.json').write_bytes(raw)
        for path, value in ((packet_dir / 'manifest.json', manifest), (packet_dir / 'translation.json', translation),
                            (evidence, clearance)):
            path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        self.stdout.write(f'{slug}: {language} translation of {source_slug} ({method}), sha256 {sha}. '
                          f'Wrote {packet_dir} and {evidence}')
