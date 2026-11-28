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
audio_sha256 (exactly the bundle MP3 hashes), the completed per-title record (term_per_territory for every
whitelisted territory, text_source_licence, cover_provenance, and music {route, licence,
source_and_licence} unless dry_narration is true; dry_narration is refused when timing.json's eav provenance
shows a score mixed under any unit), plus owner_approval {"by": <who>, "at": <when>}; a
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

stage-preview: attach one owner-approved public audio sample to an edition whose live revision already
carries the owner-cleared chapter audio (staged and published above):

  attach_audiovisual_audio stage-preview <slug> --publisher <public_id> --clip <preview.mp3>
                           --preview-json <preview.json> --evidence <docs/evidence/...json>

The clip is measured with the same ffprobe tooling as the chapters (a single MP3 stream at exactly 48 or
96 kbps) and must be at most library.audio_preview.MAX_DURATION_MS and MAX_BYTES; it is never re-encoded
here, because re-encoding changes the bytes the owner approved (re-encode beforehand and have the owner
approve the new hash). preview.json (written by the audiovisual skill) must state exactly the measured
sha256, bytes, duration_ms and quality_kbps, content_type audio/mpeg, prepared true, a measurement_evidence
note and source_mp3_sha256, the hash of the live chapter MP3 the sample was cut from (that chapter's unit
becomes the sample's unit; preview.json unit_id is retained as provenance only, because unit ids change on
every clone). --evidence is the same clearance record as for stage (schema, owner_approval, territories,
formats, complete per-title record, audio_sha256 = the live chapter hashes, source_content_sha256 = the
text the narration speaks) and must also name preview_sha256: exactly the clip's sha256. An owner review
note that does not name the clip's hash is not an exact approval and is refused.

stage-preview clones the live revision (clone_revision copies the chapter MP3s privately), re-binds the
copied chapters' measurement evidence, offline piece proofs and measured TimingMaps to the clone, stores the
clip privately as the one preview_audio asset on its unit with exact audio_preview evidence, re-approves the
live revision's approved non-test rights, adds approved non-test audio preview rights for the whitelist and
records publication_clearance over every ready asset hash. The clone stays a DRAFT with no browser
evidence; reruns resume it, and once published report already_live. Replacing a live sample is refused.

publish: --browser-report is a repo-relative JSON {"sha256": <staged content_sha256>, "status": "pass",
"scope": "...", "checks": {"audio_playback": true, ...}}. It must name the staged revision's exact hash,
pass, and cover audio playback (and, for a staged sample, checks.audio_preview true); it is then recorded
as the draft's browser evidence, and mark-ready and publish run through transition_revision (full
validate_revision) in one transaction. Any mismatch or failed check raises CommandError and changes nothing.
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
from library.audio_preview import MAX_BYTES as MAX_PREVIEW_BYTES, MAX_DURATION_MS as MAX_PREVIEW_MS
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
    provenance = timing.get("provenance") if isinstance(timing, dict) else None
    return {"rows": rows, "files": files, "bundle_sha256": bundle_sha,
            "provenance": provenance if isinstance(provenance, dict) else {}}


def score_mixed(bundle):
    """Units whose eav provenance shows a score bed was mixed under the narration."""
    units = bundle.get("provenance", {}).get("units")
    if not isinstance(units, dict):
        return []
    return sorted(u for u, row in units.items() if isinstance(row, dict) and (
        row.get("score_sha256") or row.get("mastered_with") == "eav.mix.duck_and_master"))


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


def check_approved(doc, slug):
    if not isinstance(doc, dict) or doc.get("schema") != EVIDENCE_SCHEMA or doc.get("edition_slug") != slug:
        raise CommandError(f"Clearance evidence must be {EVIDENCE_SCHEMA} for edition {slug}.")
    status = doc.get("status")
    if isinstance(status, str) and status.strip().upper().startswith("DRAFT"):
        raise CommandError("Clearance evidence is still a draft; the owner must complete and approve it first.")
    approval = doc.get("owner_approval")
    if (not isinstance(approval, dict) or not isinstance(approval.get("by"), str) or not approval["by"].strip()
            or not isinstance(approval.get("at"), str) or not approval["at"].strip()):
        raise CommandError('Clearance evidence needs owner_approval {"by": <who>, "at": <when>} from the owner.')
    if not isinstance(doc.get("territories"), list) or sorted(doc["territories"]) != sorted(territories()):
        raise CommandError("Clearance evidence territories differ from the active whitelist.")
    if not isinstance(doc.get("formats"), list) or sorted(doc["formats"]) != ["audio", "reader"]:
        raise CommandError('Clearance evidence formats must be exactly ["reader", "audio"].')


