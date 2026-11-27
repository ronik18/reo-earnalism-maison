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

    def test_queue_puts_the_corrected_clearance_cover_and_translation_on_the_monday_page_without_approving(self):
        from operations.models import ReviewItem
        out = io.StringIO()
        call_command("queue_intake_packets", "--slug", SLUG, "--slug", "kshudhita-pashan-en", stdout=out)
        items = {(i.kind, i.ref): i for i in ReviewItem.objects.all()}
        for kind, ref in (("clearance", CORRECTED_CLEARANCE), ("cover", COVER),
                          ("edition", "library/intake/kshudhita-pashan-en/translation.json")):
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
