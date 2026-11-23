import unittest

from eav.scenes import plan_film
from eav.text import estimate_seconds, sentences, words


def _para(i, n_sent=4, n_words=10):
    return " ".join(
        " ".join(f"w{i}x{s}y{k}" for k in range(n_words)) + "."
        for s in range(n_sent))


def _source(paragraphs, language="en", units=1):
    per = max(1, len(paragraphs) // units)
    out = []
    for u in range(units):
        chunk = paragraphs[u * per:(u + 1) * per] if u < units - 1 else paragraphs[u * per:]
        out.append({"unit_id": f"u{u}", "title": f"Unit {u}", "paragraphs": chunk})
    return {"language": language, "units": out}


class TextTests(unittest.TestCase):
    def test_bengali_danda_split(self):
        self.assertEqual(sentences("সে এল। তারপর গেল। কেন?", "bn"),
                         ["সে এল।", "তারপর গেল।", "কেন?"])

    def test_words_and_seconds(self):
        self.assertEqual(words("one two  three"), 3)
        self.assertAlmostEqual(estimate_seconds("a " * 120, "en"), 60.0)


class SceneTests(unittest.TestCase):
    def test_scenes_within_bounds(self):
        paras = [{"anchor_id": f"a{i}", "kind": "paragraph", "text": _para(i)}
                 for i in range(32)]
        film = plan_film(_source(paras))["films"][0]
        scenes = film["scenes"]
        for sc in scenes[:-1]:
            self.assertTrue(30 <= sc["seconds"] <= 90, sc["seconds"])
        last = scenes[-1]
        self.assertTrue(30 <= last["seconds"] <= 90 or last["flag"])
        seen = []
        for sc in scenes:
            for a in sc["anchor_ids"]:
                if a not in seen:
                    seen.append(a)
        self.assertEqual(seen, [p["anchor_id"] for p in paras])

    def test_oversized_paragraph_splits_on_sentences(self):
        text = _para(0, n_sent=40, n_words=10)  # 400 words
        paras = [{"anchor_id": "a0", "kind": "paragraph", "text": text}]
        scenes = plan_film(_source(paras))["films"][0]["scenes"]
        self.assertGreaterEqual(len(scenes), 2)
        self.assertEqual(" ".join(s["text"] for s in scenes), text)
        self.assertTrue(all(s["anchor_ids"] == ["a0"] for s in scenes))

    def test_single_huge_sentence_flagged(self):
        text = " ".join(f"w{i}" for i in range(250)) + "."
        paras = [{"anchor_id": "a0", "kind": "paragraph", "text": text}]
        scenes = plan_film(_source(paras))["films"][0]["scenes"]
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]["flag"], "over_90s_sentence")

    def test_long_book_becomes_series(self):
        paras = [{"anchor_id": f"a{i}", "kind": "paragraph", "text": _para(i, 5, 10)}
                 for i in range(120)]  # 6000 words
        plan = plan_film(_source(paras, units=2))
        self.assertIs(plan["series"], True)
        self.assertEqual(len(plan["films"]), 2)
        self.assertEqual([f["unit_ids"] for f in plan["films"]], [["u0"], ["u1"]])

    def test_short_book_single_film_and_keyframes(self):
        paras = [{"anchor_id": f"a{i}", "kind": "paragraph", "text": _para(i)}
                 for i in range(8)]
        plan = plan_film(_source(paras))
        self.assertIs(plan["series"], False)
        for sc in plan["films"][0]["scenes"]:
            self.assertGreaterEqual(sc["keyframes"] * 15, sc["seconds"])
            self.assertGreaterEqual(sc["keyframes"], 1)


if __name__ == "__main__":
    unittest.main()
