"""Wikisource intake rules, packet shape and the ক্ষুধিত পাষাণ regression (fixtures inline)."""
import datetime
import hashlib
import json
import os
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from .book_source import read_source_bytes, validate_manifest
from .intake.wikisource import IntakeError, build_packet, pages_to_paragraphs

ROOT = Path(__file__).resolve().parent.parent
TITLE = 'ক্ষুধিত পাষাণ'
NO_BREAK = '​'
# Three pages in the recorded API shape: a title page ending in a hyphen, a page ending {{nop}}, a {{gap}} page.
PAGES = [
    {'page': '১৭৩', 'revision': 1505887, 'quality': 4, 'timestamp': '2020-11-15T16:43:18Z',
     'wikitext': '<noinclude><pagequality level="4" user="x" /></noinclude>﻿﻿{{কেন্দ্র|{{x-larger|ক্ষুধিত পাষাণ।}}}}\n\n\n'
                 'আমি এবং আমার আত্মীয় কলিকাতায় ফিরিয়া আসিতেছিলাম। তাহার প্রতিবিম্ব আলো-<noinclude></noinclude>'},
    {'page': '১৭৪', 'revision': 1505889, 'quality': 4, 'timestamp': '2020-11-15T16:43:19Z',
     'wikitext': '<noinclude><pagequality level="4" user="x" />{{rh||ক্ষুধিত পাষাণ।|১৬৬}}</noinclude>'
                 'ড়িত হইল।\n{{nop}}<noinclude></noinclude>'},
    {'page': '১৭৫', 'revision': 1505890, 'quality': 4, 'timestamp': '2020-11-15T16:43:21Z',
     'wikitext': '<noinclude><pagequality level="4" user="x" />{{rh|১৬৭|গল্প-দশক।|}}</noinclude>'
                 '{{gap}}সঙ্গিনীহীন মাশুল-<noinclude></noinclude>'},
    {'page': '১৭৬', 'revision': 1924706, 'quality': 4, 'timestamp': '2025-11-27T18:13:55Z',
     'wikitext': '<noinclude><pagequality level="4" user="x" /></noinclude>কালেক্টরের  বাসস্থান।\n\n{{gap}}শেষ।<noinclude>{{left|১৫}}</noinclude>'},
]
KW = dict(source_ref='https://bn.wikisource.org/w/index.php?title=T&oldid=1', source_edition='Test edition, 1895.',
          house='golpo', description='বিবরণ', first_published=1895, author_died=1941,
          creators=['রবীন্দ্রনাথ ঠাকুর'], today=datetime.date(2026, 11, 25))


