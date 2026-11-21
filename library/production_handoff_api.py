"""Bounded authenticated attachment of already-staged private production assets."""
import hashlib
import io
from pathlib import Path
import tempfile
import time

from django.core.management import call_command
from core.api import DomainError, api_response, expected_version, json_endpoint, operation_key
from core.models import OperationReceipt
from core.services import apply_operation
from operations.production_bundle import BundleError, validate_manifest
from .intake_api import staff_permission
from .models import Asset, Revision
from .validation import body
from . import storage
from .production_handoff import _attach_verified, _handoff_plan, fingerprint, HandoffError, MAX_STAGED_R2_BYTES, measure_mp3

MAX_PREPARATION_BYTES = MAX_STAGED_R2_BYTES
PREPARATION_SECONDS = 20


def _copy_owned(asset, destination, deadline):
    """Read only a DB-owned locator. Bound every chunk; verify exact bytes/hash."""
    source, size, mime = storage._open(asset.storage_key)
    count, digest = 0, hashlib.sha256()
    try:
        if size != asset.bytes or mime and mime.split(";")[0] != asset.content_type:
            raise DomainError("asset_integrity_failed", "Staged object differs from its intent.", 422)
        with destination.open("xb") as target:
            while count < asset.bytes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DomainError("processing_budget_exceeded", "Private preparation requires a later bounded reconciliation.", 503)
                if hasattr(source, "set_socket_timeout"):
                    source.set_socket_timeout(max(.1, min(3, remaining)))
                block = source.read(min(1024 * 1024, asset.bytes - count))
                if not block:
                    break
                if count + len(block) > asset.bytes:
                    raise DomainError("asset_integrity_failed", "Staged source exceeds declared bytes.", 422)
                count += len(block); digest.update(block); target.write(block)
    except DomainError:
        raise
    except Exception:
        raise DomainError("storage_unavailable", "Private staged-object transfer was interrupted.", 503) from None
    finally:
        source.close()
    if count != asset.bytes or digest.hexdigest() != asset.sha256:
        raise DomainError("asset_integrity_failed", "Staged source failed exact byte verification.", 422)


def _prepare(request, manifest, staged, plan, etag, operation):
    content, digest = manifest["content"], plan["bundle_sha256"]
    payload = {"bundle_sha256": digest, "staging_receipt_sha256": fingerprint(staged), "expected_etag": etag}
    revision = Revision.objects.filter(pk=content["revision_id"], edition_id=content["edition_id"]).first()
    if not revision or revision.state != "draft" or revision.content_sha256 != content["text_sha256"]:
        raise DomainError("revision_frozen", "Reconciliation requires the same current private draft/hash.", 409)
    old = OperationReceipt.objects.filter(actor=request.user, operation_id=operation).first()
    if old:
        def no_second_attachment():
            raise DomainError("operation_reconciliation_required", "Reconcile this same private attachment.", 409)
        _, result = apply_operation(request.user, operation, "content.production_handoff", payload, no_second_attachment)
        return result
    if revision.version != int(etag[2:-1]):
        raise DomainError("version_conflict", "Exact current draft/ETag/hash required.", 412)
    if (staged.get("schema") != "earnalism.maison_private_handoff.v1" or staged.get("bundle_sha256") != digest
        or staged.get("revision_id") != content["revision_id"] or staged.get("edition_id") != content["edition_id"]
        or staged.get("text_sha256") != content["text_sha256"]):
        raise DomainError("asset_integrity_failed", "Staging receipt must bind this production bundle.", 409)
    if set(staged.get("assets", {})) != {x["id"] for x in plan["uploads"]}:
        raise DomainError("asset_integrity_failed", "Exact staged asset set required.", 409)
    if sum(x["body"]["bytes"] for x in plan["uploads"] if x["body"]["kind"] != "video") > MAX_PREPARATION_BYTES:
        raise DomainError("preparation_limit", "Split source-bound units into bundles of at most64MiB staged bytes.", 413)
    deadline = time.monotonic() + PREPARATION_SECONDS
    with tempfile.TemporaryDirectory(prefix="maison-production-") as directory:
        root = Path(directory).resolve()
        for item in plan["uploads"]:
            body, receipt = item["body"], staged.get("assets", {}).get(item["id"], {})
            asset = Asset.objects.filter(pk=receipt.get("asset_id"), revision=revision).first()
            if (not asset or asset.sha256 != body["sha256"] or asset.bytes != body["bytes"]
                or receipt.get("sha256") != body["sha256"] or receipt.get("bytes") != body["bytes"]
                or receipt.get("edition_revision_id") != content["revision_id"]
                or asset.content_type != body["content_type"] or asset.provider != ("stream" if body["kind"] == "video" else "r2")
                or asset.kind != ("audio_chapter" if body["kind"] == "audio" else body["kind"])
                or str(asset.unit_id) != str(body.get("unit_id"))
                or asset.state not in ({"processing", "ready"} if body["kind"] in {"audio", "video"} else {"ready"})):
                raise DomainError("asset_integrity_failed", "Only exact revision-owned completed assets may attach.", 409)
            if body["kind"] == "video":
                if asset.duration_ms != body["duration_ms"] or not asset.unit_id:
                    raise DomainError("asset_integrity_failed", "Exact Stream unit and source duration required.", 409)
                continue
            destination = root / item["path"]
            if not destination.resolve().is_relative_to(root):
                raise DomainError("invalid_asset_path", "Contained staged paths required.", 422)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_owned(asset, destination, deadline)
        def measure(path):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DomainError("processing_budget_exceeded", "Private preparation exceeded its bounded request.", 503)
            return measure_mp3(path, timeout_seconds=min(5, remaining))
        return _attach_verified(manifest, root, staged, request.user, etag, operation, plan=plan, measure=measure,
            source_scope="SERVER_VERIFIED_STAGED_ASSETS_NATIVE_WAV_PROVENANCE_REFERENCE_ONLY")


