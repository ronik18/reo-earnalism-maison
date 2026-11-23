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
              "compute-budget.md", "production-record.md", "publishing.md", "pressure-tests.md")


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

    def test_mirror_identical(self):
        canon, mirror = _files(CANONICAL), _files(MIRROR)
        self.assertTrue(canon, "canonical skill folder is empty")
        self.assertEqual(sorted(canon), sorted(mirror))
        for rel, path in canon.items():
            self.assertEqual(path.read_bytes(), mirror[rel].read_bytes(), rel)

    def test_pipeline_doc_points_to_entry_point(self):
        doc = (REPO / "docs" / "EARNALISM_AUDIOVISUAL_PIPELINE.md").read_text(encoding="utf-8")
        self.assertIn("`earnalism-audiovisual`", doc)


if __name__ == "__main__":
    unittest.main()