class WikisourceRulesTests(SimpleTestCase):
    def test_rules_match_the_kshudhita_pashan_packet(self):
        paragraphs = pages_to_paragraphs(PAGES, title=TITLE, keep_hyphen_after=frozenset({'১৭৫'}))
        self.assertEqual(paragraphs, [
            'আমি এবং আমার আত্মীয় কলিকাতায় ফিরিয়া আসিতেছিলাম। তাহার প্রতিবিম্ব আলোড়িত হইল।',
            'সঙ্গিনীহীন মাশুল-কালেক্টরের বাসস্থান।',
            'শেষ।'])
        text = ''.join(paragraphs)
        self.assertNotIn(NO_BREAK, text)
        self.assertNotIn('﻿', text)
        self.assertNotIn('{{', text)

    def test_hyphen_is_dropped_unless_the_page_is_listed(self):
        self.assertIn('মাশুলকালেক্টরের', ' '.join(pages_to_paragraphs(PAGES, title=TITLE)))

    def test_quality_below_four_is_refused(self):
        pages = [dict(PAGES[0]), dict(PAGES[1], quality=3)]
        with self.assertRaises(IntakeError) as caught:
            pages_to_paragraphs(pages, title=TITLE)
        self.assertEqual(caught.exception.code, 'PAGE_NOT_VALIDATED')

    def test_leftover_markup_is_refused(self):
        for bad in ('দেখুন [[অন্য]] পাতা।', 'টীকা<ref>x</ref>।', "''তির্যক''", '{{অজানা|x}}'):
            with self.subTest(bad=bad):
                pages = [dict(PAGES[1], wikitext=PAGES[1]['wikitext'] + bad)]
                with self.assertRaises(IntakeError) as caught:
                    pages_to_paragraphs(pages, title=TITLE)
                self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_packet_manifest_validates_and_binds_source_sha(self):
        packet = build_packet('test-book', TITLE, PAGES, keep_hyphen_after=frozenset({'১৭৫'}), **KW)
        validate_manifest(packet['manifest'])
        manifest = packet['manifest']
        self.assertEqual(manifest['project_id'], 'test-book-wikisource-20261125')
        self.assertEqual((manifest['work']['slug'], manifest['edition']['slug']), ('test-book', 'test-book'))
        self.assertEqual(manifest['edition']['description'], 'বিবরণ')
        self.assertEqual(manifest['provenance']['rights_evidence_refs'],
                         ['reo-earnalism-maison:docs/evidence/publication-clearance-test-book-draft.json'])
        from .intake.wikisource import source_bytes
        raw = source_bytes(packet['source'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest['source']['sha256'])
        self.assertEqual(len(raw), manifest['source']['bytes'])
        read_source_bytes(raw)

    def test_clearance_is_a_draft_with_the_term_screen(self):
        clearance = build_packet('test-book', TITLE, PAGES, **KW)['clearance']
        self.assertEqual(clearance['status'], 'DRAFT_PENDING_OWNER_APPROVAL')
        self.assertFalse(clearance['approval']['approved'])
        book = clearance['books']['test-book']
        self.assertEqual(book['term_screen_verdict'], 'screen_pass')
        self.assertEqual(len(book['scan_pages']), 4)
        self.assertEqual(clearance['territories'], list(book['territory_terms']))

    def test_creators_are_required(self):
        kw = dict(KW, creators=None)
        with self.assertRaises(IntakeError) as caught:
            build_packet('x', TITLE, PAGES, **kw)
        self.assertEqual(caught.exception.code, 'CREATORS_REQUIRED')


class WikisourceCommandTests(SimpleTestCase):
    def _api(self, pages):
        return {'query': {'pages': [
            {'title': f'পাতা:বই.pdf/{p["page"]}', 'proofread': {'quality': p['quality']},
             'revisions': [{'revid': p['revision'], 'timestamp': p['timestamp'], 'slots': {'main': {'content': p['wikitext']}}}]}
            for p in pages]}}

    def _run(self, directory, api, *extra):
        path = Path(directory) / 'api.json'
        path.write_text(json.dumps(api, ensure_ascii=False), encoding='utf-8')
        out = StringIO()
        call_command('intake_wikisource', 'test-book', '--api-json', str(path), '--title', TITLE,
                     '--source-ref', KW['source_ref'], '--source-edition', KW['source_edition'], '--house', 'golpo',
                     '--description', 'বিবরণ', '--first-published', '1895', '--author-died', '1941',
                     '--creator', 'রবীন্দ্রনাথ ঠাকুর', '--root', str(directory), *extra, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing_and_write_creates_the_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._api(PAGES), '--keep-hyphen-after', '১৭৫')
            self.assertFalse((Path(directory) / 'library').exists())
            self._run(directory, self._api(PAGES), '--keep-hyphen-after', '১৭৫', '--write')
            packet = Path(directory) / 'library/intake/test-book'
            manifest = json.loads((packet / 'manifest.json').read_text(encoding='utf-8'))
            validate_manifest(manifest)
            self.assertEqual(hashlib.sha256((packet / 'source.json').read_bytes()).hexdigest(), manifest['source']['sha256'])
            draft = json.loads((Path(directory) / 'docs/evidence/publication-clearance-test-book-draft.json').read_text(encoding='utf-8'))
            self.assertEqual(draft['status'], 'DRAFT_PENDING_OWNER_APPROVAL')

    def test_unvalidated_page_fails_the_command(self):
        bad = [dict(p) for p in PAGES]
        bad[1]['quality'] = 3
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(CommandError, 'PAGE_NOT_VALIDATED'):
                self._run(directory, self._api(bad))

    def test_kshudhita_pashan_source_is_reproduced_byte_for_byte(self):
        saved = Path(os.environ.get('KSHUDHITA_API_JSON', ROOT / '.superpowers/sdd/2026-11-25-earnalism-revenue-phases-5-9/kshudhita-pashan-api-pages.json'))
        if not saved.is_file():
            self.skipTest('saved MediaWiki response not present in this checkout')
        committed = ROOT / 'library/intake/kshudhita-pashan'
        expected = json.loads((committed / 'manifest.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            out = StringIO()
            call_command('intake_wikisource', 'kshudhita-pashan', '--api-json', str(saved), '--title', TITLE,
                         '--source-ref', expected['provenance']['source_ref'],
                         '--source-edition', expected['provenance']['source_edition'], '--house', 'golpo',
                         '--description', expected['edition']['description'], '--first-published', '1895',
                         '--author-died', '1941', '--creator', 'রবীন্দ্রনাথ ঠাকুর',
                         '--keep-hyphen-after', '১৭৫', '--root', directory, '--write', stdout=out)
            made = (Path(directory) / 'library/intake/kshudhita-pashan/source.json').read_bytes()
        self.assertEqual(made, (committed / 'source.json').read_bytes())
        self.assertEqual(hashlib.sha256(made).hexdigest(), expected['source']['sha256'])
