"""Private local fixtures. No real provider, production account or model calls."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from library import production_handoff as h
from operations.production_bundle import verify_bundle, BundleError
from operations.production_journal import OperationJournal


def packet(root, *, edition=None, revision=None, unit=None, anchor=None, text_sha="c" * 64):
    edition, revision, unit, anchor = [str(x or uuid.uuid4()) for x in (edition, revision, unit, anchor)]
    assets = []
    def add(ident, role, mime, raw, **extra):
        path = root / ident; path.write_bytes(raw)
        assets.append(dict(id=ident, role=role, content_type=mime, path=ident,
            bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), **extra))
    add("native", "native_audio", "audio/wav", b"synthetic retained WAV fixture, not released speech")
    add("audio", "audio", "audio/mpeg", b"synthetic MP3 protocol fixture, not measured media", unit_id=unit, duration_ms=1000, native_wav="native")
    mapping = dict(schema="earnalism.measured_audio_maps.v1", edition_revision_id=revision, text_sha256=text_sha,
        maps=[dict(audio_asset_id="audio", precision="paragraph", measured=True, measurement_evidence_ref="synthetic-local-only/alignment",
            segments=[dict(anchor_id=anchor, start_offset_chars=0, end_offset_chars=5, start_ms=0, end_ms=1000)])])
    add("map", "timing_map", "application/json", h.canonical(mapping), unit_id=unit)
    add("captions", "captions", "text/vtt", b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n")
    add("qa", "qa_report", "application/json", b'{"listening":"UNASSESSED","synthetic_fixture":true}')
    add("rights", "rights_document", "text/plain", b"Synthetic reference only; no rights approval or grant")
    return dict(schema="earnalism.production_bundle.v1", project_id="local-handoff-fixture", private=True,
        content=dict(edition_id=edition, revision_id=revision, expected_etag='"v1"', text_sha256=text_sha, language="en", voice_profile="en_mary"),
        assets=assets, evidence=dict(qa=["qa"], rights=["rights"], measured_maps="map", captions="captions"))


class FakeHTTP:
    """Exercises actual endpoint shapes and PostgreSQL child-version effects."""
    def __init__(self, manifest):
        self.manifest = manifest; self.version = 1; self.assets = {}; self.operations = {}
        self.calls = []; self.puts = []; self.fail_after = None; self.race = False

    def request(self, method, path, *, payload=None, headers=None):
        self.calls.append((method, path, copy.deepcopy(payload), copy.deepcopy(headers)))
        c = self.manifest["content"]
        if method == "GET":
            if path.endswith(("/review", "/production-handoffs")):
                return 200, dict(state=dict(edition_id=c["edition_id"], edition_revision_id=c["revision_id"], sha256=c["text_sha256"], state="draft")), {"ETag": '"v' + str(self.version) + '"'}
            if path.endswith("/document"):
                return 200, dict(state="draft", sha256=c["text_sha256"], edition_revision_id=c["revision_id"], units=[{"unit_id": self.manifest["assets"][1]["unit_id"]}]), {}
            asset = self.assets[path.rsplit("/", 1)[-1]]
            return 200, self.state(asset), {"ETag": '"v' + str(asset["version"]) + '"'}
        key = headers["Idempotency-Key"]
        binding = h.fingerprint(dict(path=path, payload=payload, etag=headers.get("If-Match")))
        if path.endswith("/production-handoffs"):
            if key not in self.operations:
                self.version += 1; self.operations[key] = (binding, None)
            assert self.operations[key][0] == binding
            if self.fail_after == "attach":
                self.fail_after = None; raise OSError("SECRET response lost after private attachment")
            ids = list(self.assets)
            return 202, dict(state="DRAFT_PRIVATE_MEDIA_PROCESSING", current_etag='"v' + str(self.version) + '"',
                verified_asset_ids=[i for i in ids if self.assets[i]["state"] == "ready"],
                processing_asset_ids=[i for i in ids if self.assets[i]["state"] != "ready"],
                release_ready=False, publication=False), {}
        if key in self.operations:
            old, reply = self.operations[key]
            if binding != old:
                return 409, {"code": "idempotency_key_reused"}, {}
            return copy.deepcopy(reply)
        if path.endswith("/uploads"):
            ident = str(uuid.uuid4())
            self.assets[ident] = dict(id=ident, body=payload, state="uploading", version=1, uploaded=False)
            data = dict(asset_id=ident, version=1, protocol="r2_put", method="PUT", upload_url="https://owned.r2.cloudflarestorage.com/private/" + ident + "?X-Amz-Signature=SECRET",
                required_headers={"Content-Type": payload["content_type"], "If-None-Match": "*"}, max_bytes=payload["bytes"], expires_at="2099-01-01T00:00:00Z")
            if payload["kind"] == "video":
                self.assets[ident]["version"] = 2
                data.update(version=2, protocol="stream_tus", method="PATCH", provider_uid="a" * 32,
                    required_headers={"Tus-Resumable": "1.0.0"})
            reply = (201, data, {"ETag": '"v1"'}); phase = "intent"
        else:
            ident = path.split("/")[-2]; asset = self.assets[ident]
            self.assert_complete(asset, payload, headers)
            asset["state"] = "processing" if asset["body"]["kind"] in {"audio", "video"} else "ready"
            asset["version"] += 1
            reply = (200, self.state(asset), {"ETag": '"v' + str(asset["version"]) + '"'}); phase = "complete"
        self.version += data["version"] if phase == "intent" else 1
        self.operations[key] = (binding, copy.deepcopy(reply))
        if self.fail_after == phase:
            self.fail_after = None
            raise OSError("SECRET lost response with provider capabilities")
        return reply

    def assert_complete(self, asset, payload, headers):
        assert headers["If-Match"] == '"v' + str(asset["version"]) + '"'
        assert payload == {k: asset["body"][k] for k in ("bytes", "sha256")}
        assert asset["uploaded"], "Fixture completion must validate actually retained bytes"

    def state(self, asset):
        return dict(asset_id=asset["id"], edition_revision_id=asset["body"]["edition_revision_id"], state=asset["state"],
            sha256=asset["body"]["sha256"], bytes=asset["body"]["bytes"], version=asset["version"])

    def put_upload(self, url, required_headers, path):
        ident = url.split("?")[0].rsplit("/", 1)[-1]; asset = self.assets[ident]
        raw = Path(path).read_bytes()
        assert len(raw) == asset["body"]["bytes"] and hashlib.sha256(raw).hexdigest() == asset["body"]["sha256"]
        assert required_headers["If-None-Match"] == "*" and not asset["uploaded"]
        asset["uploaded"] = True; self.puts.append(ident)
        if self.race:
            self.race = False; self.version += 1
        if self.fail_after == "put":
            self.fail_after = None; raise OSError("SECRET unknown PUT response")
        return 200

    def upload_tus(self, grant, path, expected_sha256, *, journal, key, reconcile=False):
        ident = grant["upload_url"].split("?")[0].rsplit("/", 1)[-1]
        raw = Path(path).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected_sha256
        self.assets[ident]["uploaded"] = True
        self.tus_reconciled = reconcile
        if self.fail_after == "tus":
            self.fail_after = None; raise OSError("unknown final TUS acknowledgement")
        return dict(upload_offset=len(raw), provider_uid=grant["provider_uid"])


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.bundle = packet(self.root)
        self.http = FakeHTTP(self.bundle); self.journal = OperationJournal(self.root / "journal")

    def run_stage(self, **kwargs):
        return h.stage_private(self.bundle, self.root, self.http, self.journal, **kwargs)

    def test_default_never_calls_http_and_preserves_native(self):
        result = self.run_stage()
        self.assertFalse(result["execution_enabled"]); self.assertEqual(self.http.calls, [])
        self.assertEqual(result["retained_only_assets"], ["native"])
        captions = next(x for x in result["uploads"] if x["id"] == "captions")
        self.assertEqual(captions["body"]["content_type"], "text/plain")

    def test_private_upload_complete_and_reuse_do_not_publish_or_repeat_put(self):
        result = self.run_stage(execute=True)
        self.assertEqual(len(result["assets"]), 5); self.assertEqual(len(self.http.puts), 5)
        self.assertEqual(result["assets"]["audio"]["state"], "processing")
        self.assertFalse(result["publication"]); self.assertFalse(result["ready"])
        self.assertEqual(result, self.run_stage(execute=True))
        self.assertEqual(len(self.http.puts), 5)
        retained = b"".join(p.read_bytes() for p in (self.root / "journal").glob("*.json"))
        self.assertNotIn(b"SECRET", retained); self.assertNotIn(b"upload_url", retained)

    def test_unknown_intent_reconciles_same_server_receipt_once(self):
        self.http.fail_after = "intent"
        with self.assertRaisesRegex(h.HandoffError, "UNKNOWN"):
            self.run_stage(execute=True)
        self.assertEqual(len(self.http.assets), 1)
        with self.assertRaisesRegex(h.HandoffError, "RECONCILIATION"):
            self.run_stage(execute=True)
        result = self.run_stage(execute=True, reconcile=True)
        self.assertEqual(len(self.http.assets), 5); self.assertEqual(len(result["assets"]), 5)

    def test_known_http_rejection_is_retained_without_unknown_retry(self):
        original = self.http.request; writes = []
        def rejected(method, path, **kwargs):
            if method == "POST":
                writes.append(path); return 422, {"code": "unsupported_profile"}, {}
            return original(method, path, **kwargs)
        self.http.request = rejected
        for _ in range(2):
            with self.assertRaisesRegex(h.HandoffError, "REJECTED_unsupported_profile"):
                self.run_stage(execute=True)
        self.assertEqual(len(writes), 1)

    def test_interrupted_local_scope_preparation_resumes_before_any_http(self):
        digest = verify_bundle(self.bundle, self.root)
        self.journal.begin("maison:" + digest + ":scope", digest)
        result = self.run_stage(execute=True)
        self.assertEqual(len(result["assets"]), 5)

    def test_unknown_put_is_never_repeated_and_remains_provider_pending(self):
        self.http.fail_after = "put"
        with self.assertRaisesRegex(h.HandoffError, "UNKNOWN_NO_REPLAY"):
            self.run_stage(execute=True)
        first = self.http.puts[0]
        result = self.run_stage(execute=True, reconcile=True)
        self.assertEqual(self.http.puts.count(first), 1)
        self.assertEqual(result["uncertain_uploads_require_provider_verification"], ["audio"])
        self.assertFalse(result["ready"])

    def test_unknown_completion_reconciles_without_reuploading(self):
        self.http.fail_after = "complete"
        with self.assertRaisesRegex(h.HandoffError, "UNKNOWN"):
            self.run_stage(execute=True)
        first = self.http.puts[0]
        self.run_stage(execute=True, reconcile=True)
        self.assertEqual(self.http.puts.count(first), 1)

    def test_unknown_attachment_resumes_rpc_without_restaging_changed_revision(self):
        self.http.fail_after = "attach"
        with self.assertRaisesRegex(h.HandoffError, "UNKNOWN"):
            self.run_stage(execute=True)
        before = list(self.http.puts)
        result = self.run_stage(execute=True, reconcile=True)
        self.assertEqual(self.http.puts, before)
        self.assertEqual(result["state"], "DRAFT_PRIVATE_MEDIA_PROCESSING")

    def test_each_explicit_reconcile_observes_fresh_ready_status(self):
        first = self.run_stage(execute=True)
        second = self.run_stage(execute=True, reconcile=True)
        self.assertTrue(first["attachment"]["processing_asset_ids"])
        self.assertTrue(second["attachment"]["processing_asset_ids"])
        before = list(self.http.puts)
        for item in self.http.assets.values(): item["state"] = "ready"
        third = self.run_stage(execute=True, reconcile=True)
        self.assertEqual(third["attachment"]["processing_asset_ids"], [])
        self.assertEqual(self.http.puts, before)
        rpc_calls = [row for row in self.http.calls if row[0] == "POST" and row[1].endswith("/production-handoffs")]
        self.assertEqual(len(rpc_calls), 3)
        self.assertEqual(len({row[3]["Idempotency-Key"] for row in rpc_calls}), 1)

    def test_private_stream_video_uses_shared_tus_hook_and_offset_reconciliation(self):
        raw = b"synthetic local video transport fixture"
        (self.root / "video").write_bytes(raw)
        self.bundle["assets"].append(dict(id="video", path="video", role="video", content_type="video/mp4",
            bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), unit_id=self.bundle["assets"][1]["unit_id"], duration_ms=1000))
        self.http.fail_after = "tus"
        with self.assertRaisesRegex(h.HandoffError, "TUS_OFFSET_RECONCILIATION"):
            self.run_stage(execute=True)
        previous_puts = list(self.http.puts)
        result = self.run_stage(execute=True, reconcile=True)
        self.assertTrue(self.http.tus_reconciled)
        self.assertEqual(previous_puts, self.http.puts)
        self.assertEqual(result["assets"]["video"]["state"], "processing")

    def test_extra_revision_change_holds_after_preserving_private_upload(self):
        self.http.race = True
        with self.assertRaisesRegex(h.HandoffError, "ETAG_CHANGED"):
            self.run_stage(execute=True)
        self.assertEqual(len(self.http.assets), 1)

    def test_tampered_original_or_nonprivate_bundle_never_dispatches(self):
        (self.root / "native").write_bytes(b"changed")
        with self.assertRaises(BundleError): self.run_stage(execute=True)
        self.assertEqual(self.http.calls, [])
        self.bundle = packet(self.root); self.bundle["private"] = False
        with self.assertRaisesRegex(h.HandoffError, "PRIVATE_EXISTING"):
            self.run_stage(execute=True)

    def test_real_transport_streams_and_never_forwards_session_to_r2(self):
        calls = []
        class Response:
            code = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
        class Opener:
            def open(self, req, **kwargs):
                calls.append((req.method, dict(req.header_items()), req.data.read()))
                return Response()
        client = h.MaisonHTTP("https://maison.example.test", "sessionid=PRIVATE", "CSRF", opener=Opener())
        self.assertEqual(client.put_upload("https://owned.r2.cloudflarestorage.com/key?signature=PRIVATE",
            {"Content-Type": "audio/mpeg", "If-None-Match": "*"}, self.root / "audio"), 200)
        self.assertEqual(calls[0][2], (self.root / "audio").read_bytes())
        self.assertFalse(any(k.lower() in {"cookie", "x-csrftoken", "authorization"} for k in calls[0][1]))
        with self.assertRaisesRegex(h.HandoffError, "STAFF_ROUTE"):
            client.request("POST", "/api/v1/staff/editions/anything/publish")
        with self.assertRaisesRegex(h.HandoffError, "UPLOAD_ORIGIN"):
            client.put_upload("https://unrelated.example.test/put", {}, self.root / "audio")

    def test_local_measurement_uses_fixed_ffprobe_arguments_and_checks_codec(self):
        result = type("Result", (), {"stdout": b'{"streams":[{"codec_name":"mp3","codec_type":"audio","bit_rate":"96000"}],"format":{"duration":"1.0"}}'})()
        with patch("subprocess.run", return_value=result) as run:
            proof = h.measure_mp3(self.root / "audio")
            self.assertEqual(proof["duration_ms"], 1000); self.assertEqual(proof["quality_kbps"], 96)
            self.assertFalse(run.call_args.kwargs.get("shell", False))
            self.assertEqual(run.call_args.args[0][-1], str((self.root / "audio").resolve()))
        result.stdout = result.stdout.replace(b'96000', b'128000')
        with patch("subprocess.run", return_value=result), self.assertRaises(h.HandoffError):
            h.measure_mp3(self.root / "audio")

    def test_actual_mp3_container_measurement_on_synthetic_local_tone(self):
        import shutil
        import subprocess
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("Local ffmpeg/ffprobe unavailable; no measurement qualification claimed")
        path = self.root / "codec-fixture.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-ac", "1", "-b:a", "96k", str(path)], check=True, capture_output=True, timeout=10)
        proof = h.measure_mp3(path)
        self.assertEqual(proof["quality_kbps"], 96); self.assertGreater(proof["duration_ms"], 0)


try:
    from django.test import TestCase
except ImportError:
    TestCase = None

if TestCase is not None:
    class AttachmentTests(TestCase):
        """Actual existing ORM/CAS/operation receipts. Isolated PostgreSQL test DB."""
        def setUp(self):
            from django.contrib.auth import get_user_model
            from library.models import Work, Edition, Revision, Unit, Paragraph, Asset
            from library.services import revision_hash
            self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
            self.actor = get_user_model().objects.create_superuser("handoff@example.test", "Local-Fixture-Password47")
            work = Work.objects.create(slug="handoff-fixture", title="Local fixture", creators=["Fixture"], house="learn")
            self.edition = Edition.objects.create(work=work, slug="handoff-fixture-en", locale="en")
            self.revision = Revision.objects.create(edition=self.edition, title="Local fixture")
            self.unit = Unit.objects.create(revision=self.revision, title="Fixture", ordinal=1, duration_ms=1000)
            para = Paragraph.objects.create(unit=self.unit, ordinal=1, text="Hello")
            self.revision.content_sha256 = revision_hash(self.revision); self.revision.save()
            self.bundle = packet(self.root, edition=self.edition.id, revision=self.revision.id, unit=self.unit.id,
                anchor=para.anchor_id, text_sha=self.revision.content_sha256)
            plan = h.prepare_handoff(self.bundle, self.root); assets = {}
            for item in plan["uploads"]:
                b = item["body"]; ident = uuid.uuid4()
                asset = Asset.objects.create(id=ident, revision=self.revision, unit=self.unit if b.get("unit_id") else None,
                    kind="audio_chapter" if b["kind"] == "audio" else b["kind"], provider="r2",
                    state="processing" if b["kind"] == "audio" else "ready", storage_key=f"revisions/{self.revision.id}/{ident}",
                    bytes=b["bytes"], sha256=b["sha256"], content_type=b["content_type"], duration_ms=b.get("duration_ms"))
                assets[item["id"]] = dict(asset_id=str(asset.id), edition_revision_id=str(self.revision.id),
                    state=asset.state, sha256=asset.sha256, bytes=asset.bytes, version=asset.version)
            self.revision.refresh_from_db(); self.etag = f'"v{self.revision.version}"'
            self.staged = dict(schema="earnalism.maison_private_handoff.v1", bundle_sha256=plan["bundle_sha256"],
                state="DRAFT_ASSETS_STAGED_ATTACHMENT_AND_MEDIA_VERIFICATION_PENDING", expected_etag=self.etag,
                edition_id=str(self.edition.id), revision_id=str(self.revision.id), text_sha256=self.revision.content_sha256, assets=assets,
                uncertain_uploads_require_provider_verification=[], retained_only_assets=["native"], publication=False, ready=False, rights_approval_created=False)
            self.measure = lambda path, **kwargs: dict(duration_ms=1000, quality_kbps=96, measurement_sha256="a" * 64, method="SYNTHETIC_ISOLATED_TEST_NOT_REAL_MEDIA")

        def attach(self, **kwargs):
            return h.attach_private(self.bundle, self.root, self.staged, self.actor, self.etag,
                kwargs.pop("operation_id", str(uuid.uuid4())), measure=self.measure, **kwargs)

        def test_default_attachment_does_not_touch_db(self):
            from library.models import TimingMap
            before = self.revision.version; self.attach()
            self.revision.refresh_from_db()
            self.assertEqual(self.revision.version, before); self.assertEqual(TimingMap.objects.count(), 0)

        def test_real_attachment_retains_evidence_and_maps_without_ready_or_rights(self):
            from library.models import Asset, TimingMap, Rights
            key = str(uuid.uuid4()); first = self.attach(execute=True, operation_id=key)
            self.assertEqual(first, self.attach(execute=True, operation_id=key))
            self.revision.refresh_from_db(); self.edition.refresh_from_db()
            self.assertEqual(self.revision.state, "draft"); self.assertIsNone(self.edition.live_revision_id)
            self.assertEqual(TimingMap.objects.count(), 1); self.assertEqual(Rights.objects.count(), 0)
            self.assertEqual(Asset.objects.get(pk=self.staged["assets"]["audio"]["asset_id"]).state, "processing")
            record = self.revision.validation_evidence["production_handoffs"][self.staged["bundle_sha256"]]
            self.assertFalse(record["actual_listening"]); self.assertFalse(record["rights_approval_created"])
            self.assertEqual(record["evidence_references"], self.bundle["evidence"])

        def test_stale_etag_rolls_back_all_attachment_mutations(self):
            from core.api import DomainError
            from library.models import TimingMap
            self.etag = '"v1"'
            with self.assertRaises(DomainError): self.attach(execute=True)
            self.assertEqual(TimingMap.objects.count(), 0)
            self.revision.refresh_from_db(); self.assertEqual(self.revision.validation_evidence, {})

        def test_mime_mismatch_cannot_attach_even_when_hash_matches(self):
            from core.api import DomainError
            from library.models import Asset, TimingMap
            asset = Asset.objects.get(pk=self.staged["assets"]["audio"]["asset_id"])
            asset.content_type = "audio/aac"; asset.save()
            self.revision.refresh_from_db(); self.etag = f'"v{self.revision.version}"'
            with self.assertRaises(DomainError): self.attach(execute=True)
            self.assertEqual(TimingMap.objects.count(), 0)

        def test_invalid_canonical_anchor_rolls_back(self):
            from core.api import DomainError
            from library.models import TimingMap
            path = self.root / "map"; mapping = json.loads(path.read_bytes())
            mapping["maps"][0]["segments"][0]["anchor_id"] = str(uuid.uuid4()); raw = h.canonical(mapping); path.write_bytes(raw)
            item = next(x for x in self.bundle["assets"] if x["id"] == "map"); item.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            # Bind a fresh fixture storage intent to changed bytes, without any provider calls.
            from library.models import Asset
            asset = Asset.objects.get(pk=self.staged["assets"]["map"]["asset_id"]); asset.bytes=len(raw); asset.sha256=item["sha256"]; asset.save()
            asset.refresh_from_db(); self.staged["assets"]["map"].update(bytes=len(raw), sha256=asset.sha256, version=asset.version)
            self.staged["bundle_sha256"] = verify_bundle(self.bundle, self.root)
            self.revision.refresh_from_db(); self.etag=f'"v{self.revision.version}"'
            with self.assertRaises(DomainError): self.attach(execute=True)
            self.assertEqual(TimingMap.objects.count(), 0)

        def test_client_against_real_staff_views_and_postgres_etags(self):
            from django.test import Client
            client = Client(enforce_csrf_checks=True)
            csrf = client.get("/api/v1/session").json()["csrf_token"]
            login = client.post("/api/v1/auth/login", h.canonical(dict(email=self.actor.email,
                password="Local-Fixture-Password47", password_purpose_consent=True,
                password_purpose_version="password-account-v1")), content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
            self.assertEqual(login.status_code, 200, login.content)
            csrf = client.get("/api/v1/session").json()["csrf_token"]
            self.bundle["content"]["expected_etag"] = self.etag
            objects = {}; calls = []
            class ViewTransport:
                def request(inner, method, path, *, payload=None, headers=None):
                    calls.append((method, path))
                    extra = {"HTTP_" + k.upper().replace("-", "_"): v for k, v in (headers or {}).items()}
                    response = client.get(path, **extra) if method == "GET" else client.post(path,
                        h.canonical(payload), content_type="application/json", HTTP_X_CSRFTOKEN=csrf, **extra)
                    return response.status_code, response.json(), dict(response.headers)
                def put_upload(inner, url, required_headers, path):
                    objects[url.rsplit("/", 1)[-1]] = Path(path).read_bytes()
                    return 200
            def read_verified(asset):
                raw = objects[str(asset.id)]
                self.assertEqual(len(raw), asset.bytes)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), asset.sha256)
                return raw
            def owned_stream(key):
                ident = key.rsplit("/", 1)[-1]
                from library.models import Asset
                asset = Asset.objects.get(pk=ident)
                by_sha = {x["sha256"]: self.root / x["path"] for x in self.bundle["assets"]}
                raw = objects[ident] if ident in objects else by_sha[asset.sha256].read_bytes()
                return io.BytesIO(raw), len(raw), asset.content_type
            with patch("library.storage.is_r2", return_value=True), patch("library.storage.upload_url",
                side_effect=lambda asset: ("https://fixture.r2.cloudflarestorage.com/" + str(asset.id),
                    {"Content-Type": asset.content_type, "If-None-Match": "*"})), patch("library.storage.read_verified", side_effect=read_verified), \
                patch("library.storage._open", side_effect=owned_stream), patch("library.production_handoff_api.measure_mp3", side_effect=self.measure), \
                patch("library.production_handoff_api.call_command"):
                result = h.stage_private(self.bundle, self.root, ViewTransport(), OperationJournal(self.root / "actual-view-journal"), execute=True)
            self.assertEqual(len(result["assets"]), 5)
            self.assertGreaterEqual(h._version(result["expected_etag"]), h._version(self.etag) + 12)
            self.assertEqual(result["assets"]["audio"]["state"], "processing")
            self.assertFalse(any(path.endswith(("/publish", "/mark-ready", "/schedule")) for _, path in calls))
            self.revision.refresh_from_db(); self.edition.refresh_from_db()
            self.assertEqual(self.revision.state, "draft"); self.assertIsNone(self.edition.live_revision_id)

        def rpc(self, *, etag=True, operation_id=None):
            from django.test import RequestFactory
            from library.production_handoff_api import production_handoffs
            headers = dict(HTTP_IDEMPOTENCY_KEY=operation_id or str(uuid.uuid4()))
            if etag: headers["HTTP_IF_MATCH"] = self.etag
            req = RequestFactory().post("/api/v1/staff/editions/" + str(self.edition.id) + "/production-handoffs",
                h.canonical(dict(manifest=self.bundle, staging_receipt=self.staged)), content_type="application/json", **headers)
            req.user = self.actor
            return production_handoffs(req, self.edition.id)

        def test_rpc_verifies_only_staged_subset_native_remains_reference(self):
            from library.models import Asset
            def source(key):
                ident = key.rsplit("/", 1)[-1]
                asset = Asset.objects.get(pk=ident)
                by_sha = {x["sha256"]: self.root / x["path"] for x in self.bundle["assets"]}
                raw = by_sha[asset.sha256].read_bytes()
                return io.BytesIO(raw), len(raw), asset.content_type
            with patch("library.storage._open", side_effect=source), patch("library.production_handoff_api.measure_mp3", side_effect=self.measure), \
                patch("library.production_handoff_api.call_command"):
                response = self.rpc()
            self.assertEqual(response.status_code, 202, response.content)
            body = json.loads(response.content); self.assertFalse(body["release_ready"])
            self.assertEqual(body["native_wav_scope"], "PROVENANCE_REFERENCE_ONLY_NOT_SERVER_BYTE_VERIFIED")
            self.revision.refresh_from_db()
            proof = self.revision.validation_evidence["production_handoffs"][self.staged["bundle_sha256"]]
            self.assertEqual(proof["source_byte_verification_scope"], "SERVER_VERIFIED_STAGED_ASSETS_NATIVE_WAV_PROVENANCE_REFERENCE_ONLY")

        def test_rpc_hash_failure_or_missing_precondition_never_attaches(self):
            from library.models import TimingMap
            with patch("library.storage._open") as provider:
                response = self.rpc(etag=False)
                self.assertEqual(response.status_code, 428)
                provider.assert_not_called()
            with patch("library.storage._open", return_value=(io.BytesIO(b"wrong"), self.bundle["assets"][1]["bytes"], "audio/mpeg")):
                response = self.rpc()
            self.assertEqual(response.status_code, 422)
            self.assertEqual(TimingMap.objects.count(), 0)

        def test_rpc_replay_cannot_hide_missing_asset_or_nonprivate_revision(self):
            from library.models import Asset
            by_sha = {x["sha256"]: self.root / x["path"] for x in self.bundle["assets"]}
            def source(key):
                asset = Asset.objects.get(pk=key.rsplit("/", 1)[-1]); raw = by_sha[asset.sha256].read_bytes()
                return io.BytesIO(raw), len(raw), asset.content_type
            operation = str(uuid.uuid4())
            with patch("library.storage._open", side_effect=source), patch("library.production_handoff_api.measure_mp3", side_effect=self.measure), \
                patch("library.production_handoff_api.call_command"):
                first = self.rpc(operation_id=operation)
                self.assertEqual(first.status_code, 202, first.content)
            Asset.objects.get(pk=self.staged["assets"]["qa"]["asset_id"]).delete()
            with patch("library.storage._open") as provider, patch("library.production_handoff_api.call_command"):
                missing = self.rpc(operation_id=operation)
                self.assertEqual(missing.status_code, 409)
                provider.assert_not_called()
            self.revision.refresh_from_db(); self.revision.state="ready"; self.revision.save()
            with patch("library.storage._open") as provider:
                frozen = self.rpc(operation_id=operation)
                self.assertEqual(frozen.status_code, 409)
                provider.assert_not_called()


if TestCase is not None:
    from django.test import TransactionTestCase, override_settings

    @override_settings(SECRET_KEY="synthetic-stream-handoff-test-key-" * 3, STREAM_ACCOUNT_ID="b" * 32,
        STREAM_API_TOKEN="synthetic-not-real", STREAM_CUSTOMER_HOST="customer-synthetic.cloudflarestream.com")
    class StreamClientJourneyTests(TransactionTestCase):
        def setUp(self):
            AttachmentTests.setUp(self)

        def test_real_video_intent_two_mutations_then_completion_and_attachment(self):
            from django.test import Client
            from django.db import connection
            from django.core.management import call_command as real_command
            from library.models import Asset
            raw = b"synthetic exact local MP4 transport fixture"
            (self.root / "video").write_bytes(raw)
            self.bundle["assets"].append(dict(id="video", path="video", role="video", content_type="video/mp4",
                bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), unit_id=str(self.unit.id), duration_ms=1000))
            self.bundle["content"]["expected_etag"] = self.etag
            client = Client(enforce_csrf_checks=True)
            csrf = client.get("/api/v1/session").json()["csrf_token"]
            login = client.post("/api/v1/auth/login", h.canonical(dict(email=self.actor.email,
                password="Local-Fixture-Password47", password_purpose_consent=True, password_purpose_version="password-account-v1")),
                content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
            self.assertEqual(login.status_code, 200)
            csrf = client.get("/api/v1/session").json()["csrf_token"]
            objects = {}; ready = False; grants = []
            class Transport:
                def request(inner, method, path, *, payload=None, headers=None):
                    extra = {"HTTP_" + k.upper().replace("-", "_"): v for k, v in (headers or {}).items()}
                    response = client.get(path, **extra) if method == "GET" else client.post(path, h.canonical(payload),
                        content_type="application/json", HTTP_X_CSRFTOKEN=csrf, **extra)
                    data = response.json()
                    if method == "POST" and path.endswith("/uploads") and payload["kind"] == "video": grants.append(data)
                    return response.status_code, data, dict(response.headers)
                def put_upload(inner, url, required_headers, path):
                    objects[url.rsplit("/", 1)[-1]] = Path(path).read_bytes(); return 200
                def upload_tus(inner, grant, path, expected_sha256, **kwargs):
                    nonlocal ready
                    uploaded = Path(path).read_bytes(); self.assertEqual(hashlib.sha256(uploaded).hexdigest(), expected_sha256)
                    ready = True
                    return dict(provider_uid=grant["provider_uid"], upload_offset=len(uploaded), bytes=len(uploaded), sha256=expected_sha256)
            def provider(asset, expiry):
                self.assertFalse(connection.in_atomic_block)
                return dict(provider_uid="a" * 32, upload_url="https://upload.videodelivery.net/tus/fixture?capability=SYNTHETIC")
            def metadata(*args, **kwargs):
                return dict(uid="a" * 32, requireSignedURLs=True, readyToStream=ready, duration=1.0,
                    status={"state": "ready" if ready else "uploading"},
                    playback={"hls": "https://customer-synthetic.cloudflarestream.com/" + "a" * 32 + "/manifest/video.m3u8"})
            def owned_source(key):
                ident = key.rsplit("/", 1)[-1]; asset = Asset.objects.get(pk=ident)
                content = objects[ident]; return io.BytesIO(content), len(content), asset.content_type
            def read_verified(asset):
                content = objects[str(asset.id)]; self.assertEqual(hashlib.sha256(content).hexdigest(), asset.sha256); return content
            def verify(command, asset_id, **kwargs):
                if Asset.objects.get(pk=asset_id).provider == "stream":
                    return real_command(command, asset_id, **kwargs)
            with patch("library.storage.is_r2", return_value=True), patch("library.storage.upload_url",
                side_effect=lambda asset: ("https://fixture.r2.cloudflarestorage.com/" + str(asset.id),
                    {"Content-Type": asset.content_type, "If-None-Match": "*"})), patch("library.storage.read_verified", side_effect=read_verified), \
                patch("library.storage._open", side_effect=owned_source), patch("library.production_handoff_api.measure_mp3", side_effect=self.measure), \
                patch("library.production_handoff_api.call_command", side_effect=verify), \
                patch("library.stream_upload._create_provider_upload", side_effect=provider), patch("library.stream._metadata_request", side_effect=metadata):
                result = h.stage_private(self.bundle, self.root, Transport(), OperationJournal(self.root / "stream-journey"), execute=True)
            self.assertEqual(grants[0]["version"], 2)
            video_id = result["assets"]["video"]["asset_id"]
            self.assertEqual(result["assets"]["video"]["version"], 3)
            self.assertEqual(Asset.objects.get(pk=video_id).state, "ready")
            self.assertEqual(result["attachment"]["asset_snapshot"][video_id]["state"], "ready")
            self.revision.refresh_from_db(); self.edition.refresh_from_db()
            self.assertEqual(self.revision.state, "draft"); self.assertIsNone(self.edition.live_revision_id)


if __name__ == "__main__":
    unittest.main()
