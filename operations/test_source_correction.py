"""ক্ষুধিত পাষাণ scan-verified correction (27 Nov 2026): two restored words, a draft clearance, and a new revision.

The 1895 printed pages ১৭৬ and ১৮২ read "রাত্রিযাপন করিবেন না।" and "জানি না কিন্তু"; the Wikisource transcription that
was published on 25 Nov 2026 omitted both "না". The corrected packet waits for the Monday page; once approved, the
revise stage builds a new draft revision of the live edition, and the English pairing still aligns.
"""
import difflib
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from operations.management.commands import publish_cleared_editions as command
from operations.test_publish_packets import CLEARANCE, CORRECTED_CLEARANCE, as_first_published, first_published_bytes

SLUG = "kshudhita-pashan"
REPO = Path(command.ROOT)  # captured before any test patches command.ROOT
PACKET = REPO / "library" / "intake" / SLUG
EN_PACKET = REPO / "library" / "intake" / "kshudhita-pashan-en"
COVER = f"library/intake/{SLUG}/cover_provenance.json"
EN_CLEARANCE = "docs/evidence/publication-clearance-kshudhita-pashan-en-draft.json"
EN_COVER = "library/intake/kshudhita-pashan-en/cover_provenance.json"
# Queries of one ordinary (no anchor map) Reader publish through transition_revision with prepared validation.
ORDINARY_PUBLISH_QUERIES = 69
# Queries of a reader position save and a note create on the live revision (hot path), unchanged by round 6.
READER_SET_PROGRESS_QUERIES = 14
READER_CREATE_ANNOTATION_QUERIES = 13


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def paragraphs(raw):
    return json.loads(raw)["units"][0]["paragraphs"]


