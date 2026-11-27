"""earnalism-audiovisual orchestrator: one title root, one production record, one next action.

  python3 -m eav.cli init <source.json> --root <dir> [--slug <maison-edition-slug>]
  python3 -m eav.cli plan --root <dir>
  python3 -m eav.cli job <narration|stills|music|reel_clips> --root <dir> --rates <rates.json>
                         [--film N | --reel N] [--spec <spec.json>] [--clause "..."]
  python3 -m eav.cli job retouch --root <dir> --rates <rates.json> --film N --spec <retouch.json>
                         [--job-id <id>]  (inpaint masked regions of imported stills; candidates;
                         references/visual-style.md, Retouch)
  python3 -m eav.cli job edit --root <dir> --rates <rates.json> --film N --spec <edit.json>
                         [--job-id <id>]  (Qwen-Image-Edit-2511 instruction edits of imported stills
                         with up to 2 reference images; candidates; references/visual-style.md, Edit)
  python3 -m eav.cli job narration --root <dir> --rates <rates.json> [--film N | --reel N]
                         --expressive [--directions <directions.json>] [--voice <OWNER_SELECTED
                         storyteller preset>] [--list-units]   (storyteller style, references/earnalism-voice.md)
  python3 -m eav.cli job narration --root <dir> --rates <rates.json> --audition <audition.json>
                         (one Colab job: 3 passages x candidate storyteller presets + the current preset)
  python3 -m eav.cli import-take <film-NN|reel-N> --root <dir> --scripts <dir of <key>.txt> --audio
                         <dir of <key>.mp3> --engine elevenlabs --model eleven_v3 --voice-id <id>
                         --voice-name "<name>" --credits <credits used>
                         (ElevenLabs: one tagged-script take per scene, key = scene_id; a reel's
                         one take is keyed by its target; references/earnalism-voice.md)
  python3 -m eav.cli import <job_id> --root <dir> --from <folder|archive> --units <CU>
                         [--archive-sha256 <sha>]           (reel_clips)
  python3 -m eav.cli exchange-stage <job_id> --root <dir> [--account <id> --bucket <name>]
                         (uploads inputs.zip to R2, prints the two Maison presign commands)
  python3 -m eav.cli exchange-stage <job_id> --root <dir> --signed <presign output file>
                         (checks the signed URLs, writes jobs/<job_id>/exchange.json)
  python3 -m eav.cli exchange-collect <job_id> --root <dir> --units <CU Colab shows>
                         [--account <id> --bucket <name>]   (downloads outputs.tar, then import)
  python3 -m eav.cli supersede <job_id> --root <dir> --reason "<why it never ran>"
  python3 -m eav.cli close <job_id> --root <dir> --units <CU Colab shows> --reason "<what happened>"
  python3 -m eav.cli touchup --root <dir> --film N --spec <touchup.json> --job-id <id>
                         (local OpenCV repaint of hand-placed boxes of imported stills: inpaint,
                         recolor, fill, clone; one <key>--c1 candidate + <key>--mask per item)
  python3 -m eav.cli glide <image> <depth.png|depth.npy|-> <out.mp4> --seconds S [--zoom 0.12 --pan-x 0 --pan-y 0
                         --ease both|in|out|none --flat --sweep down-left|down-right --drain]
                         (no --root: a layered 2.5D camera glide of one still, 1920x1080 at 24 fps; "-" = flat)
  python3 -m eav.cli retime <take.mp3|wav> <out.wav> --text <script text file> [--seed 0 --cuts 1.2,3.4]
                         (no --root: pauses detected, re-timed by punctuation, filled with the take's room tone;
                         prints JSON with the cut times mapped into the new timeline and the new duration)
  python3 -m eav.cli pick --root <dir> --job <stills|retouch|touchup|edit job id> --choices <{"<key>": N} json file>
                         (after review: one candidate per <key>--cN still; film uses only picks)
  python3 -m eav.cli hold --root <dir> --film N --keys k1,k2,... [--clear]
                         (shots with no approved still: the film shows the scene's nearest approved still;
                         a picked edit of a held key releases that key)
  python3 -m eav.cli film --root <dir> [--film N] --logo <png> --end-card <png>
                         (--score <wav> --score-route vcsl|ace-step:<job_id> | --cues-job <id>)
  python3 -m eav.cli reel <n> --root <dir> --script <script.json> [--hashtags ...]
  python3 -m eav.cli reel <n> --root <dir> --plan-shots           (after reel narration import)
  python3 -m eav.cli reel <n> --root <dir> [--score <wav> --score-route ...]
  python3 -m eav.cli qc --root <dir>
  python3 -m eav.cli status --root <dir>
  python3 -m eav.cli bundle-audio --root <dir> --out <bundle dir>
                         (--score-dir <dir> --score-route vcsl|ace-step:<job_id> | --dry)
  python3 -m eav.cli bundle-film --root <dir> --film film-NN --unit-id <uuid> --out <bundle dir>
                         (faststart MP4 + WebVTT + film.json for Maison private R2)

Every command ends with "Next: ..." -- the one action the owner (or Claude) takes next.
Reels: script -> reel narration (measured) -> --plan-shots (ceil(narration / 5.04 s) Wan clips)
-> keyframe stills -> reel_clips batches of <= 5 shots (one Wan job each) -> reel.
The CLI wraps the eav modules; it spends nothing, runs no GPU work, never marks legal clearance
and never publishes. Exit codes: 0 ok, 2 stop, 3 budget exceeded, 4 import held, 5 QC failure.
The allowance ledger is shared by every title and pinned in record.json at init (--ledger,
else $EAV_LEDGER, else <root>/../allowance-ledger.json); later commands refuse any other path.
The 60 CU title cap is lifetime; the 100 CU cap is per calendar month.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from . import budget, colab_jobs, exchange, film, film_bundle, importer, mix, qc, reel, scenes, take
from . import glide, retime, touchup
from .record import Record, sha256_file
from .text import sentences
from .voice import CONTINUOUS, EXPRESSIVE, unit_anchors, voice_units

PROG = "python3 -m eav.cli"
ROSTER = (Path(__file__).resolve().parents[3] / "earnalism-audiobook-go-live" / "references"
          / "final-voice-roster.json")
STORY_PROFILE = {"en": "en_tisha", "bn": "bn_arnav"}
STORYTELLER_ROSTER = Path(__file__).resolve().parents[2] / "references" / "storyteller-voices.json"
OWNER_SELECTED = "OWNER_SELECTED"
AUDITION_TARGET = "audition"
EVIDENCE_SCHEMA = "earnalism.audiovisual-clearance-evidence.v1"
EVIDENCE_DRAFT = "audiovisual-clearance-evidence.draft.json"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
SHA = re.compile(r"[0-9a-f]{64}")
FILM_LUFS, REEL_LUFS, LUFS_TOL, TP_MAX = -16.0, -14.0, 1.0, -1.0
LOOP_MIN = 0.8
HOOK_ONSET_MAX_S = 0.2
MP3_END_SLACK_MS = 50
TAKE_JOB = "narration_take"   # artifact kind of an imported ElevenLabs take job (its manifest)
TOUCHUP_JOB = "touchup_job"   # artifact kind of a local touch-up job (its manifest)
TOUCHUP_SCHEMA = "earnalism.audiovisual-touchup.v1"
TAKE_ENGINES = {"elevenlabs": ("eleven_v3",)}  # owner decision 2026-11-24
TAKE_AUDIO = (".mp3", ".wav")
TAKE_SCHEMA = "earnalism.audiovisual-take-import.v1"


class Stop(Exception):
    def __init__(self, message, next_action, code=2):
        super().__init__(message)
        self.next_action, self.code = next_action, code


# ---------------------------------------------------------------- state helpers
_MONTH = None  # test injection only; there is deliberately no --month flag


def _requested_ledger(args):
    path = args.ledger or os.environ.get("EAV_LEDGER")
    return Path(path).resolve() if path else None


def _ledger(rec, args) -> budget.Ledger:
    """The ledger pinned in record.json at init, relative to the record root (R17); any other
    path is refused, so a moved or copied checkout keeps the same caps."""
    pinned = rec.data.get("ledger")
    if not pinned:
        raise Stop("this record has no pinned allowance ledger", "Re-run init for this title root")
    if Path(pinned).is_absolute() or PureWindowsPath(pinned).is_absolute():
        raise Stop(f"record.json pins the ledger by an absolute path ({pinned}); it would be missed "
                   "from another checkout and the caps would read 0",
                   f"Re-run init for this title root so the ledger is pinned relative to it: "
                   f"{PROG} init <source.json> --root <new root> --ledger <the shared ledger>")
    path = (rec.root / pinned).resolve()
    asked = _requested_ledger(args)
    if asked is not None and asked != path:
        raise Stop(f"ledger {asked} differs from the ledger pinned at init ({path}); the "
                   "allowance cannot be split across ledgers",
                   "Drop --ledger / unset EAV_LEDGER and rerun")
    return budget.Ledger(path)


def _month() -> str:
    return _MONTH or datetime.now(timezone.utc).strftime("%Y-%m")


def _score_route(rec, route) -> str:
    """vcsl (cleared VCSL editorial score) or ace-step:<imported music job id>."""
    if route == "vcsl":
        return route
    m = re.fullmatch(r"ace-step:([a-z0-9][a-z0-9-]*)", route or "")
    if m and any(j["job_id"] == m.group(1) and j["kind"] == "music" and j["imported"]
                 for j in _jobs(rec)):
        return route
    raise Stop(f"score route {route!r} is not vcsl or ace-step:<imported music job id>",
               "Pass --score-route vcsl or --score-route ace-step:<job_id>")


def _music_licence(route) -> dict:
    """Route and licence of a score for the clearance record (R24)."""
    if route == "vcsl":
        return {"route": route, "licence": "CC0-1.0", "music_job_id": None,
                "source_and_licence": "VCSL (Versilian Community Sample Library) piano/harp samples, CC0-1.0, "
                                      "via earnalism-audiobook-score editorial_score.py "
                                      "(earnalism-video/software/assets/music/vcsl-piano-harp-v1)"}
    job_id = route.split(":", 1)[1]
    return {"route": route, "licence": "Apache-2.0", "music_job_id": job_id,
            "source_and_licence": f"ACE-Step {colab_jobs.MUSIC_REPO}, Apache-2.0, instrumental cues from "
                                  f"imported music job {job_id} (revision, seeds and hashes in its manifest)"}


def _check_bed(bed: Path, needed_s: float, what: str) -> None:
    have = film._duration(bed)
    if have + 0.05 < needed_s:
        raise Stop(f"score bed {bed} ({have:.2f} s) is shorter than the {what} ({needed_s:.2f} s)",
                   "Extend the bed in `earnalism-audiobook-score` so it covers the narration, then rerun")


def _record(root) -> Record:
    if not (Path(root) / "record.json").is_file():
        raise Stop(f"no production record in {root}",
                   f"{PROG} init <source.json> --root {root} --slug <maison-edition-slug>")
    return Record.load(root)


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def _plan(rec) -> dict:
    p = rec.root / "plan.json"
    if not p.is_file():
        raise Stop("no scene plan yet", f"{PROG} plan --root {rec.root}")
    return _json(p)


def _jobs(rec) -> list:
    """Every built job with its target, its build order and how it ended (if it has)."""
    events = rec.data["events"]
    targets, order, details = {}, {}, {}
    for i, e in enumerate(events):
        if e["stage"] == "cli" and e["result"] == "job_target":
            targets[e["detail"]["job_id"]], order[e["detail"]["job_id"]] = e["detail"]["target"], i
            details[e["detail"]["job_id"]] = e["detail"]
    done = {r: {e["detail"]["job_id"] for e in events if e["stage"] == s_ and e["result"] == r}
            for s_, r in (("import", "accepted"), ("job", "superseded"), ("job", "closed"),
                          ("job", "superseding"), ("job", "closing"))}
    out = []
    for a in rec.data["artifacts"]:
        if a["kind"] not in ("colab_job", TAKE_JOB, TOUCHUP_JOB):
            continue
        m = a["meta"]
        jid = m["job_id"]
        colab = a["kind"] == "colab_job"  # an imported take or touch-up has no notebook or zip
        out.append({"job_id": jid, "kind": m["job_kind"], "target": targets.get(jid),
                    "engine": details.get(jid, {}).get("engine", "parler"),
                    "order": order.get(jid, -1),
                    # narration voice style and storyteller preset (None: the default style/plan voice)
                    "style": details.get(jid, {}).get("voice_style"),
                    "voice": details.get(jid, {}).get("voice"),
                    "notebook": rec.root / a["path"] if colab else None,
                    "inputs_zip": rec.root / m["inputs_zip"] if colab else None,
                    "manifest": rec.root / m["manifest"], "forecast_units": m["forecast_units"],
                    "imported": jid in done["accepted"],
                    "superseded": jid in done["superseded"],
                    "closed": jid in done["closed"],
                    # a supersede/close that recorded its intent but has not finished (R23)
                    "unfinished": (jid in done["superseding"] and jid not in done["superseded"])
                    or (jid in done["closing"] and jid not in done["closed"])})
    return out


def _ended(j) -> bool:
    """Superseded (never ran) or closed (ran, not imported): it produces nothing more."""
    return j["superseded"] or j["closed"]


def _latest_job(rec, kind, target, imported=True, after=-1):
    found = [j for j in _jobs(rec) if j["kind"] == kind and j["target"] == target
             and not _ended(j) and j["order"] > after and (j["imported"] or not imported)]
    return found[-1] if found else None


def _last_event(rec, stage, result, target) -> int:
    """Index of the last stage/result event for target, or -1."""
    return max((i for i, e in enumerate(rec.data["events"]) if e["stage"] == stage
                and e["result"] == result and e["detail"].get("target") == target), default=-1)


def _reel_narration(rec, n, imported=True):
    """The reel's narration job built after its current script (R20)."""
    t = f"reel-{n}"
    return _latest_job(rec, "narration", t, imported, after=_last_event(rec, "reel", "scripted", t))


def _misfits(rec) -> set:
    return {e["detail"]["narration_job_id"] for e in rec.data["events"]
            if e["stage"] == "reel" and e["result"] == "narration_misfit"}


def _plan_event(rec, n):
    """(index, detail) of the current shots_planned event for reel n, or (-1, None)."""
    t = f"reel-{n}"
    planned = _last_event(rec, "reel", "shots_planned", t)
    if planned < 0 or planned < _last_event(rec, "reel", "scripted", t):
        return -1, None
    return planned, rec.data["events"][planned]["detail"]


def _planned_shots(rec, n):
    """shots.json, but only when planned from this script's measured narration (R20)."""
    planned, _ = _plan_event(rec, n)
    if planned < 0:
        return None, -1
    return _json(rec.root / "reels" / f"reel-{n}" / "shots.json"), planned


