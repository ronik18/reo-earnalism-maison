"""Audiovisual source export and owner-cleared audio attachment keep every publication gate."""
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import AuditEvent
from library.models import Asset, Edition, Revision, TimingMap
from library.services import prepare_revision_validation, revision_hash, validate_revision

EVIDENCE_DIR = Path(settings.BASE_DIR) / "docs" / "evidence"


class AudiovisualCommandTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        (self.tmp / "media").mkdir()
        options = override_settings(MEDIA_ROOT=str(self.tmp / "media"), LOCAL=True)
        options.enable(); self.addCleanup(options.disable)
        self.publisher = get_user_model().objects.create_user("publisher@example.test", "Test-Only-Passphrase-47", is_verified=True)
        self.publisher.is_staff = True
        self.publisher.save()
        self.publisher.user_permissions.add(Permission.objects.get(codename="publish_revision"))

    # --- seed: the real cleared bicharak edition, published through the existing command ---------
    def publish_stage(self, stage, *extra):
        out = io.StringIO()
        call_command("publish_cleared_editions", stage, "--publisher", str(self.publisher.public_id), "--book", "bicharak",
                     *extra, stdout=out)
        return json.loads(out.getvalue().split("MAISON_OUT ", 1)[1])["bicharak"]

    def publish_bicharak(self):
        imported = self.publish_stage("import")
        report = self.tmp / "browser.json"
        report.write_text(json.dumps({"scope": "test_replica", "books": {"bicharak": {"status": "pass", "sha256": imported["sha256"]}}}))
        self.publish_stage("evidence", "--browser-report", str(report))
        self.publish_stage("publish")
        return Edition.objects.get(slug="bicharak").live_revision

    def export(self):
        out = self.tmp / "source.json"
        call_command("export_audiovisual_source", "bicharak", "--out", str(out), stdout=io.StringIO())
        return json.loads(out.read_text())

    def bundle(self, source, extra_files=()):
        folder = self.tmp / "bundle"
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir()
        mp3 = folder / "unit-01.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-ac", "1",
                        "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "96k", str(mp3)], check=True)
        unit = source["units"][0]
        count = len(unit["paragraphs"])
        step = 2000 // count
        segments = [{"anchor_id": p["anchor_id"], "start_offset_chars": 0, "end_offset_chars": len(p["text"]),
                     "start_ms": i * step, "end_ms": (i + 1) * step} for i, p in enumerate(unit["paragraphs"])]
        (folder / "timing.json").write_text(json.dumps({"units": [{"unit_id": unit["unit_id"], "mp3": mp3.name, "segments": segments}]}))
        for name in extra_files:
            (folder / name).write_bytes(b"\x00\x00\x00\x18ftypmp42 synthetic test video")
        return folder, hashlib.sha256(mp3.read_bytes()).hexdigest()

    def evidence(self, source, audio_sha):
        name = "audiovisual-clearance-test-only-" + self.id().rsplit(".", 1)[-1] + ".json"
        path = EVIDENCE_DIR / name
        path.write_text(json.dumps({"schema": "earnalism.audiovisual-clearance-evidence.v1", "edition_slug": "bicharak",
            "source_content_sha256": source["content_sha256"], "territories": list(settings.MAISON_PUBLICATION_TERRITORIES),
            "formats": ["reader", "audio"], "audio_sha256": [audio_sha], "basis": "synthetic isolated test only"}))
        self.addCleanup(path.unlink, missing_ok=True)
        return "docs/evidence/" + name

    def attach(self, *args):
        out = io.StringIO()
        call_command("attach_audiovisual_audio", *args, stdout=out)
        return json.loads(out.getvalue().split("MAISON_OUT ", 1)[1])

    def stage(self, folder, evidence):
        return self.attach("stage", "bicharak", "--publisher", str(self.publisher.public_id),
                           "--bundle", str(folder), "--evidence", evidence)

    def browser(self, sha, checks=None, status="pass", tag="ok"):
        name = f"audiovisual-browser-test-only-{self.id().rsplit('.', 1)[-1]}-{tag}.json"
        path = EVIDENCE_DIR / name
        path.write_text(json.dumps({"sha256": sha, "status": status, "scope": "test_replica",
                                    "checks": {"audio_playback": True} if checks is None else checks}))
        self.addCleanup(path.unlink, missing_ok=True)
        return "docs/evidence/" + name

    def publish(self, report):
        return self.attach("publish", "bicharak", "--publisher", str(self.publisher.public_id), "--browser-report", report)

    def staged(self):
        old = self.publish_bicharak()
        source = self.export()
        folder, audio_sha = self.bundle(source)
        evidence = self.evidence(source, audio_sha)
        return old, folder, audio_sha, evidence, self.stage(folder, evidence)

    # --- export -----------------------------------------------------------------------------------
    def test_export_refuses_without_live_revision(self):
        self.publish_stage("import")
        with self.assertRaisesMessage(CommandError, "no live revision"):
            self.export()

    def test_export_shape_and_hash(self):
        live = self.publish_bicharak()
        source = self.export()
        self.assertEqual(source["content_sha256"], revision_hash(live))
        self.assertEqual((source["edition_id"], source["revision_id"]), (str(live.edition_id), str(live.id)))
        self.assertEqual(source["language"], "bn")
        self.assertTrue(source["public_domain_evidence"])
        self.assertEqual(source["rights"], {"reader": ["preview", "read"]})
        unit = live.units.get()
        self.assertEqual([u["unit_id"] for u in source["units"]], [str(unit.id)])
        self.assertEqual(source["units"][0]["title"], unit.title)
        self.assertEqual(source["units"][0]["paragraphs"],
                         [{"anchor_id": str(p.anchor_id), "kind": p.kind, "text": p.text} for p in unit.paragraphs.order_by("ordinal")])

    def test_export_revision_round_trips_staged_draft_ids(self):
        _, _, audio_sha, _, staged = self.staged()
        draft = Revision.objects.get(pk=staged["revision_id"])
        out = self.tmp / "draft.json"
        call_command("export_audiovisual_source", "bicharak", "--revision", str(draft.id), "--out", str(out), stdout=io.StringIO())
        source = json.loads(out.read_text())
        self.assertEqual((source["revision_id"], source["state"], source["content_sha256"]), (str(draft.id), "draft", draft.content_sha256))
        unit = draft.units.get()
        self.assertEqual(source["units"][0]["unit_id"], str(unit.id))
        self.assertEqual([p["anchor_id"] for p in source["units"][0]["paragraphs"]],
                         [str(p.anchor_id) for p in unit.paragraphs.order_by("ordinal")])
        asset = draft.assets.get(kind="audio_chapter")
        self.assertIn({"asset_id": str(asset.id), "kind": "audio_chapter", "unit_id": str(unit.id), "sha256": audio_sha,
                       "bytes": asset.bytes, "content_type": "audio/mpeg", "duration_ms": asset.duration_ms}, source["assets"])
        mapping = TimingMap.objects.get(asset=asset)
        self.assertEqual(source["timing_maps"], [{"map_id": str(mapping.id), "asset_id": str(asset.id), "asset_sha256": audio_sha,
            "text_sha256": draft.content_sha256, "precision": "paragraph", "segments": mapping.segments}])
        self.assertEqual(source["rights"], {"audio": ["read"], "reader": ["preview", "read"]})

    # --- attach: stage ------------------------------------------------------------------------------
    def test_stage_leaves_a_cleared_draft_and_does_not_publish(self):
        old, _, audio_sha, _, staged = self.staged()
        self.assertEqual(staged["status"], "staged")
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, old.id)
        draft = Revision.objects.get(pk=staged["revision_id"])
        self.assertEqual((draft.state, staged["content_sha256"]), ("draft", draft.content_sha256))
        self.assertNotIn("browser", draft.validation_evidence)
        self.assertEqual(staged["asset_sha256"], {str(a.id): a.sha256 for a in draft.assets.filter(state="ready")})
        self.assertEqual(draft.access_policy["audio"], "free")
        asset = Asset.objects.get(revision=draft, kind="audio_chapter")
        self.assertEqual((asset.sha256, asset.provider, asset.state, asset.unit.ordinal), (audio_sha, "r2", "ready", 1))
        mapping = TimingMap.objects.get(revision=draft, asset=asset)
        self.assertEqual((mapping.text_sha256, mapping.asset_sha256, mapping.measured), (draft.content_sha256, audio_sha, True))
        clearance = draft.validation_evidence["publication_clearance"]
        self.assertEqual((clearance["formats"], clearance["asset_sha256"]), (["reader", "audio"], staged["asset_sha256"]))
        checks = {c["code"]: c["status"] for c in validate_revision(draft, prepared=prepare_revision_validation(draft.id))["checks"]}
        self.assertEqual({k for k, v in checks.items() if v == "fail"}, {"browser"})
        self.assertTrue(AuditEvent.objects.filter(actor=self.publisher, action="asset.complete", entity_id=str(asset.id),
                                                  detail__channel="server_job").exists())

    def test_stage_rerun_is_idempotent(self):
        _, folder, _, evidence, staged = self.staged()
        revisions, assets, maps = Revision.objects.count(), Asset.objects.count(), TimingMap.objects.count()
        again = self.stage(folder, evidence)
        self.assertEqual((again["status"], again["revision_id"], again["content_sha256"], again["asset_sha256"]),
                         ("staged", staged["revision_id"], staged["content_sha256"], staged["asset_sha256"]))
        self.assertEqual((Revision.objects.count(), Asset.objects.count(), TimingMap.objects.count()), (revisions, assets, maps))

    # --- attach: publish ----------------------------------------------------------------------------
    def assert_unchanged(self, old, staged):
        draft = Revision.objects.get(pk=staged["revision_id"])
        self.assertEqual(draft.state, "draft")
        self.assertNotIn("browser", draft.validation_evidence)
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, old.id)

    def test_publish_refuses_report_for_another_hash(self):
        old, _, _, _, staged = self.staged()
        with self.assertRaisesMessage(CommandError, "browser report"):
            self.publish(self.browser(old.content_sha256))
        with self.assertRaisesMessage(CommandError, "browser report"):
            self.publish(self.browser(staged["content_sha256"], status="fail", tag="fail"))
        self.assert_unchanged(old, staged)

    def test_publish_refuses_report_without_audio_scope(self):
        old, _, _, _, staged = self.staged()
        with self.assertRaisesMessage(CommandError, "audio"):
            self.publish(self.browser(staged["content_sha256"], checks={"reader": True}))
        with self.assertRaisesMessage(CommandError, "browser report"):
            self.publish("docs/evidence/audiovisual-browser-missing-test-only.json")
        self.assert_unchanged(old, staged)

    def test_publish_with_matching_report_goes_live_with_audio(self):
        old, folder, audio_sha, evidence, staged = self.staged()
        result = self.publish(self.browser(staged["content_sha256"]))
        live = Edition.objects.get(slug="bicharak").live_revision
        self.assertEqual((result["status"], result["revision_id"], str(live.id), live.state), ("published", staged["revision_id"], staged["revision_id"], "live"))
        self.assertEqual(Revision.objects.get(pk=old.id).state, "retired")
        self.assertEqual(live.validation_evidence["browser"]["checks"], {"audio_playback": True})
        self.assertEqual(Asset.objects.get(revision=live, kind="audio_chapter").sha256, audio_sha)
        report = validate_revision(live, prepared=prepare_revision_validation(live.id))
        checks = {c["code"]: c["status"] for c in report["checks"]}
        self.assertEqual(report["status"], "pass", checks)
        self.assertEqual((checks["timing_map"], checks["publication_regions"], checks["publication_clearance"], checks["browser"]),
                         ("pass", "pass", "pass", "pass"))
        self.assertEqual(set(live.rights.filter(format="audio", approved=True, test_only=False).values_list("action", flat=True)), {"read"})
        self.assertTrue(AuditEvent.objects.filter(actor=self.publisher, action="revision.publish", entity_id=str(live.id),
                                                  detail__channel="server_job").exists())
        # Reruns report the live audio and create nothing new.
        revisions, assets = Revision.objects.count(), Asset.objects.count()
        self.assertEqual(self.stage(folder, evidence)["status"], "already_live")
        self.assertEqual(self.publish(self.browser(staged["content_sha256"], tag="again"))["status"], "already_live")
        self.assertEqual((Revision.objects.count(), Asset.objects.count()), (revisions, assets))

    def test_attach_refuses_video_files(self):
        live = self.publish_bicharak()
        source = self.export()
        folder, audio_sha = self.bundle(source, extra_files=("film.mp4",))
        with self.assertRaisesMessage(CommandError, "Stream hosting held"):
            self.stage(folder, self.evidence(source, audio_sha))
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, live.id)
        self.assertEqual(Revision.objects.filter(edition=live.edition).count(), 1)

    def test_attach_refuses_incomplete_timing_before_any_mutation(self):
        live = self.publish_bicharak()
        source = self.export()
        folder, audio_sha = self.bundle(source)
        timing = json.loads((folder / "timing.json").read_text())
        timing["units"][0]["segments"].pop()
        (folder / "timing.json").write_text(json.dumps(timing))
        with self.assertRaisesMessage(CommandError, "timing.json unit 1"):
            self.stage(folder, self.evidence(source, audio_sha))
        self.assertEqual(Revision.objects.filter(edition=live.edition).count(), 1)

    def test_attach_refuses_without_evidence_file(self):
        live = self.publish_bicharak()
        source = self.export()
        folder, _ = self.bundle(source)
        with self.assertRaisesMessage(CommandError, "evidence"):
            self.stage(folder, "docs/evidence/audiovisual-clearance-missing-test-only.json")
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, live.id)
        self.assertEqual(Revision.objects.filter(edition=live.edition).count(), 1)
