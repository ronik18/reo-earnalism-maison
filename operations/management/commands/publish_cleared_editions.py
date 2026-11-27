"""Owner-authorized server-side publication of exact cleared editions (23 Nov 2026).

Runs the same audited services the staff API uses -- general source import, asset
storage, rights rows, validation and transition_revision -- as a named verified
publisher, so no web staff session is needed. Every publication check still runs;
nothing here skips validate_revision. Each stage is idempotent and hash-bound.

Stages: import (create the বিচারক draft from library/intake/bicharak), revise (a corrected source
of an already-live edition becomes a new draft revision; text-only, see revise_book), evidence
(record clearance + browser acceptance against the exact text and asset hashes),
publish (mark-ready then publish). Output is JSON on stdout; no secrets are printed.
"""
import hashlib
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.services import audit
from library import storage
from operations.review import approved_for
from library.general_import import DENIED, NO_DOWNLOADS, finalize_import, start_import
from library.models import Asset, Edition, Paragraph, Revision, Rights, Unit
from library.services import (canonical_bytes, digest, paragraph_dto, prepare_reader_package, prepare_revision_validation,
                              transition_revision, validate_revision)
from core.models import AuditEvent
from operations.book_source import SourceError, read_source_bytes, reader_batches, reader_derivative, validate_manifest

ROOT = Path(settings.BASE_DIR)
INTAKE = ROOT / "library" / "intake"
CLEARANCE_DOC = "docs/evidence/publication-clearance-20261123.json"
NAMESPACE = uuid.UUID("6f1d8a52-3c1e-4c55-9a51-0b7f3a2d2311")
# The two books published on 23 Nov 2026 keep their multi-book clearance record; every later packet carries its own.
LEGACY_BOOKS = {
    "the-selfish-giant": {"edition": "the-selfish-giant-en", "intake": "covers", "import": False},
    "bicharak": {"edition": "bicharak", "intake": "bicharak", "import": True},
}
EVIDENCE_PREFIX = "reo-earnalism-maison:"
# The only asset kinds the revise stage rebuilds; any other kind on the live revision makes revise refuse.
REVISE_REBUILT_KINDS = ("reader_package", "reader_source", "cover")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def stable_id(*parts):
    """Deterministic, so a rerun replays the same operations; shaped as UUID4 for public_uuid()."""
    return uuid.UUID(bytes=uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts)).bytes, version=4)


def _json(path):
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        return None


def monday_approval(root, folder, clearance_path, clearance_file, record, edition_slug):
    """Owner decision D8: the clearance item and the cover item approved on the Monday page for these exact files.

    Returns the two ReviewItems (clearance, cover) or None. Both are bound to the files' current sha256, so a later
    change to either file voids the approval; standing permission never counts (approved_for ignores it)."""
    if (record.get("status") != "DRAFT_PENDING_OWNER_APPROVAL" or set(record.get("territories") or ()) != set(territories())
            or record.get("formats") != ["reader"]):
        return None
    try:
        cover_ref = (Path(folder) / "cover_provenance.json").relative_to(root).as_posix()
    except ValueError:
        cover_ref = f"library/intake/{Path(folder).name}/cover_provenance.json"
    cover_file = Path(folder) / "cover_provenance.json"
    if not cover_file.is_file():
        return None
    clearance = approved_for("clearance", clearance_path, sha256(Path(clearance_file).read_bytes()))
    cover = approved_for("cover", cover_ref, sha256(cover_file.read_bytes()))
    if not (clearance and cover) or (clearance.summary or {}).get("edition_slug") != edition_slug:
        return None
    return clearance, cover


def reverify_approval(packet):
    """Immediately before a write: a DB-approved packet must still match its approved items and files (D8)."""
    if not packet.get("review_items"):
        return
    root, folder = Path(packet["root"]), Path(packet["folder"])
    clearance_file = root / packet["clearance_path"]
    again = monday_approval(root, folder, packet["clearance_path"], clearance_file, _json(clearance_file) or {}, packet["edition_slug"])
    if again is None or [i.id for i in again] != [i.id for i in packet["review_items"]]:
        raise CommandError(f"{packet['slug']}: MONDAY_APPROVAL_VOIDED: the clearance or cover file changed or the approval no longer stands.")


def evidence_ref_for(packet):
    ref = packet["clearance_path"] + "#sha256=" + packet["clearance_sha256"]
    items = packet.get("review_items")
    if items:
        ref += ";review_items=" + ",".join(str(i.id) for i in items) + ";decided_by=" + ",".join(
            sorted({str(i.decided_by.public_id) if i.decided_by else "unknown" for i in items}))
    return ref


