import json
import unittest
from pathlib import Path

from eav import cli
from eav.scenes import plan_film
from eav.voice import CLAUSE_PAUSE_MS, MAX_UNIT_CHARS, block_parts, split_unit, voice_units

PRESET = {"profile_id": "p1", "description": "A warm, steady narrator."}


class VoiceTests(unittest.TestCase):
    def test_voice_description_is_preset_byte_for_byte(self):
        scene = {"scene_id": "s1", "text": "One. Two."}
        units = voice_units(scene, PRESET, None)
        self.assertTrue(units)
        for u in units:
            self.assertEqual(u["description"], PRESET["description"])

    def test_clause_appended(self):
        units = voice_units({"scene_id": "s1", "text": "One."}, PRESET, "Slower, softer.")
        self.assertEqual(units[0]["description"], PRESET["description"] + " Slower, softer.")

    def test_clause_over_12_words_rejected(self):
        clause = " ".join(["word"] * 13)
        with self.assertRaises(ValueError):
            voice_units({"scene_id": "s1", "text": "One."}, PRESET, clause)

    def test_voice_units_cover_text_exactly(self):
        text = "First sentence. Second one?\n\nNew paragraph here!  Done."
        units = voice_units({"scene_id": "s1", "text": text}, PRESET, None)
        self.assertEqual(" ".join(u["text"] for u in units), " ".join(text.split()))
        self.assertEqual(len({u["unit_key"] for u in units}), len(units))

    def test_pauses(self):
        scene = {"scene_id": "s1", "text": "Title\n\nA one. A two.\n\nB one.",
                 "blocks": [{"anchor_id": "h", "kind": "heading", "text": "Title"},
                            {"anchor_id": "a", "kind": "paragraph", "text": "A one. A two."},
                            {"anchor_id": "b", "kind": "paragraph", "text": "B one."}]}
        units = voice_units(scene, PRESET, None)
        self.assertEqual([u["pause_after_ms"] for u in units], [1200, 400, 800, 800])

    def test_reel_lines_pause_400_ms(self):
        """R20: reel pacing is Squint pacing, 400 ms between lines (not the film's 800 ms)."""
        from eav import cli
        script = {"language": "en", "hook": "One line.", "loop_close": "Three. Four.",
                  "lines": ["One line.", "Two line.", "Three. Four."]}
        units = voice_units(cli._reel_scene(script, 1), PRESET, None)
        self.assertEqual([u["pause_after_ms"] for u in units], [400, 400, 400, 400])

    def test_plan_film_scene_feeds_voice(self):
        src = {"language": "en", "units": [{"unit_id": "u", "title": "T", "paragraphs": [
            {"anchor_id": "h", "kind": "heading", "text": "Chapter"},
            {"anchor_id": "a", "kind": "paragraph", "text": "Hello there. Goodbye."}]}]}
        scene = plan_film(src)["films"][0]["scenes"][0]
        units = voice_units(scene, PRESET, None)
        self.assertEqual(units[0]["pause_after_ms"], 1200)



def _norm(text: str) -> str:
    return " ".join(text.split())