def check_evidence(doc, slug, live, bundle):
    check_approved(doc, slug)
    if doc.get("source_content_sha256") != live.content_sha256:
        raise CommandError("Clearance evidence names a different live text hash.")
    if not isinstance(doc.get("audio_sha256"), list) or sorted(doc["audio_sha256"]) != sorted(f["sha256"] for f in bundle["files"].values()):
        raise CommandError("Clearance evidence audio_sha256 differs from the bundle MP3 hashes.")
    check_record_complete(doc)
    mixed = score_mixed(bundle)
    if doc.get("dry_narration") is True and mixed:
        raise CommandError(f"Clearance evidence claims dry_narration, but the bundle provenance shows a score mixed "
                           f"under unit(s) {', '.join(mixed)}; the music record and licence are required.")


def _filled(value):
    """A completed evidence field: a non-blank string or a non-empty object/list."""
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, (dict, list)) and bool(value)


def check_record_complete(doc):
    """The per-title record the owner approves is complete (spec owner answer 4; R24)."""
    terms = doc.get("term_per_territory")
    if not isinstance(terms, dict) or not terms:
        raise CommandError("Clearance evidence term_per_territory must give the term evidence for every whitelisted territory.")
    missing = [t for t in territories() if not _filled(terms.get(t))]
    if missing:
        raise CommandError(f"Clearance evidence term_per_territory lacks: {', '.join(missing)}.")
    for field in ("text_source_licence", "cover_provenance"):
        if not _filled(doc.get(field)):
            raise CommandError(f"Clearance evidence {field} is missing.")
    if doc.get("dry_narration") is True:
        return
    music = doc.get("music")
    if (not isinstance(music, dict) or not _filled(music.get("route")) or not _filled(music.get("licence"))
            or not _filled(music.get("source_and_licence"))):
        raise CommandError("Clearance evidence music needs route, licence and source_and_licence (or dry_narration true).")


PREVIEW_JSON_KEYS = ("sha256", "bytes", "duration_ms", "quality_kbps")