def approved_packets(intake=None, root=None, check=None):
    """Every publishable packet: the two legacy books plus each intake packet with an owner-approved clearance record.

    A discovered packet qualifies only when its own clearance record (manifest.provenance.rights_evidence_refs) has a
    status exactly OWNER_APPROVED, approval.approved true and nothing still required, or (owner decision D8) a status
    exactly DRAFT_PENDING_OWNER_APPROVAL whose clearance file and cover_provenance.json each have an approved,
    non-standing Monday-page review item bound to the file's current sha256 (see monday_approval); and the text and cover bytes
    on disk are exactly those the record and cover_provenance.json name. Approval over changed bytes is refused.
    `check` limits the byte-hash verification (and its CommandError) to those slugs; None verifies every packet.
    """
    intake, root = Path(intake or INTAKE), Path(root or ROOT)
    packets = {}
    legacy_doc = root / CLEARANCE_DOC
    legacy_sha = sha256(legacy_doc.read_bytes()) if legacy_doc.exists() else None
    legacy_editions = set()
    for slug, spec in LEGACY_BOOKS.items():
        covers = ((_json(legacy_doc) or {}).get("books", {}).get(slug, {}).get("covers", {}))
        packets[slug] = {"slug": slug, "book_key": slug, "edition_slug": spec["edition"], "folder": intake / spec["intake"],
            "clearance_path": CLEARANCE_DOC, "clearance_sha256": legacy_sha, "import": spec["import"], "legacy": True,
            "covers": (covers.get("front_jpg_sha256"), covers.get("back_jpg_sha256"))}
        legacy_editions.add(spec["edition"])
    for manifest_path in sorted(intake.glob("*/manifest.json")):
        folder = manifest_path.parent
        manifest = _json(manifest_path) or {}
        # Keyed by EDITION slug: a translation shares its source's Work and must not be dropped as a duplicate.
        slug = edition_slug = (manifest.get("edition") or {}).get("slug")
        if not slug or slug in packets or slug in legacy_editions:
            continue
        refs = [r for r in (manifest.get("provenance") or {}).get("rights_evidence_refs") or [] if str(r).startswith(EVIDENCE_PREFIX)]
        if len(refs) != 1:
            continue
        clearance_path = refs[0][len(EVIDENCE_PREFIX):]
        clearance_file = root / clearance_path
        if not clearance_file.is_file():
            continue
        record = _json(clearance_file)
        if not isinstance(record, dict):
            continue
        approval = record.get("approval") or {}
        book = (record.get("books") or {}).get(slug)
        if not (isinstance(book, dict) and edition_slug):
            continue
        in_file = (record.get("status") == "OWNER_APPROVED" and approval.get("approved") is True
                   and not approval.get("still_required"))
        review_items = None
        if not in_file:
            review_items = monday_approval(root, folder, clearance_path, clearance_file, record, edition_slug)
            if review_items is None:
                continue
        provenance = _json(folder / "cover_provenance.json")
        if not provenance or not all((folder / name).is_file() for name in ("front.jpg", "back.jpg", "source.json")):
            continue
        covers = ()
        if check is not None and slug not in check:
            packets[slug] = {"slug": slug, "book_key": slug, "edition_slug": edition_slug, "folder": folder, "clearance_path": clearance_path,
                "clearance_sha256": sha256(clearance_file.read_bytes()), "import": True, "legacy": False, "covers": covers,
                "review_items": review_items, "root": str(root)}
            continue
        source_sha = sha256((folder / "source.json").read_bytes())
        if book.get("source_sha256") != source_sha or (manifest.get("source") or {}).get("sha256") != source_sha:
            raise CommandError(f"{slug}: SOURCE_HASH_MISMATCH: source.json differs from the owner-approved clearance record.")
        covers = []
        for side in ("front", "back"):
            expected = (((provenance.get("sides") or {}).get(side) or {}).get("delivery") or {}).get("sha256")
            if not expected or sha256((folder / f"{side}.jpg").read_bytes()) != expected:
                raise CommandError(f"{slug}: COVER_HASH_MISMATCH: {side}.jpg differs from cover_provenance.json.")
            covers.append(expected)
        attached = approval.get("cover_attached")
        if attached and (attached.get("front_sha256"), attached.get("back_sha256")) != tuple(covers):
            raise CommandError(f"{slug}: COVER_HASH_MISMATCH: approval.cover_attached differs from front.jpg/back.jpg.")
        packets[slug] = {"slug": slug, "book_key": slug, "edition_slug": edition_slug, "folder": folder, "clearance_path": clearance_path,
            "clearance_sha256": sha256(clearance_file.read_bytes()), "import": True, "legacy": False, "covers": tuple(covers),
            "review_items": review_items, "root": str(root)}
    return packets


