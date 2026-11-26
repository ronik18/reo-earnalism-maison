"""Owner decision 26 Nov 2026: the free preview is about the first quarter of the story.

Target = 25% of the story's words, at least 400 and at most 1,500; whole paragraphs only, stopping after the
paragraph that reaches the target; never the edition's last paragraph or verse block (the protected end); a story of 400 words or fewer previews
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
    return sum(svc.preview_word_count(p['text']) for p in blocks if p['kind'] in ('paragraph', 'verse'))


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
        self.assertLessEqual(len(read), 62)  # 6,000 words known, plus one lookahead group (each closed by one more row)

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
            self.assertEqual(document['boundary_unit_id'], str(units[1].id))  # sign-in returns to the boundary's unit


class LongStoryEndingTests(SimpleTestCase):
    """Fix round 1, C1: reading stops early on long stories, but the final paragraph is still never served."""

    def test_one_long_paragraph_has_no_preview(self):
        self.assertEqual(cut(paras(7000)), [])
        self.assertEqual(cut(paras(6000)), [])
        self.assertEqual(cut(chapter(('paragraph', words(7000)), ('note', 'n'))), [])

    def test_a_long_final_paragraph_is_never_served(self):
        story = paras(100, 7000)
        self.assertEqual(cut(story), story[:1])
        story = paras(1000, 5500)
        self.assertEqual(cut(story), story[:1])
        story = paras(300, 300, 5400)  # 6,000 words reached exactly on the final paragraph
        self.assertEqual(cut(story), story[:2])

    def test_a_long_final_unit_is_never_served(self):
        stream = [('u1', p) for p in paras(100)] + [('u2', p) for p in paras(7000)]
        self.assertEqual(svc.preview_cut(stream), [('u1', [stream[0][1]])])
        stream = [('u1', p) for p in paras(7000)] + [('u2', p) for p in paras(10)]
        self.assertEqual(svc.preview_cut(stream), [('u1', [stream[0][1]])])  # more follows, so it may be shown

    def test_lookahead_reads_at_most_one_group_past_the_stop(self):
        read = []

        def stream():
            for p in paras(7000, 10, 10, 10):
                read.append(p)
                yield 'u1', p
        preview = svc.preview_cut(stream())
        self.assertEqual(len(preview[0][1]), 1)  # the long opening paragraph is not the final one here
        self.assertLessEqual(len(read), 3)

    def test_randomised_stories_never_show_the_ending_or_run_far_past_the_cap(self):
        import random
        rng = random.Random(20261126)
        for _ in range(3000):
            sizes = [rng.choice([1, 5, 40, 150, 600, 1400, 3000, 5000, 7000, rng.randint(1, 9000)])
                     for _ in range(rng.randint(1, 12))]
            story = paras(*sizes)
            preview = cut(story)
            self.assertNotIn(story[-1], preview, sizes)
            self.assertLess(len(preview), len(story), sizes)
            self.assertEqual(preview, story[:len(preview)], sizes)  # always a prefix, whole paragraphs
            counted = [svc.preview_word_count(p['text']) for p in preview]
            if len(counted) == 1:
                self.assertEqual(counted[0], sizes[0])  # a single shown paragraph is the first one
            elif counted:
                # Everything before the paragraph that reaches the target is below the 1,500-word cap,
                # so the preview is at most max(1,500 words, first paragraph) plus that one crossing paragraph.
                self.assertLess(sum(counted[:-1]), svc.PREVIEW_MAX_WORDS, sizes)
                self.assertLessEqual(sum(counted), max(svc.PREVIEW_MAX_WORDS, sizes[0]) + counted[-1], sizes)


class ProtectedEndTests(SimpleTestCase):
    """Fix round 3, C1: the protected end is the edition's last paragraph or verse block with its notes.
    Headings and notes that follow it never count as "more follows"."""

    def test_trailing_heading_does_not_expose_the_last_paragraph(self):
        story = chapter(('paragraph', words(100)), ('paragraph', words(7000)), ('heading', 'The end'))
        self.assertEqual(cut(story), story[:1])
        story = chapter(('paragraph', words(200)), ('paragraph', words(300)), ('heading', 'The end'))
        self.assertEqual(cut(story), story[:1])
        story = chapter(('paragraph', words(7000)), ('heading', 'One'), ('heading', 'Two'))
        self.assertEqual(cut(story), [])

    def test_note_opening_a_new_unit_does_not_expose_the_last_paragraph(self):
        stream = [('u1', p) for p in paras(100, 7000)] + [('u2', p) for p in chapter(('note', 'a note'))]
        self.assertEqual(svc.preview_cut(stream), [('u1', [stream[0][1]])])
        stream = [('u1', p) for p in paras(7000)] + [('u2', p) for p in chapter(('heading', 'Two'), ('note', 'n'))]
        self.assertEqual(svc.preview_cut(stream), [])

    def test_verse_is_story_text(self):
        story = chapter(('paragraph', words(300)), ('verse', words(300)), ('verse', words(500)))
        self.assertEqual(cut(story), story[:2])  # 1,100 words: target 400; the final verse is protected
        story = chapter(('paragraph', words(7000)), ('verse', 'one line'))
        self.assertEqual(cut(story), story[:1])  # a later verse block means the long paragraph is not the end

    def test_headings_count_no_words(self):
        story = chapter(('heading', words(1000)), ('paragraph', words(100)), ('paragraph', words(100)))
        self.assertEqual(cut(story), story[:2])  # 200 story words: first paragraph only, with its heading

    def test_randomised_editions_never_include_the_protected_end(self):
        import random
        rng = random.Random(20261127)
        kinds = ['paragraph'] * 5 + ['verse', 'heading', 'heading', 'note', 'note']
        sizes = [1, 5, 40, 150, 600, 1400, 3000, 5000, 7000]
        for _ in range(4000):
            stream = []
            for u in range(rng.randint(1, 4)):
                for i in range(rng.randint(1, 8)):
                    kind = rng.choice(kinds)
                    n = rng.choice(sizes + [rng.randint(1, 9000)])
                    stream.append((f'u{u}', block(words(n), kind, i + 1)))
            preview = svc.preview_cut(list(stream))
            shown = [(unit, p) for unit, blocks in preview for p in blocks]
            self.assertEqual(shown, stream[:len(shown)])  # a whole-block prefix, in order, unit by unit
            body = [i for i, (_, p) in enumerate(stream) if p['kind'] in ('paragraph', 'verse')]
            if not body:
                self.assertEqual(preview, [])
                continue
            # The protected end starts at the last paragraph/verse block; nothing from there on is shown.
            self.assertLess(len(shown), body[-1] + 1, [(u, p['kind'], svc.preview_word_count(p['text'])) for u, p in stream])
            if shown:
                self.assertIn(shown[-1][1]['kind'] if shown[-1][1]['kind'] != 'note' else
                              next(p['kind'] for _, p in reversed(shown) if p['kind'] != 'note'), ('paragraph', 'verse'))
                self.assertLessEqual(len(preview), svc.PREVIEW_MAX_UNITS)
                self.assertTrue(all(len(blocks) <= svc.PREVIEW_MAX_BLOCKS for _, blocks in preview))
