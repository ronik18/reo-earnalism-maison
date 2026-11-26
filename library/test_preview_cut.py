"""Owner decision 26 Nov 2026: the free preview is the first chapter, cut after the paragraph that reaches 1,500 words."""
import uuid
from django.test import SimpleTestCase
from . import services as svc


def block(text, kind='paragraph', ordinal=1):
    return {'anchor_id': str(uuid.uuid4()), 'text': text, 'kind': kind, 'ordinal': ordinal}


def chapter(*specs):
    return [block(text, kind, i) for i, (kind, text) in enumerate(specs, 1)]


def words(n, word='word'):
    return ' '.join([word] * n)


class PreviewCutTests(SimpleTestCase):
    def test_limit_is_1500_words(self):
        self.assertEqual(svc.PREVIEW_WORD_LIMIT, 1500)

    def test_short_chapter_is_shown_whole_in_order(self):
        paragraphs = chapter(('heading', 'One'), ('paragraph', words(400)), ('verse', words(30)), ('paragraph', words(500)))
        self.assertEqual(svc.preview_blocks(paragraphs), paragraphs)

    def test_long_chapter_stops_after_the_paragraph_that_crosses_the_limit(self):
        paragraphs = chapter(('paragraph', words(700)), ('paragraph', words(700)), ('paragraph', words(300)), ('paragraph', words(10)))
        preview = svc.preview_blocks(paragraphs)
        self.assertEqual(preview, paragraphs[:3])  # 1,400 words, then the paragraph reaching 1,700; never mid-paragraph
        self.assertEqual(preview[-1]['text'], paragraphs[2]['text'])

    def test_exactly_reaching_the_limit_stops_there(self):
        paragraphs = chapter(('paragraph', words(1000)), ('paragraph', words(500)), ('paragraph', words(5)))
        self.assertEqual(svc.preview_blocks(paragraphs), paragraphs[:2])

    def test_single_paragraph_longer_than_the_limit_is_shown_whole(self):
        paragraphs = chapter(('paragraph', words(2400)), ('paragraph', words(5)))
        self.assertEqual(svc.preview_blocks(paragraphs), paragraphs[:1])

    def test_notes_travel_with_their_paragraph_and_do_not_count(self):
        paragraphs = chapter(('paragraph', words(1000)), ('note', words(900)), ('paragraph', words(600)),
                             ('note', words(20)), ('paragraph', words(5)), ('note', words(5)))
        preview = svc.preview_blocks(paragraphs)
        self.assertEqual(preview, paragraphs[:4])  # 1,000 + 600 words; the crossing paragraph keeps its note
        self.assertEqual(preview[-1]['kind'], 'note')

    def test_bengali_words_are_whitespace_tokens(self):
        sentence = 'আমি আজ বাড়ি   ফিরলাম।\nতারপর ঘুম।'
        self.assertEqual(svc.preview_word_count(sentence), 6)
        paragraphs = chapter(('paragraph', words(749, 'বাংলা')), ('paragraph', words(751, 'গল্প')), ('paragraph', 'শেষ'))
        self.assertEqual(svc.preview_blocks(paragraphs), paragraphs[:2])
        self.assertEqual(svc.preview_blocks(paragraphs[:1] + paragraphs[2:]), [paragraphs[0], paragraphs[2]])

    def test_a_trailing_heading_is_not_left_dangling(self):
        paragraphs = chapter(('paragraph', words(1600)), ('heading', 'Two'), ('paragraph', words(5)))
        self.assertEqual(svc.preview_blocks(paragraphs), paragraphs[:1])
        paragraphs = chapter(('paragraph', words(1400)), ('heading', words(200)), ('paragraph', words(5)))
        self.assertEqual(svc.preview_blocks(paragraphs), paragraphs[:1])
        only = chapter(('heading', 'Alone'))
        self.assertEqual(svc.preview_blocks(only), only)

    def test_contract_block_ceiling_keeps_whole_paragraphs_with_their_notes(self):
        paragraphs = chapter(*([('paragraph', 'short line')] * 99 + [('paragraph', 'with note'), ('note', 'n'), ('paragraph', 'x')]))
        preview = svc.preview_blocks(paragraphs)
        self.assertEqual(len(preview), 99)
        self.assertLessEqual(len(svc.preview_blocks(chapter(*[('paragraph', 'w')] * 300))), svc.PREVIEW_MAX_BLOCKS)

    def test_empty_chapter_has_no_preview(self):
        self.assertEqual(svc.preview_blocks([]), [])
