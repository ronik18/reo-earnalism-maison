"""Stage an owner-cleared full film (with synced captions) on a clone of a live edition, then publish it after a
fresh browser acceptance of that exact staged revision (owner decision 24 Nov 2026: full films on Maison from
private R2; Cloudflare Stream stays unprovisioned).

  attach_audiovisual_film stage <slug> --publisher <public_id> --bundle <dir> --evidence <docs/evidence/...json>
  attach_audiovisual_film publish <slug> --publisher <public_id> --browser-report <repo-relative json>

The same audited path as attach_audiovisual_audio, whose Command this subclasses: a named active verified staff
publisher, private storage, rights rows, validation evidence and library.services.transition_revision. Audio and
film stage into one draft of the live revision (whichever runs second joins the first one's draft) and publish
together; a browser report must then cover audio_playback and video_playback.

Bundle layout (--bundle <dir>, written by `eav bundle-film`), nothing else is accepted:

  <dir>/film.json  {"schema": "earnalism.audiovisual-film-bundle.v1",
                    "units": [{"unit_id": "<live unit id>", "mp4": "film.mp4", "vtt": "film.vtt",
                               "mp4_sha256": <hex>, "vtt_sha256": <hex>, "duration_ms": <int>, "bytes": <int>}]}
  <dir>/<mp4>      per unit: a faststart MP4 (top-level moov before mdat) of exactly one H.264 video stream and
                   one AAC audio stream, at most 1 073 741 824 bytes; the ffprobe-measured duration is stored,
                   the bundle's duration_ms claim is not.
  <dir>/<vtt>      per unit: WebVTT captions (starts with WEBVTT), at most 1 048 576 bytes.

Every hash and size is recomputed here; any mismatch refuses before mutation.

--evidence: earnalism.audiovisual-clearance-evidence.v1 as for audio (owner_approval, live text hash, the active
whitelist, the completed per-title record), with "reader" and "video" in formats and video_sha256 equal to the
bundle's mp4_sha256 values.

stage: clone the live revision (or join the staged audio draft of it); store each MP4 with
storage.put_private_file as kind=video, provider=r2, video/mp4, bound to its unit with the measured duration, and
each VTT as kind=video_captions (text/vtt); record measurement evidence; set access video=free; re-approve the
copied cleared rights and add approved non-test video read rights for the whitelist; record publication_clearance
for every offered format bound to every ready asset hash (captions included). The draft stays a DRAFT with no
browser evidence. Reruns report the same draft; once published they report already_live. Replacing a film that
the live revision already carries is refused.

publish: --browser-report {"sha256": <staged content_sha256>, "status": "pass", "scope": "...",
"checks": {"video_playback": true, ...}} (plus audio_playback when audio is staged on the same draft).
"""
import json
import math
import re
import struct
import subprocess
from pathlib import Path

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from core.api import DomainError
from core.services import audit
from library import storage
from library.models import Asset, Revision
from library.services import canonical_bytes, digest
from operations.management.commands import attach_audiovisual_audio as audio
from operations.management.commands.export_audiovisual_source import has_public_domain_evidence
from operations.management.commands.publish_cleared_editions import sha256, stable_id

BUNDLE_SCHEMA = "earnalism.audiovisual-film-bundle.v1"
UNIT_KEYS = {"unit_id", "mp4", "vtt", "mp4_sha256", "vtt_sha256", "duration_ms", "bytes"}
MAX_FILM_BYTES = 1_073_741_824
MAX_VTT_BYTES = 1_048_576
MAX_MANIFEST_BYTES = 1_048_576
HEX64 = re.compile(r"[a-f0-9]{64}")
WEBVTT = re.compile(rb"\A(?:\xef\xbb\xbf)?WEBVTT(?:[ \t\r\n]|\Z)")


def is_faststart(path):
    """True when the top-level moov box precedes mdat. Reads box headers only; a malformed box is False."""
    size = Path(path).stat().st_size
    with open(path, "rb") as stream:
        pos = 0
        while pos + 8 <= size:
            stream.seek(pos)
            length, kind = struct.unpack(">I4s", stream.read(8))
            header = 8
            if length == 1:
                if pos + 16 > size:
                    return False
                length, header = struct.unpack(">Q", stream.read(8))[0], 16
            elif length == 0:
                length = size - pos
            if length < header or pos + length > size:
                return False
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            pos += length
    return False


