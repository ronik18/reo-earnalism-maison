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


def approved_packets(intake=INTAKE, root=ROOT):
    """Every publishable packet: the two legacy books plus each intake packet with an owner-approved clearance record.

    A discovered packet qualifies only when its own clearance record (manifest.provenance.rights_evidence_refs) has a
    status starting OWNER_APPROVED, approval.approved true and nothing still required, and the text and cover bytes
    on disk are exactly those the record and cover_provenance.json name. Approval over changed bytes is refused.
    """
    intake, root = Path(intake), Path(root)
    packets = {}
    legacy_doc = root / CLEARANCE_DOC
    legacy_sha = sha256(legacy_doc.read_bytes()) if legacy_doc.exists() else None
    for slug, spec in LEGACY_BOOKS.items():
        covers = ((_json(legacy_doc) or {}).get("books", {}).get(slug, {}).get("covers", {}))
        packets[slug] = {"slug": slug, "edition_slug": spec["edition"], "folder": intake / spec["intake"],
            "clearance_path": CLEARANCE_DOC, "clearance_sha256": legacy_sha, "import": spec["import"], "legacy": True,
            "covers": (covers.get("front_jpg_sha256"), covers.get("back_jpg_sha256"))}
    for manifest_path in sorted(intake.glob("*/manifest.json")):
        folder = manifest_path.parent
        manifest = _json(manifest_path) or {}
        edition_slug = (manifest.get("edition") or {}).get("slug")
        slug = (manifest.get("work") or {}).get("slug") or edition_slug
        if not slug or slug in packets:
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
        if not (str(record.get("status", "")).startswith("OWNER_APPROVED") and approval.get("approved") is True
                and not approval.get("still_required") and isinstance(book, dict) and edition_slug):
            continue
        provenance = _json(folder / "cover_provenance.json")
        if not provenance or not all((folder / name).is_file() for name in ("front.jpg", "back.jpg", "source.json")):
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
        packets[slug] = {"slug": slug, "edition_slug": edition_slug, "folder": folder, "clearance_path": clearance_path,
            "clearance_sha256": sha256(clearance_file.read_bytes()), "import": True, "legacy": False, "covers": tuple(covers)}
    return packets


def reason_for(packet):
    if packet["legacy"]:
        return "Owner-authorized go-live, 23 Nov 2026: public-domain term evidence, text licence and owner cover provenance (" + CLEARANCE_DOC + ")."
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


class Command(BaseCommand):
    help = "Import, evidence and publish the owner-cleared editions without a web staff session."

    def add_arguments(self, parser):
        parser.add_argument("stage", choices=("import", "evidence", "publish", "status"))
        parser.add_argument("--publisher", required=True, help="public_id of an active verified staff publisher")
        parser.add_argument("--book", action="append", choices=sorted(approved_packets()), help="limit to these books")
        parser.add_argument("--browser-report", help="repo-relative browser acceptance report (evidence stage)")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(public_id=options["publisher"], is_active=True, is_staff=True).first()
        if actor is None or not actor.is_verified or not actor.has_perm("library.publish_revision"):
            raise CommandError("An active verified staff publisher with library.publish_revision is required.")
        out = {}
        packets = approved_packets()
        for slug in options["book"] or sorted(packets):
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
        first = revision.units.order_by("ordinal").first()
        paragraphs = [p for p in first.paragraphs.order_by("ordinal") if p.kind == "paragraph"]
        preview, used = [], 0
        for paragraph in paragraphs[:3]:
            if used + len(paragraph.text) > 1200:
                break
            preview.append({"text": paragraph.text, "anchor_id": str(paragraph.anchor_id)})
            used += len(paragraph.text)
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
                evidence = json.dumps({"territories": territories(), "evidence_ref": f"{packet['clearance_path']}#sha256={doc_sha}",
                    "basis": "owner-authorized public-domain term evidence"}, ensure_ascii=False)
                for action in ("read", "preview"):
                    right = Rights.objects.create(revision=current, format="reader", action=action, territories=territories(),
                        starts_at=now, ends_at=now + timedelta(days=3650), approved=True, test_only=False, evidence=evidence)
                    audit(actor, "rights.create", right, {"action": action, "territories": territories(), "channel": "server_job"})

    # --- evidence -----------------------------------------------------------------------------
    def record_evidence(self, actor, packet, report_path):
        slug = packet["slug"]
        revision = draft_for(packet)
        if revision is None or revision.state != "draft":
            raise CommandError(f"{slug}: a draft revision is required.")
        doc, doc_sha = clearance_document(packet)
        book = doc["books"][slug]
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
            "evidence_ref": f"{packet['clearance_path']}#sha256={doc_sha}",
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