def _bound_plan(rec, n):
    """R27: the current shot plan, checked to be exactly what --plan-shots wrote and still bound
    to the narration it was planned from (the latest imported reel narration, not ended)."""
    t = f"reel-{n}"
    planned, detail = _plan_event(rec, n)
    if detail is None:
        raise Stop(f"{t} has no shot plan from its measured narration", next_action(rec.root))
    path = rec.root / "reels" / t / "shots.json"
    want = detail.get("shots_sha256")
    if want is None:  # plans before R27: the shot_list artifact recorded with the plan
        arts = [a for a in rec.data["artifacts"] if a["kind"] == "shot_list"
                and a["meta"].get("target") == t and a["meta"].get("narration_job_id")]
        want = arts[-1]["sha256"] if arts else None
    if not path.is_file() or sha256_file(path) != want:
        raise Stop(f"reels/{t}/shots.json is not the plan --plan-shots wrote; it is never edited by hand",
                   "Report this; restore it from git, never re-plan around it")
    narr_id = detail["narration_job_id"]
    job = next((j for j in _jobs(rec) if j["job_id"] == narr_id), None)
    latest = _reel_narration(rec, n)
    if job is None or _ended(job) or not job["imported"] or latest is None or latest["job_id"] != narr_id:
        raise Stop(f"{t} shots were planned from narration {narr_id}, but the latest imported reel "
                   f"narration is {latest['job_id'] if latest else 'missing'}; clips and assembly stay "
                   "bound to the planned narration",
                   "Re-voicing a reel: supersede (never ran) or close (ran) every reel_clips batch of "
                   f"the plan, then {PROG} reel {n} --root {rec.root} --script <script>, new reel "
                   "narration, a fresh --plan-shots and new batches (references/reel-recipe.md)")
    return _json(path), planned, narr_id


def _clip_jobs(rec, n, after, imported=False) -> list:
    t = f"reel-{n}"
    return [j for j in _jobs(rec) if j["kind"] == "reel_clips" and j["target"] == t
            and not _ended(j) and j["order"] > after and (j["imported"] or not imported)]


def _covered(rec, n, after) -> dict:
    """shot id -> the active reel_clips job that holds it."""
    out = {}
    for j in _clip_jobs(rec, n, after):
        for sc in _json(j["inputs_zip"].parent / "job.json")["scenes"]:
            out[sc["id"]] = j["job_id"]
    return out


def _check_clip_batch(rec, n, spec):
    """A reel_clips batch names only planned shots not already held by another batch."""
    shots, planned, _ = _bound_plan(rec, n)
    ids = [sh.get("id") for sh in spec.get("shots") or []]
    known = {sh["id"] for sh in shots}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise Stop(f"shot id(s) {', '.join(map(str, unknown))} are not planned in reels/reel-{n}/shots.json",
                   "Use the ids from shots.json")
    taken = _covered(rec, n, planned)
    clash = [f"{i} ({taken[i]})" for i in ids if i in taken]
    if clash:
        raise Stop(f"shot(s) {', '.join(clash)} are already in another reel_clips batch",
                   "Batch only the uncovered shots: " + next_action(rec.root))
    if len(ids) > colab_jobs.MAX_CLIPS_PER_BATCH:
        raise Stop(f"{len(ids)} shots in one batch: one Wan job holds at most "
                   f"{colab_jobs.MAX_CLIPS_PER_BATCH} (2700 s wall at ~500 s per clip)",
                   f"Split the shots into batches of at most {colab_jobs.MAX_CLIPS_PER_BATCH}")


def _artifacts(rec, kind, **meta):
    return [a for a in rec.data["artifacts"] if a["kind"] == kind
            and all(a["meta"].get(k) == v for k, v in meta.items())]


def _film_target(n: int) -> str:
    return f"film-{n:02d}"


def _reel_scene(script: dict, n: int) -> dict:
    return {"scene_id": f"r{n}", "blocks": [{"anchor_id": None, "kind": "line", "text": line}
                                            for line in reel.spoken(script)]}


def _reel_script(rec, n: int):
    p = rec.root / "reels" / f"reel-{n}" / "script.json"
    return _json(p) if p.is_file() else None


def _story_preset(language: str) -> dict:
    profile = STORY_PROFILE[language]
    preset = _json(ROSTER)["profiles"][profile]["presets"]["story"]
    return {"profile": profile, "preset_key": preset["preset_key"],
            "description": preset["description"], "roster_sha256": sha256_file(ROSTER),
            **{k: preset[k] for k in colab_jobs.GENERATION_KEYS if k in preset}}


def _storyteller(language: str, key=None) -> list:
    """Storyteller presets of the title language (all, or the one named)."""
    roster = _json(STORYTELLER_ROSTER)
    found = [p for lang, ps in roster["presets"].items() for p in ps if key in (None, p["preset_key"])
             and (key is not None or lang == language)]
    if key is not None and not found:
        raise Stop(f"{key} is not in {STORYTELLER_ROSTER.name}",
                   "Use a preset_key from references/storyteller-voices.json")
    for p in found:
        if p["language"] != language:
            raise Stop(f"{p['preset_key']} is a {p['language']} preset; this title's language is {language}",
                       "Use a storyteller preset of the title's language")
    return found


def _voice_preset(p: dict) -> dict:
    return {"description": p["description"], "speaker": p["speaker"],
            **{k: p[k] for k in colab_jobs.GENERATION_KEYS if k in p}}


def _production_storyteller(language: str, key: str) -> dict:
    p = _storyteller(language, key)[0]
    if p.get("status") != OWNER_SELECTED:
        raise Stop(f"{key} is {p.get('status')!r}, not {OWNER_SELECTED}: a storyteller preset voices "
                   "production narration only after the owner picks it from an audition",
                   f"{PROG} job narration --root <dir> --rates <rates.json> --audition <audition.json>, "
                   "then the owner listens and selects (references/earnalism-voice.md)")
    return p


def _plan_preset(plan: dict) -> dict:
    preset = {k: v for k, v in plan["voice"].items()
              if k == "description" or k in colab_jobs.GENERATION_KEYS}
    profile = (_json(ROSTER)["profiles"].get(plan["voice"].get("profile")) or {})
    if profile.get("speaker"):
        preset["speaker"] = profile["speaker"]
    return preset


def _audition_spec(rec, args, plan) -> dict:
    if args.reel or args.expressive or args.directions or args.voice or args.clause:
        raise Stop("--audition takes no --reel, --expressive, --directions, --voice or --clause: it "
                   "renders the control as production does today and every candidate in the storyteller style",
                   "Put the passages, optional candidates and optional directions in audition.json")
    lang = plan["language"]
    a = _json(args.audition)
    unknown = sorted(set(a) - {"passages", "candidates", "directions"})
    if unknown:
        raise Stop(f"audition.json has unknown field(s) {', '.join(unknown)}",
                   "Use passages {narration, dialogue, emotional}, optional candidates and directions")
    keys = a.get("candidates")
    candidates = ([_storyteller(lang, k)[0] for k in keys] if keys else _storyteller(lang))
    control = _plan_preset(plan)
    variants = [{"name": "control", "preset_key": plan["voice"]["preset_key"], "preset": control,
                 "style": None}]
    variants += [{"name": p["preset_key"].replace("::", "-"), "preset_key": p["preset_key"],
                  "preset": _voice_preset(p), "style": dict(EXPRESSIVE)} for p in candidates]
    return {"audition": {"passages": a.get("passages"), "language": lang, "variants": variants,
                         "directions": a.get("directions")}}


def _title_spent(ledger, rec) -> float:
    """Lifetime spend of this title, keyed by the export's edition_id (R26)."""
    return ledger.spent(rec.data["title_slug"], None, rec.data["source"].get("edition_id"))


def _remaining(ledger, rec, month) -> float:
    cap = budget.title_cap(ledger.path, rec.data["title_slug"])
    return min(cap - _title_spent(ledger, rec),  # title cap: lifetime
               budget.MONTH_CAP - ledger.spent(None, month))


def _measured_track(units, wav_dir: Path, out: Path, job_id: str):
    """film.narration_track over the imported WAVs, plus provenance of what was measured."""
    timing = film.narration_track(units, wav_dir, out)
    provenance = {"method": "eav.film.narration_track", "measured_with": "ffprobe",
                  "narration_job_id": job_id,
                  "wav_sha256": {u["unit_key"]: sha256_file(Path(wav_dir) / f"{u['unit_key']}.wav")
                                 for u in units},
                  "track_sha256": sha256_file(out)}
    return timing, provenance


def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", *map(str, args)], check=True)


# ---------------------------------------------------------------- next action
def _wan_action(rec, job) -> str:
    """The wan22 batch notebook's own flags and the owner-written authority file (R22)."""
    job_json = job["inputs_zip"].parent / "job.json"
    wall = _json(job_json)["wall_seconds"]
    return (f"Owner runs the Wan 2.2 batch notebook {job['notebook']} in Colab (L4). It has no RUN flag; "
            "set each flag to True in its cell only after the previous step succeeded: RUN_BATCH "
            f"(prepare the bound software); upload {job['inputs_zip']} with Colab Files as "
            "/content/wan22-batch-inputs.zip, then VERIFY_INPUTS; the OWNER (Claude never writes or "
            "edits this file) writes and signs /content/wan22-batch-authority.json for this exact job: "
            '{"schema": "earnalism.wan22-batch-authority.v1", "owner_authorized": true, '
            f'"job_sha256": "{sha256_file(job_json)}", "evidence_ref": "<the owner\'s own approval '
            'record>", "observed_units_per_hour": <the rate Colab shows for this allocation>, '
            '"approved_compute_units": <at most 5 and at least 2 x that rate x '
            f'{wall} / 3600>, "free_runtime_confirmed": false, "allocation_started_at": <unix time this '
            f"allocation started>}}; then BEGIN_ALLOCATION (binds the {wall} s wall, within the Wan "
            "contract's 2700 s, and arms the runtime unassign guard), SETUP_BATCH, GENERATE_BATCH "
            "(RESUME_UNATTEMPTED stays False), EXPORT_AND_DOWNLOAD; then: "
            f"{PROG} import {job['job_id']} --root {rec.root} --from <downloaded export archive.zip> "
            "--archive-sha256 <archive_sha256 from the printed export-receipt.json> --units <CU shown in "
            "Colab>; then LOCAL_IMPORT_VERIFIED and DISCONNECT_RUNTIME. If it ran but cannot be "
            f"imported: {PROG} close {job['job_id']} --root {rec.root} --units <CU shown in Colab> "
            '--reason "<what happened>"')


def _exchange_events(rec, job_id, result) -> list:
    return [e for e in rec.data["events"] if e["stage"] == "job" and e["result"] == result
            and e["detail"].get("job_id") == job_id]


def _colab_action(rec, job) -> str:
    if job["kind"] == "reel_clips":
        return _wan_action(rec, job)
    drive = _json(job["manifest"]).get("drive_dir", colab_jobs.DRIVE_ROOT)
    r = f"--root {rec.root}"
    staged = _exchange_events(rec, job["job_id"], "exchange_staged")
    if staged:
        ex = job["notebook"].parent / exchange.FILENAME
        return (f"R2 exchange staged (URLs expire {staged[-1]['detail']['expires_at']}): put {ex} and "
                f"{job['notebook']} in Drive {drive}/; the owner opens that notebook in Colab, sets "
                f"RUN = True in the first cell and runs all (inputs download and outputs upload "
                f"themselves). Then: {PROG} exchange-collect {job['job_id']} {r} --units <CU shown in "
                f"Colab>. If it ran but cannot be imported: {PROG} close {job['job_id']} {r} --units "
                '<CU shown in Colab> --reason "<what happened>" (references/colab-exchange.md)')
    if _exchange_events(rec, job["job_id"], "exchange_uploaded"):
        return (f"Sign the two exchange URLs printed by {PROG} exchange-stage {job['job_id']} {r} with "
                f"Maison (Render one-off job: presign_colab_exchange), save both JSON lines to a file "
                f"outside the repo, then: {PROG} exchange-stage {job['job_id']} {r} --signed <that file> "
                "(references/colab-exchange.md)")
    return (f"Default (R2 exchange, references/colab-exchange.md): {PROG} exchange-stage "
            f"{job['job_id']} {r} --account <cloudflare account id> --bucket <private bucket>. "
            f"Manual fallback: run the {job['kind']} notebook in Colab: copy {job['inputs_zip']} to Drive {drive}/, "
            f"open {job['notebook']}, set RUN = True in the first cell, Run all; download that Drive "
            f"folder, then: {PROG} import {job['job_id']} --root {rec.root} --from <downloaded folder> "
            f"--units <CU shown in Colab>. If it ran but cannot be imported (crash, hard stop, lost "
            f"download): {PROG} close {job['job_id']} --root {rec.root} --units <CU shown in Colab> "
            '--reason "<what happened>"')


