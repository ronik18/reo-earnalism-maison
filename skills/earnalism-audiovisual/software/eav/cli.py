"""earnalism-audiovisual orchestrator: one title root, one production record, one next action.

  python3 -m eav.cli init <source.json> --root <dir> [--slug <maison-edition-slug>]
  python3 -m eav.cli plan --root <dir>
  python3 -m eav.cli job <narration|stills|music|reel_clips> --root <dir> --rates <rates.json>
                         [--film N | --reel N] [--spec <spec.json>] [--clause "..."]
                         (narration/stills forecast over 3600 s: built as chunks <id>-c<i>of<n>, each
                          its own job of <= 3600 s; the caps are checked once for the sum)
  python3 -m eav.cli job <narration|stills> --root <dir> --rates <rates.json> --replace-chunk <closed chunk id>
                         (rebuilds only that chunk's items as <chunk id>-r<k>; the group keeps its other chunks)
  python3 -m eav.cli import <job_id> --root <dir> --from <folder|archive> [--units <CU>]
                         [--archive-sha256 <sha>]           (reel_clips)
  python3 -m eav.cli modal-run <job_id> --root <dir> --colab-units <CU, 0 if none> [--download <dir>] [--dry-run]
                         (runs the built notebook headlessly on a Modal L4; --dry-run only checks and prints the plan;
                          leaves the job folder `import` expects; refuses (exit 3) past the 30 USD UTC-month or the
                          6 USD lifetime title Modal cap; keeps --colab-units (the CU Colab already showed for the job)
                          on the Colab caps and releases the rest of its CU reservation (Modal is capped in USD only);
                          appends the actual spend to the ledger; then import/close take --units only for Colab work
                          after the move)
  python3 -m eav.cli modal-request <job_id> --root <dir> --colab-units <CU, 0 if none>
                         (no Modal access here: the same checks, move and pending worst-case row as modal-run,
                          then production/audiovisual/modal-requests/<job_id>.json for the modal-jobs workflow,
                          which runs `r2-probe`, `modal-run --request` (caps re-checked for the run month) and
                          `r2-upload` (`modal-replay` re-applies a result after a push conflict); root commits
                          and pushes the request. A request refused before Modal was contacted releases its
                          row and restores the job's CU reservation)
  python3 -m eav.cli modal-request <job_id> --root <dir> --abandon --reason "<why>"
                         (a `running` request whose run never reached Modal (no modal_contacted_at): refused,
                          its pending row released and the CU reservation restored)
  python3 -m eav.cli modal-fetch <job_id> --root <dir> [--into <dir>]
                         (a finished request: download its job folder from private R2, sha256-verified; never imports)
  python3 -m eav.cli modal-settle <job_id> --root <dir> --usd <billed> [--run <run_id>]
                         (reconcile from the Modal bill: the job's pending row(s), else its one unbilled finished
                          row, or the named run; the row records billed: true and keeps estimated_usd)
  python3 -m eav.cli supersede <job_id> --root <dir> --reason "<why it never ran>" [--group]
                         (a chunk only with --group: every never-run chunk of its group together)
  python3 -m eav.cli close <job_id> --root <dir> [--units <CU Colab shows>] --reason "<what happened>"
  python3 -m eav.cli film --root <dir> [--film N] --logo <png> --end-card <png>
                         (--score <wav> --score-route vcsl|ace-step:<job_id> | --cues-job <id>)
  python3 -m eav.cli reel <n> --root <dir> --script <script.json> [--hashtags ...]
  python3 -m eav.cli reel <n> --root <dir> --plan-shots           (after reel narration import)
  python3 -m eav.cli reel <n> --root <dir> [--score <wav> --score-route ...]
  python3 -m eav.cli qc --root <dir>
  python3 -m eav.cli status --root <dir>
  python3 -m eav.cli bundle-audio --root <dir> --out <bundle dir>
                         (--score-dir <dir> --score-route vcsl|ace-step:<job_id> | --dry)
  python3 -m eav.cli preview --root <dir> --bundle <bundle dir> --out <preview dir>
                         (public preview clip of chapter 1: <= 120 s, <= 2 MiB, 96 kbps MP3)

Every command ends with "Next: ..." -- the one action the owner (or Claude) takes next.
Reels: script -> reel narration (measured) -> --plan-shots (ceil(narration / 5.04 s) Wan clips)
-> keyframe stills -> reel_clips batches of <= 5 shots (one Wan job each) -> reel.
The CLI wraps the eav modules; it spends nothing, runs no GPU work, never marks legal clearance
and never publishes. Exit codes: 0 ok, 2 stop, 3 budget exceeded, 4 import held, 5 QC failure.
The allowance ledger is shared by every title and pinned in record.json at init (--ledger,
else $EAV_LEDGER, else <root>/../allowance-ledger.json); later commands refuse any other path.
The 60 CU title cap is lifetime; the 100 CU cap is per calendar month; both are Colab-only.
Modal: 30 USD per UTC month and 6 USD per title (lifetime), in dollars only.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from . import (budget, colab_jobs, film, importer, mix, modal_requests, modal_run, preview,
               qc, reel, scenes, social)
from .record import Record, sha256_file
from .text import sentences
from .voice import voice_units

PROG = "python3 -m eav.cli"
ROSTER = (Path(__file__).resolve().parents[3] / "earnalism-audiobook-go-live" / "references"
          / "final-voice-roster.json")
STORY_PROFILE = {"en": "en_tisha", "bn": "bn_arnav"}
EVIDENCE_SCHEMA = "earnalism.audiovisual-clearance-evidence.v1"
EVIDENCE_DRAFT = "audiovisual-clearance-evidence.draft.json"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
SHA = re.compile(r"[0-9a-f]{64}")
FILM_LUFS, REEL_LUFS, LUFS_TOL, TP_MAX = -16.0, -14.0, 1.0, -1.0
LOOP_MIN = 0.8
HOOK_ONSET_MAX_S = 0.2
MP3_END_SLACK_MS = 50


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
    targets, order = {}, {}
    for i, e in enumerate(events):
        if e["stage"] == "cli" and e["result"] == "job_target":
            targets[e["detail"]["job_id"]], order[e["detail"]["job_id"]] = e["detail"]["target"], i
    done = {r: {e["detail"]["job_id"] for e in events if e["stage"] == s_ and e["result"] == r}
            for s_, r in (("import", "accepted"), ("job", "superseded"), ("job", "closed"),
                          ("job", "superseding"), ("job", "closing"))}
    out = []
    for a in rec.data["artifacts"]:
        if a["kind"] != "colab_job":
            continue
        m = a["meta"]
        jid = m["job_id"]
        out.append({"job_id": jid, "kind": m["job_kind"], "target": targets.get(jid),
                    "order": order.get(jid, -1), "chunk": m.get("chunk"),
                    "notebook": rec.root / a["path"], "inputs_zip": rec.root / m["inputs_zip"],
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


def _logical(rec) -> list:
    """Jobs as consumers see them: a plain job, or one entry per chunk group (job_id = the group
    id). For each chunk index the group uses the imported chunk, else the latest live one (a
    closed or superseded chunk can be rebuilt with job --replace-chunk as <chunk id>-r<k>).
    `chunks` holds those, in index order; `all_chunks` every job of the group; `missing` the
    indices with no imported or live chunk (each names its latest, ended chunk). The group is
    imported when every index 1..of has an imported chunk; while an index is missing it is
    closed/superseded (it cannot complete until that index is replaced)."""
    out, groups = [], {}
    for j in _jobs(rec):
        c = j["chunk"]
        if not c:
            out.append({**j, "chunks": [j]})
            continue
        if c["group"] not in groups:
            groups[c["group"]] = {"job_id": c["group"], "kind": j["kind"], "target": j["target"],
                                  "order": j["order"], "all_chunks": [], "of": c["of"]}
            out.append(groups[c["group"]])
        groups[c["group"]]["all_chunks"].append(j)
    for g in groups.values():
        use, missing = [], {}
        for i in range(1, g["of"] + 1):
            mine = sorted((j for j in g["all_chunks"] if j["chunk"]["index"] == i),
                          key=lambda j: j["order"])
            done = [j for j in mine if j["imported"]]
            live = [j for j in mine if not _ended(j)]
            if done or live:
                use.append((done or live)[-1])
            elif mine:
                missing[i] = mine[-1]
        g.update(chunks=use, missing=missing,
                 imported=len(use) == g["of"] and all(j["imported"] for j in use),
                 superseded=any(j["superseded"] for j in missing.values()),
                 closed=any(j["closed"] for j in missing.values()),
                 unfinished=any(j["unfinished"] for j in g["all_chunks"]))
    return out


def _find(rec, job_id):
    """A plain job or chunk group by its id (as film/reel/plan records name it)."""
    return next((j for j in _logical(rec) if j["job_id"] == job_id), None)


def _dirs(rec, job) -> list:
    """Output folders of a job: one, or every chunk's in chunk order."""
    return [rec.root / job["kind"] / c["job_id"] for c in job["chunks"]]


