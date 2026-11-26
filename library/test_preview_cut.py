"""Owner decision 26 Nov 2026: the free preview is about the first quarter of the story.

Target = 25% of the story's words, at least 400 and at most 1,500; whole paragraphs only, stopping after the
paragraph that reaches the target; never the story's final paragraph; a story of 400 words or fewer previews
only its first paragraph, and no preview at all if that is the whole story. Counted across all units."""
import uuid
from django.test import SimpleTestCase
from . import services as svc


def block(text, kind='paragraph', ordinal=1):
    return {'anchor_id': str(uuid.uuid4()), 'text': text, 'kind': kind, 'ordinal': ordinal}


def chapter(*specs):
    return [block(text, kind, i) for i, (kind, text) in enumerate(specs, 1)]


def words(n, word='word'):
    return ' '.join([word] * n)


def paras(*counts):
    return chapter(*[('paragraph', words(n)) for n in counts])


def cut(paragraphs, unit='u1'):
    """The single-unit preview blocks."""
    result = svc.preview_cut((unit, p) for p in paragraphs)
    assert len(result) <= 1
    return result[0][1] if result else []


def total(blocks):
    return sum(svc.preview_word_count(p['text']) for p in blocks if p['kind'] != 'note')


class PreviewRuleTests(SimpleTestCase):
    def test_constants(self):
        self.assertEqual((svc.PREVIEW_FRACTION, svc.PREVIEW_MIN_WORDS, svc.PREVIEW_MAX_WORDS), (0.25, 400, 1500))
        self.assertEqual((svc.PREVIEW_MAX_BLOCKS, svc.PREVIEW_MAX_UNITS), (100, 10))  # contracts/openapi.yaml PreviewPackage

    def test_medium_story_previews_a_quarter_at_paragraph_boundaries(self):
        story = paras(*[100] * 30)  # 3,000 words: target 750
        preview = cut(story)
        self.assertEqual(preview, story[:8])  # 700 < 750, the eighth paragraph reaches 800
        story = paras(*[150] * 20)  # 3,000 words: target 750, reached exactly by the fifth paragraph
        self.assertEqual(cut(story), story[:5])

    def test_short_story_gets_at_least_400_words(self):
        story = paras(*[90] * 10)  # 900 words: 25% is 225, the floor is 400
        self.assertEqual(cut(story), story[:5])
        self.assertEqual(total(cut(story)), 450)

    def test_long_story_is_capped_at_about_1500_words(self):
        story = paras(*[200] * 60)  # 12,000 words: 25% is 3,000, the cap is 1,500
        preview = cut(story)
        self.assertEqual(preview, story[:8])  # 1,400 < 1,500, the eighth reaches 1,600; never mid-paragraph
        self.assertLess(total(preview[:-1]), 1500)

    def test_long_story_is_not_read_past_what_the_cut_needs(self):
        read = []

        def stream():
            for p in paras(*[100] * 500):  # 50,000 words
                read.append(p)
                yield 'u1', p
        preview = svc.preview_cut(stream())[0][1]
        self.assertEqual(len(preview), 15)
        self.assertLessEqual(len(read), 61)  # stops once 1,500 / 0.25 = 6,000 words are known (+1 to close a note group)

    def test_story_of_400_words_or_fewer_previews_only_its_first_paragraph(self):
        story = paras(120, 100, 100, 80)  # exactly 400 words
        self.assertEqual(cut(story), story[:1])
        story = chapter(('heading', 'One'), ('paragraph', words(50)), ('paragraph', words(50)))
        self.assertEqual(cut(story), story[:2])  # a leading heading stays with the first paragraph
        story = paras(*[5] * 5) + paras(330)
        self.assertEqual(cut(story), story[:1])

    def test_no_preview_when_the_first_paragraph_is_the_whole_story(self):
        self.assertEqual(cut(paras(300)), [])
        self.assertEqual(cut(paras(3000)), [])
        self.assertEqual(cut(chapter(('heading', 'One'), ('paragraph', words(300)))), [])
        self.assertEqual(cut(chapter(('paragraph', words(300)), ('note', 'a note'))), [])
        self.assertEqual(cut([]), [])

    def test_never_the_final_paragraph(self):
        story = paras(1000, 600)  # target 400 is crossed by the first paragraph
        self.assertEqual(cut(story), story[:1])
        story = paras(100, 100, 100, 1000)  # 1,300 words: target 400 needs the last paragraph, which is never shown
        self.assertEqual(cut(story), story[:3])
        story = paras(*[50] * 9) + paras(5)  # 455 words: target 400 is reached by the eighth paragraph
        self.assertEqual(cut(story), story[:8])
        for n in range(1, 40):
            story = paras(*[37] * n)
            preview = cut(story)
            self.assertNotIn(story[-1], preview)
            self.assertLess(len(preview), len(story))

    def test_a_single_huge_opening_paragraph_is_shown_whole(self):
        story = paras(2400, 4000)
        self.assertEqual(cut(story), story[:1])

    def test_notes_follow_their_paragraph_and_do_not_count(self):
        story = chapter(('paragraph', words(300)), ('note', words(900)), ('paragraph', words(200)),
                        ('note', words(20)), ('paragraph', words(500)), ('note', words(5)), ('paragraph', words(800)))
        preview = cut(story)  # 1,800 counted words: target 450 is crossed by the second paragraph
        self.assertEqual(preview, story[:4])
        self.assertEqual(preview[-1]['kind'], 'note')
        boundary = svc.preview_boundary([('u1', preview)])
        self.assertEqual(boundary['end_anchor_id'], story[2]['anchor_id'])  # sign-in returns to the paragraph
        self.assertEqual(boundary['end_offset_chars'], len(story[2]['text']))

    def test_final_paragraph_keeps_its_notes_out_of_the_preview(self):
        story = chapter(('paragraph', words(500)), ('paragraph', words(500)), ('note', 'n'))
        self.assertEqual(cut(story), story[:1])

    def test_bengali_words_are_whitespace_tokens(self):
        sentence = 'আমি আজ বাড়ি   ফিরলাম।\nতারপর ঘুম।'
        self.assertEqual(svc.preview_word_count(sentence), 6)
        story = chapter(('paragraph', words(300, 'বাংলা')), ('paragraph', words(300, 'গল্প')),
                        ('paragraph', words(1000, 'শেষ')))
        self.assertEqual(cut(story), story[:2])  # 1,600 words: target 400

    def test_a_trailing_heading_is_not_left_dangling(self):
        story = chapter(('paragraph', words(1600)), ('heading', 'Two'), ('paragraph', words(5000)))
        self.assertEqual(cut(story), story[:1])
        story = chapter(('paragraph', words(350)), ('heading', words(100)), ('paragraph', words(1000)))
        self.assertEqual(cut(story), story[:1])

    def test_multi_unit_books_count_every_unit(self):
        one, two, three = paras(100, 100), paras(100, 100, 100), paras(*[100] * 15)
        stream = [('u1', p) for p in one] + [('u2', p) for p in two] + [('u3', p) for p in three]
        preview = svc.preview_cut(stream)  # 2,000 words: target 500, reached in the second unit
        self.assertEqual(preview, [('u1', one), ('u2', two)])
        stream = [('u1', p) for p in paras(100, 100)] + [('u2', p) for p in paras(100, 100, 100, 100)]
        self.assertEqual(svc.preview_cut(stream), [('u1', [stream[0][1], stream[1][1]]),
                                                   ('u2', [stream[2][1], stream[3][1]])])  # 600 words: floor 400

    def test_notes_do_not_cross_into_another_unit(self):
        stream = [('u1', p) for p in paras(450)] + [('u2', p) for p in chapter(('note', 'n'), ('paragraph', words(1500)))]
        self.assertEqual(svc.preview_cut(stream), [('u1', [stream[0][1]])])

    def test_contract_ceilings_keep_whole_paragraphs_with_their_notes(self):
        story = chapter(*([('paragraph', 'short line')] * 99 + [('paragraph', 'with note'), ('note', 'n')]
                          + [('paragraph', words(500))] * 3))
        preview = cut(story)
        self.assertEqual(len(preview), 99)
        self.assertLessEqual(len(cut(chapter(*[('paragraph', 'w w w w')] * 1000))), svc.PREVIEW_MAX_BLOCKS)
        stream = [(f'u{i}', p) for i in range(12) for p in paras(20)] + [('u12', p) for p in paras(5000)]
        preview = svc.preview_cut(stream)
        self.assertEqual(len(preview), svc.PREVIEW_MAX_UNITS)

    def test_a_heading_that_reaches_the_target_takes_the_paragraph_after_it(self):
        story = chapter(('heading', 'One'), ('paragraph', words(398)), ('heading', 'Part two'),
                        ('paragraph', words(40)), ('paragraph', words(1000)))
        self.assertEqual(cut(story), story[:4])  # 1,441 words: target 400 is reached on the heading


