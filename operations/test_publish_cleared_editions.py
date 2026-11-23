"""Server-side publication of the owner-cleared editions keeps every publication gate."""
import io
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import AuditEvent
from library.models import Edition, Rights


class PublishClearedEditionsTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        options = override_settings(MEDIA_ROOT=directory.name, LOCAL=True)
        options.enable(); self.addCleanup(options.disable)
        self.publisher = get_user_model().objects.create_user("publisher@example.test", "Test-Only-Passphrase-47", is_verified=True)
        self.publisher.is_staff = True
        self.publisher.save()
        self.publisher.user_permissions.add(Permission.objects.get(codename="publish_revision"))

    def run_stage(self, stage, *extra):
        out = io.StringIO()
        call_command("publish_cleared_editions", stage, "--publisher", str(self.publisher.public_id), "--book", "bicharak",
                     *extra, stdout=out)
        return json.loads(out.getvalue().split("MAISON_OUT ", 1)[1])["bicharak"]

    def browser_report(self, sha, status="pass"):
        path = self.tmp / "browser.json"
        path.write_text(json.dumps({"scope": "test_replica", "books": {"bicharak": {"status": status, "sha256": sha}}}))
        return str(path)

    def test_import_evidence_and_publish_without_a_web_session(self):
        imported = self.run_stage("import")
        self.assertEqual((imported["state"], imported["paragraphs"]), ("draft", 39))
        self.assertEqual(imported["checks"]["publication_clearance"], "fail")
        self.assertEqual(imported["checks"]["browser"], "fail")
        rights = Rights.objects.filter(revision_id=imported["revision_id"])
        self.assertEqual({(r.action, r.approved, r.test_only) for r in rights}, {("read", True, False), ("preview", True, False)})

        with self.assertRaises(Exception):  # gates still hold: nothing publishes before evidence
            self.run_stage("publish")
        self.assertIsNone(Edition.objects.get(slug="bicharak").live_revision_id)

        recorded = self.run_stage("evidence", "--browser-report", self.browser_report(imported["sha256"]))
        self.assertTrue(all(v in {"pass", "not_applicable"} for v in recorded["checks"].values()), recorded["checks"])

        published = self.run_stage("publish")
        self.assertEqual([s["action"] for s in published["steps"]], ["mark-ready", "publish"])
        self.assertEqual(published["state"], "live")
        self.assertEqual(str(Edition.objects.get(slug="bicharak").live_revision_id), imported["revision_id"])
        self.assertTrue(AuditEvent.objects.filter(actor=self.publisher, action="revision.publish").exists())
        self.assertEqual(self.run_stage("import")["state"], "live")  # rerun is a no-op, never a second import

    def test_browser_report_for_another_text_is_rejected(self):
        self.run_stage("import")
        with self.assertRaises(CommandError):
            self.run_stage("evidence", "--browser-report", self.browser_report("0" * 64))
        with self.assertRaises(CommandError):
            self.run_stage("evidence", "--browser-report", self.browser_report("x", status="fail"))

    def test_only_a_verified_staff_publisher_may_run_it(self):
        member = get_user_model().objects.create_user("member@example.test", "Test-Only-Passphrase-47", is_verified=True)
        with self.assertRaises(CommandError):
            call_command("publish_cleared_editions", "status", "--publisher", str(member.public_id), stdout=io.StringIO())
