"""Owner-authorized server-side publication of exact cleared editions (23 Nov 2026).

Runs the same audited services the staff API uses -- general source import, asset
storage, rights rows, validation and transition_revision -- as a named verified
publisher, so no web staff session is needed. Every publication check still runs;
nothing here skips validate_revision. Each stage is idempotent and hash-bound.

Stages: import (create the বিচারক draft from library/intake/bicharak), evidence
(record clearance + browser acceptance against the exact text and asset hashes),
publish (mark-ready then publish). Output is JSON on stdout; no secrets are printed.
"""
import hashlib
import json
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
from library.general_import import finalize_import, start_import
from library.models import Asset, Edition, Revision, Rights
from library.services import prepare_revision_validation, transition_revision, validate_revision

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


PREVIEW_ENTRIES, PREVIEW_CODEPOINTS = 3, 1200  # the approved bounds library.services.get_preview_document enforces
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
        return ("Owner approval on the Monday review page (D8): public-domain term evidence, text licence and owner cover provenance ("
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
        parser.add_argument("stage", choices=("import", "evidence", "publish", "status"))
        parser.add_argument("--publisher", required=True, help="public_id of an active verified staff publisher")
        parser.add_argument("--book", action="append", choices=sorted(approved_packets(check=())), help="limit to these books")
        parser.add_argument("--all", action="store_true", help="act on every approved book (required for evidence/publish without --book)")
        parser.add_argument("--browser-report", help="repo-relative browser acceptance report (evidence stage)")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(public_id=options["publisher"], is_active=True, is_staff=True).first()
        if actor is None or not actor.is_verified or not actor.has_perm("library.publish_revision"):
            raise CommandError("An active verified staff publisher with library.publish_revision is required.")
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
            return {"note": "revision is no longer a draft; nothing changed"}
        if translation:
            apply_translation(revision.edition, translation)
        self.attach_covers(actor, revision, folder)
        self.offer_reader(actor, revision, packet)
        return {"imported": True}

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
                    "basis": "owner-authorized public-domain term evidence"}, ensure_ascii=False)
                for action in ("read", "preview"):
                    right = Rights.objects.create(revision=current, format="reader", action=action, territories=territories(),
                        starts_at=now, ends_at=now + timedelta(days=3650), approved=True, test_only=False, evidence=evidence)
                    audit(actor, "rights.create", right, {"action": action, "territories": territories(), "channel": "server_job"})

    # --- evidence -----------------------------------------------------------------------------
    def record_evidence(self, actor, packet, report_path):
        slug = packet["slug"]
        require_translation_labels(packet)
        revision = draft_for(packet)
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
            "basis": "owner_authorized_public_domain_term_evidence", "recorded_by": str(actor.public_id),
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
        revision = draft_for(packet)
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
            steps.append({"action": action, "state": state["state"], "version": state["version"]})
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
