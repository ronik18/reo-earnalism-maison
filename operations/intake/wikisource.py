"""Reusable Wikisource intake: validated page wikitext to a reviewable book packet.

Pure functions, no network. The conversion rules are the ones recorded for the
ক্ষুধিত পাষাণ packet (library/intake/kshudhita-pashan/manifest.json provenance.source_edition).
The output is a draft: the clearance record stays DRAFT_PENDING_OWNER_APPROVAL and nothing here
publishes or approves anything.
"""
import datetime
import hashlib
import json
import re

from library.term_check import screen
from operations.book_source import MANIFEST_SCHEMA, SOURCE_SCHEMA, read_source_bytes, validate_manifest

BREAK = '\x00'
NOINCLUDE = re.compile(r'<noinclude>.*?</noinclude>', re.S)
MARKUP = re.compile(r'\{\{|\}\}|\[\[|\]\]|\{\||\|\}|</?[A-Za-z!][^>]*>|\'\'|&[A-Za-z#0-9]+;')
CLEARANCE_SCHEMA = 'earnalism.publication-clearance-evidence.v1'
LICENCE_NOTE = ('Wikisource transcription layer reused under CC BY-SA 4.0 with attribution; '
                'ShareAlike applies to the delivered transcription only.')


class IntakeError(ValueError):
    def __init__(self, code, detail=''):
        super().__init__(f'{code}: {detail}' if detail else code)
        self.code = code


VERSE_MARK, HEADING_MARK, LINE_SEP = '\x01', '\x02', '\x03'
CONTROLS = re.compile('[\x00-\x03]')
POEM = re.compile(r'\{\{Block center\|<poem>(.*?)</poem>\}\}', re.S)
RULE_LINE = re.compile(r'^[ \t]*\{\{rule\|[^{}\n]*\}\}[ \t]*$', re.M)
HEADING_TEXT = r'([^{}|<>\n]+?)'
HEADING = re.compile(
    r'(?:(?<=\n\n)|\A)[ \t]*(?:\{\{কেন্দ্র\|\{\{larger\|' + HEADING_TEXT + r'\}\}\}\}'
    r'|\{\{কেন্দ্র\|' + HEADING_TEXT + r'\}\}|\{\{larger\|' + HEADING_TEXT + r'\}\})[ \t]*(?=\n[ \t]*\n|\n*\Z)')
COLLECTION_HEADER = r'\{\{কেন্দ্র\|\{\{x-larger\|গল্প-দশক।\}\}\}\}\s*'


def _title_pattern(title):
    t = re.escape(title) + '।?'
    return re.compile(r'(?:' + COLLECTION_HEADER + r'\{\{কেন্দ্র\|\{\{larger\|' + t + r'\}\}\}\}'
                      r'|\{\{কেন্দ্র\|\{\{x-larger\|' + t + r'\}\}\}\})')


def _verse(match):
    lines = [line.strip() for line in match.group(1).split('\n')]
    if not lines or not all(lines):
        raise IntakeError('UNKNOWN_MARKUP', 'poem with an empty line')
    for line in lines:
        found = MARKUP.search(line)
        if found:
            raise IntakeError('UNKNOWN_MARKUP', found.group(0))
    return BREAK + VERSE_MARK + LINE_SEP.join(lines) + VERSE_MARK + BREAK


def _heading(match):
    return BREAK + HEADING_MARK + next(g for g in match.groups() if g is not None) + HEADING_MARK + BREAK


def _page_text(page, title, first):
    text = NOINCLUDE.sub('', page['wikitext']).replace('\ufeff', '')
    found = CONTROLS.search(text)
    if found:
        raise IntakeError('UNKNOWN_MARKUP', repr(found.group(0)))
    if first:
        text, found = _title_pattern(title).subn('', text, count=1)
        if not found:
            raise IntakeError('TITLE_LINE_MISSING', title)
    text = POEM.sub(_verse, text)
    text = RULE_LINE.sub(BREAK, text)
    text = HEADING.sub(_heading, text)
    closed = bool(re.search(r'\{\{nop\}\}\s*\Z', text))
    text = text.replace('{{nop}}', '')
    text = re.sub(r'\{\{gap\}\}|\n[ \t]*\n', BREAK, text).strip()
    return text + BREAK if closed else text


