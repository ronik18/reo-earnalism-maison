"""earnalism-audiovisual orchestrator: one title root, one production record, one next action.

  python3 -m eav.cli init <source.json> --root <dir> [--slug <maison-edition-slug>]
  python3 -m eav.cli plan --root <dir>
  python3 -m eav.cli job <narration|stills|music|reel_clips> --root <dir> --rates <rates.json>
                         [--film N | --reel N] [--spec <spec.json>] [--clause "..."]
  python3 -m eav.cli import <job_id> --root <dir> --from <folder|archive> --units <CU>
                         [--archive-sha256 <sha>]           (reel_clips)
  python3 -m eav.cli supersede <job_id> --root <dir> --reason "<why it never ran>"
  python3 -m eav.cli close <job_id> --root <dir> --units <CU Colab shows> --reason "<what happened>"
  python3 -m eav.cli film --root <dir> [--film N] --logo <png> --end-card <png>
                         (--score <wav> --score-route vcsl|ace-step:<job_id> | --cues-job <id>)
  python3 -m eav.cli reel <n> --root <dir> --script <script.json> [--hashtags ...]
  python3 -m eav.cli reel <n> --root <dir> --plan-shots           (after reel narration import)
  python3 -m eav.cli reel <n> --root <dir> [--score <wav> --score-route ...]
  python3 -m eav.cli qc --root <dir>
  python3 -m eav.cli status --root <dir>
  python3 -m eav.cli bundle-audio --root <dir> --out <bundle dir>
                         (--score-dir <dir> --score-route vcsl|ace-step:<job_id> | --dry)

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
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from . import budget, colab_jobs, film, importer, mix, qc, reel, scenes
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
                    "order": order.get(jid, -1),
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


def _planned_shots(rec, n):
    """shots.json, but only when planned from this script's measured narration (R20)."""
    t = f"reel-{n}"
    planned = _last_event(rec, "reel", "shots_planned", t)
    if planned < 0 or planned < _last_event(rec, "reel", "scripted", t):
        return None, -1
    return _json(rec.root / "reels" / t / "shots.json"), planned


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
    shots, planned = _planned_shots(rec, n)
    if shots is None:
        raise Stop(f"reel {n} has no shot plan from its measured narration", next_action(rec.root))
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


def _colab_action(rec, job) -> str:
    if job["kind"] == "reel_clips":
        return _wan_action(rec, job)
    drive = _json(job["manifest"]).get("drive_dir", colab_jobs.DRIVE_ROOT)
    return (f"Run the {job['kind']} notebook in Colab: copy {job['inputs_zip']} to Drive {drive}/, "
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


def cmd_job(args):
    rec = _record(args.root)
    kind = args.kind
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
                   f"(caps {budget.TITLE_CAP:g}/title, {budget.MONTH_CAP:g}/month, {month}). "
                   "Nothing was reserved or written.", hint, code=3)
    try:
        result = colab_jobs.build_job(kind, rec, spec, ledger, rates, rec.root / "jobs", month=month)
    except budget.BudgetExceeded as e:
        raise Stop(f"Budget exceeded: {e}. Nothing was written.",
                   "Hold the job and ask the owner; never retry past a cap.", code=3)
    except (ValueError, FileExistsError, KeyError) as e:
        raise Stop(f"job not built: {e}", "Fix the spec and rerun")
    rec.event("cli", "job_target", {"job_id": result["job_id"], "target": target, "kind": kind})
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
    units = [u for sc in scs for u in voice_units(sc, {"description": ""}, None, lang)]
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
    info = film.assemble(plan["plan"], timing, rec.root / "stills" / stills["job_id"], out / "mix.wav",
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
    if built and built["job_id"] not in _misfits(rec):
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
                                        "narration_seconds": seconds, "narration_job_id": narr["job_id"]})
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
    script, narr = _reel_script(rec, n), _reel_narration(rec, n)
    shots, planned = _planned_shots(rec, n)
    if script is None or narr is None or shots is None:
        raise Stop(f"{t} needs a script, its imported narration and a shot plan", next_action(rec.root))
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
        "generators": [{"model": colab_jobs.NARRATION_REPO, "revision": colab_jobs.NARRATION_REVISION,
                        "licence": "Apache-2.0", "job_ids": ids,
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
        for j in _jobs(rec):
            closed = next((e["detail"]["units"] for e in rec.data["events"] if e["result"] == "closed"
                           and e["detail"].get("job_id") == j["job_id"]), None)
            state = ("imported" if j["imported"] else "superseded" if j["superseded"]
                     else f"closed (ran, not imported; {closed:.2f} CU settled)" if j["closed"]
                     else "supersede/close unfinished: rerun it" if j["unfinished"]
                     else "waiting for Colab")
            print(f"  {j['job_id']} {j['kind']} {j['target']}: {state} "
                  f"(forecast {j['forecast_units']:.2f} CU)")


COMMANDS = {"init": cmd_init, "plan": cmd_plan, "job": cmd_job, "import": cmd_import,
            "supersede": cmd_supersede, "close": cmd_close,
            "film": cmd_film, "reel": cmd_reel, "qc": cmd_qc, "status": cmd_status,
            "bundle-audio": cmd_bundle_audio}


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
    s = add("import")
    s.add_argument("job_id")
    s.add_argument("--from", dest="source", required=True)
    s.add_argument("--units", type=float, required=True)
    s.add_argument("--archive-sha256")
    s = add("supersede")
    s.add_argument("job_id")
    s.add_argument("--reason", required=True)
    s = add("close")
    s.add_argument("job_id")
    s.add_argument("--units", type=float, required=True, help="the CU Colab shows the run used")
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
