"""Stage owner-cleared chapter narration on a clone of a live edition, then publish it after a fresh
browser acceptance of that exact staged revision (server job, 23 Nov 2026; controller ruling R6).

  attach_audiovisual_audio stage <slug> --publisher <public_id> --bundle <dir> --evidence <docs/evidence/...json>
  attach_audiovisual_audio publish <slug> --publisher <public_id> --browser-report <repo-relative json>

Same audited path as publish_cleared_editions: a named active verified staff publisher, private
storage, rights rows, validation evidence and library.services.transition_revision. Nothing here
skips validate_revision; mark-ready and publish fail closed unless every check passes.

Bundle layout (--bundle <dir>), nothing else is accepted:

  <dir>/timing.json   {"units": [{"unit_id": "<live unit id>", "mp3": "<file name in dir>",
                                  "segments": [{"anchor_id": "<live paragraph anchor>",
                                                "start_offset_chars": 0, "end_offset_chars": <len>,
                                                "start_ms": <int>, "end_ms": <int>}, ...]}, ...]}
  <dir>/<file>.mp3    one chapter MP3 per listed unit; a single mp3 audio stream at exactly 48 or
                      96 kbps (ffprobe-measured; the measured duration becomes the unit duration).

unit_id/anchor_id are the ids written by export_audiovisual_source for the current live revision.
Segments follow library.timing.validated_segments: ordered, non-overlapping in time, ending within
the measured duration, and per paragraph contiguous character ranges that together cover every
paragraph of the unit exactly (start_offset_chars of a paragraph's first segment is 0, its last
end_offset_chars is the paragraph length). Any other file -- video in particular -- is refused:
Stream hosting is held until the owner approves its cost.

--evidence is a repo-relative JSON under docs/evidence/ (schema
earnalism.audiovisual-clearance-evidence.v1) naming edition_slug, source_content_sha256 (the live
text the narration speaks), territories (= the active whitelist), formats ["reader", "audio"] and
audio_sha256 (exactly the bundle MP3 hashes), plus owner_approval {"by": <who>, "at": <when>}; a
status starting with "DRAFT" is refused (the skill drafts the record, only the owner approves it). The live revision must already carry passing
public-domain publication_clearance; other titles are refused.

stage: clone the live revision; store each MP3 privately as an audio_chapter asset bound to its unit
(storage.put_private_file: streamed and create-once, because chapter MP3s exceed put_private's 4 MiB
cap); record ffprobe measurement and offline piece proofs; create one measured TimingMap per asset
(anchors remapped to the clone by unit/paragraph ordinal); set access audio=free; re-approve the
copied reader rights that were approved and non-test on the live revision, citing the new evidence
document (clone_revision resets approval by design), and add approved non-test audio read rights for
the whitelist (no audio preview); record publication_clearance for formats reader+audio bound to every
ready asset hash and the evidence document sha256. The clone stays a DRAFT with no browser evidence;
stage prints its revision_id, content_sha256 and ready-asset hashes. A rerun with the same bundle
reports the existing staged draft (resuming an unfinished one) and never makes a second clone; once
published it reports already_live. Replacing audio that a live revision already carries is refused.

Export the staged draft with `export_audiovisual_source <slug> --revision <revision_id>` to rebuild an
identical replica and browser-test the reader and the audio player against the same content_sha256.

publish: --browser-report is a repo-relative JSON {"sha256": <staged content_sha256>, "status": "pass",
"scope": "...", "checks": {"audio_playback": true, ...}}. It must name the staged revision's exact hash,
pass, and cover audio playback; it is then recorded as the draft's browser evidence, and mark-ready and
publish run through transition_revision (full validate_revision) in one transaction. Any mismatch or
failed check raises CommandError and changes nothing.
"""
import hashlib
import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.api import DomainError
from core.services import audit
from library import storage
from library.models import Asset, Paragraph, Revision, Rights, TimingMap
from library.production_handoff import HandoffError, measure_mp3
from library.services import (canonical_bytes, clone_revision, digest, prepare_revision_validation, transition_revision,
                              validate_revision)