def next_action(root) -> str:
    root = Path(root)
    if not (root / "record.json").is_file():
        return f"{PROG} init <source.json> --root {root} --slug <maison-edition-slug>"
    rec = Record.load(root)
    if not (root / "plan.json").is_file():
        return f"{PROG} plan --root {root}"
    jobs = _jobs(rec)
    unfinished = [j for j in jobs if j["unfinished"]]
    if unfinished:
        j = unfinished[0]
        return (f"Finish the interrupted supersede/close of {j['job_id']}: rerun the same "
                f"{PROG} supersede|close {j['job_id']} --root {root} command")
    pending = [j for j in jobs if not j["imported"] and not _ended(j)]
    if pending:
        return _colab_action(rec, pending[0])
    r = f"--root {root}"
    plan = _plan(rec)
    for i in range(1, len(plan["plan"]["films"]) + 1):
        t = _film_target(i)
        if not _latest_job(rec, "narration", t):
            return (f"ElevenLabs route (owner decision 2026-11-24, references/earnalism-voice.md): one "
                    f"tagged-script Eleven v3 take per scene of film {i}, then {PROG} import-take "
                    f"{t} {r} --scripts <dir> --audio <dir> --engine elevenlabs --model eleven_v3 "
                    f"--voice-id <id> --voice-name \"<name>\" --credits <credits used>. Parler route: "
                    f"{PROG} job narration {r} --film {i} --rates <rates.json with measured "
                    f"s_per_step, units_per_hour, steps, decode_s, export_s>")
        if not _latest_job(rec, "stills", t):
            return (f"Write the world bible and one FLUX prompt per keyframe (keys <scene_id>-<k>, "
                    f"references/film-recipe.md) into stills.json, then: {PROG} job stills {r} "
                    f"--film {i} --rates <rates.json> --spec stills.json")
        if not _artifacts(rec, "film", target=t):
            return (f"{PROG} film {r} --film {i} --logo <approved logo lockup> --end-card <approved END> "
                    f"--score <score bed from earnalism-audiobook-score> --score-route vcsl "
                    f"(or --cues-job <imported ACE-Step music job_id>)")
    n = 1
    while True:
        script = _reel_script(rec, n)
        if script is None:
            if n == 1:
                return (f"Write reel 1 (hook, lines, loop_close; references/reel-recipe.md) into "
                        f"reel-1.json, then: {PROG} reel 1 {r} --script reel-1.json")
            break
        t = f"reel-{n}"
        folder = root / "reels" / t
        narr = _reel_narration(rec, n)
        if narr is None:
            return (f"Owner approves the reel {n} script ({folder / 'script.json'}); then one tagged "
                    f"Eleven v3 take of the whole reel and {PROG} import-take {t} {r} --scripts <dir "
                    f"with {t}.txt> --audio <dir with {t}.mp3> --engine elevenlabs --model eleven_v3 "
                    f"--voice-id <id> --voice-name \"<name>\" --credits <credits used> (Parler route: "
                    f"{PROG} job narration {r} --reel {n} --rates <rates.json>)")
        if narr["job_id"] in _misfits(rec):
            return (f"The measured reel {n} narration does not fit {script['length']} s +- "
                    f"{reel.FIT_TOLERANCE_S:g} s: rewrite the script's words (references/reel-recipe.md), "
                    f"then: {PROG} reel {n} {r} --script <new script.json>, and build new reel narration")
        shots, planned = _planned_shots(rec, n)
        if shots is None:
            return f"{PROG} reel {n} {r} --plan-shots"
        stills = _latest_job(rec, "stills", t, after=planned)
        if not stills:
            return (f"Write one keyframe prompt per shot of {folder / 'shots.json'} into stills.json "
                    f"(key = the shot id, e.g. shot-01; references/reel-recipe.md), then: {PROG} job "
                    f"stills {r} --reel {n} --rates <rates.json> --spec stills.json")
        covered = _covered(rec, n, planned)
        todo = [sh["id"] for sh in shots if sh["id"] not in covered]
        if todo:
            batch = todo[:colab_jobs.MAX_CLIPS_PER_BATCH]
            return (f"Write clips.json per references/reel-recipe.md (Clips spec): art_dir = "
                    f"{root / 'stills' / stills['job_id']}, prior_attempt_evidence = the retained Wan "
                    f"l4-balanced-v2 provenance (prior run ids, observed s/step, completed clips), "
                    f"shots = one {{id, image, seed, prompt}} for each of the next shots "
                    f"{', '.join(batch)} ({len(todo)} of {len(shots)} still need clips; at most "
                    f"{colab_jobs.MAX_CLIPS_PER_BATCH} per batch, one Wan job each), then: {PROG} job "
                    f"reel_clips {r} --reel {n} --rates <rates.json> --spec clips.json")
        if not _artifacts(rec, "reel", target=t):
            return f"{PROG} reel {n} {r} --score <reel score bed> --score-route vcsl|ace-step:<job_id>"
        n += 1
    last_media = max((i for i, e in enumerate(rec.data["events"])
                      if e["stage"] in ("film", "reel") and e["result"] == "assembled"), default=-1)
    qcs = [(i, e) for i, e in enumerate(rec.data["events"]) if e["stage"] == "qc"]
    if not qcs or qcs[-1][0] < last_media:
        return f"{PROG} qc {r}"
    if qcs[-1][1]["result"] != "pass":
        return ("Fix only the failing items in qc/report.json (regenerate failing shots/stills or "
                f"re-mix), re-assemble, then: {PROG} qc {r}")
    if not _artifacts(rec, "evidence_draft"):
        return ("Owner reviews the first package (opening, every join, climax, full ending); that review "
                f"is the listening assessment. Then for Maison audio: {PROG} bundle-audio {r} --out "
                f"{root / 'maison' / 'bundle'} --score-dir <one score bed per chapter> --score-route "
                f"vcsl|ace-step:<music job_id>. For Maison video (full films, private R2): {PROG} bundle-film. "
                "Social posting only to destinations the owner names (references/publishing.md).")
    return (f"Owner completes (territories, term_per_territory for every territory, text_source_licence, "
            f"cover_provenance) and approves {root / 'maison' / EVIDENCE_DRAFT}, saves it under docs/evidence/, "
            "then on the server: python manage.py attach_audiovisual_audio stage <slug> --publisher "
            "<public_id> --bundle <bundle dir> --evidence docs/evidence/<file>.json (references/publishing.md)")


# ---------------------------------------------------------------- commands
def cmd_init(args):
    src_path = Path(args.source)
    try:
        src = _json(src_path)
    except (OSError, ValueError) as e:
        raise Stop(f"no cleared source: cannot read {src_path}: {e}",
                   "Export it on the server: python manage.py export_audiovisual_source <slug> --out <path>")
    units = src.get("units") or []
    if src.get("language") not in STORY_PROFILE or not units or not SHA.fullmatch(
            str(src.get("content_sha256", ""))) or not src.get("revision_id") or any(
            not (p.get("text") or "").strip() for u in units for p in u.get("paragraphs") or [{}]):
        raise Stop("no cleared source: the export lacks language en/bn, units, paragraph text, "
                   "revision_id or content_sha256",
                   "Import and clear the edition with `earnalism-book-production`, then re-export it")
    if not isinstance(src.get("edition_id"), str) or not src["edition_id"].strip():
        raise Stop("no cleared source: the export has no edition_id (the allowance is keyed by it)",
                   "Re-export it on the server: python manage.py export_audiovisual_source <slug> --out <path>")
    if src.get("public_domain_evidence") is not True:
        raise Stop("the revision carries no passing public-domain publication clearance; "
                   "non-public-domain titles are out of scope for this skill",
                   "Hold the title. Clear the Reader edition first (`earnalism-book-production`)")
    slug = args.slug or src_path.stem
    if not SLUG.fullmatch(slug):
        raise Stop(f"slug {slug!r} is not a Maison edition slug", "Pass --slug <maison-edition-slug>")
    root = Path(args.root)
    if (root / "record.json").exists():
        raise Stop(f"{root} already holds a production record", f"{PROG} status --root {root}")
    ledger = _requested_ledger(args) or (root.parent / "allowance-ledger.json").resolve()
    here = Path(os.path.relpath(root.resolve(), ledger.parent)).as_posix()
    others = sorted(budget.Ledger(ledger).roots(src["edition_id"]) - {here})
    if others:  # R26: a second root would restart the title's lifetime cap
        raise Stop(f"edition {src['edition_id']} already has a title root on this ledger "
                   f"({', '.join(others)}); one production record per edition",
                   f"Continue that root: {PROG} status --root {ledger.parent / others[0]}")
    rec = Record.create(root, slug, {
        "edition_id": src.get("edition_id"), "revision_id": src["revision_id"],
        "content_sha256": src["content_sha256"], "language": src["language"],
        "rights": src.get("rights", {}), "public_domain_evidence": True,
        "state": src.get("state"), "export_sha256": sha256_file(src_path)})
    rec.data["ledger"] = Path(os.path.relpath(ledger, root.resolve())).as_posix()  # R17: relative pin
    rec._save()
    shutil.copyfile(src_path, root / "source.json")
    rec.add_artifact("source", root / "source.json", {"revision_id": src["revision_id"]})
    audio_read = "read" in (src.get("rights") or {}).get("audio", [])
    rec.event("init", "ok", {"slug": slug, "audio_rights_on_maison": audio_read})
    print(f"Initialised {slug}: revision {src['revision_id']}, {len(units)} units, "
          f"language {src['language']}.")
    if not audio_read:
        print("Maison audio is not cleared on this revision yet: production continues; Maison audio "
              "publication waits for the per-title evidence (bundle-audio drafts it, the owner approves it).")


def cmd_plan(args):
    rec = _record(args.root)
    if _jobs(rec):
        raise Stop("jobs were already built from the current plan; re-planning would desynchronise them",
                   f"{PROG} status --root {rec.root}")
    src = _json(rec.root / "source.json")
    p = scenes.plan_film(src, wpm=args.wpm)
    anchors = [p_["anchor_id"] for u in src["units"] for p_ in u["paragraphs"]]
    covered = []
    for f in p["films"]:
        for sc in f["scenes"]:
            covered += [a for a in sc["anchor_ids"] if not covered or covered[-1] != a]
    if covered != anchors:
        raise Stop("scene plan does not cover every paragraph in order", "Report this as a planner bug")
    voice = _story_preset(src["language"])
    path = _write_json(rec.root / "plan.json", {"plan": p, "voice": voice, "wpm": args.wpm,
                                                "language": src["language"]})
    rec.add_artifact("plan", path, {"films": len(p["films"]), "series": p["series"]})
    flags = [sc["scene_id"] + ":" + sc["flag"] for f in p["films"] for sc in f["scenes"] if sc["flag"]]
    rec.event("plan", "ok", {"films": len(p["films"]), "flags": flags, "voice": voice["preset_key"]})
    total = sum(sc["seconds"] for f in p["films"] for sc in f["scenes"])
    print(f"Planned {len(p['films'])} film(s), "
          f"{sum(len(f['scenes']) for f in p['films'])} scenes, ~{total / 60:.1f} min narration "
          f"(estimate; real timing is measured later). Voice {voice['preset_key']} byte-for-byte."
          + (" Series: one film per unit (over 40 min)." if p["series"] else ""))
    if flags:
        print("Flagged scenes: " + ", ".join(flags))


def _job_spec(rec, args, kind, target):
    plan = _plan(rec)
    lang = plan["language"]
    if kind == "narration" and args.audition:
        spec = _audition_spec(rec, args, plan)
    elif kind == "narration":
        if args.reel:
            planned, detail = _plan_event(rec, args.reel)
            if detail is not None:  # R27
                raise Stop(f"reel {args.reel} shots are already planned from narration "
                           f"{detail['narration_job_id']}; new narration would unbind them",
                           "Re-voicing a reel: supersede (never ran) or close (ran) every reel_clips "
                           f"batch of the plan, then {PROG} reel {args.reel} --root {rec.root} --script "
                           "<script>, build the new reel narration, run a fresh --plan-shots and "
                           "re-batch (references/reel-recipe.md)")
            script = _reel_script(rec, args.reel)
            if script is None:
                raise Stop(f"reel {args.reel} has no script", f"{PROG} reel {args.reel} --root {rec.root} --script <file>")
            todo = [_reel_scene(script, args.reel)]
        else:
            films = plan["plan"]["films"]
            if not 1 <= args.film <= len(films):
                raise Stop(f"film {args.film} is not in the plan ({len(films)} films)", f"{PROG} status --root {rec.root}")
            todo = films[args.film - 1]["scenes"]
        if args.directions and not args.expressive:
            raise Stop("--directions needs --expressive (the direction mode)",
                       "Rerun with --expressive --directions <file>")
        preset = (_voice_preset(_production_storyteller(lang, args.voice)) if args.voice
                  else _plan_preset(plan))
        spec = {"scenes": todo, "preset": preset,
                "language": lang, "clause": args.clause}
        if args.expressive:
            spec["style"] = dict(EXPRESSIVE)
        if args.directions:
            spec["directions"] = _json(args.directions)
    else:
        if args.audition or args.expressive or args.directions or args.voice or args.list_units:
            raise Stop("--audition, --expressive, --directions, --voice and --list-units are narration "
                       "options", f"Drop them from the {kind} job")
        if not args.spec:
            raise Stop(f"a {kind} job needs --spec (prompts, seeds{', shots' if kind == 'reel_clips' else ''})",
                       "Write it per references/film-recipe.md or references/reel-recipe.md")
        spec = _json(args.spec)
        if kind in ("retouch", "edit"):
            if args.reel:
                raise Stop(f"{kind} jobs patch a film's stills", "Pass --film <n>, not --reel")
            spec["target"] = target
        if kind == "reel_clips" and not Path(spec.get("art_dir", ".")).is_absolute():
            spec["art_dir"] = str((Path(args.spec).parent / spec.get("art_dir", ".")).resolve())
        if kind == "reel_clips":
            _check_clip_batch(rec, args.reel, spec)
    if args.job_id:
        spec["job_id"] = args.job_id
    try:
        return spec, colab_jobs.job_items(kind, spec)
    except ValueError as e:
        raise Stop(f"job not built: {e}", "Fix the directions, audition or clause and rerun")


def cmd_job(args):
    rec = _record(args.root)
    kind = args.kind
    if kind == "reel_clips" and not args.reel:
        raise Stop("reel_clips jobs belong to one reel", "Pass --reel <n>")
    target = (AUDITION_TARGET if kind == "narration" and args.audition
              else f"reel-{args.reel}" if args.reel else _film_target(args.film))
    spec, items = _job_spec(rec, args, kind, target)
    if args.list_units:  # for writing directions.json: the keys this job would use; nothing built
        for u in colab_jobs.narration_units(spec):
            print(f"{u['unit_key']}\t{u['text']}")
        return
    rates = _json(args.rates)
    try:  # R21: items and steps come from the job itself, rates from the last measured run
        compute = colab_jobs.derive_compute(kind, spec, rates, items)
    except ValueError as e:
        raise Stop(f"job not built: {e}", "Use the values measured on the last Colab run "
                   "(references/compute-budget.md) and never a compute block that differs from the job")
    ledger, month = _ledger(rec, args), _month()
    units = budget.forecast(compute, rates)
    remaining = _remaining(ledger, rec, month)
    if units > remaining:
        hint = "Hold the job and ask the owner; never retry past a cap."
        if kind == "reel_clips":
            fit = budget.fit_reel_job(compute, rates, remaining)
            if fit:
                hint = (f"The allowance covers {fit['items']} of these {items} shots: cut the clips "
                        f"spec's shots list to {fit['items']} entries and rerun (takes are fixed at 1 by "
                        "the Wan contract). The reel needs every planned shot, so the rest wait for "
                        "allowance; or hold for the owner.")
        raise Stop(f"Budget exceeded: forecast {units:.2f} CU > remaining {remaining:.2f} CU "
                   f"(caps {budget.title_cap(ledger.path, rec.data['title_slug']):g}/title, {budget.MONTH_CAP:g}/month, {month}). "
                   "Nothing was reserved or written.", hint, code=3)
    try:
        result = colab_jobs.build_job(kind, rec, spec, ledger, rates, rec.root / "jobs", month=month)
    except budget.BudgetExceeded as e:
        raise Stop(f"Budget exceeded: {e}. Nothing was written.",
                   "Hold the job and ask the owner; never retry past a cap.", code=3)
    except (ValueError, FileExistsError, KeyError) as e:
        raise Stop(f"job not built: {e}", "Fix the spec and rerun")
    detail = {"job_id": result["job_id"], "target": target, "kind": kind}
    if spec.get("style"):
        detail["voice_style"] = spec["style"]
    if kind == "narration" and args.voice:
        detail["voice"] = args.voice
    rec.event("cli", "job_target", detail)
    if target == AUDITION_TARGET:
        print("Audition job: the same passages in "
              + ", ".join(v["name"] for v in spec["audition"]["variants"])
              + ". Files <variant>__<unit_key>.wav; it is never film narration. After import the owner "
              "listens and selects a preset (references/earnalism-voice.md).")
    print(f"Built {kind} job {result['job_id']} for {target}: forecast {result['forecast_units']:.2f} CU "
          f"reserved ({remaining - result['forecast_units']:.2f} CU left under the title and month caps). "
          "Inert until the owner enables it in Colab.")


def cmd_import(args):
    rec = _record(args.root)
    job = next((j for j in _jobs(rec) if j["job_id"] == args.job_id), None)
    if job is None:
        raise Stop(f"unknown job {args.job_id}", f"{PROG} status --root {rec.root}")
    if job["imported"]:
        raise Stop(f"job {args.job_id} is already imported", f"{PROG} status --root {rec.root}")
    if _ended(job) or job["unfinished"]:
        raise Stop(f"job {args.job_id} is superseded or closed (or that is under way); it is never "
                   "imported", f"{PROG} status --root {rec.root}")
    extra = {}
    if job["kind"] == "reel_clips":
        extra = {"archive": Path(args.source), "archive_sha256": args.archive_sha256}
    try:
        arts = importer.import_job(rec, {k: job[k] for k in ("job_id", "kind", "notebook",
                                                             "inputs_zip", "manifest")},
                                   args.source, _ledger(rec, args), args.units, **extra)
    except importer.ImportHeld as e:
        raise Stop(f"Import held: {e}. Nothing was imported; the reservation stays open.",
                   "Re-download the complete output folder (or archive) of this exact job and rerun "
                   f"{PROG} import {args.job_id} ...; never rebuild or rerun the job to get past it.",
                   code=4)
    print(f"Imported {len(arts)} verified file(s) from {job['kind']} job {args.job_id}; "
          f"settled {args.units:g} CU.")


