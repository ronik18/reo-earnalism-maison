"""Export the exact live text of one edition for the earnalism-audiovisual skill (read-only).

Writes {"language", "units": [{"unit_id", "title", "paragraphs": [{"anchor_id", "kind", "text"}]}],
"edition_id", "revision_id", "content_sha256", "rights": {format: [actions]}, "public_domain_evidence"}
plus "state", "assets" (ready assets: id, kind, unit, sha256, bytes, content type, duration) and
"timing_maps" (measured maps with their exact segments). By default it reads the edition's live
revision and refuses when there is none. --revision <id> exports one revision of that edition in any
state -- e.g. a staged audio DRAFT -- with its exact unit/paragraph/anchor ids, so the owner's pipeline
can rebuild an identical local replica and browser-test it against the same content_sha256.
content_sha256 is recomputed from the exported rows and must equal the stored revision hash, so the
file is the exact text of that revision. Nothing is mutated.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from django.core.exceptions import ValidationError

from library.models import Edition, Revision
from library.services import local_fixtures_enabled, revision_hash


def live_revision(slug):
    edition = Edition.objects.select_related("live_revision").filter(slug=slug).first()
    if edition is None:
        raise CommandError(f"{slug}: edition not found.")
    revision = edition.live_revision
    if revision is None or revision.state != "live":
        raise CommandError(f"{slug}: edition has no live revision; nothing to export.")
    return edition, revision


def edition_revision(slug, revision_id):
    edition = Edition.objects.filter(slug=slug).first()
    if edition is None:
        raise CommandError(f"{slug}: edition not found.")
    try:
        return edition, Revision.objects.get(pk=revision_id, edition=edition)
    except (Revision.DoesNotExist, ValueError, ValidationError):
        raise CommandError(f"{slug}: revision {revision_id} is not a revision of this edition.") from None


def current_rights(revision):
    now = timezone.now()
    rights = {}
    for right in revision.rights.filter(approved=True, starts_at__lte=now, ends_at__gt=now):
        if right.test_only and not local_fixtures_enabled():
            continue
        rights.setdefault(right.format, set()).add(right.action)
    return {fmt: sorted(actions) for fmt, actions in sorted(rights.items())}


def has_public_domain_evidence(revision):
    clearance = revision.validation_evidence.get("publication_clearance")
    return bool(isinstance(clearance, dict) and clearance.get("status") == "pass"
                and clearance.get("sha256") == revision.content_sha256)


def source_document(edition, revision):
    if revision_hash(revision) != revision.content_sha256:
        raise CommandError(f"{edition.slug}: live text differs from its recorded hash; refusing to export.")
    units = [{"unit_id": str(unit.id), "title": unit.title,
              "paragraphs": [{"anchor_id": str(p.anchor_id), "kind": p.kind, "text": p.text}
                             for p in unit.paragraphs.order_by("ordinal")]}
             for unit in revision.units.order_by("ordinal")]
    return {"language": edition.locale, "units": units, "edition_id": str(edition.id), "revision_id": str(revision.id),
            "content_sha256": revision.content_sha256, "rights": current_rights(revision),
            "public_domain_evidence": has_public_domain_evidence(revision), "state": revision.state,
            "assets": [{"asset_id": str(a.id), "kind": a.kind, "unit_id": str(a.unit_id) if a.unit_id else None,
                        "sha256": a.sha256, "bytes": a.bytes, "content_type": a.content_type, "duration_ms": a.duration_ms}
                       for a in revision.assets.filter(state="ready").order_by("kind", "created_at", "id")],
            "timing_maps": [{"map_id": str(m.id), "asset_id": str(m.asset_id), "asset_sha256": m.asset_sha256,
                             "text_sha256": m.text_sha256, "precision": m.precision, "segments": m.segments}
                            for m in revision.timing_maps.filter(measured=True).order_by("asset__unit__ordinal", "id")]}


class Command(BaseCommand):
    help = "Write the exact text of one edition (live, or --revision <id>) as audiovisual source JSON (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("edition_slug")
        parser.add_argument("--out", required=True, help="output JSON path")
        parser.add_argument("--revision", help="export this revision of the edition (any state) instead of the live one")

    def handle(self, *args, **options):
        if options.get("revision"):
            edition, revision = edition_revision(options["edition_slug"], options["revision"])
        else:
            edition, revision = live_revision(options["edition_slug"])
        document = source_document(edition, revision)
        Path(options["out"]).write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.stdout.write("MAISON_OUT " + json.dumps({"edition_id": document["edition_id"], "revision_id": document["revision_id"],
            "state": document["state"], "content_sha256": document["content_sha256"], "units": len(document["units"]),
            "paragraphs": sum(len(u["paragraphs"]) for u in document["units"]), "out": options["out"]}))
