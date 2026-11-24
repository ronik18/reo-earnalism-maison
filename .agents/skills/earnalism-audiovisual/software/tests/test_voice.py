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


EXPRESSIVE = {"group": True, "pauses": True, "direct": True}
STORY = ("The giant came home. He was tired. The garden was empty. "
         "He sat down by the wall and looked at the bare trees for a very long time, until the night fell.")


def para(text, anchor="a"):
    return {"scene_id": "s1", "blocks": [{"anchor_id": anchor, "kind": "paragraph", "text": text}]}


class ExpressiveVoiceTests(unittest.TestCase):
    """Owner 2026-11-24: natural storytelling (grouping, direction, varied pauses)."""

    def test_default_style_is_unchanged(self):
        scene = para(STORY)
        self.assertEqual(voice_units(scene, PRESET, None), voice_units(scene, PRESET, None, "en", style=None))
        self.assertEqual(len(voice_units(scene, PRESET, None)), 4)

    def test_grouping_merges_short_sentences_and_keeps_text_exact(self):
        units = voice_units(para(STORY), PRESET, None, "en", style=EXPRESSIVE)
        self.assertEqual(" ".join(u["text"] for u in units), " ".join(STORY.split()))
        self.assertLess(len(units), 4)
        self.assertEqual(units[0]["text"], "The giant came home. He was tired. The garden was empty.")
        self.assertEqual([u["unit_key"] for u in units], [f"s1-{i:03d}" for i in range(1, len(units) + 1)])

    def test_grouping_is_capped_and_never_splits_a_sentence(self):
        long = " ".join(["Word"] * 20) + ". " + " ".join(["Next"] * 20) + "."
        units = voice_units(para(long), PRESET, None, "en", style=EXPRESSIVE)
        self.assertEqual(len(units), 2)
        huge = " ".join(["Word"] * 40) + "."
        self.assertEqual([u["text"] for u in voice_units(para(huge), PRESET, None, "en", style=EXPRESSIVE)],
                         [huge])
        from eav.voice import MAX_GROUP_WORDS
        many = " ".join(["One two three."] * 30)
        for u in voice_units(para(many), PRESET, None, "en", style=EXPRESSIVE):
            self.assertLessEqual(len(u["text"].split()), MAX_GROUP_WORDS)

    def test_grouping_never_crosses_paragraphs_headings_or_turns(self):
        scene = {"scene_id": "s1", "blocks": [
            {"anchor_id": "h", "kind": "heading", "text": "One. Two."},
            {"anchor_id": "a", "kind": "paragraph", "text": "He came. He sat."},
            {"anchor_id": "b", "kind": "paragraph",
             "text": "She looked up. \u201cWho are you?\u201d \u201cA giant.\u201d He smiled. He laughed."}]}
        texts = [u["text"] for u in voice_units(scene, PRESET, None, "en", style=EXPRESSIVE)]
        self.assertEqual(texts, ["One.", "Two.", "He came. He sat.", "She looked up.",
                                 "\u201cWho are you?\u201d", "\u201cA giant.\u201d", "He smiled. He laughed."])

    def test_one_speech_across_sentences_groups(self):
        text = "\u201cCome here. Sit down.\u201d"
        units = voice_units(para(text), PRESET, None, "en", style=EXPRESSIVE)
        self.assertEqual([u["text"] for u in units], [text])

    def test_property_concatenation_equals_source(self):
        import random
        rnd = random.Random(7)
        pool = ["He ran.", "Why?", "\u201cStop!\u201d", "The long road wound on and on past the hills.",
                "Wait\u2026", "\u0986\u09ae\u09bf \u098f\u09b2\u09be\u09ae\u0964", "She said \u2014", "Yes!"]
        for _ in range(200):
            paras = [" ".join(rnd.choice(pool) for _ in range(rnd.randint(1, 9))) for _ in range(rnd.randint(1, 4))]
            scene = {"scene_id": "x", "blocks": [{"anchor_id": f"p{i}", "kind": "paragraph", "text": t}
                                                 for i, t in enumerate(paras)]}
            units = voice_units(scene, PRESET, None, "bn", style=EXPRESSIVE)
            self.assertEqual(" ".join(u["text"] for u in units), " ".join(" ".join(paras).split()))
            from eav.voice import unit_anchors
            anchors = unit_anchors(scene, "bn", EXPRESSIVE)
            self.assertEqual(len(anchors), len(units))
            for i, t in enumerate(paras):
                self.assertEqual(" ".join(u["text"] for u, a in zip(units, anchors) if a == f"p{i}"),
                                 " ".join(t.split()))

    def test_direction_defaults_narration_and_conversation(self):
        scene = para("He looked up. \u201cWho are you?\u201d")
        units = voice_units(scene, PRESET, None, "en", style=EXPRESSIVE)
        self.assertEqual(units[0]["description"], PRESET["description"] + " A speaks in a narration tone.")
        self.assertEqual(units[1]["description"],
                         PRESET["description"] + " A speaks in a conversation tone.")
        named = dict(PRESET, speaker="Arjun")
        self.assertTrue(voice_units(scene, named, None, "en", style=EXPRESSIVE)[0]["description"]
                        .endswith(" Arjun speaks in a narration tone."))

    def test_direction_applies_emotion_and_clause(self):
        scene = para("He looked up. \u201cWho are you?\u201d")
        d = {"s1-002": {"emotion": "Fear", "clause": "Hushed, trembling, slower."}}
        units = voice_units(scene, dict(PRESET, speaker="Arjun"), "Global clause.", "en",
                            style=EXPRESSIVE, directions=d)
        self.assertEqual(units[1]["description"], PRESET["description"]
                         + " Arjun speaks in a fear tone. Hushed, trembling, slower.")
        self.assertTrue(units[0]["description"].endswith(" narration tone. Global clause."))

    def test_directions_validated(self):
        from eav.voice import validate_directions
        units = voice_units(para("One. Two."), PRESET, None, "en", style=EXPRESSIVE)
        validate_directions({"s1-001": {"emotion": "Sad"}}, units)
        for bad in ({"s1-099": {"emotion": "Sad"}}, {"s1-001": {"emotion": "Melancholy"}},
                    {"s1-001": {"emotion": "Sad", "clause": " ".join(["w"] * 13)}},
                    {"s1-001": {"emotion": "Sad", "pitch": "high"}}, {"s1-001": "Sad"}, []):
            with self.assertRaises(ValueError):
                validate_directions(bad, units)
        with self.assertRaises(ValueError):  # directions need the direction mode
            voice_units(para("One."), PRESET, None, "en", directions={"s1-001": {"emotion": "Sad"}})

    def test_expressive_pauses(self):
        from eav.voice import (DIALOGUE_TURN_PAUSE_MS, QUESTION_PAUSE_MS, SUSPENSE_PAUSE_MS,
                               SCENE_PAUSE_MS, PARAGRAPH_PAUSE_MS, HEADING_PAUSE_MS)
        scene = {"scene_id": "s1", "blocks": [
            {"anchor_id": "h", "kind": "heading", "text": "Title"},
            {"anchor_id": "a", "kind": "paragraph",
             "text": " ".join(["Word"] * 25) + ". Was it gone? " + " ".join(["Word"] * 25)
             + " and then... " + " ".join(["Word"] * 25) + ". \u201cHello.\u201d He waited."},
            {"anchor_id": "b", "kind": "paragraph", "text": "The end."}]}
        units = voice_units(scene, PRESET, None, "en", style=EXPRESSIVE)
        self.assertEqual([u["pause_after_ms"] for u in units],
                         [HEADING_PAUSE_MS, QUESTION_PAUSE_MS, SUSPENSE_PAUSE_MS,
                          DIALOGUE_TURN_PAUSE_MS, DIALOGUE_TURN_PAUSE_MS, PARAGRAPH_PAUSE_MS,
                          SCENE_PAUSE_MS])
        self.assertTrue(400 < QUESTION_PAUSE_MS < SUSPENSE_PAUSE_MS < PARAGRAPH_PAUSE_MS
                        < HEADING_PAUSE_MS <= SCENE_PAUSE_MS)
        self.assertTrue(400 < DIALOGUE_TURN_PAUSE_MS < PARAGRAPH_PAUSE_MS)

    def test_reel_lines_unchanged_in_expressive_style(self):
        from eav import cli
        script = {"language": "en", "hook": "One line.", "loop_close": "Three. Four?",
                  "lines": ["One line.", "Two line!", "Three. Four?"]}
        units = voice_units(cli._reel_scene(script, 1), PRESET, None, "en", style=EXPRESSIVE)
        self.assertEqual([u["text"] for u in units], ["One line.", "Two line!", "Three.", "Four?"])
        self.assertEqual([u["pause_after_ms"] for u in units], [400, 400, 400, 400])

    def test_continuous_take_style_adds_only_the_scene_end_pause(self):
        """ElevenLabs takes carry their own pauses: none inside a scene, 1200 ms at its end."""
        from eav.voice import CONTINUOUS, TAKE_SCENE_PAUSE_MS
        scene = {"scene_id": "s1", "text": "Title\n\nA one. A two?\n\nB one...",
                 "blocks": [{"anchor_id": "h", "kind": "heading", "text": "Title"},
                            {"anchor_id": "a", "kind": "paragraph", "text": "A one. A two?"},
                            {"anchor_id": "b", "kind": "paragraph", "text": "B one..."}]}
        plain = voice_units(scene, PRESET, None)
        units = voice_units(scene, PRESET, None, "en", style=CONTINUOUS)
        self.assertEqual(TAKE_SCENE_PAUSE_MS, 1200)
        self.assertEqual([u["unit_key"] for u in units], [u["unit_key"] for u in plain])
        self.assertEqual([u["text"] for u in units], [u["text"] for u in plain])  # never grouped
        self.assertEqual([u["pause_after_ms"] for u in units], [0, 0, 0, 1200])

    def test_continuous_reel_take_adds_no_pause(self):
        from eav import cli
        from eav.voice import CONTINUOUS
        script = {"language": "en", "hook": "One line.", "loop_close": "Three. Four?",
                  "lines": ["One line.", "Two line!", "Three. Four?"]}
        units = voice_units(cli._reel_scene(script, 1), PRESET, None, "en", style=CONTINUOUS)
        self.assertEqual([u["pause_after_ms"] for u in units], [0, 0, 0, 0])

    def test_continuous_excludes_the_parler_storyteller_modes(self):
        for other in ("group", "pauses", "direct"):
            with self.assertRaises(ValueError):
                voice_units(para("One. Two."), PRESET, None, "en", style={"continuous": True, other: True})

    def test_unknown_style_key_refused(self):
        with self.assertRaises(ValueError):
            voice_units(para("One."), PRESET, None, "en", style={"group": True, "loud": True})

    def test_audition_units(self):
        from eav.voice import audition_units
        passages = {"narration": "The giant came home. He was tired.",
                    "dialogue": "\u201cWho are you?\u201d he asked.",
                    "emotional": "She wept. The garden was gone."}
        variants = [("control", PRESET, None),
                    ("arjun-storyteller", dict(PRESET, speaker="Arjun"), EXPRESSIVE)]
        units = audition_units(passages, variants, "en", {"emotional-001": {"emotion": "Sad"}})
        keys = [u["unit_key"] for u in units]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all("__" in k for k in keys))
        self.assertIn("control__narration-001", keys)
        self.assertIn("arjun-storyteller__emotional-001", keys)
        for name, _, _ in variants:
            for pk, text in passages.items():
                got = " ".join(u["text"] for u in units if u["unit_key"].startswith(f"{name}__{pk}-"))
                self.assertEqual(got, " ".join(text.split()))
        sad = next(u for u in units if u["unit_key"] == "arjun-storyteller__emotional-001")
        self.assertIn("sad tone", sad["description"])
        ctrl = next(u for u in units if u["unit_key"] == "control__emotional-001")
        self.assertEqual(ctrl["description"], PRESET["description"])


if __name__ == "__main__":
    unittest.main()
