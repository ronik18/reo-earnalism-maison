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


class AudiovisualFixture(TestCase):
    """Shared seed: the real cleared bicharak edition, an audio bundle and synthetic evidence."""

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

    APPROVAL = {"by": "owner (synthetic test only)", "at": "2026-11-23T10:00:00+05:30"}

    def evidence(self, source, audio_sha, tag="ok", **override):
        name = f"audiovisual-clearance-test-only-{self.id().rsplit('.', 1)[-1]}-{tag}.json"
        path = EVIDENCE_DIR / name
        doc = {"schema": "earnalism.audiovisual-clearance-evidence.v1", "edition_slug": "bicharak",
            "source_content_sha256": source["content_sha256"], "territories": list(settings.MAISON_PUBLICATION_TERRITORIES),
            "formats": ["reader", "audio"], "audio_sha256": [audio_sha], "basis": "synthetic isolated test only",
            "status": "OWNER_APPROVED", "owner_approval": dict(self.APPROVAL), **self.complete_record()}
        doc.update(override)
        path.write_text(json.dumps(doc))
        self.addCleanup(path.unlink, missing_ok=True)
        return "docs/evidence/" + name

    @staticmethod
    def complete_record():
        """The per-title fields the owner completes (spec owner answer 4); synthetic test values."""
        return {"term_per_territory": {t: "synthetic test only: public domain" for t in settings.MAISON_PUBLICATION_TERRITORIES},
                "text_source_licence": "synthetic test only", "cover_provenance": "synthetic test only",
                "dry_narration": False,
                "music": {"route": "vcsl", "licence": "CC0-1.0", "source_and_licence": "synthetic test only: VCSL CC0"}}

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


class AudiovisualCommandTests(AudiovisualFixture):
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

    def test_attach_refuses_evidence_without_owner_approval(self):
        """R12: owner approval is enforced in code; a draft or unapproved record changes nothing."""
        live = self.publish_bicharak()
        source = self.export()
        folder, audio_sha = self.bundle(source)
        cases = [("draft", {"status": "DRAFT_NOT_APPROVED: complete it"}, "draft"),
                 ("null", {"owner_approval": None}, "owner_approval"),
                 ("missing", {"owner_approval": "yes"}, "owner_approval"),
                 ("nowho", {"owner_approval": {"at": "2026-11-23T10:00:00+05:30"}}, "owner_approval"),
                 ("nowhen", {"owner_approval": {"by": "owner"}}, "owner_approval"),
                 ("blank", {"owner_approval": {"by": " ", "at": ""}}, "owner_approval")]
        for tag, override, message in cases:
            with self.subTest(tag), self.assertRaisesMessage(CommandError, message):
                self.stage(folder, self.evidence(source, audio_sha, tag=tag, **override))
        unapproved = self.evidence(source, audio_sha, tag="dropped")
        path = EVIDENCE_DIR / unapproved.rsplit("/", 1)[1]
        doc = json.loads(path.read_text())
        del doc["owner_approval"]
        path.write_text(json.dumps(doc))
        with self.assertRaisesMessage(CommandError, "owner_approval"):
            self.stage(folder, unapproved)
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, live.id)
        self.assertEqual(Revision.objects.filter(edition=live.edition).count(), 1)

    def test_attach_refuses_incomplete_clearance_record(self):
        """R24: term per territory, text-source licence, cover provenance and music licence are all required."""
        live = self.publish_bicharak()
        source = self.export()
        folder, audio_sha = self.bundle(source)
        first = list(settings.MAISON_PUBLICATION_TERRITORIES)[0]
        partial_terms = {t: "public domain" for t in list(settings.MAISON_PUBLICATION_TERRITORIES)[1:]}
        cases = [("noterms", {"term_per_territory": {}}, "term_per_territory"),
                 ("oneterm", {"term_per_territory": partial_terms}, first),
                 ("blankterm", {"term_per_territory": {**partial_terms, first: " "}}, first),
                 ("termlist", {"term_per_territory": ["public domain"]}, "term_per_territory"),
                 ("notext", {"text_source_licence": None}, "text_source_licence"),
                 ("blanktext", {"text_source_licence": ""}, "text_source_licence"),
                 ("nocover", {"cover_provenance": None}, "cover_provenance"),
                 ("nomusic", {"music": None}, "music"),
                 ("nomusiclicence", {"music": {"route": "vcsl", "licence": "CC0-1.0", "source_and_licence": None}}, "music"),
                 ("noroute", {"music": {"licence": "CC0-1.0", "source_and_licence": "VCSL"}}, "music"),
                 ("nodryflag", {"dry_narration": None, "music": None}, "music")]
        for tag, override, message in cases:
            with self.subTest(tag), self.assertRaisesMessage(CommandError, message):
                self.stage(folder, self.evidence(source, audio_sha, tag=tag, **override))
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, live.id)
        self.assertEqual(Revision.objects.filter(edition=live.edition).count(), 1)

    def test_attach_accepts_dry_narration_without_music(self):
        old = self.publish_bicharak()
        source = self.export()
        folder, audio_sha = self.bundle(source)
        staged = self.stage(folder, self.evidence(source, audio_sha, tag="dry", dry_narration=True, music=None))
        self.assertEqual(staged["status"], "staged")
        self.assertNotEqual(staged["revision_id"], str(old.id))

    def with_provenance(self, folder, score_sha):
        """Add eav's per-unit provenance to timing.json (score_sha None = narration only)."""
        timing = json.loads((folder / "timing.json").read_text())
        unit_id = timing["units"][0]["unit_id"]
        timing["provenance"] = {"method": "eav.film.narration_track", "units": {unit_id: {
            "mastered_with": "eav.mix.duck_and_master" if score_sha else "eav.mix.master",
            "score_sha256": score_sha}}}
        (folder / "timing.json").write_text(json.dumps(timing))

    def test_attach_refuses_dry_claim_when_the_bundle_mixed_a_score(self):
        """R27 (minor 2): dry_narration true must match the bundle's per-unit score provenance."""
        live = self.publish_bicharak()
        source = self.export()
        folder, audio_sha = self.bundle(source)
        self.with_provenance(folder, "b" * 64)
        with self.assertRaisesMessage(CommandError, "dry_narration"):
            self.stage(folder, self.evidence(source, audio_sha, tag="drymixed", dry_narration=True, music=None))
        self.assertEqual(Revision.objects.filter(edition=live.edition).count(), 1)
        self.with_provenance(folder, None)
        staged = self.stage(folder, self.evidence(source, audio_sha, tag="dryok", dry_narration=True, music=None))
        self.assertEqual(staged["status"], "staged")

    def test_attach_refuses_without_evidence_file(self):
        live = self.publish_bicharak()
        source = self.export()
        folder, _ = self.bundle(source)
        with self.assertRaisesMessage(CommandError, "evidence"):
            self.stage(folder, "docs/evidence/audiovisual-clearance-missing-test-only.json")
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, live.id)
        self.assertEqual(Revision.objects.filter(edition=live.edition).count(), 1)


