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
from django.test import SimpleTestCase, TestCase

from operations.management.commands import publish_cleared_editions as command

CLEARANCE = "docs/evidence/publication-clearance-kshudhita-pashan.json"


class PublishPacketDiscoveryTests(SimpleTestCase):
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
        with self.assertRaises(Exception):
            command.apply_translation(self.target, command.read_translation(self.packet, self.intake))

    def test_plain_packet_has_no_translation_fields(self):
        self.assertIsNone(command.read_translation(self.intake / "kshudhita-pashan", self.intake))
