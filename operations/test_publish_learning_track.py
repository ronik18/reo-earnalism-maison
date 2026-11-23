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