def _one_dir(rec, job):
    dirs = _dirs(rec, job)
    return dirs[0] if len(dirs) == 1 else dirs


def _chunk_ids(job) -> list:
    return [c["job_id"] for c in job["chunks"]]


def _latest_job(rec, kind, target, imported=True, after=-1):
    """The latest live job (or complete chunk group, when imported=True) for kind and target."""
    found = [j for j in _logical(rec) if j["kind"] == kind and j["target"] == target
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
    job = _find(rec, narr_id)
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


def _title_spent(ledger, rec) -> float:
    """Lifetime spend of this title, keyed by the export's edition_id (R26)."""
    return ledger.spent(rec.data["title_slug"], None, rec.data["source"].get("edition_id"))


def _remaining(ledger, rec, month) -> float:
    return min(budget.TITLE_CAP - _title_spent(ledger, rec),  # title cap: lifetime
               budget.MONTH_CAP - ledger.spent(None, month))


def _measured_track(rec, units, job, out: Path):
    """film.narration_track over the imported WAVs of a narration job (or every chunk of its
    group, in order), plus provenance of what was measured."""
    wav_dir = _one_dir(rec, job)
    timing = film.narration_track(units, wav_dir, out)
    provenance = {"method": "eav.film.narration_track", "measured_with": "ffprobe",
                  "narration_job_id": job["job_id"],
                  "wav_sha256": {u["unit_key"]: sha256_file(film.unit_wav(wav_dir, u["unit_key"]))
                                 for u in units},
                  "track_sha256": sha256_file(out)}
    if "of" in job:  # a chunk group
        provenance["narration_chunk_job_ids"] = _chunk_ids(job)
    return timing, provenance


def _incomplete(rec, kind, target) -> str:
    """' (<group>: k of n chunks imported)' for a live chunk group not fully imported, else ''."""
    found = [g for g in _logical(rec) if g["kind"] == kind and g["target"] == target and "of" in g
             and not g["superseded"] and not g["imported"]]
    if not found:
        return ""
    g = found[-1]
    return (f" ({g['job_id']}: {sum(c['imported'] for c in g['chunks'])} of {g['of']} chunks "
            "imported; incomplete)")


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


def _on_modal(rec, job_id) -> bool:
    pinned = rec.data.get("ledger")
    if not pinned or Path(pinned).is_absolute():
        return False
    return budget.Ledger((rec.root / pinned).resolve()).is_modal_job(job_id)


def _colab_action(rec, job) -> str:
    if job["kind"] == "reel_clips":
        return _wan_action(rec, job)
    if _on_modal(rec, job["job_id"]):  # moved to Modal: Modal dollar caps for the Modal portion
        return (f"Job {job['job_id']} runs on Modal (the rest of its CU reservation is released). "
                f"Import its output: {PROG} import {job['job_id']} --root {rec.root} --from <the "
                f"output folder> (add --units <CU> only for Colab work after the move). If it stopped "
                f"short, rerun {PROG} modal-run {job['job_id']} --root {rec.root} --colab-units <CU "
                f"Colab showed for this job in total> to resume; if a run died with a pending row: "
                f"{PROG} modal-settle {job['job_id']} --root {rec.root} --usd <billed>. If it can "
                f"never be imported: {PROG} close {job['job_id']} --root {rec.root} --reason "
                f"\"<what happened>\" (--units only for Colab work after the move)")
    drive = _json(job["manifest"]).get("drive_dir", colab_jobs.DRIVE_ROOT)
    c = job.get("chunk")
    part = (f" (chunk {c['index']} of {c['of']} of group {c['group']}; each chunk is its own job, "
            "run and imported on its own)" if c else "")
    return (f"Run the {job['kind']} notebook{part} in Colab: copy {job['inputs_zip']} to Drive {drive}/, "
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
                f"{PROG} supersede|close {j['job_id']} --root {root} command"
                + (" (supersede of a chunk: with --group)" if j["chunk"] else ""))
    for g in _logical(rec):  # a closed chunk is rebuilt on its own; the rest of the group is kept
        if "of" in g and g["closed"] and not g["superseded"]:  # superseded: the group was given up
            i, c = next((i, c) for i, c in sorted(g["missing"].items()) if c["closed"])
            return (f"Chunk {i} of {g['of']} of group {g['job_id']} ({c['job_id']}) ran but was closed; "
                    f"rebuild only that chunk's items: {PROG} job {g['kind']} --root {root} --rates "
                    f"<rates.json> --replace-chunk {c['job_id']} (the group's other chunks are kept). "
                    f"To give the whole group up instead: {PROG} supersede {c['job_id']} --root {root} "
                    "--group --reason \"<why>\"")
    pending = [j for j in jobs if not j["imported"] and not _ended(j)]
    if pending:
        return _colab_action(rec, pending[0])
    r = f"--root {root}"
    plan = _plan(rec)
    for i in range(1, len(plan["plan"]["films"]) + 1):
        t = _film_target(i)
        if not _latest_job(rec, "narration", t):
            return (f"{PROG} job narration {r} --film {i} --rates <rates.json with measured "
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
            return (f"Owner approves the reel {n} script ({folder / 'script.json'}); then: {PROG} job "
                    f"narration {r} --reel {n} --rates <rates.json>")
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
                    f"{' or '.join(map(str, _dirs(rec, stills)))}"
                    f"{' (the chunk folder holding the batch stills)' if 'of' in stills else ''}, "
                    f"prior_attempt_evidence = the retained Wan "
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
                f"vcsl|ace-step:<music job_id>. Maison video stays held (Stream cost not approved). "
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
    if kind == "narration":
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
        preset = {k: v for k, v in plan["voice"].items()
                  if k == "description" or k in colab_jobs.GENERATION_KEYS}
        spec = {"scenes": todo, "preset": preset,
                "language": lang, "clause": args.clause}
    else:
        if not args.spec:
            raise Stop(f"a {kind} job needs --spec (prompts, seeds{', shots' if kind == 'reel_clips' else ''})",
                       "Write it per references/film-recipe.md or references/reel-recipe.md")
        spec = _json(args.spec)
        if kind == "reel_clips" and not Path(spec.get("art_dir", ".")).is_absolute():
            spec["art_dir"] = str((Path(args.spec).parent / spec.get("art_dir", ".")).resolve())
        if kind == "reel_clips":
            _check_clip_batch(rec, args.reel, spec)
    if args.job_id:
        spec["job_id"] = args.job_id
    return spec, colab_jobs.job_items(kind, spec)


def _replace_chunk(rec, args):
    """Rebuild one closed (ran, not imported) or superseded chunk: exactly its own items, order and
    settings (from its job.json and build manifest), as <chunk id>-r<k>, cap-checked and reserved on
    its own. The group's other chunks are kept, and the group completes once it is imported."""
    old = next((j for j in _jobs(rec) if j["job_id"] == args.replace_chunk), None)
    if old is None or not old["chunk"]:
        raise Stop(f"{args.replace_chunk} is not a chunk of a chunked job", f"{PROG} status --root {rec.root}")
    if old["kind"] != args.kind:
        raise Stop(f"{args.replace_chunk} is a {old['kind']} chunk, not {args.kind}",
                   f"{PROG} job {old['kind']} --root {rec.root} --rates <rates.json> "
                   f"--replace-chunk {args.replace_chunk}")
    if args.spec or args.job_id or args.clause:
        raise Stop("--replace-chunk takes the chunk's own items and settings; --spec, --job-id and "
                   "--clause do not apply", "Drop them and rerun")
    c = old["chunk"]
    group = _find(rec, c["group"])
    if old["unfinished"] or not _ended(old):
        raise Stop(f"{args.replace_chunk} is {'imported' if old['imported'] else 'still live'}; only a "
                   "closed (ran, not imported) or superseded chunk is replaced",
                   next_action(rec.root))
    if c["index"] not in group["missing"]:
        live = next(j for j in group["chunks"] if j["chunk"]["index"] == c["index"])
        raise Stop(f"chunk {c['index']} of group {c['group']} already has {live['job_id']} "
                   f"({'imported' if live['imported'] else 'live'})", next_action(rec.root))
    k = 1 + sum(1 for j in group["all_chunks"]
                if j["chunk"]["index"] == c["index"] and j["job_id"] != colab_jobs.chunk_job_id(
                    c["group"], c["index"], c["of"]))
    job_dir = old["inputs_zip"].parent
    try:
        with zipfile.ZipFile(old["inputs_zip"]) as z:
            job_json = json.loads(z.read("job.json"))
        build = _json(old["manifest"])
        if sha256_file(old["inputs_zip"]) != build.get("inputs_sha256"):
            raise ValueError(f"inputs.zip of {old['job_id']} does not match its build manifest")
        replace = {"job_json": job_json, "build": build, "k": k}
        rates = _json(args.rates)
        compute = colab_jobs._replacement_plan(args.kind, job_json, build, rates)["compute"]
    except (KeyError, ValueError, zipfile.BadZipFile) as e:
        raise Stop(f"chunk {old['job_id']} cannot be replaced: {e}",
                   f"Check {job_dir} and the measured rates.json (references/compute-budget.md)")
    if budget.forecast_seconds(compute, rates) > colab_jobs.MAX_CHUNK_SECONDS:
        raise Stop(f"at the current rates chunk {c['index']} is forecast over "
                   f"{colab_jobs.MAX_CHUNK_SECONDS} s", "Hold for the owner: the measured rates changed")
    ledger, month = _ledger(rec, args), _month()
    units = budget.forecast(compute, rates)
    remaining = _remaining(ledger, rec, month)
    if units > remaining:
        raise Stop(f"Budget exceeded: forecast {units:.2f} CU > remaining {remaining:.2f} CU "
                   f"(caps {budget.TITLE_CAP:g}/title, {budget.MONTH_CAP:g}/month, {month}). "
                   "Nothing was reserved or written.",
                   "Hold the job and ask the owner; never retry past a cap.", code=3)
    try:
        result = colab_jobs.build_job(args.kind, rec, {}, ledger, rates, rec.root / "jobs",
                                      month=month, replace=replace)
    except budget.BudgetExceeded as e:
        raise Stop(f"Budget exceeded: {e}. Nothing was written.",
                   "Hold the job and ask the owner; never retry past a cap.", code=3)
    except (ValueError, FileExistsError, KeyError) as e:
        raise Stop(f"job not built: {e}", "Fix the input it names and rerun")
    rec.event("cli", "job_target", {"job_id": result["job_id"], "target": old["target"],
                                    "kind": args.kind, "chunk": {**c, "replaces": old["job_id"]}})
    print(f"Built {args.kind} job {result['job_id']} for {old['target']}: chunk {c['index']} of "
          f"{c['of']} of group {c['group']} again (replaces {old['job_id']}; the same "
          f"{compute['items']} items), forecast {units:.2f} CU reserved ({remaining - units:.2f} CU "
          "left under the title and month caps). Inert until the owner enables it.")


def cmd_job(args):
    rec = _record(args.root)
    kind = args.kind
    if args.replace_chunk:
        return _replace_chunk(rec, args)
    if kind == "reel_clips" and not args.reel:
        raise Stop("reel_clips jobs belong to one reel", "Pass --reel <n>")
    target = f"reel-{args.reel}" if args.reel else _film_target(args.film)
    rates = _json(args.rates)
    spec, items = _job_spec(rec, args, kind, target)
    try:  # R21: items and steps come from the job itself, rates from the last measured run
        compute = colab_jobs.derive_compute(kind, spec, rates, items)
    except ValueError as e:
        raise Stop(f"job not built: {e}", "Use the values measured on the last Colab run "
                   "(references/compute-budget.md) and never a compute block that differs from the job")
    try:
        sizes, unchunkable = colab_jobs.chunk_sizes(compute, rates), None  # [items] if <= 3600 s
    except ValueError as e:
        sizes, unchunkable = [items], e
    ledger, month = _ledger(rec, args), _month()
    # the caps see the whole job: the sum of every chunk's forecast, checked once
    units = sum(budget.forecast({**compute, "items": k}, rates) for k in sizes)
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
        whole = f" for all {len(sizes)} chunks of the job" if len(sizes) > 1 else ""
        raise Stop(f"Budget exceeded: forecast {units:.2f} CU{whole} > remaining {remaining:.2f} CU "
                   f"(caps {budget.TITLE_CAP:g}/title, {budget.MONTH_CAP:g}/month, {month}). "
                   "Nothing was reserved or written.", hint, code=3)
    if unchunkable is not None:
        raise Stop(f"job not built: {unchunkable}", "Check the measured rates.json (references/"
                   "compute-budget.md); hold for the owner if they are right")
    try:
        if len(sizes) == 1:
            results = [colab_jobs.build_job(kind, rec, spec, ledger, rates, rec.root / "jobs",
                                            month=month)]
            rec.event("cli", "job_target", {"job_id": results[0]["job_id"], "target": target,
                                            "kind": kind})
        else:
            results = _build_chunks(rec, kind, spec, ledger, rates, month, sizes, target)
    except budget.BudgetExceeded as e:
        raise Stop(f"Budget exceeded: {e}. Nothing was written.",
                   "Hold the job and ask the owner; never retry past a cap.", code=3)
    except (ValueError, FileExistsError, KeyError) as e:
        raise Stop(f"job not built: {e}", "Fix the spec and rerun")
    spent = sum(r["forecast_units"] for r in results)
    if len(results) == 1:
        print(f"Built {kind} job {results[0]['job_id']} for {target}: forecast {spent:.2f} CU "
              f"reserved ({remaining - spent:.2f} CU left under the title and month caps). "
              "Inert until the owner enables it in Colab.")
        return
    print(f"Built {kind} job for {target} as {len(results)} chunks of at most "
          f"{colab_jobs.MAX_CHUNK_SECONDS} forecast seconds each (one GPU session each): "
          + ", ".join(f"{r['job_id']} ({r['forecast_units']:.2f} CU)" for r in results)
          + f"; {spent:.2f} CU reserved in all ({remaining - spent:.2f} CU left under the title and "
          "month caps). Each chunk is its own job: run and import each one; film, bundle-audio and "
          "reels use the group only once every chunk is imported. Inert until the owner enables it.")


def _build_chunks(rec, kind, spec, ledger, rates, month, sizes, target) -> list:
    """Build every chunk as its own job (own id, inputs.zip, notebook, manifest, reservation), in
    item order. The caps were checked for the sum first; if a chunk still fails, every chunk built
    so far is removed, its reservation settled at 0 and the record restored (all or nothing)."""
    group = spec.get("job_id") or colab_jobs.new_job_id(kind)
    snapshot = (list(rec.data["artifacts"]), list(rec.data["events"]))
    built, start = [], 0
    try:
        for i, k in enumerate(sizes, 1):
            chunk = {"index": i, "of": len(sizes), "group": group, "start": start, "stop": start + k}
            result = colab_jobs.build_job(kind, rec, spec, ledger, rates, rec.root / "jobs",
                                          month=month, chunk=chunk)
            built.append(result)
            rec.event("cli", "job_target", {"job_id": result["job_id"], "target": target,
                                            "kind": kind, "chunk": {"index": i, "of": len(sizes),
                                                                    "group": group}})
            start += k
    except BaseException:
        for r in built:
            shutil.rmtree(Path(r["notebook"]).parent, ignore_errors=True)
            try:
                ledger.settle(r["job_id"], 0)  # release; nothing ran
            except Exception:
                pass  # never mask the original error
        rec.data["artifacts"], rec.data["events"] = snapshot
        rec._save()
        raise
    return built


def _modal_units(ledger, job_id, given):
    """Colab CU to settle. A Colab-run job needs --units. A job run on Modal (any Modal spend row,
    or moved to Modal) settles its Modal rows in USD and, against the CU caps, the Colab CU
    recorded at the move (modal-run --colab-units) plus --units for any Colab run after the move
    (optional, default 0)."""
    if not ledger.is_modal_job(job_id):
        if given is None:
            raise Stop(f"--units is required for job {job_id} (it has no Modal runs on the ledger)",
                       "Pass the CU Colab shows the run used")
        return given
    try:
        after = budget._check_units(0 if given is None else given)
    except ValueError as e:
        raise Stop(str(e), "Pass --units as the CU Colab showed after the move to Modal, >= 0")
    return round(ledger.colab_units_before_modal(job_id) + after, 6)


def _no_pending_modal(rec, ledger, job_id, what):
    """import and close settle the job from its Modal rows: never while one still holds a
    pending worst case (a run in flight, or one that died before recording its spend)."""
    pending = ledger.pending_modal_runs(job_id)
    if pending:
        raise Stop(f"job {job_id} has a pending Modal row ({', '.join(r['run_id'] for r in pending)}); "
                   f"it is not {what} while a run may be in flight or unsettled",
                   f"Wait for the request's result, or reconcile it from the Modal bill: {PROG} "
                   f"modal-settle {job_id} --root {rec.root} --usd <billed>; then rerun")


def _settled_as(ledger, job_id, units) -> str:
    if ledger.is_modal_job(job_id):
        return (f"settled from its Modal rows at {ledger.modal_job_usd(job_id)[0]:.4f} USD plus "
                f"{units:g} CU of Colab work")
    return f"settled {units:g} CU"


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
    ledger = _ledger(rec, args)
    _no_pending_modal(rec, ledger, args.job_id, "imported")
    units = _modal_units(ledger, args.job_id, args.units)
    try:
        arts = importer.import_job(rec, {k: job[k] for k in ("job_id", "kind", "notebook",
                                                             "inputs_zip", "manifest")},
                                   args.source, ledger, units, **extra)
    except importer.ImportHeld as e:
        raise Stop(f"Import held: {e}. Nothing was imported; the reservation stays open.",
                   "Re-download the complete output folder (or archive) of this exact job and rerun "
                   f"{PROG} import {args.job_id} ...; never rebuild or rerun the job to get past it.",
                   code=4)
    print(f"Imported {len(arts)} verified file(s) from {job['kind']} job {args.job_id}; "
          f"{_settled_as(ledger, args.job_id, units)}.")


def _modal_job(rec, job_id) -> dict:
    """The checks before Modal is ever contacted (modal-run, modal-request): the job exists, is
    neither imported nor ended, is runnable there and its inputs.zip matches the build manifest."""
    job = next((j for j in _jobs(rec) if j["job_id"] == job_id), None)
    if job is None:
        raise Stop(f"unknown job {job_id}", f"{PROG} status --root {rec.root}")
    if job["imported"] or _ended(job) or job["unfinished"]:
        raise Stop(f"job {job_id} is imported, superseded or closed (or that is under way); "
                   "it is never run again", f"{PROG} status --root {rec.root}")
    if job["kind"] not in modal_run.RUNNABLE_KINDS:
        raise Stop(f"{job['kind']} jobs cannot run with modal-run", "Use the Wan worker for reel_clips")
    built = _json(job["manifest"]).get("inputs_sha256")
    if not built or sha256_file(job["inputs_zip"]) != built:
        raise Stop(f"inputs.zip of {job_id} does not match its build manifest",
                   "Never run a bundle that changed since it was built; supersede it and rebuild")
    return job


def _colab_units(args, cmd) -> float:
    if args.colab_units is None:
        raise Stop("--colab-units is required: the CU Colab already showed for this job (0 if it "
                   "never ran in Colab); they stay counted against the Colab caps",
                   f"{PROG} {cmd} {args.job_id} --root {args.root} --colab-units <CU, 0 if none>")
    try:
        return budget._check_units(args.colab_units)
    except ValueError as e:
        raise Stop(str(e), "Pass --colab-units as the CU Colab showed for this job, >= 0")


def _open_request(rec, job_id):
    """The job's request file if it is still requested/running (the workflow owns that run)."""
    path = modal_requests.request_path(rec.root, job_id)
    if not path.is_file():
        return None
    req = modal_requests.read_request(path)
    return req if req["status"] in modal_requests.OPEN else None


def _move_to_modal(rec, ledger, job_id, colab_units, now):
    try:  # the Colab CU already used stay on the CU caps; the rest of the reservation is released
        ledger.move_to_modal(job_id, now, colab_units)
    except KeyError as e:
        raise Stop(f"job {job_id} has no reservation on the ledger ({e}); Modal was not "
                   "contacted", f"{PROG} status --root {rec.root}")
    except ValueError as e:
        raise Stop(f"{e}; Modal was not contacted", f"{PROG} status --root {rec.root}")


def _reserve_modal(args, rec, job, colab_units):
    """Both Modal dollar caps against the worst case (deadline + timeout margin at the L4 rate x
    MODAL_OVERHEAD_FACTOR, pending rows counted), the move to Modal, then the provisional worst-case pending row. The row
    counts against the caps until the actual spend replaces it; if the process dies (Ctrl-C, kill,
    an error after the paid run) it stays pending until `modal-settle`. Returns
    (ledger, run_id, worst_usd)."""
    ledger, month = _ledger(rec, args), _month()
    plan = modal_run.plan(job["notebook"], job["inputs_zip"])
    worst = modal_run.modal_cost(plan["timeout_seconds"])  # deadline + margin, x overhead factor
    try:
        ledger.check_modal(month, rec.data["title_slug"], worst, rec.data["source"].get("edition_id"))
    except budget.BudgetExceeded as e:
        raise Stop(f"Budget exceeded: {e}. Modal was not contacted.",
                   "Hold the job and ask the owner; never run past the Modal cap.", code=3)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _move_to_modal(rec, ledger, args.job_id, colab_units, now)
    run_id = ledger.record_modal_spend(month, args.job_id, worst, 0.0, "pending", now)
    return ledger, run_id, worst


def _requested_run(args, rec, req_path):
    """modal-run --request: the request's --colab-units and pending row (the caps were checked and
    the row written by modal-request; it keeps counting until the run replaces it)."""
    if not req_path.is_file():
        raise Stop(f"no request file {req_path}", f"{PROG} modal-request {args.job_id} --root "
                   f"{rec.root} --colab-units <CU, 0 if none>")
    req = modal_requests.read_request(req_path)
    if req["status"] not in modal_requests.OPEN or req["job_id"] != args.job_id:
        raise Stop(f"request {req_path} is {req['status']} (job {req['job_id']}); only a requested "
                   "or running request is run", f"{PROG} status --root {rec.root}")
    colab_units = budget._check_units(req["colab_units"])
    if args.colab_units is not None and args.colab_units != colab_units:
        raise Stop(f"--colab-units {args.colab_units:g} differs from the request's {colab_units:g}",
                   "Drop --colab-units; the request carries it")
    ledger, run_id = _ledger(rec, args), req["pending_run_id"]
    row = next((r for r in ledger.modal_rows(job_id=args.job_id)
                if r["run_id"] == run_id and r["status"] == "pending"), None)
    if row is None:
        raise Stop(f"the request's row {run_id} is not pending on the ledger; Modal was not "
                   "contacted", f"Make a new request: {PROG} modal-request {args.job_id} --root "
                   f"{rec.root} --colab-units {colab_units:g}")
    # The request may run in a later UTC month (or after other spend): both caps are checked again
    # now, for the current month, with this row's worst case moved there.
    month = _month()
    try:
        ledger.check_modal(month, rec.data["title_slug"], row["usd"],
                           rec.data["source"].get("edition_id"), exclude_run_id=run_id)
    except budget.BudgetExceeded as e:
        _refuse_request(ledger, req_path, f"Budget exceeded at run time: {e}")
        raise Stop(f"Budget exceeded: {e}. The request is refused, its pending row released and the "
                   "job's CU reservation restored; Modal was not contacted.", "Hold the job and ask the owner; never run past the Modal cap.",
                   code=3)
    if not any(r["run_id"] == run_id for r in ledger.modal_rows(month=month)):
        ledger.move_modal_row(run_id, month)
    _move_to_modal(rec, ledger, args.job_id, colab_units,
                   datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return ledger, run_id, colab_units


def _refuse_request(ledger, req_path, reason):
    """Before Modal is contacted: release the request's pending row, restore the job's CU
    reservation if it never reached Modal, and mark the request refused."""
    modal_requests.refuse(req_path, ledger, reason)


def cmd_modal_run(args):
    """Run a built narration/stills/music notebook headlessly on Modal; the actual spend is appended
    to the ledger's modal_spend rows (hard caps 30 USD per UTC month and 6 USD per title, lifetime).
    The job's CU reservation is released when it moves to Modal; it settles in USD at import/close.
    --request (the modal-jobs workflow): reuse the request's pending row and --colab-units instead
    of writing a second row, and record the run's result in the request file."""
    rec = _record(args.root)
    job = _modal_job(rec, args.job_id)
    if args.dry_run:  # checks and the exact remote plan only; nothing is executed or contacted
        plan = modal_run.plan(job["notebook"], job["inputs_zip"])
        print(json.dumps({**plan, "dry_run": True, "forecast_usd": round(plan["forecast_usd"], 4),
                          "next": f"{PROG} modal-run {args.job_id} --root {rec.root}"}, sort_keys=True))
        return
    req_path = modal_requests.request_path(rec.root, args.job_id)
    if args.request:
        ledger, run_id, colab_units = _requested_run(args, rec, req_path)
    else:
        if _open_request(rec, args.job_id):
            raise Stop(f"job {args.job_id} has an open Modal request ({req_path}); the workflow runs "
                       "it and nothing was run here", f"Once it is done: {PROG} modal-fetch "
                       f"{args.job_id} --root {rec.root}")
        colab_units = _colab_units(args, "modal-run")
        ledger, run_id, _ = _reserve_modal(args, rec, job, colab_units)
    download = Path(args.download) if args.download else rec.root / "modal-downloads"
    contact = None
    if args.request:
        def contact():  # written immediately before Modal is contacted (the workflow reads it)
            req = modal_requests.read_request(req_path)
            req["modal_contacted_at"] = modal_requests.now()
            modal_requests.write_request(req_path, req)
    result = None
    try:
        result = modal_run.run_modal(job["notebook"], job["inputs_zip"], download, on_contact=contact)
    finally:
        if result is not None:
            ledger.finish_modal_spend(run_id, result["usd"], result["seconds"], result["status"])
            if args.request:
                req = modal_requests.read_request(req_path)
                req["run"] = {"run_id": run_id, "seconds": result["seconds"], "usd": result["usd"],
                              "status": result["status"], "error": result["error"]}
                modal_requests.write_request(req_path, req)
    folder, status = result["folder"], result["status"]
    nxt = f"{PROG} import {args.job_id} --root {rec.root} --from {folder}"
    if status != "ok":
        nxt = (f"Rerun {PROG} modal-run {args.job_id} --root {rec.root} --colab-units "
               f"{colab_units:g} to resume from the volume; if it can never finish: {PROG} close "
               f"{args.job_id} --root {rec.root} --reason \"<what happened>\" (settles the Modal spend "
               f"recorded on the ledger plus the {colab_units:g} CU of Colab work)")
    print(json.dumps({"job_id": args.job_id, "seconds": round(result["seconds"], 1),
                      "usd": round(result["usd"], 4), "dry_run": False, "status": status,
                      "hard_stopped": status == "hard_stopped", "error": result["error"],
                      "folder": str(folder), "next": nxt}, sort_keys=True))
    if status == "failed":
        raise Stop(f"remote run failed: {result['error']}", nxt)


def cmd_modal_request(args):
    """Queue a Modal run for the modal-jobs GitHub Actions workflow: every modal-run check, the
    move to Modal and the worst-case pending row exactly as modal-run writes them (so the caps hold
    while the remote run is in flight), then production/audiovisual/modal-requests/<job_id>.json.
    Nothing here contacts Modal or commits: root commits the request with the ledger and pushes.
    --abandon: see _abandon_request."""
    if args.abandon:
        return _abandon_request(args)
    if args.reason is not None:
        raise Stop("--reason goes with --abandon only", f"Drop --reason, or add --abandon")
    rec = _record(args.root)
    if not modal_requests.valid_job_id(args.job_id):
        raise Stop(f"job id {args.job_id!r} does not match {modal_requests.JOB_ID_RE.pattern}; the "
                   "workflow refuses such a request", f"{PROG} status --root {rec.root}")
    job = _modal_job(rec, args.job_id)
    path = modal_requests.request_path(rec.root, args.job_id)
    if path.is_file():
        old = modal_requests.read_request(path)
        if old["status"] in modal_requests.OPEN:
            raise Stop(f"job {args.job_id} already has a {old['status']} request ({path}); nothing "
                       "was written", f"Wait for the workflow, then {PROG} modal-fetch {args.job_id} "
                       f"--root {rec.root}")
    colab_units = _colab_units(args, "modal-request")
    try:
        title_root = rec.root.resolve().relative_to(modal_requests.repo_root(rec.root)).as_posix()
    except ValueError as e:
        raise Stop(str(e), "Run modal-request on a title root inside the repository checkout")
    if not modal_requests.TITLE_ROOT_RE.fullmatch(title_root):
        raise Stop(f"title root {title_root} is not under production/audiovisual/; the workflow "
                   "refuses such a request and nothing was written",
                   "Run modal-request on a title root under production/audiovisual/")
    ledger, run_id, worst = _reserve_modal(args, rec, job, colab_units)
    modal_requests.write_request(path, {
        "schema": modal_requests.SCHEMA, "job_id": args.job_id, "title_root": title_root,
        "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "requested", "colab_units": colab_units, "pending_run_id": run_id,
        "worst_case_usd": round(worst, 6),
        "r2_prefix": modal_requests.r2_prefix(rec.data["title_slug"], args.job_id, run_id)})
    print(f"Modal request written: {path} (worst case {worst:.4f} USD pending on the ledger as "
          f"{run_id}; {colab_units:g} CU of Colab work kept on the Colab caps). Modal was not "
          "contacted.")
    print(f"Then: commit {path} with the ledger {ledger.path} and push to {modal_requests.BRANCH}; "
          f"the modal-jobs workflow runs it; then {PROG} modal-fetch {args.job_id} --root {rec.root}")


def _abandon_request(args):
    """modal-request --abandon: a `running` request whose run is known not to have reached Modal
    (the runner died before the Modal step, or was cancelled) is refused: its pending row released,
    the job's CU reservation restored. Refused when modal_contacted_at is set (Modal may have
    billed: wait for the result, or reconcile with modal-settle)."""
    rec = _record(args.root)
    if args.colab_units is not None:
        raise Stop("--colab-units does not go with --abandon", "Drop --colab-units")
    if not modal_requests.valid_job_id(args.job_id):
        raise Stop(f"job id {args.job_id!r} does not match {modal_requests.JOB_ID_RE.pattern}",
                   f"{PROG} status --root {rec.root}")
    if not (args.reason or "").strip():
        raise Stop("--abandon needs --reason", f"{PROG} modal-request {args.job_id} --root {rec.root} "
                   "--abandon --reason \"<why it never reached Modal>\"")
    path = modal_requests.request_path(rec.root, args.job_id)
    if not path.is_file():
        raise Stop(f"no request file {path}", f"{PROG} status --root {rec.root}")
    req = modal_requests.read_request(path)
    if req["job_id"] != args.job_id or req["status"] != "running":
        raise Stop(f"request {path} is {req['status']}; only a running request is abandoned",
                   f"{PROG} status --root {rec.root}")
    if req.get("modal_contacted_at"):
        raise Stop(f"request {args.job_id} contacted Modal at {req['modal_contacted_at']}; it may have "
                   "been billed and is never abandoned",
                   f"Wait for the workflow's result, or reconcile from the Modal bill: {PROG} "
                   f"modal-settle {args.job_id} --root {rec.root} --usd <billed>")
    ledger = _ledger(rec, args)
    _refuse_request(ledger, path, f"abandoned: {args.reason.strip()}")
    print(f"Request {args.job_id} abandoned (refused): its pending row {req.get('pending_run_id')} "
          "was released and the job's CU reservation restored. Modal was never contacted.")
    print(f"Then: commit {path} with the ledger {ledger.path} and push")


def _req_prefix(rec, req) -> str:
    """The request's own R2 prefix (older requests: the job prefix they recorded)."""
    return req.get("r2_prefix") or modal_requests.r2_prefix(rec.data["title_slug"], req["job_id"])


def cmd_r2_upload(args):
    """The workflow, after modal-run --request: upload the job folder to the private R2 bucket, read
    every object back, and finish the request (done/failed/hard_stopped, seconds, usd, files with
    sha256). The request is finished even when the upload fails, so the spend is never lost."""
    rec = _record(args.root)
    path = modal_requests.request_path(rec.root, args.job_id)
    req = modal_requests.read_request(path)
    if req["status"] not in modal_requests.OPEN:
        raise Stop(f"request {path} is already {req['status']}",
                   f"{PROG} modal-fetch {args.job_id} --root {rec.root}")
    run = req.get("run") or {}
    prefix = _req_prefix(rec, req)
    status = modal_requests.RUN_TO_REQUEST.get(run.get("status"), "failed")
    error = run.get("error") if run else "modal-run recorded no result"
    files, upload_error = [], None
    try:
        files = modal_requests.upload_folder(Path(args.source), prefix, modal_requests.default_opener(),
                                             os.environ.get(modal_requests.TOKEN_ENV) or None)
    except modal_requests.R2Error as e:
        upload_error = f"upload: {e}"
        status, error = "failed", f"{error}; {upload_error}" if error else upload_error
    req.update(status=status, seconds=run.get("seconds"), usd=run.get("usd"), error=error,
               r2_prefix=prefix, files=files,
               finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    modal_requests.write_request(path, req)
    print(f"Request {args.job_id}: {status}; {len(files)} verified file(s) under "
          f"r2://{modal_requests.R2_BUCKET}/{prefix}")
    try:  # the copy modal-fetch reads if the request cannot be pushed back to the branch
        modal_requests.put_result(prefix, req, modal_requests.default_opener(),
                                  os.environ.get(modal_requests.TOKEN_ENV) or None)
    except modal_requests.R2Error as e:
        upload_error = upload_error or f"result copy: {e}"
        print(f"The R2 copy {modal_requests.RESULT_NAME} was not written: {e}")
    if upload_error:
        raise Stop(upload_error, "Commit the request and the ledger anyway (the spend is recorded)")


def cmd_r2_probe(args):
    """The workflow, before the paid run: PUT, list, GET and DELETE a probe object under the job's
    R2 prefix with the runner's token. On failure the request is refused and its pending row
    released, so Modal is never paid for outputs that could not be uploaded."""
    rec = _record(args.root)
    path = modal_requests.request_path(rec.root, args.job_id)
    req = modal_requests.read_request(path)
    if req["status"] not in modal_requests.OPEN:
        raise Stop(f"request {path} is {req['status']}; only an open request is probed",
                   f"{PROG} status --root {rec.root}")
    prefix = _req_prefix(rec, req)
    try:
        key = modal_requests.probe(prefix, modal_requests.default_opener(),
                                   os.environ.get(modal_requests.TOKEN_ENV) or None)
    except modal_requests.R2Error as e:
        _refuse_request(_ledger(rec, args), path, f"R2 probe failed: {e}")
        raise Stop(f"R2 probe failed: {e}. The request is refused, its pending row released and the "
                   "job's CU reservation restored; Modal was not contacted.", "Fix the R2 token or API access, then modal-request again")
    print(f"R2 probe ok: put, listed, read back and deleted r2://{modal_requests.R2_BUCKET}/{key}")


def cmd_modal_replay(args):
    """The workflow, when a push-back rebase conflicts: on the freshly fetched branch, re-apply this
    job's saved request file and its own ledger entry, and make its rows exactly the saved ones (a
    released row is never resurrected); every other job's entry and rows in the newer ledger are
    kept."""
    rec = _record(args.root)
    saved = Path(args.saved)
    req = modal_requests.read_request(saved / "request.json")
    if req["job_id"] != args.job_id:
        raise Stop(f"the saved request is for {req['job_id']}, not {args.job_id}", "Pass the right --saved")
    ledger = _ledger(rec, args)
    ledger.replay_job(args.job_id, _json(saved / "ledger.json"))
    modal_requests.write_request(modal_requests.request_path(rec.root, args.job_id), req)
    print(f"Replayed request {args.job_id} ({req['status']}) and its ledger rows onto the current tree.")


def _fetchable_request(rec, args, path):
    """The branch request; if it is still open (the workflow could not push it back), the finished
    copy of this same request (same pending_run_id) that the workflow uploaded to the request's R2
    prefix as _request-result.json."""
    if not path.is_file():
        raise Stop(f"no request file {path}", f"Pull {modal_requests.BRANCH}; {PROG} status --root {rec.root}")
    req = modal_requests.read_request(path)
    if req["status"] not in modal_requests.OPEN:
        return req, False
    try:
        copy = modal_requests.get_result(_req_prefix(rec, req), modal_requests.default_opener())
    except modal_requests.R2Error as e:
        raise Stop(f"the R2 copy of request {args.job_id} is unreadable: {e}",
                   f"Pull {modal_requests.BRANCH} and rerun")
    if copy is not None and copy.get("job_id") == args.job_id \
            and copy.get("pending_run_id") == req.get("pending_run_id") \
            and copy["status"] not in modal_requests.OPEN:
        return copy, True
    raise Stop(f"request {args.job_id} is {req['status']}; the workflow has not finished it",
               f"Pull {modal_requests.BRANCH} and rerun once the request is done")


def cmd_modal_fetch(args):
    """Download a finished request's job folder from the private R2 bucket and verify every file's
    sha256 against the request. Never imports: the printed command does."""
    rec = _record(args.root)
    path = modal_requests.request_path(rec.root, args.job_id)
    req, from_r2 = _fetchable_request(rec, args, path)
    if from_r2:
        print(f"The branch request is stale; using the R2 copy ({req['status']}). Merge "
              f"{modal_requests.FALLBACK_BRANCH.format(job_id=args.job_id)} (or its -run-<id> "
              "variant named in the workflow log: the request and the ledger rows of this run) "
              "before import.")
    if req["status"] == modal_requests.REFUSED:
        raise Stop(f"request {args.job_id} was refused before Modal was contacted: {req.get('error')}",
                   f"Hold for the owner; then {PROG} modal-request {args.job_id} --root {rec.root} ...")
    if not req.get("files"):
        raise Stop(f"request {args.job_id} is {req['status']} with no uploaded files "
                   f"({req.get('error')})", f"{PROG} close {args.job_id} --root {rec.root} --reason "
                   "\"<what happened>\" (its Modal spend is on the ledger), or request it again")
    if args.into:
        dest = Path(args.into)
    else:
        downloads = rec.root / ".downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        if not (downloads / ".gitignore").is_file():  # the outputs are never committed
            (downloads / ".gitignore").write_text("*\n", encoding="utf-8")
        dest = downloads / args.job_id
    prefix = _req_prefix(rec, req)
    try:
        modal_requests.fetch_folder(prefix, req["files"], dest, modal_requests.default_opener())
    except modal_requests.R2Error as e:
        raise Stop(f"fetch refused: {e}; nothing was written to {dest}",
                   f"Rerun {PROG} modal-fetch {args.job_id} --root {rec.root}; never copy files in by hand")
    print(f"Fetched {len(req['files'])} verified file(s) of {req['status']} request {args.job_id} "
          f"into {dest}. Nothing was imported.")
    print(f"Then: {PROG} import {args.job_id} --root {rec.root} --from {dest} (units come from the "
          "Modal rows)")


def cmd_modal_settle(args):
    """Reconcile a job's Modal row(s) with the amount the Modal dashboard billed: its pending
    (interrupted) rows, else its one finished row still holding the estimate, or the row --run
    names (pending or finished). The row records billed: true and keeps estimated_usd; the caps
    read the rows."""
    rec = _record(args.root)
    ledger = _ledger(rec, args)
    try:
        budget._check_units(args.usd)
        changed = ledger.bill_modal_run(args.job_id, args.usd, args.run)
    except ValueError as e:
        raise Stop(str(e), "Pass --usd as the amount billed, >= 0, and --run <run_id> to pick a row")
    except KeyError:
        raise Stop(f"job {args.job_id} has no pending or unbilled Modal run on the ledger",
                   f"Name the row to correct: {PROG} modal-settle {args.job_id} --root {rec.root} "
                   "--usd <billed> --run <run_id>")
    print(f"Reconciled Modal run(s) {', '.join(changed)} of job {args.job_id} at {args.usd:.4f} USD "
          f"billed (counts against the Modal dollar caps only).")


_ENDINGS = {"supersede": ("superseding", "superseded"), "close": ("closing", "closed")}


def _supersede_group(args):
    """supersede --group: every chunk of the group that is neither imported nor ended is superseded
    together (each with its own R23 intent/settle/result), so a rerun finishes an interrupted one."""
    rec = _record(args.root)
    job = next((j for j in _jobs(rec) if j["job_id"] == args.job_id), None)
    group = _find(rec, args.job_id) if job is None else _find(rec, (job["chunk"] or {}).get("group"))
    if group is None or "of" not in group:
        raise Stop(f"{args.job_id} is not a chunk or chunk group",
                   f"Drop --group: {PROG} supersede {args.job_id} --root {rec.root} --reason \"...\"")
    todo = [c["job_id"] for c in group["all_chunks"] if not c["imported"] and not _ended(c)]
    if not todo:
        raise Stop(f"chunk group {group['job_id']} has no never-run chunk left to supersede",
                   f"{PROG} status --root {rec.root}")
    ledger = _ledger(rec, args)
    ran = [j for j in todo if ledger.is_modal_job(j)]
    if ran:  # checked for every chunk before any write: a group is never half superseded
        raise Stop(f"chunk(s) {', '.join(ran)} of group {group['job_id']} ran on Modal; supersede is "
                   "for never-run jobs and nothing was superseded",
                   f"Close each chunk that ran: {PROG} close <chunk id> --root {rec.root} --reason "
                   "\"...\", then rebuild only it with --replace-chunk")
    for job_id in todo:
        _end_job(args, "supersede", job_id)


def _end_job(args, how, job_id=None):
    """supersede (never ran: settle 0) or close (ran, not imported: settle the ACTUAL units).

    R23: the intent is recorded first as a pending event, then the ledger is settled, then the
    final event is written; rerunning the same command after any failure finishes it.
    A chunk is superseded only with its whole group (supersede --group); close is per chunk."""
    pending_result, final = _ENDINGS[how]
    rec = _record(args.root)
    job_id = job_id or args.job_id
    job = next((j for j in _jobs(rec) if j["job_id"] == job_id), None)
    if job is None:
        raise Stop(f"unknown job {job_id}", f"{PROG} status --root {rec.root}")
    if how == "supersede" and job["chunk"] and not getattr(args, "group", False):
        raise Stop(f"job {job_id} is chunk {job['chunk']['index']} of {job['chunk']['of']} of group "
                   f"{job['chunk']['group']}; one chunk is never superseded alone (the group would "
                   "stay incomplete forever)",
                   f"Supersede every never-run chunk of the group together: {PROG} supersede {job_id} "
                   f"--root {rec.root} --group --reason \"<why they never ran>\"")
    if job["imported"]:
        raise Stop(f"job {job_id} was imported; its outputs and spend stay on record",
                   f"{PROG} status --root {rec.root}")
    if _ended(job):
        raise Stop(f"job {job_id} is already {'superseded' if job['superseded'] else 'closed'}",
                   f"{PROG} status --root {rec.root}")
    events = rec.data["events"]
    pending = [e for e in events if e["stage"] == "job" and e["detail"].get("job_id") == job_id
               and e["result"] in ("superseding", "closing")]
    if pending and pending[-1]["result"] != pending_result:
        raise Stop(f"job {job_id} has an unfinished {pending[-1]['result'][:-3]}e; finish that one",
                   f"Rerun {PROG} {'close' if how == 'supersede' else 'supersede'} {job_id} "
                   f"--root {rec.root}")
    if not args.reason.strip():
        raise Stop("a reason is required", f"Pass --reason \"<{'why it never ran' if how == 'supersede' else 'what happened'}>\"")
    ledger = _ledger(rec, args)
    if how == "close":
        _no_pending_modal(rec, ledger, job_id, "closed")
    if how == "supersede" and ledger.is_modal_job(job_id):
        raise Stop(f"job {job_id} ran on Modal; supersede is for never-run jobs",
                   f"{PROG} close {job_id} --root {rec.root} --reason \"...\" (--units only for "
                   "Colab work after the move to Modal)")
    units = 0 if how == "supersede" else budget._check_units(_modal_units(ledger, job_id, args.units))
    entry = next((e for e in ledger._load() if e["job_id"] == job_id), None)
    if pending:
        recorded = pending[-1]["detail"]["units"]
        if recorded != units:
            raise Stop(f"the interrupted {how} of {job_id} recorded {recorded:g} CU; it is finished "
                       "with the recorded units, never re-decided",
                       f"Rerun with --units {recorded:g}" if how == "close" else "Rerun supersede")
    else:
        if entry is None or entry["state"] != "reserved":
            raise Stop(f"job {job_id} has no open reservation on the ledger "
                       f"({'missing' if entry is None else entry['state']}); nothing to settle",
                       f"{PROG} status --root {rec.root}")
        detail = {"job_id": job_id, "units": units, "reason": args.reason}
        if ledger.is_modal_job(job_id):
            detail["runner"] = "modal"
        rec.event("job", pending_result, detail)
    if entry is None:
        raise Stop(f"job {job_id} is missing from the ledger", f"{PROG} status --root {rec.root}")
    if entry["state"] == "reserved":
        ledger.settle(job_id, units)
    elif entry["units"] != units:
        raise Stop(f"ledger entry {job_id} was settled at {entry['units']:g} CU, not {units:g}",
                   "Report this; never edit the ledger by hand")
    reason = pending[-1]["detail"]["reason"] if pending else args.reason
    if how == "supersede":
        rec.event("job", final, {"job_id": job_id, "reason": reason})
        print(f"Superseded {job['kind']} job {job_id}: reservation of {entry['units']:.2f} CU "
              "released (settled at 0). Do not run its notebook.")
    else:
        detail = {"job_id": job_id, "units": units, "ran": True, "imported": False, "reason": reason}
        if ledger.is_modal_job(job_id):
            detail.update(runner="modal", usd=round(ledger.modal_job_usd(job_id)[0], 6))
            how_much = (f"{_settled_as(ledger, job_id, units)} (CU reservation "
                        f"{entry.get('reserved_units', entry['units']):.2f})")
        else:
            how_much = f"settled at the actual {units:g} CU (reserved {entry['units']:.2f} CU)"
        rec.event("job", final, detail)
        print(f"Closed {job['kind']} job {job_id}: it ran but is not imported; {how_much}. "
              "Its outputs are not on record.")


def cmd_supersede(args):
    """Release a never-run job: settle its reservation at 0 and record job/superseded (R19).
    A chunk only with --group: every never-run chunk of its group together."""
    if args.group:
        return _supersede_group(args)
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
        raise Stop(f"{t} needs imported narration and stills jobs"
                   + _incomplete(rec, "narration", t) + _incomplete(rec, "stills", t),
                   next_action(rec.root))
    lang = plan["language"]
    scs = films[args.film - 1]["scenes"]
    units = [u for sc in scs for u in voice_units(sc, {"description": ""}, None, lang)]
    out = rec.root / "film" / t
    out.mkdir(parents=True, exist_ok=True)
    timing, prov = _measured_track(rec, units, narr, out / "narration.wav")
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
    info = film.assemble(plan["plan"], timing, _one_dir(rec, stills), out / "mix.wav",
                         Path(args.logo), Path(args.end_card), out / f"{t}.mp4",
                         film=args.film - 1, language=lang)
    for kind, p in (("timing", out / "timing.json"), ("subtitles", out / f"{t}.srt"),
                    ("mix", out / "mix.wav")):
        rec.add_artifact(kind, p, {"target": t})
    rec.add_artifact("film", out / f"{t}.mp4", {"target": t, "lufs": m["lufs"],
                                                "true_peak": m["true_peak"], "score": score_info,
                                                "narration_job_id": narr["job_id"], **info})
    rec.event("film", "assembled", {"target": t, "duration": info["duration"]})
    print(f"Assembled {out / (t + '.mp4')}: {info['duration']:.1f} s, {m['lufs']:.1f} LUFS, "
          f"TP {m['true_peak']:.1f} dBTP. Maison video stays held (Stream cost not approved).")


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
    units = voice_units(_reel_scene(script, n), {"description": ""}, None, script["language"])
    timing, prov = _measured_track(rec, units, narr, folder / "narration.wav")
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
    narr = _find(rec, narr_id)
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


def _write_audio_bundle(rec, plan, src, lang, bundle, scene_film, args):
    rows, prov_units, job_ids, run_ids = [], {}, set(), set()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bundle.mkdir(parents=True, exist_ok=True)
        for n, unit in enumerate(src["units"], 1):
            anchors = {p["anchor_id"] for p in unit["paragraphs"]}
            mine = [(fi, sc) for fi, sc in scene_film.values() if set(sc["anchor_ids"]) <= anchors]
            films_used = {fi for fi, _ in mine}
            if not mine or len(films_used) != 1:
                raise Stop(f"unit {unit['unit_id']} has no single planned film", "Re-plan the title")
            fi = films_used.pop()
            job = _latest_job(rec, "narration", _film_target(fi))
            if not job:
                raise Stop(f"unit {unit['unit_id']}: narration not imported yet"
                           + _incomplete(rec, "narration", _film_target(fi)), next_action(rec.root))
            job_ids.add(job["job_id"])
            run_ids.update(_chunk_ids(job))
            units, tags = [], []
            for _, sc in mine:
                vus = voice_units(sc, {"description": ""}, None, lang)
                tg = [b["anchor_id"] for b in sc["blocks"] for _ in sentences(b["text"], lang)]
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
            timing, prov = _measured_track(rec, units, job, chapter)
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
            if "narration_chunk_job_ids" in prov:
                prov_units[unit["unit_id"]]["narration_chunk_job_ids"] = prov["narration_chunk_job_ids"]
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
        "generators": [{"model": colab_jobs.NARRATION_REPO, "revision": colab_jobs.NARRATION_REVISION,
                        "licence": "Apache-2.0", "job_ids": sorted(run_ids),
                        "voice": plan["voice"]["preset_key"]}],
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


def cmd_preview(args):
    rec = _record(args.root)
    src = _json(rec.root / "source.json")
    chapter = Path(args.bundle) / "unit-001.mp3"
    if not src["units"] or not chapter.is_file():
        raise Stop(f"{chapter} not found", f"{PROG} bundle-audio --root {rec.root} --out <bundle dir>")
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise Stop(f"{out} is not empty", "Pass a new --out directory")
    out.mkdir(parents=True, exist_ok=True)
    try:
        record = preview.cut_preview(chapter, out / "preview.mp3", src["units"][0]["unit_id"])
    except ValueError as e:
        shutil.rmtree(out, ignore_errors=True)
        raise Stop(f"preview: {e}", "Give chapter 1 narration a pause within its first two minutes",
                   code=5)
    record["source_mp3_sha256"] = sha256_file(chapter)
    path = _write_json(out / "preview.json", record)
    rec.event("preview", "cut", {"sha256": record["sha256"], "duration_ms": record["duration_ms"]})
    print(f"Wrote preview clip {out / 'preview.mp3'} ({record['duration_ms']} ms, {record['bytes']} bytes) "
          f"and measurement record {path}. Server: stage it as a preview_audio asset; its asset_id completes "
          "revision.validation_evidence['audio_preview'].")


def cmd_status(args):
    root = Path(args.root)
    if (root / "record.json").is_file():
        rec = Record.load(root)
        s, title, month = rec.data["source"], rec.data["title_slug"], _month()
        ledger = _ledger(rec, args)
        print(f"{title}: revision {s['revision_id']} ({s['language']}), "
              f"{_title_spent(ledger, rec):.2f} CU spent/reserved for this title (lifetime cap "
              f"{budget.TITLE_CAP:g}), {ledger.spent(None, month):.2f} CU this month (all titles), "
              f"{_remaining(ledger, rec, month):.2f} CU remaining ({month}).")
        print(f"modal: ${ledger.modal_month_usd(month):.2f} of ${budget.MODAL_MONTH_CAP_USD:.2f} "
              f"this month; title: ${ledger.modal_title_usd(title, s.get('edition_id')):.2f} of "
              f"${budget.MODAL_TITLE_CAP_USD:.2f} (UTC month {month}; the CU above are Colab work "
              "only, including Colab work on jobs that later moved to Modal)")
        for j in _jobs(rec):
            closed = next((e["detail"] for e in rec.data["events"] if e["result"] == "closed"
                           and e["detail"].get("job_id") == j["job_id"]), None)
            on_modal = ledger.is_modal_job(j["job_id"])
            spent = (f"{closed['usd']:.2f} USD on Modal + {closed['units']:.2f} CU Colab"
                     if closed and "usd" in closed else f"{closed['units']:.2f} CU" if closed else "")
            state = ("imported" if j["imported"] else "superseded" if j["superseded"]
                     else f"closed (ran, not imported; {spent} settled)" if j["closed"]
                     else "supersede/close unfinished: rerun it" if j["unfinished"]
                     else (f"on Modal ({ledger.colab_units_before_modal(j['job_id']):.2f} CU of "
                           "Colab work kept, rest of the reservation released)") if on_modal
                     else "waiting for Colab")
            c = j["chunk"]
            part = f" chunk {c['index']}/{c['of']} of {c['group']}" if c else ""
            print(f"  {j['job_id']} {j['kind']} {j['target']}{part}: {state} "
                  f"(forecast {j['forecast_units']:.2f} CU)")
        for g in _logical(rec):
            if "of" in g:
                done = sum(c["imported"] for c in g["chunks"])
                state = ("complete" if g["imported"] else
                         "dead: superseded" if g["superseded"] else
                         "incomplete: chunk " + ", ".join(map(str, sorted(g["missing"])))
                         + " closed; rebuild it with job --replace-chunk" if g["closed"]
                         else "incomplete")
                print(f"  group {g['job_id']} {g['kind']} {g['target']}: {done} of {g['of']} chunks "
                      f"imported ({state})")


REPO = Path(__file__).resolve().parents[4]
FONTS = {"bn": REPO / "billing" / "fonts" / "MaisonSansBengali.ttf",
         "en": REPO / "billing" / "fonts" / "MaisonSansLatin.ttf"}


def cmd_social(args):
    """Write the posting kit: tagged links, film descriptions, reel posts and quote cards."""
    rec = _record(args.root)
    plan = _plan(rec)
    src = _json(rec.root / "source.json")  # the cleared export init copied in (units and text)
    lang, campaign = plan["language"], rec.data["title_slug"]
    url = lambda source, content: social.campaign_url(args.site, src["edition_id"], campaign, source, content)
    out = rec.root / "social"
    links, written = {}, []
    tags = list(reel.REQUIRED_TAGS)
    for n, f in enumerate(plan["plan"]["films"], 1):
        t = _film_target(n)
        art = next((a for a in reversed(rec.data["artifacts"]) if a["kind"] == "film" and a["meta"].get("target") == t), None)
        if art is None:
            continue
        timing = _json(rec.root / "film" / t / "timing.json")["units"]
        units = [u for u in src["units"] if u["unit_id"] in f["unit_ids"]]
        marks = social.chapters(units, f["scenes"], timing)
        music = _music_licence(art["meta"]["score"]["route"])
        credits = [f"Text: {args.author}, public domain in our publishing regions.",
                   "Narration: Earnalism Voice (AI narration).",
                   f"Music: {music['source_and_licence'].split(',')[0]}, {music['licence']}.",
                   "Visuals: AI-generated illustrations."]
        links[f"youtube-{t}"] = url("youtube", t)
        path = out / f"youtube-{t}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(social.film_description(args.title, args.author, links[f"youtube-{t}"], marks, credits, tags),
                        encoding="utf-8")
        written.append((path, {"target": t, "chapters": len(marks)}))
    for folder in sorted((rec.root / "reels").glob("reel-*")) if (rec.root / "reels").is_dir() else []:
        caption = folder / "caption.txt"
        if not (caption.is_file() and (folder / f"{folder.name}.mp4").is_file()):
            continue
        for platform, clickable in (("youtube", True), ("facebook", True), ("instagram", False)):
            key = f"{platform}-{folder.name}"
            links[key] = url(platform, folder.name)
            path = out / f"{key}.txt"
            path.write_text(social.reel_post(caption.read_text(encoding="utf-8"), links[key], clickable), encoding="utf-8")
            written.append((path, {"target": folder.name, "platform": platform}))
    for i, quote in enumerate(args.quote or [], 1):
        text = social.verify_quote(quote, src["units"])
        content = f"quote-{i}"
        links[f"instagram-{content}"] = url("instagram", content)
        path = out / f"{content}.png"
        info = social.quote_card(text, args.author, "theearnalism.com", FONTS.get(lang, FONTS["en"]), FONTS["en"],
                                 path, Path(args.background) if args.background else None, marks=lang != "bn")
        written.append((path, {"target": content, **info}))
    if not written:
        raise Stop("nothing to write: no assembled film, finished reel or --quote yet", next_action(rec.root))
    _write_json(out / "links.json", links)
    written.append((out / "links.json", {"count": len(links)}))
    for path, meta in written:
        rec.add_artifact("social_kit", path, meta)
    rec.event("social", "kit_written", {"files": len(written), "site": args.site})
    print(f"Social kit: {len(written)} file(s) in {out}. Nothing is posted; posting needs the owner's "
          "destination instruction and turning on each platform's AI-content label.")


COMMANDS = {"init": cmd_init, "plan": cmd_plan, "job": cmd_job, "import": cmd_import,
            "supersede": cmd_supersede, "close": cmd_close, "modal-run": cmd_modal_run, "modal-settle": cmd_modal_settle,
            "modal-request": cmd_modal_request, "r2-upload": cmd_r2_upload,
            "modal-fetch": cmd_modal_fetch, "r2-probe": cmd_r2_probe, "modal-replay": cmd_modal_replay,
            "film": cmd_film, "reel": cmd_reel, "qc": cmd_qc, "status": cmd_status,
            "bundle-audio": cmd_bundle_audio, "preview": cmd_preview, "social": cmd_social}


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
    s.add_argument("--job-id")
    s.add_argument("--replace-chunk", help="a closed or superseded chunk id: rebuild only its items "
                   "as <chunk id>-r<k>; the group's other chunks are kept")
    s = add("import")
    s.add_argument("job_id")
    s.add_argument("--from", dest="source", required=True)
    s.add_argument("--units", type=float, help="the CU Colab shows; for a job run with modal-run: "
                   "only the CU of any Colab run after the move (optional, default 0)")
    s.add_argument("--archive-sha256")
    s = add("modal-run")
    s.add_argument("job_id")
    s.add_argument("--download", help="where the job folder lands (default <root>/modal-downloads)")
    s.add_argument("--dry-run", action="store_true", help="check and print the remote plan and forecast; run nothing")
    s.add_argument("--colab-units", type=float, help="required for a run: the CU Colab already showed "
                   "for this job (0 if it never ran there); they stay on the Colab caps")
    s.add_argument("--request", action="store_true", help="the modal-jobs workflow: run the job's "
                   "request file, reusing its pending row and --colab-units")
    s = add("modal-request")
    s.add_argument("job_id")
    s.add_argument("--colab-units", type=float, help="required: as on modal-run, the CU Colab already "
                   "showed for this job (0 if it never ran there); at most its CU reservation")
    s.add_argument("--abandon", action="store_true", help="refuse a running request that never "
                   "reached Modal (no modal_contacted_at): release its row, restore the reservation")
    s.add_argument("--reason", help="with --abandon: why the run never reached Modal")
    s = add("r2-upload")
    s.add_argument("job_id")
    s.add_argument("--from", dest="source", required=True, help="the downloaded job folder")
    s = add("r2-probe")
    s.add_argument("job_id")
    s = add("modal-replay")
    s.add_argument("job_id")
    s.add_argument("--saved", required=True, help="folder with this run's request.json and ledger.json")
    s = add("modal-fetch")
    s.add_argument("job_id")
    s.add_argument("--into", help="where the job folder lands (default <root>/.downloads/<job_id>)")
    s = add("modal-settle")
    s.add_argument("job_id")
    s.add_argument("--usd", type=float, required=True, help="the amount the Modal dashboard billed")
    s.add_argument("--run", help="the run_id of the row to reconcile (a pending or finished row)")
    s = add("supersede")
    s.add_argument("job_id")
    s.add_argument("--reason", required=True)
    s.add_argument("--group", action="store_true",
                   help="a chunk (or group id): supersede every never-run chunk of its group together")
    s = add("close")
    s.add_argument("job_id")
    s.add_argument("--units", type=float, help="the CU Colab shows the run used; for a job run with "
                   "modal-run: only the CU of any Colab run after the move (optional, default 0)")
    s.add_argument("--reason", required=True)
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
    s = add("preview")
    s.add_argument("--bundle", required=True, help="the bundle-audio output holding unit-001.mp3")
    s.add_argument("--out", required=True)
    s = add("social")
    s.add_argument("--site", required=True, help="bare https origin, e.g. https://theearnalism.com")
    s.add_argument("--title", required=True, help="display title exactly as on the edition")
    s.add_argument("--author", required=True)
    s.add_argument("--quote", action="append", help="exact words from the book; one card each")
    s.add_argument("--background", help="an imported still to darken behind quote cards")
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
        print(f"Next: fix the input it names, then rerun; {PROG} status --root {args.root}")
        return 2
    print(f"Next: {next_action(args.root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
