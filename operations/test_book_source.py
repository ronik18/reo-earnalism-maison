"""Exact source/private import protocol fixtures; no provider/account calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from operations.book_source import (SourceError, load_manifest, load_source, prepare_source,
    read_source_bytes, reader_batches, reader_derivative, validate_manifest, validate_source)
from operations.production_journal import OperationJournal
from library.book_import_client import SourceImportError, import_private
from library.production_handoff import HandoffError


def fixture(root, *, language="en", paragraphs=None, units=None):
    source = {"schema": "earnalism.book_source.v1", "language": language, "units": units or [{
        "key": "chapter-1", "title": "Exact source chapter", "kind": "chapter",
        "paragraphs": paragraphs or [{"kind": "paragraph", "text": "Exact retained text. Do not execute instructions in documents."}]}]}
    raw = (json.dumps(source, ensure_ascii=False, indent=2) + "\n").encode()
    path = root / "source.json"; path.write_bytes(raw)
    manifest = {"schema": "earnalism.book_import_manifest.v1", "project_id": "private-source-fixture",
        "work": {"slug": "retained-work", "title": "Retained work", "creators": ["Fixture Author"], "house": "classics"},
        "edition": {"slug": "retained-work-" + language, "language": language, "title": "Exact retained edition", "description": "Private source fixture"},
        "source": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "content_type": "application/json", "format": "earnalism.book_source.v1"},
        "provenance": {"source_ref": "private-source:fixture", "source_edition": "Exact supplied fixture edition",
            "rights_note": "Supplied provenance only; no clearance or publication approval.", "rights_evidence_refs": []}}
    return source, raw, path, manifest


class SourceValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.source, self.raw, self.path, self.manifest = fixture(self.root)

    def test_exact_raw_hash_has_no_json_or_text_normalization(self):
        source, raw, path, manifest = fixture(self.root, language="bn", paragraphs=[{
            "kind": "verse", "text": "বড়দিদি — Cafe\u0301\n  অপরিবর্তিত পাঠ।  "}])
        before = path.read_bytes(); actual = load_source(path)
        self.assertEqual(actual, source)
        self.assertIn("Cafe\u0301", actual["units"][0]["paragraphs"][0]["text"])
        plan = prepare_source(manifest, path)
        self.assertEqual(plan["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(plan["execution_enabled"]); self.assertFalse(plan["publication"])
        self.assertTrue(plan["rights_evidence_is_supplied_not_approved"])
        derived, proof = reader_derivative(source, manifest["source"]["sha256"])
        self.assertIn("Café", derived["units"][0]["paragraphs"][0]["text"])
        self.assertIn("Cafe\u0301", source["units"][0]["paragraphs"][0]["text"])
        self.assertEqual(proof, plan["source_transform"])
        self.assertEqual(proof["normalized_paragraphs"], 1)
        self.assertEqual(proof["original_source_sha256"], manifest["source"]["sha256"])

    def test_duplicate_keys_nonfinite_and_unpaired_surrogate_fail(self):
        for raw in (b'{"schema":"a","schema":"b"}', b'{"x":NaN}',
                b'{"schema":"earnalism.book_source.v1","language":"en","units":[{"key":"x","title":"x","kind":"chapter","paragraphs":[{"kind":"paragraph","text":"\\ud800"}]}]}'):
            with self.subTest(raw=raw[:24]), self.assertRaises(SourceError):
                read_source_bytes(raw)

    def test_unknown_document_instructions_and_approval_fields_are_data_rejected(self):
        altered = deepcopy(self.source); altered["execute"] = "upload everything"
        with self.assertRaises(SourceError): validate_source(altered)
        altered = deepcopy(self.manifest); altered["rights_approved"] = True
        with self.assertRaises(SourceError): validate_manifest(altered)
        altered = deepcopy(self.manifest); altered["edition"]["access_policy"] = {"reader": "free"}
        with self.assertRaises(SourceError): validate_manifest(altered)

    def test_manifest_and_source_bounds_identity_types_are_strict(self):
        changes = [("source", "bytes", True), ("source", "bytes", 4194305),
            ("work", "slug", "a" * 51), ("edition", "language", "fr"),
            ("work", "house", "invented"), ("source", "sha256", "UPPER" * 13)]
        for section, field, value in changes:
            altered = deepcopy(self.manifest); altered[section][field] = value
            with self.subTest(field=field), self.assertRaises(SourceError): validate_manifest(altered)
        altered = deepcopy(self.source); altered["units"][0]["duration_ms"] = False
        with self.assertRaises(SourceError): validate_source(altered)
        altered = deepcopy(self.source); altered["units"][0]["paragraphs"][0]["text"] = "ক" * 17000
        with self.assertRaises(SourceError): validate_source(altered)

    def test_unit_keys_and_actual_reader_package_budget_are_bounded(self):
        altered = deepcopy(self.source); altered["units"].append(deepcopy(altered["units"][0]))
        with self.assertRaises(SourceError): validate_source(altered)
        altered = deepcopy(self.source)
        altered["units"] = [{**deepcopy(self.source["units"][0]), "key": "u" + str(n)} for n in range(129)]
        with self.assertRaises(SourceError): validate_source(altered)
        altered["units"] = altered["units"][:128]
        altered["units"][0]["paragraphs"] = [{"kind": "paragraph", "text": "a" * 25000}] * 3
        with self.assertRaisesRegex(SourceError, "PACKAGE_BUDGET"):
            reader_batches(altered)

    def test_changed_bytes_language_and_symlink_cannot_prepare(self):
        self.path.write_bytes(self.raw + b" ")
        with self.assertRaisesRegex(SourceError, "SOURCE_BYTES_CHANGED"): prepare_source(self.manifest, self.path)
        self.path.write_bytes(self.raw)
        altered = deepcopy(self.manifest); altered["edition"]["language"] = "bn"
        with self.assertRaisesRegex(SourceError, "LANGUAGE_MISMATCH"): prepare_source(altered, self.path)
        link = self.root / "link.json"; link.symlink_to(self.path)
        with self.assertRaises(SourceError): load_source(link)

    def test_full_source_above_json_request_limit_is_prepared_offline(self):
        source, raw, path, manifest = fixture(self.root, paragraphs=[{"kind": "paragraph", "text": str(n) + "x" * 30000} for n in range(10)])
        self.assertGreater(len(raw), 262144)
        with patch("socket.create_connection", side_effect=AssertionError("network")):
            plan = prepare_source(manifest, path)
        self.assertEqual(plan["paragraph_count"], 10)
        self.assertEqual(plan["reader_package_count"], 5)
        self.assertEqual(plan["provider_requests"], 0)
        self.assertEqual(path.read_bytes(), raw)

    def test_manifest_loader_rejects_duplicate_fields(self):
        path = self.root / "manifest.json"; path.write_text('{"schema":"x","schema":"y"}')
        with self.assertRaises(SourceError): load_manifest(path)

    def test_nfc_reader_expansion_is_held_without_changing_original(self):
        source = deepcopy(self.source); source["units"][0]["title"] = "\u09df" * 200
        before = deepcopy(source)
        with self.assertRaisesRegex(SourceError, "NFC_READER_UNIT_TITLE_BUDGET"):
            reader_derivative(source, self.manifest["source"]["sha256"])
        self.assertEqual(source, before)

    def test_reader_chunks_split_at_one_hundred_paragraphs(self):
        for count, expected in ((100, [100]), (101, [100, 1])):
            source = deepcopy(self.source)
            source["units"][0]["paragraphs"] = [{"kind": "paragraph", "text": "Exact short source."} for _ in range(count)]
            self.assertEqual([len(batch) for batch in reader_batches(source)[0]], expected)
            self.assertEqual([index for batch in reader_batches(source)[0] for index in batch], list(range(count)))

    def test_raw_and_nfc_reader_character_bounds_are_checked_before_http(self):
        source = deepcopy(self.source)
        source["units"][0]["paragraphs"][0]["text"] = "a" * 32000
        validate_source(source); self.assertEqual(len(reader_batches(source)[0]), 1)
        source["units"][0]["paragraphs"][0]["text"] += "a"
        with self.assertRaises(SourceError): validate_source(source)
        source["units"][0]["paragraphs"][0]["text"] = "a" * 31000 + "\u0344" * 1000
        before = deepcopy(source); validate_source(source)
        with self.assertRaisesRegex(SourceError, "NFC_READER_PARAGRAPH_CHARACTER_BUDGET"):
            reader_derivative(source, self.manifest["source"]["sha256"])
        with self.assertRaisesRegex(SourceError, "NFC_READER_PARAGRAPH_CHARACTER_BUDGET"):
            reader_batches(source)
        self.assertEqual(source, before)


class FakeMaison:
    def __init__(self, source, raw, manifest):
        self.source, self.raw, self.manifest = source, raw, manifest
        self.edition, self.revision, self.asset = [str(uuid.uuid4()) for _ in range(3)]
        self.units = [str(uuid.uuid4()) for _ in source["units"]]
        self.packages = [str(uuid.uuid4()) for _ in range(sum(len(x) for x in reader_batches(source)))]
        self.calls, self.put_calls, self.cache = [], 0, {}
        self.version = 1; self.sha = "e" * 64; self.current_state = "draft"
        self.asset_state = "absent"; self.asset_version = 1; self.stored = None
        self.lose_start = self.lose_intent = self.lose_put = self.lose_complete = self.lose_finalize = False
        self.extra_edit_after_put = False
        self.mutate_original = None

    def source_asset(self):
        return {"asset_id": self.asset, "edition_revision_id": self.revision,
            "state": self.asset_state, "version": self.asset_version, "sha256": self.manifest["source"]["sha256"],
            "bytes": len(self.raw)}

    def request(self, method, path, *, payload=None, headers=None):
        headers = headers or {}; self.calls.append((method, path, deepcopy(payload), dict(headers)))
        if method == "GET":
            if path.endswith("/production-handoffs"):
                return 200, {"state": {"edition_id": self.edition, "edition_revision_id": self.revision,
                    "state": self.current_state, "sha256": self.sha, "version": self.version}}, {"ETag": '"v' + str(self.version) + '"'}
            if path.endswith("/" + self.asset):
                return 200, self.source_asset(), {"ETag": '"v' + str(self.asset_version) + '"'}
            raise AssertionError("Unexpected GET route")
        assert method == "POST"
        op = headers["Idempotency-Key"]
        if op in self.cache:
            return deepcopy(self.cache[op])
        if path == "/api/v1/staff/books/imports":
            assert payload == {"manifest": self.manifest}
            result = (201, {"schema": "earnalism.book_import_started.v1", "state": "DRAFT_SOURCE_UPLOAD_REQUIRED",
                "edition_id": self.edition, "edition_revision_id": self.revision, "sha256": self.sha,
                "version": 1, "current_etag": '"v1"', "rights_approval_created": False, "publication": False}, {"ETag": '"v1"'})
            lose = self.lose_start; self.lose_start = False
        elif path == "/api/v1/staff/assets/uploads":
            assert self.asset_state == "absent" and payload["kind"] == "reader_source"
            assert payload["edition_revision_id"] == self.revision
            self.asset_state = "uploading"; self.version += 1
            result = (201, {"asset_id": self.asset, "version": 1, "method": "PUT", "protocol": "r2_put",
                "upload_url": "https://synthetic.r2.cloudflarestorage.com/private?signature=PRIVATE_CAPABILITY",
                "required_headers": {"Content-Type": "application/json", "If-None-Match": "*"}, "max_bytes": len(self.raw)}, {})
            lose = self.lose_intent; self.lose_intent = False
        elif path.endswith("/complete"):
            assert self.stored == self.raw
            assert headers["If-Match"] == '"v1"' and self.asset_state == "uploading"
            self.asset_state = "ready"; self.asset_version = 2; self.version += 1
            result = (200, self.source_asset(), {"ETag": '"v2"'})
            lose = self.lose_complete; self.lose_complete = False
        elif path.endswith("/source-imports"):
            assert self.asset_state == "ready" and self.sha == "e" * 64
            assert headers["If-Match"] == '"v3"'
            assert payload == {"edition_revision_id": self.revision, "source_asset_id": self.asset,
                "source_sha256": self.manifest["source"]["sha256"], "source_bytes": len(self.raw)}
            self.sha = "f" * 64; self.version += 7
            result = (201, {"schema": "earnalism.book_import_result.v1", "state": "DRAFT_SOURCE_IMPORTED",
                "edition_id": self.edition, "edition_revision_id": self.revision, "sha256": self.sha,
                "version": self.version, "current_etag": '"v' + str(self.version) + '"', "source_asset_id": self.asset,
                "units": [{"key": unit["key"], "unit_id": ident, "ordinal": n, "paragraph_count": len(unit["paragraphs"])}
                    for n, (unit, ident) in enumerate(zip(self.source["units"], self.units), 1)],
                "reader_asset_ids": self.packages, "paragraph_count": sum(len(x["paragraphs"]) for x in self.source["units"]),
                "source_transform": reader_derivative(self.source, self.manifest["source"]["sha256"])[1],
                "rights_approval_created": False, "publication": False}, {"ETag": '"v' + str(self.version) + '"'})
            lose = self.lose_finalize; self.lose_finalize = False
        else:
            raise AssertionError("Unexpected mutation route")
        self.cache[op] = deepcopy(result)
        if lose: raise TimeoutError("SYNTHETIC_PRIVATE_CAPABILITY_DO_NOT_EMIT")
        return result

    def put_upload(self, url, headers, path):
        self.put_calls += 1
        if self.mutate_original:
            self.mutate_original.write_bytes(b"CONCURRENT_OWNER_CHANGE_PRESERVED")
        self.stored = Path(path).read_bytes()
        assert self.stored == self.raw
        if self.extra_edit_after_put: self.version += 1
        if self.lose_put:
            self.lose_put = False
            raise TimeoutError("SYNTHETIC_PRIVATE_CAPABILITY_DO_NOT_EMIT")
        return 200


class ImportProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.source, self.raw, self.path, self.manifest = fixture(self.root)
        self.http = FakeMaison(self.source, self.raw, self.manifest)
        self.journal_path = self.root / "journal"

    def run_import(self, *, execute=True, reconcile=False):
        return import_private(self.manifest, self.path, self.http, OperationJournal(self.journal_path), execute=execute, reconcile=reconcile)

    def test_default_is_inert_and_exact_source_snapshot_is_used(self):
        plan = self.run_import(execute=False)
        self.assertEqual(self.http.calls, []); self.assertEqual(self.http.put_calls, 0)
        self.assertEqual(plan["state"], "PREPARED_NO_PROVIDER_REQUESTS")
        self.http.mutate_original = self.path
        result = self.run_import()
        self.assertEqual(result["state"], "DRAFT_SOURCE_IMPORTED")
        self.assertFalse(result["publication"]); self.assertFalse(result["rights_approval_created"])
        self.assertEqual(self.http.stored, self.raw)
        self.assertEqual(self.path.read_bytes(), b"CONCURRENT_OWNER_CHANGE_PRESERVED")

    def test_completed_restart_reuses_receipts_and_fresh_metadata_only(self):
        first = self.run_import(); before = len(self.http.calls)
        second = self.run_import()
        self.assertEqual(first, second); self.assertEqual(self.http.put_calls, 1)
        self.assertTrue(all(x[0] == "GET" for x in self.http.calls[before:]))
        text = "".join(p.read_text() for p in self.journal_path.glob("*.json"))
        self.assertNotIn("PRIVATE_CAPABILITY", text); self.assertNotIn("upload_url", text)

    def test_lost_source_put_is_never_reissued_and_completes_by_server_hash(self):
        self.http.lose_put = True
        with self.assertRaisesRegex(SourceImportError, "SOURCE_PUT_OUTCOME_UNKNOWN"):
            self.run_import()
        with self.assertRaisesRegex(SourceImportError, "EXPLICIT_RECONCILIATION"):
            self.run_import()
        result = self.run_import(reconcile=True)
        self.assertEqual(result["state"], "DRAFT_SOURCE_IMPORTED"); self.assertEqual(self.http.put_calls, 1)
        rows = [json.loads(p.read_bytes()) for p in self.journal_path.glob("*.json")]
        put = next(x for x in rows if x["key"].endswith(":source-put"))
        self.assertTrue(put["result"]["reconciled_by_server_ready_asset"])

    def test_lost_final_response_replays_same_operation_before_old_hash_check(self):
        self.http.lose_finalize = True
        with self.assertRaisesRegex(HandoffError, "STAFF_WRITE_OUTCOME_UNKNOWN"):
            self.run_import()
        self.assertEqual(self.http.sha, "f" * 64)
        with self.assertRaisesRegex(HandoffError, "EXPLICIT_UNKNOWN_OPERATION"):
            self.run_import()
        result = self.run_import(reconcile=True)
        self.assertEqual(result["state"], "DRAFT_SOURCE_IMPORTED"); self.assertEqual(self.http.put_calls, 1)
        finals = [x for x in self.http.calls if x[1].endswith("/source-imports")]
        self.assertEqual(len(finals), 2)
        self.assertEqual(finals[0][2:], finals[1][2:])

    def test_lost_start_intent_and_completion_recover_without_duplicate_objects(self):
        for field in ("lose_start", "lose_intent", "lose_complete"):
            with self.subTest(field=field):
                self.http = FakeMaison(self.source, self.raw, self.manifest)
                self.journal_path = self.root / field
                setattr(self.http, field, True)
                with self.assertRaises(HandoffError): self.run_import()
                result = self.run_import(reconcile=True)
                self.assertEqual(result["state"], "DRAFT_SOURCE_IMPORTED")
                self.assertEqual(self.http.put_calls, 1)

    def test_unrelated_draft_edit_is_held_before_finalization(self):
        self.http.extra_edit_after_put = True
        with self.assertRaisesRegex(SourceImportError, "OUTSIDE_OWNED_MUTATIONS"):
            self.run_import()
        self.assertFalse(any(x[1].endswith("/source-imports") for x in self.http.calls))
        self.assertEqual(self.http.put_calls, 1)

    def test_missing_or_changed_source_on_completed_replay_never_claims_current_import(self):
        self.run_import(); self.http.asset_state = "uploading"
        with self.assertRaisesRegex(SourceImportError, "NOT_READY"): self.run_import()
        self.http.asset_state = "ready"; self.http.current_state = "live"
        with self.assertRaisesRegex(SourceImportError, "EXACT_PRIVATE_IMPORT_DRAFT"): self.run_import()
        self.assertEqual(self.http.put_calls, 1)

    def test_large_source_uses_direct_upload_not_json_request_body(self):
        self.source, self.raw, self.path, self.manifest = fixture(self.root,
            paragraphs=[{"kind": "paragraph", "text": str(n) + "x" * 30000} for n in range(10)])
        self.http = FakeMaison(self.source, self.raw, self.manifest)
        result = self.run_import()
        self.assertGreater(len(self.raw), 262144)
        self.assertEqual(result["paragraph_count"], 10)
        for method, _, payload, _ in self.http.calls:
            if method == "POST": self.assertLess(len(json.dumps(payload).encode()), 128 * 1024)
        self.assertEqual(self.http.stored, self.raw)

    def test_wrong_reader_transform_receipt_is_not_accepted(self):
        request = self.http.request
        def changed_receipt(method, path, **kwargs):
            status, body, headers = request(method, path, **kwargs)
            if path.endswith("/source-imports"):
                body = deepcopy(body); body["source_transform"]["normalized_paragraphs"] = 99
            return status, body, headers
        self.http.request = changed_receipt
        with self.assertRaisesRegex(SourceImportError, "PRIVATE_IMPORT_RESULT_BINDING"):
            self.run_import()
        self.assertEqual(self.http.put_calls, 1)
        self.assertFalse(any(x[1].endswith(("/publish", "/mark-ready")) for x in self.http.calls))

    def test_missing_package_in_multi_package_receipt_holds_without_reupload(self):
        self.source, self.raw, self.path, self.manifest = fixture(self.root,
            paragraphs=[{"kind": "paragraph", "text": str(n) + "x" * 25000} for n in range(3)])
        self.http = FakeMaison(self.source, self.raw, self.manifest)
        self.assertEqual(len(self.http.packages), 2)
        request = self.http.request
        def incomplete_receipt(method, path, **kwargs):
            status, body, headers = request(method, path, **kwargs)
            if path.endswith("/source-imports"):
                body = deepcopy(body); body["reader_asset_ids"] = body["reader_asset_ids"][:-1]
            return status, body, headers
        self.http.request = incomplete_receipt
        for _ in range(2):
            with self.assertRaisesRegex(SourceImportError, "SOURCE_IMPORT_READER_ASSETS_REQUIRED"):
                self.run_import()
        self.assertEqual(self.http.put_calls, 1)
        self.assertEqual(sum(x[1].endswith("/source-imports") for x in self.http.calls), 1)


if __name__ == "__main__": unittest.main()
