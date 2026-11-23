"""Publish a reviewed learning track from learning/intake/<slug>.json (idempotent).

Identity is derived from the slug, so reruns update the same track, lessons and quiz
instead of creating copies. A track linked to an edition requires that edition to be
live. Output is JSON on stdout.
"""
import json
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from library.models import Edition
from learning.models import Lesson, Question, QuestionOption, Quiz, Track

NAMESPACE = uuid.UUID("0b8c5f7e-6a43-4d1e-9a1f-1c8e2f6b7d40")


def stable_id(*parts):
    """Deterministic, so reruns update in place; shaped as UUID4 because API inputs require UUID4."""
    return uuid.UUID(bytes=uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts)).bytes, version=4)


class Command(BaseCommand):
    help = "Publish (or update) a reviewed learning track from its intake file."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--unpublish", action="store_true")
        parser.add_argument("--intake-dir", help="directory holding <slug>.json (default learning/intake)")

    def handle(self, *args, slug, unpublish=False, intake_dir=None, **options):
        path = Path(intake_dir or Path(settings.BASE_DIR) / "learning" / "intake") / f"{slug}.json"
        if not path.is_file():
            raise CommandError(f"No intake file for {slug}.")
        data = json.loads(path.read_text())
        if data.get("schema") != "earnalism.learning_track.v1" or data.get("slug") != slug:
            raise CommandError("Intake schema or slug mismatch.")
        edition = None
        if data.get("edition_slug"):
            edition = Edition.objects.filter(slug=data["edition_slug"]).first()
            if edition is None or edition.live_revision_id is None:
                raise CommandError("The linked edition must be live before its track is published.")
        with transaction.atomic():
            track, _ = Track.objects.update_or_create(id=stable_id(slug, "track"), defaults=dict(
                title=data["title"], locale=data["locale"], kind=data["kind"], description=data["description"],
                duration_days=data.get("duration_days"), access=data["access"], edition=edition, published=False))
            for ordinal, item in enumerate(data["lessons"], 1):
                quiz_data = item.get("quiz")
                lesson, _ = Lesson.objects.update_or_create(id=stable_id(slug, "lesson", ordinal), defaults=dict(
                    track=track, title=item["title"], ordinal=ordinal, body=[{"text": t} for t in item["body"]],
                    completion_rule="quiz_pass" if quiz_data else "explicit",
                    pass_score=quiz_data["pass_score"] if quiz_data else 100))
                if quiz_data:
                    self.sync_quiz(slug, ordinal, lesson, quiz_data)
            if track.lessons.count() != len(data["lessons"]):
                raise CommandError("The track has lessons the intake file does not list; review it in the admin.")
            track.published = not unpublish
            track.save(update_fields=["published"])
        self.stdout.write("MAISON_OUT " + json.dumps({"track_id": str(track.id), "title": track.title,
            "published": track.published, "access": track.access, "lessons": track.lessons.count(),
            "edition": str(edition.id) if edition else None}, ensure_ascii=False))

    def sync_quiz(self, slug, ordinal, lesson, quiz_data):
        quiz, _ = Quiz.objects.get_or_create(id=stable_id(slug, "quiz", ordinal), defaults={"lesson": lesson})
        for q_ordinal, q in enumerate(quiz_data["questions"], 1):
            if sum(1 for o in q["options"] if o["correct"]) != 1:
                raise CommandError(f"Question {q_ordinal} needs exactly one correct option.")
            question = Question.objects.filter(id=stable_id(slug, "question", ordinal, q_ordinal)).first()
            if question is None:
                question = Question(id=stable_id(slug, "question", ordinal, q_ordinal), quiz=quiz, ordinal=q_ordinal)
            if (question.prompt, question.explanation) != (q["prompt"], q["explanation"]):
                question.prompt, question.explanation = q["prompt"], q["explanation"]
                question.save()
            for o_ordinal, o in enumerate(q["options"], 1):
                option = QuestionOption.objects.filter(id=stable_id(slug, "option", ordinal, q_ordinal, o_ordinal)).first()
                if option is None:
                    option = QuestionOption(id=stable_id(slug, "option", ordinal, q_ordinal, o_ordinal), question=question)
                if (option.text, option.is_correct) != (o["text"], o["correct"]):
                    if o["correct"]:
                        QuestionOption.objects.filter(question=question, is_correct=True).exclude(pk=option.pk).update(is_correct=False)
                    option.text, option.is_correct = o["text"], o["correct"]
                    option.save()