def pages_to_paragraphs(pages, *, title, keep_hyphen_after=frozenset()):
    """Join validated pages into [{"kind", "text"}] paragraphs using the recorded conversion rules."""
    if not pages:
        raise IntakeError('NO_PAGES')
    unknown = set(keep_hyphen_after) - {page.get('page') for page in pages}
    if unknown:
        raise IntakeError('UNKNOWN_PAGE_LABEL', ', '.join(sorted(unknown)))
    stream = ''
    for index, page in enumerate(pages):
        if page.get('quality') != 4:
            raise IntakeError('PAGE_NOT_VALIDATED', str(page.get('page')))
        text = _page_text(page, title, index == 0)
        if index and not text.startswith(BREAK) and not stream.endswith(BREAK):
            if stream.endswith('-'):
                if pages[index - 1]['page'] not in keep_hyphen_after:
                    stream = stream[:-1]
            else:
                stream += ' '
        stream += text
    paragraphs = []
    for part in stream.split(BREAK):
        if part.startswith(VERSE_MARK):
            paragraphs.append({'kind': 'verse', 'text': part[1:-1].replace(LINE_SEP, '\n')})
            continue
        kind = 'heading' if part.startswith(HEADING_MARK) else 'paragraph'
        text = ' '.join(part.strip(HEADING_MARK).split())
        if text:
            paragraphs.append({'kind': kind, 'text': text})
    if not paragraphs:
        raise IntakeError('NO_TEXT')
    for paragraph in paragraphs:
        found = MARKUP.search(paragraph['text'])
        if found:
            raise IntakeError('UNKNOWN_MARKUP', found.group(0))
    return paragraphs


def source_bytes(source):
    return (json.dumps(source, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


def build_packet(slug, title, pages, *, source_ref, source_edition, house, description,
                 first_published, author_died, creators=None, today=None, keep_hyphen_after=frozenset()):
    """Return {"source", "manifest", "clearance"}.

    `creators` is needed by the manifest and is required at runtime; `today` is injectable for tests.
    """
    if not creators:
        raise IntakeError('CREATORS_REQUIRED')
    today = today or datetime.date.today()
    paragraphs = pages_to_paragraphs(pages, title=title, keep_hyphen_after=frozenset(keep_hyphen_after))
    source = {'schema': SOURCE_SCHEMA, 'language': 'bn', 'units': [{
        'key': 'chapter-001', 'title': title, 'kind': 'chapter',
        'paragraphs': paragraphs}]}
    raw = source_bytes(source)
    read_source_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    screened = screen({'author_died': author_died, 'first_published': first_published}, today.year)
    verdict = screened['verdict']
    manifest = {
        'schema': MANIFEST_SCHEMA,
        'project_id': f'{slug}-wikisource-{today:%Y%m%d}',
        'work': {'slug': slug, 'title': title, 'creators': list(creators), 'house': house},
        'edition': {'slug': slug, 'language': 'bn', 'title': title, 'description': description},
        'source': {'sha256': sha, 'bytes': len(raw), 'content_type': 'application/json', 'format': SOURCE_SCHEMA},
        'provenance': {
            'source_ref': source_ref,
            'source_edition': source_edition,
            'rights_note': (f'{creators[0]} died {author_died}; first published {first_published}. '
                            f'Term screen verdict for {today.year}: {verdict}. {LICENCE_NOTE} Draft: owner '
                            'approval of the clearance record and a cover with owner-held provenance are still required.'),
            'rights_evidence_refs': [f'reo-earnalism-maison:docs/evidence/publication-clearance-{slug}-draft.json']}}
    validate_manifest(manifest)
    scan_pages = []
    for page in pages:
        entry = {'page': page['page'], 'revision': page['revision']}
        if page.get('timestamp'):
            entry['timestamp'] = page['timestamp']
        entry['quality'] = page['quality']
        scan_pages.append(entry)
    clearance = {
        'schema': CLEARANCE_SCHEMA,
        'status': 'DRAFT_PENDING_OWNER_APPROVAL',
        'recorded_on': today.isoformat(),
        'owner_instruction': {'date': None, 'text': None,
                              'effect': 'Draft generated by intake_wikisource. No owner decision is recorded; nothing is cleared.'},
        'approval': {'approved': False, 'approved_on': None, 'approved_by': None,
                     'still_required': ['owner approval of this clearance record',
                                        'front/back cover with owner-held provenance']},
        'territories': list(screened['territory_terms']),
        'formats': ['reader'],
        'actions': ['read', 'preview'],
        'downloads': False,
        'audio_video': 'Not covered. Audio and video need their own production record.',
        'books': {slug: {
            'work': title,
            'author': creators[0],
            'author_died': author_died,
            'first_published': first_published,
            'source_edition': source_edition,
            'text_source_ref': source_ref,
            'text_source_licence': {
                'license': 'CC-BY-SA-4.0',
                'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
                'attribution': f'{title} by {creators[0]}; Bengali Wikisource transcription and its contributors.',
                'contributors_url': re.sub(r'&oldid=\d+', '&action=history', source_ref),
                'scope': 'Applies to the source-derived transcription and formatting only, not covers, Earnalism branding or software.'},
            'scan_pages': scan_pages,
            'source_sha256': sha,
            'source_bytes': len(raw),
            'territory_terms': screened['territory_terms'],
            'term_screen_verdict': verdict,
            'review_notes': ['Generated draft; read the text against the scan before approval.']}}}
    return {'source': source, 'manifest': manifest, 'clearance': clearance}
