"""earnalism-audiovisual orchestrator: one title root, one production record, one next action.

  python3 -m eav.cli init <source.json> --root <dir> [--slug <maison-edition-slug>]
  python3 -m eav.cli plan --root <dir>
  python3 -m eav.cli job <narration|stills|music|reel_clips|film_clips> --root <dir> --rates <rates.json>
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
  python3 -m eav.cli split-passages film-NN --root <dir> --out <dir> [--cps 13]
                         (writes the untagged <scene>-p<NN>.txt passages of 15-30 s to tag for Eleven v4)
  python3 -m eav.cli import-take film-NN --root <dir> --scripts <dir of <scene>-p<NN>.txt> --audio
                         <dir of <scene>-p<NN>.mp3> --engine elevenlabs --model <model_id of <root>/voice.json>
                         --voice-id <id> --voice-name "<name>" --credits <credits used> [--cps 13]
                         [--profile voicecheck-profile.json] [--scene ID] [--accept PID=reason] [--no-retime]
                         (Eleven v4: each passage retimed (pauses matched to punctuation by position; --no-retime
                         keeps an already-retimed, owner-endorsed take as it is, recorded) and voicechecked, the
                         scene joined to film/film-NN/voice/<scene>.wav with a 0.85 s lead-in and a 2 s tail; a
                         failed passage blocks the join; after 3 different failed takes of a passage the owner
                         decides; --accept joins it on a recorded reason)
  python3 -m eav.cli scene-timing --root <dir> --film N --scene ID [--min-pause 0.3 --threshold-db -38]
                         (the measured clause timing of the scene voice for plan-shots, its lead-in and tail:
                         film/film-NN/shots/<scene>.timing.json; each clause boundary's pause is matched to its
                         punctuation by position, unpunctuated breaths stay inside their clauses, and a boundary
                         with no pause near its words stops)
  python3 -m eav.cli job film_clips --root <dir> --rates <rates.json> --resume <job_id> [--from <partial download>]
                         (reserves the rest of a job a hard stop cut short, then writes its resume notebook)
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
  python3 -m eav.cli clip-touchup --root <dir> --film N --spec <clip-touchup.json> --job-id <id>
                         (local OpenCV repaint of one recorded mask in every frame of imported Wan clips into
                         NEW clips: fill along a direction or inpaint; sha256 of source and output, motion gate;
                         then adopt binds the touched clip to its shot)
  python3 -m eav.cli glide <image> <depth.png|depth.npy|-> <out.mp4> --seconds S [--zoom 0.12 --pan-x 0 --pan-y 0
                         --ease both|in|out|none --flat --sweep down-left|down-right --drain]
                         (no --root: a layered 2.5D camera glide of one still, 1920x1080 at 24 fps; "-" = flat)
  python3 -m eav.cli retime <take.mp3|wav> <out.wav> --text <script text file> [--seed 0 --cuts 1.2,3.4]
                         (no --root: pauses detected, re-timed by punctuation, filled with the take's room tone;
                         prints JSON with the cut times mapped into the new timeline and the new duration)
  python3 -m eav.cli cue --root <dir> --film N --scene ID --stems <imported music job id> --tonic D --pick
                         (the scene's own music job only; measures its stems and saves the drone/solo/phrase choice,
                         each within its family (item "role", else the word in its key), to music/<job>/cue-pick.json)
  python3 -m eav.cli cue --root <dir> --film N --scene ID --stems <music job id> [--drone K --solo K --phrase K]
                         [--voice <retimed wav>] [--fx <fx.json>]
                         (the scene's soundtrack: needs the approved shot plan and every fx file's licence record in
                         a licences.json beside it (CC0 or author-released public domain); cuts = shot starts, peak = plan peak;
                         voice default film/film-NN/voice/<scene>.wav, writes film/film-NN/audio/<scene>.mix.wav
                         (stereo, -16 LUFS, <= -1.5 dBTP) and <scene>.mix.json. fx.json: {"ambience": [...], "foley": [...]}
                         entries {"path","at","gain_db","fin","fout","start"?,"dur"?}; gain_db = the clip's RMS dBFS)
  python3 -m eav.cli plan-shots --root <dir> --film N --scene ID [--bible <world-bible.json>] [--approve --by <name> --reviewer <name>]
                         (the paper edit, R11: lays film/film-NN/shots/<scene>.input.json out on its measured timing,
                         writes <scene>.json and the two-column <scene>.av.md and prints rules R1-R3 (hard) and
                         R7?/R8? (soft: "?" = reviewer must look, never a refusal). The input is written by Claude
                         and an independent reviewer; the code never invents content:
                           {"timing": [{"start","end","text"}, ...]  measured clauses, re-timed narration seconds
                            (optional: else <scene>.timing.json of scene-timing, its length_s included),
                            "spine", "fidelity" (R7 note), "motifs": [...], "peak": {"shot": n, "at": s},
                            "shots": [{"beats": [first, last], "subject", "framing", "motion": wan|glide|static,
                              "layer": present|memory|imagined, "transition_in": cut|dissolve|match,
                              "bible_refs": [character keys], "camera": {"move","zoom","pan_x","ease"} (glide),
                              "wan_res": "1280x704"|"896x512" (wan), "actions": [one per 6 s] (a wan shot over 6 s),
                              "sound": {"sfx": [...], "music"},
                              "plants": [earlier shot n] (the peak shot)}]}
                         --approve records approved {by, at, reviewer}; the two names must differ and rules R1-R3
                         must pass. A job spec that declares "scene" is refused until its plan is approved.)
  python3 -m eav.cli voicecheck <take...> --expected S[,S...] [--profile profile.json] [--prev-tail <wav>] [--out <dir>]
                         [--transcripts transcripts.json --sources <dir of <take-stem>.txt>]
                         (no --root: the narration redo gate; writes <take-stem>.voicecheck.json beside each take (or into --out)
                         with pass, failures and metrics; exits 1 if any take fails. Without --profile the book
                         profile is measured from the given takes and saved as voicecheck-profile.json; REDO RUNS MUST
                         PASS --profile <that file>. --expected is one value for all or one per take; --prev-tail is
                         the take before the first listed one, for the join check. With --transcripts (Whisper, from
                         templates/words_cell.py.txt) and --sources the `words` CER check runs; without a matching transcript it
                         is recorded as NOT RUN, never as a pass; import-take --transcripts does the same per passage)
  python3 -m eav.cli pick --root <dir> --job <stills|retouch|touchup|edit job id> --choices <{"<key>": N} json file>
                         (after review: one candidate per <key>--cN still; film uses only picks)
  python3 -m eav.cli adopt --root <dir> --spec <adopt.json> [--scene ID]
                         (G1: bind media that already exists to one scene's APPROVED shots, 0 CU, idempotent:
                         {"scene", "sources": {"<job>": {"root": <title root>} | {"folder": <pilot job folder>}},
                          "stills": {"<scene>-<n>": {"job", "file"} | {"file", "reason", "from"?: {"job", "file"}}},
                          "clips": {"<n>": {"job", "takes": [take, continuation...], "art"?: {"file", "reason"}}},
                          "depth": {"<scene>-<n>": {"job", "file": "<stem>.depth.png"}},
                          "music": {"job", "keys"?, "roles"?: {"<key>": drone|solo|phrase}}}
                         every file verified by sha256 against the job's recorded import (or a pilot job folder's
                         own COMPLETE outputs manifest and inputs.zip); hand-copied files need a reason and are
                         traced; takes keep their motion verdict (gated now if none); a depth map binds only to the
                         still it was made from; picks, licences and provenance are recorded)
  python3 -m eav.cli hold --root <dir> --film N --keys k1,k2,... [--clear]
                         (shots with no approved still: the film shows the scene's nearest approved still;
                         a picked edit of a held key releases that key)
  python3 -m eav.cli film --root <dir> [--film N] --logo <png> --end-card <png>
                         (--score <wav> --score-route vcsl|ace-step:<job_id> | --cues-job <id>)
         cinematic: film --root <dir> --film N --logo <png> --end-card <png> --shots --title T --author A
                         --narrator V [--burn] [--fonts <dir>]  (approved shots/<scene>.json + audio/<scene>.mix.wav)
                         [--scene ID]  (one scene's own cut, film/film-NN/film-NN-<ID>.mp4, for its review)
  python3 -m eav.cli reel <n> --root <dir> --script <script.json> [--hashtags ...]
  python3 -m eav.cli reel <n> --root <dir> --plan-shots           (after reel narration import)
  python3 -m eav.cli reel <n> --root <dir> [--score <wav> --score-route ...]
  python3 -m eav.cli qc --root <dir>
                         (cinematic films also run the face gate per scene on the media recorded in the cut:
                         qc/<scene>-faces.jpg, qc/faces/<scene>/; a double or missing pupil on a still, or held over
                         3 (double) or 4 (missing) sampled frames of a take, fails unless picks/gate-overrides.json has
                         "faces:<key>": reason; a pick changed since the cut fails until film --shots rebuilds it; a
                         shot with a character but no face judged is listed as not judged)
  python3 -m eav.cli facegate <clip|still|folder> ... [--out <dir>] [--fresh] [--expect-face]
                         (no --root: double/missing pupils, eye asymmetry, eyes off the face (takes only), morphing
                         eyes, LED-like glows; <key>.face.json and the face close-up sheet <key>.faces.png; media
                         untouched; --expect-face: a file with no face judged is a review finding)
  python3 -m eav.cli status --root <dir> [--scene ID]   (--scene: that one scene's route, not the film's first scene)
  python3 -m eav.cli bundle-audio --root <dir> --out <bundle dir> [--profile audiobook|film]
                         [--frame-dir <dir of title.wav, author.wav, closing.wav>]
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
The 60 CU title cap is lifetime (title-caps.json pinned at init, or beside/above the ledger, sets a title's own cap);
the 100 CU cap is per calendar month.
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
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from . import budget, colab_jobs, exchange, film, film_bundle, importer, mix, qc, reel, scenes, take
from . import adopt, cliptouch, cue, facegate, glide, motiongate, passages, retime, shotplan, touchup, voicecheck
from .record import Record, sha256_file
from .text import sentences
from .voice import CONTINUOUS, EXPRESSIVE, _segments, _style, unit_anchors, voice_units

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
STAGING_NOTE = ("Staging with attach_audiovisual_audio currently needs --profile film until the importer change in "
                "docs/interface-notes/2026-11-27-audio-bundle-sentences-chapters.md lands.")
FRAME_UNITS = ("title", "author", "closing")  # the audiobook's spoken opening and closing word
LOOP_MIN = 0.8
HOOK_ONSET_MAX_S = 0.2
MP3_END_SLACK_MS = 50
TAKE_JOB = "narration_take"   # artifact kind of an imported ElevenLabs take job (its manifest)
TOUCHUP_JOB = "touchup_job"   # artifact kind of a local touch-up job (its manifest)
ADOPT_JOB = "adopted_job"     # artifact kind of an adoption (G1): already-imported media bound to one scene's shots
TOUCHUP_SCHEMA = "earnalism.audiovisual-touchup.v1"
TAKE_ENGINES = {"elevenlabs": ("eleven_v3",)}  # owner decision 2026-11-24
TAKE_AUDIO = (".mp3", ".wav")
VOICE_SETTINGS = "voice.json"   # the title's voice settings: {"model_id": "<the owner-chosen Eleven v4 model id>"}
TAKE_SCHEMA = "earnalism.audiovisual-take-import.v1"
PASSAGES_SCHEMA = "earnalism.audiovisual-passages.v1"


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
    caps = rec.data.get("title_caps")   # G11: a title-caps.json pinned at init, relative to the root
    caps = (rec.root / caps).resolve() if caps else None
    if caps is not None and not caps.is_file():
        raise Stop(f"record.json pins the title caps {caps}, which does not exist; the caps are never assumed",
                   "Restore that title-caps.json (the owner's caps), then rerun")
    return budget.Ledger(path, caps=caps)


def _cap_note(ledger, title) -> str:
    """The title's lifetime cap and the file it comes from (G11: never a silent default)."""
    src = budget.caps_path(ledger.path, ledger.caps)
    cap = budget.title_cap(ledger.path, title, ledger.caps)
    return f"{cap:g} ({src if src else f'default: no {budget.CAPS_FILE} pinned, beside or above the ledger'})"


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
        if a["kind"] not in ("colab_job", TAKE_JOB, TOUCHUP_JOB, ADOPT_JOB):
            continue
        m = a["meta"]
        jid = m["job_id"]
        colab = a["kind"] == "colab_job"  # an imported take, touch-up or adoption has no notebook or zip
        out.append({"job_id": jid, "kind": m["job_kind"], "target": targets.get(jid),
                    "engine": details.get(jid, {}).get("engine", "parler"),
                    "order": order.get(jid, -1),
                    # narration voice style and storyteller preset (None: the default style/plan voice)
                    "style": details.get(jid, {}).get("voice_style"),
                    "voice": details.get(jid, {}).get("voice"),
                    "scene": details.get(jid, {}).get("scene"),   # the scene a cinematic job is bound to
                    "notebook": rec.root / a["path"] if colab else None,
                    "inputs_zip": rec.root / m["inputs_zip"] if colab else None,
                    "manifest": rec.root / m["manifest"], "forecast_units": m["forecast_units"],
                    # an adoption's bindings (adoption.json): its job.json is the "job" in it
                    "adopted": a["kind"] == ADOPT_JOB,
                    "adoption": rec.root / m["manifest"] if a["kind"] == ADOPT_JOB else None,
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
    cap = budget.title_cap(ledger.path, rec.data["title_slug"], ledger.caps)
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
    resumed = _exchange_events(rec, job["job_id"], "resume_reserved")
    if resumed:
        last = resumed[-1]["detail"]
        return (f"Resume {last['resume_id']} of {job['job_id']} is reserved ({last['units']:.2f} CU): the owner runs "
                f"{rec.root / last['notebook']} in Colab in the job's same Drive folder (done.json skips the finished "
                f"clips), then {PROG} import {job['job_id']} --root {rec.root} --from <downloaded folder> --units <CU of "
                f"all its sessions>. If it cannot be imported: {PROG} close {job['job_id']} --root {rec.root} --units "
                '<CU of all its sessions> --reason "<what happened>"')
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
    resume = (f" If the notebook's hard stop cut it short (manifest INCOMPLETE): {PROG} job film_clips --root "
              f"{rec.root} --rates <rates.json> --resume {job['job_id']} --from <the partial download> (reserves the "
              "rest before any rerun)." if job["kind"] == "film_clips" else "")
    return (f"Default (R2 exchange, references/colab-exchange.md): {PROG} exchange-stage "
            f"{job['job_id']} {r} --account <cloudflare account id> --bucket <private bucket>. "
            f"Manual fallback: run the {job['kind']} notebook in Colab: copy {job['inputs_zip']} to Drive {drive}/, "
            f"open {job['notebook']}, set RUN = True in the first cell, Run all; download that Drive "
            f"folder, then: {PROG} import {job['job_id']} --root {rec.root} --from <downloaded folder> "
            f"--units <CU shown in Colab>. If it ran but cannot be imported (crash, hard stop, lost "
            f"download): {PROG} close {job['job_id']} --root {rec.root} --units <CU shown in Colab> "
            '--reason "<what happened>"' + resume)


def _scene_next(rec, root, i, sid) -> str:
    """The cinematic flow's next step for one scene (C3), or "" when its mix is made: v4 passages (voicecheck runs
    in import-take) -> scene-timing -> plan-shots and approval -> stills job, pick -> film_clips (Wan shots plus
    the glide stills' depth maps) -> the scene's own music job -> cue."""
    r, t = f"--root {root}", _film_target(i)
    film_dir = root / "film" / t
    voice = film_dir / "voice" / f"{sid}.wav"
    if not voice.is_file():
        if not (root / VOICE_SETTINGS).is_file():
            return (f"Eleven v4 narration (references/earnalism-voice.md): write {root / VOICE_SETTINGS} "
                    '{"model_id": "<the owner-chosen Eleven v4 model id>"}; then split-passages, tag, one take per '
                    f"passage and import-take {t} (each passage voicechecked)")
        return (f"Scene {sid} voice (Eleven v4 passages, references/earnalism-voice.md): {PROG} split-passages {t} {r} "
                f"--out <dir>; tag each passage; generate one take per passage; then {PROG} import-take {t} {r} "
                f"--scene {sid} --scripts <dir> --audio <dir> --engine elevenlabs --model <model_id of "
                f"{VOICE_SETTINGS}> --voice-id <id> --voice-name \"<name>\" --credits <credits used> (each passage is "
                "retimed and voicechecked; only failed passages are regenerated, at most "
                f"{MAX_PASSAGE_ATTEMPTS} takes each)")
    paths = shotplan.paths(film_dir, sid)
    if not paths["input"].is_file() and not _timing_path(film_dir, sid).is_file():
        return f"{PROG} scene-timing {r} --film {i} --scene {sid} (the measured clause timing for the paper edit)"
    try:
        sp = shotplan.require_approved(film_dir, sid)
    except shotplan.NotApproved:
        if not paths["input"].is_file():
            return (f"Write the paper edit of scene {sid} into {paths['input']} (Claude with an independent reviewer; "
                    f"{PROG} --help, plan-shots; references/film-recipe.md), then {PROG} plan-shots {r} --film {i} "
                    f"--scene {sid}")
        return (f"{PROG} plan-shots {r} --film {i} --scene {sid}; once rules R1-R3 pass: the same with --approve "
                "--by <name> --reviewer <independent reviewer>")
    picks = _scene_picks(rec, t, sid)
    stills = [s for s in _still_shots(sp) if f"{sid}-{s['n']}" not in picks]
    if stills:
        jobs = [j for j in _jobs(rec) if j["kind"] == "stills" and j["target"] == t and j["scene"] == sid
                and j["imported"] and not _ended(j) and not j["adopted"]]
        if jobs:
            return (f"Review the candidates of {jobs[-1]['job_id']} (contact sheets; the gate's verdicts), then "
                    f"{PROG} pick {r} --job {jobs[-1]['job_id']} --choices <{{\"{sid}-<n>\": N}} json> for "
                    + ", ".join(f"{sid}-{s['n']}" for s in stills))
        return (f"Write stills.json for scene {sid} (\"scene\": \"{sid}\"; one item per glide/static shot, key "
                f"{sid}-<n>, \"candidates\": 3; references/film-recipe.md) for "
                + ", ".join(f"{sid}-{s['n']}" for s in stills) + f", then {PROG} job stills {r} --film {i} "
                f"--rates <rates.json> --spec stills.json (media the owner already picked: {PROG} adopt {r} --spec "
                "adopt.json instead, 0 CU)")
    maps = _depth_maps(rec, t)
    no_depth = [s for s in _depth_shots(sp) if (f"{sid}-{s['n']}.png", picks[f"{sid}-{s['n']}"]["sha256"]) not in maps]
    items = _film_clip_items(rec, t)
    no_clip = [s for s in sp["shots"] if s["motion"] == "wan"
               and not any(c["item"].get("shot") == s["n"] and k.startswith(sid + "-") for k, c in items.items())]
    if no_depth or no_clip:
        wan_n = ", ".join(str(s["n"]) for s in no_clip)
        depth_keys = ", ".join(f"{sid}-{s['n']}" for s in no_depth)
        what = ([f"Wan shot(s) {wan_n} (each take chained to cover its shot)"] if no_clip else []) + (
            [f"the depth maps of glide still(s) {depth_keys}"] if no_depth else [])
        return (f"Write clips.json for scene {sid} (\"scene\": \"{sid}\", art_dir, items {{key {sid}-<n>..., shot, "
                "image, width, height, seed, prompt, continue_from}}; references/film-recipe.md) for "
                + " and ".join(what) + f", then {PROG} job film_clips {r} --film {i} --rates <rates.json> --spec "
                "clips.json (depth stills are filled in from the picks; split per 70-minute session; takes and depth "
                f"maps that already exist: {PROG} adopt {r} --spec adopt.json, 0 CU)")
    if not (film_dir / "audio" / f"{sid}.mix.wav").is_file():
        music = [j for j in _jobs(rec) if j["kind"] == "music" and j["target"] == t and j["scene"] == sid
                 and j["imported"] and not _ended(j)]
        if not music:
            return (f"Write music.json for scene {sid} (\"scene\": \"{sid}\", stems with \"role\" drone, solo or phrase, "
                    f"three seeds each; references/film-recipe.md), then {PROG} job music {r} --film {i} --rates "
                    f"<rates.json> --spec music.json (stems already made for this scene: {PROG} adopt {r} --spec "
                    "adopt.json, 0 CU)")
        m = music[-1]["job_id"]
        return (f"{PROG} cue {r} --film {i} --scene {sid} --stems {m} --pick --tonic <note>, then {PROG} cue {r} "
                f"--film {i} --scene {sid} --stems {m} --fx <fx.json, every sound with its licence record>")
    return ""


def _film_next(rec, root, i, scenes) -> str:
    """The cinematic flow of film i (C3): every scene through its mix, then `film --shots`; or "" when the film is
    assembled shot by shot."""
    t = _film_target(i)
    if [a for a in _artifacts(rec, "film", target=t) if a["meta"].get("mode") == "shots"]:
        return ""   # assembled shot by shot: qc and review follow
    for sc in scenes:
        step = _scene_next(rec, root, i, sc["scene_id"])
        if step:
            return step
    return (f"{PROG} film --root {root} --film {i} --shots --logo <approved logo lockup> --end-card <approved END> "
            "--title <title> --author <author> --narrator <narration voice> [--burn], then "
            f"{PROG} qc --root {root}")


def _scene_film(rec, t, sid):
    """The latest film of one scene (`film --shots --scene`), or None."""
    found = [a for a in _artifacts(rec, "scene_film", target=t) if a["meta"].get("scene") == sid]
    return found[-1] if found else None


def _scene_route(rec, root, sid) -> str:
    """G6: the next step of one scene, for an operator working on that scene alone (a reference scene): its
    cinematic flow, then `film --shots --scene`, qc and the owner's review. The whole film is untouched by it."""
    plan = _plan(rec)
    for i, f in enumerate(plan["plan"]["films"], 1):
        if any(sc["scene_id"] == sid for sc in f["scenes"]):
            break
    else:
        return f"Scene {sid} is not in the plan; {PROG} status --root {root} (the whole film)"
    step = _scene_next(rec, root, i, sid)
    if step:
        return step
    t, r = _film_target(i), f"--root {root}"
    art = _scene_film(rec, t, sid)
    if art is None:
        return (f"{PROG} film {r} --film {i} --scene {sid} --shots --logo <approved logo lockup> --end-card "
                "<approved END> --title <title> --author <author> --narrator <narration voice> [--burn], then "
                f"{PROG} qc {r}")
    events = rec.data["events"]
    made = max((k for k, e in enumerate(events) if e["stage"] == "film" and e["result"] == "scene_assembled"
                and e["detail"].get("scene") == sid and e["detail"].get("target") == t), default=-1)
    qcs = [(k, e) for k, e in enumerate(events) if e["stage"] == "qc" and k > made]
    if not qcs:
        return f"{PROG} qc {r}"
    mine = [f for f in qcs[-1][1]["detail"].get("failed") or [] if f.startswith(f"{t}/{sid}:")]
    if mine:
        return (f"Fix only the failing items of scene {sid} ({', '.join(mine)}; qc/report.json), re-assemble it "
                f"({PROG} film {r} --film {i} --scene {sid} --shots ...), then {PROG} qc {r}")
    return (f"Owner reviews scene {sid} ({art['path']}: picture, motion, sound; listening stays unassessed until "
            f"then). The whole film: {PROG} status {r} (without --scene)")


def next_action(root, scene=None) -> str:
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
    pending = [j for j in jobs if not j["imported"] and not _ended(j) and (scene is None or j["scene"] == scene)]
    if pending:
        return _colab_action(rec, pending[0])
    if scene:
        return _scene_route(rec, root, scene)
    r = f"--root {root}"
    plan = _plan(rec)
    for i, f in enumerate(plan["plan"]["films"], 1):
        step = _film_next(rec, root, i, f["scenes"])
        if step:
            return step
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
                f"{root / 'maison' / 'bundle'} --frame-dir <title.wav, author.wav, closing.wav> "
                "--score-dir <one score bed per chapter> --score-route "
                f"vcsl|ace-step:<music job_id>. {STAGING_NOTE} For Maison video (full films, private R2): {PROG} bundle-film. "
                "Social posting only to destinations the owner names (references/publishing.md).")
    return (f"Owner completes (territories, term_per_territory for every territory, text_source_licence, "
            f"cover_provenance) and approves {root / 'maison' / EVIDENCE_DRAFT}, saves it under docs/evidence/, "
            "then on the server: python manage.py attach_audiovisual_audio stage <slug> --publisher "
            f"<public_id> --bundle <bundle dir> --evidence docs/evidence/<file>.json (references/publishing.md). {STAGING_NOTE}")


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
    if args.title_caps and not Path(args.title_caps).is_file():
        raise Stop(f"--title-caps {args.title_caps} does not exist", "Pass the owner's title-caps.json")
    rec = Record.create(root, slug, {
        "edition_id": src.get("edition_id"), "revision_id": src["revision_id"],
        "content_sha256": src["content_sha256"], "language": src["language"],
        "rights": src.get("rights", {}), "public_domain_evidence": True,
        "state": src.get("state"), "export_sha256": sha256_file(src_path)})
    rec.data["ledger"] = Path(os.path.relpath(ledger, root.resolve())).as_posix()  # R17: relative pin
    caps = Path(args.title_caps).resolve() if args.title_caps else budget.caps_path(ledger)
    if caps is not None:   # G11: the caps the ledger is held to, pinned like the ledger
        rec.data["title_caps"] = Path(os.path.relpath(caps, root.resolve())).as_posix()
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
        if (kind in ("reel_clips", "film_clips") or (kind == "stills" and "art_dir" in spec)) \
                and not Path(spec.get("art_dir", ".")).is_absolute():
            spec["art_dir"] = str((Path(args.spec).parent / spec.get("art_dir", ".")).resolve())
        if kind == "reel_clips":
            _check_clip_batch(rec, args.reel, spec)
    if args.job_id:
        spec["job_id"] = args.job_id
    try:
        return spec, colab_jobs.job_items(kind, spec)
    except ValueError as e:
        raise Stop(f"job not built: {e}", "Fix the directions, audition or clause and rerun")


def _job_json(job) -> dict:
    """The built job.json of a notebook job (inside its inputs.zip), or an adoption's bound job, or {}."""
    if job.get("adoption"):
        try:
            return _json(job["adoption"]).get("job") or {}
        except (OSError, ValueError):
            return {}
    if job.get("kind") == "clip_touchup":   # a clip touch-up's items (the source items, key unchanged)
        try:
            return _json(job["manifest"]).get("job") or {}
        except (OSError, ValueError):
            return {}
    if not job.get("inputs_zip"):   # a local job (touch-up, take) has no notebook inputs: nothing was built
        return {}
    try:
        with zipfile.ZipFile(job["inputs_zip"]) as z:
            return json.loads(z.read("job.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, TypeError):
        return {}


def _scene_picks(rec, t, sid) -> dict:
    """{"<sid>-<n>": {"path", "sha256", "job_id", "candidate"}}: the operator's recorded picks of the stills (and
    retouch, touchup, edit) jobs bound to scene `sid` ("scene" in their spec), the latest job's pick winning per key.
    Nothing else is a cinematic still: no unpicked file, no base job, no older film's still with the same key (C2)."""
    out = {}
    for j in sorted(_jobs(rec), key=lambda j: j["order"]):
        if j["kind"] not in PICK_KINDS or j["target"] != t or not j["imported"] or _ended(j) or j["scene"] != sid:
            continue
        for key, c in (_latest_pick(rec, j["job_id"]) or {}).items():
            if key.rpartition("-")[0] != sid:
                continue
            src = rec.root / c["file"]
            if not src.is_file() or sha256_file(src) != c["sha256"]:
                raise Stop(f"picked still {c['file']} changed since it was picked",
                           f"{PROG} pick --root {rec.root} --job {j['job_id']} --choices <json>")
            out[key] = {"path": src, "sha256": c["sha256"], "job_id": j["job_id"], "candidate": c.get("candidate")}
    return out


def _still_shots(sp) -> list:
    return [s for s in sp["shots"] if s["motion"] in ("glide", "static")]


def _depth_shots(sp) -> list:
    return [s for s in sp["shots"] if s["motion"] == "glide" and not (s.get("camera") or {}).get("flat")]


def _film_clip_jobs(rec, t, imported=None) -> list:
    return [j for j in _jobs(rec) if j["kind"] == "film_clips" and j["target"] == t and not _ended(j)
            and (imported is None or j["imported"] == imported)]


def _depth_maps(rec, t) -> dict:
    """{(still name, sha256 of the still): depth map path} of the imported film_clips jobs' depth-only stills."""
    out = {}
    for j in _film_clip_jobs(rec, t, imported=True):
        for name, sha in (_job_json(j).get("depth_stills") or {}).items():
            path = rec.root / "film_clips" / j["job_id"] / "depth" / (name.rsplit(".", 1)[0] + ".depth.png")
            if path.is_file():
                out[(name, sha)] = path
    return out


def _film_clips_scene_spec(rec, args, spec, t, approved):
    """C1/I3/I5: bind a scene's film_clips spec to its approved plan. The depth stills are filled in from the
    scene's picks (every non-flat glide shot whose picked still has no depth map yet from an active job), each
    take's chain must cover its shot, and Wan shots already held by another active job of the scene count."""
    sid = spec["scene"]
    picks = _scene_picks(rec, t, sid)
    unpicked = [f"{sid}-{s['n']}" for s in _depth_shots(approved) if f"{sid}-{s['n']}" not in picks]
    need = [s for s in _depth_shots(approved) if f"{sid}-{s['n']}" in picks]
    if unpicked:
        print(f"NOTE: glide shot(s) {', '.join(unpicked)} have no picked still yet: their depth maps need a later "
              f"film_clips job of scene {sid} (depth only), built after the pick; film --shots refuses them until then.")
    held = {}
    for j in _film_clip_jobs(rec, t):
        held.update(_job_json(j).get("depth_stills") or {})
    depth = {f"{sid}-{s['n']}.png": {"path": str(picks[f"{sid}-{s['n']}"]["path"]),
                                      "sha256": picks[f"{sid}-{s['n']}"]["sha256"]}
             for s in need if held.get(f"{sid}-{s['n']}.png") != picks[f"{sid}-{s['n']}"]["sha256"]}
    listed = spec.get("depth_stills")
    if listed is not None and sorted(listed) != sorted(depth):
        raise Stop(f"the spec lists depth_stills {sorted(listed)}, but the scene's glide shots need exactly "
                   f"{sorted(depth)} (their picked stills without a depth map yet)",
                   "Drop depth_stills from the spec: job film_clips fills it in from the picks")
    if depth:
        spec["depth_stills"] = depth
    else:
        spec.pop("depth_stills", None)
    covered = set()
    for j in _film_clip_jobs(rec, t):
        jj = _job_json(j)
        if jj.get("scene") == sid:
            covered |= {i.get("shot") for i in jj.get("items") or []}
    if not spec.get("items") and not depth:
        raise Stop(f"nothing to build for scene {sid}: every Wan shot has a job and every glide still has a depth map",
                   next_action(rec.root))
    try:
        colab_jobs.check_film_plan(spec, approved, covered)
    except ValueError as e:
        raise Stop(f"job not built: {e}", "Give every item the number of an approved wan shot (\"shot\") at that "
                   "shot's wan_res, chain continuations until each take covers its shot, and give every wan shot "
                   "at least one item")
    return spec


def _resume_film_clips(args, rec):
    """I5: a film_clips job that a session's hard stop cut short is resumed in a new session of the SAME job (its
    Drive folder's done.json skips the finished clips). The remaining items' forecast is reserved first, as a
    ledger entry linked to the job within the title and month caps, and the resume notebook's hard stop is that
    entry's seconds; import (or close) settles the job and its resumes together at the actual CU."""
    job = next((j for j in _jobs(rec) if j["job_id"] == args.resume), None)
    if job is None or job["kind"] != "film_clips":
        raise Stop(f"{args.resume} is not a film_clips job of this title", f"{PROG} status --root {rec.root}")
    if job["imported"] or _ended(job) or job["unfinished"]:
        raise Stop(f"film_clips job {args.resume} is imported, superseded or closed: nothing to resume",
                   f"{PROG} status --root {rec.root}")
    jj = _job_json(job)
    items, depth = jj.get("items") or [], dict(jj.get("depth_stills") or {})
    done, folder = set(), Path(args.source) if args.source else None
    if folder is not None:   # the partial Drive download: done.json, checked against the clips it lists
        try:
            journal = json.loads((folder / "done.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            journal = {}
        done = {k for k, sha in (journal if isinstance(journal, dict) else {}).items()
                if (folder / f"{k}.mp4").is_file() and sha256_file(folder / f"{k}.mp4") == sha}
        depth = {n: h for n, h in depth.items() if not (folder / (n.rsplit(".", 1)[0] + ".depth.png")).is_file()}
    left = [i for i in items if i["key"] not in done]
    if not left and not depth:
        raise Stop(f"every item of {args.resume} is finished in {folder}", f"Let the notebook's manifest cell finish, "
                   f"then {PROG} import {args.resume} --root {rec.root} --from <folder> --units <CU of all sessions>")
    rates = _json(args.rates)
    build = _json(job["manifest"])
    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(job["inputs_zip"]) as z:
        for name in {i["image"] for i in left if i.get("image")} | set(depth):
            (Path(td) / name).write_bytes(z.read(name))
        sub = {"art_dir": td, "items": left, "min_vram_gib": build.get("min_vram_gib", 0),
               **({"depth_stills": sorted(depth)} if depth else {}),
               **({"sfx": jj["sfx"]} if jj.get("sfx") and not (folder and (folder / "sfx-licences.json").is_file()) else {})}
        try:
            compute = colab_jobs.derive_compute("film_clips", sub, rates, colab_jobs.job_items("film_clips", sub))
        except ValueError as e:
            raise Stop(f"resume not built: {e}", "Use the rates.json measured on the last Colab run")
    secs = budget.forecast_seconds(compute, rates)
    units = budget.forecast(compute, rates)
    k = 1 + len(_exchange_events(rec, args.resume, "resume_reserved"))
    resume_id = f"{args.resume}-resume-{k}"
    ledger, month = _ledger(rec, args), _month()
    edition_id = rec.data["source"].get("edition_id")
    here = Path(os.path.relpath(rec.root.resolve(), ledger.path.parent.resolve())).as_posix()
    try:
        ledger.reserve(rec.data["title_slug"], month, units, resume_id, edition_id=edition_id,
                       root=here if edition_id else None, resume_of=args.resume)
    except budget.BudgetExceeded as e:
        raise Stop(f"Budget exceeded: the resume needs {units:.2f} CU: {e}. Nothing was reserved.",
                   "Hold the job and ask the owner; never retry past a cap.", code=3)
    nb = colab_jobs.resume_notebook(job["notebook"], job["notebook"].with_name(f"film_clips.resume-{k}.ipynb"),
                                    secs, resume_id, [i["key"] for i in left] + sorted(depth))
    rec.event("job", "resume_reserved", {"job_id": args.resume, "resume_id": resume_id, "units": units,
                                         "seconds": int(secs), "keys": [i["key"] for i in left],
                                         "depth_stills": sorted(depth),
                                         "notebook": nb.relative_to(rec.root).as_posix()})
    print(f"Resume {resume_id} of film_clips job {args.resume}: {len(left)} clip(s) and {len(depth)} depth still(s) "
          f"left, {int(secs)} s hard stop, {units:.2f} CU reserved (linked to the job). Run {nb} in Colab in the same "
          f"Drive folder; then {PROG} import {args.resume} --root {rec.root} --from <folder> --units <CU of ALL its "
          "sessions> (the job and its resumes settle together).")


def cmd_job(args):
    rec = _record(args.root)
    kind = args.kind
    if args.resume:
        return _resume_film_clips(args, rec)
    if kind == "reel_clips" and not args.reel:
        raise Stop("reel_clips jobs belong to one reel", "Pass --reel <n>")
    target = (AUDITION_TARGET if kind == "narration" and args.audition
              else f"reel-{args.reel}" if args.reel else _film_target(args.film))
    spec, items = _job_spec(rec, args, kind, target)
    if kind in ("stills", "film_clips", "music", "retouch", "edit") and spec.get("scene"):  # R11: a shot-plan-driven job needs the approved paper edit
        try:
            approved = shotplan.require_approved(rec.root / "film" / target, spec["scene"])
        except shotplan.NotApproved as e:
            raise Stop(str(e), f"{PROG} plan-shots --root {rec.root} --film {args.film or '<n>'} --scene {spec['scene']}")
        if kind == "film_clips":  # the approved plan limits what is built: its wan shots, at its wan_res
            spec = _film_clips_scene_spec(rec, args, spec, target, approved)
            items = colab_jobs.job_items(kind, spec)
    if args.list_units:  # for writing directions.json: the keys this job would use; nothing built
        for u in colab_jobs.narration_units(spec):
            print(f"{u['unit_key']}\t{u['text']}")
        return
    rates = _json(args.rates)
    specs = [spec]
    try:  # R21: items and steps come from the job itself, rates from the last measured run
        if kind == "film_clips":   # I5: one job per Colab session (70 min), split where needed
            specs = colab_jobs.split_film_spec(spec, rates)
            if len(specs) > 1 and spec.get("job_id"):
                specs = [{**sp, "job_id": f"{spec['job_id']}-{k}"} for k, sp in enumerate(specs, 1)]
            elif spec.get("job_id"):
                specs[0]["job_id"] = spec["job_id"]
        computes = [colab_jobs.derive_compute(kind, sp, rates, colab_jobs.job_items(kind, sp)) for sp in specs]
    except ValueError as e:
        raise Stop(f"job not built: {e}", "Use the values measured on the last Colab run "
                   "(references/compute-budget.md) and never a compute block that differs from the job")
    compute = computes[0]
    ledger, month = _ledger(rec, args), _month()
    units = sum(budget.forecast(c, rates) for c in computes)
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
                   f"(caps {_cap_note(ledger, rec.data['title_slug'])}/title, {budget.MONTH_CAP:g}/month, {month}). "
                   "Nothing was reserved or written.", hint, code=3)
    built = []
    for sp in specs:
        try:
            result = colab_jobs.build_job(kind, rec, sp, ledger, rates, rec.root / "jobs", month=month)
        except budget.BudgetExceeded as e:
            raise Stop(f"Budget exceeded: {e}. Nothing more was written"
                       + (f" (built before it: {', '.join(built)})" if built else "") + ".",
                       "Hold the job and ask the owner; never retry past a cap.", code=3)
        except (ValueError, FileExistsError, KeyError) as e:
            raise Stop(f"job not built: {e}" + (f" (built before it: {', '.join(built)})" if built else ""),
                       "Fix the spec and rerun")
        detail = {"job_id": result["job_id"], "target": target, "kind": kind}
        if spec.get("style"):
            detail["voice_style"] = spec["style"]
        if kind == "narration" and args.voice:
            detail["voice"] = args.voice
        if isinstance(spec.get("scene"), str):
            detail["scene"] = spec["scene"]
        rec.event("cli", "job_target", detail)
        built.append(result["job_id"])
        if len(specs) > 1:
            print(f"Built {kind} job {result['job_id']} ({len(built)} of {len(specs)}: one Colab session each): "
                  f"forecast {result['forecast_units']:.2f} CU reserved.")
    if len(specs) > 1:
        print(f"Split into {len(specs)} {kind} jobs of at most {colab_jobs.FILM_SESSION_S} s each: {', '.join(built)}; "
              f"{units:.2f} CU reserved in all ({remaining - units:.2f} CU left under the title and month caps). "
              "Inert until the owner enables each in Colab.")
        return
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
    except budget.BudgetExceeded as e:
        raise Stop(f"Import held: {e}. Nothing was imported; the reservation stays open.",
                   "Hold for the owner: the run used more CU than its reservation and the caps allow; never "
                   "settle past a cap", code=3)
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
    v4 = _v4_model(rec) if args.model != "eleven_v3" else None  # a bad voice.json never blocks the v3 route
    per_passage = args.engine == "elevenlabs" and v4 is not None and args.model == v4
    if args.model not in TAKE_ENGINES.get(args.engine, ()) and not per_passage:
        raise Stop(f"engine/model {args.engine}/{args.model} is not the approved narration engine",
                   "Use --engine elevenlabs --model eleven_v3, or the Eleven v4 model_id of the title's "
                   f"{VOICE_SETTINGS} (references/earnalism-voice.md)")
    if not re.fullmatch(r"[A-Za-z0-9]{8,64}", args.voice_id or "") or not (args.voice_name or "").strip():
        raise Stop("--voice-id must be the ElevenLabs voice id and --voice-name its name",
                   "Pass the owner-picked voice (references/earnalism-voice.md)")
    try:
        credits = budget._check_units(args.credits)
    except ValueError:
        raise Stop(f"--credits must be the credits the generations used (>= 0), got {args.credits!r}",
                   "Read them from the ElevenLabs usage and rerun")
    if per_passage:
        return _import_passages(args, rec, plan, lang, credits)
    if args.no_retime:
        raise Stop("--no-retime is for Eleven v4 passage takes (the one-take route slices the take, it never retimes it)",
                   "Drop --no-retime")
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


def _v4_model(rec):
    """The owner-chosen Eleven v4 model id from the title's voice settings (<root>/voice.json), or None.
    Nothing is assumed: without the file only eleven_v3 imports."""
    path = rec.root / VOICE_SETTINGS
    if not path.is_file():
        return None
    try:
        model = json.loads(path.read_text(encoding="utf-8")).get("model_id")
    except (ValueError, AttributeError):
        raise Stop(f"{path} is not a JSON object", f'Write {{"model_id": "<the Eleven v4 model id>"}} in {path}')
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,63}", model):
        raise Stop(f"{path} has no valid model_id", f'Write {{"model_id": "<the Eleven v4 model id>"}} in {path}')
    if model in TAKE_ENGINES["elevenlabs"]:
        raise Stop(f"{path} names {model}, the one-take route's model, as the Eleven v4 id",
                   f'Write the Eleven v4 model id in {path}; {model} is imported without voice.json')
    return model


def _passage_files(scripts: Path, audio: Path, key: str) -> list:
    """[(passage id, tagged script path, take path)] of one scene, numbered p01.. without a gap."""
    found = {}
    for p in scripts.glob(f"{key}-p*.txt"):
        m = re.fullmatch(re.escape(key) + r"-p(\d{2})\.txt", p.name)
        if m:
            found[int(m.group(1))] = p
    if not found:
        raise Stop(f"no passage scripts {key}-p01.txt ... for {key} in {scripts}",
                   f"{PROG} split-passages <film-NN> --root <dir> --out <dir>, tag each passage, generate one "
                   "take per passage")
    rows = []
    for n in range(1, max(found) + 1):
        pid = f"{key}-p{n:02d}"
        if n not in found:
            raise Stop(f"passage script {pid}.txt is missing (numbering must run p01.. without a gap)",
                       f"Add {pid}.txt and its take {pid}.mp3")
        takes = [audio / f"{pid}{ext}" for ext in TAKE_AUDIO if (audio / f"{pid}{ext}").is_file()]
        if len(takes) != 1:
            raise Stop(f"{'no' if not takes else 'more than one'} take for passage {pid} in {audio} "
                       f"(expected {pid}.mp3 or {pid}.wav)", "Download exactly one take per passage, named <passage id>.mp3")
        rows.append((pid, found[n], takes[0]))
    return rows


def _scene_text(sc, lang):
    """(text, heading texts): the scene's units joined by a space within a block and a blank line between
    blocks, so paragraph and heading boundaries survive for the passage cuts and seams."""
    parts, prev, headings = [], None, set()
    for block, text, _ in _segments(sc, lang, _style(CONTINUOUS)):
        if prev is not None:
            parts.append(" " if block is prev else "\n\n")
        parts.append(text)
        if block.get("kind") == "heading":
            headings.add(" ".join(text.split()))
        prev = block
    return "".join(parts), headings


def _import_passages(args, rec, plan, lang, credits):
    """Eleven v4: one take per passage of a scene. Each passage is retimed, then voicechecked (against the
    film's saved profile when present); a scene whose passages all pass is joined into
    film/film-NN/voice/<scene>.wav, the file `cue` reads. A scene with a failed passage is listed for redo and
    not joined; the other scenes of the call still are. Credits are recorded on every run."""
    target, todo = _take_target(rec, plan, args.target)
    if not target.startswith("film-"):
        raise Stop(f"{target} is a reel: passage narration builds film scene voice", "Pass film-NN")
    scripts, audio = Path(args.scripts), Path(args.audio)
    for d, what in ((scripts, "--scripts"), (audio, "--audio")):
        if not d.is_dir():
            raise Stop(f"{what} {d} is not a folder", f"Pass {what} <folder>")
    cps = args.cps
    if not cps or cps <= 0:
        raise Stop(f"--cps must be a positive number of characters per second, got {args.cps!r}", "Fix --cps and rerun")
    if args.scene:
        todo = [t for t in todo if t[0] == args.scene]
        if not todo:
            raise Stop(f"{args.scene} is not a scene of {target}", f"{PROG} status --root {rec.root}")
    else:  # the scenes whose first passage script is present
        todo = [t for t in todo if (scripts / f"{t[0]}-p01.txt").is_file()]
        if not todo:
            raise Stop(f"no <scene>-p01.txt passage script of {target} in {scripts}",
                       f"{PROG} split-passages {target} --root {rec.root} --out <dir>, tag the passages, "
                       "generate one take per passage")
    voice_dir = rec.root / "film" / target / "voice"
    work = voice_dir / "passages"
    scenes, blocked = [], []
    for key, sc in todo:
        wav = voice_dir / f"{key}.wav"
        if wav.is_file() and not (voice_dir / f"{key}.passages.json").is_file():
            if args.scene:
                raise Stop(f"{wav} was placed by hand (no {key}.passages.json); it is not overwritten",
                           "Move that file away if the passages should replace it")
            blocked.append(key)
            continue
        text, headings = _scene_text(sc, lang)
        rows = _passage_files(scripts, audio, key)
        try:
            plain = passages.check_passage_scripts(text, [r[1].read_text(encoding="utf-8") for r in rows])
        except ValueError as e:
            raise Stop(f"passage scripts of {key} rejected: {e}",
                       "Fix the tagged passage scripts (the words are exactly the book's) and regenerate only "
                       "the passages whose script changed")
        scenes.append({"key": key, "rows": rows, "plain": plain, "headings": headings})
    if not scenes:
        raise Stop(f"every requested scene has a hand-placed wav ({', '.join(blocked)}); none is overwritten",
                   "Move the wav away if the passages should replace it")
    work.mkdir(parents=True, exist_ok=True)
    for sub in ("scripts", "takes"):
        (work / sub).mkdir(exist_ok=True)
    retimed = []
    for sc in scenes:
        for (pid, script, take_path), plain in zip(sc["rows"], sc["plain"]):
            shutil.copy2(script, work / "scripts" / script.name)
            shutil.copy2(take_path, work / "takes" / take_path.name)
            dst = work / f"{pid}.wav"
            if args.no_retime:   # G3: an already-retimed (owner-endorsed) take keeps every pause as it is
                retime.retime(take_path, dst, [], [])
            else:   # pauses matched to the punctuation by position; unpunctuated breaths keep place and length
                x = retime.read(take_path)
                a, b = passages._bounds(x)
                pauses = retime.detect_pauses(take_path)
                span = (a / retime.SR, b / retime.SR)
                retime.retime(take_path, dst, retime.plan_pauses(plain, pauses, zlib.crc32(pid.encode()), bounds=span), [])
                cl_ = retime.clauses(plain)
                for r_ in retime.match_pauses(plain, pauses, span):   # I1: reported, never filled from a breath
                    if r_["pause"] is None:
                        print(f"Note {pid}: no pause near the {r_['kind']} ending «{' '.join(cl_[r_['clause']][0].split()[-3:])}» "
                              f"(about {r_['expected_s']:.2f} s into the take); none is inserted, no breath is stretched "
                              "into it: listen there")
            retimed.append((sc, pid, dst, len(plain.strip()), len(retime.read(dst)) / retime.SR))
    tdata = _load_transcripts(args.transcripts) if args.transcripts else None
    words = {}   # passage id -> (transcript of the downloaded take, untagged passage text)
    if tdata is not None:
        for sc in scenes:
            for (pid, _, take_path), plain in zip(sc["rows"], sc["plain"]):
                text = _transcript_for(tdata, pid, take_path)
                if text is not None:
                    words[pid] = (text, plain)
    expected, measured = passages.expected_durations([r[3] for r in retimed], [r[4] for r in retimed], cps)
    if args.profile:
        pf = Path(args.profile)
        try:
            prof = json.loads(pf.read_text())
        except (OSError, ValueError):
            raise Stop(f"{pf} is not a readable voicecheck profile", "Fix --profile and rerun")
    elif (work / "voicecheck-profile.json").is_file():  # a redo run keeps the film's profile (voicecheck rule)
        prof = json.loads((work / "voicecheck-profile.json").read_text())
    else:
        prof = voicecheck.profile([r[2] for r in retimed])
        (work / "voicecheck-profile.json").write_text(json.dumps(prof, indent=1))
    saved_prof = not args.profile
    all_pids = {pid for sc in scenes for pid, _, _ in sc["rows"]}
    accepts = _reasons(args.accept, "--accept")
    unknown = sorted(set(accepts) - all_pids)
    if unknown:
        raise Stop(f"--accept names {', '.join(unknown)}, which is not a passage of this run",
                   f"Name passage ids of this run: {', '.join(sorted(all_pids))}")
    tried = _passage_attempts(rec, target)
    takes_sha = {pid: sha256_file(tk) for sc in scenes for pid, _, tk in sc["rows"]}
    results = {}
    failed, prev, last_key, unchecked = {}, None, None, False
    held = []
    for (sc, pid, dst, _, _), exp in zip(retimed, expected):
        prev = prev if last_key == sc["key"] else None
        res = _words_note(voicecheck.check(dst, exp, prof, prev, *words[pid]) if pid in words
                          else voicecheck.check(dst, exp, prof, prev), tdata)
        unchecked = unchecked or bool(res.get("not_run"))
        if not measured and "duration" in res["failures"]:  # only a guessed rate: a warning, not a failure
            res["failures"] = [f for f in res["failures"] if f != "duration"]
            res["warnings"] = res.get("warnings", []) + ["duration"]
            res["pass"] = False if res["failures"] else (None if res.get("not_run") else True)
        res["expected_s"] = round(exp, 3)
        if res["failures"] and pid in accepts:   # the operator's recorded override: joined, never a pass
            res["accepted"] = {"reason": accepts[pid], "failures": res["failures"]}
            res["failures"], res["pass"] = [], None
        (work / f"{pid}.voicecheck.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
        results[pid] = res
        if res["failures"]:
            attempts = len(tried.get(pid, set()) | {takes_sha[pid]})
            res["attempt"] = attempts
            (work / f"{pid}.voicecheck.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
            note = f"attempt {attempts} of {MAX_PASSAGE_ATTEMPTS}"
            if attempts >= MAX_PASSAGE_ATTEMPTS:
                held.append(pid)
                note += ": HELD for the owner, do not regenerate"
            failed.setdefault(sc["key"], []).append(f"{pid} ({', '.join(res['failures'])}; {note})")
        prev, last_key = dst, sc["key"]
    if saved_prof and tdata is not None:   # only takes accepted in this run enter the saved profile's median
        acc = voicecheck.accepted_cers({k: v for k, v in results.items() if "words" in v["metrics"]})
        if acc:
            (work / "voicecheck-profile.json").write_text(json.dumps(voicecheck.with_words(prof, acc), indent=1))
    for pid, r in sorted(results.items()):
        for code, v in sorted((r.get("warning_values") or {}).items()):
            print(f"Voicecheck WARNING {pid}: {code} measured {v['measured']:g} against the uncalibrated limit "
                  f"{v['limit']:g}; listen. Not a redo until the limit is calibrated on accepted v4 takes.")
        if r.get("accepted"):
            print(f"Accepted by the operator (--accept): {pid} despite {', '.join(r['accepted']['failures'])}: "
                  f"{r['accepted']['reason']}")
    if any("words" in r.get("warnings", []) for r in results.values()):
        print("Word check WARNING: CER above the provisional ceiling "
              f"{voicecheck.WORDS_CEILING:g} (fewer than {voicecheck.WORDS_MIN_TAKES} accepted takes with a "
              "transcript, so no calibrated median yet); listen to the listed passage(s). Not a redo.")
    if unchecked:
        print("Word check NOT RUN for passage(s) without a matching Whisper transcript (--transcripts, "
              "templates/words_cell.py.txt); a passing take is not word-checked.")
    if not measured:
        print(f"Warning: fewer than {passages.MIN_RUN} passages, so the expected duration is only the --cps "
              f"{cps:g} estimate: a duration miss is a warning, not a failure.")
    voice_json = rec.root / VOICE_SETTINGS
    joined = [sc for sc in scenes if sc["key"] not in failed]
    # the credits of THIS run (a redo's: its regenerated passages), recorded first, whether or not anything joins
    rec.event("import", "passages_checked", {"target": target, "model": args.model, "voice_id": args.voice_id,
                                             "credits": credits, "scenes": [sc["key"] for sc in scenes],
                                             "joined": [sc["key"] for sc in joined], "failed": failed,
                                             "takes": takes_sha,
                                             "failed_passages": sorted(p for p, r in results.items() if r["failures"]),
                                             "accepted": {p: r["accepted"]["reason"] for p, r in results.items()
                                                          if r.get("accepted")},
                                             "retime": not args.no_retime,
                                             "skipped_hand_placed": blocked})
    if joined:
        stage = Path(tempfile.mkdtemp(dir=rec.root, prefix=".passages-"))
        try:
            manifests = {}
            for sc in joined:
                ids = [r[0] for r in sc["rows"]]
                seams = passages.seam_lengths(sc["plain"], ids, sc["headings"])
                info = passages.join_passages([work / f"{i}.wav" for i in ids], stage / f"{sc['key']}.wav", seams,
                                              lead_in_s=passages.LEAD_IN_S, tail_s=passages.TAIL_S)
                manifests[sc["key"]] = {
                    "schema": PASSAGES_SCHEMA, "scene": sc["key"], "target": target, "engine": args.engine,
                    "model": args.model, "voice_json_sha256": sha256_file(voice_json), "voice_id": args.voice_id,
                    "voice_name": args.voice_name, "credits": credits, "cps": cps,
                    "retime": "off: the takes were imported as already retimed (--no-retime)" if args.no_retime
                    else "pauses matched to punctuation by position (retime.match_pauses)",
                    "passages": [{"id": pid, "script": f"film/{target}/voice/passages/scripts/{script.name}",
                                  "script_sha256": sha256_file(script),
                                  "take": f"film/{target}/voice/passages/takes/{tk.name}",
                                  "take_sha256": sha256_file(tk), "retimed": f"film/{target}/voice/passages/{pid}.wav",
                                  "retimed_by_import": not args.no_retime,
                                  "retimed_sha256": sha256_file(work / f"{pid}.wav"),
                                  "voicecheck": f"film/{target}/voice/passages/{pid}.voicecheck.json",
                                  "plain": plain,
                                  **({"accepted": results[pid]["accepted"]} if results[pid].get("accepted") else {})}
                                 for (pid, script, tk), plain in zip(sc["rows"], sc["plain"])],
                    "join": info, "wav_sha256": sha256_file(stage / f"{sc['key']}.wav")}
            voice_dir.mkdir(parents=True, exist_ok=True)
            snapshot = (list(rec.data["artifacts"]), list(rec.data["events"]))
            try:
                for sc in joined:
                    k = sc["key"]
                    _write_json(voice_dir / f"{k}.passages.json", manifests[k])
                    os.replace(stage / f"{k}.wav", voice_dir / f"{k}.wav")
                    meta = {"model": args.model, "passages": len(sc["rows"]), "voice_id": args.voice_id}
                    rec.add_artifact("scene_voice", voice_dir / f"{k}.wav", meta)
                    rec.add_artifact("passage_manifest", voice_dir / f"{k}.passages.json", meta)
                rec.event("import", "passages_joined", {"target": target, "engine": args.engine, "model": args.model,
                                                        "voice_id": args.voice_id, "retime": not args.no_retime,
                                                        "scenes": [sc["key"] for sc in joined],
                                                        "passages": sum(len(sc["rows"]) for sc in joined)})
            except BaseException:
                rec.rollback(snapshot)
                raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    n = sum(len(sc["rows"]) for sc in joined)
    if joined:
        print(f"Imported {n} passage take(s) of {len(joined)} scene(s) for {target} ({args.model}, voice "
              f"{args.voice_name}): each " + ("kept as retimed (--no-retime, recorded)" if args.no_retime else "retimed")
              + f" and voicechecked, joined by {round(passages.XF_S * 1000)} ms "
              f"crossfades over room tone with a {passages.LEAD_IN_S:g} s lead-in and a {passages.TAIL_S:g} s tail "
              f"into {voice_dir}/<scene>.wav. Next: {PROG} scene-timing --root {rec.root} --film {int(target[5:])} "
              "--scene <ID> (the measured clause timing for plan-shots)")
    print(f"{credits:g} credits recorded for this run.")
    if blocked:
        print(f"Skipped (a hand-placed wav is never overwritten): {', '.join(blocked)}")
    if held:
        listing = "; ".join(f"{k}: {', '.join(v)}" for k, v in failed.items())
        raise Stop(f"passage(s) {', '.join(held)} failed voicecheck on {MAX_PASSAGE_ATTEMPTS} different takes: "
                   f"{listing}. Those scenes were not joined; no further take is generated",
                   "Stop regenerating and ask the owner: listen to the take and the voicecheck.json values, then "
                   f"either rerun the same import-take call with --accept <passage id>=\"<the owner's reason>\" "
                   "(recorded in the passage manifest) or change the passage's tagged script")
    if failed:
        listing = "; ".join(f"{k}: {', '.join(v)}" for k, v in failed.items())
        raise Stop(f"passage(s) failed voicecheck and are listed for redo: {listing}. Those scenes were not joined",
                   "Regenerate only those passages from the same tagged scripts, download each over its old "
                   "<passage id>.mp3 and rerun the same import-take call with --credits of that regeneration only "
                   f"(the profile {work / 'voicecheck-profile.json'} is reused)")


MAX_PASSAGE_ATTEMPTS = 3   # failed takes of one passage before the tool stops asking for regeneration


def _passage_attempts(rec, target) -> dict:
    """{passage id: {sha256 of each different take that failed voicecheck}} from the passages_checked events."""
    out = {}
    for e in rec.data["events"]:
        d = e["detail"]
        if e["stage"] == "import" and e["result"] == "passages_checked" and d.get("target") == target:
            for pid in d.get("failed_passages") or []:
                if (d.get("takes") or {}).get(pid):
                    out.setdefault(pid, set()).add(d["takes"][pid])
    return out


def cmd_split_passages(args):
    """Write the untagged passage scripts <scene>-p<NN>.txt (15-30 s, cut at sentence or paragraph ends)."""
    rec = _record(args.root)
    plan = _plan(rec)
    target, todo = _take_target(rec, plan, args.target)
    if not target.startswith("film-"):
        raise Stop(f"{target} is a reel: passages are for film scenes", "Pass film-NN")
    out = Path(args.out)
    files = {}
    for key, sc in todo:
        text, _ = _scene_text(sc, plan["language"])
        for n, p in enumerate(passages.split_passages(text, cps=args.cps), 1):
            files[out / f"{key}-p{n:02d}.txt"] = p.strip()
    clash = [p.name for p in files if p.exists()]
    if clash:
        raise Stop(f"{', '.join(clash[:3])} already exist in {out}; tagged scripts are never overwritten",
                   "Pass an empty --out folder")
    out.mkdir(parents=True, exist_ok=True)
    for path, text in files.items():
        path.write_text(text + "\n", encoding="utf-8")
    print(f"Wrote {len(files)} passage script(s) for {target} to {out} (about 15-30 s each at {args.cps:g} "
          f"characters/s). Next: tag each (references/earnalism-voice.md), generate one take per passage, "
          f"import-take {target} ...")


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
        try:
            ledger.settle(args.job_id, units)
        except budget.BudgetExceeded as e:
            raise Stop(f"not settled: {e}. The reservation stays open and the {how} is unfinished",
                       "Hold for the owner: never settle past a cap", code=3)
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


def _film_clip_items(rec, t) -> dict:
    """key -> {"job_id", "item"}: the items of the film's imported film_clips jobs (a later job replaces a key)."""
    found = {}
    for j in _jobs(rec):
        if j["kind"] != "film_clips" or j["target"] != t or not j["imported"] or _ended(j):
            continue
        if j["adopted"]:   # G1: an adoption's items carry the shot they are bound to
            items = _job_json(j).get("items") or []
        else:
            with zipfile.ZipFile(j["inputs_zip"]) as z:
                items = json.loads(z.read("job.json")).get("items") or []
        for item in items:
            found[item["key"]] = {"job_id": j["job_id"], "item": item}
    return found


def _motion_verdicts(rec, files, sid, n) -> dict:
    """I12: the motion gate verdict of each Wan take of a shot, {take key: notes} of those that need review.
    A take whose <key>.motion.json says pass false (a clear stutter or jump) does not enter the film unless its key
    has a reason in picks/gate-overrides.json {"<key>": "<reason>"} (the file the still gate uses). A missing,
    unreadable or edited motion.json (its sha256 differs from the one recorded at import) never passes silently: the
    take is gated again on demand, here, and that verdict is used. needs_review takes are returned so `film --shots`
    prints them and records them in the film's meta, and qc lists them."""
    allowed = {}
    path = rec.root / "picks" / "gate-overrides.json"
    if path.is_file():
        allowed = {k: v for k, v in _json(path).items() if isinstance(v, str) and v.strip()}
    recorded = {a["path"]: a["sha256"] for a in (getattr(rec, "data", None) or {}).get("artifacts", [])
                if a["kind"] == "motion_gate"}
    review = {}
    for f in files:
        mj = f.with_name(f.stem + ".motion.json")
        gate = None
        if mj.is_file() and recorded.get(mj.relative_to(rec.root).as_posix()) in (None, sha256_file(mj)):
            try:
                gate = json.loads(mj.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                gate = None
        if not isinstance(gate, dict) or not isinstance(gate.get("pass"), bool):
            print(f"Motion gate: {f.stem} has no readable recorded motion.json; gating it now.")
            gate = motiongate.gate_clip(f)
        notes = "; ".join(str(x) for x in gate.get("notes") or [])
        if gate["pass"] is False and f.stem not in allowed:
            raise Stop(f"scene {sid} shot {n}: take {f.stem} failed the motion gate ({notes or 'motion gate failed'})",
                       f"Re-seed the shot, pick another take in clip-picks.json, or record why it stands: a reason "
                       f"in {path} ({{\"{f.stem}\": \"<reason>\"}}). Contact sheet: "
                       f"{f.with_name(str(gate.get('contact_sheet') or f.stem + '.contact.png'))}")
        if gate.get("needs_review") or (gate["pass"] is False and f.stem in allowed):
            review[f.stem] = {"scene": sid, "shot": n, "notes": notes or "needs review",
                              **({"override": allowed[f.stem]} if f.stem in allowed else {}),
                              "contact_sheet": f.with_name(str(gate.get("contact_sheet") or f.stem + ".contact.png"))
                              .relative_to(rec.root).as_posix()}
    return review


# ---------------------------------------------------------------- face and eye gate (owner request 28 Nov 2026)
FACE_OVERRIDE_PREFIX = "faces:"   # picks/gate-overrides.json {"faces:<key>": "<reason>"}: a face fail stands


def _face_overrides(rec) -> dict:
    """{key: reason} of picks/gate-overrides.json "faces:<key>" entries. A value is a reason, or {"reason", "sha256"}:
    the sha256 form stands only for the very file the owner looked at (a regenerated take with the same key does not
    inherit it)."""
    path = rec.root / "picks" / "gate-overrides.json"
    if not path.is_file():
        return {}
    out = {}
    for k, v in _json(path).items():
        if not k.startswith(FACE_OVERRIDE_PREFIX):
            continue
        if isinstance(v, str) and v.strip():
            out[k[len(FACE_OVERRIDE_PREFIX):]] = {"reason": v}
        elif isinstance(v, dict) and str(v.get("reason") or "").strip():
            out[k[len(FACE_OVERRIDE_PREFIX):]] = {"reason": v["reason"], "sha256": v.get("sha256")}
    return out


def _override_for(overrides, key, sha):
    o = overrides.get(key)
    if o and (not o.get("sha256") or o["sha256"] == sha):
        return o["reason"]
    return None


def _expects_face(shot) -> bool:
    """The shot plan names a character here (bible_refs), or frames a person (close-up, medium)."""
    framing = str(shot.get("framing") or "").lower()
    return bool(shot.get("bible_refs")) or any(w in framing for w in ("close", "medium"))


def _scene_face_media(rec, t, sid) -> tuple:
    """([{"scene", "shot", "kind": clip|still, "key", "path" (root-relative), "sha256", "expect_face"}], [why a shot's
    media could not be found]) of one scene as it would be assembled now: the Wan takes of each shot's picked chain and
    the operator's picked stills (the stills folder of the last assembly as a fallback)."""
    film_dir = rec.root / "film" / t
    plan = film_dir / "shots" / f"{sid}.json"
    if not plan.is_file():
        return [], [f"scene {sid} has no shot plan {plan.name}"]
    sp = _json(plan)
    picks_path = film_dir / "clip-picks.json"
    picks = _json(picks_path) if picks_path.is_file() else {}
    clip_items = None
    found, missing = [], []
    try:
        picked = _scene_picks(rec, t, sid)
    except Stop as e:
        picked = {}
        missing.append(str(e))

    def entry(n, kind, key, path, shot):
        return {"scene": sid, "shot": n, "kind": kind, "key": key, "path": Path(path).relative_to(rec.root).as_posix(),
                "sha256": sha256_file(path), "expect_face": _expects_face(shot)}
    for shot in sp.get("shots") or []:
        n = shot.get("n")
        if shot.get("motion") == "wan":
            if clip_items is None:
                clip_items = _film_clip_items(rec, t)
            try:
                keys = film.pick_wan_clips([c["item"] for c in clip_items.values()], sid, n, picks)
            except ValueError as e:
                missing.append(f"shot {n}: {e}")
                continue
            for k in keys:
                f = rec.root / "film_clips" / clip_items[k]["job_id"] / "clips" / f"{k}.mp4"
                (found.append(entry(n, "clip", k, f, shot)) if f.is_file()
                 else missing.append(f"shot {n}: clip {f} is missing"))
        elif shot.get("motion") in ("glide", "static"):
            stem = f"{sid}-{n}"
            if stem in picked:
                found.append(entry(n, "still", stem, picked[stem]["path"], shot))
                continue
            still = next((p for p in sorted((film_dir / "stills").glob(f"{stem}.*"))
                          if p.suffix.lower() in film.STILL_EXTS), None) if (film_dir / "stills").is_dir() else None
            (found.append(entry(n, "still", stem, still, shot)) if still else
             missing.append(f"shot {n}: no picked still {stem} in {film_dir / 'stills'} (assemble with film --shots)"))
    return found, missing


def _scene_faces(rec, t, sid, recorded=None) -> dict:
    """Run the face gate over a scene's clips and stills into qc/faces/<scene>/ (cached by sha256) and draw the
    scene's face close-up sheet qc/<scene>-faces.jpg. `recorded`: the media film --shots recorded in the cut's meta
    (I3: qc judges what is in the cut); a recorded file that changed or vanished is `missing`, and a shot whose
    current pick differs from the cut is `stale` (the cut must be rebuilt). Without a record (a cut assembled before
    28 Nov) the current picks are judged and `unrecorded` is set. Returns {"sheet", "items", "flagged", "fails",
    "missing", "stale", "not_judged", "unrecorded", "error"}; a fail is a double or missing pupil without a recorded
    "faces:<key>" override."""
    out = rec.root / "qc" / "faces" / sid
    current, missing = _scene_face_media(rec, t, sid)
    stale = []
    if recorded is not None:
        inputs = list(recorded)
        rec_by, cur_by = {}, {}
        for m in inputs:
            rec_by.setdefault(m["shot"], []).append(m["sha256"])
        for m in current:
            cur_by.setdefault(m["shot"], []).append(m["sha256"])
        for n in sorted(set(rec_by) | set(cur_by)):
            if rec_by.get(n) != cur_by.get(n):
                stale.append(f"shot {n}: the cut has {', '.join(x[:12] for x in rec_by.get(n, [])) or 'nothing'}, the "
                             f"current pick is {', '.join(x[:12] for x in cur_by.get(n, [])) or 'nothing'}")
        missing = [x for x in missing if not x.startswith(f"scene {sid} has no shot plan")] if inputs else missing
    else:
        inputs = current
    overrides = _face_overrides(rec)
    items, flagged, fails, sections, not_judged = {}, [], [], [], []
    if not facegate.available():
        return {"sheet": None, "items": {}, "flagged": [], "fails": [], "missing": missing, "stale": stale,
                "not_judged": [], "unrecorded": recorded is None,
                "error": "OpenCV is not importable: the face gate cannot run"}
    for m in inputs:
        n, kind, key = m["shot"], m["kind"], m["key"]
        path = rec.root / m["path"]
        if not path.is_file() or sha256_file(path) != m["sha256"]:
            missing.append(f"shot {n}: {m['path']} {'changed since the cut was assembled' if path.is_file() else 'is missing'}"
                           " (rebuild the cut with film --shots)")
            continue
        try:   # a still is named by its shot key (<scene>-<n>), a take by its own key
            r = facegate.gate(path, out, key=key, expect_face=m.get("expect_face", False))
        except facegate.Unavailable as e:
            missing.append(f"shot {n}: {e}")
            continue
        verdict = ("fail" if not r["pass"] else "review" if r["needs_review"] else
                   "not judged" if r.get("not_judged") else "pass")
        reason = _override_for(overrides, key, r["sha256"])
        items[key] = {"shot": n, "kind": kind, "verdict": verdict, "sha256": r["sha256"],
                      "judged_fraction": r.get("judged_fraction"), "expect_face": r.get("expect_face"),
                      "face_json": (out / f"{key}.face.json").relative_to(rec.root).as_posix(),
                      "sheet": (out / r["sheet"]).relative_to(rec.root).as_posix() if r.get("sheet") else None,
                      **({"override": reason} if reason else {})}
        for f in r["findings"]:
            flagged.append({"scene": sid, "shot": n, "key": key, "kind": f["kind"], "severity": f["severity"],
                            "frames": f["frames"], "times": f["times"], "detail": f["detail"],
                            **({"override": reason} if reason and f["severity"] == "fail" else {})})
        if not r["pass"] and not reason:
            fails.append(key)
        if r.get("not_judged") or any(f["kind"] == "not_judged" for f in r["findings"]):
            not_judged.append(f"shot {n} {key}")
        if r.get("sheet"):
            sections.append((f"{sid} shot {n} {key} ({kind}): {verdict.upper()}"
                             + (f", judged in {r.get('face_frames', 0)}/{r.get('sampled', 1)} samples"
                                if kind == "clip" else "")
                             + (f" - override: {reason}" if reason and verdict == "fail" else ""),
                             out / r["sheet"]))
    sheet = facegate.scene_sheet(sections, rec.root / "qc" / f"{sid}-faces.jpg") if sections else None
    return {"sheet": sheet.relative_to(rec.root).as_posix() if sheet else None, "items": items, "flagged": flagged,
            "fails": fails, "missing": missing, "stale": stale, "not_judged": not_judged,
            "unrecorded": recorded is None, "error": None}


def _face_lines(sid, res) -> list:
    lines = []
    for f in res["flagged"]:
        where = (f"frames {f['frames'][0]}-{f['frames'][-1]} ({f['times'][0]:.2f}-{f['times'][-1]:.2f} s of the take)"
                 if f["times"] else "still")
        lines.append(f"FACE {f['severity'].upper()} {sid} shot {f['shot']} {f['key']}: {f['kind'].replace('_', ' ')}, "
                     f"{where}; {f['detail']}" + (f" (override: {f['override']})" if f.get("override") else ""))
    return lines


def cmd_facegate(args):
    if not facegate.available():
        raise Stop("OpenCV (opencv-python-headless) is not importable: the face gate cannot run, so nothing passed",
                   "pip install -r skills/earnalism-audiovisual/software/requirements-touchup.txt and rerun")
    media = []
    for a in args.media:
        p = Path(a)
        if p.is_dir():
            media += sorted(x for x in p.iterdir() if x.suffix.lower() in facegate.CLIP_EXTS | facegate.IMAGE_EXTS
                            and not x.name.endswith((".faces.png", ".contact.png", ".mask.png", ".before.png",
                                                     ".after.png", "-depth.png", ".depth.png")))
        elif p.is_file():
            media.append(p)
        else:
            raise Stop(f"{p} does not exist", "Fix the path and rerun")
    if not media:
        raise Stop("no clips or stills given", "Pass clip or still files, or a folder of them")
    out = Path(args.out) if args.out else None
    failed = 0
    for m in media:
        try:
            r = facegate.gate(m, out, reuse=not args.fresh, expect_face=args.expect_face)
        except facegate.Unavailable as e:
            failed += 1
            print(f"NOT RUN {m.name}: {e} (counts as a failure)")
            continue
        failed += not r["pass"]
        print(facegate.summary_line(r) + (f" Sheet: {r['sheet']}" if r.get("sheet") else ""))
    print(f"{len(media)} file(s) gated, {failed} failed. Written beside each file (or in --out): <key>.face.json and "
          "<key>.faces.png; the media are untouched. Thresholds are uncalibrated beyond scene 14. Identity and age "
          "are not measured: look at every sheet.")
    if failed:
        raise Stop(f"{failed} file(s) failed the face gate (or could not be gated)",
                   "Look at each sheet at full size; regenerate the still or take, or record why it stands in "
                   "picks/gate-overrides.json as {\"faces:<key>\": \"<reason>\"}", code=5)


def _shot_face_media(rec, t, sid, shot, asset, scene_picks) -> list:
    """The media film --shots puts on screen for one shot, as qc's face gate will judge it (I3)."""
    n, expect = shot["n"], _expects_face(shot)
    if "clips" in asset:
        return [{"scene": sid, "shot": n, "kind": "clip", "key": f.stem, "path": f.relative_to(rec.root).as_posix(),
                 "sha256": sha256_file(f), "expect_face": expect} for f in asset["clips"]]
    key = f"{sid}-{n}"
    if sid not in scene_picks:
        scene_picks[sid] = _scene_picks(rec, t, sid)
    src = scene_picks[sid].get(key, {}).get("path") or asset["image"]   # the pick itself, not the rebuilt link
    return [{"scene": sid, "shot": n, "kind": "still", "key": key, "path": Path(src).relative_to(rec.root).as_posix(),
             "sha256": sha256_file(asset["image"]), "expect_face": expect}]


def _shot_assets(rec, t, sid, shot, clip_items, picks, stills_dir, depth_maps=None, review=None) -> dict:
    """Inputs of one shot: its imported Wan clip(s), or its picked still (C2: the scene's picks only, linked into
    stills_dir as <scene>-<n>) and, for a layered glide, the depth map made of exactly that still (C1)."""
    n = shot["n"]
    if shot["motion"] == "wan":
        try:
            keys = film.pick_wan_clips([c["item"] for c in clip_items.values()], sid, n, picks)
        except ValueError as e:
            raise Stop(f"scene {sid} shot {n}: {e}", f"Import the film_clips job for it ({PROG} job film_clips) "
                       "or name the take in clip-picks.json")
        files = [rec.root / "film_clips" / clip_items[k]["job_id"] / "clips" / f"{k}.mp4" for k in keys]
        absent = [f for f in files if not f.is_file()]
        if absent:
            raise Stop(f"scene {sid} shot {n}: clip {absent[0]} is missing", f"{PROG} status --root {rec.root}")
        found = _motion_verdicts(rec, files, sid, n)
        if review is not None:
            review.update(found)
        return {"clips": files}
    stem = f"{sid}-{n}"
    still = next((p for p in sorted(Path(stills_dir).iterdir()) if p.stem == stem and p.suffix.lower() in film.STILL_EXTS),
                 None)
    if still is None:
        raise Stop(f"scene {sid} shot {n} has no still {stem}.png in {stills_dir}", next_action(rec.root))
    assets = {"image": still}
    if shot["motion"] == "glide" and not (shot.get("camera") or {}).get("flat"):
        depth = (depth_maps or {}).get((f"{stem}.png", sha256_file(still)))
        if depth is None:
            raise Stop(f"scene {sid} shot {n} (glide) has no depth map of its picked still {stem}: depth maps come from "
                       "an imported film_clips job, which fills its depth_stills in from the scene's picks",
                       f"{PROG} job film_clips --root {rec.root} --film {int(t[5:])} --rates <rates.json> --spec "
                       f"<clips.json with \"scene\": \"{sid}\">, run it and import it (or set the shot flat)")
        assets["depth"] = depth
    return assets


def _adopted_bindings(rec) -> dict:
    """{(adopted stills job id, key): its binding in adoption.json} of every active adopted stills job (I2)."""
    out = {}
    for j in _jobs(rec):
        if j["adopted"] and j["kind"] == "stills" and not _ended(j):
            for key, b in ((_json(j["adoption"]).get("binding") or {}).get("stills") or {}).items():
                out[(j["job_id"], key)] = b
    return out


def _ungated_copy(b) -> bool:
    """A hand copy that no gated job output vouches for (untraced, or only a declared derivation): it has no gate
    verdict of its own, so it enters a film only on a recorded reason (I2)."""
    return bool(b.get("hand_copied")) and str((b.get("gate") or {}).get("why", "")).startswith("hand-copied")


def _release_blocker(job_id, key, b):
    """A still whose licence is not verified (None): a blocking item for release (I2), or None."""
    lic = b.get("licence") or {}
    if lic.get("licence") is not None:
        return None
    src = b.get("hand_copied") or b.get("source") or {}
    return {"key": key, "job_id": job_id, "file": src.get("file"), "sha256": src.get("sha256"),
            "licence": None, "blocker": "licence unverified (provenance untraced): the owner must clear it "
                                        "before any release"}


def _release_blockers(rec) -> list:
    return [x for (jid, key), b in sorted(_adopted_bindings(rec).items()) for x in [_release_blocker(jid, key, b)] if x]


def _cinematic_stills(rec, t, scenes, out) -> tuple:
    """C2: the stills of the cinematic film: for every glide or static shot, the operator's recorded pick of the
    scene's own stills jobs, linked into <film>/stills as <scene>-<n>. A shot with no pick stops the film; nothing
    falls back to an older film's still with the same key."""
    files, info, missing, touched = {}, {}, [], {}
    kinds = {j["job_id"]: j["kind"] for j in _jobs(rec)}
    for sid, sp, _ in scenes:
        picks = _scene_picks(rec, t, sid)
        for shot in _still_shots(sp):
            key = f"{sid}-{shot['n']}"
            if key not in picks:
                missing.append(key)
                continue
            files[key] = picks[key]["path"]
            info[key] = {"job_id": picks[key]["job_id"], "candidate": picks[key]["candidate"],
                         "sha256": picks[key]["sha256"]}
            if kinds.get(picks[key]["job_id"]) == "touchup":   # a repaint has no still-gate verdict of its own
                touched[key] = (sid, _expects_face(shot))
    if missing:
        raise Stop(f"shot(s) {', '.join(missing)} have no picked still of their scene's stills jobs; the film never "
                   "falls back to an older still with the same key",
                   f"Build the scene's stills job (spec \"scene\", one item per glide/static shot key, candidates), "
                   f"review the candidates and {PROG} pick --root {rec.root} --job <job> --choices <json>")
    adopted = _adopted_bindings(rec)
    path = rec.root / "picks" / "gate-overrides.json"
    allowed = {k: v for k, v in (_json(path).items() if path.is_file() else []) if isinstance(v, str) and v.strip()}
    ungated, blockers, overridden = [], [], {}
    for key, inf in info.items():
        b = adopted.get((inf["job_id"], key))
        if b is None:
            continue
        if _ungated_copy(b):
            if key in allowed:
                overridden[key] = allowed[key]
            else:
                ungated.append(key)
        blk = _release_blocker(inf["job_id"], key, b)
        if blk:
            blockers.append(blk)
    for key in touched:   # a picked touch-up stands only on a recorded reason, as an adopted hand copy does
        if key in allowed:
            overridden[key] = allowed[key]
        else:
            ungated.append(key)
    if ungated:
        raise Stop(f"still(s) {', '.join(ungated)} are hand copies or touch-ups with no still-gate verdict of their own "
                   "(untraced, a declared derivation, or a local repaint): they never enter the film ungated",
                   f"Look at each at full size and record why it stands (quote the source's gate): a reason in {path} "
                   + "{" + ", ".join(f'"{k}": "<reason>"' for k in ungated) + "}, or pick a gated job's candidate")
    face_fails = []
    if touched:   # the face and eye gate judges the touched file itself, now; a fail stands only on a "faces:" reason
        if not facegate.available():
            raise Stop(f"touched still(s) {', '.join(touched)} cannot be face-gated: OpenCV is not importable",
                       "pip install -r skills/earnalism-audiovisual/software/requirements-touchup.txt and rerun")
        face_over = _face_overrides(rec)
        for key, (sid, expect) in touched.items():
            fdir = rec.root / "qc" / "faces" / sid
            try:
                r = facegate.gate(files[key], fdir, key=key, expect_face=expect)
            except facegate.Unavailable as e:
                raise Stop(f"touched still {key} could not be face-gated: {e}", "Fix the file and rerun") from None
            reason = _override_for(face_over, key, r["sha256"])
            info[key]["faces"] = {"verdict": ("fail" if not r["pass"] else "review" if r["needs_review"] else
                                              "not judged" if r.get("not_judged") else "pass"),
                                  "sha256": r["sha256"], "expect_face": bool(expect),
                                  "face_json": (fdir / f"{key}.face.json").relative_to(rec.root).as_posix(),
                                  **({"override": reason} if reason else {})}
            if not r["pass"] and not reason:
                why = "; ".join(str(f["detail"]) for f in r["findings"] if f["severity"] == "fail")
                face_fails.append(f"{key} ({why or 'face gate failed'})")
    if face_fails:
        raise Stop("touched still(s) fail the face and eye gate: " + " | ".join(face_fails),
                   f"Look at qc/faces/<scene>/<key>.faces.png at full size; redo the touch-up, or record why it stands "
                   f"in {path} as {{\"faces:<key>\": \"<reason>\"}}")
    merged = out / "stills"
    if merged.exists():
        shutil.rmtree(merged)
    merged.mkdir(parents=True)
    for key, src in files.items():
        dst = merged / (key + src.suffix)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    extra = {**({"gate_overrides": overridden} if overridden else {}),
             **({"release_blockers": blockers} if blockers else {})}
    for blk in blockers:
        print(f"RELEASE BLOCKER {blk['key']}: {blk['blocker']} ({blk['job_id']}, sha256 {str(blk['sha256'])[:12]}...)")
    return merged, {"picks": info, **extra}


def _film_shots(args, rec, plan, t, scs):
    """cinematic film: every scene's approved shot plan, rendered shot by shot (glide, Wan, static; cached),
    joined at 24 fps with the scene mixes, a captions track, the title and credit cards, the logo and the END."""
    film_dir = rec.root / "film" / t
    lang = plan["language"]
    for need in ("title", "author", "narrator"):
        if not getattr(args, need):
            raise Stop(f"--shots needs --{need} (title card, credits and the AI disclosure)", f"Rerun with --{need}")
    only = getattr(args, "scene", None)   # G6: one scene's own cut, for its review; the whole film is untouched
    if only:
        scs = [sc for sc in scs if sc["scene_id"] == only]
        if not scs:
            raise Stop(f"scene {only} is not in film {args.film}", f"{PROG} status --root {rec.root}")
    stem = f"{t}-{only}" if only else t
    scenes = []
    for sc in scs:
        sid = sc["scene_id"]
        try:
            sp = shotplan.require_approved(film_dir, sid)
        except shotplan.NotApproved as e:
            raise Stop(str(e), f"{PROG} plan-shots --root {rec.root} --film {args.film} --scene {sid}")
        scene_mix = film_dir / "audio" / f"{sid}.mix.wav"
        if not scene_mix.is_file():
            raise Stop(f"scene {sid} has no mix {scene_mix}", f"{PROG} cue --root {rec.root} --film {args.film} --scene {sid} ...")
        if abs(film._duration(scene_mix) - sp["seconds"]) > 0.15:
            raise Stop(f"the mix of scene {sid} is {film._duration(scene_mix):.2f} s but its shot plan is {sp['seconds']:.2f} s",
                       f"Remix the scene with {PROG} cue")
        try:
            film.check_shot_coverage(sid, sp["shots"], sp["seconds"])
        except ValueError as e:
            raise Stop(str(e), f"Re-plan the scene: {PROG} plan-shots --root {rec.root} --film {args.film} --scene {sid}")
        scenes.append((sid, sp, scene_mix))
    scene_fr = film.scene_frames([sp["seconds"] for _, sp, _ in scenes])
    picks_path = film_dir / "clip-picks.json"
    picks = _json(picks_path) if picks_path.is_file() else {}
    clip_items = _film_clip_items(rec, t)
    stills_dir, stills_info = _cinematic_stills(rec, t, scenes, film_dir)
    depth_maps, review = _depth_maps(rec, t), {}
    shots, assets, units, timing, mixes, at = [], [], [], [], [], 0.0
    caption_top = []   # film-timeline spans of shots whose burned captions sit at the top (shot plan "caption")
    starts = [sum(scene_fr[:k]) / film.SHOT_FPS for k in range(len(scenes))]   # frame-aligned scene starts
    face_media, scene_picks = [], {}   # I3: the exact media of every shot, recorded for qc's face gate
    for (sid, sp, scene_mix), at in zip(scenes, starts):
        for i, c in enumerate(_scene_clauses(film_dir, sid), 1):
            key = f"{sid}-{i:03d}"
            units.append({"unit_key": key, "text": c["text"]})
            timing.append({"unit_key": key, "start": round(at + c["start"], 3), "end": round(at + c["end"], 3)})
        for shot in sp["shots"]:
            shots.append({**shot, "scene_id": sid})
            if shot.get("caption") == "top":
                caption_top.append((round(film.TITLE_S + at + shot["start"], 3), round(film.TITLE_S + at + shot["end"], 3)))
            assets.append(_shot_assets(rec, t, sid, shot, clip_items, picks, stills_dir, depth_maps, review))
            face_media += _shot_face_media(rec, t, sid, shot, assets[-1], scene_picks)
        mixes.append(scene_mix)
    durations = [s["end"] - s["start"] for s in shots]
    trans = [film.DISSOLVE_S if s["transition_in"] == "dissolve" else 0.0 for s in shots[1:]]
    lens, overlaps = film.edit_lengths(durations, trans)
    cache = film_dir / "shots-cache"
    clips = []
    for shot, a, ln in zip(shots, assets, lens):
        try:
            clips.append(film.render_shot({**shot, "seconds": ln}, a, cache))
        except ValueError as e:
            raise Stop(f"scene {shot['scene_id']} shot {shot['n']}: {e}", "Fix the shot plan's camera or the inputs")
    mixed = film_dir / "audio" / (f"{stem}.film-mix.wav" if only else "film.mix.wav")
    film.join_scene_mixes(mixes, scene_fr, mixed)   # each mix held to its frame-aligned scene length
    try:
        vtt = film_dir / f"{stem}.vtt"
        vtt.write_text(film.captions(timing, units, lang, offset=film.TITLE_S), encoding="utf-8")
        srt = film_dir / f"{stem}.srt"       # bundle-film reads the "subtitles" artifact as SRT
        srt.write_text(film.captions(timing, units, lang, offset=film.TITLE_S, fmt="srt"), encoding="utf-8")
    except ValueError as e:
        raise Stop(f"captions: {e}", "Re-time the narration or split the clause in the planner input")
    fonts = Path(args.fonts) if args.fonts else None
    card = film.cards(args.title, args.author, args.narrator, film_dir / "cards", fonts)
    common = dict(logo=Path(args.logo), end_card=Path(args.end_card), title_card=Path(card["cards"]["title"]),
                  credits_card=Path(card["cards"]["credits"]), captions_vtt=vtt, fonts_dir=fonts,
                  caption_top=caption_top)
    out = film_dir / f"{stem}.mp4"
    info = film.assemble_shots(clips, lens, overlaps, mixed, out, **common)
    burned = None
    if args.burn:
        burned = film_dir / f"{stem}.burned.mp4"
        film.assemble_shots(clips, lens, overlaps, mixed, burned, burn=True, **common)
    m = mix.measure(out)
    if m["true_peak"] > film.SHOT_TP_MAX or abs(m["lufs"] - FILM_LUFS) > LUFS_TOL:   # R10
        raise Stop(f"QC failure: the film measures {m['lufs']:.1f} LUFS and {m['true_peak']:.1f} dBTP; the gate "
                   f"is {FILM_LUFS:g} +-{LUFS_TOL:g} LUFS and at most {film.SHOT_TP_MAX} dBTP",
                   "Re-balance the scene mixes (cue) and rerun film", code=5)
    meta = {"target": t, "mode": "shots", "lufs": m["lufs"], "true_peak": m["true_peak"], "stills": stills_info,
            "motion_review": review, "face_media": face_media,
            "scenes": [s for s, _, _ in scenes], "shots": len(shots), "cards_sha256": sha256_file(film_dir / "cards" / "cards.json"),
            "captions_sha256": sha256_file(vtt), **({"caption_top": caption_top} if caption_top else {}), **info}
    if only:   # a scene's own cut: its own artifact kinds, so the whole film's record (and bundle-film) never sees it
        scene_meta = {"target": t, "scene": only}
        rec.add_artifact("scene_mix", mixed, scene_meta)
        rec.add_artifact("scene_captions", vtt, scene_meta)
        rec.add_artifact("scene_subtitles", srt, scene_meta)
        rec.add_artifact("scene_film", out, {**meta, "scene": only})
        rec.event("film", "scene_assembled", {"target": t, "scene": only, "duration": info["duration"], "mode": "shots",
                                              **({"burned": str(burned)} if burned else {})})
    else:
        rec.add_artifact("mix", mixed, {"target": t})
        rec.add_artifact("captions", vtt, {"target": t})
        rec.add_artifact("subtitles", srt, {"target": t})
        rec.add_artifact("film", out, meta)
        rec.event("film", "assembled", {"target": t, "duration": info["duration"], "mode": "shots",
                                        **({"burned": str(burned)} if burned else {})})
    print(f"Assembled {out}: {info['duration']:.1f} s, {len(shots)} shots at 24 fps, {m['lufs']:.1f} LUFS, "
          f"TP {m['true_peak']:.1f} dBTP, captions {vtt.name}" + (f", burned-in rendition {burned.name}" if burned else "") + ".")
    for key, r in sorted(review.items()):
        print(f"MOTION REVIEW {r['scene']} shot {r['shot']} take {key}: {r['notes']}"
              + (f" (passed on the recorded override: {r['override']})" if r.get("override") else "")
              + f"; look at {r['contact_sheet']} before the owner sees the cut.")
    for sid, _, _ in scenes:   # the minute anomaly review: the scene's face close-up sheet, qc enforces the gate
        try:
            faces = _scene_faces(rec, t, sid, [m for m in face_media if m["scene"] == sid])
        except Stop as e:      # the cut is already recorded: a face-gate lookup must not turn it into a failure
            print(f"FACE GATE NOT RUN for scene {sid}: {e}; qc will run it")
            continue
        for line in _face_lines(sid, faces):
            print(line)
        if faces["error"] or faces["missing"]:
            print(f"FACE GATE NOT RUN for part of scene {sid}: " + "; ".join(([faces["error"]] if faces["error"] else [])
                                                                       + faces["missing"]))
        print(f"FACE SHEET {sid}: " + (f"{rec.root / faces['sheet']}" if faces["sheet"] else "no face found in any shot")
              + " (face crops x3, flagged frames in red). Go through the minute anomaly checklist (SKILL.md) on it "
              "before the owner sees the cut; qc fails a double or missing pupil.")
        for x in faces["not_judged"]:
            print(f"FACE NOT JUDGED {sid} {x}: no eye on a face was found; look at it on the sheet")


def cmd_film(args):
    rec = _record(args.root)
    plan = _plan(rec)
    t = _film_target(args.film)
    films = plan["plan"]["films"]
    if not 1 <= args.film <= len(films):
        raise Stop(f"film {args.film} is not in the plan", f"{PROG} status --root {rec.root}")
    if args.shots:
        return _film_shots(args, rec, plan, t, films[args.film - 1]["scenes"])
    if args.scene:
        raise Stop("--scene assembles one scene of a cinematic film", "Add --shots (and --title, --author, --narrator)")
    planned = sorted(p.name for p in (rec.root / "film" / t / "shots").glob("*.input.json"))
    if planned:   # C3: the cinematic film is assembled shot by shot and gated by qc's film gates
        raise Stop(f"{t} has shot plans ({', '.join(planned[:3])}{' ...' if len(planned) > 3 else ''}): it is a "
                   "cinematic film, and the pre-cinematic assembly would skip its shots and qc's film gates",
                   f"{PROG} film --root {rec.root} --film {args.film} --shots --logo <lockup> --end-card <END> "
                   "--title <T> --author <A> --narrator <V>")
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


def _job_gated(rec, job_id) -> bool:
    """Was the job's gate intended? The imported manifest's MODEL_INFO carries "gate" (recorded before the
    gate runs, so a gate that was skipped or failed still shows it), and every artifact of the job keeps it
    in its meta. Not inferred from the gate.json files on disk."""
    return any(isinstance((a["meta"].get("model") or {}).get("gate"), dict)
               for a in rec.data["artifacts"] if a["meta"].get("job_id") == job_id)


def _gate_of(path: Path, gated: bool):
    """The still's gate verdict (<stem>.gate.json beside it): (gate dict | None, level, why) with level None
    (nothing to say), "review" (needs review, advisory until the title is calibrated) or "fail" (a certain
    fail: pass false and needs_review false). A gated job's missing or unreadable gate.json is "review"; a job
    that was never gated has no verdicts and blocks nothing."""
    gate_path = path.with_name(path.stem + ".gate.json")
    if not gate_path.is_file():
        return (None, "review", "no gate result for this candidate although the job's gate was intended "
                "(it was skipped, ran out of time or failed)") if gated else (None, None, None)
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if not isinstance(gate, dict) or not isinstance(gate.get("pass"), bool):
            raise ValueError("not a gate verdict")
    except (OSError, ValueError):
        return None, "review", "its gate.json is unreadable"
    if gate["pass"] is True and not gate.get("needs_review"):
        return gate, None, None
    why = "; ".join(str(n) for n in gate.get("notes") or []) or ", ".join(gate.get("anachronisms") or []) or "failed"
    if gate.get("needs_review"):
        return gate, "review", "gate needs review: " + why
    return gate, "fail", "gate failed: " + why


def _reasons(items, flag):
    """{key: reason} from repeated KEY=reason flags."""
    out = {}
    for item in items or []:
        key, sep, reason = item.partition("=")
        if not sep or not key.strip() or not reason.strip():
            raise Stop(f"{flag} needs KEY=reason (a still key and why), not {item!r}",
                       f"e.g. {flag} f01s014-12=\"owner viewed it: the cylinder is a period lamp\"")
        out[key.strip()] = reason.strip()
    return out


def _latest_pick_overrides(rec, job_id) -> dict:
    picks = _artifacts(rec, "stills_pick", job_id=job_id)
    return dict(picks[-1]["meta"].get("overrides") or {}) if picks else {}


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
    picked, overrides, advisories, blocked = {}, {}, {}, []
    review_over, fail_over = _reasons(args.override, "--override"), _reasons(args.override_fail, "--override-fail")
    for key in list(review_over) + list(fail_over):
        if key not in choices:
            raise Stop(f"override names {key!r}, which is not in the choices file",
                       f"Name only keys you are picking: {', '.join(sorted(choices))}")
    gated = _job_gated(rec, args.job)
    calibrated = (rec.root / "gate-calibration.json").is_file()
    for key, n in choices.items():
        if key not in cands:
            raise Stop(f"{key!r} has no candidates in {args.job}",
                       f"Use one of: {', '.join(sorted(cands))}")
        if isinstance(n, bool) or not isinstance(n, int) or n not in cands[key]:
            raise Stop(f"{key!r} candidate {n!r} is not one of {args.job}'s "
                       f"{', '.join(str(c) for c in sorted(cands[key]))}",
                       f"Fix {args.choices} and rerun pick")
        path = cands[key][n]
        gate, level, why = _gate_of(path, gated)
        if level:
            record = {"candidate": n, "level": level, "why": why,
                      "gate": None if gate is None else {k: gate.get(k) for k in (
                          "pass", "needs_review", "anachronisms", "hands_detached", "eyes",
                          "anchor_similarity", "notes")}}
            if level == "fail":
                if key in fail_over:
                    overrides[key] = {**record, "reason": fail_over[key]}
                else:
                    blocked.append(f"{key} c{n}: {why} (certain fail: --override-fail {key}=\"<reason>\")")
            elif calibrated:
                if key in review_over:
                    overrides[key] = {**record, "reason": review_over[key]}
                else:
                    blocked.append(f"{key} c{n}: {why} (--override {key}=\"<reason>\")")
            else:  # no gate-calibration.json yet: advisory, warned and recorded, never blocking
                advisories[key] = {"candidate": n, "why": why}
        picked[key] = {"candidate": n, "file": path.relative_to(rec.root).as_posix(),
                       "sha256": sha256_file(path)}
    if blocked:
        raise Stop("the gate does not pass: " + " | ".join(blocked),
                   "Pick a candidate whose gate passed, or look at it yourself and rerun with the "
                   "per-key override named above (the reason is recorded in the pick)")
    version = len(_artifacts(rec, "stills_pick", job_id=args.job)) + 1
    extra = {**({"overrides": overrides} if overrides else {}), **({"advisories": advisories} if advisories else {})}
    path = _write_json(rec.root / "picks" / f"{args.job}.pick-{version}.json",
                       {"job_id": args.job, "choices": picked, **extra})
    rec.add_artifact("stills_pick", path, {"job_id": args.job, "choices": picked,
                                           "version": version, **extra})
    rec.event("pick", "recorded", {"job_id": args.job, "version": version,
                                   "choices": {k: v["candidate"] for k, v in picked.items()},
                                   **({"overrides": {k: v["reason"] for k, v in overrides.items()}}
                                      if overrides else {}),
                                   **({"advisories": {k: v["why"] for k, v in advisories.items()}}
                                      if advisories else {})})
    for key, adv in sorted(advisories.items()):
        print(f"WARNING (advisory until {rec.root.name}/gate-calibration.json exists): {key} c{adv['candidate']}: "
              f"{adv['why']}")
    print(f"Picked {len(picked)} still(s) of {args.job}: "
          + ", ".join(f"{k} -> c{v['candidate']}" for k, v in sorted(picked.items()))
          + ". The film uses only these candidates; a later pick replaces this one.")


def _touchup_items(rec, t, spec) -> list:
    """Validate a touchup spec against the record: [(key, job, kind, name, path, sha256, ops, licence)]; the
    licence is the source still's verified model licence (I2: a derivation inherits only from a verified source),
    else None."""
    sources = {j["job_id"]: j["kind"] for j in _jobs(rec) if j["kind"] in ("stills", "retouch")
               and j["target"] == t and j["imported"] and not _ended(j)}
    recorded = {a["path"]: a["sha256"] for a in rec.data["artifacts"]
                if a["kind"] in ("stills", "retouch") and a["meta"].get("job_id") in sources}
    repos = {a["path"]: (a["meta"].get("model") or {}).get("repo") for a in rec.data["artifacts"]
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
        repo = repos.get(rel)
        lic = {"model": repo, "licence": adopt.MODEL_LICENCES[repo]} if repo in adopt.MODEL_LICENCES else None
        out.append((key, job, kind, name, path, digest, s.get("ops"), lic))
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
    sid = spec.get("scene")   # a scene-bound touch-up: its pick is the shot's still (as a clip-touchup is adopted)
    if sid is not None:
        if not isinstance(sid, str) or not sid:
            raise Stop("touchup \"scene\" must be a scene id", "Fix the spec")
        try:   # R11: a scene-bound still enters only the approved paper edit
            shotplan.require_approved(rec.root / "film" / t, sid)
        except shotplan.NotApproved as e:
            raise Stop(f"touchup not made: {e}",
                       f"{PROG} plan-shots --root {rec.root} --film {int(t[5:])} --scene {sid} (approve it)")
        for key, job, kind, name, *_, lic in items:
            if key.rpartition("-")[0] != sid:   # the rule _scene_picks binds by
                raise Stop(f"touchup key {key!r} is not a key of scene {sid}", "Fix the spec")
            if lic is None:   # I2: a derivation inherits a licence only from a verified source
                raise Stop(f"touchup {key!r}: the model licence of {kind}/{job}/{name} is not on record (an unverified "
                           f"source), so its touch-up cannot be bound to scene {sid}",
                           "Touch up a still whose model licence is recorded (an imported stills or retouch job)")
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
        for key, job, kind, name, path, digest, ops, lic in items:
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
                         "licence": lic, "candidate": f"touchup/{job_id}/{key}--c1.png",
                         "candidate_sha256": sha256_file(stage / "out" / f"{key}--c1.png"),
                         "mask": f"touchup/{job_id}/{key}--mask.png",
                         "mask_sha256": sha256_file(stage / "out" / f"{key}--mask.png")})
        _write_json(stage / "job" / "touchup.json", spec)
        manifest = {"schema": TOUCHUP_SCHEMA, "job_id": job_id, "target": t, "kind": "touchup",
                    **({"scene": sid} if sid else {}),
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
                                        "engine": "opencv", **({"scene": sid} if sid else {})})
        arts = []
        for r in rows:
            src = {"key": r["key"], "source": r["source"], "source_sha256": r["source_sha256"]}
            # model provenance of the verified source still (I2); no "gate": a touch-up has no gate verdict of its own
            prov = {"model": {"repo": r["licence"]["model"]}} if r["licence"] else {}
            arts.append(rec.add_artifact("touchup", rec.root / r["candidate"],
                                         {**meta, **src, **prov, "ops": r["ops"]}))
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
          f"full size, then {PROG} pick --root {rec.root} --job {job_id} --choices <json>"
          + (f" (bound to scene {sid}: the pick is that shot's still)." if sid else "."))
    for r in rows:
        if r["licence"]:
            print(f"WARNING {r['key']}: licence {r['licence']['licence']} ({r['licence']['model']}) inherited from "
                  f"{r['source']} (verified) by this touch-up (OpenCV, no model); it has no still-gate verdict of its "
                  "own: film --shots refuses it until picks/gate-overrides.json holds a reason for its key (quote the "
                  "source's gate), and face-gates the touched file (a fail needs a \"faces:<key>\" reason).")
        else:
            print(f"WARNING {r['key']}: the model licence of {r['source']} is not on record (an unverified source): "
                  "this touch-up cannot be bound to a scene or adopted.")


CLIP_TOUCHUP_SCHEMA = cliptouch.SCHEMA


def _clip_touchup_source(rec, key, src):
    """(job row, artifact, path, licence) of the clip an item touches up: a recorded Wan clip of this record (a
    film_clips job, an adoption, or an earlier clip touch-up), verified against the sha256 recorded with it."""
    if not isinstance(src, dict) or not src.get("job") or not src.get("file"):
        raise Stop(f"clip-touchup {key!r}: source needs {{\"job\", \"file\"}}", "Fix the spec")
    row = next((j for j in _jobs(rec) if j["job_id"] == src["job"]), None)
    if row is None or not row["imported"] or _ended(row) or row["kind"] not in ("film_clips", "clip_touchup"):
        raise Stop(f"clip-touchup {key!r}: {src['job']} is not an imported film_clips or clip_touchup job of this "
                   "record", "Fix the spec")
    art = next((a for a in rec.data["artifacts"] if a["kind"] in ("film_clips", "clip_touchup")
                and a["meta"].get("job_id") == src["job"] and Path(a["path"]).name == src["file"]), None)
    if art is None or src["file"] != f"{key}.mp4":
        raise Stop(f"clip-touchup {key!r}: {src['file']} is not the recorded clip {key}.mp4 of {src['job']}",
                   "Fix the spec")
    path = rec.root / art["path"]
    if not path.is_file() or sha256_file(path) != art["sha256"]:
        raise Stop(f"clip-touchup {key!r}: {art['path']} is missing or differs from its recorded sha256",
                   f"{PROG} status --root {rec.root}")
    lic = None
    if row["adopted"]:
        for b in ((_json(row["adoption"]).get("binding") or {}).get("clips") or {}).values():
            if any(tk.get("key") == key for tk in b.get("takes") or []):
                lic = b.get("licence")
    elif row["kind"] == "clip_touchup":
        lic = next((it.get("licence") for it in _json(row["manifest"]).get("items") or [] if it.get("key") == key), None)
    else:
        repo = ((art["meta"].get("model") or {}).get("repo"))
        if repo in adopt.MODEL_LICENCES:
            lic = {"model": repo, "licence": adopt.MODEL_LICENCES[repo]}
    if not lic or lic.get("model") not in adopt.MODEL_LICENCES:
        raise Stop(f"clip-touchup {key!r}: the model licence of {src['job']}/{src['file']} is not on record",
                   "Touch up only a clip whose model licence is recorded")
    item = next((it for it in _job_json(row).get("items") or [] if it.get("key") == key), None)
    return row, art, path, lic, item


def cmd_clip_touchup(args):
    """V1: remove a small fixed defect from imported Wan clips (OpenCV, local, no model, 0 CU) into NEW clip files,
    filed as an imported clip_touchup job (sha256 of source and output, the mask, the fill, the reason and the motion
    gate of the touched clip). `adopt` then binds the touched clip to its shot ("clips": {"<n>": {"job": <this job>,
    "takes": [<key>]}}), as a touched still is adopted."""
    rec = _record(args.root)
    t = _film_target(args.film)
    spec = _json(args.spec)
    job_id = args.job_id
    if not SLUG.fullmatch(job_id or "") or any(j["job_id"] == job_id for j in _jobs(rec)):
        raise Stop(f"job id {job_id!r} is not new or not lowercase letters, digits and hyphens", "Pass a new --job-id")
    items = spec.get("items") if isinstance(spec, dict) else None
    if not isinstance(items, list) or not items:
        raise Stop("the clip-touchup spec needs items: [{key, reason, source: {job, file}, mask, fill, mode}]",
                   "Fix the spec")
    sid = spec.get("scene")
    dest, job_dest = rec.root / "clip_touchup" / job_id, rec.root / "jobs" / job_id
    if dest.exists() or job_dest.exists():
        raise Stop(f"{dest} or {job_dest} already exists", "Pass a new --job-id")
    try:
        version = cliptouch.opencv_version()
    except ValueError as e:
        raise Stop(str(e), "pip install -r skills/earnalism-audiovisual/software/requirements-touchup.txt")
    seen, rows, sources = set(), [], []
    for it in items:
        key = it.get("key") if isinstance(it, dict) else None
        if not isinstance(key, str) or not SLUG.fullmatch(key) or key in seen:
            raise Stop(f"clip-touchup key {key!r} is not a clip key, or appears twice", "Fix the spec")
        if sid and not key.startswith(sid + "-"):
            raise Stop(f"clip-touchup key {key!r} is not a key of scene {sid}", "Fix the spec")
        if not str(it.get("reason") or "").strip():
            raise Stop(f"clip-touchup {key!r} needs the operator's \"reason\"", "Fix the spec")
        seen.add(key)
        sources.append((it, *_clip_touchup_source(rec, key, it.get("source"))))
    stage = Path(tempfile.mkdtemp(dir=rec.root, prefix=".cliptouch-"))
    try:
        (stage / "out").mkdir()
        (stage / "job").mkdir()
        for it, row, art, path, lic, item in sources:
            key = it["key"]
            src_sha = sha256_file(path)
            try:
                meas = cliptouch.apply_clip(path, {k: it[k] for k in ("mask", "fill", "mode") if k in it},
                                            stage / "out" / f"{key}.mp4", stage / "out")
            except (ValueError, subprocess.CalledProcessError) as e:
                raise Stop(f"clip-touchup {key!r}: {e}", "Fix the item's mask, fill or mode") from None
            if sha256_file(path) != src_sha:
                raise Stop(f"clip-touchup {key!r}: the source clip changed while it was read", "Rerun")
            gate = motiongate.gate_clip(stage / "out" / f"{key}.mp4")
            out_sha = sha256_file(stage / "out" / f"{key}.mp4")
            rows.append({"key": key, "reason": it["reason"].strip(), "source_job": row["job_id"],
                         "source": art["path"], "source_sha256": src_sha, "licence": lic,
                         "mask": it["mask"], "fill": it["fill"], "mode": it.get("mode", "plate"),
                         "output": f"clip_touchup/{job_id}/{key}.mp4", "output_sha256": out_sha,
                         "mask_png": f"clip_touchup/{job_id}/{key}.mask.png",
                         "mask_png_sha256": sha256_file(stage / "out" / f"{key}.mask.png"),
                         "measured": meas,
                         "motion_gate": {x: gate.get(x) for x in ("pass", "needs_review", "notes")},
                         "item": {**{k: v for k, v in (item or {"key": key}).items()
                                     if k not in ("prompt", "negative_prompt")}, "key": key}})
        _write_json(stage / "job" / "clip-touchup.json", spec)
        manifest = {"schema": CLIP_TOUCHUP_SCHEMA, "job_id": job_id, "target": t, "kind": "clip_touchup",
                    **({"scene": sid} if sid else {}), "engine": "opencv", "opencv": version,
                    "method": "eav.cliptouch.apply_clip", "spent_cu": 0,
                    "spec_sha256": sha256_file(stage / "job" / "clip-touchup.json"), "items": rows,
                    "job": {"items": [r["item"] for r in rows]}}
        _write_json(stage / "job" / "clip-touchup-manifest.json", manifest)
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
        meta = {"job_id": job_id, "job_kind": "clip_touchup", "engine": "opencv", "opencv": version}
        rec.add_artifact(TOUCHUP_JOB, job_dest / "clip-touchup-manifest.json",
                         {**meta, "forecast_units": 0.0, "manifest": f"jobs/{job_id}/clip-touchup-manifest.json"})
        rec.add_artifact("clip_touchup_spec", job_dest / "clip-touchup.json", meta)
        rec.event("cli", "job_target", {"job_id": job_id, "target": t, "kind": "clip_touchup", "engine": "opencv",
                                        **({"scene": sid} if sid else {})})
        arts = []
        for r in rows:
            src = {"key": r["key"], "source": r["source"], "source_sha256": r["source_sha256"],
                   "model": {"repo": r["licence"]["model"]}}
            arts.append(rec.add_artifact("clip_touchup", rec.root / r["output"], {**meta, **src}))
            if arts[-1]["sha256"] != r["output_sha256"]:
                raise Stop(f"{r['output']} changed while filing", "Rerun clip-touchup with a new --job-id")
            rec.add_artifact("clip_touchup_mask", rec.root / r["mask_png"], {**meta, "key": r["key"]})
            rec.add_artifact("motion_gate", dest / f"{r['key']}.motion.json", {**meta, "clip": f"{r['key']}.mp4"})
        rec.event("import", "accepted", {"job_id": job_id, "kind": "clip_touchup", "actual_units": 0,
                                         "engine": "opencv", "opencv": version,
                                         "manifest_sha256": sha256_file(job_dest / "clip-touchup-manifest.json"),
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
    for r in rows:
        g, m_ = r["motion_gate"], r["measured"]
        print(f"Touched up clip {r['key']} as job {job_id} (OpenCV {version}, 0 CU): mask {m_['mask_pixels']} px in "
              f"{m_['mask_bbox']}, outside the mask PSNR {m_['outside_mask']['psnr_db']} dB, motion gate "
              f"{'pass' if g['pass'] else 'FAIL'}{' (needs review)' if g['needs_review'] else ''}. Source "
              f"{r['source']} unchanged (sha256 {r['source_sha256'][:12]}...), output sha256 {r['output_sha256'][:12]}...")
    print(f"Look at clip_touchup/{job_id}/<key>.before.png, .after.png and .mask.png at full size; then adopt the "
          f"touched clip: \"clips\": {{\"<shot>\": {{\"job\": \"{job_id}\", \"takes\": [\"<key>\"]}}}}.")
    return 0


def _refuse_gate_fails(rec, files, jobs, base):
    """A still whose gate.json is a certain fail (pass false, needs_review false) does not enter the film
    unless an override reason is recorded: in the pick that chose it (--override-fail) or, for a single image,
    in picks/gate-overrides.json {"<key>": "<reason>"}. needs_review stays advisory."""
    allowed = {}
    path = rec.root / "picks" / "gate-overrides.json"
    if path.is_file():
        allowed.update({k: v for k, v in _json(path).items() if isinstance(v, str) and v.strip()})
    for job, _, cands in jobs[base + 1:]:
        if cands:
            allowed.update({k: v.get("reason") for k, v in _latest_pick_overrides(rec, job["job_id"]).items()
                            if v.get("level") == "fail" and v.get("reason")})
    blocked = []
    for key, src in files.items():
        gate_path = src.with_name(src.stem + ".gate.json")
        if not gate_path.is_file():
            continue
        try:
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(gate, dict) and gate.get("pass") is False and not gate.get("needs_review") \
                and key not in allowed:
            blocked.append(f"{key} ({'; '.join(str(n) for n in gate.get('notes') or []) or 'gate failed'})")
    if blocked:
        raise Stop("the film's stills include a certain gate fail: " + " | ".join(sorted(blocked)),
                   f"Redo the still, pick another candidate, or record why it stands: --override-fail on "
                   f"{PROG} pick, or a reason in {rec.root / 'picks' / 'gate-overrides.json'} "
                   "({\"<key>\": \"<reason>\"})")


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
    _refuse_gate_fails(rec, files, jobs, base)
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
        elif a["kind"] == "scene_film":   # G6: a scene's own cut is checked with the same film gates
            latest[f"{a['meta']['target']}/{a['meta']['scene']}"] = a
    if not latest:
        raise Stop("nothing assembled yet", next_action(rec.root))
    out = rec.root / "qc"
    out.mkdir(exist_ok=True)
    report = {"advisory_only": ["contact sheets need a human/visual check"],
              "listening": "unassessed until the owner reviews the package", "items": {}}
    failed = []
    for target, a in sorted(latest.items()):
        video = rec.root / a["path"]
        m = mix.measure(video)
        # C1: one flat file per target ("film-01/f01s014" -> "film-01--f01s014"; "--" never occurs in a film or reel
        # target), so a scene cut and the whole film never share or nest an output path
        sheet_path = out / f"{target.replace('/', '--')}-contact.jpg"
        sheet_path.parent.mkdir(parents=True, exist_ok=True)
        sheet = qc.contact_sheet(video, sheet_path)
        lufs = REEL_LUFS if a["kind"] == "reel" else FILM_LUFS
        shots_film = a["kind"] in ("film", "scene_film") and a["meta"].get("mode") == "shots"   # R10: -1.5 dBTP
        checks = {"loudness": abs(m["lufs"] - lufs) <= LUFS_TOL,
                  "true_peak": m["true_peak"] <= (film.SHOT_TP_MAX if shots_film else TP_MAX)}
        item = {"sha256": sha256_file(video), **m, "contact_sheet": sheet.name}
        blockers = ((a["meta"].get("stills") or {}).get("release_blockers") or []) if a["kind"] != "reel" else []
        if blockers:   # I2: an unverified licence blocks release; qc fails until the owner clears it
            item["release_blockers"] = blockers
            checks["licences"] = False
            report["advisory_only"] += [f"{target} still {b['key']}: {b['blocker']}" for b in blockers]
        if shots_film:
            film_dir = rec.root / "film" / a["meta"]["target"]
            gate_checks, detail, not_run = qc.film_gates(video, film_dir, a["meta"]["scenes"], _plan(rec)["language"],
                                                         vtt=video.with_suffix(".vtt"))
            review = a["meta"].get("motion_review") or {}   # I12: advisory takes reach the owner's report
            if review:
                item["motion_review"] = review
                report["advisory_only"] += [f"{target} {r['scene']} shot {r['shot']}: Wan take {k} needs a look "
                                            f"({r['notes']}; {r['contact_sheet']})" for k, r in sorted(review.items())]
            words = sorted(p_.name[:-len(".voicecheck.json")] for p_ in
                           (film_dir / "voice" / "passages").glob("*.voicecheck.json")
                           if p_.name.split("-p")[0] in a["meta"]["scenes"]
                           and "words" in (json.loads(p_.read_text(encoding="utf-8")).get("not_run") or []))
            if words:   # M6: the passages whose word check did not run
                item["words_not_run"] = words
                report["advisory_only"].append(f"{target}: word check NOT RUN for {len(words)} passage(s): "
                                               + ", ".join(words))
            face_items, face_flagged, face_sheets, face_fails, face_missing = {}, [], {}, [], []
            face_stale, face_unjudged, unrecorded = [], [], False
            recorded = a["meta"].get("face_media")   # I3: the media in the cut, recorded at film --shots
            for sid in a["meta"]["scenes"]:
                fres = _scene_faces(rec, a["meta"]["target"], sid,
                                    None if recorded is None else [m for m in recorded if m["scene"] == sid])
                face_items.update(fres["items"])
                face_flagged += fres["flagged"]
                face_sheets[sid] = fres["sheet"]
                face_fails += fres["fails"]
                face_missing += ([fres["error"]] if fres["error"] else []) + fres["missing"]
                face_stale += [f"{sid} {x}" for x in fres["stale"]]
                face_unjudged += [f"{sid} {x}" for x in fres["not_judged"]]
                unrecorded |= fres["unrecorded"]
                report["advisory_only"] += [f"{target} " + ln for ln in _face_lines(sid, fres)
                                            if " REVIEW " in ln or "(override:" in ln]
            item["faces"] = {"sheets": face_sheets, "items": face_items, "flagged": face_flagged,
                             "not_judged": face_unjudged, "identity": facegate.IDENTITY,
                             "judged": "the media recorded in the cut" if not unrecorded else
                                       "the current picks (this cut predates the face media record: rebuild it)"}
            if face_unjudged:
                report["advisory_only"].append(f"{target} faces NOT JUDGED (no eye on a face found): "
                                               + ", ".join(face_unjudged) + "; look at them on the face sheet")
            if unrecorded:
                report["advisory_only"].append(f"{target} faces: the cut has no face media record; the current picks "
                                               "were judged, not necessarily what is in the cut (rebuild with film --shots)")
            if face_stale:
                item["faces"]["stale"] = face_stale
                report["advisory_only"].append(f"{target} faces: the picks changed after the cut was assembled ("
                                               + "; ".join(face_stale) + "): faces fails until film --shots rebuilds it")
            if face_missing:
                not_run["faces"] = "; ".join(face_missing)
            else:
                gate_checks["faces"] = not face_fails and not face_stale
            if face_fails:
                item["faces"]["fails"] = face_fails
            checks.update(gate_checks)
            item["gates"] = detail
            item["not_run"] = not_run          # a gate that cannot run fails the QC, it never passes
            failed += [f"{target}:not_run:{g}" for g in not_run]
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
    report["failed"] = failed
    rec.add_artifact("qc_report", _write_json(out / "report.json", report), {"failed": failed})
    rec.event("qc", report["result"], {"failed": failed})
    for target, item in report["items"].items():
        print(f"{target}: " + ", ".join(f"{k} {v}" for k, v in item["checks"].items())
              + f"; contact sheet qc/{item['contact_sheet']} (look at it)")
        faces = item.get("faces") or {}
        for f in faces.get("flagged") or []:
            where = (f"frames {f['frames'][0]}-{f['frames'][-1]}" if f["times"] else "still")
            print(f"  FACE {f['severity'].upper()} {f['scene']} shot {f['shot']} {f['key']}: {f['kind']} {where}"
                  + (f" (override: {f['override']})" if f.get("override") else ""))
        for x in faces.get("stale") or []:
            print(f"  FACE STALE {x}")
        for x in faces.get("not_judged") or []:
            print(f"  FACE NOT JUDGED {x}")
        for sid, sheet in (faces.get("sheets") or {}).items():
            print(f"  face sheet {sid}: {sheet or 'no face found'} (minute anomaly review: look at every tile)")
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
    if args.profile == "audiobook":
        missing = [f"{k}.wav" for k in FRAME_UNITS
                   if not (args.frame_dir and (Path(args.frame_dir) / f"{k}.wav").is_file())]
        if missing:
            raise Stop("the audiobook opens with the title and author and ends with the closing word: pass "
                       f"--frame-dir <dir> holding {', '.join(f'{k}.wav' for k in FRAME_UNITS)} "
                       f"(missing: {', '.join(missing)}), narrated in the book's voice",
                       "Narrate the three units, then rerun bundle-audio --frame-dir <dir> "
                       "(or --profile film for the film-level master)")
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


_PART_HEADING = re.compile(r"খণ্ড|ভাগ")


def _is_part(unit: dict) -> bool:
    """A unit is a part (not a chapter) when the plan flags it `part: true` or its title or a heading
    paragraph names it a খণ্ড or ভাগ."""
    heads = [p["text"] for p in unit["paragraphs"] if retime._HEADING_LINE.match(p["text"])]
    return bool(unit.get("part")) or any(_PART_HEADING.search(t) for t in [unit.get("title", ""), *heads])


def _audiobook_cues(args, bed, n: int, count: int, unit: dict) -> dict:
    """Title and author open the first unit, the closing word ends the last; a score bed (when given)
    plays only at the book's intro and outro, and at the start of a unit that is a part (units are
    chapters: they get no bed)."""
    frame = {k: Path(args.frame_dir) / f"{k}.wav" for k in FRAME_UNITS}
    cues = {}
    if n == 1:
        cues["opening"] = [frame["title"], frame["author"]]
    if n == count:
        cues["closing"] = frame["closing"]
    if bed:
        if n == 1:
            cues["intro"] = bed
        elif _is_part(unit):
            cues["part"] = bed
        if n == count:
            cues["outro"] = bed
    return cues


def _chapters(unit: dict, segs: list) -> list:
    """পরিচ্ছেদ markers: each heading paragraph (retime's heading rule) at its measured start; a unit
    with none, or with text before its first heading, also gets one at 0 titled with the unit."""
    start = {s["anchor_id"]: s["start_ms"] for s in segs}
    marks = [{"title": " ".join(p["text"].split()).lstrip("# ").rstrip("।. "), "start_ms": start[p["anchor_id"]]}
             for p in unit["paragraphs"] if retime._HEADING_LINE.match(p["text"])]
    if not marks or marks[0]["start_ms"] > segs[0]["start_ms"]:
        marks.insert(0, {"title": unit["title"], "start_ms": 0})
    return marks


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


def _passage_generators(rec, targets) -> list:
    """I11: the evidence draft's rows for Eleven v4 passage narration: model, voice and the credits of every
    import-take run of the film (passages_checked events, redos included)."""
    rows = []
    for t in sorted(targets):
        runs = [e["detail"] for e in rec.data["events"] if e["stage"] == "import"
                and e["result"] == "passages_checked" and e["detail"].get("target") == t]
        mans = [_json(rec.root / a["path"]) for a in rec.data["artifacts"] if a["kind"] == "passage_manifest"
                and a["path"].startswith(f"film/{t}/")]
        models = sorted({m["model"] for m in mans})
        rows.append({"model": [f"elevenlabs/{m}" for m in models] if len(models) != 1 else f"elevenlabs/{models[0]}",
                     "engine": "elevenlabs", "target": t, "route": "eleven-v4-passages",
                     "licence": "ElevenLabs paid-plan commercial licence (owner decision 2026-11-24)",
                     "voice": sorted({m["voice_name"] for m in mans}), "voice_id": sorted({m["voice_id"] for m in mans}),
                     "credits": sum(r.get("credits") or 0 for r in runs), "scenes": sorted({m["scene"] for m in mans})})
    return rows


def _unit_times(units, clauses) -> tuple:
    """Each voice unit's (start, end) from the scene's clause timing, by aligning their characters (whitespace
    aside). A unit edge on a clause edge takes the measured time; one inside a clause is placed by its characters
    (returned in `estimated`)."""
    def flat(t):
        return "".join(t.split())
    if flat("".join(c["text"] for c in clauses)) != flat("".join(u["text"] for u in units)):
        raise Stop("the scene's clause timing does not spell its voice units (the book's words)",
                   "Re-run scene-timing for the scene; never publish narration that differs from the book")
    edges, pos = [], 0
    for c in clauses:
        n = len(flat(c["text"]))
        edges.append((pos, pos + n, c["start"], c["end"]))
        pos += n

    def at(ch, end):
        for a, b, s0, s1 in edges:
            if (a <= ch < b) if not end else (a < ch <= b):
                if ch == (b if end else a):
                    return (s1 if end else s0), False
                return s0 + (s1 - s0) * (ch - a) / max(1, b - a), True
        return edges[-1][3], True
    out, est, pos = [], [], 0
    for u in units:
        n = len(flat(u["text"]))
        (s0, e0), (s1, e1) = at(pos, False), at(pos + n, True)
        out.append((s0, s1))
        if e0 or e1:
            est.append(u["unit_key"])
        pos += n
    return out, est


def _scene_voice_track(rec, t, scs, units, out: Path) -> tuple:
    """I11: the chapter wav of a unit narrated by the Eleven v4 passage route (its scenes' joined voices, back to
    back) and each voice unit's measured timing on it (from each scene's scene-timing clauses)."""
    film_dir = rec.root / "film" / t
    parts, timing, offset, est, shas = [], [], 0.0, [], {}
    for sc in scs:
        sid = sc["scene_id"]
        wav, tf = film_dir / "voice" / f"{sid}.wav", _timing_path(film_dir, sid)
        if not wav.is_file():
            raise Stop(f"scene {sid}: narration not imported yet (no {wav})", next_action(rec.root))
        if not tf.is_file() or _json(tf).get("voice_sha256") != sha256_file(wav):
            raise Stop(f"scene {sid} has no scene timing of its current voice", f"{PROG} scene-timing --root {rec.root} "
                       f"--film {int(t[5:])} --scene {sid}")
        x = retime.read(wav)
        mine = [u for u in units if u["unit_key"].startswith(sid + "-")]
        spans, e = _unit_times(mine, _json(tf)["timing"])
        timing += [{"unit_key": u["unit_key"], "start": round(offset + a, 3), "end": round(offset + b, 3)}
                   for u, (a, b) in zip(mine, spans)]
        est += e
        shas[sid] = sha256_file(wav)
        parts.append(x)
        offset += len(x) / retime.SR
    import numpy as np
    retime.write(out, np.concatenate(parts))
    return timing, {"wav_sha256": shas, "track_sha256": sha256_file(out), "scene_voice": shas, "estimated": est}


def _write_audio_bundle(rec, plan, src, lang, bundle, scene_film, args):
    rows, prov_units, job_ids, v4_targets = [], {}, set(), set()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bundle.mkdir(parents=True, exist_ok=True)
        for n, unit in enumerate(src["units"], 1):
            anchors = {p["anchor_id"] for p in unit["paragraphs"]}
            mine = [(fi, sc) for fi, sc in scene_film.values() if set(sc["anchor_ids"]) <= anchors]
            films_used = {fi for fi, _ in mine}
            if not mine or len(films_used) != 1:
                raise Stop(f"unit {unit['unit_id']} has no single planned film", "Re-plan the title")
            ft = _film_target(films_used.pop())
            job = _latest_job(rec, "narration", ft)
            style = job["style"] if job else CONTINUOUS
            if job:
                job_ids.add(job["job_id"])
            units, tags = [], []
            for _, sc in mine:
                vus = voice_units(sc, {"description": ""}, None, lang, style)
                tg = unit_anchors(sc, lang, style)
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
            if job:
                timing, prov = _measured_track(units, rec.root / "narration" / job["job_id"], chapter,
                                               job["job_id"])
            else:   # I11: the Eleven v4 passage route: the joined scene voices and their measured clause timing
                timing, prov = _scene_voice_track(rec, ft, [sc for _, sc in mine], units, chapter)
                v4_targets.add(ft)
            master, score_sha = td / f"unit-{n:03d}-master.wav", None
            audiobook = args.profile == "audiobook"
            offset, pauses, master_info = 0.0, [], {}
            try:
                if audiobook:  # own master: -18 LUFS, TP <= -2 dBTP, LRA 4-8 LU, mono 64 kbps, beds at part ends only
                    bed = None if args.dry else Path(args.score_dir) / f"{unit['unit_id']}.wav"
                    score_sha = sha256_file(bed) if bed else None
                    master_info = mix.master_audiobook(chapter, _audiobook_cues(
                        args, bed, n, len(src["units"]), unit), td / f"unit-{n:03d}.mp3")
                    offset = master_info["voice_offset_s"]
                    pauses = retime.detect_pauses(chapter)
                    mastered = "eav.mix.master_audiobook"
                elif args.dry:  # narration only, same -16 LUFS / -1 dBTP gate
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
            if audiobook:
                shutil.copy2(td / mp3.name, mp3)
            else:
                _ff("-i", master, "-ar", 48000, "-ac", 2, "-c:a", "libmp3lame", "-b:a", "96k", mp3)
            dur_ms = round(film._duration(mp3) * 1000)
            segs, sents, unmeasured, mapping = [], [], [], {}
            for p in unit["paragraphs"]:
                times = [t for t, a in zip(timing, tags) if a == p["anchor_id"]]
                start, end = round((times[0]["start"] + offset) * 1000), round((times[-1]["end"] + offset) * 1000)
                if end > dur_ms:
                    if end - dur_ms > MP3_END_SLACK_MS:
                        raise Stop(f"{mp3.name}: measured narration ends after the MP3", "Report as a bug")
                    end = dur_ms
                segs.append({"anchor_id": p["anchor_id"], "start_offset_chars": 0,
                             "end_offset_chars": len(p["text"]), "start_ms": start, "end_ms": end})
                if audiobook:
                    got = retime.sentence_spans(p["text"], times[0]["start"], times[-1]["end"], pauses)
                    if got is None:  # too few pauses: the paragraph keeps paragraph-level timing
                        unmeasured.append(p["anchor_id"])
                        continue
                    spans, mapping[p["anchor_id"]] = got
                    ms = [(round((a + offset) * 1000), round((b + offset) * 1000)) for a, b in spans]
                    ms[0], ms[-1] = (start, ms[0][1]), (ms[-1][0], end)
                    sents += [{"anchor_id": p["anchor_id"], "sentence_index": i, "start_ms": a, "end_ms": b}
                              for i, (a, b) in enumerate(ms)]
            row = {"unit_id": unit["unit_id"], "mp3": mp3.name, "segments": segs}
            if audiobook:
                row.update(chapters=_chapters(unit, segs), sentences=sents)
            rows.append(row)
            prov_units[unit["unit_id"]] = {
                "narration_job_id": job["job_id"] if job else None, "wav_sha256": prov["wav_sha256"],
                **({"scene_voice": prov["scene_voice"], "timing_estimated": prov["estimated"]} if not job else {}),
                "chapter_wav_sha256": prov["track_sha256"], "mastered_with": mastered,
                "score_sha256": score_sha,
                "mp3_sha256": sha256_file(mp3), "mp3_duration_ms": dur_ms,
                "encoder": ("ffmpeg libmp3lame 64 kbps CBR mono 48 kHz" if audiobook
                            else "ffmpeg libmp3lame 96 kbps CBR stereo 48 kHz")}
            if audiobook:
                prov_units[unit["unit_id"]].update(
                    lufs=master_info["lufs"], true_peak_dbtp=master_info["true_peak"],
                    lra_lu=master_info["lra"], bed_under_voice_lu=master_info["bed_under_voice_lu"],
                    duck_db=master_info["duck_db"], release_s=master_info["release_s"],
                    voice_offset_ms=round(offset * 1000), sentences_unmeasured=unmeasured,
                    sentence_mapping=mapping)
    ids = sorted(job_ids)
    provenance = {"method": "eav.film.narration_track" if ids else "eav.cli scene voices + scene-timing",
                  "measured_with": "ffprobe",
                  "narration_job_id": (ids[0] if len(ids) == 1 else ids) if ids else None, "units": prov_units}
    if args.profile == "audiobook":
        provenance.update(profile="audiobook", sentence_splitter="eav.text.sentences",
                          frame_units_sha256={k: sha256_file(Path(args.frame_dir) / f"{k}.wav")
                                              for k in FRAME_UNITS})
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
        "generators": _narration_generators(rec, plan, job_ids) + _passage_generators(rec, v4_targets),
        "dry_narration": bool(args.dry),
        "music": None if args.dry else {
            **_music_licence(args.score_route),
            "mix": ("score bed at the opening, part changes and closing only, 24 LU under the voice, ducked "
                    "6 dB with a 1.5 s release (eav.mix.master_audiobook, -18 LUFS)"
                    if args.profile == "audiobook" else
                    "per-chapter score bed, ducked under speech (eav.mix.duck_and_master, -16 LUFS)"),
            "score_sha256": {u: v["score_sha256"] for u, v in prov_units.items()}},
        "release_blockers": _release_blockers(rec),
        "owner_must_complete": ["territories", "term_per_territory", "text_source_licence",
                                "cover_provenance", "status", "owner_approval"]
        + (["release_blockers"] if _release_blockers(rec) else []),
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
              f"{_cap_note(ledger, title)}), {ledger.spent(None, month):.2f} CU this month (all titles), "
              f"{_remaining(ledger, rec, month):.2f} CU remaining ({month}).")
        for j in _jobs(rec):
            closed = next((e["detail"]["units"] for e in rec.data["events"] if e["result"] == "closed"
                           and e["detail"].get("job_id") == j["job_id"]), None)
            state = ("adopted (0 CU; imported media bound to its scene)" if j["adopted"]
                     else "imported" if j["imported"] else "superseded" if j["superseded"]
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
    a, b = passages._bounds(retime.read(src))
    plan = retime.plan_pauses(text.read_text(encoding="utf-8"), pauses, args.seed, bounds=(a / retime.SR, b / retime.SR))
    cuts = [float(c) for c in args.cuts.split(",") if c.strip()] if args.cuts else []
    res = retime.retime(src, Path(args.dst), plan, cuts)
    print(json.dumps({"pauses": len(pauses), **res}))


def _load_transcripts(path) -> dict:
    """The Colab words cell's transcripts.json: {stem: {"sha256", "text"}} plus the model record."""
    pf = Path(path)
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
        if data.get("schema") != voicecheck.TRANSCRIPT_SCHEMA or not isinstance(data["takes"], dict):
            raise ValueError
    except (OSError, ValueError, KeyError, AttributeError):
        raise Stop(f"{pf} is not a transcripts.json written by the words cell",
                   "Run templates/words_cell.py.txt in Colab, download its transcripts.json and pass that")
    return data


def _transcript_for(data, stem, take_file):
    """The transcript text of one take, or None (not run) when absent or made for another file's bytes."""
    row = (data or {}).get("takes", {}).get(stem)
    if not isinstance(row, dict):
        return None
    if row.get("sha256") != voicecheck.sha256_file(take_file):
        print(f"Warning: the transcript of {stem} was made for different file bytes than {take_file}; "
              "it is not applied (word check NOT RUN). Transcribe the exact file you pass here, with no "
              "conversion in between (references/earnalism-voice.md).")
        return None
    return row.get("text")


def _words_note(res, data):
    w = res["metrics"].get("words")
    if data is not None and w and w["run"]:
        w["model"] = data.get("model")
    return res


def cmd_motiongate(args):
    clips = []
    for a in args.clips:
        p = Path(a)
        if p.is_dir():
            clips += sorted(p.glob("*.mp4"))
        elif p.is_file():
            clips.append(p)
        else:
            raise Stop(f"{p} does not exist", "Fix the path and rerun")
    if not clips:
        raise Stop("no .mp4 clips given", "Pass clip files or a folder of clips")
    out = Path(args.out) if args.out else None
    failed = 0
    for c in clips:
        r = motiongate.gate_clip(c, out)
        verdict = "FAIL" if not r["pass"] else ("REVIEW" if r["needs_review"] else "pass")
        failed += not r["pass"]
        print(f"{verdict:6} {c.name}: " + ("; ".join(r["notes"]) or "smooth"))
    print(f"{len(clips)} clip(s) gated, {failed} failed. Written beside each clip (or in --out): "
          "<key>.motion.json and <key>.contact.png; the clips are untouched. Thresholds are uncalibrated.")


def cmd_voicecheck(args):
    takes = [Path(t) for t in args.takes]
    for t in takes:
        if not t.is_file():
            raise Stop(f"{t} does not exist", "Fix the path and rerun")
    exp = [float(v) for v in args.expected.split(",")]
    if len(exp) not in (1, len(takes)):
        raise Stop("--expected needs one value or one per take", "Fix --expected and rerun")
    exp = exp * len(takes) if len(exp) == 1 else exp
    out = Path(args.out) if args.out else takes[0].parent
    out.mkdir(parents=True, exist_ok=True)
    data = _load_transcripts(args.transcripts) if args.transcripts else None
    if data is not None and not args.sources:
        raise Stop("--transcripts needs --sources <folder of <take-stem>.txt untagged book text>",
                   "Pass --sources; without source text the word check cannot run")
    words = {}   # take -> (transcript, source) where both exist
    for t in takes:
        src = Path(args.sources or ".") / f"{t.stem}.txt" if data is not None else None
        text = _transcript_for(data, t.stem, t) if src is not None and src.is_file() else None
        if text is not None:
            words[t] = (text, take.strip_tags(src.read_text(encoding="utf-8")))
    if args.profile:
        pf = Path(args.profile)
        if not pf.is_file():
            raise Stop(f"{pf} does not exist", "Fix --profile and rerun")
        prof = json.loads(pf.read_text())
    else:
        prof = voicecheck.profile(takes)
        (out / "voicecheck-profile.json").write_text(json.dumps(prof, indent=1))
    prev = Path(args.prev_tail) if args.prev_tail else None
    if prev is not None and not prev.is_file():
        raise Stop(f"{prev} does not exist", "Fix --prev-tail and rerun")
    failed, results = 0, {}
    for t, e in zip(takes, exp):
        r = _words_note(voicecheck.check(t, e, prof, prev, *words.get(t, (None, None))), data)
        prev = t
        results[t.stem] = r
        (t.parent if not args.out else out).joinpath(f"{t.stem}.voicecheck.json").write_text(
            json.dumps(r, indent=1, ensure_ascii=False))
        failed += bool(r["failures"])
        print(f"{t.name}: {'REDO ' + ','.join(r['failures']) if r['failures'] else 'PASS'}"
              + (" (word check NOT RUN: no matching transcript)" if r.get("not_run") else "")
              + (f" (word check WARNING: CER {r['metrics']['words']['cer']:.3f} above the provisional ceiling "
                 f"{r['metrics']['words']['threshold']:g}; listen)" if "words" in r.get("warnings", []) else "")
              + "".join(f" (WARNING {c}: measured {v['measured']:g} against the uncalibrated limit {v['limit']:g}; "
                        "listen, not a redo)" for c, v in sorted((r.get("warning_values") or {}).items())))
    if not args.profile and data is not None:   # the saved profile's median is of the accepted takes only
        acc = voicecheck.accepted_cers(results)
        if acc:
            (out / "voicecheck-profile.json").write_text(json.dumps(voicecheck.with_words(prof, acc), indent=1))
    print(f"Wrote <take>.voicecheck.json per take{'' if args.profile else ' and ' + str(out / 'voicecheck-profile.json')}.")
    if failed:
        print(f"Next: regenerate the {failed} REDO take(s), then rerun with --profile {out / 'voicecheck-profile.json'}")
        return 1
    return 0


def _music_roles(job, stems_dir) -> dict:
    """{stem key: drone|solo|phrase|None}: the role each item of the music job declared, else the word in its key."""
    declared = {i["key"]: i.get("role") for i in _job_json(job).get("items") or [] if isinstance(i, dict)}
    keys = sorted({p.stem for p in Path(stems_dir).iterdir() if p.is_file() and p.suffix.lower() in cue.STEM_EXTS})
    return {k: cue.stem_role(k, declared.get(k)) for k in keys}


def cmd_cue(args):
    rec = _record(args.root)
    t = _film_target(args.film)
    if not args.scene:
        raise Stop("cue needs --scene (a cue belongs to one scene)", "Rerun with --scene <ID>")
    job = next((j for j in _jobs(rec) if j["job_id"] == args.stems and j["kind"] == "music"
                and j["imported"] and not _ended(j)), None)
    stems_dir = rec.root / "music" / args.stems
    if job is None or not stems_dir.is_dir():   # I9/F13: an imported music job, never a folder copied by hand
        raise Stop(f"{args.stems} is not an imported music job of this title", next_action(rec.root))
    if job["scene"] != args.scene:              # one cue per scene: never another scene's stems
        raise Stop(f"music job {args.stems} is " + (f"scene {job['scene']}'s own" if job["scene"] else
                                                    "not bound to a scene") + f", not scene {args.scene}'s",
                   f"Build scene {args.scene}'s own stems: {PROG} job music --root {rec.root} --film {args.film} "
                   f"--rates <rates.json> --spec <music.json with \"scene\": \"{args.scene}\" and each item's \"role\">")
    film_dir = rec.root / "film" / t
    for other in sorted((film_dir / "audio").glob("*.mix.json")):
        doc = _json(other)
        if doc.get("scene") != args.scene and doc.get("stems_job") == args.stems:
            raise Stop(f"scene {doc.get('scene')} already mixes stems of {args.stems}; a scene never borrows another "
                       "scene's cue", f"Build scene {args.scene}'s own music job")
    roles_of = _music_roles(job, stems_dir)
    if args.pick:
        if not args.tonic:
            raise Stop("--pick needs --tonic (e.g. D)", "Rerun with --tonic")
        try:
            pick = cue.pick_stems(stems_dir, args.tonic, roles_of)
        except ValueError as e:
            raise Stop(str(e), "Label the music job's stems (spec item \"role\": drone|solo|phrase) and rebuild it")
        saved = cue.write_pick(stems_dir, args.tonic, pick)
        print(f"Picked {json.dumps(pick)} for tonic {args.tonic}, each within its family; saved {saved}. "
              f"Next: {PROG} cue --root {rec.root} --film {args.film} --scene {args.scene} --stems {args.stems} --fx <fx.json>")
        return 0
    try:
        sp = shotplan.require_approved(film_dir, args.scene)
    except shotplan.NotApproved as e:
        raise Stop(str(e), f"{PROG} plan-shots --root {rec.root} --film {args.film} --scene {args.scene}")
    if (sp.get("peak") or {}).get("at") is None:
        raise Stop(f"the shot plan of scene {args.scene} has no peak.at", "Set peak in the planner input and re-approve")
    roles = {r: getattr(args, r) for r in ("drone", "solo", "phrase")}
    if not all(roles.values()):
        saved = stems_dir / "cue-pick.json"
        if not saved.is_file():
            raise Stop("cue needs --drone, --solo and --phrase (or a saved pick)", f"{PROG} cue --pick --tonic <note> first")
        roles = {r: roles[r] or _json(saved)[r] for r in roles}
    wrong = [f"{k} as the {r} ({roles_of.get(k) or 'unlabelled'})" for r, k in roles.items() if roles_of.get(k) != r]
    if wrong:
        raise Stop("stem roles do not match their families: " + ", ".join(wrong),
                   "Pick each role from its own family (cue --pick does), or label the stems in the music spec")
    voice = Path(args.voice) if args.voice else film_dir / "voice" / f"{args.scene}.wav"
    if not voice.is_file():
        raise Stop(f"the scene voice {voice} does not exist", "Pass --voice <retimed wav> or put it there")
    fx = _json(args.fx) if args.fx else {}
    base = Path(args.fx).parent if args.fx else Path(".")
    items = {k: [{**e, "path": str(base / e["path"])} for e in fx.get(k, [])] for k in ("ambience", "foley")}
    licences, refused = {}, []
    for e in (e for v in items.values() for e in v):   # I10: a licence on file for every sound, fail closed
        try:
            licences[e["path"]] = cue.sound_licence(e["path"])
        except ValueError as err:
            refused.append(str(err))
    if refused:
        raise Stop("sound(s) without a licence on file: " + " | ".join(refused),
                   "Use CC0 or author-released public-domain sounds with their record: the imported film_clips "
                   "sfx/licences.json, or a licences.json beside your CC0 synthesis ({\"<file>\": {\"title\", "
                   "\"licence\": \"CC0-1.0\", \"author\", \"basis\": {\"rule\": \"cc0-synthesis\"}}})")
    try:
        stems = {r: cue.stem_path(stems_dir, k) for r, k in roles.items()}
    except ValueError as e:
        raise Stop(str(e), "Fix the stem keys and rerun")
    out = film_dir / "audio" / f"{args.scene}.mix.wav"
    res = cue.scene_mix(voice, [s["start"] for s in sp["shots"]], sp["peak"]["at"], stems,
                        items["ambience"], items["foley"], out, sp["seconds"])
    _write_json(out.with_suffix(".json"), {"scene": args.scene, "stems_job": args.stems, "stems": roles,
                                      "peak_at": sp["peak"]["at"], "voice": str(voice.resolve()),
                                      "fx": {k: [{**e, "path": str(Path(e["path"]).resolve()),
                                                  "licence": licences[e["path"]]} for e in v] for k, v in items.items()},
                                      **res})
    print(f"Mixed {out}: {res['lufs']:.1f} LUFS, {res['true_peak']:.1f} dBTP, voice over music {res['voice_over_music_db']:.1f} dB.")
    return 0


def cmd_plan_shots(args):
    rec = _record(args.root)
    if args.approve and not (args.by and args.reviewer):
        raise Stop("--approve needs --by and --reviewer", "Pass both names: Claude plus an independent reviewer")
    if args.approve and args.by.strip().lower() == args.reviewer.strip().lower():
        raise Stop("approval needs an independent reviewer: --by and --reviewer must be different people",
                   "Have the reviewer approve, not the author")
    films = _plan(rec)["plan"]["films"]
    if not 1 <= args.film <= len(films):
        raise Stop(f"film {args.film} is not in the plan ({len(films)} films)", f"{PROG} status --root {rec.root}")
    scene = next((sc for sc in films[args.film - 1]["scenes"] if sc["scene_id"] == args.scene), None)
    if scene is None:
        raise Stop(f"scene {args.scene} is not in film {args.film}", f"{PROG} status --root {rec.root}")
    film_dir = rec.root / "film" / _film_target(args.film)
    paths = shotplan.paths(film_dir, args.scene)
    if not paths["input"].is_file():
        raise Stop(f"no planner input at {paths['input']}",
                   f"Write it (Claude and the reviewer; format: {PROG} --help, plan-shots) and rerun")
    bible = Path(args.bible) if args.bible else rec.root / "specs" / "world-bible.json"
    if not bible.is_file():
        raise Stop(f"{bible} does not exist", "Pass --bible <world-bible.json>")
    inp = _json(paths["input"])
    timing_sha = None
    if not inp.get("timing"):   # I6: the measured clause timing of scene-timing, its length_s included
        tf = _timing_path(film_dir, args.scene)
        if not tf.is_file():
            raise Stop(f"the planner input has no \"timing\" and there is no {tf.name}",
                       f"{PROG} scene-timing --root {rec.root} --film {args.film} --scene {args.scene}")
        measured = _json(tf)
        inp = {**inp, "timing": measured["timing"], **({} if "length_s" in inp else {"length_s": measured["length_s"]})}
        timing_sha = shotplan.input_sha256(tf)
    sp = shotplan.plan({**inp, "scene_id": args.scene, "text": scene["text"]}, inp.get("timing") or [], _json(bible))
    if args.approve:
        try:
            sp = shotplan.approve(sp, args.by, args.reviewer, input_sha256=shotplan.input_sha256(paths["input"]),
                                  timing_sha256=timing_sha)
        except ValueError as e:
            raise Stop(f"not approved: {e}", f"Fix {paths['input']} and rerun plan-shots without --approve")
    shotplan.write(film_dir, sp)
    found = shotplan.check(sp)
    for code, msg in found:
        print(f"{code}: {msg}")
    hard = [c for c, _ in found if not c.endswith("?")]
    print(f"Wrote {paths['plan']} and {paths['av']}: {len(sp['shots'])} shots, {sp['seconds']:.1f} s, "
          f"{sp['compute']['wan_clips']} Wan clip(s), about {sp['compute']['cu']} CU (planning estimate)"
          + (f"; approved by {sp['approved']['by']} with {sp['approved']['reviewer']}." if args.approve else
             ("; hard rules fail, fix the input." if hard else "; rules R1-R3 pass, ready for approval.")))
    return 1 if hard else 0


TIMING_SCHEMA = "earnalism.audiovisual-scene-timing.v1"
TIMING_MIN_PAUSE_S = 0.30   # after retime every punctuation pause is >= 0.34 s (0.40 - 15 %); a breath kept short is not


def _timing_path(film_dir, sid) -> Path:
    return shotplan.paths(film_dir, sid)["dir"] / f"{sid}.timing.json"


def _scene_clauses(film_dir, sid) -> list:
    """The scene's measured clause timing [{start, end, text}]: the planner input's own "timing", else the
    `scene-timing` file <scene>.timing.json beside it."""
    p = shotplan.paths(film_dir, sid)["input"]
    inp = _json(p) if p.is_file() else {}
    if inp.get("timing"):
        return inp["timing"]
    tf = _timing_path(film_dir, sid)
    return _json(tf)["timing"] if tf.is_file() else []


TIMING_TOLERANCE = (f"each clause boundary's pause within {retime.POS_TOL_CHARS} characters at the local speaking rate of "
                    f"its local estimate, {retime.POS_TOL_MIN_S:g}-{retime.POS_TOL_MAX_S:g} s (x{retime.POS_TOL_LONG:g} for a "
                    "pause already as long as its punctuation pause); see each boundary's tol_s")


def _passage_clauses(wav: Path, plain: str, offset: float, pid: str, threshold_db: float, min_pause: float) -> tuple:
    """(clauses, breaths, boundaries with their tolerance) of one retimed passage: its clauses (retime.clauses) with each boundary at the measured
    pause its punctuation matches by position (retime.match_pauses), and the pauses no mark explains (breaths inside
    a clause, kept as they are). A boundary with no pause near its words, or whose pause lies far from them, is a
    mislabelled clause: it stops, nothing is guessed."""
    cl = retime.clauses(plain)
    x = retime.read(wav)
    a, b = passages._bounds(x)
    t0, t1 = a / retime.SR, b / retime.SR
    pauses = sorted((ps, pe) for ps, pe in retime.detect_pauses(wav, threshold_db, min_pause) if t0 < ps and pe < t1)
    rows = retime.match_pauses(plain, pauses, (t0, t1))

    def short(text):
        w = text.split()
        return text if len(w) <= 6 else " ".join(w[:3]) + " … " + " ".join(w[-2:])
    bad = []
    for r in rows:
        where = f"clause {r['clause'] + 1} «{short(cl[r['clause']][0])}» ({r['kind']})"
        if r["pause"] is None:
            near = min(pauses, key=lambda p_: abs(p_[0] - r["expected_s"]), default=None)
            bad.append(f"{where} ends at no measured pause of at least {min_pause:g} s within {r['tol_s']:.2f} s of where "
                       f"its words put the end ({offset + r['expected_s']:.2f} s)"
                       + (f"; the nearest pause, at {offset + near[0]:.2f} s, is too far to be it and is not used" if near else ""))
        elif abs(r["error_s"]) > r["tol_s"]:
            ps = pauses[r["pause"]][0]
            bad.append(f"{where} would end at the pause at {offset + ps:.2f} s, {abs(r['error_s']):.1f} s from where "
                       f"its words put it ({offset + r['expected_s']:.2f} s)")
    if bad:
        raise Stop(f"passage {pid}: the measured pauses do not match its punctuation by position: " + "; ".join(bad)
                   + f" ({len(pauses)} pause(s) of at least {min_pause:g} s for {len(rows)} clause boundar"
                   f"{'y' if len(rows) == 1 else 'ies'}); the clause times would be guessed, so none are written",
                   "Listen to the passage: tune --min-pause / --threshold-db until every clause boundary has its pause, "
                   "or time this scene's clauses by ear into the planner input's \"timing\"")
    cuts = [pauses[r["pause"]] for r in rows]
    used = {r["pause"] for r in rows}
    marks = [t0] + [v for ps in cuts for v in ps] + [t1]
    out = [{"start": round(offset + marks[2 * i], 3), "end": round(offset + marks[2 * i + 1], 3), "text": c}
           for i, (c, _) in enumerate(cl)]
    breaths = [{"start": round(offset + ps, 3), "end": round(offset + pe, 3)}
               for j, (ps, pe) in enumerate(pauses) if j not in used]
    bounds_ = [{"passage": pid, "clause": r["clause"] + 1, "kind": r["kind"],
                "expected_s": round(offset + r["expected_s"], 3), "error_s": r["error_s"], "tol_s": r["tol_s"],
                "local_s_per_char": r["local_s_per_char"]} for r in rows]
    return out, breaths, bounds_


def cmd_scene_timing(args):
    """I6 (F4, F5): the measured clause timing of a scene's voice for plan-shots, with its R9 lead-in and R4 tail.
    A passage-joined scene (Eleven v4) is timed passage by passage from its retimed takes and the join's offsets;
    a scene wav placed by hand is timed as one passage of the scene text. Writes film/film-NN/shots/<scene>.timing.json
    ({"timing": [{start, end, text}], "length_s", "lead_in_s", "tail_s", ...}); plan-shots reads it when the
    planner input has no "timing" of its own."""
    rec = _record(args.root)
    plan = _plan(rec)
    films = plan["plan"]["films"]
    if not 1 <= args.film <= len(films):
        raise Stop(f"film {args.film} is not in the plan ({len(films)} films)", f"{PROG} status --root {rec.root}")
    t = _film_target(args.film)
    sc = next((x for x in films[args.film - 1]["scenes"] if x["scene_id"] == args.scene), None)
    if sc is None:
        raise Stop(f"scene {args.scene} is not in film {args.film}", f"{PROG} status --root {rec.root}")
    film_dir = rec.root / "film" / t
    voice = film_dir / "voice" / f"{args.scene}.wav"
    if not voice.is_file():
        raise Stop(f"scene {args.scene} has no voice {voice}", next_action(rec.root))
    manifest_path = film_dir / "voice" / f"{args.scene}.passages.json"
    rows, breaths, bounds_ = [], [], []
    if manifest_path.is_file():
        man = _json(manifest_path)
        if man.get("wav_sha256") != sha256_file(voice):
            raise Stop(f"{voice} is not the wav its passage manifest records", "Re-import the scene's passages")
        offsets = (man.get("join") or {}).get("offsets")
        if not offsets or len(offsets) != len(man["passages"]):
            raise Stop(f"the passage manifest of {args.scene} predates the join offsets", "Rerun the same import-take "
                       "call for the scene (no new takes or credits) to rejoin it with its lead-in, tail and offsets")
        plains = [p_.get("plain") for p_ in man["passages"]]
        if not all(plains):
            text, _ = _scene_text(sc, plan["language"])
            plains = passages.check_passage_scripts(text, [(rec.root / p_["script"]).read_text(encoding="utf-8")
                                                           for p_ in man["passages"]])
        for p_, plain, off in zip(man["passages"], plains, offsets):
            got, br, bd = _passage_clauses(rec.root / p_["retimed"], plain, off, p_["id"], args.threshold_db, args.min_pause)
            rows, breaths, bounds_ = rows + got, breaths + br, bounds_ + bd
    else:
        text, _ = _scene_text(sc, plan["language"])
        rows, breaths, bounds_ = _passage_clauses(voice, text, 0.0, args.scene, args.threshold_db, args.min_pause)
    length = len(retime.read(voice)) / retime.SR
    lead, tail = rows[0]["start"], length - rows[-1]["end"]
    lo, hi = passages.LEAD_IN_RANGE
    out = _write_json(_timing_path(film_dir, args.scene), {
        "schema": TIMING_SCHEMA, "scene": args.scene, "timing": rows, "breaths": breaths, "boundaries": bounds_,
        "position_tolerance": TIMING_TOLERANCE, "length_s": round(length, 3),
        "speech_start": rows[0]["start"], "speech_end": rows[-1]["end"], "lead_in_s": round(lead, 3),
        "tail_s": round(tail, 3), "r9_lead_in_ok": lo <= lead <= hi, "voice_sha256": sha256_file(voice),
        "method": "eav.cli scene-timing: retime.clauses matched by position (retime.match_pauses) to "
                  "retime.detect_pauses per retimed passage; unmatched pauses are breaths inside a clause",
        "threshold_db": args.threshold_db, "min_pause_s": args.min_pause})
    rec.add_artifact("scene_timing", out, {"target": t, "scene": args.scene})
    print(f"Timed {len(rows)} clause(s) of {args.scene}: speech {rows[0]['start']:.2f}-{rows[-1]['end']:.2f} s of "
          f"{length:.2f} s (lead-in {lead:.2f} s, tail {tail:.2f} s); wrote {out}."
          + (f" {len(breaths)} unpunctuated breath(s) kept inside their clauses: "
             + ", ".join(f"{b_['start']:.2f}-{b_['end']:.2f} s" for b_ in breaths) if breaths else ""))
    if not lo <= lead <= hi:
        print(f"WARNING R9: the first word lands {lead:.2f} s in, not {lo:g}-{hi:g} s: rejoin the scene (import-take "
              "pads the lead-in) before the paper edit")
    print(f"Next: write the planner input {shotplan.paths(film_dir, args.scene)['input']} without \"timing\" (this file "
          f"is read, length_s included), then {PROG} plan-shots --root {rec.root} --film {args.film} --scene {args.scene}")
    return 0


# ---------------------------------------------------------------- adoption (G1)
ADOPT_DIRS = {"stills": "stills", "film_clips": "film_clips", "music": "music"}


def _rel(path, root) -> str:
    return Path(os.path.relpath(Path(path).resolve(), Path(root).resolve())).as_posix()


def _adopt_sources(rec, spec, base):
    """A loader of the jobs an adoption may draw on, and every source it can trace hand-copied files to."""
    where_all = spec.get("sources") or {}
    if not isinstance(where_all, dict):
        raise adopt.Refused('"sources" must be {"<job id>": {"root": <title root>} | {"folder": <pilot job folder>}}')
    cache, others = {}, {}

    def load(job_id):
        if job_id in cache:
            return cache[job_id]
        where = where_all.get(job_id)
        if where is None:
            row = next((j for j in _jobs(rec) if j["job_id"] == job_id), None)
            if row is None:
                raise adopt.Refused(f"{job_id} is not a job of this record; say where it is in the spec's \"sources\" "
                                    f'({{"{job_id}": {{"root": "<title root>"}}}} or {{"folder": "<pilot job folder>"}})')
            if row["adopted"]:
                raise adopt.Refused(f"{job_id} is itself an adoption: adopt from the job that made the files")
            src = adopt.record_source(rec.root, row, rec.data["artifacts"], _job_json(row), "this record")
        elif isinstance(where, dict) and where.get("root"):
            root = (base / where["root"]).resolve()
            if not (root / "record.json").is_file():
                raise adopt.Refused(f"{job_id}: {root} holds no production record")
            if root not in others:
                others[root] = Record.load(root)
            other = others[root]
            row = next((j for j in _jobs(other) if j["job_id"] == job_id), None)
            if row is None:
                raise adopt.Refused(f"{job_id} is not a job of the record at {root}")
            src = adopt.record_source(other.root, row, other.data["artifacts"], _job_json(row), _rel(root, rec.root))
        elif isinstance(where, dict) and where.get("folder"):
            folder = (base / where["folder"]).resolve()
            src = adopt.folder_source(folder, job_id, _rel(folder, rec.root))
        else:
            raise adopt.Refused(f'"sources" entry of {job_id} needs "root" or "folder"')
        cache[job_id] = src
        return src

    def everything():
        """Every loadable source, for tracing a hand-copied file: the spec's sources and this record's jobs."""
        out = []
        for jid in list(where_all) + [j["job_id"] for j in _jobs(rec) if j["imported"] and not _ended(j)
                                      and not j["adopted"] and j["kind"] in PICK_KINDS + ("film_clips", "music")]:
            try:
                out.append(load(jid))
            except adopt.Refused:
                pass
        return out
    return load, everything


def _adopt_gate(rec, key, src, name, path, entry, advisories):
    """The pick gate of an adopted candidate, as `pick` applies it; returns the recorded verdict."""
    gated = isinstance(((src.prov.get("model") if src else None) or {}).get("gate"), dict)
    if src is not None and f"{Path(name).stem}.gate.json" in src.files:
        src.file(f"{Path(name).stem}.gate.json")
    gate, level, why = _gate_of(path, gated) if src is not None else (None, None, None)
    if src is None:
        return {"level": None, "why": "hand-copied file with no gate result of its own"}
    record = {"level": level, "why": why,
              "gate": None if gate is None else {k: gate.get(k) for k in ("pass", "needs_review", "anachronisms",
                                                                         "hands_detached", "eyes", "notes")}}
    if level == "fail":
        if not (entry.get("override_fail") or "").strip():
            raise adopt.Refused(f"{key}: {why} (a certain fail: give \"override_fail\": \"<reason>\" in its entry)")
        record["override_fail"] = entry["override_fail"]
    elif level == "review":
        if (rec.root / "gate-calibration.json").is_file():
            if not (entry.get("override") or "").strip():
                raise adopt.Refused(f"{key}: {why} (give \"override\": \"<reason>\" in its entry)")
            record["override"] = entry["override"]
        else:
            advisories[key] = why
    return record


def _adopt_stills(rec, spec, base, sid, shots, load, everything, advisories):
    binding, files = {}, []
    for key, entry in sorted((spec.get("stills") or {}).items()):
        n = int(key.rpartition("-")[2]) if key.startswith(sid + "-") and key.rpartition("-")[2].isdigit() else None
        if n not in shots:
            raise adopt.Refused(f"still key {key!r} is not <scene>-<n> of a shot of scene {sid}")
        if shots[n]["motion"] not in ("glide", "static"):
            raise adopt.Refused(f"shot {n} of scene {sid} is {shots[n]['motion']}: adopt its takes under \"clips\"")
        if not isinstance(entry, dict) or not entry.get("file"):
            raise adopt.Refused(f"{key}: an entry needs \"file\" (and \"job\", or a hand-copied file's \"reason\")")
        if entry.get("job"):
            src = load(entry["job"])
            if src.kind not in PICK_KINDS:
                raise adopt.Refused(f"{key}: {entry['job']} is a {src.kind} job, not a stills job")
            path, sha = src.file(Path(entry["file"]).name)
            lic = src.licence("image")
            gate = _adopt_gate(rec, key, src, path.name, path, entry, advisories)
            how = {"source": {**{k: src.prov.get(k) for k in ("origin", "record", "folder", "job_id", "kind",
                                                               "input_zip_sha256", "verified_against") if src.prov.get(k)},
                              "file": path.name, "sha256": sha}}
        else:
            path = (base / entry["file"]).resolve()
            if not path.is_file():
                raise adopt.Refused(f"{key}: hand-copied file {path} does not exist")
            if not (entry.get("reason") or "").strip():
                raise adopt.Refused(f"{key}: {path.name} is a hand-copied file (no job): it needs the operator's "
                                    "\"reason\", recorded with its sha256 and traced provenance")
            sha = sha256_file(path)
            traced = adopt.trace(sha, everything())
            lic, gate, src = None, None, None
            for t_ in traced:
                s_ = load(t_["job_id"])
                if t_["relation"].startswith("identical to the job's output") and s_.kind == "touchup":
                    # I2: a touch-up (OpenCV, no model) inherits the licence of its source still only when that source
                    # was verified at touch-up time (recorded as the output's model); it has no gate verdict of its own
                    if s_.model_repo() not in adopt.MODEL_LICENCES:
                        raise adopt.Refused(f"{key}: {path.name} is the output of touch-up {s_.job_id}, whose source "
                                            "still's model licence is not on record (an unverified source)")
                    lic, src = s_.licence("image"), s_
                    advisories[key] = (f"licence {lic['licence']} inherited from {s_.job_id}/{t_['file']}, a touch-up of "
                                       "a verified source still; no gate verdict of its own: film --shots needs a "
                                       "reason in picks/gate-overrides.json")
                    break
                if t_["relation"].startswith("identical to the job's output") and s_.kind in PICK_KINDS:
                    lic, src = s_.licence("image"), s_
                    gate = _adopt_gate(rec, key, s_, t_["file"], s_.file(t_["file"])[0], entry, advisories)
                    break
            declared = entry.get("from")
            if declared:
                if not isinstance(declared, dict) or not declared.get("job") or not declared.get("file"):
                    raise adopt.Refused(f"{key}: \"from\" needs {{\"job\", \"file\"}} (the job file it was derived from)")
                d_src = load(declared["job"])
                _, d_sha = d_src.file(Path(declared["file"]).name)
                declared = {"job_id": d_src.job_id, "file": Path(declared["file"]).name, "sha256": d_sha,
                            "relation": "identical" if d_sha == sha else
                            "derived by hand, as the operator declares (not byte-identical; not verified)"}
                if lic is None and d_src.kind in PICK_KINDS:   # only from a source verified just now (d_src.file)
                    lic = d_src.licence("image")
                    if declared["relation"] != "identical":
                        advisories[key] = (f"licence {lic['licence']} inherited from {d_src.job_id}/{declared['file']} "
                                           "(verified) by the operator's declared derivation, which is not verified; "
                                           "no gate verdict: film --shots needs a reason in picks/gate-overrides.json")
            if lic is None:
                lic = {"model": None, "licence": None, "note": "unverified: no job output matches it and none is declared"}
                advisories[key] = ("licence unverified (provenance untraced): a release blocker in film, qc and the "
                                   "clearance draft until the owner clears it; no gate verdict: film --shots needs a "
                                   "reason in picks/gate-overrides.json")
            how = {"hand_copied": {"file": _rel(path, rec.root), "sha256": sha, "reason": entry["reason"].strip(),
                                   "traced": traced, **({"declared_from": declared} if declared else {})}}
            if gate is None:
                gate = {"level": None, "why": "hand-copied file with no gate result of its own"}
        binding[key] = {**how, "licence": lic, "gate": gate}
        files.append((path, f"{key}--c1{path.suffix.lower()}", sha, key))
    return binding, files


def _adopt_clips(rec, spec, base, sid, sp, shots, load):
    binding, files, items = {}, [], []
    need = shotplan.render_frames(sp["shots"])
    for n_s, entry in sorted((spec.get("clips") or {}).items(), key=lambda kv: int(kv[0])):
        n = int(n_s)
        if n not in shots or shots[n]["motion"] != "wan":
            raise adopt.Refused(f"clips entry {n_s}: shot {n} of scene {sid} is not a wan shot of the approved plan")
        takes = entry.get("takes") if isinstance(entry, dict) else None
        if not entry.get("job") or not isinstance(takes, list) or not takes:
            raise adopt.Refused(f"clips entry {n}: needs \"job\" and \"takes\" (the take and its continuations, in order)")
        src = load(entry["job"])
        if src.kind not in ("film_clips", "clip_touchup"):
            raise adopt.Refused(f"shot {n}: {entry['job']} is a {src.kind} job, not a film_clips (Wan) job or a "
                                "clip touch-up of one")
        lic = src.licence("clip")
        chain, prev, frames = [], None, 0
        for k, key in enumerate(takes):
            if not str(key).startswith(sid + "-"):
                raise adopt.Refused(f"shot {n}: take {key!r} is not a key of scene {sid} (<scene>-...)")
            path, sha = src.file(f"{key}.mp4")
            item = src.item(key)
            if src.job.get("items") and item is None:
                raise adopt.Refused(f"shot {n}: {entry['job']} built no item {key!r}")
            item = dict(item or {"key": key})
            if (item.get("continue_from") or None) != prev:
                raise adopt.Refused(f"shot {n}: take {key} continues {item.get('continue_from') or 'nothing'} in "
                                    f"{entry['job']}, not {prev or 'nothing'}: list a take and its continuations in order")
            v = film._probe_video(path)
            if f"{v['width']}x{v['height']}" != shots[n].get("wan_res"):
                raise adopt.Refused(f"shot {n}: take {key} is {v['width']}x{v['height']}, but the approved plan's "
                                    f"wan_res is {shots[n].get('wan_res')}")
            frames += v["frames"] - (1 if k else 0)
            mj = src.motion.get(key)
            if mj is not None:
                if not Path(mj[0]).is_file() or sha256_file(mj[0]) != mj[1]:
                    mj = None   # an edited or missing verdict never passes: gated again on adoption
            chain.append({"key": key, "file": f"{key}.mp4", "sha256": sha, "frames": v["frames"],
                          "motion_gate": "recorded at import" if mj else "gated on adoption"})
            items.append({**{k_: v_ for k_, v_ in item.items() if k_ not in ("prompt", "negative_prompt")},
                          "key": key, "shot": n, "continue_from": prev, "width": v["width"], "height": v["height"],
                          "source_job": src.job_id})
            files.append((path, f"clips/{key}.mp4", sha, key, mj))
            prev = key
        if not shotplan.chain_covers(len(takes), need[n]) or frames < need[n] + shotplan.CHAIN_MARGIN:
            raise adopt.Refused(f"shot {n} renders {need[n]} frames plus a {shotplan.CHAIN_MARGIN}-frame margin, but "
                                f"the take {' -> '.join(takes)} plays {frames}: adopt its continuation too, or re-plan")
        art = entry.get("art")
        if art:
            a_path = (base / art.get("file", "")).resolve()
            if not a_path.is_file() or not (art.get("reason") or "").strip():
                raise adopt.Refused(f"shot {n}: \"art\" needs an existing \"file\" and the operator's \"reason\" "
                                    "(a hand-copied file)")
            a_sha = sha256_file(a_path)
            start = (src.item(takes[0]) or {}).get("image")
            want = src.images.get(start) if start else None
            if a_sha != want:
                raise adopt.Refused(f"shot {n}: art {a_path.name} (sha256 {a_sha[:12]}...) is not the start image "
                                    f"{start or '(none recorded)'} the take {takes[0]} was made from")
            art = {"file": _rel(a_path, rec.root), "sha256": a_sha, "reason": art["reason"].strip(),
                   "relation": f"identical to the start image {start} of {src.job_id} item {takes[0]}"}
        binding[str(n)] = {"source": {k: src.prov.get(k) for k in ("origin", "record", "folder", "job_id", "kind",
                                                                   "input_zip_sha256", "verified_against") if src.prov.get(k)},
                           "takes": chain, "frames": frames, "needs_frames": need[n] + shotplan.CHAIN_MARGIN,
                           "licence": lic, **({"art": art} if art else {})}
    return binding, files, items


def _adopt_depth(rec, spec, sid, t, shots, still_binding, load):
    binding, files, depth_stills = {}, [], {}
    picks = None
    for key, entry in sorted((spec.get("depth") or {}).items()):
        n = int(key.rpartition("-")[2]) if key.startswith(sid + "-") and key.rpartition("-")[2].isdigit() else None
        if n not in shots or shots[n]["motion"] != "glide" or (shots[n].get("camera") or {}).get("flat"):
            raise adopt.Refused(f"depth {key!r}: not a layered (non-flat) glide shot of scene {sid}")
        if not isinstance(entry, dict) or not entry.get("job") or not entry.get("file"):
            raise adopt.Refused(f"depth {key}: needs \"job\" and \"file\" (<stem>.depth.png of a film_clips job)")
        src = load(entry["job"])
        name = Path(entry["file"]).name
        if src.kind != "film_clips" or not name.endswith(".depth.png"):
            raise adopt.Refused(f"depth {key}: {entry['job']}/{name} is not a film_clips job's depth map")
        path, sha = src.file(name)
        lic = src.licence("depth")
        if key in still_binding:
            still_sha = (still_binding[key].get("source") or still_binding[key].get("hand_copied"))["sha256"]
        else:
            picks = _scene_picks(rec, t, sid) if picks is None else picks
            if key not in picks:
                raise adopt.Refused(f"depth {key}: shot {n} has no picked still: a depth map is adopted only for the "
                                    "exact still it was made from")
            still_sha = picks[key]["sha256"]
        made_from = src.depth_image_sha(name)
        if made_from != still_sha:
            raise adopt.Refused(f"depth {key}: {src.job_id}/{name} was made from an image with sha256 "
                                f"{(made_from or 'unknown')[:12]}..., but the picked still of {key} is {still_sha[:12]}...: "
                                "no depth map matches it (a depth-only film_clips job makes one)")
        depth_stills[f"{key}.png"] = still_sha
        binding[key] = {"source": {k: src.prov.get(k) for k in ("origin", "record", "folder", "job_id",
                                                                 "verified_against") if src.prov.get(k)},
                        "file": name, "sha256": sha, "still_sha256": still_sha, "licence": lic,
                        **({"depth_model_evidence": src.prov["depth_model_evidence"]}
                           if src.prov.get("depth_model_evidence") else {})}
        files.append((path, f"depth/{key}.depth.png", sha, key, None))
    return binding, files, depth_stills


def _adopt_music(spec, load):
    entry = spec.get("music")
    if not entry:
        return {}, [], []
    if not isinstance(entry, dict) or not entry.get("job"):
        raise adopt.Refused('"music" needs "job" (and optional "keys", "roles": {"<key>": drone|solo|phrase})')
    src = load(entry["job"])
    if src.kind != "music":
        raise adopt.Refused(f"music: {entry['job']} is a {src.kind} job, not a music job")
    lic = src.licence("music")
    names = {Path(n).stem: n for n in src.files if Path(n).suffix.lower() in cue.STEM_EXTS}
    keys = entry.get("keys") or sorted(names)
    roles = entry.get("roles") or {}
    bad = [k for k in keys if k not in names] + [k for k in roles if k not in keys]
    if bad:
        raise adopt.Refused(f"music: {', '.join(bad)} is not a stem of {src.job_id} being adopted")
    wrong = [f"{k}={r}" for k, r in roles.items() if r not in cue.ROLES]
    if wrong:
        raise adopt.Refused(f"music: roles must be one of {', '.join(cue.ROLES)} ({', '.join(wrong)})")
    files, items, stems = [], [], {}
    for k in keys:
        path, sha = src.file(names[k])
        files.append((path, names[k], sha, k, None))
        item = dict(src.item(k) or {"key": k})
        if roles.get(k):
            item["role"] = roles[k]
        items.append(item)
        stems[k] = {"file": names[k], "sha256": sha, **({"role": roles[k]} if roles.get(k) else {})}
    binding = {"source": {k: src.prov.get(k) for k in ("origin", "record", "folder", "job_id", "input_zip_sha256",
                                                       "verified_against") if src.prov.get(k)},
               "stems": stems, "licence": lic}
    return binding, files, items


def _adopt_write(rec, t, sid, jid, kind, doc, files, gate_overrides, picks=None):
    """Place one adopted job's files (hard links, else copies, each re-verified), its adoption.json and its record
    rows, all or nothing. Clips without a recorded motion verdict are gated now; a clear fail stops."""
    dest = rec.root / ADOPT_DIRS[kind] / jid
    jobs_dir = rec.root / "jobs" / jid
    if dest.exists() or jobs_dir.exists():
        raise adopt.Refused(f"{dest} or {jobs_dir} already exists")
    stage = Path(tempfile.mkdtemp(dir=rec.root, prefix=".adopt-"))
    try:
        gates = []
        for src, rel, sha, key, mj in files:
            out = stage / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, out)
            except OSError:
                shutil.copy2(src, out)
            if sha256_file(out) != sha:
                raise adopt.Refused(f"the copy of {src} differs from it")
            if kind == "stills" and Path(src).with_name(Path(src).stem + ".gate.json").is_file():
                shutil.copy2(Path(src).with_name(Path(src).stem + ".gate.json"), out.with_name(out.stem + ".gate.json"))
            if rel.startswith("clips/"):
                if mj:
                    shutil.copy2(mj[0], out.with_name(f"{key}.motion.json"))
                    contact = Path(mj[0]).with_name(f"{key}.contact.png")
                    if contact.is_file():
                        shutil.copy2(contact, out.with_name(contact.name))
                    gate = json.loads(Path(mj[0]).read_text(encoding="utf-8"))
                else:
                    gate = motiongate.gate_clip(out)
                if gate.get("pass") is False and key not in gate_overrides:
                    raise adopt.Refused(f"take {key} failed the motion gate ({'; '.join(map(str, gate.get('notes') or []))}); "
                                        f"record why it stands in picks/gate-overrides.json ({{\"{key}\": \"<reason>\"}}) "
                                        "or adopt another take")
                gates.append((key, gate))
        dest.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(dest)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    snapshot = (list(rec.data["artifacts"]), list(rec.data["events"]))
    try:
        doc = {**doc, "files": {rel: sha for _, rel, sha, _, _ in files},
               "motion_gates": {k: {x: g.get(x) for x in ("pass", "needs_review", "notes")} for k, g in gates}}
        path = _write_json(jobs_dir / "adoption.json", doc)
        meta = {"job_id": jid, "job_kind": kind, "adopted": True}
        rec.add_artifact(ADOPT_JOB, path, {**meta, "forecast_units": 0.0, "manifest": f"jobs/{jid}/adoption.json",
                                           "scene": sid})
        rec.event("cli", "job_target", {"job_id": jid, "target": t, "kind": kind, "scene": sid, "adopted": True})
        arts = []
        for src, rel, sha, key, _ in files:
            arts.append(rec.add_artifact(kind, dest / rel, {**meta, "adopted_from": str(src), "key": key}))
            gj = (dest / rel).with_name(Path(rel).stem + ".gate.json")
            if kind == "stills" and gj.is_file():
                rec.add_artifact(kind, gj, {**meta, "key": key})
        for key, _ in gates:
            rec.add_artifact("motion_gate", dest / "clips" / f"{key}.motion.json",
                             {**meta, "clip": f"{key}.mp4"})
        rec.event("import", "accepted", {"job_id": jid, "kind": kind, "actual_units": 0, "adopted": True,
                                         "files": [a["path"] for a in arts], "adoption_sha256": sha256_file(path)})
        if picks:
            ppath = _write_json(rec.root / "picks" / f"{jid}.pick-1.json", {"job_id": jid, "choices": picks,
                                                                            "adopted": True})
            rec.add_artifact("stills_pick", ppath, {"job_id": jid, "choices": picks, "version": 1, "adopted": True})
            rec.event("pick", "recorded", {"job_id": jid, "version": 1, "adopted": True,
                                           "choices": {k: v["candidate"] for k, v in picks.items()}})
    except BaseException:
        try:
            rec.rollback(snapshot)
        finally:
            shutil.rmtree(dest, ignore_errors=True)
            shutil.rmtree(jobs_dir, ignore_errors=True)
        raise
    return gates


def cmd_adopt(args):
    """G1: bind already-imported media (stills, Wan takes, depth maps, a music job) to one scene's approved shots,
    verified file by file and recorded as adopted jobs with their picks; 0 CU, idempotent."""
    rec = _record(args.root)
    spec_path = Path(args.spec)
    spec = _json(spec_path)
    base = spec_path.resolve().parent
    sid = spec.get("scene") if isinstance(spec, dict) else None
    if not isinstance(sid, str) or (args.scene and args.scene != sid):
        raise Stop("adopt.json needs \"scene\" (and --scene, if given, must name the same scene)",
                   "Fix adopt.json and rerun")
    args.scene = sid   # G6: the Next: line follows this scene
    plan = _plan(rec)
    i = next((k for k, f in enumerate(plan["plan"]["films"], 1) if any(sc["scene_id"] == sid for sc in f["scenes"])),
             None)
    if i is None:
        raise Stop(f"scene {sid} is not in the plan", f"{PROG} status --root {rec.root}")
    t = _film_target(i)
    film_dir = rec.root / "film" / t
    try:   # R11: media is bound to the shots of the approved paper edit only
        sp = shotplan.require_approved(film_dir, sid)
    except shotplan.NotApproved as e:
        raise Stop(f"not adopted: {e}", f"{PROG} plan-shots --root {rec.root} --film {i} --scene {sid} (approve it)")
    shots = {s["n"]: s for s in sp["shots"]}
    plan_sha = sha256_file(shotplan.paths(film_dir, sid)["plan"])
    overrides = {}
    gpath = rec.root / "picks" / "gate-overrides.json"
    if gpath.is_file():
        overrides = {k: v for k, v in _json(gpath).items() if isinstance(v, str) and v.strip()}
    advisories = {}
    try:
        load, everything = _adopt_sources(rec, spec, base)
        stills, still_files = _adopt_stills(rec, spec, base, sid, shots, load, everything, advisories)
        clips, clip_files, clip_items = _adopt_clips(rec, spec, base, sid, sp, shots, load)
        depth, depth_files, depth_stills = _adopt_depth(rec, spec, sid, t, shots, stills, load)
        music, music_files, music_items = _adopt_music(spec, load)
        if not (stills or clips or depth or music):
            raise adopt.Refused("adopt.json binds nothing (\"stills\", \"clips\", \"depth\", \"music\")")
        groups = []
        if stills:
            groups.append(("stills", "stills", {"stills": stills}, still_files,
                           {"scene": sid, "items": [{"key": f"{k}--c1", "base": k, "candidate": 1} for k in stills]}))
        if clips or depth:
            groups.append(("clips", "film_clips", {"clips": clips, "depth": depth}, clip_files + depth_files,
                           {"scene": sid, "items": clip_items, **({"depth_stills": depth_stills} if depth_stills else {})}))
        if music:
            groups.append(("music", "music", {"music": music}, music_files, {"scene": sid, "items": music_items}))
        known = {j["job_id"] for j in _jobs(rec)}
        done, kept = [], []
        for tag, kind, binding, files, job in groups:
            jid = adopt.binding_id(sid, tag, {"binding": binding, "plan_sha256": plan_sha, "target": t})
            if jid in known:
                kept.append(jid)
                continue
            doc = {"schema": adopt.SCHEMA, "job_id": jid, "kind": kind, "target": t, "scene": sid,
                   "plan_sha256": plan_sha, "binding": binding, "job": job, "spent_cu": 0,
                   "spec": {"path": _rel(spec_path, rec.root), "sha256": sha256_file(spec_path)}}
            picks = None
            if kind == "stills":
                picks = {k: {"candidate": 1, "file": f"stills/{jid}/{rel}", "sha256": sha}
                         for _, rel, sha, k in files}
            files = [f if len(f) == 5 else (*f, None) for f in files]
            gates = _adopt_write(rec, t, sid, jid, kind, doc, files, overrides, picks)
            done.append((jid, kind, len(files), gates))
    except adopt.Refused as e:
        raise Stop(f"not adopted: {e}. Nothing more was written", "Fix adopt.json (or the source it names) and rerun; "
                   "never edit a job's manifest or recorded sha256")
    if not done:
        print(f"Already adopted for scene {sid}: {', '.join(kept)}; nothing changed (0 CU).")
        return 0
    for jid, kind, count, gates in done:
        print(f"Adopted {count} file(s) as {kind} job {jid} for scene {sid} of {t}: verified by sha256, licences and "
              "provenance recorded, 0 CU" + (" (picks recorded)" if kind == "stills" else "") + ".")
        for key, g in gates:
            if g.get("needs_review") or g.get("pass") is False:
                print(f"MOTION REVIEW {key}: {'; '.join(map(str, g.get('notes') or [])) or 'needs review'} "
                      f"(passed on the recorded override: {overrides[key]})" if key in overrides else
                      f"MOTION REVIEW {key}: {'; '.join(map(str, g.get('notes') or [])) or 'needs review'}; look at its "
                      "contact sheet before the owner sees the cut.")
    for key, why in sorted(advisories.items()):
        print(f"WARNING {key}: {why}")
    if kept:
        print(f"Unchanged (already adopted): {', '.join(kept)}.")
    unbound = [f"{sid}-{s['n']}" for s in _depth_shots(sp)
               if f"{sid}-{s['n']}" not in depth and (f"{sid}-{s['n']}.png", (_scene_picks(rec, t, sid).get(
                   f"{sid}-{s['n']}") or {}).get("sha256")) not in _depth_maps(rec, t)]
    if unbound:
        print(f"Note: glide still(s) {', '.join(unbound)} have no depth map yet; film --shots refuses them until a "
              "matching depth map is adopted or a depth-only film_clips job makes one.")
    return 0


COMMANDS = {"init": cmd_init, "plan": cmd_plan, "job": cmd_job, "import": cmd_import,
            "import-take": cmd_import_take, "split-passages": cmd_split_passages,
            "supersede": cmd_supersede, "close": cmd_close, "pick": cmd_pick, "hold": cmd_hold, "touchup": cmd_touchup, "clip-touchup": cmd_clip_touchup, "glide": cmd_glide, "retime": cmd_retime, "voicecheck": cmd_voicecheck, "motiongate": cmd_motiongate, "facegate": cmd_facegate,
            "cue": cmd_cue, "plan-shots": cmd_plan_shots, "scene-timing": cmd_scene_timing,
            "exchange-stage": cmd_exchange_stage, "exchange-collect": cmd_exchange_collect,
            "film": cmd_film, "reel": cmd_reel, "qc": cmd_qc, "status": cmd_status,
            "bundle-audio": cmd_bundle_audio,
            "bundle-film": cmd_bundle_film, "adopt": cmd_adopt}


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
    s.add_argument("--title-caps", help="the owner's title-caps.json to pin (default: the one beside the ledger, "
                                        "else the nearest one above it)")
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
    s.add_argument("--resume", metavar="JOB_ID",
                   help="film_clips: reserve and write a resume session for a job its hard stop cut short")
    s.add_argument("--from", dest="source",
                   help="with --resume: the partial download (done.json and the finished clips) to skip")
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
    s.add_argument("--cps", type=float, default=passages.CPS_BN,
                   help="Eleven v4 passages: characters per second of narration, for each passage's expected "
                        f"duration (default {passages.CPS_BN:g}, an estimate; use the rate of the first real takes)")
    s.add_argument("--scene", help="Eleven v4 passages: import only this scene id (default: every scene whose "
                                   "<scene>-p01.txt is present)")
    s.add_argument("--profile", help="Eleven v4 passages: saved voicecheck-profile.json (default: the title's "
                                     "saved one under film/film-NN/voice/passages, else measured and saved)")
    s.add_argument("--transcripts", help="Eleven v4 passages: transcripts.json from the Colab words cell, keyed by "
                                         "<passage id>: turns on the Whisper word check (else recorded as not run)")
    s.add_argument("--no-retime", action="store_true",
                   help="Eleven v4 passages: the takes are already retimed (an owner-endorsed take): import them with "
                        "their pauses as they are; recorded in the passage manifest and the passages_checked event")
    s.add_argument("--accept", action="append", metavar="PID=reason",
                   help="Eleven v4 passages: join this passage despite its voicecheck failures (repeatable; the "
                        "reason is recorded in the passage manifest and the passages_checked event)")
    s = add("split-passages", help="write the untagged passage scripts of a film (Eleven v4)")
    s.add_argument("target", help="film-NN")
    s.add_argument("--out", required=True, help="folder for <scene_id>-p<NN>.txt")
    s.add_argument("--cps", type=float, default=passages.CPS_BN, help="characters per second used to size passages")
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
    s.add_argument("--override", action="append", metavar="KEY=reason",
                   help="pick a candidate whose gate needs review after gate-calibration.json exists (repeatable; "
                   "the reason is recorded in the pick and its event)")
    s.add_argument("--override-fail", action="append", metavar="KEY=reason",
                   help="pick a candidate whose gate is a certain fail (repeatable; the reason is recorded)")
    s = add("adopt", help="bind already-imported media (stills, Wan takes, depth maps, music) to one scene's approved "
                          "shots, verified by sha256, with recorded picks, licences and provenance; 0 CU")
    s.add_argument("--spec", required=True, help='adopt.json {"scene", "sources", "stills", "clips", "depth", "music"}')
    s.add_argument("--scene", help="the scene adopt.json binds (checked against its \"scene\")")
    s = add("hold", help="show the nearest approved still of the scene for shots with none yet")
    s.add_argument("--film", type=int, default=1)
    s.add_argument("--keys", help="comma-separated held still keys, e.g. f01s007-4,f01s007-5")
    s.add_argument("--clear", action="store_true", help="remove all holds of the film")
    s = add("clip-touchup", help="remove a small fixed defect from imported Wan clips into new clips (local)")
    s.add_argument("--film", type=int, required=True)
    s.add_argument("--spec", required=True, help='{"scene", "items": [{"key", "reason", "source": {"job", "file"}, '
                                                 '"mask", "fill", "mode"}]} (eav/cliptouch.py)')
    s.add_argument("--job-id", required=True)
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
    s = sub.add_parser("motiongate", help="motion gate for Wan takes: stutter, jumps, contact sheet (standalone: no record; clips untouched)")
    s.add_argument("clips", nargs="+", help="clip .mp4 files or folders of them")
    s.add_argument("--out", help="folder for <key>.motion.json and <key>.contact.png (default: beside each clip)")
    s = sub.add_parser("facegate", help="face/eye anomaly gate for clips and stills: double or missing pupils, "
                       "asymmetry, eyes off the face (takes only), morphing, LED-like glows; face close-up sheet "
                       "(standalone: no record; media untouched)")
    s.add_argument("media", nargs="+", help="clip or still files, or folders of them")
    s.add_argument("--out", help="folder for <key>.face.json and <key>.faces.png (default: beside each file)")
    s.add_argument("--fresh", action="store_true", help="re-measure even when a matching face.json exists")
    s.add_argument("--expect-face", action="store_true",
                   help="every file shows a character: one where no face is judged is a review finding, not a pass")
    s = sub.add_parser("voicecheck", help="narration redo gate: flag robotic/monotone/flawed takes (standalone: no record)")
    s.add_argument("takes", nargs="+")
    s.add_argument("--expected", required=True, help="expected duration in seconds: one value, or one per take (comma-separated)")
    s.add_argument("--profile", help="saved voicecheck-profile.json; always pass it on redo runs (default: measured from the given takes and saved)")
    s.add_argument("--prev-tail", help="the take before the first listed one, for the join check")
    s.add_argument("--out", help="folder for the profile and results (default: beside each take)")
    s.add_argument("--transcripts", help="transcripts.json from the Colab words cell (Whisper): turns on the word check")
    s.add_argument("--sources", help="with --transcripts: folder of <take-stem>.txt, the untagged book text of each take")
    s = add("plan-shots", help="the paper edit: shot plan and two-column AV script for one scene (R11)")
    s.add_argument("--film", type=int, required=True)
    s.add_argument("--scene", required=True)
    s.add_argument("--bible", help="world bible (default <root>/specs/world-bible.json)")
    s.add_argument("--approve", action="store_true", help="record the approval; needs --by and --reviewer")
    s.add_argument("--by")
    s.add_argument("--reviewer")
    s = add("scene-timing", help="measured clause timing of a scene's voice for plan-shots (R9 lead-in, R4 tail)")
    s.add_argument("--film", type=int, required=True)
    s.add_argument("--scene", required=True)
    s.add_argument("--min-pause", type=float, default=TIMING_MIN_PAUSE_S,
                   help=f"shortest pause that ends a clause (default {TIMING_MIN_PAUSE_S:g} s)")
    s.add_argument("--threshold-db", type=float, default=-38.0, help="silence threshold (default -38 dBFS)")
    s = add("cue", help="per-scene music cue and film mix from ACE-Step stems (peak silence, smooth ducking)")
    s.add_argument("--film", type=int, default=1)
    s.add_argument("--scene")
    s.add_argument("--stems", required=True, help="imported music job id (music/<job>/<key>.wav)")
    s.add_argument("--pick", action="store_true", help="measure the stems and save the choice (needs --tonic)")
    s.add_argument("--tonic", help="e.g. D, F#, Bb (with --pick)")
    s.add_argument("--drone")
    s.add_argument("--solo")
    s.add_argument("--phrase")
    s.add_argument("--voice", help="the scene's re-timed narration wav (default film/film-NN/voice/<scene>.wav)")
    s.add_argument("--fx", help="json {ambience: [...], foley: [...]}")
    s = add("film")
    s.add_argument("--film", type=int, default=1)
    s.add_argument("--logo", required=True)
    s.add_argument("--end-card", required=True)
    s.add_argument("--score")
    s.add_argument("--score-route", help="vcsl or ace-step:<imported music job id>")
    s.add_argument("--cues-job")
    s.add_argument("--shots", action="store_true",
                   help="cinematic film: render every scene's approved shot plan (glide/Wan/static) from "
                        "film/film-NN/shots, join with the scene mixes (film/film-NN/audio), captions and cards")
    s.add_argument("--burn", action="store_true", help="--shots: also write a burned-in captions rendition")
    s.add_argument("--title", help="--shots: the title card's title")
    s.add_argument("--author", help="--shots: the author, for the title and credits cards")
    s.add_argument("--narrator", help="--shots: the narration voice credited on the credits card")
    s.add_argument("--fonts", help="--shots: Maison fonts folder (default static/maison/fonts)")
    s.add_argument("--scene", help="--shots: assemble this one scene (e.g. f01s014) into film-NN-<scene>.mp4 for its "
                                   "review; the whole film still needs every scene")
    s = add("reel")
    s.add_argument("n", type=int)
    s.add_argument("--script")
    s.add_argument("--plan-shots", action="store_true",
                   help="plan the shots from the imported, measured reel narration")
    s.add_argument("--score")
    s.add_argument("--score-route", help="vcsl or ace-step:<imported music job id>")
    s.add_argument("--hashtags", nargs="*")
    add("qc")
    s = add("status")
    s.add_argument("--scene", help="the next step of this one scene (e.g. f01s014): its cinematic flow, then film "
                                   "--shots --scene, qc and review; without it the whole film from its first scene")
    s = add("bundle-audio")
    s.add_argument("--out", required=True)
    s.add_argument("--score-dir", help="<unit_id>.wav score bed per chapter (default route)")
    s.add_argument("--score-route", help="with --score-dir: vcsl or ace-step:<imported music job id>")
    s.add_argument("--dry", action="store_true", help="narration only; recorded in the evidence draft")
    s.add_argument("--profile", choices=("audiobook", "film"), default="audiobook",
                   help="audiobook (default): own master, chapters, sentence timing; "
                        "film: the film-level -16 LUFS stereo 96 kbps master")
    s.add_argument("--frame-dir", help="audiobook: <dir> with title.wav, author.wav and closing.wav "
                                       "(the spoken opening and closing word)")
    s = add("bundle-film")
    s.add_argument("--film", required=True, help="film id, e.g. film-01")
    s.add_argument("--unit-id", required=True, help="the Maison unit UUID the film belongs to")
    s.add_argument("--out", required=True)
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        rc = COMMANDS[args.command](args)
        if rc:
            return rc
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
        print(f"Next: {next_action(args.root, _route_scene(args))}")
    return 0


SCENE_ROUTE = ("status", "film", "adopt", "import-take", "scene-timing", "plan-shots", "cue")   # G6: --scene scopes Next:


def _route_scene(args):
    return getattr(args, "scene", None) if args.command in SCENE_ROUTE else None


if __name__ == "__main__":
    sys.exit(main())
