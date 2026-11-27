"""library.sentences against the golden file shared with the client splitter and eav.text.sentences."""
import importlib.util
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from library.sentences import split_sentences

GOLDEN = json.loads((Path(settings.BASE_DIR) / "contracts" / "sentence-split-golden.json").read_text())
EAV_TEXT = Path(settings.BASE_DIR) / "skills" / "earnalism-audiovisual" / "software" / "eav" / "text.py"


def eav_sentences():
    spec = importlib.util.spec_from_file_location("eav_text_for_golden", EAV_TEXT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.sentences


class SentenceSplitTests(SimpleTestCase):
    def test_golden_offsets(self):
        for case in GOLDEN["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual([list(span) for span in split_sentences(case["text"])], case["offsets"])

    def test_offsets_are_a_partition_whose_text_equals_the_golden_sentences(self):
        for case in GOLDEN["cases"]:
            with self.subTest(case=case["name"]):
                spans = split_sentences(case["text"])
                if spans:
                    self.assertEqual(spans[0][0], 0)
                    self.assertEqual(spans[-1][1], len(case["text"]))
                    self.assertTrue(all(a[1] == b[0] for a, b in zip(spans, spans[1:])))
                self.assertEqual([" ".join(case["text"][s:e].split()) for s, e in spans], case["sentences"])

    def test_matches_eav_text_sentences_on_every_golden_case(self):
        sentences = eav_sentences()
        for case in GOLDEN["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(sentences(case["text"]), case["sentences"])
                self.assertEqual([" ".join(case["text"][s:e].split()) for s, e in split_sentences(case["text"])],
                                 sentences(case["text"]))
