"""Owner-approved intake packets are discovered for publication; unapproved or altered ones never are."""
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from operations.management.commands import publish_cleared_editions as command

CLEARANCE = "docs/evidence/publication-clearance-kshudhita-pashan.json"


class PublishPacketDiscoveryTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.intake = self.root / "library" / "intake"
        shutil.copytree(command.INTAKE / "kshudhita-pashan", self.intake / "kshudhita-pashan")
        (self.root / CLEARANCE).parent.mkdir(parents=True)
        shutil.copy(command.ROOT / CLEARANCE, self.root / CLEARANCE)

    def packets(self):
        return command.approved_packets(self.intake, root=self.root)

    def edit_clearance(self, change):
        path = self.root / CLEARANCE
        record = json.loads(path.read_text(encoding="utf-8"))
        change(record)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def test_approved_packet_with_cover_is_discovered(self):
        packet = self.packets()["kshudhita-pashan"]
        self.assertEqual(packet["slug"], "kshudhita-pashan")
        self.assertEqual(packet["edition_slug"], "kshudhita-pashan")
        self.assertEqual(Path(packet["folder"]), self.intake / "kshudhita-pashan")
        self.assertEqual(packet["clearance_path"], CLEARANCE)
        self.assertEqual(len(packet["clearance_sha256"]), 64)

    def test_draft_or_cover_pending_packet_is_skipped(self):
        self.edit_clearance(lambda r: (r.update(status="OWNER_APPROVED_COVER_PENDING"),
                                       r["approval"].update(still_required=["front/back cover"])))
        self.assertNotIn("kshudhita-pashan", self.packets())
        self.edit_clearance(lambda r: (r.update(status="OWNER_APPROVED"), r["approval"].pop("still_required")))
        self.assertIn("kshudhita-pashan", self.packets())  # an absent still_required means nothing is outstanding
        self.edit_clearance(lambda r: r["approval"].update(still_required=[], approved=False))
        self.assertNotIn("kshudhita-pashan", self.packets())
        self.edit_clearance(lambda r: r.update(status="DRAFT"))
        self.assertNotIn("kshudhita-pashan", self.packets())

    def test_packet_without_covers_is_skipped(self):
        (self.intake / "kshudhita-pashan" / "front.jpg").unlink()
        self.assertNotIn("kshudhita-pashan", self.packets())

    def test_source_changed_after_approval_is_refused(self):
        source = self.intake / "kshudhita-pashan" / "source.json"
        source.write_bytes(source.read_bytes() + b" ")
        with self.assertRaises(CommandError) as raised:
            self.packets()
        self.assertIn("SOURCE_HASH_MISMATCH", str(raised.exception))

    def test_cover_changed_after_approval_is_refused(self):
        front = self.intake / "kshudhita-pashan" / "front.jpg"
        front.write_bytes(front.read_bytes() + b"\0")
        with self.assertRaises(CommandError) as raised:
            self.packets()
        self.assertIn("COVER_HASH_MISMATCH", str(raised.exception))

    def test_existing_bicharak_and_selfish_giant_still_listed(self):
        listed = command.approved_packets()
        self.assertIn("bicharak", listed)
        self.assertIn("the-selfish-giant", listed)
        self.assertIn("kshudhita-pashan", listed)
        self.assertEqual(listed["bicharak"]["edition_slug"], "bicharak")
        self.assertEqual(listed["bicharak"]["clearance_path"], command.CLEARANCE_DOC)
        self.assertEqual(listed["kshudhita-pashan"]["clearance_path"], CLEARANCE)

    def test_status_must_be_exactly_owner_approved(self):
        self.edit_clearance(lambda r: r.update(status="OWNER_APPROVED_COVER_PENDING"))
        self.assertNotIn("kshudhita-pashan", self.packets())

    def test_cover_attached_hashes_must_match_the_cover_files(self):
        self.edit_clearance(lambda r: r["approval"]["cover_attached"].update(back_sha256="0" * 64))
        with self.assertRaises(CommandError) as raised:
            self.packets()
        self.assertIn("COVER_HASH_MISMATCH", str(raised.exception))

    def test_check_limits_hash_verification_to_the_named_books(self):
        source = self.intake / "kshudhita-pashan" / "source.json"
        source.write_bytes(source.read_bytes() + b" ")
        self.assertIn("kshudhita-pashan", command.approved_packets(self.intake, root=self.root, check=()))
        with self.assertRaises(CommandError):
            command.approved_packets(self.intake, root=self.root, check={"kshudhita-pashan"})

    def test_kshudhita_reason_and_clearance_reference_its_own_record(self):
        packet = command.approved_packets()["kshudhita-pashan"]
        reason = command.reason_for(packet)
        self.assertIn(CLEARANCE + "#sha256=" + packet["clearance_sha256"], reason)
        self.assertNotIn(command.CLEARANCE_DOC, reason)
        doc, doc_sha = command.clearance_document(packet)
        self.assertEqual(doc_sha, packet["clearance_sha256"])
        self.assertIn("kshudhita-pashan", doc["books"])


