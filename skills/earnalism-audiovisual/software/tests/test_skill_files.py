"""The skill text: frontmatter, references, stage-skill delegation and the byte-identical mirror."""
import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
REPO = next(p for p in SKILL.parents if (p / "AGENTS.md").is_file())
MIRROR = REPO / ".agents" / "skills" / "earnalism-audiovisual"
CANONICAL = REPO / "skills" / "earnalism-audiovisual"
STAGE_SKILLS = ("earnalism-book-production", "earnalism-audiobook-go-live",
                "earnalism-audiobook-score", "earnalism-video", "earnalism-covers",
                "earnalism-book-audiovisual")
REFERENCES = ("earnalism-voice.md", "film-recipe.md", "reel-recipe.md", "free-stack.md",
              "compute-budget.md", "production-record.md", "publishing.md", "pressure-tests.md",
              "colab-exchange.md")


def _frontmatter(text: str) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise AssertionError("SKILL.md has no frontmatter")
    out = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


class SkillFileTests(unittest.TestCase):
    def setUp(self):
        self.text = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    def test_skill_frontmatter(self):
        fm = _frontmatter(self.text)
        self.assertEqual(fm["name"], "earnalism-audiovisual")
        self.assertTrue(fm["description"].startswith(
            "Use when the owner names a book (English or Bengali) and wants its audiobook film, "
            "story reels or audiovisual package"))
        self.assertLessEqual(len(fm["description"]), 1024)
        self.assertLess(len(self.text.splitlines()), 260)

    def test_skill_mentions_every_stage_skill(self):
        for name in STAGE_SKILLS:
            self.assertIn(f"`{name}`", self.text, name)

    def test_references_exist_and_are_linked(self):
        for name in REFERENCES:
            self.assertTrue((SKILL / "references" / name).is_file(), name)
            self.assertIn(f"references/{name}", self.text, name)

    def test_stop_conditions_named(self):
        low = self.text.lower()
        for phrase in ("no cleared source", "budget exceeded", "import held", "qc failure",
                       "stream", "public-domain"):
            self.assertIn(phrase, low, phrase)

    def test_reel_recipe_documents_clips_spec(self):
        text = (SKILL / "references" / "reel-recipe.md").read_text(encoding="utf-8")
        self.assertIn("## Clips spec", text)
        for key in ("art_dir", "prior_attempt_evidence", "shots", '"id"', '"image"', '"seed"',
                    '"prompt"', "l4-balanced-v2"):
            self.assertIn(key, text, key)

    def test_pressure_results_recorded(self):
        text = (SKILL / "references" / "pressure-tests.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("Observed with the skill (2026-11-23): PASS"), 3)

    def test_mirror_identical(self):
        canon, mirror = _files(CANONICAL), _files(MIRROR)
        self.assertTrue(canon, "canonical skill folder is empty")
        self.assertEqual(sorted(canon), sorted(mirror))
        for rel, path in canon.items():
            self.assertEqual(path.read_bytes(), mirror[rel].read_bytes(), rel)

    def test_colab_exchange_documented_and_never_committed(self):
        text = (SKILL / "references" / "colab-exchange.md").read_text(encoding="utf-8")
        for phrase in ("RUN = True", "exchange-stage", "presign_colab_exchange", "--signed",
                       "exchange-collect", "Render one-off job", "never in record.json",
                       "reel_clips"):
            self.assertIn(phrase, text, phrase)
        self.assertIn("exchange", self.text.lower())
        ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("production/**/exchange.json", ignored)

    def test_pipeline_doc_points_to_entry_point(self):
        doc = (REPO / "docs" / "EARNALISM_AUDIOVISUAL_PIPELINE.md").read_text(encoding="utf-8")
        self.assertIn("`earnalism-audiovisual`", doc)

    def test_publishing_says_staging_needs_the_film_profile_for_now(self):
        text = " ".join((SKILL / "references" / "publishing.md").read_text(encoding="utf-8").split())
        self.assertIn("attach_audiovisual_audio", text)
        self.assertRegex(text, r"--profile film[^.]*until[^.]*interface note")


    def _ref(self, name):
        return " ".join((SKILL / "references" / name).read_text(encoding="utf-8").split())

    def test_film_recipe_states_rules_r1_to_r11(self):
        text = self._ref("film-recipe.md")
        for n in range(1, 12):
            self.assertRegex(text, rf"\bR{n}\b", f"R{n}")
        for phrase in ("plan-shots", "no holds", "6 s", "24 fps", "--shots", "glide", "film_clips",
                       "reference scene", "scene 14", "J- or L-cut", "1.5 dBTP", "17 dB"):
            self.assertIn(phrase.lower(), text.lower(), phrase)

    def test_voice_reference_names_v4_and_redo_gate(self):
        text = self._ref("earnalism-voice.md")
        for phrase in ("Eleven v4", "passage", "retime", "voicecheck", "--profile",
                       "redo", "voicecheck-profile.json", "24 November 2026", "eleven_v3",
                       "never open a passage on a bare"):
            self.assertIn(phrase, text, phrase)

    def test_free_stack_excludes_depth_base_large(self):
        text = self._ref("free-stack.md")
        self.assertIn("Depth-Anything-V2-Small", text)
        self.assertRegex(text, r"Base and Large[^.]*(non-commercial|excluded|refused)")
        for phrase in ("Wan 2.2 TI2V-5B", "MediaPipe", "OWLv2", "Whisper", "MIT"):
            self.assertIn(phrase, text, phrase)

    def test_free_stack_names_dinov2_not_clip(self):
        text = self._ref("free-stack.md")
        self.assertIn("DINOv2", text)
        self.assertRegex(text, r"CLIP[^.]*(excluded|out of scope|not used)")
        table = "\n".join(l for l in (SKILL / "references" / "free-stack.md").read_text(
            encoding="utf-8").splitlines() if l.startswith("|"))
        self.assertNotIn("CLIP-image", table)

    def test_skill_md_stage_order(self):
        order = ["plan-shots", "stills", "film_clips", "voice", "retime", "voicecheck", "cue",
                 "film --shots", "qc", "owner review"]
        flow = next(l for l in self.text.splitlines() if "plan-shots" in l and "film_clips" in l
                    and "owner review" in l)
        pos = [flow.index(k) for k in order]
        self.assertEqual(pos, sorted(pos), flow)
        self.assertNotIn("a fixed 60 CU", self.text)
        self.assertIn("title-caps.json", self.text)
        self.assertNotIn("fixed 60 CU", self._ref("compute-budget.md"))

    def test_pressure_tests_cover_cinematic_scenarios(self):
        text = self._ref("pressure-tests.md")
        for phrase in ("hold", "regenerate", "9 s glide", "split", "music borrowed",
                       "one cue per scene", "T5", "voicecheck", "country-limited"):
            self.assertIn(phrase, text, phrase)
        self.assertEqual(text.count("Observed with the skill (2026-11-23): PASS"), 3)


if __name__ == "__main__":
    unittest.main()