def measure_film(path, *, timeout_seconds=20):
    """Bounded container measurement: exactly one H.264 video and one AAC audio stream, finite duration."""
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
                                 "format=duration:stream=codec_name,codec_type", "-of", "json", str(Path(path).resolve())],
                                capture_output=True, check=True, timeout=timeout_seconds)
        if len(result.stdout) > 65536:
            raise ValueError
        measured = json.loads(result.stdout)
        kinds = sorted((s.get("codec_type"), s.get("codec_name")) for s in measured["streams"])
        duration = float(measured["format"]["duration"])
    except Exception:
        raise CommandError(f"{Path(path).name}: ffprobe could not measure the film.") from None
    if kinds != [("audio", "aac"), ("video", "h264")]:
        raise CommandError(f"{Path(path).name}: the film must be exactly one H.264 video stream plus one AAC audio "
                           f"stream; found {kinds}.")
    if not math.isfinite(duration) or duration <= 0:
        raise CommandError(f"{Path(path).name}: the film has no measurable duration.")
    return {"duration_ms": round(duration * 1000), "measurement_sha256": sha256(result.stdout),
            "method": "ffprobe exact retained MP4; container metadata only, not viewing QA"}


def _plain_name(value, suffix):
    return isinstance(value, str) and Path(value).name == value and value.lower().endswith(suffix) and value != suffix


def read_film_bundle(folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise CommandError(f"Bundle directory not found: {folder}")
    manifest_path = folder / "film.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise CommandError("Bundle requires a bounded film.json.")
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw)
        rows = manifest["units"]
        if set(manifest) != {"schema", "units"} or manifest["schema"] != BUNDLE_SCHEMA or not isinstance(rows, list) or not rows:
            raise ValueError
        for row in rows:
            if (not isinstance(row, dict) or set(row) != UNIT_KEYS or not isinstance(row["unit_id"], str)
                    or not _plain_name(row["mp4"], ".mp4") or not _plain_name(row["vtt"], ".vtt")
                    or not all(isinstance(row[k], str) and HEX64.fullmatch(row[k]) for k in ("mp4_sha256", "vtt_sha256"))
                    or not all(type(row[k]) is int for k in ("duration_ms", "bytes"))):
                raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise CommandError(f'film.json must be {{"schema": "{BUNDLE_SCHEMA}", "units": [{{{", ".join(sorted(UNIT_KEYS))}}}]}}.') from None
    names = [row["mp4"] for row in rows] + [row["vtt"] for row in rows]
    if len(set(names)) != len(names) or len({row["unit_id"] for row in rows}) != len(rows):
        raise CommandError("film.json must name distinct files, one film per distinct unit.")
    for entry in sorted(folder.iterdir()):
        if entry.name != "film.json" and entry.name not in names:
            raise CommandError(f"Bundle holds {entry.name!r}, which film.json does not list; remove it.")
        if not entry.is_file():
            raise CommandError(f"Bundle entry {entry.name!r} is not a file.")
    units = []
    for row in rows:
        mp4, vtt = folder / row["mp4"], folder / row["vtt"]
        if not mp4.is_file() or not vtt.is_file():
            raise CommandError(f"Bundle lacks {row['mp4']} or {row['vtt']}.")
        size = mp4.stat().st_size
        if not 1 <= size <= MAX_FILM_BYTES:
            raise CommandError(f"{row['mp4']} is {size} bytes; at most {MAX_FILM_BYTES} bytes are allowed.")
        if size != row["bytes"]:
            raise CommandError(f"film.json bytes {row['bytes']} differs from {row['mp4']} ({size} bytes).")
        if not is_faststart(mp4):
            raise CommandError(f"{row['mp4']} is not faststart (the top-level moov box must precede mdat).")
        mp4_sha = audio.file_sha256(mp4)
        if mp4_sha != row["mp4_sha256"]:
            raise CommandError(f"film.json mp4_sha256 differs from {row['mp4']}.")
        measured = measure_film(mp4)
        vtt_bytes = vtt.stat().st_size
        if not 1 <= vtt_bytes <= MAX_VTT_BYTES:
            raise CommandError(f"{row['vtt']} is {vtt_bytes} bytes; captions must be 1..{MAX_VTT_BYTES} bytes.")
        vtt_raw = vtt.read_bytes()
        if sha256(vtt_raw) != row["vtt_sha256"]:
            raise CommandError(f"film.json vtt_sha256 differs from {row['vtt']}.")
        if not WEBVTT.match(vtt_raw):
            raise CommandError(f"{row['vtt']} is not WebVTT (it must start with WEBVTT).")
        try:
            vtt_raw.decode("utf-8")
        except UnicodeDecodeError:
            raise CommandError(f"{row['vtt']} is not UTF-8.") from None
        units.append({"unit_id": row["unit_id"],
                      "mp4": {"path": mp4, "sha256": mp4_sha, "bytes": size, **measured},
                      "vtt": {"path": vtt, "sha256": row["vtt_sha256"], "bytes": vtt_bytes}})
    bundle_sha = digest(canonical_bytes({"film_json_sha256": sha256(raw),
                                         "mp4": {u["unit_id"]: u["mp4"]["sha256"] for u in units},
                                         "vtt": {u["unit_id"]: u["vtt"]["sha256"] for u in units}}))
    return {"units": units, "bundle_sha256": bundle_sha}


