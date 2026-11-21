"""General English/Bengali source intake using existing denied drafts and assets.

The metadata reservation is a DB-only operation. Source reads and deterministic
Reader-package preparation occur before the short final receipt transaction.
No source or rights reference creates a Rights approval or publishes content.
"""
import gzip
import json
import time
import unicodedata
import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from core.api import DomainError, public_uuid
from core.models import OperationReceipt
from core.services import apply_operation, audit, locked_actor
from operations.book_source import SourceError, read_source_bytes, reader_batches, validate_manifest
from .intake_api import staff_permission
from .models import Asset, Edition, Paragraph, Revision, Unit, Work
from .services import canonical_bytes, digest, paragraph_dto, prepare_reader_package, revision_hash
from . import storage

EVIDENCE_KEY = "general_source_import"
IMPORT_SCHEMA = "earnalism.general_source_import_binding.v1"
DENIED = {"reader": "deny", "audio": "deny", "video": "deny"}
NO_DOWNLOADS = {"reader": False, "audio": False, "video": False}
EMPTY_SHA = digest(canonical_bytes([]))
MAX_PREPARATION_SECONDS = 20
MAX_PACKAGES = 128


def _publisher(actor):
    actor = get_user_model().objects.get(pk=actor.pk)
    staff_permission(actor)
    if not actor.is_verified:
        raise DomainError("email_verification_required", "A verified publisher is required.", 403)
    return actor


def _admit_preparation(actor):
    """Check current request authority briefly; release locks before storage I/O."""
    with transaction.atomic():
        _publisher(locked_actor(actor))


def _identifier(actor_public_id, operation, manifest_sha, label):
    raw = digest(canonical_bytes([str(actor_public_id), str(operation), manifest_sha, label]))
    return uuid.UUID(hex=raw[:32], version=4)


def _etag(revision):
    return '"v' + str(revision.version) + '"'


def _manifest(manifest):
    try:
        return validate_manifest(manifest)
    except (SourceError, TypeError, ValueError, KeyError):
        raise DomainError("invalid_book_source", "Use an exact bounded source-import manifest.", 422) from None


def _binding(revision, actor):
    record = revision.validation_evidence.get(EVIDENCE_KEY, {}) if isinstance(revision.validation_evidence, dict) else {}
    if (not isinstance(record, dict) or record.get("schema") != IMPORT_SCHEMA or record.get("actor_public_id") != str(actor.public_id)
            or revision.state != "draft"):
        raise DomainError("import_scope_mismatch", "Select this publisher's existing private import draft.", 409)
    manifest = record.get("manifest")
    if _manifest(manifest) != record.get("manifest_sha256"):
        raise DomainError("import_scope_mismatch", "The retained source manifest has changed.", 409)
    work, edition = manifest["work"], manifest["edition"]
    if (revision.edition.slug != edition["slug"] or revision.edition.locale != edition["language"]
            or revision.title != edition["title"] or revision.description != edition["description"]
            or revision.edition.work.slug != work["slug"] or revision.edition.work.title != work["title"]
            or revision.edition.work.creators != work["creators"] or revision.edition.work.house != work["house"]
            or revision.edition.live_revision_id is not None):
        raise DomainError("import_scope_mismatch", "The exact draft/work identity changed.", 409)
    return record


def _revision(edition_id, revision_id, actor):
    revision = Revision.objects.select_related("edition", "edition__work").filter(
        pk=revision_id, edition_id=edition_id).first()
    if revision is None:
        raise DomainError("not_found", "Private import draft not found.", 404)
    _binding(revision, actor)
    return revision


def _source_asset(revision, record, source_id, source_sha, source_bytes):
    declared = record["manifest"]["source"]
    if source_sha != declared["sha256"] or source_bytes != declared["bytes"]:
        raise DomainError("source_integrity_failed", "Source completion differs from the original manifest.", 422)
    asset = Asset.objects.filter(pk=source_id, revision=revision).first()
    if (asset is None or asset.kind != "reader_source" or asset.state != "ready" or asset.unit_id is not None
            or asset.provider != "r2" or asset.content_type != "application/json"
            or asset.sha256 != source_sha or asset.bytes != source_bytes):
        raise DomainError("source_integrity_failed", "Use the exact ready source asset belonging to this draft.", 409)
    return asset


