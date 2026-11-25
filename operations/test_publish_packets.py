"""Owner-approved intake packets are discovered for publication; unapproved or altered ones never are."""
import json
import shutil
import tempfile
from pathlib import Path

from django.core.management.base import CommandError
from django.test import SimpleTestCase

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
