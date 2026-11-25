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
from django.test import SimpleTestCase, TestCase, override_settings

from .models import ReviewItem

from .book_source import read_source_bytes, validate_manifest
from .intake.wikisource import IntakeError, build_packet, pages_to_paragraphs

ROOT = Path(__file__).resolve().parent.parent
TITLE = 'ক্ষুধিত পাষাণ'
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
            {'kind': 'paragraph', 'text': 'আমি এবং আমার আত্মীয় কলিকাতায় ফিরিয়া আসিতেছিলাম। তাহার প্রতিবিম্ব আলোড়িত হইল।'},
            {'kind': 'paragraph', 'text': 'সঙ্গিনীহীন মাশুল-কালেক্টরের বাসস্থান।'},
            {'kind': 'paragraph', 'text': 'শেষ।'}])
        text = ''.join(p['text'] for p in paragraphs)
        self.assertNotIn('﻿', text)
        self.assertNotIn('{{', text)

    def test_hyphen_is_dropped_unless_the_page_is_listed(self):
        self.assertIn('মাশুলকালেক্টরের', ' '.join(p['text'] for p in pages_to_paragraphs(PAGES, title=TITLE)))

    def test_missing_title_line_is_refused(self):
        pages = [dict(PAGES[0], wikitext='আমি।')]
        with self.assertRaises(IntakeError) as caught:
            pages_to_paragraphs(pages, title=TITLE)
        self.assertEqual(caught.exception.code, 'TITLE_LINE_MISSING')

    def test_unknown_keep_hyphen_label_is_refused(self):
        with self.assertRaises(IntakeError) as caught:
            pages_to_paragraphs(PAGES, title=TITLE, keep_hyphen_after=frozenset({'৯৯৯'}))
        self.assertEqual(caught.exception.code, 'UNKNOWN_PAGE_LABEL')

    def test_quality_below_four_is_refused(self):
        pages = [dict(PAGES[0]), dict(PAGES[1], quality=3)]
        with self.assertRaises(IntakeError) as caught:
            pages_to_paragraphs(pages, title=TITLE)
        self.assertEqual(caught.exception.code, 'PAGE_NOT_VALIDATED')

    def test_leftover_markup_is_refused(self):
        for bad in ('দেখুন [[অন্য]] পাতা।', "''তির্যক''", '{{অজানা|x}}'):
            with self.subTest(bad=bad):
                pages = [dict(PAGES[0], wikitext=PAGES[0]['wikitext'] + bad)]
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


def _one(wikitext, title=TITLE):
    return pages_to_paragraphs([{'page': '১', 'revision': 1, 'quality': 4, 'wikitext': wikitext}], title=title)