from library.timing import validated_segments
from operations.management.commands.export_audiovisual_source import has_public_domain_evidence, live_revision
from operations.management.commands.publish_cleared_editions import ROOT, sha256, stable_id, territories

EVIDENCE_SCHEMA = "earnalism.audiovisual-clearance-evidence.v1"
STREAM_HELD = ("Stream hosting held: the owner has not approved Stream hosting cost, so only timing.json and chapter "
               "MP3 files are accepted; remove {name!r} from the bundle.")
MAX_TIMING_BYTES = 4 * 1024 * 1024


def file_sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as stream:
        while block := stream.read(storage.CHUNK_BYTES):
            hasher.update(block)
    return hasher.hexdigest()


def read_bundle(folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise CommandError(f"Bundle directory not found: {folder}")
    entries = sorted(folder.iterdir())
    for entry in entries:
        if entry.name == "timing.json" and entry.is_file():
            continue
        if not entry.is_file() or entry.suffix.lower() != ".mp3":
            raise CommandError(STREAM_HELD.format(name=entry.name))
    timing_path = folder / "timing.json"
    if not timing_path.is_file() or timing_path.stat().st_size > MAX_TIMING_BYTES:
        raise CommandError("Bundle requires a bounded timing.json.")
    raw = timing_path.read_bytes()
    try:
        timing = json.loads(raw)
        rows = timing["units"]
        if not isinstance(rows, list) or not rows:
            raise ValueError
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"unit_id", "mp3", "segments"} or not isinstance(row["unit_id"], str)
                    or not isinstance(row["mp3"], str) or not isinstance(row["segments"], list)):
                raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise CommandError('timing.json must be {"units": [{"unit_id", "mp3", "segments"}]}.') from None
    names = [row["mp3"] for row in rows]
    mp3s = {e.name for e in entries if e.suffix.lower() == ".mp3"}
    if len(set(names)) != len(names) or len({r["unit_id"] for r in rows}) != len(rows) or set(names) != mp3s:
        raise CommandError("timing.json must list each bundle MP3 exactly once, one per distinct unit.")
    files = {}
    for name in names:
        path = folder / name
        try:
            measured = measure_mp3(path)
        except HandoffError as exc:
            raise CommandError(f"{name}: {exc}") from None
        files[name] = {"path": path, "sha256": file_sha256(path), "bytes": path.stat().st_size, **measured}
    bundle_sha = digest(canonical_bytes({"timing_sha256": sha256(raw), "mp3": {n: f["sha256"] for n, f in files.items()}}))
    return {"rows": rows, "files": files, "bundle_sha256": bundle_sha}