def read_clip(clip, preview_json):
    """The sample as measured here, cross-checked against the skill's preview.json; nothing is re-encoded."""
    clip, preview_json = Path(clip), Path(preview_json)
    if not clip.is_file() or clip.suffix.lower() != ".mp3":
        raise CommandError(f"Preview clip not found as an .mp3 file: {clip}")
    if not preview_json.is_file() or preview_json.stat().st_size > 65536:
        raise CommandError(f"Bounded preview.json not found: {preview_json}")
    size = clip.stat().st_size
    if not 0 < size <= MAX_PREVIEW_BYTES:
        raise CommandError(f"Preview clip is {size} bytes; the bounded sample limit is {MAX_PREVIEW_BYTES} bytes.")
    try:
        measured = measure_mp3(clip)
    except HandoffError as exc:
        raise CommandError(f"{clip.name}: {exc} (re-encode beforehand; the owner approves the re-encoded hash).") from None
    if not 1 <= measured["duration_ms"] <= MAX_PREVIEW_MS:
        raise CommandError(f"Preview clip lasts {measured['duration_ms']} ms; the bounded sample limit is {MAX_PREVIEW_MS} ms.")
    raw = preview_json.read_bytes()
    try:
        stated = json.loads(raw)
        if not isinstance(stated, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        raise CommandError("preview.json is not a JSON object.") from None
    clip_sha = file_sha256(clip)
    actual = {"sha256": clip_sha, "bytes": size, "duration_ms": measured["duration_ms"], "quality_kbps": measured["quality_kbps"]}
    differs = [k for k in PREVIEW_JSON_KEYS if stated.get(k) != actual[k] or type(stated.get(k)) is not type(actual[k])]
    if differs:
        raise CommandError(f"preview.json differs from the measured clip in {', '.join(differs)}: measured {actual}.")
    if stated.get("content_type") != "audio/mpeg" or stated.get("prepared") is not True:
        raise CommandError('preview.json must state content_type "audio/mpeg" and prepared true.')
    if not _filled(stated.get("measurement_evidence")):
        raise CommandError("preview.json must carry its measurement_evidence note.")
    source = stated.get("source_mp3_sha256")
    if not isinstance(source, str) or len(source) != 64:
        raise CommandError("preview.json must name source_mp3_sha256, the live chapter MP3 the sample was cut from.")
    return {"path": clip, **actual, **measured, "source_mp3_sha256": source, "stated": stated,
            "preview_json_sha256": sha256(raw)}


def check_preview_evidence(doc, slug, live, clip):
    check_approved(doc, slug)
    spoken = {live.content_sha256, live.validation_evidence.get("audiovisual_audio", {}).get("source_content_sha256")}
    if doc.get("source_content_sha256") not in spoken:
        raise CommandError("Clearance evidence names a different text hash from the one the live narration speaks.")
    chapters = sorted(live.assets.filter(kind="audio_chapter", state="ready").values_list("sha256", flat=True))
    if not isinstance(doc.get("audio_sha256"), list) or sorted(doc["audio_sha256"]) != chapters:
        raise CommandError("Clearance evidence audio_sha256 differs from the live chapter MP3 hashes.")
    check_record_complete(doc)
    if doc.get("preview_sha256") != clip["sha256"]:
        raise CommandError(f"Clearance evidence does not approve this exact sample: preview_sha256 must equal {clip['sha256']} "
                           "(an owner review note without the clip hash is not an exact approval).")


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
        parser.add_argument("phase", choices=("stage", "stage-preview", "publish"))
        parser.add_argument("edition_slug")
        parser.add_argument("--publisher", required=True, help="public_id of an active verified staff publisher")
        parser.add_argument("--bundle", help="stage: directory holding timing.json and the chapter MP3s only")
        parser.add_argument("--clip", help="stage-preview: the owner-approved sample MP3")
        parser.add_argument("--preview-json", help="stage-preview: the sample's preview.json")
        parser.add_argument("--evidence", help="stage, stage-preview: repo-relative clearance JSON under docs/evidence/")
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
        if options["phase"] == "stage-preview":
            if not options.get("clip") or not options.get("preview_json") or not options.get("evidence"):
                raise CommandError("stage-preview requires --clip, --preview-json and --evidence.")
            return self.stage_preview(actor, edition, live, options)
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
        staged = Revision.objects.filter(edition=edition, state__in=["draft", "ready"])
        chapters = staged.filter(validation_evidence__audiovisual_audio__source_revision_id=str(live.id), assets__kind="audio_chapter")
        sample = staged.filter(validation_evidence__audiovisual_preview__source_revision_id=str(live.id), assets__kind="preview_audio")
        draft = (chapters | sample).distinct().order_by("-created_at").first()
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
        if draft.assets.filter(kind="preview_audio").exists() and checks.get("audio_preview") is not True:
            raise CommandError("browser report does not cover the public sample (checks.audio_preview must be true).")
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

    # --- stage-preview: the one bounded public sample on a clone of the live audio revision ------------
    def stage_preview(self, actor, edition, live, options):
        slug = edition.slug
        clip = read_clip(options["clip"], options["preview_json"])
        doc, _, evidence_ref = read_evidence(options["evidence"])
        live_clips = list(live.assets.filter(kind="preview_audio"))
        if live_clips:
            if ([a.sha256 for a in live_clips] == [clip["sha256"]]
                    and live.validation_evidence.get("audio_preview", {}).get("sha256") == clip["sha256"]):
                return self.emit({"status": "already_live", "edition_id": str(edition.id), "revision_id": str(live.id),
                                  "preview_sha256": clip["sha256"], "asset_id": str(live_clips[0].id)})
            raise CommandError(f"{slug}: the live revision already carries a different audio sample; replacing it is not supported here.")
        if not has_public_domain_evidence(live):
            raise CommandError(f"{slug}: live revision lacks passing public-domain publication clearance; refused.")
        chapters = {a.sha256: a for a in live.assets.filter(kind="audio_chapter", state="ready").select_related("unit")}
        if not chapters or not live.validation_evidence.get("audiovisual_audio"):
            raise CommandError(f"{slug}: the live revision carries no owner-cleared chapter audio; stage and publish the chapters first.")
        source = chapters.get(clip["source_mp3_sha256"])
        if source is None:
            raise CommandError("preview.json source_mp3_sha256 is not a chapter MP3 of the live revision.")
        maps = {}
        for asset in chapters.values():
            mapping = live.timing_maps.filter(asset=asset, measured=True, asset_sha256=asset.sha256,
                                              text_sha256=live.content_sha256).first()
            if mapping is None or str(asset.id) not in live.validation_evidence.get("media_assets", {}):
                raise CommandError(f"{slug}: live chapter {asset.unit.ordinal} lacks its measured timing map or evidence.")
            maps[asset.sha256] = mapping
        check_preview_evidence(doc, slug, live, clip)
        draft = self.find_or_clone_preview(actor, edition, live, clip)
        if draft.state == "draft" and not draft.assets.filter(kind="preview_audio").exists():
            self.attach_preview(actor, live, draft, clip, source, chapters, maps, evidence_ref)
        draft.refresh_from_db()
        sample = draft.assets.filter(kind="preview_audio").first()
        self.emit({"status": "staged", "edition_id": str(edition.id), "revision_id": str(draft.id), "state": draft.state,
            "content_sha256": draft.content_sha256, "source_revision_id": str(live.id), "evidence_ref": evidence_ref,
            "asset_sha256": {str(a.id): a.sha256 for a in draft.assets.filter(state="ready")},
            "preview": sample and {"asset_id": str(sample.id), "unit_id": str(sample.unit_id), "sha256": sample.sha256,
                                   "bytes": sample.bytes, "duration_ms": sample.duration_ms},
            "audio": [{"unit_id": str(a.unit_id), "asset_id": str(a.id), "sha256": a.sha256, "duration_ms": a.duration_ms}
                      for a in draft.assets.filter(kind="audio_chapter").order_by("unit__ordinal")]})

    def find_or_clone_preview(self, actor, edition, live, clip):
        marker = {"preview_sha256": clip["sha256"], "preview_json_sha256": clip["preview_json_sha256"],
                  "source_revision_id": str(live.id), "source_content_sha256": live.content_sha256}
        draft = (Revision.objects.filter(edition=edition, state__in=["draft", "ready"],
                 validation_evidence__audiovisual_preview__preview_sha256=marker["preview_sha256"],
                 validation_evidence__audiovisual_preview__source_revision_id=marker["source_revision_id"])
                 .order_by("-created_at").first())
        if draft is not None:
            return draft
        try:
            clone = clone_revision(live.id)
        except DomainError as exc:
            raise CommandError(f"{exc.code}: {exc.message}") from None
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=clone.pk)
            # The chapter marker stays the live one (its source revision is not this live), so stage reruns report already_live.
            current.validation_evidence = {**current.validation_evidence, "audiovisual_preview": marker,
                                           "audiovisual_audio": live.validation_evidence["audiovisual_audio"]}
            current.version += 1
            current.save()
            audit(actor, "revision.clone", current, {"source_revision_id": str(live.id),
                  "preview_sha256": marker["preview_sha256"], "channel": "server_job"})
        return current

    def attach_preview(self, actor, live, draft, clip, source, chapters, maps, evidence_ref):
        units = {u.ordinal: u for u in draft.units.all()}
        copied = {(a.unit.ordinal, a.sha256): a for a in draft.assets.filter(kind="audio_chapter").select_related("unit")}
        pairs = []
        for sha, old in chapters.items():
            new = copied.get((old.unit.ordinal, sha))
            if new is None:
                raise CommandError(f"Clone lacks the copied chapter {old.unit.ordinal}; review the draft {draft.id}.")
            try:
                pieces = storage.prepare_audio_pieces(new)
            except DomainError as exc:
                raise CommandError(f"{exc.code}: {exc.message}") from None
            pairs.append((old, new, pieces))
        unit = units[source.unit.ordinal]
        asset_id = stable_id(draft.id, "preview_audio", unit.ordinal, clip["sha256"])
        key = f"revisions/{draft.id}/{asset_id}.mp3"
        try:
            storage.put_private_file(key, clip["path"], "audio/mpeg", clip["bytes"], clip["sha256"])
        except DomainError as exc:
            raise CommandError(f"{exc.code}: {exc.message}") from None
        sample = Asset(id=asset_id, revision=draft, unit=unit, kind="preview_audio", state="ready", provider="r2",
                       storage_key=key, sha256=clip["sha256"], bytes=clip["bytes"], content_type="audio/mpeg",
                       duration_ms=clip["duration_ms"])
        now = timezone.now()
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=draft.pk)
            if current.state != "draft" or current.content_sha256 != draft.content_sha256:
                raise CommandError("Clone changed while attaching the sample; review the current draft.")
            anchors = {(p.unit.ordinal, p.ordinal): str(p.anchor_id)
                       for p in Paragraph.objects.filter(unit__revision=current).select_related("unit")}
            evidence = dict(current.validation_evidence)
            media = dict(evidence.get("media_assets", {}))
            proofs = dict(evidence.get("offline_piece_manifests", {}))
            for old, new, pieces in pairs:
                media[str(new.id)] = {**live.validation_evidence["media_assets"][str(old.id)], "unit_id": str(new.unit_id)}
                proofs[str(new.id)] = pieces
            evidence["media_assets"] = media
            evidence["offline_piece_manifests"] = proofs
            current.validation_evidence = evidence
            for old, new, _ in pairs:
                old_map = maps[old.sha256]
                ordinals = {str(p.anchor_id): p.ordinal for p in Paragraph.objects.filter(unit=old.unit)}
                segments = [{**s, "anchor_id": anchors[(old.unit.ordinal, ordinals[s["anchor_id"]])]} for s in old_map.segments]
                mapping = TimingMap(revision=current, asset=new, text_sha256=current.content_sha256, asset_sha256=new.sha256,
                                    precision=old_map.precision, measured=True, segments=segments)
                new.revision = current
                try:
                    validated_segments(mapping)
                except DomainError as exc:
                    raise CommandError(f"timing map for unit {old.unit.ordinal}: {exc.message}") from None
                mapping.save()
                audit(actor, "timing_map.create", mapping, {"asset_id": str(new.id), "asset_sha256": new.sha256,
                      "text_sha256": current.content_sha256, "copied_from": str(old_map.id), "channel": "server_job"})
            sample.revision = current
            sample.save()
            audit(actor, "asset.complete", sample, {"sha256": sample.sha256, "kind": sample.kind, "unit_id": str(unit.id),
                  "duration_ms": sample.duration_ms, "channel": "server_job"})
            evidence["audio_preview"] = {"asset_id": str(sample.id), "unit_id": str(unit.id), "sha256": sample.sha256,
                "bytes": sample.bytes, "duration_ms": sample.duration_ms, "quality_kbps": clip["quality_kbps"], "prepared": True,
                "measurement_evidence": f"audiovisual_preview:{clip['preview_json_sha256']}/ffprobe:{clip['measurement_sha256']}",
                "re_encoded": False, "source_mp3_sha256": clip["source_mp3_sha256"],
                "preparation": clip["stated"]["measurement_evidence"], "source_unit_id": clip["stated"].get("unit_id"),
                "evidence_ref": evidence_ref, "actual_listening": False}
            current.validation_evidence = evidence
            current.save()
            self.approve_rights(actor, live, current, evidence_ref, now)
            if not current.rights.filter(format="audio", action="preview", approved=True, test_only=False).exists():
                note = json.dumps({"territories": territories(), "evidence_ref": evidence_ref, "preview_sha256": sample.sha256,
                                   "basis": "owner-approved bounded sample; public-domain term evidence"}, ensure_ascii=False)
                right = Rights.objects.create(revision=current, format="audio", action="preview", territories=territories(),
                    starts_at=now, ends_at=now + timedelta(days=3650), approved=True, test_only=False, evidence=note)
                audit(actor, "rights.create", right, {"format": "audio", "action": "preview", "territories": territories(),
                      "channel": "server_job"})
            ready = list(current.assets.filter(state="ready"))
            clearance = {"status": "pass", "sha256": current.content_sha256, "territories": territories(),
                "formats": ["reader", "audio"], "asset_sha256": {str(a.id): a.sha256 for a in ready},
                "evidence_ref": evidence_ref, "basis": "owner_authorized_public_domain_term_evidence_audio_preview",
                "source_revision_id": str(live.id), "recorded_by": str(actor.public_id), "recorded_at": now.isoformat()}
            current.validation_evidence = {**current.validation_evidence, "publication_clearance": clearance}
            current.version += 1
            current.save()
            audit(actor, "revision.evidence", current, {"publication_clearance": evidence_ref, "channel": "server_job"})

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