class WikisourceStructureTests(SimpleTestCase):
    TL = '{{কেন্দ্র|{{x-larger|ক্ষুধিত পাষাণ।}}}}\n\n'

    def test_poem_block_is_one_verse_paragraph(self):
        got = _one(self.TL + 'আগে।\n\n{{Block center|<poem>প্রথম  পংক্তি \n  দ্বিতীয় পংক্তি,–\nতৃতীয়</poem>}}\n\n{{gap}}পরে।')
        self.assertEqual(got, [
            {'kind': 'paragraph', 'text': 'আগে।'},
            {'kind': 'verse', 'text': 'প্রথম  পংক্তি\nদ্বিতীয় পংক্তি,–\nতৃতীয়'},
            {'kind': 'paragraph', 'text': 'পরে।'}])

    def test_poem_starts_and_ends_a_paragraph_even_without_blank_lines(self):
        got = _one(self.TL + 'আগে\n{{Block center|<poem>ক\nখ</poem>}}\nপরে')
        self.assertEqual([p['kind'] for p in got], ['paragraph', 'verse', 'paragraph'])

    def test_poem_with_blank_line_or_markup_is_refused(self):
        for bad in ('ক\n\nখ', 'ক [[খ]]', 'ক {{গ}}'):
            with self.subTest(bad=bad), self.assertRaises(IntakeError) as caught:
                _one(self.TL + '{{Block center|<poem>' + bad + '</poem>}}')
            self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_section_headings_in_all_three_forms(self):
        body = ('{{কেন্দ্র|প্রথম পরিচ্ছেদ।}}\n\nএক।\n\n{{কেন্দ্র|{{larger|দ্বিতীয় পরিচ্ছেদ}}}}\n\n'
                'দুই।\n\n{{larger|তৃতীয় পরিচ্ছেদ।}}\n\nতিন।')
        self.assertEqual(_one(self.TL + body), [
            {'kind': 'heading', 'text': 'প্রথম পরিচ্ছেদ।'}, {'kind': 'paragraph', 'text': 'এক।'},
            {'kind': 'heading', 'text': 'দ্বিতীয় পরিচ্ছেদ'}, {'kind': 'paragraph', 'text': 'দুই।'},
            {'kind': 'heading', 'text': 'তৃতীয় পরিচ্ছেদ।'}, {'kind': 'paragraph', 'text': 'তিন।'}])

    def test_heading_must_be_its_own_block_else_refused(self):
        for bad in ('এক {{কেন্দ্র|শিরোনাম}} দুই', 'এক।\n{{কেন্দ্র|শিরোনাম}}\nদুই', '{{কেন্দ্র|{{x-larger|শিরোনাম}}}}',
                    '{{কেন্দ্র|ক|খ}}', '{{larger|{{larger|ক}}}}'):
            with self.subTest(bad=bad), self.assertRaises(IntakeError) as caught:
                _one(self.TL + bad)
            self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_rule_line_is_a_paragraph_break_with_no_text(self):
        got = _one(self.TL + 'এক\n{{rule|3em}}\nদুই\n\n{{rule|3em}}')
        self.assertEqual(got, [{'kind': 'paragraph', 'text': 'এক'}, {'kind': 'paragraph', 'text': 'দুই'}])

    def test_rule_inside_a_line_is_refused(self):
        with self.assertRaises(IntakeError) as caught:
            _one(self.TL + 'এক {{rule|3em}} দুই')
        self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_rule_right_after_the_title_line(self):
        got = _one(self.TL + '{{rule|3em}}\n\nএক')
        self.assertEqual(got, [{'kind': 'paragraph', 'text': 'এক'}])

    def test_collection_header_then_title_line_are_both_dropped(self):
        got = _one('{{কেন্দ্র|{{x-larger|গল্প-দশক।}}}}\n\n{{কেন্দ্র|{{larger|ক্ষুধিত পাষাণ।}}}}\n\n'
                   '{{কেন্দ্র|প্রথম পরিচ্ছেদ।}}\n\nএক।')
        self.assertEqual(got, [{'kind': 'heading', 'text': 'প্রথম পরিচ্ছেদ।'}, {'kind': 'paragraph', 'text': 'এক।'}])

    def test_collection_header_without_the_title_line_is_refused(self):
        for bad in ('{{কেন্দ্র|{{x-larger|গল্প-দশক।}}}}\n\nএক।', '{{কেন্দ্র|{{larger|ক্ষুধিত পাষাণ।}}}}\n\nএক।'):
            with self.subTest(bad=bad), self.assertRaises(IntakeError) as caught:
                _one(bad)
            self.assertEqual(caught.exception.code, 'TITLE_LINE_MISSING')

    def test_collection_header_on_a_later_page_is_refused(self):
        pages = [PAGES[0], dict(PAGES[1], wikitext='{{কেন্দ্র|{{x-larger|গল্প-দশক।}}}}\n\nএক')]
        with self.assertRaises(IntakeError) as caught:
            pages_to_paragraphs(pages, title=TITLE)
        self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_xx_larger_title_line_is_dropped(self):
        got = _one('\ufeff{{কেন্দ্র|{{xx-larger|\ufeffমেঘ ও রৌদ্র।}}}}\n\n{{rule|3em}}\n\nএক।', title='মেঘ ও রৌদ্র')
        self.assertEqual(got, [{'kind': 'paragraph', 'text': 'এক।'}])

    KC = ('{{কেন্দ্র|{{xxxx-larger|কথা-চতুষ্টয়।}}}}\n\n'
          '{{কেন্দ্র|[[File:কথা-চতুষ্টয় - রবীন্দ্রনাথ ঠাকুর (page 5 crop 1).jpg|150px]]}}\n\n'
          '{{কেন্দ্র|{{xx-larger|মধ্যবর্ত্তিনী।}}}}\n\n'
          '{{কেন্দ্র|[[File:কথা-চতুষ্টয় - রবীন্দ্রনাথ ঠাকুর (page 5 crop 2).jpg|120px]]}}\n\n'
          '{{কেন্দ্র|{{x-larger|প্রথম পরিচ্ছেদ।}}}}\n\n'
          '{{কেন্দ্র|[[File:কথা-চতুষ্টয় - রবীন্দ্রনাথ ঠাকুর (page 5 crop 3).jpg|100px]]}}\n\n')

    def test_katha_chatushtay_opening_keeps_only_the_section_heading(self):
        got = _one(self.KC + 'নিবারণের সংসার।\n\n{{gap}}দুই।', title='মধ্যবর্ত্তিনী')
        self.assertEqual(got, [{'kind': 'heading', 'text': 'প্রথম পরিচ্ছেদ।'},
                               {'kind': 'paragraph', 'text': 'নিবারণের সংসার।'}, {'kind': 'paragraph', 'text': 'দুই।'}])

    def test_katha_chatushtay_opening_must_be_exact(self):
        variants = (self.KC.replace('page 5 crop 2', 'other'),            # not a scan ornament
                    self.KC.replace('কথা-চতুষ্টয়।}}', 'গল্প-দশক।}}'),     # a different collection
                    self.KC.replace('মধ্যবর্ত্তিনী।', 'শাস্তি।'))           # a different story
        for bad in variants:
            with self.subTest(bad=bad[:80]), self.assertRaises(IntakeError):
                _one(bad + 'এক।', title='মধ্যবর্ত্তিনী')

    def test_ornament_or_x_larger_heading_outside_the_opening_is_refused(self):
        for bad in ('{{কেন্দ্র|[[File:কথা-চতুষ্টয় - রবীন্দ্রনাথ ঠাকুর (page 9 crop 1).jpg|100px]]}}',
                    '{{কেন্দ্র|{{x-larger|দ্বিতীয় পরিচ্ছেদ।}}}}'):
            with self.subTest(bad=bad), self.assertRaises(IntakeError) as caught:
                _one(self.KC + 'এক।\n\n' + bad + '\n\nদুই।', title='মধ্যবর্ত্তিনী')
            self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_author_footnote_becomes_a_note_after_its_paragraph(self):
        got = _one(self.TL + 'আদেশ পালন করিল।<ref>এই গল্প  পূর্ব্বে রচিত।</ref>\n\n{{gap}}পরে।')
        self.assertEqual(got, [{'kind': 'paragraph', 'text': 'আদেশ পালন করিল।'},
                               {'kind': 'note', 'text': 'এই গল্প পূর্ব্বে রচিত।'}, {'kind': 'paragraph', 'text': 'পরে।'}])

    def test_footnote_mid_paragraph_follows_the_whole_paragraph(self):
        got = _one(self.TL + 'এক<ref>টীকা</ref> দুই।\n\nতিন।')
        self.assertEqual(got, [{'kind': 'paragraph', 'text': 'এক দুই।'}, {'kind': 'note', 'text': 'টীকা'},
                               {'kind': 'paragraph', 'text': 'তিন।'}])

    def test_footnote_with_markup_empty_or_outside_a_paragraph_is_refused(self):
        for bad in ('এক<ref>ক {{gap}}</ref>', 'এক<ref> </ref>', 'এক<ref name="a">ক</ref>',
                    '{{কেন্দ্র|প্রথম<ref>ক</ref>}}', '{{Block center|<poem>ক<ref>খ</ref></poem>}}', '<references/>'):
            with self.subTest(bad=bad), self.assertRaises(IntakeError) as caught:
                _one(self.TL + bad)
            self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_poem_split_across_pages_is_one_verse(self):
        pages = [{'page': '১', 'revision': 1, 'quality': 4,
                  'wikitext': self.TL + 'আগে,—\n\n{{Block center/s}}<poem>ক খ\nগ</poem><noinclude>{{block center/e}}</noinclude>'},
                 {'page': '২', 'revision': 2, 'quality': 4,
                  'wikitext': '<noinclude>{{rh||x|১}}\n{{Block center/s}}</noinclude><poem>ঘ\nঙ</poem>{{block center/e}}\n\n{{gap}}পরে।'}]
        self.assertEqual(pages_to_paragraphs(pages, title=TITLE), [
            {'kind': 'paragraph', 'text': 'আগে,—'}, {'kind': 'verse', 'text': 'ক খ\nগ\nঘ\nঙ'},
            {'kind': 'paragraph', 'text': 'পরে।'}])

    def test_split_poem_halves_must_meet_at_a_page_break(self):
        open_end = self.TL + 'এক\n\n{{Block center/s}}<poem>ক</poem>'
        close_start = '<poem>খ</poem>{{block center/e}}\n\nদুই'
        for bad in ([open_end, 'দুই।'], [self.TL + 'এক', close_start], [open_end + '\n\nআরও', close_start]):
            pages = [{'page': str(n), 'revision': n, 'quality': 4, 'wikitext': text} for n, text in enumerate(bad, 1)]
            with self.subTest(bad=bad), self.assertRaises(IntakeError) as caught:
                pages_to_paragraphs(pages, title=TITLE)
            self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_verse_and_heading_flow_into_the_source_units(self):
        pages = [{'page': '১', 'revision': 1, 'quality': 4, 'timestamp': None,
                  'wikitext': self.TL + '{{কেন্দ্র|প্রথম পরিচ্ছেদ।}}\n\n{{Block center|<poem>ক\nখ</poem>}}'}]
        source = build_packet('test-book', TITLE, pages, **KW)['source']
        self.assertEqual([p['kind'] for p in source['units'][0]['paragraphs']], ['heading', 'verse'])
        self.assertEqual(source['units'][0]['paragraphs'][1]['text'], 'ক\nখ')

    def test_centered_song_line_is_a_verse_paragraph(self):
        for tpl in ('center', 'c'):
            with self.subTest(tpl=tpl):
                got = _one(self.TL + 'আগে।\n\n{{' + tpl + '|কেন, পূর্ণিমা আঁধার!}}\n\nপরে।')
                self.assertEqual(got, [{'kind': 'paragraph', 'text': 'আগে।'},
                                       {'kind': 'verse', 'text': 'কেন, পূর্ণিমা আঁধার!'},
                                       {'kind': 'paragraph', 'text': 'পরে।'}])

    def test_centered_line_with_markup_or_inline_is_refused(self):
        for bad in ('{{center|ক {{x}} খ}}', '{{center|ক|খ}}', 'এক {{center|ক}} দুই', 'এক।\n{{c|ক}}\nদুই', '{{center|[[ক]]}}'):
            with self.subTest(bad=bad), self.assertRaises(IntakeError) as caught:
                _one(self.TL + bad)
            self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_book_end_marker_is_dropped_on_the_last_page_only(self):
        end = '{{কেন্দ্র|সম্পূর্ণ।}}'
        P0 = dict(PAGES[0], wikitext=self.TL + 'এক।{{nop}}')
        last = dict(PAGES[1], wikitext='শেষ।\n\n{{rule|3em}}\n' + end)
        self.assertEqual(pages_to_paragraphs([P0, last], title=TITLE)[-1], {'kind': 'paragraph', 'text': 'শেষ।'})
        last = dict(PAGES[1], wikitext='শেষ।\n\n' + end)
        self.assertEqual(pages_to_paragraphs([P0, last], title=TITLE)[-1], {'kind': 'paragraph', 'text': 'শেষ।'})
        for pages in ([PAGES[0], dict(PAGES[1], wikitext='শেষ।\n\n' + end), PAGES[2]],
                      [PAGES[0], dict(PAGES[1], wikitext='শেষ।\n\n' + end + '\n\nআরও।')],
                      [dict(PAGES[0], wikitext=PAGES[0]['wikitext'] + '\n\n' + end), PAGES[1]]):
            with self.subTest(pages=len(pages)), self.assertRaises(IntakeError) as caught:
                pages_to_paragraphs(pages, title=TITLE)
            self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_samapta_is_also_a_last_page_end_marker(self):
        P0 = dict(PAGES[0], wikitext=self.TL + 'এক।{{nop}}')
        last = dict(PAGES[1], wikitext='গাহিতে লাগিল—\n\n{{কেন্দ্র|এস এস হে!}}\n\n\n\n{{কেন্দ্র|সমাপ্ত।}}')
        self.assertEqual(pages_to_paragraphs([P0, last], title=TITLE)[-2:], [
            {'kind': 'paragraph', 'text': 'গাহিতে লাগিল—'}, {'kind': 'verse', 'text': 'এস এস হে!'}])
        with self.assertRaises(IntakeError) as caught:
            pages_to_paragraphs([dict(P0, wikitext=self.TL + 'এক।\n\n{{কেন্দ্র|সমাপ্ত।}}'), PAGES[1]], title=TITLE)
        self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')

    def test_bare_centered_line_is_a_heading_only_when_it_names_a_section(self):
        got = _one(self.TL + '{{কেন্দ্র|নবম পরিচ্ছেদ।}}\n\nএক।\n\n{{কেন্দ্র|পরিশিষ্ট।}}\n\nদুই।\n\n{{কেন্দ্র|এস এস হে!}}')
        self.assertEqual([p['kind'] for p in got], ['heading', 'paragraph', 'heading', 'paragraph', 'verse'])

    def test_blocks_adjacent_to_a_rule_line_with_a_single_newline(self):
        got = _one(self.TL + 'এক।\n\n{{rule|3em}}\n{{কেন্দ্র|{{larger|দ্বিতীয়।}}}}\n{{rule|3em}}\n{{Block center|<poem>ক\nখ</poem>}}\n{{rule|2em}}\nদুই।')
        self.assertEqual(got, [{'kind': 'paragraph', 'text': 'এক।'}, {'kind': 'heading', 'text': 'দ্বিতীয়।'},
                               {'kind': 'verse', 'text': 'ক\nখ'}, {'kind': 'paragraph', 'text': 'দুই।'}])

    def test_control_characters_in_the_source_are_refused(self):
        with self.assertRaises(IntakeError) as caught:
            _one(self.TL + 'এক\x01দুই')
        self.assertEqual(caught.exception.code, 'UNKNOWN_MARKUP')