class MondayApprovalTests(TestCase):
    """Owner decision D8: approving a clearance item and its cover item on the Monday page approves that exact packet."""
    SLUG = "kshudhita-pashan"
    COVER = "library/intake/kshudhita-pashan/cover_provenance.json"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.intake = self.root / "library" / "intake"
        shutil.copytree(command.INTAKE / self.SLUG, self.intake / self.SLUG)
        (self.root / CLEARANCE).parent.mkdir(parents=True)
        shutil.copy(command.ROOT / CLEARANCE, self.root / CLEARANCE)
        self.edit_clearance(lambda r: (r.update(status="DRAFT_PENDING_OWNER_APPROVAL"), r.pop("approval", None)))
        self.owner = get_user_model().objects.create_user("owner@example.test", "Test-Only-Passphrase-47", is_verified=True)

    def edit_clearance(self, change):
        path = self.root / CLEARANCE
        record = json.loads(path.read_text(encoding="utf-8"))
        change(record)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def digest(self, ref):
        return command.sha256((self.root / ref).read_bytes())

    def item(self, kind, ref, status="approved", standing=False, **extra):
        from django.utils import timezone
        from operations.models import ReviewItem
        extra.setdefault("summary", {"edition_slug": self.SLUG})
        extra.setdefault("decided_at", timezone.now() if status == "approved" else None)
        return ReviewItem.objects.create(kind=kind, ref=ref, sha256=extra.pop("sha256", self.digest(ref)), status=status,
                                         decided_by=self.owner if status == "approved" else None, standing=standing, **extra)

    def approve_both(self):
        return self.item("clearance", CLEARANCE), self.item("cover", self.COVER)

    def packets(self):
        return command.approved_packets(self.intake, root=self.root)

    def test_monday_approval_qualifies_draft_packet(self):
        self.assertNotIn(self.SLUG, self.packets())
        self.approve_both()
        packet = self.packets()[self.SLUG]
        self.assertEqual(packet["clearance_path"], CLEARANCE)
        self.assertEqual(len(packet["review_items"]), 2)

    def test_changed_clearance_after_monday_approval_does_not_qualify(self):
        self.approve_both()
        self.assertIn(self.SLUG, self.packets())
        self.edit_clearance(lambda r: r.update(note="edited after approval"))
        self.assertNotIn(self.SLUG, self.packets())

    def test_cover_item_also_required(self):
        self.item("clearance", CLEARANCE)
        self.assertNotIn(self.SLUG, self.packets())
        from operations.models import ReviewItem
        ReviewItem.objects.all().delete()
        self.item("cover", self.COVER)
        self.assertNotIn(self.SLUG, self.packets())

    def test_rejected_or_pending_items_do_not_qualify(self):
        for status in ("pending", "rejected"):
            from operations.models import ReviewItem
            ReviewItem.objects.all().delete()
            self.item("clearance", CLEARANCE)
            self.item("cover", self.COVER, status=status)
            self.assertNotIn(self.SLUG, self.packets(), status)

    def test_approved_item_without_decider_does_not_unlock(self):
        from operations.models import ReviewItem
        self.approve_both()
        self.assertIn(self.SLUG, self.packets())
        ReviewItem.objects.update(decided_by=None)
        self.assertNotIn(self.SLUG, self.packets())
        ReviewItem.objects.update(decided_by=self.owner, decided_at=None)
        self.assertNotIn(self.SLUG, self.packets())

    def test_standing_is_database_forbidden_for_clearance_items(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.item("clearance", CLEARANCE, standing=True)

    def test_only_draft_pending_status_qualifies(self):
        self.approve_both()
        for status in ("REJECTED", "WITHDRAWN", "DRAFT"):
            self.edit_clearance(lambda r: r.update(status=status))
            from operations.models import ReviewItem
            ReviewItem.objects.all().delete()
            self.approve_both()
            self.assertNotIn(self.SLUG, self.packets(), status)

    def test_clearance_item_must_name_the_packet_edition(self):
        self.item("clearance", CLEARANCE, summary={"edition_slug": "another-book"})
        self.item("cover", self.COVER)
        self.assertNotIn(self.SLUG, self.packets())

    def test_reverify_refuses_when_files_change_after_discovery(self):
        self.approve_both()
        packet = self.packets()[self.SLUG]
        command.reverify_approval(packet)
        self.edit_clearance(lambda r: r.update(note="changed after discovery"))
        with self.assertRaises(CommandError) as raised:
            command.reverify_approval(packet)
        self.assertIn("MONDAY_APPROVAL_VOIDED", str(raised.exception))

    def make_actor(self):
        actor = get_user_model().objects.create_user("publisher16@example.test", "Test-Only-Passphrase-47", is_verified=True)
        actor.is_staff = True
        actor.save()
        return actor

    def make_draft(self, packet, content_sha=None):
        from library.models import Asset, Edition, Revision, Work
        edition = Edition.objects.create(work=Work.objects.create(slug="w-" + packet["edition_slug"], title="Test work"),
                                         slug=packet["edition_slug"], locale="bn")
        revision = Revision.objects.create(edition=edition, title="Draft", content_sha256=content_sha or "")
        pair = {}
        for side, digest in zip(("front", "back"), packet["covers"]):
            Asset.objects.create(revision=revision, kind="cover", state="ready", storage_key=f"revisions/{revision.id}/{side}", sha256=digest,
                                 bytes=1, content_type="image/jpeg")
            pair[side] = {"sha256": digest}
        revision.validation_evidence = {"cover_pair": pair}
        revision.save()
        return revision

    def test_recorded_clearance_evidence_ref_cites_review_items(self):
        self.approve_both()
        packet = self.packets()[self.SLUG]
        revision = self.make_draft(packet)
        command.Command().record_evidence(self.make_actor(), packet, None)
        revision.refresh_from_db()
        ref = revision.validation_evidence["publication_clearance"]["evidence_ref"]
        self.assertEqual(ref, command.evidence_ref_for(packet))
        self.assertIn("review_items=", ref)
        self.assertIn("decided_by=" + str(self.owner.public_id), ref)

    def test_legacy_packet_evidence_ref_keeps_the_plain_form(self):
        packet = command.approved_packets(check=())["bicharak"]
        self.assertFalse(packet.get("review_items"))
        doc, _ = command.clearance_document(packet)
        revision = self.make_draft(packet, doc["books"]["bicharak"].get("maison_revision_content_sha256"))
        command.Command().record_evidence(self.make_actor(), packet, None)
        revision.refresh_from_db()
        ref = revision.validation_evidence["publication_clearance"]["evidence_ref"]
        self.assertEqual(ref, packet["clearance_path"] + "#sha256=" + packet["clearance_sha256"])
        self.assertNotIn("review_items", ref)

    def test_publish_and_offer_reader_refuse_after_the_files_change(self):
        self.approve_both()
        packet = self.packets()[self.SLUG]
        revision = self.make_draft(packet)
        actor = self.make_actor()
        before = (revision.state, revision.version, revision.preview, revision.access_policy)
        self.edit_clearance(lambda r: r.update(note="changed after discovery"))
        for call in (lambda: command.Command().publish(actor, packet),
                     lambda: command.Command().offer_reader(actor, revision, packet)):
            with self.assertRaises(CommandError) as raised:
                call()
            self.assertIn("MONDAY_APPROVAL_VOIDED", str(raised.exception))
        revision.refresh_from_db()
        self.assertEqual((revision.state, revision.version, revision.preview, revision.access_policy), before)
        self.assertFalse(revision.rights.exists())

    def test_source_change_still_refused_for_db_approved_packet(self):
        self.approve_both()
        source = self.intake / self.SLUG / "source.json"
        source.write_bytes(source.read_bytes() + b" ")
        with self.assertRaises(CommandError) as raised:
            self.packets()
        self.assertIn("SOURCE_HASH_MISMATCH", str(raised.exception))

    def test_reason_cites_review_items(self):
        items = self.approve_both()
        packet = self.packets()[self.SLUG]
        reason = command.reason_for(packet)
        self.assertIn(CLEARANCE + "#sha256=" + packet["clearance_sha256"], reason)
        for item in items:
            self.assertIn(str(item.id), reason)
        self.assertIn(str(self.owner.public_id), reason)
        self.assertIn(str(items[0].id), command.evidence_ref_for(packet))
        self.assertIn("draft record approved on the Monday page (review items " + str(items[0].id), reason)

    def test_monday_approved_evidence_basis_says_draft_record_not_in_file(self):
        items = self.approve_both()
        packet = self.packets()[self.SLUG]
        revision = self.make_draft(packet)
        command.Command().record_evidence(self.make_actor(), packet, None)
        revision.refresh_from_db()
        basis = revision.validation_evidence["publication_clearance"]["basis"]
        self.assertEqual(basis, "draft_record_approved_on_monday_page")
        legacy = command.approved_packets(check=())["bicharak"]
        self.assertNotIn("Monday page", command.reason_for(legacy))


class PublishStageGuardTests(TestCase):
    def setUp(self):
        self.publisher = get_user_model().objects.create_user("publisher@example.test", "Test-Only-Passphrase-47", is_verified=True)
        self.publisher.is_staff = True
        self.publisher.save()
        self.publisher.user_permissions.add(Permission.objects.get(codename="publish_revision"))

    def run_command(self, stage, *extra):
        out = io.StringIO()
        call_command("publish_cleared_editions", stage, "--publisher", str(self.publisher.public_id), *extra, stdout=out)
        return out.getvalue()

    def test_evidence_and_publish_require_a_book_or_all(self):
        from core.models import AuditEvent
        from library.models import Edition
        before = (AuditEvent.objects.count(), Edition.objects.count())
        for stage in ("evidence", "publish"):
            with self.assertRaises(CommandError) as raised:
                self.run_command(stage)
            self.assertIn("BOOK_REQUIRED", str(raised.exception))
        self.assertEqual((AuditEvent.objects.count(), Edition.objects.count()), before)

    def test_a_tampered_packet_does_not_break_status_of_another_book(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        intake = root / "library" / "intake"
        shutil.copytree(command.INTAKE, intake)
        (root / CLEARANCE).parent.mkdir(parents=True)
        shutil.copy(command.ROOT / CLEARANCE, root / CLEARANCE)
        shutil.copy(command.ROOT / command.CLEARANCE_DOC, root / command.CLEARANCE_DOC)
        source = intake / "kshudhita-pashan" / "source.json"
        source.write_bytes(source.read_bytes() + b" ")
        with mock.patch.object(command, "INTAKE", intake), mock.patch.object(command, "ROOT", root):
            self.assertIn("MAISON_OUT", self.run_command("status", "--book", "bicharak"))
            with self.assertRaises(CommandError) as raised:
                self.run_command("status", "--book", "kshudhita-pashan")
        self.assertIn("SOURCE_HASH_MISMATCH", str(raised.exception))


class TranslationImportTests(TestCase):
    def setUp(self):
        from library.models import Edition, Work
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.intake = Path(directory.name)
        shutil.copytree(command.INTAKE / "kshudhita-pashan", self.intake / "kshudhita-pashan")
        self.packet = self.intake / "kshudhita-pashan-en"
        self.packet.mkdir()
        source_sha = command.sha256((self.intake / "kshudhita-pashan" / "source.json").read_bytes())
        (self.packet / "translation.json").write_text(json.dumps({
            "translated_from": "kshudhita-pashan", "method": "ai_edited", "credit": "Edited by Test",
            "model": "claude-test", "date": "2026-11-25", "source_sha256": source_sha}), encoding="utf-8")
        work = Work.objects.create(slug="kshudhita-pashan", title="x", creators=["a"], house="golpo")
        self.source = Edition.objects.create(work=work, slug="kshudhita-pashan", locale="bn")
        self.target = Edition.objects.create(work=work, slug="kshudhita-pashan-en", locale="en")

    def test_translation_packet_import_sets_label_fields(self):
        command.apply_translation(self.target, command.read_translation(self.packet, self.intake))
        self.target.refresh_from_db()
        self.assertEqual(self.target.translated_from, self.source)
        self.assertEqual((self.target.translation_method, self.target.translation_credit, self.target.translation_model),
                         ("ai_edited", "Edited by Test", "claude-test"))

    def test_translation_import_refuses_missing_source_edition(self):
        self.source.delete()
        with self.assertRaises(CommandError) as raised:
            command.read_translation(self.packet, self.intake)
        self.assertIn("SOURCE_EDITION_MISSING", str(raised.exception))

    def test_translation_import_refuses_changed_source_packet(self):
        source = self.intake / "kshudhita-pashan" / "source.json"
        source.write_bytes(source.read_bytes() + b" ")
        with self.assertRaises(CommandError) as raised:
            command.read_translation(self.packet, self.intake)
        self.assertIn("SOURCE_PACKET_HASH_MISMATCH", str(raised.exception))

    def test_same_locale_translation_is_refused(self):
        self.target.locale = "bn"
        self.target.save()
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            command.apply_translation(self.target, command.read_translation(self.packet, self.intake))

    def test_invalid_translation_json_is_refused(self):
        for text in ("{not json", json.dumps({"translated_from": "kshudhita-pashan"})):
            (self.packet / "translation.json").write_text(text, encoding="utf-8")
            with self.assertRaises(CommandError) as raised:
                command.read_translation(self.packet, self.intake)
            self.assertIn("TRANSLATION_JSON_INVALID", str(raised.exception))

    def test_publish_and_evidence_refuse_when_labels_are_absent(self):
        packet = {"slug": "kshudhita-pashan-en", "edition_slug": "kshudhita-pashan-en", "folder": str(self.packet)}
        with mock.patch.object(command, "INTAKE", self.intake):
            for stage in (command.Command().publish, lambda actor, p: command.Command().record_evidence(actor, p, None)):
                with self.assertRaises(CommandError) as raised:
                    stage(None, packet)
                self.assertIn("TRANSLATION_LABELS_MISSING", str(raised.exception))
            command.apply_translation(self.target, command.read_translation(self.packet, self.intake))
            command.require_translation_labels(packet)  # labels present: guard passes

    def test_plain_packet_has_no_translation_fields(self):
        self.assertIsNone(command.read_translation(self.intake / "kshudhita-pashan", self.intake))


EN_TRANSLATION = {"schema": "earnalism.book_source.v1", "language": "en", "units": [{
    "key": "chapter-001", "title": "The Hungry Stones", "kind": "chapter",
    "paragraphs": [{"kind": "paragraph", "text": "My kinsman and myself were returning to Calcutta from our Puja trip."},
                   {"kind": "paragraph", "text": "We met the man in the train."}]}]}


def approve_draft(root, slug):
    draft = root / "docs" / "evidence" / f"publication-clearance-{slug}-draft.json"
    record = json.loads(draft.read_text(encoding="utf-8"))
    record.update(status="OWNER_APPROVED")
    record["approval"].update(approved=True, approved_on="2026-11-25", approved_by="test owner", still_required=[])
    draft.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def give_covers(root, slug):
    """The kshudhita-pashan owner cover pair, copied with its provenance (test only)."""
    for name in ("front.jpg", "back.jpg", "cover_provenance.json"):
        shutil.copy(command.INTAKE / "kshudhita-pashan" / name, root / "library" / "intake" / slug / name)


def make_source_packet(root, slug="golpo-test"):
    """intake_wikisource --write output from the recorded API shape, then approved and given covers."""
    from .test_intake_wikisource import PAGES, TITLE
    api = root / "pages.json"
    api.write_text(json.dumps({"query": {"pages": [
        {"title": f"Book/{page['page']}", "proofread": {"quality": page["quality"]},
         "revisions": [{"revid": page["revision"], "timestamp": page["timestamp"], "slots": {"main": {"content": page["wikitext"]}}}]}
        for page in PAGES]}}, ensure_ascii=False), encoding="utf-8")
    with override_settings(BASE_DIR=root):  # the command queues its clearance draft relative to the repository root
        call_command("intake_wikisource", slug, "--api-json", str(api), "--title", TITLE,
                     "--source-ref", "https://bn.wikisource.org/w/index.php?title=T&oldid=1", "--source-edition", "Test edition, 1895.",
                     "--house", "golpo", "--description", "বিবরণ", "--first-published", "1895", "--author-died", "1941",
                     "--creator", "রবীন্দ্রনাথ ঠাকুর", "--keep-hyphen-after", "১৭৫", "--write", "--root", str(root), stdout=io.StringIO())
    approve_draft(root, slug)
    give_covers(root, slug)


def make_translation_packet(root, slug="kshudhita-pashan-en", source="kshudhita-pashan", approve=True):
    """intake_translation output for an approved source packet, approved and given an owner cover pair."""
    translated = root / "translated.json"
    translated.write_text(json.dumps(EN_TRANSLATION, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with override_settings(BASE_DIR=root):
        call_command("intake_translation", slug, "--from", source, "--source", str(translated),
                     "--method", "ai", "--model", "claude-test", "--title", "The Hungry Stones",
                     "--description", "A tale of a palace.", "--root", str(root), stdout=io.StringIO())
    give_covers(root, slug)
    if approve:
        approve_draft(root, slug)
    return root / "library" / "intake" / slug


class TranslationPacketSharesSourceWorkTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.intake = self.root / "library" / "intake"
        shutil.copytree(command.INTAKE / "kshudhita-pashan", self.intake / "kshudhita-pashan")
        (self.root / CLEARANCE).parent.mkdir(parents=True)
        shutil.copy(command.ROOT / CLEARANCE, self.root / CLEARANCE)

    def test_translation_manifest_copies_the_source_work_block(self):
        folder = make_translation_packet(self.root)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        source = json.loads((self.intake / "kshudhita-pashan" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["work"], source["work"])
        self.assertEqual(manifest["edition"]["slug"], "kshudhita-pashan-en")
        self.assertEqual(manifest["edition"]["title"], "The Hungry Stones")

    def test_packets_are_keyed_by_edition_slug_so_a_translation_is_not_a_duplicate(self):
        make_translation_packet(self.root)
        packets = command.approved_packets(self.intake, root=self.root)
        self.assertEqual(packets["kshudhita-pashan"]["edition_slug"], "kshudhita-pashan")
        self.assertEqual(packets["kshudhita-pashan-en"]["edition_slug"], "kshudhita-pashan-en")
        self.assertEqual(packets["kshudhita-pashan-en"]["book_key"], "kshudhita-pashan-en")
        self.assertEqual(packets["the-selfish-giant"]["book_key"], "the-selfish-giant")
        self.assertEqual(packets["the-selfish-giant"]["edition_slug"], "the-selfish-giant-en")

    def test_clearance_book_is_looked_up_by_edition_slug(self):
        make_translation_packet(self.root)
        draft = self.root / "docs" / "evidence" / "publication-clearance-kshudhita-pashan-en-draft.json"
        record = json.loads(draft.read_text(encoding="utf-8"))
        record["books"] = {"kshudhita-pashan": record["books"]["kshudhita-pashan-en"]}  # keyed by work slug only
        draft.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        self.assertNotIn("kshudhita-pashan-en", command.approved_packets(self.intake, root=self.root))

    def test_import_order_puts_a_source_before_its_translations(self):
        make_translation_packet(self.root)
        packets = command.approved_packets(self.intake, root=self.root)
        order = command.import_order(["kshudhita-pashan-en", "kshudhita-pashan"], packets)
        self.assertEqual(order, ["kshudhita-pashan", "kshudhita-pashan-en"])
        self.assertEqual(command.import_order(["kshudhita-pashan-en"], packets), ["kshudhita-pashan-en"])


class TranslationEndToEndTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        options = override_settings(MEDIA_ROOT=str(self.root / "media"), LOCAL=True)
        options.enable(); self.addCleanup(options.disable)
        self.intake = self.root / "library" / "intake"
        make_source_packet(self.root, "golpo-test")
        make_translation_packet(self.root, "golpo-test-en", source="golpo-test")
        self.publisher = get_user_model().objects.create_user("publisher@example.test", "Test-Only-Passphrase-47", is_verified=True)
        self.publisher.is_staff = True
        self.publisher.save()
        self.publisher.user_permissions.add(Permission.objects.get(codename="publish_revision"))
        for name, value in (("INTAKE", self.intake), ("ROOT", self.root)):
            patcher = mock.patch.object(command, name, value)
            patcher.start(); self.addCleanup(patcher.stop)

    def run_command(self, stage, *extra):
        out = io.StringIO()
        call_command("publish_cleared_editions", stage, "--publisher", str(self.publisher.public_id),
                     "--book", "golpo-test-en", "--book", "golpo-test", *extra, stdout=out)
        return json.loads(out.getvalue().split("MAISON_OUT ", 1)[1])

    def test_source_and_translation_import_publish_and_pair_on_the_title_page(self):
        from library.models import Edition
        imported = self.run_command("import")
        self.assertEqual(list(imported), ["golpo-test", "golpo-test-en"])  # source first, whatever order was asked
        report = self.root / "browser.json"
        report.write_text(json.dumps({"scope": "test_replica", "books": {
            slug: {"status": "pass", "sha256": imported[slug]["sha256"]} for slug in imported}}), encoding="utf-8")
        self.run_command("evidence", "--browser-report", str(report))
        published = self.run_command("publish")
        self.assertEqual({slug: value["state"] for slug, value in published.items()},
                         {"golpo-test": "live", "golpo-test-en": "live"})
        source, translation = Edition.objects.get(slug="golpo-test"), Edition.objects.get(slug="golpo-test-en")
        self.assertEqual(source.work_id, translation.work_id)
        self.assertEqual(translation.translated_from_id, source.pk)
        html = self.client.get(f"/en/titles/{source.pk}/").content.decode()
        self.assertIn(f'href="/en/titles/{translation.pk}/"', html)


class PreviewPrefixTests(SimpleTestCase):
    """Task 16b: a first paragraph longer than the 1,200 codepoint budget previews an exact sentence prefix."""

    @staticmethod
    def paragraphs(*texts):
        import uuid
        from types import SimpleNamespace
        return [SimpleNamespace(text=t, anchor_id=uuid.uuid4()) for t in texts]

    def real_paragraphs(self):
        source = json.loads((command.INTAKE / "kshudhita-pashan" / "source.json").read_text(encoding="utf-8"))
        return self.paragraphs(*[p["text"] for p in source["units"][0]["paragraphs"] if p["kind"] == "paragraph"])

    def test_long_opening_paragraph_previews_exact_sentence_prefix(self):
        paragraphs = self.real_paragraphs()
        self.assertGreater(len(paragraphs[0].text), 1200)
        preview = command.preview_entries(paragraphs)
        self.assertEqual(len(preview), 1)
        text = preview[0]["text"]
        self.assertTrue(paragraphs[0].text.startswith(text))
        self.assertLessEqual(len(text), 1200)
        self.assertEqual(text[-1], "।")
        self.assertEqual(preview[0]["anchor_id"], str(paragraphs[0].anchor_id))
        self.assertEqual(len(text), 1084)  # the danda at index 1083; the next sentence end (1311) no longer fits

    def test_preview_unchanged_for_short_paragraphs(self):
        paragraphs = self.paragraphs("a" * 500, "b" * 400, "c" * 400, "d" * 10)
        preview = command.preview_entries(paragraphs)
        self.assertEqual([p["text"] for p in preview], ["a" * 500, "b" * 400])
        self.assertEqual(preview[0]["anchor_id"], str(paragraphs[0].anchor_id))

    def test_no_sentence_end_within_budget_is_refused(self):
        self.assertEqual(command.preview_entries(self.paragraphs("x" * 1300 + "।")), [])
        self.assertEqual(command.preview_entries(self.paragraphs("x" * 1198 + ".y" + "।")), [])  # "." not before a space

    def test_period_counts_only_before_space_or_end(self):
        text = "Hello world. " + "y" * 1300
        self.assertEqual(command.preview_entries(self.paragraphs(text))[0]["text"], "Hello world.")

    def test_get_preview_document_serves_the_first_chapter_once_a_preview_is_offered(self):
        # Owner decision 26 Nov 2026: the stored preview entries only mark that a reader preview is offered;
        # readers see the first chapter's whole paragraphs up to the one that reaches PREVIEW_WORD_LIMIT words.
        import uuid
        from types import SimpleNamespace
        from library import services as svc
        paragraphs = self.real_paragraphs()
        rows = [SimpleNamespace(anchor_id=p.anchor_id, text=p.text, kind="paragraph", ordinal=i) for i, p in enumerate(paragraphs, 1)]
        unit = SimpleNamespace(id=uuid.uuid4(), paragraphs=mock.MagicMock())
        unit.paragraphs.all.return_value = rows
        revision = mock.MagicMock(preview=command.preview_entries(paragraphs))
        revision.units.first.return_value = unit
        with mock.patch.object(svc, "edition_detail", return_value={"edition_revision_id": "r"}), \
                mock.patch.object(svc, "_revision", return_value=revision), \
                mock.patch.object(svc, "current_right", return_value=object()), \
                mock.patch.object(svc, "unit_dto", return_value={}):
            document = svc.get_preview_document("e", unit.id)
        shown = document["paragraphs"]
        self.assertEqual(shown[0]["text"], rows[0].text)  # the long opening paragraph is now whole
        self.assertEqual([p["anchor_id"] for p in shown], [str(r.anchor_id) for r in rows[:len(shown)]])
        counted = [svc.preview_word_count(p["text"]) for p in shown]
        self.assertTrue(sum(counted) >= svc.PREVIEW_WORD_LIMIT or len(shown) == len(rows))
        self.assertLess(sum(counted[:-1]), svc.PREVIEW_WORD_LIMIT)
        self.assertEqual(document["boundary"]["end_offset_chars"], len(shown[-1]["text"]))
        self.assertEqual(document["boundary"]["end_anchor_id"], shown[-1]["anchor_id"])