def import_order(chosen, packets):
    """`chosen` reordered so a source packet comes before every translation made from it (translation.json
    translated_from names the source packet folder); otherwise the given order is kept."""
    by_folder = {Path(packets[slug]["folder"]).name: slug for slug in chosen}
    ordered, seen = [], set()

    def visit(slug, trail=()):
        if slug in seen:
            return
        if slug in trail:
            raise CommandError(f"TRANSLATION_CYCLE: {' -> '.join(trail + (slug,))}")
        record = _json(Path(packets[slug]["folder"]) / "translation.json") or {}
        source = by_folder.get(record.get("translated_from")) if isinstance(record, dict) else None
        if source and source != slug:
            visit(source, trail + (slug,))
        seen.add(slug)
        ordered.append(slug)

    for slug in chosen:
        visit(slug)
    return ordered


# Revision.preview must be non-empty to offer a Reader preview; it is the on/off signal only. Since the owner decision
# of 26 Nov 2026 readers see library.services.preview_cut (about 25% of the story, 400-1,500 words), not these entries.
# These bounds are the model's stored-entry validation (Revision.clean), not the served preview length.
PREVIEW_ENTRIES, PREVIEW_CODEPOINTS = 3, 1200
SENTENCE_MARKS = "\u0964?!"  # Bengali danda, question mark, exclamation mark; "." counts only before a space or the end


def sentence_prefix(text, limit=PREVIEW_CODEPOINTS):
    """The longest exact prefix of `text` within `limit` codepoints that ends at a sentence end, or None."""
    for end in range(min(len(text), limit), 0, -1):
        mark = text[end - 1]
        if mark in SENTENCE_MARKS or (mark == "." and (end == len(text) or text[end].isspace())):
            return text[:end]
    return None


def preview_entries(paragraphs):
    """Bounded public preview: up to 3 whole leading paragraphs within 1,200 codepoints. When the first paragraph alone
    exceeds the budget, one entry: its exact prefix ending at the last sentence end that fits (same anchor_id)."""
    preview, used = [], 0
    for paragraph in paragraphs[:PREVIEW_ENTRIES]:
        if used + len(paragraph.text) > PREVIEW_CODEPOINTS:
            break
        preview.append({"text": paragraph.text, "anchor_id": str(paragraph.anchor_id)})
        used += len(paragraph.text)
    if not preview and paragraphs:
        prefix = sentence_prefix(paragraphs[0].text)
        if prefix:
            preview.append({"text": prefix, "anchor_id": str(paragraphs[0].anchor_id)})
    return preview


def reason_for(packet):
    if packet["legacy"]:
        return "Owner-authorized go-live, 23 Nov 2026: public-domain term evidence, text licence and owner cover provenance (" + CLEARANCE_DOC + ")."
    if packet.get("review_items"):
        ids = ", ".join(str(i.id) for i in packet["review_items"])
        return ("Owner approval on the Monday review page (D8): the draft record approved on the Monday page (review items " + ids
                + ", not an in-file approval) for public-domain term evidence, text licence and owner cover provenance ("
                + evidence_ref_for(packet) + ").")
    return ("Owner-authorized publication: public-domain term evidence, text licence and owner cover provenance ("
            + packet["clearance_path"] + "#sha256=" + packet["clearance_sha256"] + ").")


def clearance_document(packet):
    raw = (ROOT / packet["clearance_path"]).read_bytes()
    return json.loads(raw), sha256(raw)


def territories():
    return list(settings.MAISON_PUBLICATION_TERRITORIES)


def draft_for(packet):
    edition = Edition.objects.filter(slug=packet["edition_slug"]).first()
    if edition is None:
        return None
    return edition.revisions.order_by("-created_at").first()


def correction_record(packet):
    """The approved clearance record's source_correction block for this packet, or None for a first publication."""
    if packet.get("legacy") or not packet.get("clearance_path"):
        return None
    doc, _ = clearance_document(packet)
    book = (doc.get("books") or {}).get(packet.get("book_key", packet["slug"])) or {}
    correction = book.get("source_correction")
    return correction if isinstance(correction, dict) else None


def revise_revision_id(packet):
    """The deterministic ID of the revision the revise stage builds from this packet's approved source."""
    return stable_id(packet["slug"], "revise", sha256((Path(packet["folder"]) / "source.json").read_bytes()), "revision")


def _single_insertion(old, new, inserted):
    """True when `new` is `old` with `inserted` added once at one position."""
    if not inserted or len(new) != len(old) + len(inserted):
        return False
    start = len(os.path.commonprefix([old, new]))  # the insertion point is at most len(inserted) before this
    return any(old[:i] + inserted + old[i:] == new for i in range(max(0, start - len(inserted)), start + 1))