class WikisourceCommandTests(TestCase):
    def _api(self, pages):
        return {'query': {'pages': [
            {'title': f'পাতা:বই.pdf/{p["page"]}', 'proofread': {'quality': p['quality']},
             'revisions': [{'revid': p['revision'], 'timestamp': p['timestamp'], 'slots': {'main': {'content': p['wikitext']}}}]}
            for p in pages]}}

    def _run(self, directory, api, *extra, base=None):
        path = Path(directory) / 'api.json'
        path.write_text(json.dumps(api, ensure_ascii=False), encoding='utf-8')
        out = StringIO()
        with override_settings(BASE_DIR=Path(base or directory)):
            call_command('intake_wikisource', 'test-book', '--api-json', str(path), '--title', TITLE,
                         '--source-ref', KW['source_ref'], '--source-edition', KW['source_edition'], '--house', 'golpo',
                         '--description', 'বিবরণ', '--first-published', '1895', '--author-died', '1941',
                         '--creator', 'রবীন্দ্রনাথ ঠাকুর', '--root', str(directory), *extra, stdout=out)
        return out.getvalue()

    def test_write_queues_the_clearance_draft_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._api(PAGES), '--keep-hyphen-after', '১৭৫')
            self.assertFalse(ReviewItem.objects.exists())  # a dry run queues nothing
            self._run(directory, self._api(PAGES), '--keep-hyphen-after', '১৭৫', '--write')
            ref = 'docs/evidence/publication-clearance-test-book-draft.json'
            item = ReviewItem.objects.get()
            self.assertEqual((item.kind, item.ref, item.status), ('clearance', ref, 'pending'))
            self.assertEqual(item.sha256, hashlib.sha256((Path(directory) / ref).read_bytes()).hexdigest())
            self.assertEqual(item.summary, {'edition_slug': 'test-book', 'title': TITLE})

    def test_output_outside_the_repository_is_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as repo:
            with self.assertRaisesRegex(CommandError, 'REVIEW_REF_INVALID'):
                self._run(directory, self._api(PAGES), '--write', base=repo)
            self.assertFalse((Path(directory) / 'library').exists())
            self.assertFalse(ReviewItem.objects.exists())

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

    def test_existing_packet_is_not_overwritten_without_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._api(PAGES), '--write')
            with self.assertRaisesRegex(CommandError, 'PACKET_EXISTS'):
                self._run(directory, self._api(PAGES), '--write')
            self._run(directory, self._api(PAGES), '--write', '--replace')

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
        with tempfile.TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
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