def read_report(relative):
    path = (ROOT / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise CommandError(f"browser report not found as a repo-relative file: {relative}")
    raw = path.read_bytes()
    try:
        report = json.loads(raw)
    except ValueError:
        raise CommandError("browser report is not JSON.") from None
    return report, f"{relative}#sha256={sha256(raw)}"


def read_evidence(relative):
    path = (ROOT / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to((ROOT / "docs" / "evidence").resolve()):
        raise CommandError("--evidence must be a repo-relative JSON under docs/evidence/.")
    if not path.is_file():
        raise CommandError(f"Clearance evidence document not found: {relative}")
    raw = path.read_bytes()
    try:
        doc = json.loads(raw)
    except ValueError:
        raise CommandError("Clearance evidence document is not JSON.") from None
    return doc, sha256(raw), f"{relative}#sha256={sha256(raw)}"


def check_evidence(doc, slug, live, bundle):
    if not isinstance(doc, dict) or doc.get("schema") != EVIDENCE_SCHEMA or doc.get("edition_slug") != slug:
        raise CommandError(f"Clearance evidence must be {EVIDENCE_SCHEMA} for edition {slug}.")
    status = doc.get("status")
    if isinstance(status, str) and status.strip().upper().startswith("DRAFT"):
        raise CommandError("Clearance evidence is still a draft; the owner must complete and approve it first.")
    approval = doc.get("owner_approval")
    if (not isinstance(approval, dict) or not isinstance(approval.get("by"), str) or not approval["by"].strip()
            or not isinstance(approval.get("at"), str) or not approval["at"].strip()):
        raise CommandError('Clearance evidence needs owner_approval {"by": <who>, "at": <when>} from the owner.')
    if doc.get("source_content_sha256") != live.content_sha256:
        raise CommandError("Clearance evidence names a different live text hash.")
    if not isinstance(doc.get("territories"), list) or sorted(doc["territories"]) != sorted(territories()):
        raise CommandError("Clearance evidence territories differ from the active whitelist.")
    if not isinstance(doc.get("formats"), list) or sorted(doc["formats"]) != ["audio", "reader"]:
        raise CommandError('Clearance evidence formats must be exactly ["reader", "audio"].')
    if not isinstance(doc.get("audio_sha256"), list) or sorted(doc["audio_sha256"]) != sorted(f["sha256"] for f in bundle["files"].values()):
        raise CommandError("Clearance evidence audio_sha256 differs from the bundle MP3 hashes.")


def in_memory_check(revision, unit, segments, measured, sha, evidence):
    """Geometry check through validated_segments against revision rows; nothing is saved."""
    unit.duration_ms = measured["duration_ms"]
    probe = Revision(id=revision.id, edition_id=revision.edition_id, content_sha256=revision.content_sha256,
                     validation_evidence=evidence)
    asset = Asset(id=stable_id("probe", revision.id, unit.id), revision=probe, unit=unit, kind="audio_chapter",
                  state="ready", provider="r2", sha256=sha, duration_ms=measured["duration_ms"])
    evidence.setdefault("media_assets", {})[str(asset.id)] = media_value(asset, measured, "probe")
    mapping = TimingMap(revision=probe, asset=asset, text_sha256=revision.content_sha256, asset_sha256=sha,
                        precision="paragraph", measured=True, segments=segments)
    try:
        validated_segments(mapping)
    except DomainError as exc:
        raise CommandError(f"timing.json unit {unit.ordinal}: {exc.message}") from None


def media_value(asset, measured, bundle_sha):
    return {"sha256": asset.sha256, "unit_id": str(asset.unit_id), "duration_ms": measured["duration_ms"],
            "quality_kbps": measured["quality_kbps"], "prepared": True,
            "measurement_evidence": f"audiovisual_bundle:{bundle_sha}/ffprobe:{measured['measurement_sha256']}",
            "actual_listening": False}


class Command(BaseCommand):
    help = __doc__.split("\n\n", 1)[0] + " Bundle layout and evidence schema: see this module's docstring."

    def add_arguments(self, parser):
        parser.add_argument("phase", choices=("stage", "publish"))
        parser.add_argument("edition_slug")
        parser.add_argument("--publisher", required=True, help="public_id of an active verified staff publisher")
        parser.add_argument("--bundle", help="stage: directory holding timing.json and the chapter MP3s only")
        parser.add_argument("--evidence", help="stage: repo-relative clearance JSON under docs/evidence/")
        parser.add_argument("--browser-report", help="publish: repo-relative browser acceptance JSON for the staged hash")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(public_id=options["publisher"], is_active=True, is_staff=True).first()
        if actor is None or not actor.is_verified or not actor.has_perm("library.publish_revision"):
            raise CommandError("An active verified staff publisher with library.publish_revision is required.")
        edition, live = live_revision(options["edition_slug"])
        if options["phase"] == "stage":
            if not options.get("bundle") or not options.get("evidence"):
                raise CommandError("stage requires --bundle and --evidence.")
            return self.stage(actor, edition, live, options)
        if not options.get("browser_report"):
            raise CommandError("publish requires --browser-report.")
        return self.publish_staged(actor, edition, live, options["browser_report"])

    def stage(self, actor, edition, live, options):
        slug = edition.slug
        bundle = read_bundle(options["bundle"])
        doc, doc_sha, evidence_ref = read_evidence(options["evidence"])
        shas = sorted(f["sha256"] for f in bundle["files"].values())
        live_audio = sorted(live.assets.filter(kind="audio_chapter").values_list("sha256", flat=True))
        if live_audio:
            if (live_audio == shas and live.validation_evidence.get("audiovisual_audio", {}).get("bundle_sha256") == bundle["bundle_sha256"]):
                return self.emit({"status": "already_live", "edition_id": str(edition.id), "revision_id": str(live.id),
                                  "bundle_sha256": bundle["bundle_sha256"], "audio_sha256": shas})
            raise CommandError(f"{slug}: the live revision already carries different audio; replacing audio is not supported here.")
        if not has_public_domain_evidence(live):
            raise CommandError(f"{slug}: live revision lacks passing public-domain publication clearance; refused.")
        check_evidence(doc, slug, live, bundle)
        plan = self.preflight(live, bundle)
        draft = self.find_or_clone(actor, edition, live, bundle)
        if draft.state == "draft" and not draft.assets.filter(kind="audio_chapter").exists():
            self.attach(actor, live, draft, bundle, plan, evidence_ref)
        draft.refresh_from_db()
        self.emit({"status": "staged", "edition_id": str(edition.id), "revision_id": str(draft.id), "state": draft.state,
            "content_sha256": draft.content_sha256, "source_revision_id": str(live.id), "bundle_sha256": bundle["bundle_sha256"],
            "evidence_ref": evidence_ref,
            "asset_sha256": {str(a.id): a.sha256 for a in draft.assets.filter(state="ready")},
            "audio": [{"unit_id": str(a.unit_id), "asset_id": str(a.id), "sha256": a.sha256, "duration_ms": a.duration_ms}
                      for a in draft.assets.filter(kind="audio_chapter").order_by("unit__ordinal")]})

    def publish_staged(self, actor, edition, live, report_path):
        draft = (Revision.objects.filter(edition=edition, state__in=["draft", "ready"],
                 validation_evidence__audiovisual_audio__source_revision_id=str(live.id), assets__kind="audio_chapter")
                 .distinct().order_by("-created_at").first())
        if draft is None:
            if live.validation_evidence.get("audiovisual_audio") and live.assets.filter(kind="audio_chapter").exists():
                return self.emit({"status": "already_live", "edition_id": str(edition.id), "revision_id": str(live.id)})
            raise CommandError(f"{edition.slug}: no staged audio draft of the live revision; run the stage phase first.")
        report, report_ref = read_report(report_path)
        checks = report.get("checks") if isinstance(report, dict) else None
        if not isinstance(report, dict) or report.get("status") != "pass" or report.get("sha256") != draft.content_sha256:
            raise CommandError("browser report does not pass for the staged revision's exact content_sha256.")
        if not isinstance(checks, dict) or checks.get("audio_playback") is not True:
            raise CommandError("browser report does not cover audio playback (checks.audio_playback must be true).")
        if not isinstance(report.get("scope"), str) or not report["scope"].strip():
            raise CommandError("browser report must name its release scope.")
        browser = {"status": "pass", "sha256": draft.content_sha256, "scope": report["scope"], "checks": checks,
                   "report": report_ref, "recorded_at": timezone.now().isoformat()}
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=draft.pk)
            if current.content_sha256 != draft.content_sha256:
                raise CommandError("Staged draft changed while recording browser evidence.")
            if current.state == "draft":
                current.validation_evidence = {**current.validation_evidence, "browser": browser}
                current.version += 1
                current.save()
                audit(actor, "revision.evidence", current, {"browser": report_ref, "channel": "server_job"})
            steps = self.publish(actor, current, report_ref)
        current.refresh_from_db()
        report = validate_revision(current, prepared=prepare_revision_validation(current.id))
        self.emit({"status": "published", "edition_id": str(edition.id), "revision_id": str(current.id),
            "retired_revision_id": str(live.id), "state": current.state, "browser_report": report_ref, "steps": steps,
            "checks": {c["code"]: c["status"] for c in report["checks"]}})

    def emit(self, out):
        self.stdout.write("MAISON_OUT " + json.dumps(out, ensure_ascii=False, default=str))

    # --- preflight: everything checkable before any mutation ----------------------------------
    def preflight(self, live, bundle):
        units = {str(u.id): u for u in live.units.all()}
        plan = []
        for row in bundle["rows"]:
            unit = units.get(row["unit_id"])
            if unit is None:
                raise CommandError(f"timing.json unit {row['unit_id']} is not a unit of the live revision.")
            ordinals = {str(p.anchor_id): p.ordinal for p in Paragraph.objects.filter(unit=unit)}
            for segment in row["segments"]:
                if not isinstance(segment, dict) or segment.get("anchor_id") not in ordinals:
                    raise CommandError(f"timing.json unit {unit.ordinal}: segment anchor is not in this live unit.")
            measured = bundle["files"][row["mp3"]]
            in_memory_check(live, unit, row["segments"], measured, measured["sha256"], {})
            plan.append({"unit_ordinal": unit.ordinal, "file": measured,
                         "segments": [{**s, "paragraph_ordinal": ordinals[s["anchor_id"]]} for s in row["segments"]]})
        return plan

    # --- clone (or resume the unfinished clone of this exact bundle) ---------------------------
    def find_or_clone(self, actor, edition, live, bundle):
        marker = {"bundle_sha256": bundle["bundle_sha256"], "source_revision_id": str(live.id),
                  "source_content_sha256": live.content_sha256}
        draft = (Revision.objects.filter(edition=edition, state__in=["draft", "ready"],
                 validation_evidence__audiovisual_audio__bundle_sha256=marker["bundle_sha256"],
                 validation_evidence__audiovisual_audio__source_revision_id=marker["source_revision_id"])
                 .order_by("-created_at").first())
        if draft is not None:
            return draft
        try:
            clone = clone_revision(live.id)
        except DomainError as exc:
            raise CommandError(f"{exc.code}: {exc.message}") from None
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=clone.pk)
            current.validation_evidence = {**current.validation_evidence, "audiovisual_audio": marker}
            current.version += 1
            current.save()
            audit(actor, "revision.clone", current, {"source_revision_id": str(live.id),
                  "bundle_sha256": marker["bundle_sha256"], "channel": "server_job"})
        return current

    # --- attach -------------------------------------------------------------------------------
    def attach(self, actor, live, draft, bundle, plan, evidence_ref):
        units = {u.ordinal: u for u in draft.units.all()}
        prepared = []
        for item in plan:
            unit = units[item["unit_ordinal"]]
            measured = item["file"]
            asset_id = stable_id(draft.id, "audio_chapter", unit.ordinal, measured["sha256"])
            key = f"revisions/{draft.id}/{asset_id}.mp3"
            try:
                storage.put_private_file(key, measured["path"], "audio/mpeg", measured["bytes"], measured["sha256"])
                asset = Asset(id=asset_id, revision=draft, unit=unit, kind="audio_chapter", state="ready", provider="r2",
                              storage_key=key, sha256=measured["sha256"], bytes=measured["bytes"],
                              content_type="audio/mpeg", duration_ms=measured["duration_ms"])
                pieces = storage.prepare_audio_pieces(asset)
            except DomainError as exc:
                raise CommandError(f"{exc.code}: {exc.message}") from None
            prepared.append((item, unit, asset, pieces))
        now = timezone.now()
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=draft.pk)
            if current.state != "draft" or current.content_sha256 != draft.content_sha256:
                raise CommandError("Clone changed while attaching audio; review the current draft.")
            anchors = {(p.unit.ordinal, p.ordinal): str(p.anchor_id)
                       for p in Paragraph.objects.filter(unit__revision=current).select_related("unit")}
            evidence = dict(current.validation_evidence)
            media = dict(evidence.get("media_assets", {}))
            pieces_proofs = dict(evidence.get("offline_piece_manifests", {}))
            for item, unit, asset, pieces in prepared:
                unit.duration_ms = item["file"]["duration_ms"]
                unit.save()
                asset.revision = current
                asset.save()
                audit(actor, "asset.complete", asset, {"sha256": asset.sha256, "kind": asset.kind, "unit_id": str(unit.id),
                      "duration_ms": asset.duration_ms, "channel": "server_job"})
                media[str(asset.id)] = media_value(asset, item["file"], bundle["bundle_sha256"])
                pieces_proofs[str(asset.id)] = pieces
            evidence["media_assets"] = media
            evidence["offline_piece_manifests"] = pieces_proofs
            current.validation_evidence = evidence
            current.access_policy = {**current.access_policy, "audio": "free"}
            current.save()
            for item, unit, asset, _ in prepared:
                asset.revision = current
                segments = [{"anchor_id": anchors[(unit.ordinal, s["paragraph_ordinal"])],
                             **{k: s[k] for k in ("start_offset_chars", "end_offset_chars", "start_ms", "end_ms")}}
                            for s in item["segments"]]
                mapping = TimingMap(revision=current, asset=asset, text_sha256=current.content_sha256, asset_sha256=asset.sha256,
                                    precision="paragraph", measured=True, segments=segments)
                try:
                    validated_segments(mapping)
                except DomainError as exc:
                    raise CommandError(f"timing map for unit {unit.ordinal}: {exc.message}") from None
                mapping.save()
                audit(actor, "timing_map.create", mapping, {"asset_id": str(asset.id), "asset_sha256": asset.sha256,
                      "text_sha256": current.content_sha256, "channel": "server_job"})
            self.approve_rights(actor, live, current, evidence_ref, now)
            ready = list(current.assets.filter(state="ready"))
            clearance = {"status": "pass", "sha256": current.content_sha256, "territories": territories(),
                "formats": ["reader", "audio"], "asset_sha256": {str(a.id): a.sha256 for a in ready},
                "evidence_ref": evidence_ref, "basis": "owner_authorized_public_domain_term_evidence_audio",
                "source_revision_id": str(live.id), "recorded_by": str(actor.public_id), "recorded_at": now.isoformat()}
            current.validation_evidence = {**current.validation_evidence, "publication_clearance": clearance}
            current.version += 1
            current.save()
            audit(actor, "revision.evidence", current, {"publication_clearance": evidence_ref, "channel": "server_job"})

    def approve_rights(self, actor, live, current, evidence_ref, now):
        cleared = {(r.format, r.action, tuple(r.territories), r.starts_at, r.ends_at)
                   for r in live.rights.filter(approved=True, test_only=False)}
        for right in current.rights.filter(approved=False, test_only=False):
            if (right.format, right.action, tuple(right.territories), right.starts_at, right.ends_at) not in cleared:
                continue
            right.approved = True
            right.evidence = json.dumps({"evidence_ref": evidence_ref, "reapproved_from_revision": str(live.id),
                                         "basis": "owner-authorized public-domain term evidence"}, ensure_ascii=False)
            right.version += 1
            right.save()
            audit(actor, "rights.approve", right, {"format": right.format, "action": right.action, "channel": "server_job"})
        if not current.rights.filter(format="audio", action="read", approved=True, test_only=False).exists():
            evidence = json.dumps({"territories": territories(), "evidence_ref": evidence_ref,
                                   "basis": "owner-authorized public-domain term evidence"}, ensure_ascii=False)
            right = Rights.objects.create(revision=current, format="audio", action="read", territories=territories(),
                starts_at=now, ends_at=now + timedelta(days=3650), approved=True, test_only=False, evidence=evidence)
            audit(actor, "rights.create", right, {"format": "audio", "action": "read", "territories": territories(),
                  "channel": "server_job"})

    # --- mark-ready + publish (same as publish_cleared_editions.publish) -----------------------------------
    def publish(self, actor, revision, report_ref):
        reason = f"Owner-cleared narration audio; fresh browser acceptance {report_ref}."
        steps = []
        for action in ("mark-ready", "publish"):
            revision.refresh_from_db()
            if (action == "mark-ready" and revision.state != "draft") or (action == "publish" and revision.state != "ready"):
                continue
            try:
                state = transition_revision(actor, revision.id, action, revision.version, revision.content_sha256, reason)
            except DomainError as exc:
                details = exc.details if isinstance(exc.details, dict) else {}
                failed = [c["code"] for c in details.get("checks", []) if c["status"] == "fail"]
                raise CommandError(f"{action}: {exc.code}: {exc.message} {failed}") from None
            audit(actor, "revision." + action, revision, {"reason": reason, "channel": "server_job"})
            steps.append({"action": action, "state": state["state"], "version": state["version"]})
        return steps