def _asset_identity(asset):
    return {"asset_id": str(asset.id), "unit_id": str(asset.unit_id) if asset.unit_id else None,
        "kind": asset.kind, "state": asset.state, "provider": asset.provider,
        "sha256": asset.sha256, "bytes": asset.bytes, "compressed_bytes": asset.compressed_bytes,
        "content_type": asset.content_type, "storage_key": asset.storage_key}


def start_import(actor, manifest, operation):
    """Reserve an empty denied draft. No source download or storage request."""
    _publisher(actor)
    manifest_sha = _manifest(manifest)
    operation = public_uuid(operation, "Idempotency-Key")
    payload = {"manifest": manifest}
    old = OperationReceipt.objects.filter(actor=actor, operation_id=operation).first()
    if old:
        def no_second_reservation():
            raise DomainError("operation_reconciliation_required", "Reconcile the original draft reservation.", 409)
        status, result = apply_operation(actor, operation, "book.general_import_start", payload, no_second_reservation)
        revision = _revision(result["edition_id"], result["edition_revision_id"], actor)
        return status, result

    def create():
        current_actor = _publisher(locked_actor(actor))
        work_data, edition_data = manifest["work"], manifest["edition"]
        work, _ = Work.objects.get_or_create(slug=work_data["slug"], defaults={
            "id": _identifier(actor.public_id, operation, manifest_sha, "work"),
            "title": work_data["title"], "creators": work_data["creators"], "house": work_data["house"]})
        work = Work.objects.select_for_update().get(pk=work.pk)
        if any(getattr(work, key) != work_data[key] for key in ("title", "creators", "house")):
            raise DomainError("import_identity_conflict", "Existing work differs from this source manifest.", 409)
        if Edition.objects.filter(slug=edition_data["slug"]).exists():
            raise DomainError("already_imported", "Reconcile the existing edition; this operation never overwrites it.", 409)
        edition = Edition.objects.create(id=_identifier(actor.public_id, operation, manifest_sha, "edition"),
            work=work, slug=edition_data["slug"], locale=edition_data["language"])
        record = {"schema": IMPORT_SCHEMA, "actor_public_id": str(current_actor.public_id),
            "start_operation_id": str(operation), "manifest_sha256": manifest_sha,
            "manifest": manifest, "state": "AWAITING_SOURCE", "rights_approval_created": False,
            "publication": False}
        revision = Revision.objects.create(id=_identifier(actor.public_id, operation, manifest_sha, "revision"),
            edition=edition, title=edition_data["title"], description=edition_data["description"],
            content_sha256=EMPTY_SHA, access_policy=dict(DENIED), download_policy=dict(NO_DOWNLOADS),
            preview=[], validation_evidence={EVIDENCE_KEY: record})
        audit(actor, "book.general_import_start", revision,
            {"project_id": manifest["project_id"], "manifest_sha256": manifest_sha,
             "source_sha256": manifest["source"]["sha256"], "rights_approval_created": False})
        return 201, {"schema": "earnalism.book_import_started.v1", "edition_id": str(edition.id),
            "edition_revision_id": str(revision.id), "sha256": revision.content_sha256,
            "version": revision.version, "current_etag": _etag(revision),
            "state": "DRAFT_SOURCE_UPLOAD_REQUIRED", "publication": False,
            "rights_approval_created": False}, revision.version
    try:
        outcome = apply_operation(actor, operation, "book.general_import_start", payload, create)
        if getattr(outcome, "replayed", False):
            _revision(outcome[1]["edition_id"], outcome[1]["edition_revision_id"], actor)
        return outcome
    except IntegrityError:
        raise DomainError("import_identity_conflict", "The import identity changed; reconcile the existing edition.", 409) from None


