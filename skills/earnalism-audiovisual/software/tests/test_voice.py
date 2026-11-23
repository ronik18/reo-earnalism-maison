import unittest

from eav.scenes import plan_film
from eav.voice import voice_units

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

    def test_plan_film_scene_feeds_voice(self):
        src = {"language": "en", "units": [{"unit_id": "u", "title": "T", "paragraphs": [
            {"anchor_id": "h", "kind": "heading", "text": "Chapter"},
            {"anchor_id": "a", "kind": "paragraph", "text": "Hello there. Goodbye."}]}]}
        scene = plan_film(src)["films"][0]["scenes"][0]
        units = voice_units(scene, PRESET, None)
        self.assertEqual(units[0]["pause_after_ms"], 1200)


if __name__ == "__main__":
    unittest.main()