class MultiUnitPreviewDocumentTests(SimpleTestCase):
    """The reader page serves each unit's share of the story-wide preview; the boundary is the preview's end."""

    def test_each_unit_page_serves_its_share_and_knows_whether_the_preview_continues(self):
        from types import SimpleNamespace
        from unittest import mock

        def rows(*counts):
            return [SimpleNamespace(anchor_id=uuid.uuid4(), text=words(n), kind='paragraph', ordinal=i)
                    for i, n in enumerate(counts, 1)]

        units = []
        for counts in ((100, 100), (100, 100, 100), (100,) * 15):
            unit = SimpleNamespace(id=uuid.uuid4(), paragraphs=mock.MagicMock())
            unit.paragraphs.all.return_value = rows(*counts)
            units.append(unit)
        revision = mock.MagicMock(preview=[{'text': 'marker'}])
        revision.units.all.return_value = units
        with mock.patch.object(svc, 'edition_detail', return_value={'edition_revision_id': 'r'}), \
                mock.patch.object(svc, '_revision', return_value=revision), \
                mock.patch.object(svc, 'current_right', return_value=object()), \
                mock.patch.object(svc, 'unit_dto', side_effect=lambda unit, territory: {'unit_id': str(unit.id)}):
            first = svc.get_preview_document('e', units[0].id)
            second = svc.get_preview_document('e', str(units[1].id))
            with self.assertRaises(svc.DomainError):
                svc.get_preview_document('e', units[2].id)  # 2,000 words: target 500 ends in the second unit
        self.assertEqual(len(first['paragraphs']), 2)
        self.assertTrue(first['preview_continues'])
        self.assertEqual(len(second['paragraphs']), 3)
        self.assertFalse(second['preview_continues'])
        end = units[1].paragraphs.all.return_value[-1]
        for document in (first, second):
            self.assertEqual(document['boundary']['end_anchor_id'], str(end.anchor_id))