def _package_raw(unit, paragraphs, asset_id):
    return canonical_bytes({"schema_version": 1, "edition_revision_id": str(unit.revision_id),
        "unit_id": str(unit.id), "chunk_id": str(asset_id), "anchor_revision": unit.revision.anchor_revision,
        "locale": unit.revision.edition.locale, "paragraphs": [paragraph_dto(p) for p in paragraphs]})


def _fits(unit, paragraphs, asset_id):
    if not paragraphs or len(paragraphs) > 100 or any(len(p.text) > 32000 for p in paragraphs):
        return False
    raw = _package_raw(unit, paragraphs, asset_id)
    return len(raw) <= 262144 and len(gzip.compress(raw, mtime=0)) <= 65536


def _budget(started):
    if time.monotonic() - started >= MAX_PREPARATION_SECONDS:
        raise DomainError("import_preparation_timeout", "Private package preparation reached its bounded budget; retain the exact source and operation.", 503)


def _plan_source(revision, record, source, started, original_source):
    """Prepare the complete deterministic local plan before any package PUT."""
    actor_id, operation, manifest_sha = record["actor_public_id"], record["start_operation_id"], record["manifest_sha256"]
    units, paragraphs, groups, unit_keys = [], [], [], []
    try:
        batches = reader_batches(original_source)
    except (SourceError, ValueError, TypeError, KeyError):
        raise DomainError("import_preparation_limit", "Source exceeds the bounded Reader package budget.", 413) from None
    _budget(started)
    for ordinal, (row, unit_batches) in enumerate(zip(source["units"], batches), 1):
        _budget(started)
        label = "source:" + record["manifest"]["source"]["sha256"] + ":" + row["key"]
        unit = Unit(id=_identifier(actor_id, operation, manifest_sha, label), revision=revision,
            title=row["title"], kind=row["kind"], ordinal=ordinal, duration_ms=row.get("duration_ms"))
        source_paragraphs = [Paragraph(id=_identifier(actor_id, operation, manifest_sha, label + ":paragraph:" + str(n)),
            anchor_id=_identifier(actor_id, operation, manifest_sha, label + ":anchor:" + str(n)),
            unit=unit, ordinal=n, kind=p["kind"], text=p["text"]) for n, p in enumerate(row["paragraphs"], 1)]
        for chunk_number, indexes in enumerate(unit_batches):
            _budget(started)
            chunk_id = _identifier(actor_id, operation, manifest_sha, label + ":chunk:" + str(chunk_number))
            chunk = [source_paragraphs[index] for index in indexes]
            if not _fits(unit, chunk, chunk_id):
                raise DomainError("chunk_too_large", "Source slice exceeds Reader package bounds.", 413)
            groups.append((unit, chunk, chunk_id))
            if len(groups) > MAX_PACKAGES:
                raise DomainError("import_preparation_limit", "This bounded import supports at most 128 Reader packages.", 413)
        units.append(unit); paragraphs.extend(source_paragraphs)
        unit_keys.append({"key": row["key"], "unit_id": str(unit.id), "ordinal": ordinal,
            "paragraph_count": len(source_paragraphs)})
    if len(groups) > MAX_PACKAGES:
        raise DomainError("import_preparation_limit", "This bounded import supports at most 128 Reader packages.", 413)
    return units, paragraphs, groups, unit_keys