class FilmCommandTests(AudiovisualFixture):
    """attach_audiovisual_film: a faststart H.264/AAC film plus captions on private R2, same gates as audio."""

    def film_bundle(self, unit_id, *, faststart=True, video_codec="libx264", vtt=b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n",
                    folder_name="film-bundle", **override):
        folder = self.tmp / folder_name
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir()
        mp4 = folder / "film.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1:r=10",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", video_codec, "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", *(["-movflags", "+faststart"] if faststart else []), str(mp4)], check=True)
        (folder / "film.vtt").write_bytes(vtt)
        unit = {"unit_id": unit_id, "mp4": "film.mp4", "vtt": "film.vtt",
                "mp4_sha256": hashlib.sha256(mp4.read_bytes()).hexdigest(),
                "vtt_sha256": hashlib.sha256(vtt).hexdigest(),
                "duration_ms": 987654, "bytes": mp4.stat().st_size}  # a wrong duration claim: the command measures
        unit.update(override)
        (folder / "film.json").write_text(json.dumps({"schema": "earnalism.audiovisual-film-bundle.v1", "units": [unit]}))
        return folder, unit

    def film_evidence(self, source, video_shas, tag="film", **override):
        return self.evidence(source, None, tag=tag, **{"formats": ["reader", "video"], "video_sha256": list(video_shas),
                                                       "audio_sha256": None, **override})

    def film(self, *args):
        out = io.StringIO()
        call_command("attach_audiovisual_film", *args, stdout=out)
        return json.loads(out.getvalue().split("MAISON_OUT ", 1)[1])

    def stage_film(self, folder, evidence):
        return self.film("stage", "bicharak", "--publisher", str(self.publisher.public_id),
                         "--bundle", str(folder), "--evidence", evidence)

    def publish_film(self, report):
        return self.film("publish", "bicharak", "--publisher", str(self.publisher.public_id), "--browser-report", report)

    def staged_film(self):
        old = self.publish_bicharak()
        source = self.export()
        folder, unit = self.film_bundle(source["units"][0]["unit_id"])
        evidence = self.film_evidence(source, [unit["mp4_sha256"]])
        return old, source, folder, unit, evidence, self.stage_film(folder, evidence)

    def assert_nothing_staged(self, live):
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, live.id)
        self.assertEqual(Revision.objects.filter(edition=live.edition).count(), 1)
        self.assertFalse(Asset.objects.filter(kind__in=["video", "video_captions"]).exists())

    # --- stage --------------------------------------------------------------------------------------
    def test_stage_creates_r2_video_and_captions_on_draft(self):
        old, source, _, unit, _, staged = self.staged_film()
        self.assertEqual(staged["status"], "staged")
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, old.id)
        draft = Revision.objects.get(pk=staged["revision_id"])
        self.assertEqual((draft.state, staged["content_sha256"]), ("draft", draft.content_sha256))
        self.assertNotIn("browser", draft.validation_evidence)
        video = Asset.objects.get(revision=draft, kind="video")
        self.assertEqual((video.provider, video.state, video.content_type, video.sha256, video.bytes, video.unit.ordinal),
                         ("r2", "ready", "video/mp4", unit["mp4_sha256"], unit["bytes"], 1))
        self.assertTrue(900 <= video.duration_ms <= 1200, video.duration_ms)  # ffprobe-measured, not the bundle's 987654
        captions = Asset.objects.get(revision=draft, kind="video_captions")
        self.assertEqual((captions.provider, captions.state, captions.content_type, captions.sha256, captions.unit_id),
                         ("r2", "ready", "text/vtt", unit["vtt_sha256"], video.unit_id))
        self.assertEqual(draft.access_policy["video"], "free")
        self.assertEqual(staged["asset_sha256"], {str(a.id): a.sha256 for a in draft.assets.filter(state="ready")})
        clearance = draft.validation_evidence["publication_clearance"]
        self.assertEqual((clearance["formats"], clearance["asset_sha256"]), (["reader", "video"], staged["asset_sha256"]))
        self.assertTrue(draft.rights.filter(format="video", action="read", approved=True, test_only=False).exists())
        proof = draft.validation_evidence["media_assets"][str(video.id)]
        self.assertEqual((proof["sha256"], proof["duration_ms"], proof["faststart"]), (video.sha256, video.duration_ms, True))
        checks = {c["code"]: c["status"] for c in validate_revision(draft, prepared=prepare_revision_validation(draft.id))["checks"]}
        self.assertEqual({k for k, v in checks.items() if v == "fail"}, {"browser"}, checks)
        self.assertTrue(AuditEvent.objects.filter(actor=self.publisher, action="asset.complete", entity_id=str(video.id),
                                                  detail__channel="server_job").exists())

    def test_stage_refuses_non_faststart(self):
        live = self.publish_bicharak()
        source = self.export()
        folder, unit = self.film_bundle(source["units"][0]["unit_id"], faststart=False)
        with self.assertRaisesMessage(CommandError, "faststart"):
            self.stage_film(folder, self.film_evidence(source, [unit["mp4_sha256"]]))
        self.assert_nothing_staged(live)

    def test_stage_refuses_hash_mismatch(self):
        live = self.publish_bicharak()
        source = self.export()
        unit_id = source["units"][0]["unit_id"]
        folder, unit = self.film_bundle(unit_id, mp4_sha256="a" * 64)
        with self.subTest("bundle mp4"), self.assertRaisesMessage(CommandError, "mp4_sha256"):
            self.stage_film(folder, self.film_evidence(source, ["a" * 64], tag="mp4"))
        folder, unit = self.film_bundle(unit_id, vtt_sha256="b" * 64)
        with self.subTest("bundle vtt"), self.assertRaisesMessage(CommandError, "vtt_sha256"):
            self.stage_film(folder, self.film_evidence(source, [unit["mp4_sha256"]], tag="vtt"))
        folder, unit = self.film_bundle(unit_id)
        with self.subTest("evidence"), self.assertRaisesMessage(CommandError, "video_sha256"):
            self.stage_film(folder, self.film_evidence(source, ["c" * 64], tag="evidence"))
        self.assert_nothing_staged(live)

    def test_stage_refuses_evidence_without_video_format(self):
        live = self.publish_bicharak()
        source = self.export()
        folder, unit = self.film_bundle(source["units"][0]["unit_id"])
        with self.assertRaisesMessage(CommandError, "video"):
            self.stage_film(folder, self.film_evidence(source, [unit["mp4_sha256"]], formats=["reader", "audio"]))
        self.assert_nothing_staged(live)

    def test_stage_refuses_bad_media(self):
        live = self.publish_bicharak()
        source = self.export()
        unit_id = source["units"][0]["unit_id"]
        cases = [("codec", {"video_codec": "mpeg4"}, "H.264"),
                 ("vtt", {"vtt": b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"}, "WEBVTT"),
                 ("bytes", {"bytes": 1}, "bytes")]
        for tag, kwargs, message in cases:
            folder, unit = self.film_bundle(unit_id, **kwargs)
            with self.subTest(tag), self.assertRaisesMessage(CommandError, message):
                self.stage_film(folder, self.film_evidence(source, [unit["mp4_sha256"]], tag=tag))
        folder, unit = self.film_bundle(unit_id)
        (folder / "notes.txt").write_text("not part of the bundle")
        with self.assertRaisesMessage(CommandError, "notes.txt"):
            self.stage_film(folder, self.film_evidence(source, [unit["mp4_sha256"]], tag="extra"))
        self.assert_nothing_staged(live)

    def test_stage_rerun_is_idempotent(self):
        _, _, folder, _, evidence, staged = self.staged_film()
        revisions, assets, rights = Revision.objects.count(), Asset.objects.count(), self.count_rights()
        again = self.stage_film(folder, evidence)
        self.assertEqual((again["status"], again["revision_id"], again["content_sha256"], again["asset_sha256"]),
                         ("staged", staged["revision_id"], staged["content_sha256"], staged["asset_sha256"]))
        self.assertEqual((Revision.objects.count(), Asset.objects.count(), self.count_rights()), (revisions, assets, rights))

    @staticmethod
    def count_rights():
        from library.models import Rights
        return Rights.objects.count()

    # --- publish ------------------------------------------------------------------------------------
    def film_browser(self, sha, checks=None, tag="film"):
        return self.browser(sha, checks={"video_playback": True} if checks is None else checks, tag=tag)

    def test_publish_refuses_without_browser_report(self):
        old, _, _, _, _, staged = self.staged_film()
        cases = [("missing", "docs/evidence/audiovisual-browser-missing-test-only.json", "browser report"),
                 ("otherhash", self.film_browser(old.content_sha256, tag="otherhash"), "browser report"),
                 ("failed", self.browser(staged["content_sha256"], status="fail", checks={"video_playback": True}, tag="failed"),
                  "browser report"),
                 ("audioonly", self.film_browser(staged["content_sha256"], checks={"audio_playback": True}, tag="audioonly"),
                  "video playback"),
                 ("videofalse", self.film_browser(staged["content_sha256"], checks={"video_playback": False}, tag="videofalse"),
                  "video playback")]
        for tag, report, message in cases:
            with self.subTest(tag), self.assertRaisesMessage(CommandError, message):
                self.publish_film(report)
        with self.assertRaises(CommandError):
            self.film("publish", "bicharak", "--publisher", str(self.publisher.public_id))
        draft = Revision.objects.get(pk=staged["revision_id"])
        self.assertEqual(draft.state, "draft")
        self.assertNotIn("browser", draft.validation_evidence)
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, old.id)

    def test_publish_with_matching_report_goes_live_with_film(self):
        old, _, folder, unit, evidence, staged = self.staged_film()
        result = self.publish_film(self.film_browser(staged["content_sha256"]))
        live = Edition.objects.get(slug="bicharak").live_revision
        self.assertEqual((result["status"], str(live.id), live.state), ("published", staged["revision_id"], "live"))
        self.assertEqual(Revision.objects.get(pk=old.id).state, "retired")
        self.assertEqual(Asset.objects.get(revision=live, kind="video").sha256, unit["mp4_sha256"])
        report = validate_revision(live, prepared=prepare_revision_validation(live.id))
        checks = {c["code"]: c["status"] for c in report["checks"]}
        self.assertEqual(report["status"], "pass", checks)
        self.assertEqual((checks["publication_clearance"], checks["media"], checks["publication_regions"]), ("pass", "pass", "pass"))
        revisions, assets = Revision.objects.count(), Asset.objects.count()
        self.assertEqual(self.stage_film(folder, evidence)["status"], "already_live")
        self.assertEqual(self.publish_film(self.film_browser(staged["content_sha256"], tag="again"))["status"], "already_live")
        self.assertEqual((Revision.objects.count(), Asset.objects.count()), (revisions, assets))

    # --- audio and film share one draft -------------------------------------------------------------
    def assert_combined(self, draft_id):
        draft = Revision.objects.get(pk=draft_id)
        self.assertEqual(Revision.objects.filter(edition=draft.edition, state="draft").count(), 1)
        self.assertEqual(sorted(draft.assets.filter(kind__in=["audio_chapter", "video", "video_captions"]).values_list("kind", flat=True)),
                         ["audio_chapter", "video", "video_captions"])
        self.assertEqual((draft.access_policy["audio"], draft.access_policy["video"]), ("free", "free"))
        clearance = draft.validation_evidence["publication_clearance"]
        self.assertEqual(clearance["formats"], ["reader", "audio", "video"])
        self.assertEqual(clearance["asset_sha256"], {str(a.id): a.sha256 for a in draft.assets.filter(state="ready")})
        checks = {c["code"]: c["status"] for c in validate_revision(draft, prepared=prepare_revision_validation(draft.id))["checks"]}
        self.assertEqual({k for k, v in checks.items() if v == "fail"}, {"browser"}, checks)
        return draft

    def test_audio_then_film_share_one_draft_and_publish_together(self):
        old, _, _, _, audio = self.staged()
        source = self.export()
        folder, unit = self.film_bundle(source["units"][0]["unit_id"])
        film = self.stage_film(folder, self.film_evidence(source, [unit["mp4_sha256"]]))
        self.assertEqual(film["revision_id"], audio["revision_id"])
        draft = self.assert_combined(film["revision_id"])
        with self.assertRaisesMessage(CommandError, "audio playback"):
            self.publish_film(self.film_browser(draft.content_sha256, tag="videoonly"))
        with self.assertRaisesMessage(CommandError, "video playback"):
            self.publish(self.browser(draft.content_sha256, tag="audioonly"))
        result = self.publish_film(self.film_browser(draft.content_sha256, checks={"audio_playback": True, "video_playback": True}))
        live = Edition.objects.get(slug="bicharak").live_revision
        self.assertEqual((result["status"], str(live.id)), ("published", str(draft.id)))
        self.assertEqual(validate_revision(live, prepared=prepare_revision_validation(live.id))["status"], "pass")
        self.assertEqual(Revision.objects.get(pk=old.id).state, "retired")

    def test_film_then_audio_share_one_draft(self):
        _, source, _, _, _, film = self.staged_film()
        folder, audio_sha = self.bundle(source)
        audio = self.stage(folder, self.evidence(source, audio_sha, tag="audio"))
        self.assertEqual(audio["revision_id"], film["revision_id"])
        self.assert_combined(audio["revision_id"])

    # --- a live revision already offering the other medium is refused before any mutation ----------
    def test_film_refused_when_live_revision_offers_audio(self):
        _, _, _, _, staged = self.staged()
        self.publish(self.browser(staged["content_sha256"]))
        live = Edition.objects.get(slug="bicharak").live_revision
        source = self.export()
        folder, unit = self.film_bundle(source["units"][0]["unit_id"])
        revisions, assets = Revision.objects.count(), Asset.objects.count()
        with self.assertRaisesMessage(CommandError, "already offers audio"):
            self.stage_film(folder, self.film_evidence(source, [unit["mp4_sha256"]]))
        self.assertEqual((Revision.objects.count(), Asset.objects.count()), (revisions, assets))
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, live.id)
        self.assertFalse(Asset.objects.filter(kind__in=["video", "video_captions"]).exists())
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob("*.mp4")), [])  # nothing uploaded

    def test_audio_refused_when_live_revision_offers_film(self):
        _, _, _, _, _, staged = self.staged_film()
        self.publish_film(self.film_browser(staged["content_sha256"]))
        live = Edition.objects.get(slug="bicharak").live_revision
        source = self.export()
        folder, audio_sha = self.bundle(source)
        revisions, assets = Revision.objects.count(), Asset.objects.count()
        with self.assertRaisesMessage(CommandError, "already offers video"):
            self.stage(folder, self.evidence(source, audio_sha, tag="audio"))
        self.assertEqual((Revision.objects.count(), Asset.objects.count()), (revisions, assets))
        self.assertEqual(Edition.objects.get(slug="bicharak").live_revision_id, live.id)
        self.assertFalse(Asset.objects.filter(kind="audio_chapter").exists())
