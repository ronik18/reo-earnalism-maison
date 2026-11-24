"""Social kit: tagged links, chapters only from real unit titles, exact-word quote cards."""
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from eav import social
from eav.cli import FONTS
from eav.record import Record
from tests.test_cli import RoundTwo, SOURCE, RATES, run

EDITION = "3b92b964-475f-4650-ae8e-6715f7730bd7"


class LinkTests(unittest.TestCase):
    def test_link_matches_the_maison_attribution_contract(self):
        url = social.campaign_url("https://theearnalism.com", EDITION, "selfish-giant", "youtube", "film-01")
        parts = urlsplit(url)
        self.assertEqual(parts.path, f"/en/titles/{EDITION}/")
        self.assertEqual(parse_qs(parts.query), {"utm_source": ["youtube"], "utm_campaign": ["selfish-giant"],
                                                 "utm_content": ["film-01"]})

    def test_bad_inputs_are_refused(self):
        for args in (("http://theearnalism.com", EDITION, "a", "youtube", "b"),
                     ("https://theearnalism.com/en/", EDITION, "a", "youtube", "b"),
                     ("https://theearnalism.com", "e-1", "a", "youtube", "b"),
                     ("https://theearnalism.com", EDITION, "A B", "youtube", "b"),
                     ("https://theearnalism.com", EDITION, "a", "tiktok", "b")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                social.campaign_url(*args)


class ChapterTests(unittest.TestCase):
    UNITS = [{"unit_id": f"u{i}", "title": f"Part {i}", "paragraphs": [{"anchor_id": f"a{i}", "text": "x"}]}
             for i in range(1, 4)]
    SCENES = [{"scene_id": f"f01s00{i}", "anchor_ids": [f"a{i}"]} for i in range(1, 4)]

    def timing(self, starts, end):
        return [{"unit_key": f"f01s00{i}-001", "start": s, "end": s + 1} for i, s in enumerate(starts, 1)] + \
               [{"unit_key": "f01s003-002", "start": end - 1, "end": end}]

    def test_unit_titles_become_youtube_chapters(self):
        marks = social.chapters(self.UNITS, self.SCENES, self.timing([0.4, 75.2, 3700.0], 3800))
        self.assertEqual(marks, [(0.0, "Part 1"), (75.2, "Part 2"), (3700.0, "Part 3")])
        self.assertEqual([social.stamp(s) for s, _ in marks], ["0:00", "1:15", "1:01:40"])

    def test_no_chapters_rather_than_invalid_or_invented_ones(self):
        self.assertEqual(social.chapters(self.UNITS[:2], self.SCENES, self.timing([0, 60, 120], 200)), [])
        self.assertEqual(social.chapters(self.UNITS, self.SCENES, self.timing([0, 5, 120], 200)), [])
        untitled = [dict(self.UNITS[0], title="")] + self.UNITS[1:]
        self.assertEqual(social.chapters(untitled, self.SCENES, self.timing([0, 60, 120], 200)), [])

    def test_description_and_reel_posts(self):
        text = social.film_description("The Selfish Giant", "Oscar Wilde", "https://x.test/l", [(0.0, "One")],
                                       ["Narration: Earnalism Voice (AI narration)."], ["#earnalism"])
        self.assertIn("Read it free on Earnalism: https://x.test/l", text)
        self.assertIn("0:00 One", text)
        self.assertIn("(link in bio)", social.reel_post("Hook", "https://x.test/l", clickable=False))
        self.assertIn("https://x.test/l", social.reel_post("Hook", "https://x.test/l", clickable=True))
        with self.assertRaises(ValueError):
            social.film_description("t", "a", "u", [], ["x" * 5001], [])


class QuoteTests(unittest.TestCase):
    UNITS = [{"paragraphs": [{"text": "Every afternoon the children played in the garden.\nIt was large."}]},
             {"paragraphs": [{"text": "আমি বিচারক, আমার কাছে দয়া নাই।"}]}]

    def test_only_the_books_exact_words(self):
        self.assertEqual(social.verify_quote("the children played  in the garden.", self.UNITS),
                         "the children played in the garden.")
        for bad in ("The children danced in the garden.", "", "x" * 221):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                social.verify_quote(bad, self.UNITS)

    def test_cards_render_in_english_and_bengali(self):
        with tempfile.TemporaryDirectory() as d:
            for lang, quote, marks in (("en", "Every afternoon the children played in the garden.", True),
                                       ("bn", "আমি বিচারক, আমার কাছে দয়া নাই।", False)):
                out = Path(d) / f"{lang}.png"
                bg = Path(d) / "bg.png"
                Image.new("RGB", (1920, 1080), (90, 120, 60)).save(bg)
                info = social.quote_card(quote, "Author", "theearnalism.com", FONTS[lang], FONTS["en"], out, bg, marks)
                with Image.open(out) as img:
                    self.assertEqual(img.size, (1080, 1080))
                    self.assertGreater(len(set(img.getdata())), 50)  # text actually drawn
                self.assertGreaterEqual(info["font_size"], 34)


class SocialCommandTests(RoundTwo, unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / "selfish-giant"
        self.ledger = self.d / "titles" / "allowance-ledger.json"
        self.src = self.d / "selfish-giant.json"
        self.src.write_text(json.dumps({**SOURCE, "edition_id": EDITION}), encoding="utf-8")
        self.rates = self.d / "rates.json"
        self.rates.write_text(json.dumps(RATES), encoding="utf-8")

    def init_and_plan(self):
        self.assertEqual(run("init", self.src, "--root", self.root, "--slug", "selfish-giant")[0], 0)
        self.assertEqual(run("plan", "--root", self.root)[0], 0)

    def social(self, *extra):
        return run("social", "--root", self.root, "--site", "https://theearnalism.com",
                   "--title", "The Selfish Giant", "--author", "Oscar Wilde", *extra)

    def test_kit_from_an_assembled_film_plus_a_quote_card(self):
        self.film_ready()
        bed = self.d / "bed.wav"
        self.noise(bed, 30)
        code, out = run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                        self.d / "end.png", "--score", bed, "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        code, out = self.social("--quote", "Every afternoon the children played in the garden.")
        self.assertEqual(code, 0, out)
        self.assertIn("Nothing is posted", out)
        kit = self.root / "social"
        links = json.loads((kit / "links.json").read_text())
        self.assertEqual(set(links), {"youtube-film-01", "instagram-quote-1"})
        self.assertIn("utm_source=youtube&utm_campaign=selfish-giant&utm_content=film-01", links["youtube-film-01"])
        text = (kit / "youtube-film-01.txt").read_text()
        self.assertIn("The Selfish Giant — Oscar Wilde", text)
        self.assertIn("CC0-1.0", text)
        self.assertIn("AI-generated", text)
        self.assertNotIn("Chapters", text)  # two short units: YouTube would reject them
        self.assertTrue((kit / "quote-1.png").is_file())
        kinds = [a["kind"] for a in Record.load(self.root).data["artifacts"]]
        self.assertEqual(kinds.count("social_kit"), 3)

    def test_refuses_invented_quotes_and_an_empty_kit(self):
        self.init_and_plan()
        code, out = self.social()
        self.assertEqual(code, 2)
        self.assertIn("nothing to write", out)
        code, out = self.social("--quote", "The giant loved winter most of all.")
        self.assertEqual(code, 2)
        self.assertIn("exact words", out)


if __name__ == "__main__":
    unittest.main()