def _replay_import(actor, edition_id, data, payload, operation):
    def never_attach_twice():
        raise DomainError("operation_reconciliation_required", "Reconcile the original source import.", 409)
    status, result = apply_operation(actor, operation, "book.general_import_finalize", payload, never_attach_twice)
    revision = _revision(edition_id, data["edition_revision_id"], actor)
    record = _binding(revision, actor)
    _source_asset(revision, record, data["source_asset_id"], data["source_sha256"], data["source_bytes"])
    if (record.get("state") != "IMPORTED" or record.get("source_asset_id") != data["source_asset_id"]
            or revision.content_sha256 != result["sha256"] or revision_hash(revision) != result["sha256"]):
        raise DomainError("import_scope_mismatch", "Imported text no longer matches its retained source receipt.", 409)
    actual_units = {str(u.id): {"title": u.title, "kind": u.kind, "duration_ms": u.duration_ms,
        "ordinal": u.ordinal} for u in revision.units.all()}
    if actual_units != record.get("unit_identities"):
        raise DomainError("import_scope_mismatch", "Imported unit identity changed after its source receipt.", 409)
    transform = record.get("source_transform", {})
    if (not isinstance(transform, dict) or transform != result.get("source_transform") or transform.get("method") != "UNICODE_NFC_READER_DERIVATIVE"
            or transform.get("original_source_sha256") != data["source_sha256"] or transform.get("source_unchanged") is not True):
        raise DomainError("import_scope_mismatch", "The declared Reader derivative changed after import.", 409)
    keys = {row["unit_id"]: row["key"] for row in result["units"]}
    source_units = []
    for unit in revision.units.prefetch_related("paragraphs").all():
        rows = [{"kind": p.kind, "text": p.text} for p in unit.paragraphs.all()]
        if (unit.title != unicodedata.normalize("NFC", unit.title)
                or any(p["text"] != unicodedata.normalize("NFC", p["text"]) for p in rows)):
            raise DomainError("import_scope_mismatch", "Imported Reader text is no longer its declared NFC derivative.", 409)
        row = {"key": keys[str(unit.id)], "title": unit.title, "kind": unit.kind, "paragraphs": rows}
        if unit.duration_ms is not None:
            row["duration_ms"] = unit.duration_ms
        source_units.append(row)
    derived = {"schema": "earnalism.book_source.v1", "language": revision.edition.locale, "units": source_units}
    if digest(canonical_bytes(derived)) != transform.get("canonical_source_sha256"):
        raise DomainError("import_scope_mismatch", "Reader derivative differs from its source transformation proof.", 409)
    assets = list(Asset.objects.filter(pk__in=result["reader_asset_ids"], revision=revision))
    expected = record.get("reader_assets", {})
    if ({str(a.id): _asset_identity(a) for a in assets} != expected
            or set(expected) != set(result["reader_asset_ids"])):
        raise DomainError("import_scope_mismatch", "Imported Reader assets are missing or changed.", 409)
    return status, {**result, "version": revision.version, "current_etag": _etag(revision)}