def check_film_evidence(doc, slug, live, bundle):
    audio.check_evidence_identity(doc, slug, live)
    formats = doc.get("formats")
    if (not isinstance(formats, list) or len(set(map(str, formats))) != len(formats) or not {"reader", "video"} <= set(formats)
            or set(formats) - {"reader", "audio", "video"}):
        raise CommandError('Clearance evidence formats must include "reader" and "video" (no other values).')
    video = doc.get("video_sha256")
    if not isinstance(video, list) or sorted(map(str, video)) != sorted(u["mp4"]["sha256"] for u in bundle["units"]):
        raise CommandError("Clearance evidence video_sha256 differs from the bundle mp4_sha256 values.")
    audio.check_record_complete(doc)


class Command(audio.Command):
    help = ("Stage an owner-cleared full film with captions on a clone of a live edition (private R2), then publish "
            "after browser acceptance. Bundle layout and evidence schema: see this module's docstring.")
    MARKER = "audiovisual_film"
    FORMAT = "video"
    BUNDLE_HELP = "stage: directory holding film.json and its listed MP4 and VTT files only"
    REASON = "Owner-cleared full film with captions"

    def stage(self, actor, edition, live, options):
        slug = edition.slug
        bundle = read_film_bundle(options["bundle"])
        doc, _, evidence_ref = audio.read_evidence(options["evidence"])
        shas = sorted(u["mp4"]["sha256"] for u in bundle["units"])
        live_video = sorted(live.assets.filter(kind="video").values_list("sha256", flat=True))
        if live_video:
            if live_video == shas and live.validation_evidence.get(self.MARKER, {}).get("bundle_sha256") == bundle["bundle_sha256"]:
                return self.emit({"status": "already_live", "edition_id": str(edition.id), "revision_id": str(live.id),
                                  "bundle_sha256": bundle["bundle_sha256"], "video_sha256": shas})
            raise CommandError(f"{slug}: the live revision already carries a different film; replacing it is not supported here.")
        if not has_public_domain_evidence(live):
            raise CommandError(f"{slug}: live revision lacks passing public-domain publication clearance; refused.")
        check_film_evidence(doc, slug, live, bundle)
        plan = self.preflight(live, bundle)
        draft = self.find_or_clone(actor, edition, live, bundle)
        if draft.state == "draft" and not draft.assets.filter(kind="video").exists():
            self.attach(actor, live, draft, bundle, plan, evidence_ref)
        draft.refresh_from_db()
        self.emit({"status": "staged", "edition_id": str(edition.id), "revision_id": str(draft.id), "state": draft.state,
            "content_sha256": draft.content_sha256, "source_revision_id": str(live.id), "bundle_sha256": bundle["bundle_sha256"],
            "evidence_ref": evidence_ref,
            "asset_sha256": {str(a.id): a.sha256 for a in draft.assets.filter(state="ready")},
            "film": [{"unit_id": str(a.unit_id), "asset_id": str(a.id), "sha256": a.sha256, "duration_ms": a.duration_ms}
                     for a in draft.assets.filter(kind="video").order_by("unit__ordinal")]})

    def preflight(self, live, bundle):
        units = {str(u.id): u.ordinal for u in live.units.all()}
        plan = []
        for item in bundle["units"]:
            if item["unit_id"] not in units:
                raise CommandError(f"film.json unit {item['unit_id']} is not a unit of the live revision.")
            plan.append({**item, "unit_ordinal": units[item["unit_id"]]})
        return plan

    def attach(self, actor, live, draft, bundle, plan, evidence_ref):
        units = {u.ordinal: u for u in draft.units.all()}
        prepared = []
        for item in plan:
            unit, mp4, vtt = units[item["unit_ordinal"]], item["mp4"], item["vtt"]
            video_id = stable_id(draft.id, "video", unit.ordinal, mp4["sha256"])
            captions_id = stable_id(draft.id, "video_captions", unit.ordinal, vtt["sha256"])
            video_key, captions_key = f"revisions/{draft.id}/{video_id}.mp4", f"revisions/{draft.id}/{captions_id}.vtt"
            try:
                storage.put_private_file(video_key, mp4["path"], "video/mp4", mp4["bytes"], mp4["sha256"])
                storage.put_private_file(captions_key, vtt["path"], "text/vtt", vtt["bytes"], vtt["sha256"])
            except DomainError as exc:
                raise CommandError(f"{exc.code}: {exc.message}") from None
            video = Asset(id=video_id, revision=draft, unit=unit, kind="video", state="ready", provider="r2",
                          storage_key=video_key, sha256=mp4["sha256"], bytes=mp4["bytes"], content_type="video/mp4",
                          duration_ms=mp4["duration_ms"])
            captions = Asset(id=captions_id, revision=draft, unit=unit, kind="video_captions", state="ready", provider="r2",
                             storage_key=captions_key, sha256=vtt["sha256"], bytes=vtt["bytes"], content_type="text/vtt")
            prepared.append((item, unit, video, captions))
        now = timezone.now()
        with transaction.atomic():
            current = Revision.objects.select_for_update().get(pk=draft.pk)
            if current.state != "draft" or current.content_sha256 != draft.content_sha256:
                raise CommandError("Clone changed while attaching the film; review the current draft.")
            evidence = dict(current.validation_evidence)
            media = dict(evidence.get("media_assets", {}))
            for item, unit, video, captions in prepared:
                for asset in (video, captions):
                    asset.revision = current
                    asset.save()
                    audit(actor, "asset.complete", asset, {"sha256": asset.sha256, "kind": asset.kind, "unit_id": str(unit.id),
                          "duration_ms": asset.duration_ms, "channel": "server_job"})
                mp4 = item["mp4"]
                media[str(video.id)] = {"sha256": video.sha256, "unit_id": str(unit.id), "duration_ms": mp4["duration_ms"],
                    "codecs": ["h264", "aac"], "faststart": True, "captions_asset_id": str(captions.id), "prepared": True,
                    "measurement_evidence": f"audiovisual_film_bundle:{bundle['bundle_sha256']}/ffprobe:{mp4['measurement_sha256']}",
                    "actual_viewing": False}
                media[str(captions.id)] = {"sha256": captions.sha256, "unit_id": str(unit.id), "video_asset_id": str(video.id),
                    "format": "webvtt", "prepared": True}
            evidence["media_assets"] = media
            current.validation_evidence = evidence
            current.access_policy = {**current.access_policy, "video": "free"}
            current.save()
            self.approve_rights(actor, live, current, evidence_ref, now)
            self.record_clearance(actor, live, current, evidence_ref, now)