def _production_root():
    """<repo>/production/audiovisual above this skill copy (either mirror), or None."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "production" / "audiovisual").is_dir():
            return parent / "production" / "audiovisual"
    return None


class SplitTests(unittest.TestCase):
    """V1: every unit fits Parler's ~30 s output cap (<= 200 chars), losslessly."""

    def assert_lossless(self, text, parts):
        self.assertEqual(" ".join(parts), _norm(text))
        for p in parts:
            self.assertTrue(p)
            self.assertLessEqual(len(p), MAX_UNIT_CHARS)
            self.assertEqual(p, p.strip())

    def test_limit_values(self):
        self.assertEqual(MAX_UNIT_CHARS, 200)
        self.assertEqual(CLAUSE_PAUSE_MS, 150)

    def test_short_sentence_is_one_unit(self):
        self.assertEqual(split_unit("  A short   one. "), ["A short one."])
        self.assertEqual(split_unit("x" * 200), ["x" * 200])

    def test_english_splits_at_the_comma_closest_to_the_middle(self):
        a = "The children came back to the garden after school every single day of the long year"
        b = "and they played among the flowers and the peach trees until the evening light faded"
        c = "while the selfish giant was far away visiting his friend"
        text = f"{a}, {b}, {c}."
        parts = split_unit(text)
        self.assert_lossless(text, parts)
        self.assertEqual(parts, [f"{a},", f"{b}, {c}."])

    def test_clause_punctuation_beats_a_more_central_space(self):
        text = ("word " * 30) + "end; " + ("tail " * 10) + "stop."
        parts = split_unit(text)
        self.assert_lossless(text, parts)
        self.assertTrue(parts[0].endswith("end;"))

    def test_dashes_and_colons_are_clause_points(self):
        for mark in ("—", "–", ":"):
            text = ("alpha " * 25) + mark + " " + ("beta " * 20) + "end."
            parts = split_unit(text)
            self.assert_lossless(text, parts)
            self.assertTrue(parts[0].endswith(mark), (mark, parts))

    def test_no_punctuation_splits_at_whitespace_near_the_middle(self):
        text = " ".join(f"w{i:03d}" for i in range(60))  # 299 chars
        parts = split_unit(text)
        self.assert_lossless(text, parts)
        self.assertEqual(len(parts), 2)
        self.assertLess(abs(len(parts[0]) - len(parts[1])), 6)

    def test_very_long_word_run_recurses(self):
        text = " ".join(["running"] * 300)  # 2399 chars, no punctuation
        parts = split_unit(text)
        self.assert_lossless(text, parts)
        self.assertGreaterEqual(len(parts), 12)

    def test_never_splits_inside_a_word(self):
        word = "অ" * 150
        text = f"{word} {word}।"
        self.assertEqual(split_unit(text), [word, word + "।"])
        with self.assertRaises(ValueError):
            split_unit("x" * 201)

    def test_bengali_danda_inside_a_sentence(self):
        a = " ".join(["তিনি বাগানে ফিরে এলেন"] * 6)
        b = " ".join(["শিশুরা খেলা করছিল"] * 6)
        for mark in ("॥", ","):
            text = f"{a}{mark} {b}।"
            parts = split_unit(text)
            self.assert_lossless(text, parts)
            self.assertEqual(parts, [f"{a}{mark}", f"{b}।"])

    def test_clause_mark_before_a_closing_quote(self):
        a = " ".join(["he said the garden was his own"] * 4)
        text = f"“{a},” " + ("and then he built a wall " * 4) + "around it."
        parts = split_unit(text)
        self.assert_lossless(text, parts)
        self.assertTrue(parts[0].endswith(",”"))

    def test_long_bengali_paragraph_units_and_pauses(self):
        clause = "তিনি অনেক দিন পরে বাগানে ফিরে এসে দেখলেন যে শিশুরা সেখানে খেলা করছে"
        long_sentence = ", ".join([clause] * 8) + "।"
        text = f"ছোট বাক্য। {long_sentence} শেষ।"
        scene = {"scene_id": "s1", "blocks": [{"anchor_id": "a", "kind": "paragraph", "text": text}]}
        units = voice_units(scene, PRESET, None, "bn")
        self.assertEqual(" ".join(u["text"] for u in units), _norm(text))
        self.assertTrue(all(len(u["text"]) <= MAX_UNIT_CHARS for u in units))
        self.assertGreater(len(units), 3)
        self.assertEqual([u["unit_key"] for u in units],
                         [f"s1-{i:03d}" for i in range(1, len(units) + 1)])
        pauses = [u["pause_after_ms"] for u in units]
        self.assertEqual(pauses[0], 400)  # "ছোট বাক্য।" ends its sentence
        self.assertEqual(pauses[-2], 400)  # last part of the long sentence keeps the sentence rule
        self.assertEqual(pauses[-1], 800)  # paragraph end
        self.assertEqual(set(pauses[1:-2]), {CLAUSE_PAUSE_MS})
        self.assertEqual(len(block_parts(text, "bn")), len(units))

    def test_split_last_part_of_a_heading_keeps_the_heading_pause(self):
        text = ", ".join(["a long heading phrase that goes on"] * 10)
        scene = {"scene_id": "s1", "blocks": [{"anchor_id": "h", "kind": "heading", "text": text}]}
        pauses = [u["pause_after_ms"] for u in voice_units(scene, PRESET, None)]
        self.assertEqual(pauses[-1], 1200)
        self.assertEqual(set(pauses[:-1]), {CLAUSE_PAUSE_MS})


class ProductionSourceTests(unittest.TestCase):
    """Every real title (read-only): units fit the limit and reproduce the book's text exactly."""

    def test_every_production_source_fits_and_is_lossless(self):
        root = _production_root()
        if root is None:
            self.skipTest("no production/audiovisual next to this skill copy")
        sources = sorted(root.glob("*/source.json"))
        self.assertTrue(sources)
        for src_path in sources:
            with self.subTest(title=src_path.parent.name):
                source = json.loads(src_path.read_text(encoding="utf-8"))
                lang = source["language"]
                plan_path = src_path.parent / "plan.json"
                preset = (json.loads(plan_path.read_text(encoding="utf-8"))["voice"]
                          if plan_path.is_file() else cli._story_preset(lang))
                self.assertEqual(preset["description"], cli._story_preset(lang)["description"])
                block_texts = []
                for f in plan_film(source)["films"]:
                    for sc in f["scenes"]:
                        units = voice_units(sc, preset, None, lang)
                        texts = [_norm(b["text"]) for b in sc["blocks"]]
                        block_texts += texts
                        self.assertEqual(" ".join(u["text"] for u in units), " ".join(texts))
                        self.assertEqual(len(units), sum(len(block_parts(b["text"], lang))
                                                         for b in sc["blocks"]))
                        for u in units:
                            self.assertLessEqual(len(u["text"]), MAX_UNIT_CHARS, u["unit_key"])
                            self.assertEqual(u["description"], preset["description"])
                        self.assertEqual([u["unit_key"] for u in units],
                                         [f"{sc['scene_id']}-{i:03d}"
                                          for i in range(1, len(units) + 1)])
                paragraphs = [_norm(p["text"]) for u in source["units"] for p in u["paragraphs"]]
                self.assertEqual(" ".join(block_texts), " ".join(paragraphs))


if __name__ == "__main__":
    unittest.main()
