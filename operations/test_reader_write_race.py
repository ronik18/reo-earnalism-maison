"""K1 round 7: a real reader-write race against a text-correction publish, on two database connections.

Thread A publishes the corrected revision and pauses inside the publish transaction, holding the edition row FOR
UPDATE. Thread B saves a position, note, highlight or bookmark against the old revision. B must wait for A's commit and
then land on the correction, mapped; the after-commit pass then has nothing left to move.
"""
import threading
import time
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings

from operations import test_source_correction as base  # a module import: its TestCases are not collected twice

COVER, CORRECTED_CLEARANCE, SLUG = base.COVER, base.CORRECTED_CLEARANCE, base.SLUG

PASSWORD = "Test-Only-Passphrase-47"


@override_settings(FREE_ACCESS_ENABLED=True)
class ReaderWriteRaceTests(TransactionTestCase):
    run_command, browser, approve = base.ReviseStageTests.run_command, base.ReviseStageTests.browser, base.ReviseStageTests.approve
    publish_first, apply_correction = base.ReviseStageTests.publish_first, base.ReviseStageTests.apply_correction
    position_input, note_input = base.ReviseStageTests.position_input, base.ReviseStageTests.note_input

    def setUp(self):
        from operations.models import PublicCacheGeneration
        PublicCacheGeneration.objects.get_or_create(pk=1, defaults={"epoch": 1})  # migration-seeded; a flush removes it
        base.ReviseStageTests.setUp(self)

    def member(self, email):
        return get_user_model().objects.create_user(email, PASSWORD, is_verified=True)

    def ready_correction(self, replaces_other=False):
        from library import services
        from library.models import Paragraph, Revision
        first = self.publish_first()
        old = Revision.objects.get(pk=first["revision_id"])
        self.apply_correction()
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        revised = self.run_command("revise", SLUG)[SLUG]
        self.run_command("evidence", SLUG, extra=self.browser({SLUG: revised["sha256"]}))
        new = Revision.objects.get(pk=revised["revision_id"])
        if replaces_other:  # the live map names some other revision: `old` becomes an unrelated stale revision
            evidence = new.validation_evidence
            evidence["source_revision"]["replaces_revision_id"] = str(uuid.uuid4())
            Revision.objects.filter(pk=new.pk).update(validation_evidence=evidence)
            new.refresh_from_db()
        state = services.transition_revision(self.publisher, new.id, "mark-ready", new.version, new.content_sha256, "Race (test)")
        paragraphs = {n: Paragraph.objects.get(unit__revision=old, ordinal=n) for n in (6, 10, 37)}
        return old, new, state["version"], paragraphs

    def race(self, new, version, write, pause_target, pause_name, first_call_only=True):
        """Publish in thread A, paused at `pause_target.pause_name` inside the publish transaction; `write` in thread B."""
        from library import services
        real = getattr(pause_target, pause_name)
        paused, release, calls, outcome = threading.Event(), threading.Event(), [], {}

        def hold(*args, **kwargs):
            if not calls or not first_call_only:
                if not paused.is_set():
                    paused.set()
                    release.wait(10)
            result = real(*args, **kwargs)
            calls.append(result)
            return result

        def publisher():
            try:
                services.transition_revision(self.publisher, new.id, "publish", version, new.content_sha256, "Race (test)")
            except Exception as error:  # surfaced below
                outcome["publish_error"] = error
            finally:
                connection.close()

        def reader():
            try:
                outcome["result"] = write()
            except Exception as error:
                outcome["error"] = error
            finally:
                outcome["done_at"] = time.monotonic()
                connection.close()

        with mock.patch.object(pause_target, pause_name, side_effect=hold):
            a = threading.Thread(target=publisher)
            a.start()
            self.assertTrue(paused.wait(10))
            b = threading.Thread(target=reader)
            b.start()
            b.join(0.5)
            self.assertTrue(b.is_alive(), "the reader write must wait for the publish holding the edition row")
            released_at = time.monotonic()
            release.set()
            a.join(10)
            b.join(10)
        self.assertNotIn("publish_error", outcome)
        self.assertGreaterEqual(outcome["done_at"], released_at)
        return outcome, calls

    def test_racing_position_note_highlight_and_bookmark_land_mapped_on_the_correction(self):
        from library.models import Paragraph
        from operations import revision_remap
        from reader import services as reader
        from reader.models import Annotation, Progress
        old, new, version, p = self.ready_correction()
        user = self.member("racer@example.test")
        six, thirty_seven = p[6].text, p[37].text
        after = six.index("রাত্রিযাপন করিবেন") + len("রাত্রিযাপন করিবেন") + 1  # just after the danda
        start37, end37 = thirty_seven.index("লাগিল"), thirty_seven.index("কিন্তু") + len("কিন্তু")
        notes = [self.note_input(old.id, p[37].unit_id, p[37].anchor_id, start37, end37),
                 {**self.note_input(old.id, p[6].unit_id, p[6].anchor_id, 0, after), "kind": "highlight", "color": "gold", "note_text": None},
                 {**self.note_input(old.id, p[6].unit_id, p[6].anchor_id, after, after), "kind": "bookmark", "note_text": None}]

        def write():
            results = [reader.set_progress(user, old.edition_id, "reader", self.position_input(old.id, p[6].unit_id, p[6].anchor_id, after), 0)]
            return results + [reader.create_annotation(user, note, str(uuid.uuid4())) for note in notes]
        outcome, passes = self.race(new, version, write, revision_remap, "remap_reader_state")
        self.assertNotIn("error", outcome)
        self.assertEqual(len(passes), 2)  # in the publish transaction, then after commit
        self.assertEqual(passes[1], {"progress": 0, "annotations": 0, "left_unmapped": 0})  # nothing was left behind
        q = {n: Paragraph.objects.get(unit__revision=new, ordinal=n) for n in (6, 37)}
        position = Progress.objects.get(user=user)
        self.assertEqual((position.revision_id, position.location["anchor_id"], position.location["offset_chars"]),
                         (new.id, str(q[6].anchor_id), after + 3))
        rows = {row.kind: row for row in Annotation.objects.filter(user=user)}
        self.assertEqual({row.revision_id for row in rows.values()}, {new.id})
        self.assertEqual((rows["note"].range["start_anchor_id"], rows["note"].quoted_text), (str(q[37].anchor_id), "লাগিল জানি না কিন্তু"))
        self.assertEqual((rows["highlight"].range["start_anchor_id"], rows["highlight"].range["end_offset_chars"]),
                         (str(q[6].anchor_id), after + 3))
        self.assertTrue(rows["highlight"].quoted_text.endswith("রাত্রিযাপন করিবেন না।"))
        self.assertEqual((rows["bookmark"].range["start_offset_chars"], rows["bookmark"].range["end_offset_chars"]),
                         (after + 3, after + 3))

    def test_racing_writes_against_an_unrelated_stale_revision_keep_todays_responses(self):
        from core.api import DomainError
        from library import search
        from reader import services as reader
        from reader.models import Annotation, Progress
        old, new, version, p = self.ready_correction(replaces_other=True)
        user = self.member("unrelated@example.test")
        end = p[10].text.index(" ", 5)

        def write():
            try:
                reader.set_progress(user, old.edition_id, "reader", self.position_input(old.id, p[10].unit_id, p[10].anchor_id, 0), 0)
            except DomainError as error:
                return error.code, error.status
        # No reader-state move runs for an unrelated map, so the publish is held later in its transaction.
        outcome, _ = self.race(new, version, write, search, "refresh_revision_search")
        self.assertEqual(outcome.get("result"), ("edition_revision_changed", 409))
        self.assertFalse(Progress.objects.filter(user=user).exists())
        with self.assertRaises(DomainError) as raised:  # after the switch the old revision is retired: today's 404
            reader.create_annotation(user, self.note_input(old.id, p[10].unit_id, p[10].anchor_id, 0, end), str(uuid.uuid4()))
        self.assertEqual((raised.exception.code, raised.exception.status), ("content_unavailable", 404))
        self.assertFalse(Annotation.objects.filter(user=user).exists())

    def test_a_reader_write_that_times_out_on_the_lock_returns_the_contract_retryable_503(self):
        old, new, version, p = self.ready_correction()
        user = self.member("timeout@example.test")
        self.client.post("/api/v1/auth/login", {"email": user.email, "password": PASSWORD, "password_purpose_consent": True,
                         "password_purpose_version": "password-account-v1"}, content_type="application/json")
        locked, release = threading.Event(), threading.Event()

        def holder():  # a publish-like holder of the edition row
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM maison_edition WHERE id=%s FOR UPDATE", [old.edition_id])
                    locked.set()
                    release.wait(10)
            finally:
                connection.close()
        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(locked.wait(10))
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '200ms'")
            response = self.client.put(f"/api/v1/me/progress/{old.edition_id}/reader",
                                       self.position_input(old.id, p[10].unit_id, p[10].anchor_id, 0),
                                       content_type="application/json", HTTP_IF_MATCH='"v0"')
        finally:
            release.set()
            thread.join(10)
            with connection.cursor() as cursor:
                cursor.execute("RESET lock_timeout")
        self.assertEqual(response.status_code, 503, response.content)
        body = response.json()
        self.assertEqual((body["code"], body["retryable"]), ("temporarily_unavailable", True))
        self.assertTrue(response.has_header("Retry-After"))