# ---------------------------------------------------------------- ElevenLabs takes
def _take_target(rec, plan, target: str):
    """(canonical target, [(key, scene)]): a film's plan scenes keyed by scene_id, or a reel's one
    take keyed by the reel target (its lines are the units)."""
    m = re.fullmatch(r"(film|reel)-0*([1-9][0-9]*)", target or "")
    if not m:
        raise Stop(f"unknown target {target!r}", "Pass film-NN (a planned film) or reel-N (a scripted reel)")
    n = int(m.group(2))
    if m.group(1) == "film":
        films = plan["plan"]["films"]
        if n > len(films):
            raise Stop(f"unknown target {target!r}: the plan has {len(films)} film(s)",
                       f"{PROG} status --root {rec.root}")
        return _film_target(n), [(sc["scene_id"], sc) for sc in films[n - 1]["scenes"]]
    t = f"reel-{n}"
    script = _reel_script(rec, n)
    if script is None:
        raise Stop(f"unknown target {target!r}: reel {n} has no script",
                   f"{PROG} reel {n} --root {rec.root} --script <file>")
    if _plan_event(rec, n)[1] is not None:  # R27: new narration would unbind planned shots
        raise Stop(f"{t} shots are already planned from narration "
                   f"{_plan_event(rec, n)[1]['narration_job_id']}; new narration would unbind them",
                   "Re-voicing a reel: supersede (never ran) or close (ran) every reel_clips batch, "
                   f"then {PROG} reel {n} --root {rec.root} --script <script>, import the new take, "
                   "a fresh --plan-shots and new batches (references/reel-recipe.md)")
    return t, [(t, _reel_scene(script, n))]


def _take_inputs(args, todo, lang) -> list:
    """Every scene's tagged script checked against the plan text, and its one take found."""
    scripts, audio = Path(args.scripts), Path(args.audio)
    for d, what in ((scripts, "--scripts"), (audio, "--audio")):
        if not d.is_dir():
            raise Stop(f"{what} {d} is not a folder", f"Pass {what} <folder>")
    rows = []
    for key, sc in todo:
        units = voice_units(sc, {"description": ""}, None, lang, CONTINUOUS)
        script = scripts / f"{key}.txt"
        if not script.is_file():
            raise Stop(f"no tagged script {script.name} for {key} in {scripts}",
                       "Write one tagged script per scene (references/earnalism-voice.md)")
        try:
            take.check_script(" ".join(u["text"] for u in units), script.read_text(encoding="utf-8"))
        except ValueError as e:
            raise Stop(f"script {script.name} rejected: {e}",
                       "Fix the tagged script so its words are exactly the book's, then regenerate "
                       "that scene's take from the fixed script")
        found = [audio / f"{key}{ext}" for ext in TAKE_AUDIO if (audio / f"{key}{ext}").is_file()]
        if len(found) != 1:
            raise Stop(f"{'no' if not found else 'more than one'} take for {key} in {audio} "
                       f"(expected {key}.mp3 or {key}.wav)",
                       "Download exactly one take per scene, named <scene_id>.mp3")
        rows.append({"key": key, "units": units, "script": script, "audio": found[0]})
    return rows


def cmd_import_take(args):
    """File an ElevenLabs narration job: one continuous take per scene, sliced per voice unit."""
    rec = _record(args.root)
    plan = _plan(rec)
    lang = plan["language"]
    if args.model not in TAKE_ENGINES.get(args.engine, ()):
        raise Stop(f"engine/model {args.engine}/{args.model} is not the approved narration engine",
                   "Use --engine elevenlabs --model eleven_v3 (references/earnalism-voice.md)")
    if not re.fullmatch(r"[A-Za-z0-9]{8,64}", args.voice_id or "") or not (args.voice_name or "").strip():
        raise Stop("--voice-id must be the ElevenLabs voice id and --voice-name its name",
                   "Pass the owner-picked voice (references/earnalism-voice.md)")
    try:
        credits = budget._check_units(args.credits)
    except ValueError:
        raise Stop(f"--credits must be the credits the generations used (>= 0), got {args.credits!r}",
                   "Read them from the ElevenLabs usage and rerun")
    target, todo = _take_target(rec, plan, args.target)
    waiting = [j["job_id"] for j in _jobs(rec) if j["kind"] == "narration" and j["target"] == target
               and (j["unfinished"] or (not j["imported"] and not _ended(j)))]
    if waiting:
        raise Stop(f"{target} has narration job(s) {', '.join(waiting)} built and not ended (or a "
                   "supersede/close under way); two narrations of one target would conflict",
                   f"{PROG} supersede <job_id> --root {rec.root} --reason \"<why it never ran>\" (or close "
                   "it with its actual units if it ran), then rerun import-take")
    rows = _take_inputs(args, todo, lang)
    job_id = args.job_id or f"narration-{args.engine}-{uuid.uuid4().hex[:8]}"
    if not SLUG.fullmatch(job_id) or any(j["job_id"] == job_id for j in _jobs(rec)):
        raise Stop(f"job id {job_id!r} is not new or not lowercase letters, digits and hyphens",
                   "Drop --job-id or pass a new one")
    wav_dest, job_dest = rec.root / "narration" / job_id, rec.root / "jobs" / job_id
    if wav_dest.exists() or job_dest.exists():
        raise Stop(f"{wav_dest} or {job_dest} already exists", "Drop --job-id or pass a new one")
    ledger = _ledger(rec, args)
    stage = Path(tempfile.mkdtemp(dir=rec.root, prefix=".take-"))
    try:
        (stage / "wav").mkdir()
        for sub in ("scripts", "takes"):
            (stage / "job" / sub).mkdir(parents=True)
        scenes_out = []
        for r in rows:
            try:
                info = take.slice_take(r["audio"], r["units"], stage / "wav")
            except (ValueError, subprocess.CalledProcessError) as e:
                raise Stop(f"take {r['audio'].name} not sliced: {e}",
                           "Check it is the complete downloaded take of that scene, then rerun")
            shutil.copy2(r["script"], stage / "job" / "scripts" / r["script"].name)
            shutil.copy2(r["audio"], stage / "job" / "takes" / r["audio"].name)
            scenes_out.append({"key": r["key"], "audio": f"jobs/{job_id}/takes/{r['audio'].name}",
                               "audio_sha256": sha256_file(r["audio"]),
                               "script": f"jobs/{job_id}/scripts/{r['script'].name}",
                               "script_sha256": sha256_file(r["script"]), **info})
        estimated = [k for sc in scenes_out for k in sc["estimated"]]
        files = {f"narration/{job_id}/{p.name}": sha256_file(p) for p in sorted((stage / "wav").iterdir())}
        for sc in scenes_out:
            for k in ("audio", "script"):
                path = stage / "job" / Path(sc[k]).relative_to(f"jobs/{job_id}")
                if sha256_file(path) != sc[f"{k}_sha256"]:
                    raise Stop(f"copy of {sc[k]} differs from its source", "Rerun import-take")
                files[sc[k]] = sc[f"{k}_sha256"]
        manifest = {"schema": TAKE_SCHEMA, "job_id": job_id, "target": target, "kind": "narration",
                    "engine": args.engine, "model": args.model, "voice_id": args.voice_id,
                    "voice_name": args.voice_name, "credits": credits, "voice_style": CONTINUOUS,
                    "method": "eav.take.slice_take", "estimated_boundaries": estimated,
                    "scenes": scenes_out, "files": files}
        _write_json(stage / "job" / "take-manifest.json", manifest)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    month = _month()
    edition_id = rec.data["source"].get("edition_id")
    here = Path(os.path.relpath(rec.root.resolve(), ledger.path.parent.resolve())).as_posix()
    try:  # 0 Colab CU: the ledger records the job; the credits stay on the job
        ledger.reserve(rec.data["title_slug"], month, 0, job_id, edition_id=edition_id,
                       root=here if edition_id else None)
    except (ValueError, budget.BudgetExceeded) as e:
        shutil.rmtree(stage, ignore_errors=True)
        raise Stop(f"take not filed: {e}", f"{PROG} status --root {rec.root}")
    snapshot = (list(rec.data["artifacts"]), list(rec.data["events"]))
    parents = {p: p.exists() for p in (wav_dest.parent, job_dest.parent)}
    try:  # all or nothing: files, record rows; the 0 CU entry is settled either way
        for p in parents:
            p.mkdir(parents=True, exist_ok=True)
        (stage / "wav").rename(wav_dest)
        (stage / "job").rename(job_dest)
        meta = {"job_id": job_id, "job_kind": "narration", "engine": args.engine, "model": args.model}
        rec.add_artifact(TAKE_JOB, job_dest / "take-manifest.json",
                         {**meta, "forecast_units": 0.0, "month": month,
                          "manifest": f"jobs/{job_id}/take-manifest.json"})
        rec.event("cli", "job_target", {"job_id": job_id, "target": target, "kind": "narration",
                                        "voice_style": dict(CONTINUOUS), "engine": args.engine,
                                        "model": args.model, "voice": args.voice_name,
                                        "voice_id": args.voice_id, "credits": credits,
                                        "estimated_boundaries": estimated})
        arts = [rec.add_artifact("narration", wav_dest / p.name, meta) for p in sorted(wav_dest.iterdir())]
        for sc in scenes_out:
            rec.add_artifact("take_audio", rec.root / sc["audio"], {**meta, "key": sc["key"]})
            rec.add_artifact("take_script", rec.root / sc["script"], {**meta, "key": sc["key"]})
        rec.event("import", "accepted", {"job_id": job_id, "kind": "narration", "actual_units": 0,
                                         "engine": args.engine, "credits": credits,
                                         "manifest_sha256": sha256_file(job_dest / "take-manifest.json"),
                                         "files": [a["path"] for a in arts],
                                         "estimated_boundaries": estimated})
    except BaseException:
        try:
            rec.rollback(snapshot)
        finally:
            for p in (wav_dest, job_dest, stage):
                shutil.rmtree(p, ignore_errors=True)
            for p, existed in parents.items():
                if not existed:
                    try:
                        p.rmdir()
                    except OSError:
                        pass
            ledger.settle(job_id, 0)
        raise
    ledger.settle(job_id, 0)
    shutil.rmtree(stage, ignore_errors=True)
    n_units = sum(len(r["units"]) for r in rows)
    print(f"Imported ElevenLabs narration job {job_id} for {target}: {len(rows)} take(s) "
          f"({args.model}, voice {args.voice_name}), {n_units} unit WAVs sliced sample-exactly, "
          f"{credits:g} credits recorded on the job, 0 Colab CU.")
    if estimated:
        print("Estimated joins (no usable silence; listen there): after " + ", ".join(estimated))


def _exchange_job(rec, job_id):
    """A pending narration/stills/music job the exchange may still serve."""
    job = next((j for j in _jobs(rec) if j["job_id"] == job_id), None)
    if job is None:
        raise Stop(f"unknown job {job_id}", f"{PROG} status --root {rec.root}")
    if job["kind"] not in exchange.KINDS:
        raise Stop(f"{job['kind']} jobs have their own Colab route (the Wan batch builder), not the "
                   "R2 exchange", f"{PROG} status --root {rec.root}")
    if job["imported"]:
        raise Stop(f"job {job_id} is already imported", f"{PROG} status --root {rec.root}")
    if _ended(job) or job["unfinished"]:
        raise Stop(f"job {job_id} is superseded or closed (or that is under way); the exchange never "
                   "serves it", f"{PROG} status --root {rec.root}")
    return job


def _r2_target(args):
    account = args.account or os.environ.get("EAV_R2_ACCOUNT", "")
    bucket = args.bucket or os.environ.get("EAV_R2_BUCKET", "")
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    try:
        exchange.endpoint(account, bucket)
    except exchange.ExchangeError as e:
        raise Stop(str(e), "Pass --account and --bucket (or set EAV_R2_ACCOUNT / EAV_R2_BUCKET)")
    if not token:
        raise Stop("CLOUDFLARE_API_TOKEN is not set",
                   "Export CLOUDFLARE_API_TOKEN (where the egress proxy injects the real token, any "
                   "placeholder value works); never paste a token into a file or the record")
    return account, bucket, token


def cmd_exchange_stage(args):
    """Upload inputs.zip and print the presign requests, or (--signed) write exchange.json."""
    rec = _record(args.root)
    job = _exchange_job(rec, args.job_id)
    title, job_id = rec.data["title_slug"], job["job_id"]
    zip_path = job["inputs_zip"]
    zip_sha, zip_bytes = sha256_file(zip_path), zip_path.stat().st_size
    if zip_sha != _json(job["manifest"]).get("inputs_sha256"):
        raise Stop(f"{zip_path} differs from its build manifest", "Report this; never rebuild to get past it")
    if not args.signed:
        account, bucket, token = _r2_target(args)
        k = exchange.key(title, job_id, exchange.INPUTS)
        try:
            exchange.cloudflare_upload(account, bucket, k, zip_path, exchange.INPUT_TYPE, token)
        except exchange.ExchangeError as e:
            raise Stop(f"exchange not staged: {e}", "Check the account, bucket and token, then rerun")
        rec.event("job", "exchange_uploaded", {"job_id": job_id, "key": k, "sha256": zip_sha,
                                               "bytes": zip_bytes})
        print(f"Uploaded {zip_path.name} ({zip_bytes} bytes, sha256 {zip_sha}) to R2 key {k}.")
        print("Sign these two requests with Maison where the R2 credentials live (Render one-off job), "
              "and save both printed JSON lines to one file outside the repository:")
        for req in exchange.presign_requests(title, job_id):
            print("  " + exchange.presign_command(req))
        return
    uploads = [e for e in _exchange_events(rec, job_id, "exchange_uploaded")
               if e["detail"].get("sha256") == zip_sha]
    if not uploads:
        raise Stop(f"inputs.zip of {job_id} has not been uploaded to the exchange",
                   f"{PROG} exchange-stage {job_id} --root {rec.root} --account <id> --bucket <name>")
    try:
        rows = exchange.parse_signed(Path(args.signed).read_text(encoding="utf-8"))
        checked = exchange.check_signed(rows, title, job_id)
    except exchange.ExchangeError as e:
        raise Stop(f"exchange not staged: {e}", "Re-run the two presign_colab_exchange commands and pass "
                   "their exact output with --signed")
    doc = exchange.exchange_document(title, job_id, checked, zip_sha, zip_bytes)
    path = job["notebook"].parent / exchange.FILENAME
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    # Keys and expiry only: the URLs are capabilities and never enter record.json.
    rec.event("job", "exchange_staged", {"job_id": job_id, "inputs_key": checked["inputs_key"],
                                         "outputs_key": checked["outputs_key"],
                                         "inputs_sha256": zip_sha, "expires_at": doc["expires_at"]})
    print(f"Wrote {path} (gitignored; URLs expire {doc['expires_at']}). Put it next to the notebook in "
          "the job's Drive folder; never commit or paste it.")


