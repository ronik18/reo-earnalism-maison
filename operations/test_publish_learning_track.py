"""The reviewed Selfish Giant companion track publishes idempotently and only for a live edition."""
import io
import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from library.models import Edition, Work
from learning.models import Lesson, QuestionOption, Track

INTAKE = Path(settings.BASE_DIR) / "learning" / "intake" / "selfish-giant-companion.json"


class PublishLearningTrackTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        options = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True)
        options.enable(); self.addCleanup(options.disable)
        call_command("seed_local_pilot", stdout=io.StringIO())
        self.live = Edition.objects.exclude(live_revision=None).first()
        work = Work.objects.create(slug="draft-only-work", title="Draft only", creators=["Test"], house="classics")
        self.draft = Edition.objects.create(work=work, slug="draft-only", locale="en")

    def run_command(self, edition):
        data = json.loads(INTAKE.read_text())
        data["edition_slug"] = edition.slug
        (self.dir / "selfish-giant-companion.json").write_text(json.dumps(data))
        out = io.StringIO()
        call_command("publish_learning_track", "selfish-giant-companion", "--intake-dir", str(self.dir), stdout=out)
        return json.loads(out.getvalue().split("MAISON_OUT ", 1)[1])

    def test_requires_the_linked_edition_to_be_live(self):
        before = Track.objects.count()
        with self.assertRaises(CommandError):
            self.run_command(self.draft)
        self.assertEqual(Track.objects.count(), before)

    def test_publishes_once_and_reruns_without_copies(self):
        before = Track.objects.count()
        first = self.run_command(self.live)
        second = self.run_command(self.live)
        self.assertEqual(first["track_id"], second["track_id"])
        self.assertEqual((first["published"], first["access"], first["lessons"]), (True, "free", 4))
        self.assertEqual(Track.objects.count(), before + 1)
        last = Lesson.objects.get(track_id=first["track_id"], ordinal=4)
        self.assertEqual((last.completion_rule, last.pass_score), ("quiz_pass", 75))
        self.assertEqual(last.quiz.questions.count(), 4)
        self.assertEqual(QuestionOption.objects.filter(question__quiz=last.quiz, is_correct=True).count(), 4)
        self.assertTrue(all(p["text"] for p in last.body))

    def test_shipped_intake_names_the_selfish_giant_edition(self):
        data = json.loads(INTAKE.read_text())
        self.assertEqual((data["edition_slug"], data["access"], len(data["lessons"])), ("the-selfish-giant-en", "free", 4))

    def test_shipped_bengali_intake_names_the_bicharak_edition(self):
        data = json.loads((INTAKE.parent / "bicharak-companion.json").read_text())
        self.assertEqual((data["edition_slug"], data["locale"], data["access"], len(data["lessons"])), ("bicharak", "bn", "free", 4))
        quiz = data["lessons"][-1]["quiz"]
        self.assertTrue(all(sum(o["correct"] for o in q["options"]) == 1 for q in quiz["questions"]))


class KshudhitaPashanCompanionTests(TestCase):
    """The ক্ষুধিত পাষাণ companion matches the বিচারক shape, quotes only the published text, and prints."""
    SLUG = "kshudhita-pashan-companion"
    SOURCE = Path(settings.BASE_DIR) / "library" / "intake" / "kshudhita-pashan" / "source.json"

    def setUp(self):
        self.data = json.loads((INTAKE.parent / f"{self.SLUG}.json").read_text())

    def test_shipped_intake_names_the_live_bengali_edition(self):
        data = self.data
        self.assertEqual((data["schema"], data["slug"], data["edition_slug"], data["locale"], data["access"],
                          data["duration_days"], len(data["lessons"])),
                         ("earnalism.learning_track.v1", self.SLUG, "kshudhita-pashan", "bn", "free", 4, 4))
        self.assertTrue(all(len(lesson["body"]) == 4 and all(lesson["body"]) for lesson in data["lessons"]))
        self.assertEqual([("quiz" in lesson) for lesson in data["lessons"]], [False, False, False, True])
        quiz = data["lessons"][-1]["quiz"]
        self.assertEqual((quiz["pass_score"], len(quiz["questions"])), (75, 4))
        self.assertTrue(all(sum(o["correct"] for o in q["options"]) == 1 for q in quiz["questions"]))

    # 1-based paragraph ranges of source.json each lesson covers; a lesson may quote only its own range,
    # so a quotation can never reach ahead of the day the reader is on.
    LESSON_PARAGRAPHS = [(1, 8), (10, 19), (20, 36), (37, 59)]

    def test_quotations_come_from_each_lessons_own_paragraphs(self):
        import re
        source = json.loads(self.SOURCE.read_text())
        (unit,) = source["units"]
        paragraphs = [p["text"] for p in unit["paragraphs"]]
        self.assertEqual(len(paragraphs), self.LESSON_PARAGRAPHS[-1][1])
        quoted = lambda strings: [q.rstrip("।!") for s in strings for q in re.findall("‘([^’]+)’", s)]
        # The description quotes only the story's title (the unit title), which is not a paragraph quotation.
        self.assertEqual(quoted([self.data["description"]]), [unit["title"]])
        self.assertEqual([lesson["title"] for lesson in self.data["lessons"] if "‘" in lesson["title"]], [])
        total = 0
        for lesson, (first, last) in zip(self.data["lessons"], self.LESSON_PARAGRAPHS, strict=True):
            strings = list(lesson["body"])
            for q in lesson.get("quiz", {}).get("questions", []):
                strings += [q["prompt"], q["explanation"]] + [o["text"] for o in q["options"]]
            allowed = "\n".join(paragraphs[first - 1:last])
            phrases = quoted(strings)
            self.assertTrue(phrases, lesson["title"])
            self.assertEqual([q for q in phrases if q not in allowed], [], lesson["title"])
            total += len(phrases)
        self.assertGreaterEqual(total, 14)

    def test_publishes_against_a_live_edition_and_renders_a_worksheet(self):
        from learning import worksheet
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        options = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True)
        options.enable(); self.addCleanup(options.disable)
        call_command("seed_local_pilot", stdout=io.StringIO())
        data = dict(self.data, edition_slug=Edition.objects.exclude(live_revision=None).first().slug)
        (Path(directory.name) / f"{self.SLUG}.json").write_text(json.dumps(data, ensure_ascii=False))
        out = io.StringIO()
        call_command("publish_learning_track", self.SLUG, "--intake-dir", directory.name, stdout=out)
        result = json.loads(out.getvalue().split("MAISON_OUT ", 1)[1])
        self.assertEqual((result["title"], result["published"], result["access"], result["lessons"]),
                         ("ক্ষুধিত পাষাণ পাঠ", True, "free", 4))
        last = Lesson.objects.get(track_id=result["track_id"], ordinal=4)
        self.assertEqual((last.completion_rule, last.pass_score, last.quiz.questions.count()), ("quiz_pass", 75, 4))
        _, lessons = worksheet.worksheet_content(result["track_id"])
        first = lessons[-1]["questions"][0]
        self.assertEqual(first["options"][first["correct"][0]], "তুলার মাশুল আদায়ের কাজে")
        for answers in (False, True):
            self.assertTrue(worksheet.render(result["track_id"], answers=answers).startswith(b"%PDF"))