def check_approved_correction(packet, live, derived, live_units, changed, source_sha):
    """revise publishes only the correction the owner approved: the clearance record's source_correction names the
    source the live revision was built from and every changed paragraph; the changes derived from the approved
    source (bound by its sha256) must be exactly those, each with its recorded printed and transcription text."""
    slug = packet["slug"]
    record = correction_record(packet)
    if record is None:
        raise CommandError(f"{slug}: REVISE_CORRECTION_RECORD_REQUIRED: the approved clearance record has no source_correction.")
    doc, _ = clearance_document(packet)
    book = doc["books"][packet.get("book_key", slug)]
    if book.get("source_sha256") != source_sha:
        raise CommandError(f"{slug}: SOURCE_HASH_MISMATCH: source.json differs from the approved clearance record.")
    revises = record.get("revises") or {}
    live_sources = sorted(live.assets.filter(kind="reader_source").values_list("sha256", flat=True))
    if not revises.get("source_sha256") or live_sources != [revises["source_sha256"]]:
        raise CommandError(f"{slug}: REVISE_LIVE_SOURCE_MISMATCH: the live revision was built from {live_sources or 'no recorded source'}, "
                           f"not the source the approved correction revises ({revises.get('source_sha256')}).")
    changes = record.get("changes") or []
    approved = {(c.get("unit_key"), c.get("paragraph_ordinal")) for c in changes}
    found = {(key, n) for key, ordinals in changed.items() for n in ordinals}
    if len(approved) != len(changes) or approved != found:
        raise CommandError(f"{slug}: REVISE_CHANGES_DIFFER_FROM_APPROVED: the approved correction names "
                           f"{sorted(approved, key=str)}, but the source changes {sorted(found)}.")
    units = {row["key"]: (row, unit) for row, unit in zip(derived["units"], live_units)}
    for change in changes:
        row, unit = units[change["unit_key"]]
        n = change["paragraph_ordinal"]
        new, old = row["paragraphs"][n - 1]["text"], list(unit.paragraphs.all())[n - 1].text
        printed = str(change.get("printed", "")).strip("…")
        had = str(change.get("transcription_had", "")).strip("…")
        inserted = change.get("inserted")
        if (not printed or printed not in new or not had or had not in old
                or (inserted is not None and not _single_insertion(old, new, inserted))):
            raise CommandError(f"{slug}: REVISE_CHANGES_DIFFER_FROM_APPROVED: {change['unit_key']} paragraph {n} does not "
                               "carry exactly the approved correction.")


def target_revision(packet):
    """The revision evidence and publish act on. For a correction packet this is exactly the revise stage's
    revision for the approved source sha; a different newest revision (another draft) is refused."""
    revision = draft_for(packet)
    if correction_record(packet) is None:
        return revision
    expected = revise_revision_id(packet)
    if revision is None or revision.id != expected:
        raise CommandError(f"{packet['slug']}: REVISE_TARGET_MISMATCH: the approved correction is revision {expected}, "
                           f"but the newest revision is {revision.id if revision else 'none'}; run revise or reconcile the other revision.")
    return revision


def read_translation(folder, intake=None):
    """Validated translation labels from a packet's translation.json, or None for a plain packet."""
    path = Path(folder) / "translation.json"
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        for key in ("translated_from", "method", "credit", "model", "source_sha256"):
            if not isinstance(record[key], str):
                raise TypeError(key)
    except (ValueError, KeyError, TypeError):
        raise CommandError("TRANSLATION_JSON_INVALID: translation.json is not valid or lacks required keys")
    source_dir = Path(intake or INTAKE) / record["translated_from"]
    try:
        source_raw = (source_dir / "source.json").read_bytes()
        source_slug = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))["edition"]["slug"]
    except (FileNotFoundError, ValueError, KeyError):
        raise CommandError(f"SOURCE_EDITION_MISSING: no source packet {record['translated_from']}")
    if sha256(source_raw) != record["source_sha256"]:
        raise CommandError("SOURCE_PACKET_HASH_MISMATCH: the source packet changed after this translation was made")
    source = Edition.objects.filter(slug=source_slug).first()
    if source is None:
        raise CommandError(f"SOURCE_EDITION_MISSING: import {source_slug} before its translation")
    return {"translated_from": source, "translation_method": record["method"],
            "translation_credit": record["credit"], "translation_model": record["model"]}


def apply_translation(edition, translation):
    for field, value in translation.items():
        setattr(edition, field, value)
    edition.full_clean()
    edition.save(update_fields=list(translation))


def require_translation_labels(packet):
    """Publish/evidence guard: an edition built from a translation packet must carry its labels."""
    translation = read_translation(packet["folder"])
    if translation is None:
        return
    edition = Edition.objects.filter(slug=packet["edition_slug"]).first()
    if edition is None or any(getattr(edition, field + "_id" if field == "translated_from" else field)
                              != (value.pk if field == "translated_from" else value)
                              for field, value in translation.items()):
        raise CommandError(f"TRANSLATION_LABELS_MISSING: {packet['slug']} lacks the translation labels from translation.json")


