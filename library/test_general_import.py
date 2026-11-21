"""Private general imports on PostgreSQL; provider objects are in-memory fixtures."""
from copy import deepcopy
import io
import json
import uuid
import unicodedata
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase
from django.utils import timezone

from core.api import DomainError
from core.models import OperationReceipt
from . import general_import as service
from .models import Asset, Edition, Paragraph, Revision, Rights, Unit, Work
from .services import _reader_package_coverage, canonical_bytes, digest, revision_hash
from .validation import validate_schema


def source_packet(language="en", *, large=False, nfd=False):
    if language == "bn":
        text = "ঘরে আলো জ্বলিতেছে। বিচারক কাগজখানি মন দিয়ে পড়িলেন।"
        title = "বিচারক — ব্যক্তিগত পরীক্ষার পাঠ"
    else:
        text = "The retained source remained unchanged while its private Reader edition was prepared."
        title = "Private source chapter"
    if nfd:
        text = "Cafe\u0301 and \u09dc \u09df retain their exact source code points."
        title = "Cafe\u0301 — \u09dc \u09df"
    count = 4200 if large else 3
    return {"schema": "earnalism.book_source.v1", "language": language,
        "units": [{"key": "chapter-1", "title": title, "kind": "chapter", "duration_ms": 12000,
            "paragraphs": [{"kind": "paragraph", "text": text + " " + str(n)} for n in range(count)]},
            {"key": "ending", "title": "Ending", "kind": "chapter",
             "paragraphs": [{"kind": "verse", "text": "A full ending.\nNothing is discarded."}]}]}


def manifest_for(source):
    raw = json.dumps(source, ensure_ascii=False, indent=1).encode("utf-8")
    manifest = {"schema": "earnalism.book_import_manifest.v1", "project_id": "private-source-fixture",
        "work": {"slug": "private-general-work", "title": "Private source work",
            "creators": ["Synthetic source author"], "house": "golpo"},
        "edition": {"slug": "private-general-edition", "language": source["language"],
            "title": "Private source edition", "description": "Local protocol fixture; no rights or release approval."},
        "source": {"sha256": digest(raw), "bytes": len(raw), "content_type": "application/json",
            "format": "earnalism.book_source.v1"},
        "provenance": {"source_ref": "synthetic-local/source-001", "source_edition": "Private test edition",
            "rights_note": "Reference only. No publication clearance is asserted.",
            "rights_evidence_refs": ["synthetic-local/uncleared-reference"]}}
    return manifest, raw


class GeneralSourceImportTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser("general-import@example.test", "Local-Import-Password47")
        self.objects, self.provider_puts, self.provider_reads = {}, [], []
        self.race = False
        self.put = patch("library.storage.put_private", side_effect=self.put_private).start()
        self.open = patch("library.storage._open", side_effect=self.open_private).start()
        self.addCleanup(patch.stopall)

    def put_private(self, key, raw, content_type="application/json"):
        self.assertFalse(connection.in_atomic_block, "Provider PUT must precede the receipt transaction")
        old = self.objects.get(key)
        if old is not None:
            self.assertEqual(old, (raw, content_type))
        else:
            self.objects[key] = (raw, content_type)
        self.provider_puts.append(key)
        if self.race:
            self.race = False
            Revision.objects.update(description="Concurrent metadata edit preserved")
        return {"bytes": len(raw), "sha256": digest(raw)}

    def open_private(self, key):
        self.assertFalse(connection.in_atomic_block, "Source GET must precede the receipt transaction")
        self.provider_reads.append(key)
        raw, mime = self.objects[key]
        return io.BytesIO(raw), len(raw), mime

    def reserve(self, source=None):
        self.source = source or source_packet()
        self.manifest, self.raw = manifest_for(self.source)
        self.start_operation = uuid.uuid4()
        status, result = service.start_import(self.actor, self.manifest, self.start_operation)
        self.assertEqual(status, 201)
        self.started = result
        self.revision = Revision.objects.select_related("edition", "edition__work").get(pk=result["edition_revision_id"])
        return result

    def staged_source(self):
        asset = Asset.objects.create(revision=self.revision, kind="reader_source", state="ready",
            storage_key=f"revisions/{self.revision.id}/{uuid.uuid4()}.json", content_type="application/json",
            sha256=digest(self.raw), bytes=len(self.raw))
        self.objects[asset.storage_key] = (self.raw, "application/json")
        self.revision.refresh_from_db(); self.version = self.revision.version
        self.source_asset = asset
        self.completion = {"edition_revision_id": str(self.revision.id), "source_asset_id": str(asset.id),
            "source_sha256": asset.sha256, "source_bytes": asset.bytes}
        self.final_operation = uuid.uuid4()
        return asset

    def finalize(self, *, actor=None, data=None, version=None, operation=None):
        return service.finalize_import(actor or self.actor, self.revision.edition_id,
            data or self.completion, self.version if version is None else version, operation or self.final_operation)

    def assert_private(self):
        self.revision.refresh_from_db(); self.revision.edition.refresh_from_db()
        self.assertEqual(self.revision.state, "draft"); self.assertIsNone(self.revision.edition.live_revision_id)
        self.assertEqual(self.revision.access_policy, service.DENIED)
        self.assertEqual(self.revision.download_policy, service.NO_DOWNLOADS)
        self.assertEqual(self.revision.preview, []); self.assertEqual(Rights.objects.count(), 0)

    def test_start_is_db_only_denied_draft_and_reservation_replay_is_immutable(self):
        first = self.reserve(); self.assert_private()
        self.assertEqual(self.revision.content_sha256, service.EMPTY_SHA)
        self.assertEqual(Unit.objects.count(), 0); self.put.assert_not_called(); self.open.assert_not_called()
        self.staged_source()
        replay = service.start_import(self.actor, deepcopy(self.manifest), self.start_operation)
        self.assertEqual(replay, (201, first))
        self.assertEqual(Revision.objects.count(), 1); self.assertEqual(Edition.objects.count(), 1)
        self.put.assert_not_called(); self.open.assert_not_called()

    def test_exact_english_and_bengali_text_import_with_measured_unit_identity(self):
        for language in ("en", "bn"):
            with self.subTest(language=language):
                # Distinct existing identities, not destructive fixture replacement.
                source = source_packet(language)
                manifest, raw = manifest_for(source)
                manifest["work"]["slug"] += "-" + language
                manifest["edition"]["slug"] += "-" + language
                _, self.started = service.start_import(self.actor, manifest, uuid.uuid4())
                self.source, self.manifest, self.raw = source, manifest, raw
                self.revision = Revision.objects.select_related("edition").get(pk=self.started["edition_revision_id"])
                self.staged_source(); status, result = self.finalize()
                self.assertEqual(status, 200); self.assert_private()
                self.assertEqual(result["sha256"], revision_hash(self.revision))
                self.assertEqual(result["units"][0]["key"], "chapter-1")
                self.assertEqual(self.revision.units.first().duration_ms, 12000)
                self.assertEqual(list(self.revision.units.first().paragraphs.values_list("text", flat=True)),
                    [unicodedata.normalize("NFC", p["text"]) for p in source["units"][0]["paragraphs"]])
                self.assertTrue(_reader_package_coverage(self.revision, list(self.revision.assets.filter(kind="reader_package"))))
                self.assertEqual(self.objects[self.source_asset.storage_key][0], raw)

    def test_declared_nfc_derivative_retains_original_latin_and_bengali_codepoints(self):
        self.reserve(source_packet(nfd=True)); self.staged_source()
        original = self.raw
        _, result = self.finalize()
        proof = result["source_transform"]
        self.assertEqual(proof["method"], "UNICODE_NFC_READER_DERIVATIVE")
        self.assertEqual(proof["original_source_sha256"], digest(original))
        self.assertEqual(proof["normalized_paragraphs"], 3)
        self.assertEqual(proof["normalized_unit_titles"], 1)
        self.assertTrue(proof["source_unchanged"])
        self.assertEqual(self.objects[self.source_asset.storage_key][0], original)
        paragraph = self.revision.units.first().paragraphs.first()
        self.assertEqual(paragraph.text, unicodedata.normalize("NFC", self.source["units"][0]["paragraphs"][0]["text"]))
        self.assertNotEqual(paragraph.text, self.source["units"][0]["paragraphs"][0]["text"])
        self.assertTrue(_reader_package_coverage(self.revision, list(self.revision.assets.filter(kind="reader_package"))))
        self.assertEqual(self.finalize()[1]["source_transform"], proof)

    def test_large_english_source_retains_every_paragraph_and_complete_reader_coverage(self):
        self.reserve(source_packet("en", large=True)); self.assertGreater(len(self.raw), 262144)
        self.staged_source(); _, result = self.finalize()
        self.assertEqual(result["paragraph_count"], 4201)
        self.assertEqual(list(self.revision.units.first().paragraphs.values_list("text", flat=True)),
            [p["text"] for p in self.source["units"][0]["paragraphs"]])
        self.assertGreater(len(result["reader_asset_ids"]), 1)
        self.assertTrue(_reader_package_coverage(self.revision, list(self.revision.assets.filter(kind="reader_package"))))
        self.assertEqual(self.objects[self.source_asset.storage_key][0], self.raw)
        self.assert_private()

    def test_provider_unavailability_after_success_needs_no_download_or_second_package(self):
        self.reserve(); self.staged_source(); first = self.finalize()
        old_puts, old_reads = list(self.provider_puts), list(self.provider_reads)
        with patch("library.storage.read_verified", side_effect=AssertionError("no provider replay")), patch(
                "library.general_import.prepare_reader_package", side_effect=AssertionError("no package replay")):
            self.assertEqual(self.finalize(), first)
        self.assertEqual(self.provider_puts, old_puts); self.assertEqual(self.provider_reads, old_reads)
        self.assert_private()

    def test_source_hash_language_and_foreign_asset_reject_before_packages(self):
        self.reserve(); self.staged_source()
        other = get_user_model().objects.create_superuser("other-import@example.test", "Other-Import-Password47")
        with self.assertRaises(DomainError) as denied: self.finalize(actor=other)
        self.assertEqual(denied.exception.code, "import_scope_mismatch")
        with self.assertRaises(DomainError): self.finalize(data={**self.completion, "source_sha256": "0" * 64})
        with self.assertRaises(DomainError): self.finalize(data={**self.completion, "source_asset_id": str(uuid.uuid4())})
        self.objects[self.source_asset.storage_key] = (self.raw[:-1] + b" ", "application/json")
        with self.assertRaises(DomainError) as changed: self.finalize()
        self.assertEqual(changed.exception.code, "asset_integrity_failed")
        self.put.assert_not_called(); self.assertEqual(Paragraph.objects.count(), 0)

    def test_language_mismatch_rejects_valid_source_without_attaching_text(self):
        self.reserve(source_packet("bn")); self.manifest["edition"]["language"] = "en"
        # Make a distinct reservation whose actual uploaded source conflicts with its declared language.
        self.manifest["edition"]["slug"] += "-conflict"
        _, result = service.start_import(self.actor, self.manifest, uuid.uuid4())
        self.revision = Revision.objects.select_related("edition").get(pk=result["edition_revision_id"])
        self.staged_source()
        with self.assertRaises(DomainError) as error: self.finalize()
        self.assertEqual(error.exception.code, "source_language_mismatch")
        self.put.assert_not_called(); self.assertEqual(Paragraph.objects.count(), 0)

    def test_concurrent_metadata_edit_after_put_is_preserved_and_text_attach_rolls_back(self):
        self.reserve(); self.staged_source(); self.race = True
        with self.assertRaises(DomainError) as error: self.finalize()
        self.assertEqual(error.exception.code, "version_conflict")
        self.revision.refresh_from_db(); self.assertEqual(self.revision.description, "Concurrent metadata edit preserved")
        self.assertEqual(Unit.objects.count(), 0); self.assertEqual(Paragraph.objects.count(), 0)
        self.assertEqual(Asset.objects.filter(kind="reader_package").count(), 0)
        self.assertTrue(self.provider_puts, "Already-prepared private objects remain retained")

    def test_missing_asset_frozen_revision_or_changed_derivative_cannot_replay_success(self):
        self.reserve(); self.staged_source(); _, result = self.finalize()
        asset = Asset.objects.get(pk=result["reader_asset_ids"][0]); asset.delete()
        with self.assertRaises(DomainError) as missing: self.finalize()
        self.assertEqual(missing.exception.code, "import_scope_mismatch")
        Revision.objects.filter(pk=self.revision.id).update(state="ready")
        with self.assertRaises(DomainError) as frozen: self.finalize()
        self.assertEqual(frozen.exception.code, "import_scope_mismatch")
        self.assertEqual(Rights.objects.count(), 0)

    def test_conflicting_operation_or_existing_work_never_overwrites(self):
        self.reserve(); original = deepcopy(self.manifest)
        changed = deepcopy(original); changed["edition"]["title"] = "Different edition title"
        with self.assertRaises(DomainError) as reused: service.start_import(self.actor, changed, self.start_operation)
        self.assertEqual(reused.exception.code, "idempotency_key_reused")
        with self.assertRaises(DomainError) as existing: service.start_import(self.actor, original, uuid.uuid4())
        self.assertEqual(existing.exception.code, "already_imported")
        changed["edition"]["slug"] += "-different"; changed["work"]["creators"] = ["Different author"]
        with self.assertRaises(DomainError) as work: service.start_import(self.actor, changed, uuid.uuid4())
        self.assertEqual(work.exception.code, "import_identity_conflict")
        self.assertEqual(Edition.objects.count(), 1); self.assertEqual(Work.objects.count(), 1)
        self.assert_private()

    def test_exact_stale_etag_and_preparation_budget_never_attach_partial_text(self):
        self.reserve(); self.staged_source()
        with self.assertRaises(DomainError) as stale: self.finalize(version=self.version - 1)
        self.assertEqual(stale.exception.status, 412)
        self.open.assert_not_called()
        with patch("library.general_import.MAX_PREPARATION_SECONDS", 0):
            with self.assertRaises(DomainError) as timed: self.finalize()
        self.assertEqual(timed.exception.code, "import_preparation_timeout")
        self.assertEqual(Paragraph.objects.count(), 0); self.put.assert_not_called()

    def login(self):
        client = Client(enforce_csrf_checks=True)
        csrf = client.get("/api/v1/session").json()["csrf_token"]
        response = client.post("/api/v1/auth/login", json.dumps({"email": self.actor.email,
            "password": "Local-Import-Password47", "password_purpose_consent": True,
            "password_purpose_version": "password-account-v1"}), content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.content)
        return client, client.get("/api/v1/session").json()["csrf_token"]

    def test_authenticated_large_source_journey_uses_existing_direct_upload_and_strict_contract(self):
        client, csrf = self.login(); source = source_packet("bn", large=True)
        manifest, raw = manifest_for(source); self.assertGreater(len(raw), 262144)
        start_url = "/api/v1/staff/books/imports"
        self.assertEqual(client.post(start_url, json.dumps({"manifest": manifest}), content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())).status_code, 403)
        self.assertEqual(Client().post(start_url, json.dumps({"manifest": manifest}), content_type="application/json").status_code, 401)
        started = client.post(start_url, json.dumps({"manifest": manifest}), content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf, HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(started.status_code, 201, started.content)
        validate_schema(started.json(), "GeneralBookImportStartResult")
        self.revision = Revision.objects.select_related("edition").get(pk=started.json()["edition_revision_id"])
        upload_body = {"edition_revision_id": str(self.revision.id), "kind": "reader_source", "file_name": "source.json",
            "content_type": "application/json", "bytes": len(raw), "sha256": digest(raw)}
        with patch("library.storage.is_r2", return_value=True), patch("library.storage.upload_url", return_value=(
                "https://synthetic.r2.cloudflarestorage.com/private/synthetic", {"Content-Type": "application/json", "If-None-Match": "*"})):
            intent = client.post("/api/v1/staff/assets/uploads", json.dumps(upload_body), content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf, HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            self.assertEqual(intent.status_code, 201, intent.content)
            asset = Asset.objects.get(pk=intent.json()["asset_id"])
            self.objects[asset.storage_key] = (raw, "application/json")
            complete = client.post(f"/api/v1/staff/assets/{asset.id}/complete", json.dumps({"bytes": len(raw), "sha256": digest(raw)}),
                content_type="application/json", HTTP_X_CSRFTOKEN=csrf,
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()), HTTP_IF_MATCH=intent["ETag"])
            self.assertEqual(complete.status_code, 200, complete.content)
        self.revision.refresh_from_db(); version = self.revision.version
        body = {"edition_revision_id": str(self.revision.id), "source_asset_id": str(asset.id),
            "source_sha256": digest(raw), "source_bytes": len(raw)}
        key = str(uuid.uuid4()); url = f"/api/v1/staff/editions/{self.revision.edition_id}/source-imports"
        finalized = client.post(url, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=csrf,
            HTTP_IDEMPOTENCY_KEY=key, HTTP_IF_MATCH='"v' + str(version) + '"')
        self.assertEqual(finalized.status_code, 200, finalized.content)
        validate_schema(finalized.json(), "GeneralBookImportResult")
        self.assertEqual(finalized.json()["paragraph_count"], 4201)
        self.assertGreater(len(finalized.json()["reader_asset_ids"]), 1)
        self.assert_private(); self.assertEqual(self.objects[asset.storage_key][0], raw)
        self.assertEqual(self.revision.content_sha256, revision_hash(self.revision))
        self.assertTrue(_reader_package_coverage(self.revision, list(self.revision.assets.filter(kind="reader_package"))))
        replay = client.post(url, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=csrf,
            HTTP_IDEMPOTENCY_KEY=key, HTTP_IF_MATCH='"v' + str(version) + '"')
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), finalized.json())
        public = Client().get(f"/api/v1/catalog/editions/{self.revision.edition_id}")
        self.assertNotEqual(public.status_code, 200)
        self.assertGreaterEqual(self.revision.version, version + 4201)

    def test_reader_package_limit_rejects_before_any_provider_put(self):
        source = source_packet(); source["units"] = [{"key": f"u-{n}", "title": "Unit", "kind": "chapter",
            "paragraphs": [{"kind": "paragraph", "text": "source"}]} for n in range(129)]
        self.reserve(source); self.staged_source()
        with self.assertRaises(DomainError): self.finalize()
        self.put.assert_not_called(); self.assertEqual(Unit.objects.count(), 0)

    def test_request_session_authority_is_preserved_for_reservation_and_final_receipt(self):
        manifest, _ = manifest_for(source_packet())
        stale = (self.actor.session_epoch, str(uuid.uuid4()), str(uuid.uuid4()), "f" * 64)
        self.actor._maison_operation_authority = stale
        with self.assertRaises(DomainError) as start: service.start_import(self.actor, manifest, uuid.uuid4())
        self.assertEqual(start.exception.code, "authentication_required")
        self.assertEqual(Revision.objects.count(), 0)
        del self.actor._maison_operation_authority
        self.reserve(); self.staged_source()
        self.actor._maison_operation_authority = stale
        self.put.reset_mock(); self.open.reset_mock()
        with self.assertRaises(DomainError) as finish: self.finalize()
        self.assertEqual(finish.exception.code, "authentication_required")
        self.put.assert_not_called(); self.open.assert_not_called()
        self.assertEqual(Unit.objects.count(), 0)
        self.assertEqual(OperationReceipt.objects.filter(kind="book.general_import_finalize").count(), 0)

    def test_session_revoked_during_private_preparation_prevents_commit(self):
        from accounts.models import Device
        self.reserve(); self.staged_source(); self.login()
        device = Device.objects.get(user=self.actor)
        self.actor.refresh_from_db()
        self.actor._maison_operation_authority = (self.actor.session_epoch, device.pk,
            device.session_id, device.token_binding_sha256)
        def revoke(key, raw, content_type="application/json"):
            result = self.put_private(key, raw, content_type)
            Device.objects.filter(pk=device.pk).update(revoked_at=timezone.now())
            return result
        with patch("library.storage.put_private", side_effect=revoke):
            with self.assertRaises(DomainError) as error: self.finalize()
        self.assertEqual(error.exception.code, "authentication_required")
        self.assertTrue(self.provider_puts)
        self.assertEqual(Unit.objects.count(), 0); self.assertEqual(Paragraph.objects.count(), 0)
        self.assertEqual(OperationReceipt.objects.filter(kind="book.general_import_finalize").count(), 0)