def cmd_exchange_collect(args):
    """Download outputs.tar, safe-extract it inside the title root, then the normal import."""
    rec = _record(args.root)
    job = _exchange_job(rec, args.job_id)
    staged = _exchange_events(rec, job["job_id"], "exchange_staged")
    if not staged:
        raise Stop(f"job {job['job_id']} has no staged R2 exchange",
                   f"{PROG} exchange-stage {job['job_id']} --root {rec.root} --account <id> --bucket <name>")
    account, bucket, token = _r2_target(args)
    k = staged[-1]["detail"]["outputs_key"]
    ledger = _ledger(rec, args)
    work = Path(tempfile.mkdtemp(dir=rec.root, prefix=".exchange-"))
    try:
        tar_path = work / exchange.OUTPUTS
        try:
            exchange.cloudflare_download(account, bucket, k, tar_path, token, exchange.MAX_OUTPUT_BYTES)
            tar_sha = sha256_file(tar_path)
            names = exchange.safe_extract(tar_path, work / "outputs")
        except exchange.ExchangeError as e:
            raise Stop(f"Import held: {e}. Nothing was imported; the reservation stays open.",
                       f"Check the notebook printed a 2xx upload, then rerun {PROG} exchange-collect "
                       f"{job['job_id']} ...; never rebuild or rerun the job to get past it.", code=4)
        try:
            arts = importer.import_job(rec, {kk: job[kk] for kk in ("job_id", "kind", "notebook",
                                                                    "inputs_zip", "manifest")},
                                       work / "outputs", ledger, args.units)
        except importer.ImportHeld as e:
            raise Stop(f"Import held: {e}. Nothing was imported; the reservation stays open.",
                       f"If the run ended INCOMPLETE or its outputs are wrong: {PROG} close "
                       f"{job['job_id']} --root {rec.root} --units <CU shown in Colab> --reason "
                       '"<what happened>"; never rebuild or rerun the job to get past it.', code=4)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    rec.event("job", "exchange_collected", {"job_id": job["job_id"], "outputs_key": k,
                                            "outputs_tar_sha256": tar_sha, "members": sorted(names)})
    print(f"Collected {k} (sha256 {tar_sha}) and imported {len(arts)} verified file(s) from "
          f"{job['kind']} job {job['job_id']}; settled {args.units:g} CU.")


_ENDINGS = {"supersede": ("superseding", "superseded"), "close": ("closing", "closed")}


def _end_job(args, how):
    """supersede (never ran: settle 0) or close (ran, not imported: settle the ACTUAL units).

    R23: the intent is recorded first as a pending event, then the ledger is settled, then the
    final event is written; rerunning the same command after any failure finishes it."""
    pending_result, final = _ENDINGS[how]
    rec = _record(args.root)
    job = next((j for j in _jobs(rec) if j["job_id"] == args.job_id), None)
    if job is None:
        raise Stop(f"unknown job {args.job_id}", f"{PROG} status --root {rec.root}")
    if job["imported"]:
        raise Stop(f"job {args.job_id} was imported; its outputs and spend stay on record",
                   f"{PROG} status --root {rec.root}")
    if _ended(job):
        raise Stop(f"job {args.job_id} is already {'superseded' if job['superseded'] else 'closed'}",
                   f"{PROG} status --root {rec.root}")
    events = rec.data["events"]
    pending = [e for e in events if e["stage"] == "job" and e["detail"].get("job_id") == args.job_id
               and e["result"] in ("superseding", "closing")]
    if pending and pending[-1]["result"] != pending_result:
        raise Stop(f"job {args.job_id} has an unfinished {pending[-1]['result'][:-3]}e; finish that one",
                   f"Rerun {PROG} {'close' if how == 'supersede' else 'supersede'} {args.job_id} "
                   f"--root {rec.root}")
    if not args.reason.strip():
        raise Stop("a reason is required", f"Pass --reason \"<{'why it never ran' if how == 'supersede' else 'what happened'}>\"")
    units = 0 if how == "supersede" else budget._check_units(args.units)
    ledger = _ledger(rec, args)
    entry = next((e for e in ledger._load() if e["job_id"] == args.job_id), None)
    if pending:
        recorded = pending[-1]["detail"]["units"]
        if recorded != units:
            raise Stop(f"the interrupted {how} of {args.job_id} recorded {recorded:g} CU; it is finished "
                       "with the recorded units, never re-decided",
                       f"Rerun with --units {recorded:g}" if how == "close" else "Rerun supersede")
    else:
        if entry is None or entry["state"] != "reserved":
            raise Stop(f"job {args.job_id} has no open reservation on the ledger "
                       f"({'missing' if entry is None else entry['state']}); nothing to settle",
                       f"{PROG} status --root {rec.root}")
        rec.event("job", pending_result, {"job_id": args.job_id, "units": units, "reason": args.reason})
    if entry is None:
        raise Stop(f"job {args.job_id} is missing from the ledger", f"{PROG} status --root {rec.root}")
    if entry["state"] == "reserved":
        ledger.settle(args.job_id, units)
    elif entry["units"] != units:
        raise Stop(f"ledger entry {args.job_id} was settled at {entry['units']:g} CU, not {units:g}",
                   "Report this; never edit the ledger by hand")
    reason = pending[-1]["detail"]["reason"] if pending else args.reason
    if how == "supersede":
        rec.event("job", final, {"job_id": args.job_id, "reason": reason})
        print(f"Superseded {job['kind']} job {args.job_id}: reservation of {entry['units']:.2f} CU "
              "released (settled at 0). Do not run its notebook.")
    else:
        rec.event("job", final, {"job_id": args.job_id, "units": units, "ran": True,
                                 "imported": False, "reason": reason})
        print(f"Closed {job['kind']} job {args.job_id}: it ran but is not imported; settled at the "
              f"actual {units:g} CU (reserved {entry['units']:.2f} CU). Its outputs are not on record.")


def cmd_supersede(args):
    """Release a never-run job: settle its reservation at 0 and record job/superseded (R19)."""
    _end_job(args, "supersede")


def cmd_close(args):
    """A job that ran but cannot be imported: settle its actual units, record job/closed (R23)."""
    _end_job(args, "close")


