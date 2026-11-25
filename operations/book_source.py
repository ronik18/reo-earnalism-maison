"""Bounded English/Bengali source import data, never instructions or authority.

Source bytes and text are retained exactly. Validation performs no network,
normalization, content generation, clearance decision or publication operation.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import re
import unicodedata

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_UNITS = 128
MAX_PARAGRAPHS = 50000
MAX_PARAGRAPH_BYTES = 48 * 1024
MAX_PARAGRAPH_CHARACTERS = 32000
MAX_CHUNK_PARAGRAPHS = 100
MAX_READER_PACKAGES = 128
READER_RAW_BUDGET = 60 * 1024
MANIFEST_SCHEMA = "earnalism.book_import_manifest.v1"
SOURCE_SCHEMA = "earnalism.book_source.v1"
HOUSES = frozenset(("classics", "golpo", "learn", "interview", "series", "collections"))
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SLUG = re.compile(r"[-A-Za-z0-9_]{1,50}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")


class SourceError(ValueError):
    pass


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or set(required) - value.keys() or value.keys() - set(required) - set(optional):
        raise SourceError("SOURCE_FIELDS_INVALID")


def _text(value, limit, *, multiline=False, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise SourceError("SOURCE_TEXT_BOUNDS_INVALID")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise SourceError("SOURCE_UTF8_TEXT_REQUIRED") from None
    allowed = {"\r", "\n", "\t"} if multiline else set()
    if any(ord(c) < 32 and c not in allowed or ord(c) == 127 for c in value):
        raise SourceError("SOURCE_CONTROL_CHARACTER_INVALID")


def _json(raw, limit):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
        raise SourceError("BOUNDED_SOURCE_BYTES_REQUIRED")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SourceError("DUPLICATE_SOURCE_JSON_KEY")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(SourceError("FINITE_SOURCE_JSON_REQUIRED")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise SourceError("SOURCE_JSON_REQUIRED") from None


def validate_manifest(manifest):
    """Validate metadata; return its SHA. No source bytes or rights are verified."""
    _keys(manifest, ("schema", "project_id", "work", "edition", "source", "provenance"))
    if manifest["schema"] != MANIFEST_SCHEMA or not isinstance(manifest["project_id"], str) or not NAME.fullmatch(manifest["project_id"]):
        raise SourceError("SOURCE_MANIFEST_IDENTITY_INVALID")
    work = manifest["work"]
    _keys(work, ("slug", "title", "creators", "house"))
    if not isinstance(work["slug"], str) or not SLUG.fullmatch(work["slug"]):
        raise SourceError("SOURCE_WORK_SLUG_REQUIRED")
    _text(work["title"], 240)
    if not isinstance(work["creators"], list) or not 1 <= len(work["creators"]) <= 20:
        raise SourceError("SOURCE_CREATORS_REQUIRED")
    for creator in work["creators"]:
        _text(creator, 240)
    if not isinstance(work["house"], str) or work["house"] not in HOUSES:
        raise SourceError("SOURCE_HOUSE_INVALID")
    edition = manifest["edition"]
    _keys(edition, ("slug", "language", "title", "description"))
    if not isinstance(edition["slug"], str) or not SLUG.fullmatch(edition["slug"]) or edition["language"] not in ("en", "bn"):
        raise SourceError("SOURCE_EDITION_IDENTITY_INVALID")
    _text(edition["title"], 240)
    _text(edition["description"], 4000, multiline=True, empty=True)
    source = manifest["source"]
    _keys(source, ("sha256", "bytes", "content_type", "format"))
    if (not isinstance(source["sha256"], str) or not SHA.fullmatch(source["sha256"])
            or type(source["bytes"]) is not int or not 1 <= source["bytes"] <= MAX_SOURCE_BYTES
            or source["content_type"] != "application/json" or source["format"] != SOURCE_SCHEMA):
        raise SourceError("EXACT_BOUNDED_JSON_SOURCE_REQUIRED")
    provenance = manifest["provenance"]
    _keys(provenance, ("source_ref", "source_edition", "rights_note", "rights_evidence_refs"))
    _text(provenance["source_ref"], 2048)
    _text(provenance["source_edition"], 1000)
    _text(provenance["rights_note"], 4000, multiline=True)
    refs = provenance["rights_evidence_refs"]
    if not isinstance(refs, list) or len(refs) > 20:
        raise SourceError("BOUNDED_SOURCE_RIGHTS_REFERENCES_REQUIRED")
    for ref in refs:
        _text(ref, 2048)
    if len(set(refs)) != len(refs):
        raise SourceError("UNIQUE_SOURCE_RIGHTS_REFERENCES_REQUIRED")
    raw = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > 128 * 1024:
        raise SourceError("BOUNDED_SOURCE_MANIFEST_REQUIRED")
    return hashlib.sha256(raw).hexdigest()


def validate_source(source):
    """Validate exact source structure; text is neither normalized nor executed."""
    _keys(source, ("schema", "language", "units"))
    if source["schema"] != SOURCE_SCHEMA or source["language"] not in ("en", "bn"):
        raise SourceError("SOURCE_LANGUAGE_SCHEMA_INVALID")
    units = source["units"]
    if not isinstance(units, list) or not 1 <= len(units) <= MAX_UNITS:
        raise SourceError("BOUNDED_SOURCE_UNITS_REQUIRED")
    keys, count = set(), 0
    for unit in units:
        _keys(unit, ("key", "title", "kind", "paragraphs"), ("duration_ms",))
        key = unit["key"]
        if not isinstance(key, str) or not NAME.fullmatch(key) or key in keys:
            raise SourceError("UNIQUE_SOURCE_UNIT_KEYS_REQUIRED")
        keys.add(key)
        _text(unit["title"], 240)
        if unit["kind"] not in ("chapter", "lesson", "episode"):
            raise SourceError("SOURCE_UNIT_KIND_INVALID")
        if "duration_ms" in unit and (type(unit["duration_ms"]) is not int or not 1 <= unit["duration_ms"] <= 9223372036854775807):
            raise SourceError("SOURCE_MEASURED_DURATION_INVALID")
        paragraphs = unit["paragraphs"]
        if not isinstance(paragraphs, list) or not paragraphs:
            raise SourceError("SOURCE_PARAGRAPHS_REQUIRED")
        count += len(paragraphs)
        if count > MAX_PARAGRAPHS:
            raise SourceError("BOUNDED_SOURCE_PARAGRAPHS_REQUIRED")
        previous = None
        for paragraph in paragraphs:
            _keys(paragraph, ("kind", "text"))
            if paragraph["kind"] not in ("paragraph", "heading", "verse", "note"):
                raise SourceError("SOURCE_PARAGRAPH_KIND_INVALID")
            # An author's footnote sits directly after the paragraph or verse it annotates.
            if paragraph["kind"] == "note" and previous not in ("paragraph", "verse"):
                raise SourceError("SOURCE_NOTE_PLACEMENT_INVALID")
            previous = paragraph["kind"]
            _text(paragraph["text"], MAX_PARAGRAPH_CHARACTERS, multiline=True)
            if len(paragraph["text"].encode("utf-8")) > MAX_PARAGRAPH_BYTES:
                raise SourceError("SOURCE_PARAGRAPH_UTF8_BUDGET_EXCEEDED")
    return source


def read_source_bytes(raw):
    return validate_source(_json(raw, MAX_SOURCE_BYTES))


def reader_derivative(source, original_source_sha256):
    """Return a named NFC Reader copy and proof; never alter the raw original."""
    validate_source(source)
    if not isinstance(original_source_sha256, str) or not SHA.fullmatch(original_source_sha256):
        raise SourceError("ORIGINAL_SOURCE_SHA256_REQUIRED")
    derived = deepcopy(source)
    paragraphs = titles = 0
    for unit in derived["units"]:
        normalized = unicodedata.normalize("NFC", unit["title"])
        if len(normalized) > 240:
            raise SourceError("NFC_READER_UNIT_TITLE_BUDGET_EXCEEDED")
        titles += normalized != unit["title"]
        unit["title"] = normalized
        for paragraph in unit["paragraphs"]:
            normalized = unicodedata.normalize("NFC", paragraph["text"])
            if len(normalized) > MAX_PARAGRAPH_CHARACTERS:
                raise SourceError("NFC_READER_PARAGRAPH_CHARACTER_BUDGET_EXCEEDED")
            paragraphs += normalized != paragraph["text"]
            paragraph["text"] = normalized
    raw = json.dumps(derived, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return derived, {"method": "UNICODE_NFC_READER_DERIVATIVE",
        "original_source_sha256": original_source_sha256, "canonical_source_sha256": hashlib.sha256(raw).hexdigest(),
        "normalized_paragraphs": paragraphs, "normalized_unit_titles": titles, "source_unchanged": True}


def reader_batches(source):
    """Return per-unit paragraph-index batches within existing Reader limits.

    New imported IDs are UUID4 strings, all the same encoded length. A60KiB raw
    body conservatively fits the existing64KiB gzip limit even for incompressible
    content. NFC is used only to measure the existing Reader representation;
    source text and raw input remain unchanged.
    """
    validate_source(source)

    def encoded(value):
        return unicodedata.normalize("NFC", json.dumps(value, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"))).encode("utf-8")

    uid = "00000000-0000-4000-8000-000000000000"
    overhead = len(encoded({"schema_version": 1, "edition_revision_id": uid, "unit_id": uid,
        "chunk_id": uid, "anchor_revision": 1, "locale": source["language"], "paragraphs": []}))
    output, total = [], 0
    for unit in source["units"]:
        batches, batch, size = [], [], overhead
        for index, paragraph in enumerate(unit["paragraphs"]):
            if len(unicodedata.normalize("NFC", paragraph["text"])) > MAX_PARAGRAPH_CHARACTERS:
                raise SourceError("NFC_READER_PARAGRAPH_CHARACTER_BUDGET_EXCEEDED")
            row = {"anchor_id": uid, "kind": paragraph["kind"], "text": paragraph["text"], "ordinal": index + 1}
            count = len(encoded(row))
            if overhead + count > READER_RAW_BUDGET:
                raise SourceError("READER_PARAGRAPH_PACKAGE_BUDGET_EXCEEDED")
            extra = count + bool(batch)
            if len(batch) >= MAX_CHUNK_PARAGRAPHS or size + extra > READER_RAW_BUDGET:
                batches.append(batch); total += 1
                if total >= MAX_READER_PACKAGES:
                    raise SourceError("PRIVATE_IMPORT_PACKAGE_BUDGET_EXCEEDED")
                batch, size, extra = [], overhead, count
            batch.append(index); size += extra
        batches.append(batch); total += 1
        if total > MAX_READER_PACKAGES:
            raise SourceError("PRIVATE_IMPORT_PACKAGE_BUDGET_EXCEEDED")
        output.append(batches)
    return output


def _snapshot(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise SourceError("EXACT_BOUNDED_SOURCE_FILE_REQUIRED")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise SourceError("BOUNDED_SOURCE_BYTES_REQUIRED")
    return raw


def source_snapshot(path):
    raw = _snapshot(path, MAX_SOURCE_BYTES)
    return raw, read_source_bytes(raw)


def load_source(path):
    return source_snapshot(path)[1]


def load_manifest(path):
    manifest = _json(_snapshot(path, 128 * 1024), 128 * 1024)
    validate_manifest(manifest)
    return manifest


def prepare_source(manifest, source_path):
    fingerprint = validate_manifest(manifest)
    raw, source = source_snapshot(source_path)
    if len(raw) != manifest["source"]["bytes"] or hashlib.sha256(raw).hexdigest() != manifest["source"]["sha256"]:
        raise SourceError("SOURCE_BYTES_CHANGED")
    if source["language"] != manifest["edition"]["language"]:
        raise SourceError("SOURCE_EDITION_LANGUAGE_MISMATCH")
    _, transform = reader_derivative(source, manifest["source"]["sha256"])
    packages = reader_batches(source)
    return {"schema": "earnalism.book_import_plan.v1", "state": "PREPARED_NO_PROVIDER_REQUESTS",
        "manifest_sha256": fingerprint, "source_sha256": manifest["source"]["sha256"], "source_bytes": len(raw),
        "work": manifest["work"], "edition": manifest["edition"],
        "unit_count": len(source["units"]), "paragraph_count": sum(len(u["paragraphs"]) for u in source["units"]),
        "reader_package_count": sum(len(batches) for batches in packages),
        "original_source_bytes_preserved": True, "source_transform": transform,
        "rights_evidence_is_supplied_not_approved": True,
        "execution_enabled": False, "provider_requests": 0, "model_calls": 0,
        "rights_approval_created": False, "publication": False,
        "limits": {"source_bytes": MAX_SOURCE_BYTES, "units": MAX_UNITS, "paragraphs": MAX_PARAGRAPHS,
            "paragraph_utf8_bytes": MAX_PARAGRAPH_BYTES, "paragraph_characters": MAX_PARAGRAPH_CHARACTERS,
            "chunk_paragraphs": MAX_CHUNK_PARAGRAPHS, "reader_packages": MAX_READER_PACKAGES}}