def finalize_import(actor, edition_id, data, version, operation):
    """Hash the exact owned source, prepare private chunks, then atomically attach."""
    _publisher(actor)
    edition_id = public_uuid(edition_id, "edition_id")
    operation = public_uuid(operation, "Idempotency-Key")
    fields = {"edition_revision_id", "source_asset_id", "source_sha256", "source_bytes"}
    if not isinstance(data, dict) or set(data) != fields:
        raise DomainError("validation_error", "Use the exact source-import completion fields.", 422)
    data = dict(data)
    for field in ("edition_revision_id", "source_asset_id"):
        data[field] = str(public_uuid(data[field], field))
    if type(version) is not int or version < 1 or type(data["source_bytes"]) is not int:
        raise DomainError("validation_error", "Positive source size and current revision version required.", 422)
    payload = {**data, "edition_id": str(edition_id), "expected_version": version}
    if OperationReceipt.objects.filter(actor=actor, operation_id=operation).exists():
        return _replay_import(actor, edition_id, data, payload, operation)
    _admit_preparation(actor)
    revision = _revision(edition_id, data["edition_revision_id"], actor)
    record = _binding(revision, actor)
    if revision.version != version:
        raise DomainError("version_conflict", "The exact current draft ETag is required.", 412)
    if (record.get("state") != "AWAITING_SOURCE" or revision.content_sha256 != EMPTY_SHA
            or revision.units.exists() or revision.rights.exists()
            or revision.access_policy != DENIED or revision.download_policy != NO_DOWNLOADS or revision.preview):
        raise DomainError("import_scope_mismatch", "Source import requires its unchanged empty denied draft.", 409)
    asset = _source_asset(revision, record, data["source_asset_id"], data["source_sha256"], data["source_bytes"])
    source_identity = _asset_identity(asset)
    started = time.monotonic()
    raw = storage.read_verified(asset)
    try:
        source = read_source_bytes(raw)
    except (SourceError, ValueError, TypeError, KeyError):
        raise DomainError("invalid_book_source", "The verified source must match the bounded source schema.", 422) from None
    if source["language"] != record["manifest"]["edition"]["language"]:
        raise DomainError("source_language_mismatch", "Source language differs from the reserved edition.", 409)
    from operations.book_source import reader_derivative
    try:
        derived, transform = reader_derivative(source, data["source_sha256"])
    except (SourceError, ValueError, TypeError, KeyError):
        raise DomainError("invalid_book_source", "Source cannot form the declared bounded NFC Reader derivative.", 422) from None
    units, paragraphs, groups, unit_keys = _plan_source(revision, record, derived, started, source)
    assets = []
    for unit, chunk, identifier in groups:
        _budget(started)
        package = prepare_reader_package(unit, chunk, asset_id=identifier)
        _budget(started)
        expected_raw = _package_raw(unit, chunk, identifier)
        if package.sha256 != digest(expected_raw) or package.bytes != len(expected_raw):
            raise DomainError("source_integrity_failed", "Prepared package differs from the source plan.", 409)
        assets.append(package)
    content_sha = digest(canonical_bytes([{"unit_id": str(u.id), "title": u.title, "ordinal": u.ordinal,
        "paragraphs": [paragraph_dto(p) for p in paragraphs if p.unit_id == u.id]} for u in units]))
    _budget(started)

    def attach():
        _publisher(locked_actor(actor))
        current = Revision.objects.select_for_update(of=("self",)).select_related("edition", "edition__work").get(pk=revision.id)
        if current.version != version:
            raise DomainError("version_conflict", "The draft changed during private package preparation; no text was attached.", 412)
        current_record = _binding(current, actor)
        current_asset = Asset.objects.select_for_update().get(pk=asset.id)
        if (current.version != version or current.content_sha256 != EMPTY_SHA or current_record != record
                or _asset_identity(current_asset) != source_identity or current.units.exists() or current.rights.exists()
                or current.access_policy != DENIED or current.download_policy != NO_DOWNLOADS or current.preview):
            raise DomainError("version_conflict", "The draft/source changed during package preparation; no text was attached.", 412)
        Unit.objects.bulk_create(units)
        Paragraph.objects.bulk_create(paragraphs, batch_size=1000)
        # Preserve manifest order: existing Reader coverage sorts by created_at/id.
        for package in assets:
            package.save()
        current.content_sha256 = content_sha
        binding = {**record, "state": "IMPORTED", "source_asset_id": str(asset.id),
            "source_byte_verification": "EXACT_READY_OWNED_SOURCE_HASH_VERIFIED",
            "source_transform": transform,
            "unit_identities": {str(u.id): {"title": u.title, "kind": u.kind, "duration_ms": u.duration_ms,
                "ordinal": u.ordinal} for u in units},
            "reader_assets": {str(a.id): _asset_identity(a) for a in assets},
            "paragraph_count": len(paragraphs), "rights_approval_created": False, "publication": False}
        current.validation_evidence = {**current.validation_evidence, EVIDENCE_KEY: binding}
        current.save(); current.refresh_from_db()
        audit(actor, "book.general_import_finalize", current,
            {"manifest_sha256": record["manifest_sha256"], "source_sha256": asset.sha256,
             "paragraph_count": len(paragraphs), "reader_asset_ids": [str(a.id) for a in assets],
             "rights_approval_created": False})
        return 200, {"schema": "earnalism.book_import_result.v1", "state": "DRAFT_SOURCE_IMPORTED",
            "edition_id": str(current.edition_id), "edition_revision_id": str(current.id),
            "sha256": current.content_sha256, "version": current.version, "current_etag": _etag(current),
            "source_asset_id": str(asset.id), "units": unit_keys, "reader_asset_ids": [str(a.id) for a in assets],
            "source_transform": transform,
            "paragraph_count": len(paragraphs), "rights_approval_created": False, "publication": False}, current.version
    outcome = apply_operation(actor, operation, "book.general_import_finalize", payload, attach)
    if getattr(outcome, "replayed", False):
        return _replay_import(actor, edition_id, data, payload, operation)
    return outcome
