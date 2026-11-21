"""Pure stdlib client for source-bound private draft import. Never publishes."""
import hashlib
from pathlib import Path
import tempfile
import time
import uuid

from operations.book_source import prepare_source, source_snapshot, SourceError
from .production_handoff import HandoffError, _call, _get, _version, fingerprint


class SourceImportError(HandoffError):
    pass


def _uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise SourceImportError("IMPORT_UUID4_REQUIRED") from None
    if parsed.version != 4 or str(parsed) != value:
        raise SourceImportError("IMPORT_UUID4_REQUIRED")
    return value


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise SourceImportError("IMPORT_SHA256_REQUIRED")
    return value


def import_private(manifest, source_path, transport, journal, *, execute=False, reconcile=False):
    """Use existing staff JSON/R2 operations and one same-operation journal.

    Default preparation has no HTTP. An unknown PUT is never reissued. An unknown
    finalize is replayed before checking its now-changed draft hash. This is exact
    source intake, not clearance, narration, adaptation or release acceptance.
    """
    plan = prepare_source(manifest, source_path)
    if not execute:
        return plan
    raw, source = source_snapshot(source_path)
    if len(raw) != plan["source_bytes"] or hashlib.sha256(raw).hexdigest() != plan["source_sha256"]:
        raise SourceError("SOURCE_BYTES_CHANGED")
    prefix = "book-import:" + plan["manifest_sha256"] + ":"
    scope_key = prefix + "scope"
    scope = journal.read(scope_key)
    if scope is None:
        journal.begin(scope_key, fingerprint({"manifest": plan["manifest_sha256"]}))
        scope = journal.read(scope_key)
    if scope["state"] != "acknowledged":
        journal.acknowledge(scope_key, {"started_epoch": scope["started_epoch"]})
        scope = journal.read(scope_key)
    if time.time() - scope["result"]["started_epoch"] > 30 * 86400:
        raise SourceImportError("IMPORT_JOURNAL_EXCEEDS_SERVER_RECEIPT_WINDOW")

    started = _call(transport, journal, prefix + "start", "/api/v1/staff/books/imports",
        {"manifest": manifest}, reconcile=reconcile)["data"]
    if (started.get("schema") != "earnalism.book_import_started.v1"
            or started.get("state") != "DRAFT_SOURCE_UPLOAD_REQUIRED"
            or started.get("rights_approval_created") is not False or started.get("publication") is not False
            or type(started.get("version")) is not int or started["version"] < 1
            or _version(started.get("current_etag")) != started["version"]):
        raise SourceImportError("PRIVATE_IMPORT_START_BINDING_REQUIRED")
    edition = _uuid(started.get("edition_id")); revision = _uuid(started.get("edition_revision_id"))
    empty_hash = _hash(started.get("sha256"))
    identity_route = "/api/v1/staff/editions/" + edition + "/production-handoffs"
    final_route = "/api/v1/staff/editions/" + edition + "/source-imports"
    intent_key, put_key, complete_key, final_key = [prefix + x for x in ("source-intent", "source-put", "source-complete", "finalize")]

    def identity():
        value, headers = _get(transport, identity_route)
        state = value.get("state", {})
        if (state.get("edition_id") != edition or state.get("edition_revision_id") != revision or state.get("state") != "draft"):
            raise SourceImportError("EXACT_PRIVATE_IMPORT_DRAFT_REQUIRED")
        return state, headers

    def expected_source_etag():
        return '"v' + str(started["version"] + 2) + '"'

    def draft(*, exact=True):
        state, headers = identity()
        if state.get("sha256") != empty_hash:
            raise SourceImportError("SOURCE_IMPORT_DRAFT_CONTENT_CHANGED")
        known = pending = 0
        for key in (intent_key, complete_key):
            row = journal.read(key)
            if row and row["state"] == "acknowledged":
                if 200 <= row["result"]["status"] < 300:
                    known += 1
            elif row:
                pending += 1
        actual, expected = _version(headers.get("ETag")), started["version"] + known
        if not expected <= actual <= expected + (0 if exact else pending):
            raise SourceImportError("SOURCE_IMPORT_DRAFT_CHANGED_OUTSIDE_OWNED_MUTATIONS")
        return headers["ETag"]

    def source_asset(asset_id):
        asset, headers = _get(transport, "/api/v1/staff/assets/" + _uuid(asset_id))
        if (asset.get("asset_id") != asset_id or asset.get("edition_revision_id") != revision
                or asset.get("sha256") != plan["source_sha256"] or asset.get("bytes") != len(raw)
                or asset.get("state") not in {"uploading", "ready"}):
            raise SourceImportError("EXACT_REVISION_SOURCE_ASSET_REQUIRED")
        return asset, headers

    def finish(asset_id):
        body = {"edition_revision_id": revision, "source_asset_id": asset_id,
            "source_sha256": plan["source_sha256"], "source_bytes": len(raw)}
        result = _call(transport, journal, final_key, final_route, body,
            etag=expected_source_etag(), reconcile=reconcile)["data"]
        if (result.get("schema") != "earnalism.book_import_result.v1"
                or result.get("state") != "DRAFT_SOURCE_IMPORTED"
                or result.get("edition_id") != edition or result.get("edition_revision_id") != revision
                or result.get("source_asset_id") != asset_id
                or result.get("rights_approval_created") is not False or result.get("publication") is not False
                or type(result.get("version")) is not int
                or _version(result.get("current_etag")) != result["version"]
                or result.get("paragraph_count") != plan["paragraph_count"]
                or result.get("source_transform") != plan["source_transform"]):
            raise SourceImportError("PRIVATE_IMPORT_RESULT_BINDING_REQUIRED")
        _hash(result.get("sha256"))
        units = result.get("units")
        if not isinstance(units, list) or len(units) != len(source["units"]):
            raise SourceImportError("SOURCE_IMPORT_UNIT_MAP_REQUIRED")
        identifiers = set()
        for n, (unit, wanted) in enumerate(zip(units, source["units"]), 1):
            if (unit.get("key") != wanted["key"] or unit.get("ordinal") != n
                    or unit.get("paragraph_count") != len(wanted["paragraphs"])):
                raise SourceImportError("SOURCE_IMPORT_UNIT_MAP_REQUIRED")
            ident = _uuid(unit.get("unit_id"))
            if ident in identifiers:
                raise SourceImportError("SOURCE_IMPORT_UNIT_MAP_REQUIRED")
            identifiers.add(ident)
        assets = result.get("reader_asset_ids")
        if not isinstance(assets, list) or len(assets) != plan["reader_package_count"]:
            raise SourceImportError("SOURCE_IMPORT_READER_ASSETS_REQUIRED")
        if len({_uuid(ident) for ident in assets}) != len(assets):
            raise SourceImportError("SOURCE_IMPORT_READER_ASSETS_REQUIRED")
        current, headers = identity()
        if current.get("sha256") != result["sha256"] or headers.get("ETag") != result["current_etag"]:
            raise SourceImportError("IMPORTED_DRAFT_CHANGED_REVIEW_CURRENT_STATE")
        asset, _ = source_asset(asset_id)
        if asset["state"] != "ready":
            raise SourceImportError("IMPORTED_SOURCE_ASSET_NOT_READY")
        return {**result, "manifest_sha256": plan["manifest_sha256"], "source_sha256": plan["source_sha256"],
            "source_bytes": len(raw), "model_calls": 0, "quality_acceptance_supplied_by_importer": False}

    # A lost final ACK may already have created content and changed the ETag/hash.
    # Resolve that same operation first; no source PUT or new finalization follows.
    if journal.read(final_key) is not None:
        row = journal.read(intent_key)
        if not row or row["state"] != "acknowledged" or not 200 <= row["result"]["status"] < 300:
            raise SourceImportError("FINAL_IMPORT_SOURCE_INTENT_RECEIPT_REQUIRED")
        return finish(row["result"]["data"]["asset_id"])

    draft(exact=False)
    upload_body = {"edition_revision_id": revision, "kind": "reader_source", "file_name": "book-source.json",
        "content_type": "application/json", "bytes": len(raw), "sha256": plan["source_sha256"]}
    intent = _call(transport, journal, intent_key, "/api/v1/staff/assets/uploads", upload_body,
        reconcile=reconcile)["data"]
    asset_id = _uuid(intent.get("asset_id"))
    if (intent.get("method") != "PUT" or intent.get("protocol") not in {"r2_put", "local_put"}
            or intent.get("max_bytes") != len(raw) or intent.get("version") != 1):
        raise SourceImportError("BOUNDED_SOURCE_UPLOAD_GRANT_REQUIRED")
    asset, _ = source_asset(asset_id)
    put = journal.read(put_key)
    if asset["state"] == "uploading":
        draft(exact=False)
        if put is not None and put["state"] != "acknowledged" and not reconcile:
            raise SourceImportError("UNKNOWN_SOURCE_PUT_REQUIRES_EXPLICIT_RECONCILIATION_NO_REPLAY")
        if put is None:
            if "upload_url" not in intent:
                # Recover only the already acknowledged original intent; this
                # cannot renew an expired capability or create a second asset.
                op = str(uuid.UUID(hex=hashlib.sha256(intent_key.encode()).hexdigest()[:32], version=4))
                status, recovered, _ = transport.request("POST", "/api/v1/staff/assets/uploads", payload=upload_body,
                    headers={"Idempotency-Key": op})
                if status != 201 or recovered.get("asset_id") != asset_id:
                    raise SourceImportError("EXISTING_SOURCE_UPLOAD_GRANT_NOT_RECOVERED")
                intent = recovered
            journal.begin(put_key, fingerprint(upload_body))
            try:
                # Upload a private snapshot of already-validated bytes, not a
                # path that could change while the network transfer runs.
                with tempfile.TemporaryDirectory(prefix="earnalism-source-") as directory:
                    snapshot = Path(directory) / "source.json"
                    with snapshot.open("xb") as stream:
                        stream.write(raw)
                    snapshot.chmod(0o600)
                    status = transport.put_upload(intent["upload_url"], intent["required_headers"], snapshot)
                if not 200 <= status < 300:
                    raise SourceImportError("SOURCE_PUT_NOT_ACKNOWLEDGED")
            except Exception:
                journal.unknown(put_key, "SOURCE_PUT_OUTCOME_UNKNOWN_NO_REPLAY")
                raise SourceImportError("SOURCE_PUT_OUTCOME_UNKNOWN_NO_REPLAY") from None
            journal.acknowledge(put_key, {"accepted": True})
        _call(transport, journal, complete_key, "/api/v1/staff/assets/" + asset_id + "/complete",
            {"bytes": len(raw), "sha256": plan["source_sha256"]}, etag='"v1"', reconcile=reconcile)
        asset, _ = source_asset(asset_id)
    else:
        completion = journal.read(complete_key)
        if completion and completion["state"] != "acknowledged":
            _call(transport, journal, complete_key, "/api/v1/staff/assets/" + asset_id + "/complete",
                {"bytes": len(raw), "sha256": plan["source_sha256"]}, etag='"v1"', reconcile=reconcile)
    if asset["state"] != "ready":
        raise SourceImportError("SOURCE_ASSET_NOT_SERVER_VERIFIED")
    if put and put["state"] != "acknowledged":
        journal.acknowledge(put_key, {"accepted": True, "reconciled_by_server_ready_asset": True})
    if draft() != expected_source_etag():
        raise SourceImportError("EXACT_SOURCE_IMPORT_ETAG_REQUIRED")
    return finish(asset_id)