def cmd_film(args):
    rec = _record(args.root)
    plan = _plan(rec)
    t = _film_target(args.film)
    films = plan["plan"]["films"]
    if not 1 <= args.film <= len(films):
        raise Stop(f"film {args.film} is not in the plan", f"{PROG} status --root {rec.root}")
    narr = _latest_job(rec, "narration", t)
    stills = _latest_job(rec, "stills", t)
    if not narr or not stills:
        raise Stop(f"{t} needs imported narration and stills jobs", next_action(rec.root))
    lang = plan["language"]
    scs = films[args.film - 1]["scenes"]
    units = [u for sc in scs for u in voice_units(sc, {"description": ""}, None, lang, narr["style"])]
    out = rec.root / "film" / t
    out.mkdir(parents=True, exist_ok=True)
    timing, prov = _measured_track(units, rec.root / "narration" / narr["job_id"],
                                   out / "narration.wav", narr["job_id"])
    _write_json(out / "timing.json", {"units": timing, "provenance": prov})
    (out / f"{t}.srt").write_text(film.subtitles(timing, units), encoding="utf-8")
    if args.score:  # the bed never outlasts the narration; the END card follows it
        if not args.score_route:
            raise Stop("--score needs --score-route vcsl or ace-step:<music job id> for the record",
                       "Rerun with --score-route")
        score_info = {"route": _score_route(rec, args.score_route), "sha256": sha256_file(args.score)}
        _check_bed(Path(args.score), timing[-1]["end"], "narration")
        score = out / "score.wav"
        _ff("-i", args.score, "-t", f"{timing[-1]['end']:.3f}", "-ar", 48000, "-ac", 2, score)
    elif args.cues_job:
        cues = sorted(p for p in (rec.root / "music" / args.cues_job).iterdir()
                      if p.suffix.lower() in (".wav", ".flac", ".mp3"))
        if not cues:
            raise Stop(f"music job {args.cues_job} has no imported cues", next_action(rec.root))
        starts = [next(x["start"] for x in timing if x["unit_key"].startswith(sc["scene_id"] + "-"))
                  for sc in scs]
        k = min(len(cues), len(starts))
        bounds = [starts[(i * len(starts)) // k] for i in range(k)]
        bounds[0] = 0.0
        score = mix.arrange_cues(cues[:k], bounds, timing[-1]["end"], out / "score.wav")
        score_info = {"route": _score_route(rec, f"ace-step:{args.cues_job}"),
                      "sha256": sha256_file(score),
                      "cues_sha256": {c.name: sha256_file(c) for c in cues[:k]}}
    else:
        raise Stop("the film needs a score", "Pass --score <bed from earnalism-audiobook-score> "
                   "or --cues-job <imported ACE-Step music job>")
    try:
        m = mix.duck_and_master(out / "narration.wav", score, out / "mix.wav", FILM_LUFS)
    except ValueError as e:
        raise Stop(f"QC failure: {e}", "Re-balance the score bed and rerun film", code=5)
    stills_dir, stills_info = _film_stills(rec, t, out)
    info = film.assemble(plan["plan"], timing, stills_dir, out / "mix.wav",
                         Path(args.logo), Path(args.end_card), out / f"{t}.mp4",
                         film=args.film - 1, language=lang, style=narr["style"])
    for kind, p in (("timing", out / "timing.json"), ("subtitles", out / f"{t}.srt"),
                    ("mix", out / "mix.wav")):
        rec.add_artifact(kind, p, {"target": t})
    rec.add_artifact("film", out / f"{t}.mp4", {"target": t, "lufs": m["lufs"],
                                                "true_peak": m["true_peak"], "score": score_info,
                                                "narration_job_id": narr["job_id"],
                                                "stills": stills_info, **info})
    rec.event("film", "assembled", {"target": t, "duration": info["duration"]})
    print(f"Assembled {out / (t + '.mp4')}: {info['duration']:.1f} s, {m['lufs']:.1f} LUFS, "
          f"TP {m['true_peak']:.1f} dBTP. "
          "Maison video: eav bundle-film (full films go to Maison from private R2).")


_CANDIDATE = re.compile(r"(?P<key>.+)--c(?P<n>[1-9][0-9]*)$")


PICK_KINDS = ("stills", "retouch", "touchup", "edit")  # jobs whose <key>--cN candidates are picked
PATCH_KINDS = ("retouch", "touchup", "edit")  # always patches of picked candidates; never a base


def _stills_files(rec, job_id, kind="stills") -> dict:
    """{file stem: path} of one imported stills (or retouch) job's images."""
    folder = rec.root / kind / job_id
    return {p.stem: p for p in sorted(folder.iterdir()) if p.suffix.lower() in film.STILL_EXTS}


def _candidate_files(files: dict) -> dict:
    """{key: {candidate number: path}} for the <key>--cN images of a candidates job."""
    out = {}
    for stem, path in files.items():
        m = _CANDIDATE.fullmatch(stem)
        if m:
            out.setdefault(m["key"], {})[int(m["n"])] = path
    return out


def _latest_pick(rec, job_id):
    picks = _artifacts(rec, "stills_pick", job_id=job_id)
    return picks[-1]["meta"]["choices"] if picks else None


def cmd_pick(args):
    """Record the reviewer's choice among a stills, retouch, touchup or edit job's candidates (<key>--cN
    images; a retouch or touchup job's <key>--mask is for review only and never a candidate)."""
    rec = _record(args.root)
    job = next((j for j in _jobs(rec) if j["job_id"] == args.job), None)
    if job is None or job["kind"] not in PICK_KINDS or not job["imported"] or _ended(job):
        raise Stop(f"{args.job} is not an imported stills job",
                   f"{PROG} status --root {rec.root}; pick names an imported stills, retouch, "
                   "touchup or edit job with candidates")
    cands = _candidate_files(_stills_files(rec, args.job, job["kind"]))
    if not cands:
        raise Stop(f"stills job {args.job} has no candidate files (<key>--cN.png)",
                   "Build the redone shots with \"candidates\": N in the stills spec, import, review, pick")
    choices = _json(args.choices)
    if not isinstance(choices, dict):
        raise Stop("the choices file must be a JSON object {\"<key>\": <candidate number>}",
                   f"Fix {args.choices} and rerun pick")
    if not choices:
        raise Stop("the choices file has no choices", f"Name at least one key of {args.job}: "
                   f"{', '.join(sorted(cands))}")
    picked = {}
    for key, n in choices.items():
        if key not in cands:
            raise Stop(f"{key!r} has no candidates in {args.job}",
                       f"Use one of: {', '.join(sorted(cands))}")
        if isinstance(n, bool) or not isinstance(n, int) or n not in cands[key]:
            raise Stop(f"{key!r} candidate {n!r} is not one of {args.job}'s "
                       f"{', '.join(str(c) for c in sorted(cands[key]))}",
                       f"Fix {args.choices} and rerun pick")
        path = cands[key][n]
        picked[key] = {"candidate": n, "file": path.relative_to(rec.root).as_posix(),
                       "sha256": sha256_file(path)}
    version = len(_artifacts(rec, "stills_pick", job_id=args.job)) + 1
    path = _write_json(rec.root / "picks" / f"{args.job}.pick-{version}.json",
                       {"job_id": args.job, "choices": picked})
    rec.add_artifact("stills_pick", path, {"job_id": args.job, "choices": picked,
                                           "version": version})
    rec.event("pick", "recorded", {"job_id": args.job, "version": version,
                                   "choices": {k: v["candidate"] for k, v in picked.items()}})
    print(f"Picked {len(picked)} still(s) of {args.job}: "
          + ", ".join(f"{k} -> c{v['candidate']}" for k, v in sorted(picked.items()))
          + ". The film uses only these candidates; a later pick replaces this one.")


def _touchup_items(rec, t, spec) -> list:
    """Validate a touchup spec against the record: [(key, job, kind, name, path, sha256, ops)]."""
    sources = {j["job_id"]: j["kind"] for j in _jobs(rec) if j["kind"] in ("stills", "retouch")
               and j["target"] == t and j["imported"] and not _ended(j)}
    recorded = {a["path"]: a["sha256"] for a in rec.data["artifacts"]
                if a["kind"] in ("stills", "retouch") and a["meta"].get("job_id") in sources}
    film_keys = {colab_jobs.CANDIDATE_SUFFIX.sub("", Path(a["path"]).stem)
                 for a in rec.data["artifacts"] if a["kind"] == "stills"
                 and sources.get(a["meta"].get("job_id")) == "stills"}
    if not film_keys:
        raise Stop(f"{t} has no imported stills to touch up", next_action(rec.root))
    items = spec.get("items") if isinstance(spec, dict) else None
    if not isinstance(items, list) or not items:
        raise Stop("the touchup spec needs items: [{key, source: {job, file}, ops}]",
                   "Fix the spec per references/visual-style.md (Touch-up)")
    out, seen = [], set()
    for s in items:
        key = s.get("key") if isinstance(s, dict) else None
        if not isinstance(key, str) or colab_jobs.CANDIDATE_SUFFIX.search(key) or key.endswith("--mask"):
            raise Stop(f"touchup key {key!r} must be a still key (no --cN or --mask)", "Fix the spec")
        if key in seen:
            raise Stop(f"touchup key {key!r} appears twice; one item per still", "Fix the spec")
        seen.add(key)
        if key not in film_keys:
            raise Stop(f"touchup key {key!r} is not a still of {t}", "Fix the spec")
        src = s.get("source") or {}
        job, name = src.get("job"), src.get("file")
        if job not in sources:
            raise Stop(f"touchup {key!r}: source job {job!r} is not an imported stills or retouch job "
                       f"of {t}", f"{PROG} status --root {rec.root}")
        kind = sources[job]
        rel = f"{kind}/{job}/{name}"
        if not isinstance(name, str) or Path(name).name != name or rel not in recorded \
                or name.endswith("--mask.png"):
            raise Stop(f"touchup {key!r}: {name!r} is not a recorded still of {kind} job {job}",
                       "Name a recorded <key>.png or <key>--cN.png of that job")
        if colab_jobs.CANDIDATE_SUFFIX.sub("", Path(name).stem) != key:
            raise Stop(f"touchup {key!r}: source {name!r} is another still's file", "Fix the spec")
        path = rec.root / rel
        digest = sha256_file(path) if path.is_file() else None
        if digest != recorded[rel]:
            raise Stop(f"touchup {key!r}: {rel} sha256 {str(digest)[:12]} differs from the record's "
                       f"{recorded[rel][:12]}; the still changed since import", "Restore the imported file")
        out.append((key, job, kind, name, path, digest, s.get("ops")))
    return out


def cmd_touchup(args):
    """Repaint small defects in hand-placed boxes of imported stills (OpenCV, local, no model):
    one <key>--c1.png candidate and one <key>--mask.png (review only) per item, filed as an
    imported touchup job so pick and film treat it exactly like a retouch job."""
    import numpy as np
    from PIL import Image

    rec = _record(args.root)
    t = _film_target(args.film)
    spec = _json(args.spec)
    job_id = args.job_id
    if not SLUG.fullmatch(job_id or "") or any(j["job_id"] == job_id for j in _jobs(rec)):
        raise Stop(f"job id {job_id!r} is not new or not lowercase letters, digits and hyphens",
                   "Pass a new --job-id")
    items = _touchup_items(rec, t, spec)
    dest, job_dest = rec.root / "touchup" / job_id, rec.root / "jobs" / job_id
    if dest.exists() or job_dest.exists():
        raise Stop(f"{dest} or {job_dest} already exists", "Pass a new --job-id")
    try:
        version = touchup.opencv_version()
    except ValueError as e:
        raise Stop(str(e), "pip install -r skills/earnalism-audiovisual/software/requirements-touchup.txt")
    stage = Path(tempfile.mkdtemp(dir=rec.root, prefix=".touchup-"))
    try:
        (stage / "out").mkdir()
        (stage / "job").mkdir()
        rows = []
        for key, job, kind, name, path, digest, ops in items:
            with Image.open(path) as im:
                img = np.asarray(im.convert("RGB"))
            try:
                edited, mask = touchup.apply(img, ops)
            except ValueError as e:
                raise Stop(f"touchup {key!r}: {e}", "Fix the item's ops") from None
            Image.fromarray(edited, "RGB").save(stage / "out" / f"{key}--c1.png")
            Image.fromarray(mask, "L").save(stage / "out" / f"{key}--mask.png")
            rows.append({"key": key, "source_job": job, "source_kind": kind, "source_file": name,
                         "source": f"{kind}/{job}/{name}", "source_sha256": digest, "ops": ops,
                         "candidate": f"touchup/{job_id}/{key}--c1.png",
                         "candidate_sha256": sha256_file(stage / "out" / f"{key}--c1.png"),
                         "mask": f"touchup/{job_id}/{key}--mask.png",
                         "mask_sha256": sha256_file(stage / "out" / f"{key}--mask.png")})
        _write_json(stage / "job" / "touchup.json", spec)
        manifest = {"schema": TOUCHUP_SCHEMA, "job_id": job_id, "target": t, "kind": "touchup",
                    "engine": "opencv", "opencv": version, "method": "eav.touchup.apply",
                    "spec_sha256": sha256_file(stage / "job" / "touchup.json"), "items": rows}
        _write_json(stage / "job" / "touchup-manifest.json", manifest)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    snapshot = (list(rec.data["artifacts"]), list(rec.data["events"]))
    parents = {p: p.exists() for p in (dest.parent, job_dest.parent)}
    try:  # all or nothing: files and record rows
        for p in parents:
            p.mkdir(parents=True, exist_ok=True)
        (stage / "out").rename(dest)
        (stage / "job").rename(job_dest)
        meta = {"job_id": job_id, "job_kind": "touchup", "engine": "opencv", "opencv": version}
        rec.add_artifact(TOUCHUP_JOB, job_dest / "touchup-manifest.json",
                         {**meta, "forecast_units": 0.0,
                          "manifest": f"jobs/{job_id}/touchup-manifest.json"})
        rec.add_artifact("touchup_spec", job_dest / "touchup.json", meta)
        rec.event("cli", "job_target", {"job_id": job_id, "target": t, "kind": "touchup",
                                        "engine": "opencv"})
        arts = []
        for r in rows:
            src = {"key": r["key"], "source": r["source"], "source_sha256": r["source_sha256"]}
            arts.append(rec.add_artifact("touchup", rec.root / r["candidate"],
                                         {**meta, **src, "ops": r["ops"]}))
            arts.append(rec.add_artifact("touchup_mask", rec.root / r["mask"], {**meta, **src}))
        for a, want in zip(arts, [h for r in rows for h in (r["candidate_sha256"], r["mask_sha256"])]):
            if a["sha256"] != want:
                raise Stop(f"{a['path']} changed while filing", "Rerun touchup with a new --job-id")
        rec.event("import", "accepted", {"job_id": job_id, "kind": "touchup", "actual_units": 0,
                                         "engine": "opencv", "opencv": version,
                                         "manifest_sha256": sha256_file(job_dest / "touchup-manifest.json"),
                                         "files": [a["path"] for a in arts]})
    except BaseException:
        try:
            rec.rollback(snapshot)
        finally:
            for p in (dest, job_dest, stage):
                shutil.rmtree(p, ignore_errors=True)
            for p, existed in parents.items():
                if not existed:
                    try:
                        p.rmdir()
                    except OSError:
                        pass
        raise
    shutil.rmtree(stage, ignore_errors=True)
    print(f"Touched up {len(rows)} still(s) of {t} as job {job_id} (OpenCV {version}, 0 CU): "
          + ", ".join(r["key"] for r in rows) + ". Open every <key>--c1.png and <key>--mask.png at "
          f"full size, then {PROG} pick --root {rec.root} --job {job_id} --choices <json>.")


def _film_stills(rec, t, out):
    """The film's stills: the latest complete stills job, with any later imported job whose
    keys are all already in it applied as a patch (it replaces just those stills, e.g. one
    character regenerated). A candidates job (<key>--cN files) is never a base: it patches only
    its picked candidates, renamed to <key>, and contributes nothing until picked. A retouch,
    touchup or edit job is always such a patch (its <key>--mask files never enter the film). A held
    key whose film still is a picked edit is released: the edit is that shot's approved still.
    Linked into film/<t>/stills so the film reads one folder."""
    jobs = []
    for j in _jobs(rec):
        if j["kind"] in PICK_KINDS and j["target"] == t and j["imported"] and not _ended(j):
            files = _stills_files(rec, j["job_id"], j["kind"])
            cands = _candidate_files(files)
            if j["kind"] in PATCH_KINDS:
                files, cands = {}, cands or {"": {}}  # picks only; never a base or a whole job
            jobs.append((j, files, cands))
    base = None
    for i, (job, keys, cands) in enumerate(jobs):
        if cands:
            continue
        if base is None or not set(keys) <= set(jobs[base][1]):
            base = i
    if base is None:
        raise Stop(f"{t} has no ordinary stills job to use as a base (candidates jobs only patch)",
                   next_action(rec.root))
    files = dict(jobs[base][1])
    origin = {}  # key -> kind of the job its film still now comes from (patches only)
    patches, unpicked = [], []
    for job, keys, cands in jobs[base + 1:]:
        if not cands:
            files.update(keys)
            origin.update({k: job["kind"] for k in keys})
            patches.append(job["job_id"])
            continue
        choices = _latest_pick(rec, job["job_id"])
        if not choices:
            unpicked.append(job["job_id"])
            continue
        for key, c in choices.items():
            src = rec.root / c["file"]
            if sha256_file(src) != c["sha256"]:
                raise Stop(f"picked still {c['file']} changed since it was picked",
                           f"{PROG} pick --root {rec.root} --job {job['job_id']} --choices <json>")
            files[key] = src
            origin[key] = job["kind"]
        patches.append(job["job_id"])
    held, substitutes = _held_keys(rec, t), {}
    released = [k for k in held if origin.get(k) == "edit"]
    held = [k for k in held if k not in released]
    if held:
        files, substitutes = _apply_hold(files, held)
    merged = out / "stills"
    if merged.exists():
        shutil.rmtree(merged)
    merged.mkdir()
    for key, src in files.items():
        dst = merged / (key + src.suffix)  # a picked <key>--cN file lands as <key>
        try:
            os.link(src, dst)  # same disk: no copy of the image bytes
        except OSError:
            shutil.copy2(src, dst)
    meta = {"base": jobs[base][0]["job_id"], "patches": patches}
    if unpicked:
        meta["unpicked"] = unpicked
    if held:
        meta["held"] = sorted(held, key=_shot_order)
        meta["substitutes"] = substitutes
    if released:
        meta["released_by_edit"] = sorted(released, key=_shot_order)
    return merged, meta


def _shot_order(key):
    """Sort key of a still key f01s007-4: scene prefix, then the shot number."""
    scene, _, shot = key.rpartition("-")
    return (scene, int(shot) if shot.isdigit() else 0, key)


def _held_keys(rec, t) -> list:
    holds = _artifacts(rec, "stills_hold", target=t)
    return list(holds[-1]["meta"]["keys"]) if holds else []


def _apply_hold(files, held):
    """Held keys never use their own file: each takes the file of the nearest non-held key of its
    scene (the previous key in order, else the next). A scene with every shot held takes the last
    approved key of the previous scene, else the first approved key of the next one. Returns
    (files, {held key: {"use": substitute, "cross_scene": bool}})."""
    files = {k: v for k, v in files.items() if k not in held}
    universe = sorted(set(files) | set(held), key=_shot_order)
    approved = [k for k in universe if k not in held]
    if not approved:
        raise Stop("every shot of the film is held: no approved still to show",
                   f"Approve stills (pick) or release holds: {PROG} hold --root <dir> --film <n> --clear")
    subs = {}
    for key in sorted(held, key=_shot_order):
        scene = key.rpartition("-")[0]
        same = [k for k in universe if k.rpartition("-")[0] == scene]
        i = same.index(key)
        pick = next((k for k in reversed(same[:i]) if k not in held), None) \
            or next((k for k in same[i + 1:] if k not in held), None)
        cross = pick is None
        if cross:
            before = [k for k in approved if _shot_order(k)[0] < scene]
            pick = before[-1] if before else next(k for k in approved if _shot_order(k)[0] > scene)
        subs[key] = {"use": pick, "cross_scene": cross}
    out = dict(files)
    for key, sub in subs.items():
        out[key] = files[sub["use"]]
    return out, subs


def cmd_hold(args):
    """Record which shots of a film have no approved still: the film shows the nearest approved
    still of the same scene for them (latest call wins; --clear removes the holds)."""
    rec = _record(args.root)
    t = _film_target(args.film)
    if args.clear == bool(args.keys):
        raise Stop("hold needs exactly one of --keys or --clear",
                   f"{PROG} hold --root {rec.root} --film {args.film} --keys k1,k2 | --clear")
    keys = [] if args.clear else sorted({k.strip() for k in args.keys.split(",") if k.strip()},
                                        key=_shot_order)
    bad = [k for k in keys if not re.fullmatch(r".+-[0-9]+", k)]
    if bad:
        raise Stop(f"not a still key: {', '.join(bad)}", "Keys look like f01s007-4")
    version = len(_artifacts(rec, "stills_hold", target=t)) + 1
    path = _write_json(rec.root / "holds" / f"{t}.hold-{version}.json", {"target": t, "keys": keys})
    rec.add_artifact("stills_hold", path, {"target": t, "keys": keys, "version": version})
    rec.event("hold", "recorded", {"target": t, "version": version, "keys": keys})
    print(f"{len(keys)} shot(s) of {t} held" + (": " + ", ".join(keys) if keys else " (cleared)")
          + ". The film shows the nearest approved still of the same scene for them.")


def _line_ends(script, units, timing) -> list:
    """Measured end time of each reel line (a line may hold several sentences/units)."""
    lang = script["language"]
    ends, k = [], 0
    for line in reel.spoken(script):
        k += len(sentences(line, lang))
        ends.append(timing[k - 1]["end"])
    if k != len(units):
        raise Stop("reel narration units do not match the script lines", "Report this as a bug")
    return ends


def _reel_track(rec, n, script, narr, folder):
    units = voice_units(_reel_scene(script, n), {"description": ""}, None, script["language"],
                        narr.get("style"))
    timing, prov = _measured_track(units, rec.root / "narration" / narr["job_id"],
                                   folder / "narration.wav", narr["job_id"])
    return units, timing, prov


def _reel_set_script(rec, args, n, t, folder):
    script = _json(args.script)
    try:
        reel.validate_script(script)
    except ValueError as e:
        raise Stop(f"reel script rejected: {e}", "Fix the script per references/reel-recipe.md")
    built = _reel_narration(rec, n, imported=False)
    planned, detail = _plan_event(rec, n)
    if detail is not None:  # R27: re-voicing retires the plan only once none of its batches is active
        live = [j["job_id"] for j in _jobs(rec) if j["kind"] == "reel_clips" and j["target"] == t
                and j["order"] > planned and not _ended(j)]
        if live:
            raise Stop(f"{t} has active reel_clips batch(es) {', '.join(live)} of its shot plan",
                       "Re-voicing: supersede (never ran) or close (ran) each of them first; imported "
                       "clips cannot be retired, so re-voice as a new reel number instead")
    elif built and built["job_id"] not in _misfits(rec):
        raise Stop(f"{t} narration was already built from its script", f"{PROG} status --root {rec.root}")
    _write_json(folder / "script.json", script)
    (folder / "caption.txt").write_text(reel.caption(script, args.hashtags or []) + "\n", encoding="utf-8")
    for kind, name in (("reel_script", "script.json"), ("caption", "caption.txt")):
        rec.add_artifact(kind, folder / name, {"target": t})
    rec.event("reel", "scripted", {"target": t, "shots": "planned from the measured narration"})
    print(f"Reel {n}: script and caption written. Shots are planned after its narration is imported "
          f"and measured ({PROG} reel {n} --plan-shots).")


def _reel_plan_shots(rec, n, t, folder):
    script = _reel_script(rec, n)
    narr = _reel_narration(rec, n)
    if script is None or narr is None:
        raise Stop(f"{t} needs a script and its imported narration before shots are planned",
                   next_action(rec.root))
    if _planned_shots(rec, n)[0] is not None:
        raise Stop(f"{t} shots are already planned; re-planning would desynchronise its stills and clips",
                   f"{PROG} status --root {rec.root}")
    units, timing, prov = _reel_track(rec, n, script, narr, folder)
    seconds = timing[-1]["end"]
    try:
        reel.validate_script(script, narration_seconds=seconds)
    except ValueError as e:
        rec.event("reel", "narration_misfit", {"target": t, "narration_job_id": narr["job_id"],
                                               "narration_seconds": seconds})
        raise Stop(f"QC failure: {e}", next_action(rec.root), code=5)
    clip = colab_jobs.reel_clip_seconds()
    shots = reel.shot_list(script, clip, seconds, _line_ends(script, units, timing))
    _write_json(folder / "shots.json", shots)
    rec.add_artifact("shot_list", folder / "shots.json", {"target": t, "narration_job_id": narr["job_id"]})
    rec.event("reel", "shots_planned", {"target": t, "shots": len(shots), "clip_seconds": clip,
                                        "narration_seconds": seconds, "narration_job_id": narr["job_id"],
                                        "shots_sha256": sha256_file(folder / "shots.json")})
    print(f"Reel {n}: measured narration {seconds:.2f} s -> {len(shots)} shots of {clip:.4f} s "
          f"(last {shots[-1]['seconds']:.2f} s), in batches of at most {colab_jobs.MAX_CLIPS_PER_BATCH}.")


def cmd_reel(args):
    rec = _record(args.root)
    n, t = args.n, f"reel-{args.n}"
    folder = rec.root / "reels" / t
    if args.script:
        return _reel_set_script(rec, args, n, t, folder)
    if args.plan_shots:
        return _reel_plan_shots(rec, n, t, folder)
    script = _reel_script(rec, n)
    if script is None or _plan_event(rec, n)[1] is None:
        raise Stop(f"{t} needs a script, its imported narration and a shot plan", next_action(rec.root))
    shots, planned, narr_id = _bound_plan(rec, n)  # R27: exactly the planned narration
    narr = next(j for j in _jobs(rec) if j["job_id"] == narr_id)
    by_scene, jobs = {}, []
    for j in _clip_jobs(rec, n, planned, imported=True):
        jobs.append(j["job_id"])
        for a in _artifacts(rec, "reel_clip", job_id=j["job_id"]):
            if a["meta"]["scene"] in by_scene:
                raise Stop(f"shot {a['meta']['scene']} has clips in two batches", "Report this as a bug")
            by_scene[a["meta"]["scene"]] = rec.root / a["path"]
    missing = [sh["id"] for sh in shots if sh["id"] not in by_scene]
    if missing:
        raise Stop(f"{t}: no imported clip yet for shot(s) {', '.join(missing)}", next_action(rec.root))
    clips = [by_scene[sh["id"]] for sh in shots]
    _, _, prov = _reel_track(rec, n, script, narr, folder)
    durs = [film._duration(c) for c in clips]
    last = min(durs[-1], shots[-1]["seconds"])
    total = sum(durs[:-1]) + last
    spoken = film._duration(folder / "narration.wav")
    if spoken > total + reel.AUDIO_TOLERANCE_S:
        raise Stop(f"QC failure: narration {spoken:.2f} s is longer than the clips {total:.2f} s; "
                   "narration is never trimmed", "Report this as a bug: shots are planned from it", code=5)
    _ff("-i", folder / "narration.wav", "-af", f"apad=whole_dur={total:.3f}", "-ar", 48000,
        folder / "narration-padded.wav")
    audio, score_info = folder / "narration-padded.wav", None
    if args.score:
        if not args.score_route:
            raise Stop("--score needs --score-route vcsl or ace-step:<music job id> for the record",
                       "Rerun with --score-route")
        score_info = {"route": _score_route(rec, args.score_route), "sha256": sha256_file(args.score)}
        _check_bed(Path(args.score), total, "reel")
        _ff("-i", args.score, "-t", f"{total:.3f}", "-ar", 48000, folder / "score-cut.wav")
        try:
            mix.duck_and_master(audio, folder / "score-cut.wav", folder / "mix.wav", REEL_LUFS)
        except ValueError as e:
            raise Stop(f"QC failure: {e}", "Re-balance the reel score and rerun", code=5)
        audio = folder / "mix.wav"
    try:
        info = reel.assemble(clips, audio, folder / f"{t}.mp4", last_seconds=last)
    except ValueError as e:
        raise Stop(f"QC failure: {e}", "Fix the failing input and rerun", code=5)
    rec.add_artifact("narration_provenance", _write_json(folder / "narration-provenance.json", prov),
                     {"target": t, "narration_job_id": narr["job_id"]})
    rec.add_artifact("reel", folder / f"{t}.mp4", {"target": t, "score": score_info,
                                                   "narration_job_id": narr["job_id"],
                                                   "clip_jobs": jobs, **info})
    rec.event("reel", "assembled", {"target": t, "seconds": info["seconds"]})
    print(f"Assembled {folder / (t + '.mp4')}: {info['seconds']:.1f} s from {len(clips)} clips in "
          f"{len(jobs)} batch(es), {info['lufs']:.1f} LUFS.")


def cmd_qc(args):
    rec = _record(args.root)
    latest = {}
    for a in rec.data["artifacts"]:
        if a["kind"] in ("film", "reel"):
            latest[a["meta"]["target"]] = a
    if not latest:
        raise Stop("nothing assembled yet", next_action(rec.root))
    out = rec.root / "qc"
    out.mkdir(exist_ok=True)
    report = {"advisory_only": ["contact sheets need a human/visual check",
                                "ASR comparison not run here"],
              "listening": "unassessed until the owner reviews the package", "items": {}}
    failed = []
    for target, a in sorted(latest.items()):
        video = rec.root / a["path"]
        m = mix.measure(video)
        sheet = qc.contact_sheet(video, out / f"{target}-contact.jpg")
        lufs = REEL_LUFS if a["kind"] == "reel" else FILM_LUFS
        checks = {"loudness": abs(m["lufs"] - lufs) <= LUFS_TOL, "true_peak": m["true_peak"] <= TP_MAX}
        item = {"sha256": sha256_file(video), **m, "contact_sheet": sheet.name}
        if a["kind"] == "reel":
            item["loop_ssim"] = qc.loop_score(video)
            checks["loop_close"] = item["loop_ssim"] >= LOOP_MIN
            # R26: the hook is spoken from 0.0-0.2 s (Parler's leading silence can delay it)
            narration = rec.root / "reels" / target / "narration.wav"
            onset = qc.speech_onset(narration) if narration.is_file() else None
            item["hook_onset_s"] = onset
            checks["hook_onset"] = onset is not None and 0.0 <= onset <= HOOK_ONSET_MAX_S
            checks["size_1080x1920"] = (a["meta"].get("width"), a["meta"].get("height")) == (1080, 1920)
        item["checks"] = {k: "pass" if v else "fail" for k, v in checks.items()}
        failed += [f"{target}:{k}" for k, v in checks.items() if not v]
        report["items"][target] = item
    report["result"] = "fail" if failed else "pass"
    rec.add_artifact("qc_report", _write_json(out / "report.json", report), {"failed": failed})
    rec.event("qc", report["result"], {"failed": failed})
    for target, item in report["items"].items():
        print(f"{target}: " + ", ".join(f"{k} {v}" for k, v in item["checks"].items())
              + f"; contact sheet qc/{item['contact_sheet']} (look at it)")
    if failed:
        raise Stop("QC failure: " + ", ".join(failed), next_action(rec.root), code=5)


def _qc_passed(rec) -> bool:
    """The latest qc came after the last film/reel assembly and passed (R26)."""
    events = rec.data["events"]
    last_media = max((i for i, e in enumerate(events)
                      if e["stage"] in ("film", "reel") and e["result"] == "assembled"), default=-1)
    qcs = [(i, e) for i, e in enumerate(events) if e["stage"] == "qc"]
    return bool(qcs) and qcs[-1][0] > last_media and qcs[-1][1]["result"] == "pass"


def cmd_bundle_audio(args):
    rec = _record(args.root)
    plan, src = _plan(rec), _json(rec.root / "source.json")
    lang = plan["language"]
    bundle = Path(args.out)
    if bundle.exists() and any(bundle.iterdir()):
        raise Stop(f"{bundle} is not empty", "Pass a new --out directory")
    scene_film = {}
    for i, f in enumerate(plan["plan"]["films"], 1):
        for sc in f["scenes"]:
            scene_film[sc["scene_id"]] = (i, sc)
    films = [_film_target(i) for i in range(1, len(plan["plan"]["films"]) + 1)]
    if not all(_artifacts(rec, "film", target=t) for t in films) or not _qc_passed(rec):
        raise Stop("bundle-audio needs every film assembled and a passing qc after the last assembly",
                   f"{PROG} qc --root {rec.root}, fix any failure, then the owner's review")
    if args.dry and (args.score_dir or args.score_route):
        raise Stop("--dry excludes --score-dir and --score-route", "Choose one")
    if not args.dry:
        if not args.score_dir:
            raise Stop("Maison audio carries narration with its background score: pass --score-dir "
                       "<dir> holding <unit_id>.wav per chapter (from `earnalism-audiobook-score`), or "
                       "--dry for narration only (recorded in the evidence draft)",
                       "Prepare one score bed per chapter, then rerun bundle-audio --score-dir <dir>")
        if not args.score_route:
            raise Stop("the evidence record must name the score's route and licence: pass --score-route "
                       "vcsl (CC0 VCSL editorial score) or ace-step:<imported music job id> (Apache-2.0)",
                       "Rerun bundle-audio with --score-route")
        args.score_route = _score_route(rec, args.score_route)
        missing = [u["unit_id"] for u in src["units"]
                   if not (Path(args.score_dir) / f"{u['unit_id']}.wav").is_file()]
        if missing:
            raise Stop(f"no chapter score for unit(s) {', '.join(missing)} in {args.score_dir}",
                       "Add <unit_id>.wav for every chapter, or rerun with --dry")
    created = not bundle.exists()
    try:
        return _write_audio_bundle(rec, plan, src, lang, bundle, scene_film, args)
    except BaseException:  # the bundle was empty: leave nothing half-written behind
        if created:
            shutil.rmtree(bundle, ignore_errors=True)
        elif bundle.is_dir():
            for child in bundle.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        raise


def _narration_generators(rec, plan, job_ids) -> list:
    """The evidence draft's narration generators: Parler jobs as one row, each ElevenLabs take
    job as its own row (model, voice id and credits from the job)."""
    jobs = [j for j in _jobs(rec) if j["job_id"] in job_ids]
    rows, parler = [], sorted(j["job_id"] for j in jobs if j["engine"] == "parler")
    if parler:
        voices = sorted({j["voice"] or plan["voice"]["preset_key"] for j in jobs if j["job_id"] in parler})
        rows.append({"model": colab_jobs.NARRATION_REPO, "revision": colab_jobs.NARRATION_REVISION,
                     "licence": "Apache-2.0", "job_ids": parler,
                     "voice": voices[0] if len(voices) == 1 else voices})
    details = {e["detail"]["job_id"]: e["detail"] for e in rec.data["events"]
               if e["stage"] == "cli" and e["result"] == "job_target"}
    for j in sorted((j for j in jobs if j["engine"] != "parler"), key=lambda j: j["job_id"]):
        d = details[j["job_id"]]
        rows.append({"model": f"{d['engine']}/{d['model']}", "engine": d["engine"], "job_ids": [j["job_id"]],
                     "licence": "ElevenLabs paid-plan commercial licence (owner decision 2026-11-24)",
                     "voice": d["voice"], "voice_id": d["voice_id"], "credits": d["credits"]})
    return rows


def _write_audio_bundle(rec, plan, src, lang, bundle, scene_film, args):
    rows, prov_units, job_ids = [], {}, set()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bundle.mkdir(parents=True, exist_ok=True)
        for n, unit in enumerate(src["units"], 1):
            anchors = {p["anchor_id"] for p in unit["paragraphs"]}
            mine = [(fi, sc) for fi, sc in scene_film.values() if set(sc["anchor_ids"]) <= anchors]
            films_used = {fi for fi, _ in mine}
            if not mine or len(films_used) != 1:
                raise Stop(f"unit {unit['unit_id']} has no single planned film", "Re-plan the title")
            job = _latest_job(rec, "narration", _film_target(films_used.pop()))
            if not job:
                raise Stop(f"unit {unit['unit_id']}: narration not imported yet", next_action(rec.root))
            job_ids.add(job["job_id"])
            units, tags = [], []
            for _, sc in mine:
                vus = voice_units(sc, {"description": ""}, None, lang, job["style"])
                tg = unit_anchors(sc, lang, job["style"])
                if len(tg) != len(vus):
                    raise Stop(f"scene {sc['scene_id']}: unit/anchor mismatch", "Report as a bug")
                units += vus
                tags += tg
            spoken = {}
            for u, a in zip(units, tags):
                spoken.setdefault(a, []).append(u["text"])
            for p in unit["paragraphs"]:
                if " ".join(spoken.get(p["anchor_id"], [])) != " ".join(p["text"].split()):
                    raise Stop(f"paragraph {p['anchor_id']}: spoken units do not reproduce its text "
                               "exactly", "Refuse; never publish narration that differs from the book")
            chapter = td / f"unit-{n:03d}.wav"
            timing, prov = _measured_track(units, rec.root / "narration" / job["job_id"], chapter,
                                           job["job_id"])
            master, score_sha = td / f"unit-{n:03d}-master.wav", None
            try:
                if args.dry:  # narration only, same -16 LUFS / -1 dBTP gate
                    mix.master(chapter, master, FILM_LUFS)
                    mastered = "eav.mix.master"
                else:  # R10: narration + best-fit score, ducked, -16 LUFS
                    bed = Path(args.score_dir) / f"{unit['unit_id']}.wav"
                    _check_bed(bed, timing[-1]["end"], f"chapter {unit['unit_id']} narration")
                    score_sha = sha256_file(bed)
                    cut = td / f"unit-{n:03d}-score.wav"
                    _ff("-i", bed, "-t", f"{timing[-1]['end']:.3f}", "-ar", 48000, "-ac", 2, cut)
                    mix.duck_and_master(chapter, cut, master, FILM_LUFS)
                    mastered = "eav.mix.duck_and_master"
            except ValueError as e:
                raise Stop(f"QC failure: {unit['unit_id']}: {e}",
                           "Re-balance that chapter (score bed or narration level) and rerun", code=5)
            mp3 = bundle / f"unit-{n:03d}.mp3"  # stereo keeps the master's measured loudness
            _ff("-i", master, "-ar", 48000, "-ac", 2, "-c:a", "libmp3lame", "-b:a", "96k", mp3)
            dur_ms = round(film._duration(mp3) * 1000)
            segs = []
            for p in unit["paragraphs"]:
                times = [t for t, a in zip(timing, tags) if a == p["anchor_id"]]
                start, end = round(times[0]["start"] * 1000), round(times[-1]["end"] * 1000)
                if end > dur_ms:
                    if end - dur_ms > MP3_END_SLACK_MS:
                        raise Stop(f"{mp3.name}: measured narration ends after the MP3", "Report as a bug")
                    end = dur_ms
                segs.append({"anchor_id": p["anchor_id"], "start_offset_chars": 0,
                             "end_offset_chars": len(p["text"]), "start_ms": start, "end_ms": end})
            rows.append({"unit_id": unit["unit_id"], "mp3": mp3.name, "segments": segs})
            prov_units[unit["unit_id"]] = {
                "narration_job_id": job["job_id"], "wav_sha256": prov["wav_sha256"],
                "chapter_wav_sha256": prov["track_sha256"], "mastered_with": mastered,
                "score_sha256": score_sha,
                "mp3_sha256": sha256_file(mp3), "mp3_duration_ms": dur_ms,
                "encoder": "ffmpeg libmp3lame 96 kbps CBR stereo 48 kHz"}
    ids = sorted(job_ids)
    provenance = {"method": "eav.film.narration_track", "measured_with": "ffprobe",
                  "narration_job_id": ids[0] if len(ids) == 1 else ids, "units": prov_units}
    timing_path = _write_json(bundle / "timing.json", {"units": rows, "provenance": provenance})
    audio = [v["mp3_sha256"] for v in prov_units.values()]
    draft = _write_json(rec.root / "maison" / EVIDENCE_DRAFT, {
        "schema": EVIDENCE_SCHEMA,
        "status": "DRAFT_NOT_APPROVED: complete territories, term per territory, text-source licence "
                  "and cover provenance, then obtain the owner's approval; this CLI never marks clearance",
        "edition_slug": rec.data["title_slug"], "edition_id": rec.data["source"].get("edition_id"),
        "source_revision_id": rec.data["source"]["revision_id"],
        "source_content_sha256": rec.data["source"]["content_sha256"],
        "territories": [], "territories_note": "must equal the active whitelist "
        "(contracts/publication-policy.json / MAISON_PUBLICATION_TERRITORIES)",
        "formats": ["reader", "audio"], "audio_sha256": audio,
        "timing_json_sha256": sha256_file(timing_path), "term_per_territory": {},
        "text_source_licence": None, "cover_provenance": None,
        "generators": _narration_generators(rec, plan, job_ids),
        "dry_narration": bool(args.dry),
        "music": None if args.dry else {
            **_music_licence(args.score_route),
            "mix": "per-chapter score bed, ducked under speech (eav.mix.duck_and_master, -16 LUFS)",
            "score_sha256": {u: v["score_sha256"] for u, v in prov_units.items()}},
        "owner_must_complete": ["territories", "term_per_territory", "text_source_licence",
                                "cover_provenance", "status", "owner_approval"],
        "owner_approval": None,
        "owner_approval_required": {"by": "<who approved>", "at": "<ISO 8601 time>"}})
    rec.add_artifact("evidence_draft", draft, {"bundle": str(bundle), "audio_sha256": audio})
    rec.event("bundle_audio", "drafted", {"bundle": str(bundle), "audio_sha256": audio,
                                          "timing_json_sha256": sha256_file(timing_path)})
    print(f"Wrote Maison audio bundle {bundle} ({len(rows)} chapter MP3s, measured timing.json with "
          f"provenance) and evidence DRAFT {draft}.")
    print(f"Maison audio: complete and owner-approve the draft, save it under docs/evidence/, then on the "
          f"server: python manage.py attach_audiovisual_audio stage {rec.data['title_slug']} --publisher "
          f"<public_id> --bundle {bundle} --evidence docs/evidence/<file>.json; browser-test the staged "
          "revision, then attach_audiovisual_audio publish --browser-report <report.json>.")


def cmd_status(args):
    root = Path(args.root)
    if (root / "record.json").is_file():
        rec = Record.load(root)
        s, title, month = rec.data["source"], rec.data["title_slug"], _month()
        ledger = _ledger(rec, args)
        print(f"{title}: revision {s['revision_id']} ({s['language']}), "
              f"{_title_spent(ledger, rec):.2f} CU spent/reserved for this title (lifetime cap "
              f"{budget.title_cap(ledger.path, title):g}), {ledger.spent(None, month):.2f} CU this month (all titles), "
              f"{_remaining(ledger, rec, month):.2f} CU remaining ({month}).")
        for j in _jobs(rec):
            closed = next((e["detail"]["units"] for e in rec.data["events"] if e["result"] == "closed"
                           and e["detail"].get("job_id") == j["job_id"]), None)
            state = ("imported" if j["imported"] else "superseded" if j["superseded"]
                     else f"closed (ran, not imported; {closed:.2f} CU settled)" if j["closed"]
                     else "supersede/close unfinished: rerun it" if j["unfinished"]
                     else "waiting for Colab")
            print(f"  {j['job_id']} {j['kind']} {j['target']}: {state} "
                  f"(forecast {j['forecast_units']:.2f} CU)")


def cmd_bundle_film(args):
    """Bundle one assembled, qc-passed film for Maison's private R2 delivery."""
    rec = _record(args.root)
    try:
        uuid.UUID(args.unit_id)
    except ValueError:
        raise Stop(f"--unit-id {args.unit_id!r} is not a UUID", "Pass the Maison unit's UUID")
    t = args.film
    films = _artifacts(rec, "film", target=t)
    subs = _artifacts(rec, "subtitles", target=t)
    if not films or not subs:
        raise Stop(f"{t} has no assembled film and subtitles in the record",
                   f"{PROG} film --root {rec.root}")
    mp4, srt = rec.root / films[-1]["path"], rec.root / subs[-1]["path"]
    reports = _artifacts(rec, "qc_report")
    item = None
    if _qc_passed(rec) and reports:
        report = _json(rec.root / reports[-1]["path"])
        item = report.get("items", {}).get(t)
    if (not item or report.get("result") != "pass"
            or any(v != "pass" for v in item.get("checks", {}).values())):
        raise Stop(f"bundle-film needs a passing film qc for {t} after its last assembly",
                   f"{PROG} qc --root {rec.root}")
    if item.get("sha256") != sha256_file(mp4) or films[-1]["sha256"] != item["sha256"]:
        raise Stop(f"the qc sha256 for {t} does not match the current film MP4",
                   f"{PROG} qc --root {rec.root}")
    bundle = Path(args.out)
    if bundle.exists() and any(bundle.iterdir()):
        raise Stop(f"{bundle} is not empty", "Pass a new --out directory")
    manifest = film_bundle.build(mp4, srt, args.unit_id, bundle)
    u = manifest["units"][0]
    rec.event("bundle_film", "bundled", {"target": t, "bundle": str(bundle),
                                         "mp4_sha256": u["mp4_sha256"]})
    print(f"Bundled {t}: {u['bytes']} bytes, {u['duration_ms']} ms, mp4 {u['mp4_sha256'][:12]}. "
          f"Stage it with attach_audiovisual_film.")


def cmd_glide(args):
    flat = args.flat or args.depth == "-"
    depth = None if args.depth == "-" else Path(args.depth)
    for label, path in (("image", Path(args.image)), ("depth map", depth)):
        if path is not None and not path.is_file():
            raise Stop(f"{label} {path} does not exist", "Fix the path and rerun")
    res = glide.render(Path(args.image), depth, Path(args.out), args.seconds, zoom=args.zoom, pan_x=args.pan_x,
                       pan_y=args.pan_y, ease=args.ease, flat=flat, sweep=args.sweep, drain=args.drain)
    print(f"Glide {args.out}: {res['frames']} frames at 24 fps, overscan {res['base_overscan']:.3f}.")


def cmd_retime(args):
    src, text = Path(args.src), Path(args.text)
    for path in (src, text):
        if not path.is_file():
            raise Stop(f"{path} does not exist", "Fix the path and rerun")
    pauses = retime.detect_pauses(src)
    plan = retime.plan_pauses(text.read_text(encoding="utf-8"), pauses, args.seed)
    cuts = [float(c) for c in args.cuts.split(",") if c.strip()] if args.cuts else []
    res = retime.retime(src, Path(args.dst), plan, cuts)
    print(json.dumps({"pauses": len(pauses), **res}))


COMMANDS = {"init": cmd_init, "plan": cmd_plan, "job": cmd_job, "import": cmd_import,
            "import-take": cmd_import_take,
            "supersede": cmd_supersede, "close": cmd_close, "pick": cmd_pick, "hold": cmd_hold, "touchup": cmd_touchup, "glide": cmd_glide, "retime": cmd_retime,
            "exchange-stage": cmd_exchange_stage, "exchange-collect": cmd_exchange_collect,
            "film": cmd_film, "reel": cmd_reel, "qc": cmd_qc, "status": cmd_status,
            "bundle-audio": cmd_bundle_audio,
            "bundle-film": cmd_bundle_film}


def _parser():
    p = argparse.ArgumentParser(prog=PROG, description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--root", required=True)
        s.add_argument("--ledger", help="init pins it in record.json; later commands refuse any other")
        return s

    s = add("init")
    s.add_argument("source")
    s.add_argument("--slug")
    add("plan").add_argument("--wpm", type=float, default=120)
    s = add("job")
    s.add_argument("kind", choices=colab_jobs.KINDS)
    s.add_argument("--rates", required=True)
    s.add_argument("--spec")
    s.add_argument("--film", type=int, default=1)
    s.add_argument("--reel", type=int)
    s.add_argument("--clause", help="optional appended voice clause, <= 12 words")
    s.add_argument("--expressive", action="store_true",
                   help="narration: storyteller style (grouping, emotion direction, varied pauses)")
    s.add_argument("--directions", help="narration with --expressive: {unit_key: {emotion, clause}}")
    s.add_argument("--voice", help="narration: an OWNER_SELECTED storyteller preset_key")
    s.add_argument("--audition", help="narration: audition.json (3 passages x candidate presets)")
    s.add_argument("--list-units", action="store_true",
                   help="narration: print the unit keys and texts this job would use; build nothing")
    s.add_argument("--job-id")
    s = add("import-take", help="file an ElevenLabs narration job from one take per scene")
    s.add_argument("target", help="film-NN or reel-N")
    s.add_argument("--scripts", required=True, help="folder of <scene_id>.txt tagged scripts")
    s.add_argument("--audio", required=True, help="folder of <scene_id>.mp3 takes")
    s.add_argument("--engine", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--voice-id", required=True)
    s.add_argument("--voice-name", required=True)
    s.add_argument("--credits", type=float, required=True, help="credits the generations used")
    s.add_argument("--job-id")
    s = add("import")
    s.add_argument("job_id")
    s.add_argument("--from", dest="source", required=True)
    s.add_argument("--units", type=float, required=True)
    s.add_argument("--archive-sha256")
    s = add("exchange-stage")
    s.add_argument("job_id")
    s.add_argument("--signed", help="file with the two JSON lines presign_colab_exchange printed")
    s.add_argument("--account", help="Cloudflare account id (else $EAV_R2_ACCOUNT)")
    s.add_argument("--bucket", help="private R2 bucket (else $EAV_R2_BUCKET)")
    s = add("exchange-collect")
    s.add_argument("job_id")
    s.add_argument("--units", type=float, required=True, help="the CU Colab shows the run used")
    s.add_argument("--account", help="Cloudflare account id (else $EAV_R2_ACCOUNT)")
    s.add_argument("--bucket", help="private R2 bucket (else $EAV_R2_BUCKET)")
    s = add("supersede")
    s.add_argument("job_id")
    s.add_argument("--reason", required=True)
    s = add("close")
    s.add_argument("job_id")
    s.add_argument("--units", type=float, required=True, help="the CU Colab shows the run used")
    s.add_argument("--reason", required=True)
    s = add("pick", help="choose one candidate per redone still after review")
    s.add_argument("--job", required=True,
                   help="the imported stills, retouch, touchup or edit job with <key>--cN candidates")
    s.add_argument("--choices", required=True, help='JSON file {"<key>": <candidate number>, ...}')
    s = add("hold", help="show the nearest approved still of the scene for shots with none yet")
    s.add_argument("--film", type=int, default=1)
    s.add_argument("--keys", help="comma-separated held still keys, e.g. f01s007-4,f01s007-5")
    s.add_argument("--clear", action="store_true", help="remove all holds of the film")
    s = add("touchup", help="repaint small defects in hand-placed boxes of imported stills (local)")
    s.add_argument("--film", type=int, required=True)
    s.add_argument("--spec", required=True, help='{"items": [{"key", "source": {"job", "file"}, "ops"}]}')
    s.add_argument("--job-id", required=True)
    s = sub.add_parser("glide", help="layered depth camera glide of one still (standalone: no record)")
    s.add_argument("image")
    s.add_argument("depth", help="16-bit PNG or .npy depth map, or - for flat")
    s.add_argument("out")
    s.add_argument("--seconds", type=float, required=True)
    s.add_argument("--zoom", type=float, default=0.12)
    s.add_argument("--pan-x", type=float, default=0.0)
    s.add_argument("--pan-y", type=float, default=0.0)
    s.add_argument("--ease", default="both", choices=glide.EASES)
    s.add_argument("--flat", action="store_true", help="single layer, no depth split (faces, close-ups)")
    s.add_argument("--sweep", choices=glide.SWEEPS)
    s.add_argument("--drain", action="store_true")
    s = sub.add_parser("retime", help="re-time narration pauses by punctuation with room tone (standalone: no record)")
    s.add_argument("src")
    s.add_argument("dst")
    s.add_argument("--text", required=True, help="the narrated script text (UTF-8)")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--cuts", help="comma-separated cut times in the old timeline to map into the new one")
    s = add("film")
    s.add_argument("--film", type=int, default=1)
    s.add_argument("--logo", required=True)
    s.add_argument("--end-card", required=True)
    s.add_argument("--score")
    s.add_argument("--score-route", help="vcsl or ace-step:<imported music job id>")
    s.add_argument("--cues-job")
    s = add("reel")
    s.add_argument("n", type=int)
    s.add_argument("--script")
    s.add_argument("--plan-shots", action="store_true",
                   help="plan the shots from the imported, measured reel narration")
    s.add_argument("--score")
    s.add_argument("--score-route", help="vcsl or ace-step:<imported music job id>")
    s.add_argument("--hashtags", nargs="*")
    add("qc")
    add("status")
    s = add("bundle-audio")
    s.add_argument("--out", required=True)
    s.add_argument("--score-dir", help="<unit_id>.wav score bed per chapter (default route)")
    s.add_argument("--score-route", help="with --score-dir: vcsl or ace-step:<imported music job id>")
    s.add_argument("--dry", action="store_true", help="narration only; recorded in the evidence draft")
    s = add("bundle-film")
    s.add_argument("--film", required=True, help="film id, e.g. film-01")
    s.add_argument("--unit-id", required=True, help="the Maison unit UUID the film belongs to")
    s.add_argument("--out", required=True)
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        COMMANDS[args.command](args)
    except Stop as e:
        print(f"STOP: {e}")
        print(f"Next: {e.next_action}")
        return e.code
    except (OSError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
        print(f"STOP: {type(e).__name__}: {e}")
        print("Next: fix the named file or input and rerun the same command")
        return 2
    except ValueError as e:  # a helper refused its input: report it, never a traceback
        print(f"STOP: {e}")
        print(f"Next: fix the input it names, then rerun; {PROG} status --root {args.root}"
              if hasattr(args, "root") else "Next: fix the input it names, then rerun")
        return 2
    if hasattr(args, "root"):
        print(f"Next: {next_action(args.root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