@json_endpoint(("GET", "POST"))
def production_handoffs(request, edition_id):
    staff_permission(request.user)
    if request.method == "GET":
        revision = Revision.objects.filter(edition_id=edition_id, state="draft").order_by("-created_at").first()
        if revision is None:
            raise DomainError("not_found", "A private draft revision is required.", 404)
        return api_response({"state": {"edition_id": str(revision.edition_id), "edition_revision_id": str(revision.id),
            "state": revision.state, "sha256": revision.content_sha256, "version": revision.version}}, version=revision.version)
    data = body(request, "ProductionHandoffInput")
    version, operation = expected_version(request), operation_key(request)
    manifest, staged = data["manifest"], data["staging_receipt"]
    if not isinstance(staged, dict) or not isinstance(staged.get("assets"), dict):
        raise DomainError("invalid_production_bundle", "A bounded staging receipt object is required.", 422)
    try:
        digest = validate_manifest(manifest)
        plan = _handoff_plan(manifest, digest)
        if manifest["content"]["edition_id"] != str(edition_id):
            raise DomainError("edition_revision_mismatch", "URL and exact draft edition must match.", 409)
        result = _prepare(request, manifest, staged, plan, '"v' + str(version) + '"', operation)
    except (BundleError, HandoffError, ValueError, KeyError, TypeError):
        raise DomainError("invalid_production_bundle", "Use exact private bundle/staging evidence and supported measured assets.", 422) from None
    # Existing immutable provider piece preparation runs outside all DB locks.
    # On replay ready assets are skipped; processing IDs remain explicit.
    deadline = time.monotonic() + 8
    for asset_id in result.get("verify_media_asset_ids", []):
        asset = Asset.objects.filter(pk=asset_id, revision_id=manifest["content"]["revision_id"]).first()
        if asset and asset.state == "processing" and time.monotonic() < deadline:
            try:
                call_command("verify_media_asset", asset_id, max_seconds=max(1, min(5, int(deadline - time.monotonic()))), stdout=io.StringIO())
            except Exception:
                pass  # Provider errors never become readiness; fresh state below is authoritative.
    expected_ids = [x["asset_id"] for x in staged["assets"].values()]
    if len(set(expected_ids)) != len(expected_ids):
        raise DomainError("asset_integrity_failed", "Distinct exact staged asset identities required.", 409)
    current = Asset.objects.filter(pk__in=expected_ids, revision_id=manifest["content"]["revision_id"])
    snapshot = {str(x.id): {"state": x.state, "version": x.version, "sha256": x.sha256} for x in current}
    if set(snapshot) != set(expected_ids):
        raise DomainError("asset_integrity_failed", "A staged asset is missing; preserve evidence and reconcile.", 409)
    verified = [key for key, value in snapshot.items() if value["state"] == "ready"]
    pending = [key for key, value in snapshot.items() if value["state"] != "ready"]
    revision = Revision.objects.get(pk=manifest["content"]["revision_id"])
    if revision.state != "draft" or str(revision.edition_id) != manifest["content"]["edition_id"] or revision.content_sha256 != manifest["content"]["text_sha256"]:
        raise DomainError("revision_frozen", "The exact private draft changed during processing.", 409)
    complete = not pending
    return api_response({"schema": "earnalism.maison_private_attachment_rpc.v1", "attachment": result,
        "state": "DRAFT_PRIVATE_HANDOFF_TECHNICALLY_COMPLETE" if complete else "DRAFT_PRIVATE_MEDIA_PROCESSING",
        "verified_asset_ids": verified, "processing_asset_ids": pending, "asset_snapshot": snapshot,
        "stream_source_scope": "SOURCE_UPLOAD_SHA_AND_PRIVATE_PROVIDER_UID_BINDING_NOT_RENDITION_BYTE_HASH",
        "native_wav_scope": "PROVENANCE_REFERENCE_ONLY_NOT_SERVER_BYTE_VERIFIED",
        "source_byte_verification_scope": "EXACT_STAGED_SUBSET_ONLY", "current_etag": '"v' + str(revision.version) + '"',
        "release_ready": False, "publication": False}, 200 if complete else 202, version=revision.version)