class Command(BaseCommand):
    help = "Import, evidence and publish the owner-cleared editions without a web staff session."

    def add_arguments(self, parser):
        parser.add_argument("stage", choices=("import", "revise", "evidence", "publish", "status"))
        parser.add_argument("--publisher", required=True, help="public_id of an active verified staff publisher")
        parser.add_argument("--book", action="append", choices=sorted(approved_packets(check=())), help="limit to these books")
        parser.add_argument("--all", action="store_true", help="act on every approved book (required for evidence/publish without --book)")
        parser.add_argument("--browser-report", help="repo-relative browser acceptance report (evidence stage)")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(public_id=options["publisher"], is_active=True, is_staff=True).first()
        if actor is None or not actor.is_verified or not actor.has_perm("library.publish_revision"):
            raise CommandError("An active verified staff publisher with library.publish_revision is required.")
        if options["stage"] == "revise" and not options["book"]:
            raise CommandError("BOOK_REQUIRED: the revise stage needs --book <slug>.")
        if options["stage"] in ("evidence", "publish") and not options["book"] and not options["all"]:
            raise CommandError(f"BOOK_REQUIRED: the {options['stage']} stage needs --book <slug> or --all.")
        out = {}
        chosen = options["book"] or sorted(approved_packets(check=()))
        packets = approved_packets(check=set(chosen))
        for slug in import_order(chosen, packets):
            packet = packets[slug]
            stage = options["stage"]
            if stage == "import":
                out[slug] = self.import_book(actor, packet) if packet["import"] else {"skipped": "already imported"}
            elif stage == "revise":
                if packet["legacy"]:
                    raise CommandError(f"{slug}: REVISE_NOT_SUPPORTED: legacy books keep their 23 Nov 2026 record.")
                out[slug] = self.revise_book(actor, packet)
            elif stage == "evidence":
                out[slug] = self.record_evidence(actor, packet, options.get("browser_report"))
            elif stage == "publish":
                out[slug] = self.publish(actor, packet)
            out.setdefault(slug, {}).update(self.status(packet))
        self.stdout.write("MAISON_OUT " + json.dumps(out, ensure_ascii=False, default=str))

    # --- import -------------------------------------------------------------------------------
    def import_book(self, actor, packet):
        slug, folder = packet["slug"], Path(packet["folder"])
        manifest = json.loads((folder / "manifest.json").read_text())
        raw = (folder / "source.json").read_bytes()
        if sha256(raw) != manifest["source"]["sha256"] or len(raw) != manifest["source"]["bytes"]:
            raise CommandError("Intake source differs from its manifest.")
        translation = read_translation(folder)
        revision = draft_for(packet)
        if revision is None:
            _, started = start_import(actor, manifest, str(stable_id(slug, "start")))[:2]
            revision = Revision.objects.get(pk=started["edition_revision_id"])
        record = revision.validation_evidence.get("general_source_import", {})
        if record.get("state") == "AWAITING_SOURCE":
            source_id = stable_id(slug, "reader_source", manifest["source"]["sha256"])
            key = f"revisions/{revision.id}/{source_id}"
            storage.put_private(key, raw, "application/json")
            asset, _ = Asset.objects.get_or_create(id=source_id, defaults=dict(revision=revision, kind="reader_source",
                state="ready", storage_key=key, sha256=sha256(raw), bytes=len(raw), content_type="application/json"))
            audit(actor, "asset.complete", asset, {"sha256": asset.sha256, "kind": asset.kind, "channel": "server_job"})
            revision.refresh_from_db()
            finalize_import(actor, revision.edition_id, {"edition_revision_id": str(revision.id),
                "source_asset_id": str(asset.id), "source_sha256": asset.sha256, "source_bytes": asset.bytes},
                revision.version, str(stable_id(slug, "finalize")))
            revision.refresh_from_db()
        if revision.state != "draft":
            return {"note": "revision is no longer a draft; nothing changed (a corrected source of a live edition uses the revise stage)"}
        if translation:
            apply_translation(revision.edition, translation)
        self.attach_covers(actor, revision, folder)
        self.offer_reader(actor, revision, packet)
        return {"imported": True}

    # --- revise -------------------------------------------------------------------------------
    def revise_book(self, actor, packet):
        """A corrected source for an edition that is already live becomes a NEW draft revision of that edition.

        A live revision is frozen (Revision.clean and the PostgreSQL guards), so a correction is never made in place.
        The new revision follows clone_revision's rules: the same edition, anchor_revision + 1 and fresh anchors
        (anchor_id is unique across revisions); Reader resume moves to the same chapter's start and annotations on the
        old revision stay as orphaned quotes (reader.services). Only paragraph text may change: units, unit titles,
        kinds and paragraph counts must equal the live revision's, so a translation stays paired by ordinal and kind.
        IDs derive from the corrected source sha256, so a rerun reuses the same draft. Covers, Reader access, preview
        and rights then follow the import stage (attach_covers, offer_reader); evidence and publish are unchanged."""
        reverify_approval(packet)
        slug, folder = packet["slug"], Path(packet["folder"])
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        raw = (folder / "source.json").read_bytes()
        source_sha = sha256(raw)
        if source_sha != manifest["source"]["sha256"] or len(raw) != manifest["source"]["bytes"]:
            raise CommandError("Intake source differs from its manifest.")
        edition = Edition.objects.filter(slug=packet["edition_slug"]).first()
        if edition is None or edition.live_revision_id is None:
            raise CommandError(f"{slug}: REVISE_NEEDS_LIVE_EDITION: import and publish the first revision instead.")
        revision_id = stable_id(slug, "revise", source_sha, "revision")
        revision = Revision.objects.filter(pk=revision_id).first()
        if revision is None:
            latest = draft_for(packet)
            if latest.id != edition.live_revision_id:
                raise CommandError(f"{slug}: REVISE_PENDING_REVISION: revision {latest.id} ({latest.state}) is newer than "
                                   "the live revision; reconcile it first.")
            revision = self.build_revision(actor, packet, edition, latest, manifest, raw, source_sha, revision_id)
        if revision.state != "draft":
            return {"note": "revision is no longer a draft; nothing changed"}
        self.attach_covers(actor, revision, folder)
        self.offer_reader(actor, revision, packet)
        record = revision.validation_evidence.get("source_revision", {})
        return {"revised": True, "replaces_revision_id": record.get("replaces_revision_id"),
                "changed_paragraphs": record.get("changed_paragraphs")}

    def build_revision(self, actor, packet, edition, live, manifest, raw, source_sha, revision_id):
        slug = packet["slug"]
        media = sorted(set(live.assets.exclude(kind__in=REVISE_REBUILT_KINDS).values_list("kind", flat=True)))
        if media:
            raise CommandError(f"{slug}: REVISE_LIVE_HAS_MEDIA: the live revision {live.id} holds {', '.join(media)} assets. "
                               "revise rebuilds only reader packages, the reader source and covers, so publishing its draft "
                               "would drop them. Media made from the old text would no longer match the corrected text and "
                               "must be re-made from the corrected revision, not carried over; nothing was changed.")
        try:
            source = read_source_bytes(raw)
            derived, transform = reader_derivative(source, source_sha)
            batches = reader_batches(source)
            manifest_sha = validate_manifest(manifest)
        except (SourceError, ValueError, TypeError, KeyError):
            raise CommandError(f"{slug}: INVALID_BOOK_SOURCE: the corrected source must match the bounded source schema.") from None
        if source["language"] != edition.locale:
            raise CommandError(f"{slug}: SOURCE_LANGUAGE_MISMATCH: the source language differs from the edition.")
        live_units = list(live.units.order_by("ordinal").prefetch_related("paragraphs"))
        live_shape = [(u.title, u.kind, [p.kind for p in u.paragraphs.all()]) for u in live_units]
        new_shape = [(row["title"], row["kind"], [p["kind"] for p in row["paragraphs"]]) for row in derived["units"]]
        if live_shape != new_shape:
            raise CommandError(f"{slug}: REVISION_STRUCTURE_CHANGED: units, titles, kinds and paragraph counts must equal "
                               "the live revision; only paragraph text may be corrected.")
        changed = {row["key"]: [n for n, (p, old) in enumerate(zip(row["paragraphs"], unit.paragraphs.all()), 1) if p["text"] != old.text]
                   for row, unit in zip(derived["units"], live_units)}
        changed = {key: ordinals for key, ordinals in changed.items() if ordinals}
        if not changed:
            raise CommandError(f"{slug}: NOTHING_TO_REVISE: the source text equals the live revision.")
        check_approved_correction(packet, live, derived, live_units, changed, source_sha)
        revision = Revision(id=revision_id, edition=edition, title=live.title, description=live.description,
            anchor_revision=live.anchor_revision + 1, access_policy=dict(DENIED), download_policy=dict(NO_DOWNLOADS), preview=[])
        units, paragraphs, groups = [], [], []
        for ordinal, (row, unit_batches, old) in enumerate(zip(derived["units"], batches, live_units), 1):
            label = f"{source_sha}:{row['key']}"
            unit = Unit(id=stable_id(slug, "revise", label, "unit"), revision=revision, title=row["title"], kind=row["kind"],
                        ordinal=ordinal, duration_ms=old.duration_ms, preview=old.preview)
            rows = [Paragraph(id=stable_id(slug, "revise", label, "paragraph", n), anchor_id=stable_id(slug, "revise", label, "anchor", n),
                              unit=unit, ordinal=n, kind=p["kind"], text=p["text"]) for n, p in enumerate(row["paragraphs"], 1)]
            for number, indexes in enumerate(unit_batches):
                groups.append((unit, [rows[i] for i in indexes], stable_id(slug, "revise", label, "chunk", number)))
            units.append(unit)
            paragraphs.extend(rows)
        revision.content_sha256 = digest(canonical_bytes([{"unit_id": str(u.id), "title": u.title, "ordinal": u.ordinal,
            "paragraphs": [paragraph_dto(p) for p in paragraphs if p.unit_id == u.id]} for u in units]))
        packages = [prepare_reader_package(unit, chunk, asset_id=asset_id) for unit, chunk, asset_id in groups]
        source_id = stable_id(slug, "revise", source_sha, "reader_source")
        key = f"revisions/{revision.id}/{source_id}"
        storage.put_private(key, raw, "application/json")
        source_asset = Asset(id=source_id, revision=revision, kind="reader_source", state="ready", storage_key=key,
                             sha256=source_sha, bytes=len(raw), content_type="application/json")
        live_source = (live.validation_evidence.get("general_source_import") or {}).get("manifest", {}).get("source", {}).get("sha256")
        revision.validation_evidence = {"source_revision": {
            "schema": "earnalism.source_revision.v1", "manifest_sha256": manifest_sha, "source_sha256": source_sha,
            "source_bytes": len(raw), "source_asset_id": str(source_id), "source_transform": transform,
            "replaces_revision_id": str(live.id), "replaces_content_sha256": live.content_sha256,
            "replaces_source_sha256": live_source, "anchor_revision": revision.anchor_revision,
            "changed_paragraphs": changed, "reader_asset_ids": [str(a.id) for a in packages],
            # Every unit and paragraph, old -> new (like clone_revision's anchor_map); publish moves reader state with it.
            "unit_map": {str(old.id): str(new.id) for old, new in zip(live_units, units)},
            "anchor_map": {str(old.anchor_id): str(new.anchor_id) for old_unit, new_unit in zip(live_units, units)
                           for old, new in zip(old_unit.paragraphs.all(), [p for p in paragraphs if p.unit_id == new_unit.id])},
            "clearance_ref": packet["clearance_path"] + "#sha256=" + packet["clearance_sha256"],
            "rights_approval_created": False, "publication": False}}
        with transaction.atomic():
            current = Edition.objects.select_for_update().get(pk=edition.pk)
            if current.live_revision_id != live.id or Revision.objects.filter(pk=revision_id).exists():
                raise CommandError(f"{slug}: version_conflict: the edition changed while the corrected revision was prepared.")
            revision.save()
            Unit.objects.bulk_create(units)
            Paragraph.objects.bulk_create(paragraphs, batch_size=1000)
            for package in packages:  # Reader coverage orders packages by created_at, then id
                package.save()
            source_asset.save()
            audit(actor, "book.source_revision", revision, {"source_sha256": source_sha, "replaces_revision_id": str(live.id),
                "changed_paragraphs": changed, "anchor_revision": revision.anchor_revision, "channel": "server_job"})
        revision.refresh_from_db()
        return revision

    def attach_covers(self, actor, revision, folder):
        pair = dict(revision.validation_evidence.get("cover_pair", {}))
        for side in ("front", "back"):
            raw = (folder / f"{side}.jpg").read_bytes()
            digest = sha256(raw)
            if pair.get(side, {}).get("sha256") == digest:
                continue
            asset_id = stable_id(revision.id, "cover", side, digest)
            key = f"revisions/{revision.id}/{asset_id}"
            storage.put_private(key, raw, "image/jpeg")
            asset, _ = Asset.objects.get_or_create(id=asset_id, defaults=dict(revision=revision, kind="cover", state="ready",
                storage_key=key, sha256=digest, bytes=len(raw), content_type="image/jpeg"))
            audit(actor, "asset.complete", asset, {"sha256": digest, "kind": "cover", "side": side, "channel": "server_job"})
            pair[side] = {"asset_id": str(asset.id), "sha256": digest, "bytes": len(raw), "width": 800, "height": 1200}
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=revision.pk)
            current.validation_evidence = {**current.validation_evidence, "cover_pair": pair}
            current.version += 1
            current.save()
        revision.refresh_from_db()

    def offer_reader(self, actor, revision, packet):
        reverify_approval(packet)
        first = revision.units.order_by("ordinal").first()
        paragraphs = [p for p in first.paragraphs.order_by("ordinal") if p.kind == "paragraph"]
        preview = preview_entries(paragraphs)
        if not preview:
            raise CommandError("No bounded preview paragraph is available.")
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=revision.pk)
            current.access_policy = {"reader": "free", "audio": "deny", "video": "deny"}
            current.download_policy = {}
            current.preview = preview
            current.version += 1
            current.save()
            if not current.rights.exists():
                doc, doc_sha = clearance_document(packet)
                now = timezone.now()
                evidence = json.dumps({"territories": territories(), "evidence_ref": evidence_ref_for(packet) if packet.get("review_items") else f"{packet['clearance_path']}#sha256={doc_sha}",
                    "basis": "draft record approved on the Monday page (review items " + ", ".join(str(i.id) for i in packet["review_items"]) + ")"
                    if packet.get("review_items") else "owner-authorized public-domain term evidence"}, ensure_ascii=False)
                for action in ("read", "preview"):
                    right = Rights.objects.create(revision=current, format="reader", action=action, territories=territories(),
                        starts_at=now, ends_at=now + timedelta(days=3650), approved=True, test_only=False, evidence=evidence)
                    audit(actor, "rights.create", right, {"action": action, "territories": territories(), "channel": "server_job"})

    # --- evidence -----------------------------------------------------------------------------
    def record_evidence(self, actor, packet, report_path):
        slug = packet["slug"]
        require_translation_labels(packet)
        revision = target_revision(packet)
        if revision is None or revision.state != "draft":
            raise CommandError(f"{slug}: a draft revision is required.")
        doc, doc_sha = clearance_document(packet)
        book = doc["books"][packet.get("book_key", slug)]
        if set(doc["territories"]) != set(territories()) or doc["formats"] != ["reader"]:
            raise CommandError("Clearance document scope differs from the active whitelist/offered formats.")
        if book.get("maison_revision_content_sha256") not in (None, revision.content_sha256):
            raise CommandError(f"{slug}: clearance document names a different text hash.")
        covers = {a.sha256 for a in revision.assets.filter(kind="cover", state="ready")}
        pair = revision.validation_evidence.get("cover_pair", {})
        if {pair.get("front", {}).get("sha256"), pair.get("back", {}).get("sha256")} != set(packet["covers"]) or not covers:
            raise CommandError(f"{slug}: selected cover pair differs from the cleared artwork.")
        browser = None
        if report_path:
            raw = (ROOT / report_path).read_bytes()
            report = json.loads(raw)
            entry = report["books"].get(slug, {})
            if entry.get("status") != "pass" or entry.get("sha256") != revision.content_sha256:
                raise CommandError(f"{slug}: browser report does not pass for this exact text hash.")
            browser = {"status": "pass", "sha256": revision.content_sha256, "scope": report["scope"],
                "report": f"{report_path}#sha256={sha256(raw)}", "recorded_at": timezone.now().isoformat()}
        ready = list(revision.assets.filter(state="ready"))
        clearance = {"status": "pass", "sha256": revision.content_sha256, "territories": territories(), "formats": ["reader"],
            "asset_sha256": {str(a.id): a.sha256 for a in ready},
            "evidence_ref": evidence_ref_for(packet) if packet.get("review_items") else f"{packet['clearance_path']}#sha256={doc_sha}",
            "basis": "draft_record_approved_on_monday_page" if packet.get("review_items") else "owner_authorized_public_domain_term_evidence", "recorded_by": str(actor.public_id),
            "recorded_at": timezone.now().isoformat()}
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=revision.pk)
            if current.content_sha256 != revision.content_sha256:
                raise CommandError(f"{slug}: text changed while recording evidence.")
            evidence = {**current.validation_evidence, "publication_clearance": clearance}
            if browser:
                evidence["browser"] = browser
            current.validation_evidence = evidence
            current.version += 1
            current.save()
            audit(actor, "revision.evidence", current, {"publication_clearance": clearance["evidence_ref"],
                "browser": browser and browser["report"], "channel": "server_job"})
        return {"evidence_recorded": True}

    # --- publish ------------------------------------------------------------------------------
    def publish(self, actor, packet):
        reverify_approval(packet)
        require_translation_labels(packet)
        revision = target_revision(packet)
        if revision is None:
            raise CommandError(f"{packet['slug']}: no revision.")
        reason = reason_for(packet)
        steps = []
        for action in ("mark-ready", "publish"):
            revision.refresh_from_db()
            if (action == "mark-ready" and revision.state != "draft") or (action == "publish" and revision.state != "ready"):
                continue
            state = transition_revision(actor, revision.id, action, revision.version, revision.content_sha256, reason)
            audit(actor, "revision." + action, revision, {"reason": reason, "channel": "server_job"})
            step = {"action": action, "state": state["state"], "version": state["version"]}
            # transition_revision moves readers' state for a revise revision (library.services.move_reader_state).
            moved = AuditEvent.objects.filter(action="revision.reader_state_moved", entity_id=str(revision.id),
                                              detail__pass="publish").order_by("-created_at").first()
            if action == "publish" and moved:
                step["reader_state_moved"] = {k: moved.detail[k] for k in ("progress", "annotations", "left_unmapped")}
            steps.append(step)
        return {"steps": steps}

    # --- status -------------------------------------------------------------------------------
    def status(self, packet):
        revision = draft_for(packet)
        if revision is None:
            return {"exists": False}
        report = validate_revision(revision, prepared=prepare_revision_validation(revision.id))
        return {"edition_id": str(revision.edition_id), "revision_id": str(revision.id), "state": revision.state,
            "version": revision.version, "sha256": revision.content_sha256,
            "live": str(revision.edition.live_revision_id) if revision.edition.live_revision_id else None,
            "units": revision.units.count(), "paragraphs": sum(u.paragraphs.count() for u in revision.units.all()),
            "checks": {c["code"]: c["status"] for c in report["checks"]}}