class CorrectedPacketTests(SimpleTestCase):
    def setUp(self):
        self.corrected = (PACKET / "source.json").read_bytes()
        self.published = first_published_bytes(self.corrected)
        self.approved = load(REPO / CLEARANCE)

    def test_corrected_source_differs_from_the_published_one_by_exactly_two_insertions_of_na(self):
        book = self.approved["books"][SLUG]
        self.assertEqual((command.sha256(self.published), len(self.published)), (book["source_sha256"], book["source_bytes"]))
        old, new = self.published.decode("utf-8"), self.corrected.decode("utf-8")
        ops = [op for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if op[0] != "equal"]
        self.assertEqual([(tag, i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in ops], [("insert", 0, 3), ("insert", 0, 3)])
        first = old.index("কখনো এখানে রাত্রিযাপন করিবেন") + len("কখনো এখানে রাত্রিযাপন করিবেন")
        second = old.index("নিষেধ করিতে লাগিল জানি") + len("নিষেধ করিতে লাগিল জানি")
        self.assertEqual(new, old[:first] + " না" + old[first:second] + " না" + old[second:])
        self.assertEqual(len(self.corrected) - len(self.published), 14)

    def test_only_paragraphs_6_and_37_change_and_the_structure_is_unchanged(self):
        before, after = paragraphs(self.published), paragraphs(self.corrected)
        self.assertEqual([p["kind"] for p in before], [p["kind"] for p in after])
        self.assertEqual(len(after), 59)
        changed = [n for n, (a, b) in enumerate(zip(before, after), 1) if a != b]
        self.assertEqual(changed, [6, 37])
        self.assertIn("কখনো এখানে রাত্রিযাপন করিবেন না।", after[5]["text"])
        self.assertIn("কে আমাকে নিষেধ করিতে লাগিল জানি না কিন্তু", after[36]["text"])

    def test_manifest_and_draft_clearance_bind_the_corrected_source(self):
        manifest = load(PACKET / "manifest.json")
        sha = command.sha256(self.corrected)
        self.assertEqual((manifest["source"]["sha256"], manifest["source"]["bytes"]), (sha, len(self.corrected)))
        self.assertEqual(manifest["provenance"]["rights_evidence_refs"], ["reo-earnalism-maison:" + CORRECTED_CLEARANCE])
        notes = manifest["provenance"]["source_edition"] + manifest["provenance"]["rights_note"]
        for fact in ("2026-11-27", "verified from printed page images", "১৭৬", "১৮২", "Wikisource transcription omitted",
                     "https://bn.wikisource.org/wiki/পাতা:গল্প-দশক_-_রবীন্দ্রনাথ_ঠাকুর.pdf/১৭৬",
                     "https://bn.wikisource.org/wiki/পাতা:গল্প-দশক_-_রবীন্দ্রনাথ_ঠাকুর.pdf/১৮২"):
            self.assertIn(fact, notes)
        draft = load(REPO / CORRECTED_CLEARANCE)
        self.assertEqual(draft["status"], "DRAFT_PENDING_OWNER_APPROVAL")
        self.assertIs(draft["approval"]["approved"], False)
        self.assertIsNone(draft["approval"]["approved_by"])
        self.assertNotIn("cover_attached", draft["approval"])
        self.assertEqual(set(draft["territories"]), set(settings.MAISON_PUBLICATION_TERRITORIES))
        self.assertEqual((draft["formats"], draft["actions"], draft["downloads"]), (["reader"], ["read", "preview"], False))
        book = draft["books"][SLUG]
        self.assertEqual((book["source_sha256"], book["source_bytes"]), (sha, len(self.corrected)))
        correction = book["source_correction"]
        self.assertEqual(correction["revises"]["clearance_record_sha256"], command.sha256((REPO / CLEARANCE).read_bytes()))
        self.assertEqual(correction["revises"]["source_sha256"], self.approved["books"][SLUG]["source_sha256"])
        self.assertEqual([(c["scan_page"], c["paragraph_ordinal"], c["inserted"]) for c in correction["changes"]],
                         [("১৭৬", 6, " না"), ("১৮২", 37, " না")])
        # The 25 Nov record stays exactly the owner-approved record of the text as first published.
        self.assertEqual(self.approved["status"], "OWNER_APPROVED")
        self.assertEqual(self.approved["books"][SLUG]["source_sha256"], command.sha256(self.published))

    def test_english_translation_binds_the_corrected_source_and_its_text_is_unchanged(self):
        record = load(EN_PACKET / "translation.json")
        self.assertEqual(record["source_sha256"], command.sha256(self.corrected))
        self.assertEqual(record["source_corrections"][0]["translated_from_sha256"], command.sha256(self.published))
        manifest = load(EN_PACKET / "manifest.json")
        english = (EN_PACKET / "source.json").read_bytes()
        self.assertEqual(command.sha256(english), manifest["source"]["sha256"])
        self.assertEqual(load(REPO / EN_CLEARANCE)["books"]["kshudhita-pashan-en"]["source_sha256"], manifest["source"]["sha256"])
        en = paragraphs(english)
        self.assertEqual([p["kind"] for p in en], [p["kind"] for p in paragraphs(self.corrected)])
        self.assertIn("never spend the night there", en[5]["text"])
        self.assertIn("Someone, I do not know who, kept forbidding me", en[36]["text"])


class CorrectionQueueTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("owner@example.test", "Test-Only-Passphrase-47", is_verified=True)

    def test_queue_puts_the_corrected_clearance_and_cover_on_the_monday_page_without_approving(self):
        from library.models import Edition, Revision, Work
        from operations.models import ReviewItem
        # As in production: The Hungry Stone is live, so its edition files are informational and not queued.
        work = Work.objects.create(slug=SLUG, title="ক্ষুধিত পাষাণ", creators=["রবীন্দ্রনাথ ঠাকুর"], house="golpo")
        english = Edition.objects.create(work=work, slug="kshudhita-pashan-en", locale="en")
        revision = Revision.objects.create(edition=english, title="The Hungry Stone", content_sha256="")
        Revision.objects.filter(pk=revision.pk).update(state="live")
        Edition.objects.filter(pk=english.pk).update(live_revision=revision)
        out = io.StringIO()
        call_command("queue_intake_packets", "--slug", SLUG, "--slug", "kshudhita-pashan-en", stdout=out)
        self.assertIn("kshudhita-pashan-en: edition files skipped (informational: the edition is already live)", out.getvalue())
        self.assertFalse(ReviewItem.objects.filter(kind="edition").exists())
        items = {(i.kind, i.ref): i for i in ReviewItem.objects.all()}
        for kind, ref in (("clearance", CORRECTED_CLEARANCE), ("cover", COVER)):
            item = items[(kind, ref)]
            self.assertEqual(item.sha256, command.sha256((REPO / ref).read_bytes()))
            self.assertEqual((item.status, item.decided_by, item.standing), ("pending", None, False))
        self.assertEqual(items[("clearance", CORRECTED_CLEARANCE)].summary["edition_slug"], SLUG)
        self.assertFalse(ReviewItem.objects.exclude(status="pending").exists())

    def test_corrected_packet_publishes_only_after_its_monday_approval(self):
        from operations.models import ReviewItem
        self.assertNotIn(SLUG, command.approved_packets())
        for kind, ref in (("clearance", CORRECTED_CLEARANCE), ("cover", COVER)):
            ReviewItem.objects.create(kind=kind, ref=ref, sha256=command.sha256((REPO / ref).read_bytes()),
                                      status="approved", decided_by=self.owner, decided_at=timezone.now(), summary={"edition_slug": SLUG})
        packet = command.approved_packets(check={SLUG})[SLUG]  # hash checks pass for the corrected source and covers
        self.assertEqual(packet["clearance_path"], CORRECTED_CLEARANCE)
        self.assertEqual(len(packet["review_items"]), 2)


@override_settings(FREE_ACCESS_ENABLED=True)
class ReviseStageTests(TestCase):
    """First publication of the 25 Nov text, then the approved correction becomes a new live revision."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        options = override_settings(MEDIA_ROOT=str(self.root / "media"), LOCAL=True)
        options.enable(); self.addCleanup(options.disable)
        self.intake = self.root / "library" / "intake"
        shutil.copytree(PACKET, self.intake / SLUG)
        as_first_published(self.intake / SLUG)
        (self.root / "docs" / "evidence").mkdir(parents=True)
        shutil.copy(REPO / CLEARANCE, self.root / CLEARANCE)
        for name, value in (("INTAKE", self.intake), ("ROOT", self.root)):
            patcher = mock.patch.object(command, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        user = get_user_model()
        self.publisher = user.objects.create_user("publisher@example.test", "Test-Only-Passphrase-47", is_verified=True)
        self.publisher.is_staff = True
        self.publisher.save()
        self.publisher.user_permissions.add(Permission.objects.get(codename="publish_revision"))
        self.owner = user.objects.create_user("owner@example.test", "Test-Only-Passphrase-47", is_verified=True)

    def run_command(self, stage, *books, extra=()):
        out = io.StringIO()
        args = [a for book in books for a in ("--book", book)]
        call_command("publish_cleared_editions", stage, "--publisher", str(self.publisher.public_id), *args, *extra, stdout=out)
        return json.loads(out.getvalue().split("MAISON_OUT ", 1)[1])

    def browser(self, shas):
        report = self.root / "browser.json"
        report.write_text(json.dumps({"scope": "test_replica", "books": {
            slug: {"status": "pass", "sha256": sha} for slug, sha in shas.items()}}), encoding="utf-8")
        return ("--browser-report", str(report))

    def approve(self, *refs):
        from operations.models import ReviewItem
        for kind, ref, slug in refs:
            ReviewItem.objects.create(kind=kind, ref=ref, sha256=command.sha256((self.root / ref).read_bytes()), status="approved",
                                      decided_by=self.owner, decided_at=timezone.now(), summary={"edition_slug": slug})

    def publish_first(self):
        imported = self.run_command("import", SLUG)
        self.run_command("evidence", SLUG, extra=self.browser({SLUG: imported[SLUG]["sha256"]}))
        return self.run_command("publish", SLUG)[SLUG]

    def apply_correction(self):
        for name in ("source.json", "manifest.json"):
            shutil.copy(PACKET / name, self.intake / SLUG / name)
        shutil.copy(REPO / CORRECTED_CLEARANCE, self.root / CORRECTED_CLEARANCE)

    def texts(self, revision_id):
        from library.models import Paragraph
        return list(Paragraph.objects.filter(unit__revision_id=revision_id).order_by("unit__ordinal", "ordinal").values_list("kind", "text", "anchor_id"))

    def test_revise_waits_for_the_monday_approval(self):
        first = self.publish_first()
        self.apply_correction()
        with self.assertRaises(CommandError):  # not an approved packet yet: --book has no such choice
            self.run_command("revise", SLUG)
        from library.models import Edition
        self.assertEqual(str(Edition.objects.get(slug=SLUG).live_revision_id), first["revision_id"])
        self.assertEqual(Edition.objects.get(slug=SLUG).revisions.count(), 1)

    def test_revise_builds_a_new_draft_revision_with_only_the_two_paragraphs_changed_then_publishes_it(self):
        from library.models import Edition, Revision
        first = self.publish_first()
        self.assertEqual(first["state"], "live")
        old = Revision.objects.get(pk=first["revision_id"])
        self.apply_correction()
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        revised = self.run_command("revise", SLUG)[SLUG]
        self.assertEqual(revised["changed_paragraphs"], {"chapter-001": [6, 37]})
        self.assertEqual(revised["replaces_revision_id"], str(old.id))
        self.assertEqual(revised["state"], "draft")
        # IDs and the text hash depend only on the slug and the corrected source, so a replica predicts production.
        self.assertEqual((revised["revision_id"], revised["sha256"]),
                         ("335dd363-de06-427c-bd43-b57373553eee", "7514f67a84623d233ac24c58a41a237f91ff160e8aa0d37c96cbcaa94464ce86"))
        new = Revision.objects.get(pk=revised["revision_id"])
        self.assertEqual(new.anchor_revision, old.anchor_revision + 1)
        self.assertEqual((new.title, new.description, new.edition_id), (old.title, old.description, old.edition_id))
        self.assertEqual(new.access_policy, {"reader": "free", "audio": "deny", "video": "deny"})
        before, after = self.texts(old.id), self.texts(new.id)
        self.assertEqual([k for k, _, _ in before], [k for k, _, _ in after])
        self.assertEqual([n for n, (a, b) in enumerate(zip(before, after), 1) if a[1] != b[1]], [6, 37])
        self.assertEqual(after[5][1], before[5][1].replace("করিবেন।", "করিবেন না।"))
        self.assertEqual(after[36][1], before[36][1].replace("জানি কিন্তু", "জানি না কিন্তু"))
        self.assertFalse({a for _, _, a in before} & {a for _, _, a in after})  # anchor_id is unique per revision
        source = new.assets.get(kind="reader_source")
        self.assertEqual(source.sha256, command.sha256((PACKET / "source.json").read_bytes()))
        self.assertTrue(new.rights.filter(approved=True, format="reader").count() == 2)
        self.assertEqual(Edition.objects.get(slug=SLUG).live_revision_id, old.id)  # readers keep the old text until publish
        self.assertEqual(revised["checks"]["publication_clearance"], "fail")
        self.assertEqual(revised["checks"]["browser"], "fail")
        again = self.run_command("revise", SLUG)[SLUG]  # rerun reuses the same deterministic draft
        self.assertEqual(again["revision_id"], revised["revision_id"])
        self.assertEqual(Edition.objects.get(slug=SLUG).revisions.count(), 2)

        self.run_command("evidence", SLUG, extra=self.browser({SLUG: revised["sha256"]}))
        published = self.run_command("publish", SLUG)[SLUG]
        self.assertEqual((published["state"], published["live"]), ("live", revised["revision_id"]))
        self.assertTrue(all(status in ("pass", "not_applicable") for status in published["checks"].values()), published["checks"])
        old.refresh_from_db()
        self.assertEqual(old.state, "retired")
        clearance = Revision.objects.get(pk=new.id).validation_evidence["publication_clearance"]
        self.assertTrue(clearance["evidence_ref"].startswith(CORRECTED_CLEARANCE + "#sha256="))
        self.assertIn("review_items=", clearance["evidence_ref"])

    def test_revise_refuses_when_the_live_revision_holds_audio(self):
        from library.models import Asset, Edition, Revision
        imported = self.run_command("import", SLUG)[SLUG]
        draft = Revision.objects.get(pk=imported["revision_id"])
        Asset.objects.bulk_create([Asset(revision=draft, unit=draft.units.get(), kind="audio_chapter", state="ready",
            storage_key=f"revisions/{draft.id}/audio-1.mp3", sha256="a" * 64, bytes=1, content_type="audio/mpeg", duration_ms=1000)])
        # Stand-in for an audio-bearing publication (attach_audiovisual_audio); the frozen-content guards allow this state change.
        Revision.objects.filter(pk=draft.pk).update(state="live", published_at=timezone.now())
        Edition.objects.filter(pk=draft.edition_id).update(live_revision=draft)
        self.apply_correction()
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        with self.assertRaises(CommandError) as raised:
            self.run_command("revise", SLUG)
        message = str(raised.exception)
        self.assertIn("REVISE_LIVE_HAS_MEDIA", message)
        self.assertIn("audio_chapter", message)
        self.assertIn("must be re-made", message)
        edition = Edition.objects.get(pk=draft.edition_id)
        self.assertEqual((edition.live_revision_id, edition.revisions.count()), (draft.id, 1))
        self.assertFalse(Asset.objects.filter(revision__edition=edition).exclude(revision=draft).exists())

    def test_revise_proceeds_when_the_live_revision_holds_only_text_and_covers(self):
        from library.models import Revision
        first = self.publish_first()
        live = Revision.objects.get(pk=first["revision_id"])
        self.assertEqual(set(live.assets.values_list("kind", flat=True)), {"reader_package", "reader_source", "cover"})
        self.apply_correction()
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        revised = self.run_command("revise", SLUG)[SLUG]
        self.assertTrue(revised["revised"])
        self.assertEqual(set(Revision.objects.get(pk=revised["revision_id"]).assets.values_list("kind", flat=True)),
                         set(command.REVISE_REBUILT_KINDS))

    def edit_draft(self, change):
        path = self.root / CORRECTED_CLEARANCE
        record = load(path)
        change(record["books"][SLUG])
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def set_source(self, raw):
        (self.intake / SLUG / "source.json").write_bytes(raw)
        path = self.intake / SLUG / "manifest.json"
        manifest = load(path)
        manifest["source"].update(sha256=command.sha256(raw), bytes=len(raw))
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.edit_draft(lambda book: book.update(source_sha256=command.sha256(raw), source_bytes=len(raw)))

    def assert_revise_refused(self, code):
        from library.models import Edition
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        with self.assertRaises(CommandError) as raised:
            self.run_command("revise", SLUG)
        self.assertIn(code, str(raised.exception))
        self.assertEqual(Edition.objects.get(slug=SLUG).revisions.count(), 1)

    def test_revise_refuses_a_change_the_approved_record_does_not_name(self):
        self.publish_first()
        self.apply_correction()
        raw = (self.intake / SLUG / "source.json").read_bytes()
        self.set_source(raw.replace("আমি এবং আমার আত্মীয়".encode(), "আমি ও আমার আত্মীয়".encode(), 1))  # an unapproved ¶1 edit
        self.assert_revise_refused("REVISE_CHANGES_DIFFER_FROM_APPROVED")

    def test_revise_refuses_when_the_record_names_fewer_changes_than_the_source_makes(self):
        self.publish_first()
        self.apply_correction()
        self.edit_draft(lambda book: book["source_correction"].update(changes=book["source_correction"]["changes"][:1]))
        self.assert_revise_refused("REVISE_CHANGES_DIFFER_FROM_APPROVED")

    def test_revise_refuses_when_a_change_text_differs_from_the_record(self):
        self.publish_first()
        self.apply_correction()
        self.edit_draft(lambda book: book["source_correction"]["changes"][1].update(inserted=" নাই"))
        self.assert_revise_refused("REVISE_CHANGES_DIFFER_FROM_APPROVED")

    def test_revise_refuses_when_the_live_text_is_not_the_source_the_correction_revises(self):
        self.publish_first()
        self.apply_correction()
        self.edit_draft(lambda book: book["source_correction"]["revises"].update(source_sha256="0" * 64))
        self.assert_revise_refused("REVISE_LIVE_SOURCE_MISMATCH")

    def test_revise_requires_a_source_correction_record(self):
        self.publish_first()
        self.apply_correction()
        self.edit_draft(lambda book: book.pop("source_correction"))
        self.assert_revise_refused("REVISE_CORRECTION_RECORD_REQUIRED")

    def test_evidence_and_publish_target_only_the_revise_revision(self):
        from library.models import Edition, Revision
        first = self.publish_first()
        self.apply_correction()
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        expected = str(command.revise_revision_id(command.approved_packets(check={SLUG})[SLUG]))
        for stage in ("evidence", "publish"):  # before revise, the newest revision is the old live one
            with self.assertRaises(CommandError) as raised:
                self.run_command(stage, SLUG)
            self.assertIn("REVISE_TARGET_MISMATCH", str(raised.exception))
        revised = self.run_command("revise", SLUG)[SLUG]
        self.assertEqual(revised["revision_id"], expected)
        edition = Edition.objects.get(slug=SLUG)
        other = Revision.objects.create(edition=edition, title="Another draft", content_sha256="")  # e.g. a later clone
        for stage, extra in (("evidence", self.browser({SLUG: revised["sha256"]})), ("publish", ())):
            with self.assertRaises(CommandError) as raised:
                self.run_command(stage, SLUG, extra=extra)
            self.assertIn("REVISE_TARGET_MISMATCH", str(raised.exception))
            self.assertIn(str(other.id), str(raised.exception))
        edition.refresh_from_db()
        self.assertEqual(str(edition.live_revision_id), first["revision_id"])
        self.assertNotIn("publication_clearance", Revision.objects.get(pk=expected).validation_evidence)

    def test_publish_moves_positions_notes_and_highlights_to_the_corrected_revision_once(self):
        import uuid
        from library.models import Edition, Paragraph, Revision
        from reader.models import Annotation, Progress
        from reader.services import annotation_data
        first = self.publish_first()
        old = Revision.objects.get(pk=first["revision_id"])
        edition = old.edition
        unit = old.units.get()
        p = {n: Paragraph.objects.get(unit=unit, ordinal=n) for n in (6, 10, 37)}
        users = [get_user_model().objects.create_user(f"reader{i}@example.test", "Test-Only-Passphrase-47", is_verified=True)
                 for i in range(3)]
        six, thirty_seven = p[6].text, p[37].text
        after_insert = six.index("রাত্রিযাপন করিবেন") + len("রাত্রিযাপন করিবেন") + 1  # just after the danda
        start37, end37 = thirty_seven.index("লাগিল"), thirty_seven.index("কিন্তু") + len("কিন্তু")
        ten_end = p[10].text.index(" ", 5)  # a word boundary

        def rng(paragraph, start, end):
            return {"unit_id": str(unit.id), "start_anchor_id": str(paragraph.anchor_id), "start_offset_chars": start,
                    "end_anchor_id": str(paragraph.anchor_id), "end_offset_chars": end, "offset_unit": "unicode_code_point"}

        def progress(user, paragraph, offset):
            return Progress.objects.create(user=user, edition=edition, revision=old, format="reader", last_operation_id=uuid.uuid4(),
                location={"format": "reader", "unit_id": str(unit.id), "anchor_id": str(paragraph.anchor_id), "offset_chars": offset})

        note_unchanged = Annotation.objects.create(user=users[0], revision=old, kind="note", range=rng(p[10], 0, ten_end),
                                                   note_text="unchanged", quoted_text=p[10].text[:ten_end])
        note_changed = Annotation.objects.create(user=users[0], revision=old, kind="note", range=rng(p[37], start37, end37),
                                                 note_text="changed", quoted_text=thirty_seven[start37:end37])
        highlight = Annotation.objects.create(user=users[1], revision=old, kind="highlight", color="gold",
                                              range=rng(p[6], 0, after_insert), quoted_text=six[:after_insert])
        bookmark = Annotation.objects.create(user=users[1], revision=old, kind="bookmark", range=rng(p[6], after_insert, after_insert))
        saved_changed, saved_unchanged = progress(users[0], p[6], after_insert), progress(users[1], p[10], ten_end)
        before_updated = Progress.objects.get(pk=saved_unchanged.pk).updated_at

        self.apply_correction()
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        revised = self.run_command("revise", SLUG)[SLUG]
        new = Revision.objects.get(pk=revised["revision_id"])
        record = new.validation_evidence["source_revision"]
        self.assertEqual(len(record["anchor_map"]), 59)
        self.assertEqual(record["unit_map"], {str(unit.id): str(new.units.get().id)})
        self.assertEqual(Progress.objects.filter(revision=old).count(), 2)  # nothing moves before publish
        self.run_command("evidence", SLUG, extra=self.browser({SLUG: revised["sha256"]}))
        published = self.run_command("publish", SLUG)[SLUG]
        self.assertEqual(published["steps"][-1]["reader_state_moved"], {"progress": 2, "annotations": 4, "left_unmapped": 0})

        new_unit = new.units.get()
        q = {n: Paragraph.objects.get(unit=new_unit, ordinal=n) for n in (6, 10, 37)}
        self.assertEqual(record["anchor_map"][str(p[6].anchor_id)], str(q[6].anchor_id))
        for row in (note_unchanged, note_changed, highlight, bookmark):
            row.refresh_from_db()
            self.assertEqual(row.revision_id, new.id)
            self.assertEqual(row.range["unit_id"], str(new_unit.id))
            self.assertEqual(row.version, 2)
            self.assertEqual(annotation_data(row)["anchor_status"], "valid")
        self.assertEqual((note_unchanged.range["start_anchor_id"], note_unchanged.range["end_offset_chars"]), (str(q[10].anchor_id), ten_end))
        self.assertEqual(note_unchanged.quoted_text, q[10].text[:ten_end])
        self.assertEqual(note_changed.range["start_anchor_id"], str(q[37].anchor_id))
        self.assertEqual(note_changed.quoted_text, "লাগিল জানি না কিন্তু")  # the range spans the restored word
        self.assertEqual(highlight.range["end_offset_chars"], after_insert + 3)
        self.assertTrue(highlight.quoted_text.endswith("রাত্রিযাপন করিবেন না।"))
        self.assertEqual((bookmark.range["start_offset_chars"], bookmark.range["end_offset_chars"]), (after_insert + 3, after_insert + 3))
        saved_changed.refresh_from_db(); saved_unchanged.refresh_from_db()
        self.assertEqual((saved_changed.revision_id, saved_changed.location["anchor_id"], saved_changed.location["offset_chars"]),
                         (new.id, str(q[6].anchor_id), after_insert + 3))
        self.assertLessEqual(saved_changed.location["offset_chars"], len(q[6].text))
        self.assertEqual((saved_unchanged.location["anchor_id"], saved_unchanged.location["offset_chars"]), (str(q[10].anchor_id), ten_end))
        self.assertEqual(saved_unchanged.updated_at, before_updated)  # the Continue shelf order is kept

        again = self.run_command("publish", SLUG)[SLUG]  # re-run: already live, nothing moves twice
        self.assertEqual(again["steps"], [])
        from operations.revision_remap import remap_reader_state
        self.assertEqual(remap_reader_state(old.id, new), {"progress": 0, "annotations": 0, "left_unmapped": 0})
        self.assertEqual(sorted(Annotation.objects.values_list("version", flat=True)), [2, 2, 2, 2])
        self.assertEqual(sorted(Progress.objects.values_list("version", flat=True)), [2, 2])
        self.assertEqual(Edition.objects.get(pk=edition.pk).live_revision_id, new.id)

    def prepare_correction(self):
        from library.models import Paragraph, Revision
        first = self.publish_first()
        old = Revision.objects.get(pk=first["revision_id"])
        self.apply_correction()
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        revised = self.run_command("revise", SLUG)[SLUG]
        self.run_command("evidence", SLUG, extra=self.browser({SLUG: revised["sha256"]}))
        paragraph = Paragraph.objects.get(unit__revision=old, ordinal=10)
        return old, Revision.objects.get(pk=revised["revision_id"]), paragraph

    def reader_progress(self, old, paragraph, email):
        import uuid
        from reader.models import Progress
        user = get_user_model().objects.create_user(email, "Test-Only-Passphrase-47", is_verified=True)
        return Progress.objects.create(user=user, edition=old.edition, revision=old, format="reader", last_operation_id=uuid.uuid4(),
            location={"format": "reader", "unit_id": str(paragraph.unit_id), "anchor_id": str(paragraph.anchor_id), "offset_chars": 0})

    def test_after_commit_pass_moves_a_position_written_against_the_old_revision_during_publish(self):
        from core.models import AuditEvent
        old, new, paragraph = self.prepare_correction()
        early = self.reader_progress(old, paragraph, "early@example.test")
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.run_command("publish", SLUG)
        early.refresh_from_db()
        self.assertEqual(early.revision_id, new.id)  # moved inside the publish transaction
        late = self.reader_progress(old, paragraph, "late@example.test")  # written while publish ran, against the old revision
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        late.refresh_from_db()
        self.assertEqual((late.revision_id, late.location["anchor_id"]),
                         (new.id, new.validation_evidence["source_revision"]["anchor_map"][str(paragraph.anchor_id)]))
        self.assertEqual(AuditEvent.objects.filter(action="revision.reader_state_moved", detail__pass="after_commit").count(), 1)
        callbacks[0]()  # idempotent: a second pass finds nothing and records nothing
        self.assertEqual(late.version, type(late).objects.get(pk=late.pk).version)
        self.assertEqual(AuditEvent.objects.filter(action="revision.reader_state_moved", detail__pass="after_commit").count(), 1)

    def test_any_publish_path_through_transition_revision_moves_reader_state(self):
        from library import services
        old, new, paragraph = self.prepare_correction()
        saved = self.reader_progress(old, paragraph, "staff-path@example.test")
        # As the staff API, Django admin and the scheduled-publication worker do: transition_revision directly.
        for action in ("mark-ready", "publish"):
            new.refresh_from_db()
            services.transition_revision(self.publisher, new.id, action, new.version, new.content_sha256, "Staff UI publish (test)")
        saved.refresh_from_db()
        self.assertEqual(saved.revision_id, new.id)
        self.assertEqual(saved.location["anchor_id"], new.validation_evidence["source_revision"]["anchor_map"][str(paragraph.anchor_id)])

    def test_publishing_a_revision_without_an_anchor_map_moves_nothing(self):
        from library import services
        from library.models import Revision
        from reader.models import Progress
        old, new, paragraph = self.prepare_correction()
        saved = self.reader_progress(old, paragraph, "plain@example.test")
        self.assertIsNone(services.move_reader_state(self.publisher, old.id, Revision(validation_evidence={})))
        self.assertIsNone(services.move_reader_state(self.publisher, None, new))
        self.assertEqual(Progress.objects.get(pk=saved.pk).revision_id, old.id)

    def flaky_after_commit(self):
        """remap_reader_state that works in the publish transaction and raises in the after-commit pass."""
        from django.db import OperationalError
        from operations import revision_remap
        real, calls = revision_remap.remap_reader_state, []

        def remap(*args):
            calls.append(args)
            if len(calls) > 1:
                raise OperationalError("synthetic lock timeout")
            return real(*args)
        return mock.patch.object(revision_remap, "remap_reader_state", side_effect=remap), calls

    def failure_audits(self):
        from core.models import AuditEvent
        return list(AuditEvent.objects.filter(action="revision.reader_state_move_failed").values_list("detail", flat=True))

    def test_a_raising_after_commit_pass_leaves_the_transition_result_unchanged(self):
        from library import services
        old, new, paragraph = self.prepare_correction()
        self.reader_progress(old, paragraph, "robust@example.test")
        new.refresh_from_db()
        state = services.transition_revision(self.publisher, new.id, "mark-ready", new.version, new.content_sha256, "Staff UI (test)")
        patcher, calls = self.flaky_after_commit()
        with patcher, self.captureOnCommitCallbacks(execute=True):
            result = services.transition_revision(self.publisher, new.id, "publish", state["version"], new.content_sha256, "Staff UI (test)")
        self.assertEqual((result["state"], result["edition_revision_id"]), ("live", str(new.id)))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.failure_audits(), [{"replaced_revision_id": str(old.id), "pass": "after_commit", "error": "OperationalError"}])

    def test_a_raising_after_commit_pass_does_not_fail_the_scheduled_job(self):
        from datetime import timedelta
        from core.models import OutboxJob
        from library import services
        from operations.publication import process_scheduled_publication
        old, new, paragraph = self.prepare_correction()
        new.refresh_from_db()
        state = services.transition_revision(self.publisher, new.id, "mark-ready", new.version, new.content_sha256, "Scheduled (test)")
        due = timezone.now() + timedelta(minutes=1)
        services.transition_revision(self.publisher, new.id, "schedule", state["version"], new.content_sha256, "Scheduled (test)", due)
        new.refresh_from_db()
        job = OutboxJob.objects.get(dedupe_key=f"scheduled-publication:{new.id}:{new.version}")
        patcher, _ = self.flaky_after_commit()
        with patcher, mock.patch("operations.publication.timezone.now", return_value=due + timedelta(seconds=1)), \
                self.captureOnCommitCallbacks(execute=True):
            result = process_scheduled_publication(job)
        self.assertEqual(result["status"], "published")
        self.assertEqual(len(self.failure_audits()), 1)

    def test_a_raising_after_commit_pass_keeps_the_server_job_publish_audit(self):
        from core.models import AuditEvent
        old, new, paragraph = self.prepare_correction()
        patcher, _ = self.flaky_after_commit()
        with patcher, self.captureOnCommitCallbacks(execute=True):
            published = self.run_command("publish", SLUG)[SLUG]
        self.assertEqual(published["state"], "live")
        self.assertEqual(published["steps"][-1]["reader_state_moved"], {"progress": 0, "annotations": 0, "left_unmapped": 0})
        self.assertEqual(AuditEvent.objects.filter(action="revision.publish", entity_id=str(new.id)).count(), 1)
        self.assertEqual(len(self.failure_audits()), 1)

    def test_a_failing_in_transaction_move_rolls_the_whole_publish_back(self):
        from core.models import AuditEvent
        from library.models import Edition
        from operations import revision_remap
        old, new, paragraph = self.prepare_correction()
        saved = self.reader_progress(old, paragraph, "rollback@example.test")
        edition_before = Edition.objects.values_list("version", "live_revision_id").get(pk=old.edition_id)
        with mock.patch.object(revision_remap, "remap_reader_state", side_effect=RuntimeError("synthetic")), \
                self.captureOnCommitCallbacks(execute=True) as callbacks, self.assertRaises(RuntimeError):
            self.run_command("publish", SLUG)
        self.assertEqual(callbacks, [])
        old.refresh_from_db(); new.refresh_from_db(); saved.refresh_from_db()
        self.assertEqual((old.state, new.state), ("live", "ready"))  # mark-ready committed on its own; publish did not
        self.assertEqual(Edition.objects.values_list("version", "live_revision_id").get(pk=old.edition_id), edition_before)
        self.assertEqual((saved.revision_id, saved.version), (old.id, 1))
        self.assertFalse(AuditEvent.objects.filter(action__in=["revision.reader_state_moved", "revision.publish"], entity_id=str(new.id)).exists())

    def test_an_anchor_map_for_a_different_revision_moves_nothing(self):
        import uuid
        from library import services
        from library.models import Revision
        old, new, paragraph = self.prepare_correction()
        saved = self.reader_progress(old, paragraph, "mismatch@example.test")
        evidence = new.validation_evidence
        evidence["source_revision"]["replaces_revision_id"] = str(uuid.uuid4())  # a map for some other revision
        Revision.objects.filter(pk=new.pk).update(validation_evidence=evidence)
        new.refresh_from_db()
        for action in ("mark-ready", "publish"):
            new.refresh_from_db()
            services.transition_revision(self.publisher, new.id, action, new.version, new.content_sha256, "Staff UI (test)")
        saved.refresh_from_db()
        self.assertEqual((saved.revision_id, saved.version), (old.id, 1))
        self.assertIsNone(services.move_reader_state(self.publisher, old.id, new))

    def test_an_ordinary_publish_pays_nothing_for_the_reader_state_move(self):
        from library import services
        from library.models import Revision
        imported = self.run_command("import", SLUG)[SLUG]
        self.run_command("evidence", SLUG, extra=self.browser({SLUG: imported["sha256"]}))
        draft = Revision.objects.get(pk=imported["revision_id"])
        state = services.transition_revision(self.publisher, draft.id, "mark-ready", draft.version, draft.content_sha256, "First publish (test)")
        prepared = services.prepare_revision_validation(draft.id)
        with self.assertNumQueries(0):  # no anchor map: two dict lookups, no query, no lock, no callback
            self.assertIsNone(services.move_reader_state(self.publisher, draft.id, draft))
        with self.assertNumQueries(ORDINARY_PUBLISH_QUERIES), self.captureOnCommitCallbacks() as callbacks:
            services.transition_revision(self.publisher, draft.id, "publish", state["version"], draft.content_sha256,
                                         "First publish (test)", prepared=prepared)
        self.assertFalse(any(getattr(c, "__name__", "") == "after_commit" for c in callbacks))

    # --- reader writes against a replaced revision (round 6) ------------------------------------------------------
    def position_input(self, revision_id, unit_id, anchor_id, offset):
        import uuid
        return {"operation_id": str(uuid.uuid4()), "edition_revision_id": str(revision_id),
                "location": {"format": "reader", "unit_id": str(unit_id), "anchor_id": str(anchor_id), "offset_chars": offset},
                "occurred_at": timezone.now().isoformat().replace("+00:00", "Z")}

    def note_input(self, revision_id, unit_id, anchor_id, start, end):
        import uuid
        return {"annotation_id": str(uuid.uuid4()), "edition_revision_id": str(revision_id), "kind": "note", "note_text": "n",
                "range": {"unit_id": str(unit_id), "start_anchor_id": str(anchor_id), "start_offset_chars": start,
                          "end_anchor_id": str(anchor_id), "end_offset_chars": end, "offset_unit": "unicode_code_point"}}

    def member(self, email):
        return get_user_model().objects.create_user(email, "Test-Only-Passphrase-47", is_verified=True)

    def publish_correction(self):
        from library.models import Paragraph
        old, new, _ = self.prepare_correction()
        self.run_command("publish", SLUG)
        old.refresh_from_db(); new.refresh_from_db()
        return old, new, {n: Paragraph.objects.get(unit__revision=old, ordinal=n) for n in (6, 10, 37)}

    def test_reader_writes_on_the_live_revision_cost_no_extra_queries(self):
        import uuid
        from library.models import Paragraph, Revision
        from reader import services as reader
        first = self.publish_first()
        live = Revision.objects.get(pk=first["revision_id"])
        paragraph = Paragraph.objects.get(unit__revision=live, ordinal=10)
        user = self.member("hot@example.test")
        end = paragraph.text.index(" ", 5)
        with self.assertNumQueries(READER_SET_PROGRESS_QUERIES):
            reader.set_progress(user, live.edition_id, "reader", self.position_input(live.id, paragraph.unit_id, paragraph.anchor_id, end), 0)
        with self.assertNumQueries(READER_CREATE_ANNOTATION_QUERIES):
            reader.create_annotation(user, self.note_input(live.id, paragraph.unit_id, paragraph.anchor_id, 0, end), str(uuid.uuid4()))

    def test_first_ever_note_posted_against_the_replaced_revision_lands_mapped_on_the_correction(self):
        import uuid
        from library.models import Paragraph
        from reader import services as reader
        from reader.models import Annotation
        old, new, p = self.publish_correction()
        user = self.member("late-note@example.test")
        text = p[37].text
        start, end = text.index("লাগিল"), text.index("কিন্তু") + len("কিন্তু")
        status, body = reader.create_annotation(user, self.note_input(old.id, p[37].unit_id, p[37].anchor_id, start, end), str(uuid.uuid4()))[:2]
        self.assertEqual(status, 201)
        row = Annotation.objects.get(pk=body["annotation_id"])
        target = Paragraph.objects.get(unit__revision=new, ordinal=37)
        self.assertEqual((row.revision_id, row.range["start_anchor_id"], row.range["unit_id"]), (new.id, str(target.anchor_id), str(target.unit_id)))
        self.assertEqual(row.quoted_text, "লাগিল জানি না কিন্তু")
        self.assertEqual((body["edition_revision_id"], body["anchor_status"]), (str(new.id), "valid"))

    def test_first_ever_position_saved_against_the_replaced_revision_lands_mapped_on_the_correction(self):
        from library.models import Paragraph
        from reader import services as reader
        from reader.models import Progress
        old, new, p = self.publish_correction()
        user = self.member("late-position@example.test")
        after = p[6].text.index("রাত্রিযাপন করিবেন") + len("রাত্রিযাপন করিবেন") + 1  # after the danda
        status, body = reader.set_progress(user, old.edition_id, "reader", self.position_input(old.id, p[6].unit_id, p[6].anchor_id, after), 0)[:2]
        self.assertEqual(status, 200)
        row = Progress.objects.get(user=user)
        target = Paragraph.objects.get(unit__revision=new, ordinal=6)
        self.assertEqual((row.revision_id, row.location["anchor_id"], row.location["offset_chars"]), (new.id, str(target.anchor_id), after + 3))
        self.assertEqual(body["edition_revision_id"], str(new.id))

    def test_a_note_whose_revision_was_read_before_the_switch_is_rechecked_and_mapped(self):
        import uuid
        from library.models import Revision
        from reader import services as reader
        from reader.models import Annotation
        old, new, p = self.publish_correction()
        real = reader.authorize_revision
        calls = []

        def stale_then_real(user, revision, *args, **kwargs):  # the first read happened before publish committed
            calls.append(revision)
            return Revision.objects.select_related("edition").get(pk=old.id) if len(calls) == 1 else real(user, revision, *args, **kwargs)
        end = p[10].text.index(" ", 5)
        with mock.patch.object(reader, "authorize_revision", side_effect=stale_then_real):
            body = reader.create_annotation(self.member("race@example.test"), self.note_input(old.id, p[10].unit_id, p[10].anchor_id, 0, end), str(uuid.uuid4()))[1]
        row = Annotation.objects.get(pk=body["annotation_id"])
        self.assertEqual(row.revision_id, new.id)
        self.assertEqual(row.range["start_anchor_id"], new.validation_evidence["source_revision"]["anchor_map"][str(p[10].anchor_id)])

    def test_a_write_against_an_unrelated_stale_revision_keeps_todays_response(self):
        import uuid
        from core.api import DomainError
        from library import services
        from library.models import Revision
        from reader import services as reader
        from reader.models import Annotation, Progress
        old, new, paragraph = self.prepare_correction()
        evidence = new.validation_evidence
        evidence["source_revision"]["replaces_revision_id"] = str(uuid.uuid4())  # the live map does not name `old`
        Revision.objects.filter(pk=new.pk).update(validation_evidence=evidence)
        for action in ("mark-ready", "publish"):
            new.refresh_from_db()
            services.transition_revision(self.publisher, new.id, action, new.version, new.content_sha256, "Staff UI (test)")
        user = self.member("stale@example.test")
        with self.assertRaises(DomainError) as raised:
            reader.set_progress(user, old.edition_id, "reader", self.position_input(old.id, paragraph.unit_id, paragraph.anchor_id, 0), 0)
        self.assertEqual((raised.exception.code, raised.exception.status), ("edition_revision_changed", 409))
        end = paragraph.text.index(" ", 5)
        with self.assertRaises(DomainError) as raised:
            reader.create_annotation(user, self.note_input(old.id, paragraph.unit_id, paragraph.anchor_id, 0, end), str(uuid.uuid4()))
        self.assertEqual((raised.exception.code, raised.exception.status), ("content_unavailable", 404))
        self.assertFalse(Progress.objects.filter(user=user).exists() or Annotation.objects.filter(user=user).exists())

    def test_map_offset_follows_an_insertion_and_clamps(self):
        from operations.revision_remap import map_offset
        old, new = "জানি কিন্তু", "জানি না কিন্তু"
        self.assertEqual(map_offset(old, new, old.index("কিন্তু"), "start"), new.index("কিন্তু"))
        self.assertEqual(map_offset(old, new, len("জানি"), "end"), len("জানি"))
        self.assertEqual(map_offset(old, new, len(old), "end"), len(new))
        self.assertEqual(map_offset("abcdef", "abc", 6, "start"), 3)  # clamped to the new length

    def test_revise_refuses_a_structural_change(self):
        self.publish_first()
        self.apply_correction()
        source = self.intake / SLUG / "source.json"
        record = json.loads(source.read_bytes())
        record["units"][0]["paragraphs"].append({"kind": "paragraph", "text": "অতিরিক্ত।"})
        raw = (json.dumps(record, ensure_ascii=False, indent=1) + "\n").encode()
        source.write_bytes(raw)
        for path in (self.intake / SLUG / "manifest.json", self.root / CORRECTED_CLEARANCE):
            value = load(path)
            target = value["source"] if "source" in value else value["books"][SLUG]
            key = "sha256" if "source" in value else "source_sha256"
            target.update({key: command.sha256(raw), ("bytes" if "source" in value else "source_bytes"): len(raw)})
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG))
        with self.assertRaises(CommandError) as raised:
            self.run_command("revise", SLUG)
        self.assertIn("REVISION_STRUCTURE_CHANGED", str(raised.exception))

    def test_english_side_by_side_pairs_with_the_corrected_revision(self):
        from library.models import Edition
        from library.services import parallel_companion
        self.publish_first()
        self.apply_correction()
        shutil.copytree(EN_PACKET, self.intake / "kshudhita-pashan-en")
        shutil.copy(REPO / EN_CLEARANCE, self.root / EN_CLEARANCE)
        self.approve(("clearance", CORRECTED_CLEARANCE, SLUG), ("cover", COVER, SLUG),
                     ("clearance", EN_CLEARANCE, "kshudhita-pashan-en"), ("cover", EN_COVER, "kshudhita-pashan-en"))
        imported = self.run_command("import", "kshudhita-pashan-en")
        revised = self.run_command("revise", SLUG)
        shas = {"kshudhita-pashan-en": imported["kshudhita-pashan-en"]["sha256"], SLUG: revised[SLUG]["sha256"]}
        self.run_command("evidence", SLUG, "kshudhita-pashan-en", extra=self.browser(shas))
        self.run_command("publish", SLUG, "kshudhita-pashan-en")
        bengali, english = Edition.objects.get(slug=SLUG), Edition.objects.get(slug="kshudhita-pashan-en")
        self.assertEqual(english.translated_from_id, bengali.id)
        self.assertEqual(str(bengali.live_revision_id), revised[SLUG]["revision_id"])
        reader = get_user_model().objects.create_user("reader@example.test", "Test-Only-Passphrase-47", is_verified=True)
        unit = english.live_revision.units.get()
        companion = parallel_companion(reader, english.id, unit.id)
        self.assertIsNotNone(companion)
        self.assertEqual(len(companion["paragraphs"]), 59)
        self.assertIn("রাত্রিযাপন করিবেন না।", companion["paragraphs"][5]["text"])
        self.assertIn("জানি না কিন্তু", companion["paragraphs"][36]["text"])
