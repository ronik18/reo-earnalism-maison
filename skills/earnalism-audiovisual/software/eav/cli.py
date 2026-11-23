"""earnalism-audiovisual orchestrator: one title root, one production record, one next action.

  python3 -m eav.cli init <source.json> --root <dir> [--slug <maison-edition-slug>]
  python3 -m eav.cli plan --root <dir>
  python3 -m eav.cli job <narration|stills|music|reel_clips> --root <dir> --rates <rates.json>
                         [--film N | --reel N] [--spec <spec.json>] [--clause "..."]
  python3 -m eav.cli import <job_id> --root <dir> --from <folder|archive> --units <CU>
                         [--archive-sha256 <sha>]           (reel_clips)
  python3 -m eav.cli film --root <dir> [--film N] --logo <png> --end-card <png> (--score <wav> | --cues-job <id>)
  python3 -m eav.cli reel <n> --root <dir> [--script <script.json>] [--score <wav>] [--hashtags ...]
  python3 -m eav.cli qc --root <dir>
  python3 -m eav.cli status --root <dir>
  python3 -m eav.cli bundle-audio --root <dir> --out <bundle dir> (--score-dir <dir> | --dry)

Every command ends with "Next: ..." -- the one action the owner (or Claude) takes next.
The CLI wraps the eav modules; it spends nothing, runs no GPU work, never marks legal clearance
and never publishes. Exit codes: 0 ok, 2 stop, 3 budget exceeded, 4 import held, 5 QC failure.
The allowance ledger is shared by every title: --ledger, else $EAV_LEDGER, else
<root>/../allowance-ledger.json.
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
from pathlib import Path

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
MP3_END_SLACK_MS = 50


class Stop(Exception):
    def __init__(self, message, next_action, code=2):
        super().__init__(message)
        self.next_action, self.code = next_action, code


# ---------------------------------------------------------------- state helpers
def _ledger(args) -> budget.Ledger:
    path = args.ledger or os.environ.get("EAV_LEDGER") or Path(args.root).parent / "allowance-ledger.json"
    return budget.Ledger(Path(path))


def _month(args) -> str:
    return args.month or datetime.now(timezone.utc).strftime("%Y-%m")


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
    targets = {e["detail"]["job_id"]: e["detail"]["target"] for e in rec.data["events"]
               if e["stage"] == "cli" and e["result"] == "job_target"}
    imported = {e["detail"]["job_id"] for e in rec.data["events"]
                if e["stage"] == "import" and e["result"] == "accepted"}
    out = []
    for a in rec.data["artifacts"]:
        if a["kind"] != "colab_job":
            continue
        m = a["meta"]
        out.append({"job_id": m["job_id"], "kind": m["job_kind"], "target": targets.get(m["job_id"]),
                    "notebook": rec.root / a["path"], "inputs_zip": rec.root / m["inputs_zip"],
                    "manifest": rec.root / m["manifest"], "forecast_units": m["forecast_units"],
                    "imported": m["job_id"] in imported})
    return out


def _latest_job(rec, kind, target, imported=True):
    found = [j for j in _jobs(rec) if j["kind"] == kind and j["target"] == target
             and (j["imported"] or not imported)]
    return found[-1] if found else None


def _artifacts(rec, kind, **meta):
    return [a for a in rec.data["artifacts"] if a["kind"] == kind
            and all(a["meta"].get(k) == v for k, v in meta.items())]


def _film_target(n: int) -> str:
    return f"film-{n:02d}"


def _reel_scene(script: dict, n: int) -> dict:
    return {"scene_id": f"r{n}", "blocks": [{"anchor_id": None, "kind": "paragraph", "text": line}
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


def _remaining(ledger, title, month) -> float:
    return min(budget.TITLE_CAP - ledger.spent(title, month),
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
def _colab_action(rec, job) -> str:
    if job["kind"] == "reel_clips":
        return (f"Run the reel_clips (Wan 2.2) notebook in Colab: open {job['notebook']}, upload "
                f"{job['inputs_zip']}, set RUN = True in the first cell, Run all, download the export "
                f"archive, then: {PROG} import {job['job_id']} --root {rec.root} --from <archive.zip> "
                f"--archive-sha256 <sha256 printed by the notebook> --units <CU shown in Colab>")
    drive = _json(job["manifest"]).get("drive_dir", colab_jobs.DRIVE_ROOT)
    return (f"Run the {job['kind']} notebook in Colab: copy {job['inputs_zip']} to Drive {drive}/, "
            f"open {job['notebook']}, set RUN = True in the first cell, Run all; download that Drive "
            f"folder, then: {PROG} import {job['job_id']} --root {rec.root} --from <downloaded folder> "
            f"--units <CU shown in Colab>")


def next_action(root) -> str:
    root = Path(root)
    if not (root / "record.json").is_file():
        return f"{PROG} init <source.json> --root {root} --slug <maison-edition-slug>"
    rec = Record.load(root)
    if not (root / "plan.json").is_file():
        return f"{PROG} plan --root {root}"
    pending = [j for j in _jobs(rec) if not j["imported"]]
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
                    f"--score <score bed from earnalism-audiobook-score> (or --cues-job <music job_id>)")
    n = 1
    while True:
        script = _reel_script(rec, n)
        if script is None:
            if n == 1:
                return (f"Write reel 1 (hook, lines, loop_close; references/reel-recipe.md) into "
                        f"reel-1.json, then: {PROG} reel 1 {r} --script reel-1.json")
            break
        t = f"reel-{n}"
        if not _latest_job(rec, "stills", t):
            return (f"Write one keyframe prompt per shot in reels/reel-{n}/shots.json into stills.json, "
                    f"then: {PROG} job stills {r} --reel {n} --rates <rates.json> --spec stills.json")
        if not _latest_job(rec, "reel_clips", t):
            return (f"Write the Wan shot spec (art_dir = the imported reel-{n} stills, one motion prompt "
                    f"per shot), then: {PROG} job reel_clips {r} --reel {n} --rates <rates.json> "
                    f"--spec clips.json")
        if not _latest_job(rec, "narration", t):
            return f"{PROG} job narration {r} --reel {n} --rates <rates.json>"
        if not _artifacts(rec, "reel", target=t):
            return f"{PROG} reel {n} {r} --score <reel score bed>"
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
                f"{root / 'maison' / 'bundle'} --score-dir <one score bed per chapter>. Maison video stays held (Stream cost not approved). "
                "Social posting only to destinations the owner names (references/publishing.md).")
    return (f"Complete and owner-approve {root / 'maison' / EVIDENCE_DRAFT}, save it under docs/evidence/, "
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
    rec = Record.create(root, slug, {
        "edition_id": src.get("edition_id"), "revision_id": src["revision_id"],
        "content_sha256": src["content_sha256"], "language": src["language"],
        "rights": src.get("rights", {}), "public_domain_evidence": True,
        "state": src.get("state"), "export_sha256": sha256_file(src_path)})
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
        items = sum(len(voice_units(s, spec["preset"], args.clause, lang)) for s in todo)
    else:
        if not args.spec:
            raise Stop(f"a {kind} job needs --spec (prompts, seeds{', shots' if kind == 'reel_clips' else ''})",
                       "Write it per references/film-recipe.md or references/reel-recipe.md")
        spec = _json(args.spec)
        if kind == "reel_clips" and not Path(spec.get("art_dir", ".")).is_absolute():
            spec["art_dir"] = str((Path(args.spec).parent / spec.get("art_dir", ".")).resolve())
        items = len(spec.get("shots" if kind == "reel_clips" else "items") or [])
    if args.job_id:
        spec["job_id"] = args.job_id
    return spec, items


def cmd_job(args):
    rec = _record(args.root)
    kind = args.kind
    if kind == "reel_clips" and not args.reel:
        raise Stop("reel_clips jobs belong to one reel", "Pass --reel <n>")
    target = f"reel-{args.reel}" if args.reel else _film_target(args.film)
    rates = _json(args.rates)
    rate = rates.get(kind) or {}
    if not all(isinstance(rate.get(k), (int, float)) for k in ("s_per_step", "units_per_hour")):
        raise Stop(f"rates.json has no measured s_per_step/units_per_hour for {kind}",
                   "Take them from the last Colab run (references/compute-budget.md)")
    spec, items = _job_spec(rec, args, kind, target)
    if "compute" not in spec:
        missing = [k for k in ("steps", "decode_s", "export_s") if k not in rate]
        if missing:
            raise Stop(f"no measured {', '.join(missing)} for {kind} in rates.json; forecasts are "
                       "never defaulted", "Add the values measured on the last Colab run "
                       "(references/compute-budget.md)")
        spec["compute"] = {"steps": rate["steps"], "items": items, "takes": rate.get("takes", 1),
                           "decode_s": rate["decode_s"], "export_s": rate["export_s"]}
    ledger, month, title = _ledger(args), _month(args), rec.data["title_slug"]
    try:
        units = budget.forecast({"kind": kind, **spec["compute"]}, rates)
    except (KeyError, TypeError) as e:
        raise Stop(f"cannot forecast {kind}: {e}", "Fix rates.json / spec compute block")
    remaining = _remaining(ledger, title, month)
    if units > remaining:
        hint = "Hold the job and ask the owner; never retry past a cap."
        if kind == "reel_clips":
            fit = budget.fit_reel_job({"kind": kind, **spec["compute"]}, rates, remaining)
            if fit:
                hint = (f"Cut the spec to takes={fit['takes']}, shots={fit['items']} "
                        f"(takes first, then shots), then rerun; or hold for the owner.")
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
          "Inert until RUN = True.")


def cmd_import(args):
    rec = _record(args.root)
    job = next((j for j in _jobs(rec) if j["job_id"] == args.job_id), None)
    if job is None:
        raise Stop(f"unknown job {args.job_id}", f"{PROG} status --root {rec.root}")
    if job["imported"]:
        raise Stop(f"job {args.job_id} is already imported", f"{PROG} status --root {rec.root}")
    extra = {}
    if job["kind"] == "reel_clips":
        extra = {"archive": Path(args.source), "archive_sha256": args.archive_sha256}
    try:
        arts = importer.import_job(rec, {k: job[k] for k in ("job_id", "kind", "notebook",
                                                             "inputs_zip", "manifest")},
                                   args.source, _ledger(args), args.units, **extra)
    except importer.ImportHeld as e:
        raise Stop(f"Import held: {e}. Nothing was imported; the reservation stays open.",
                   "Re-download the complete output folder (or archive) of this exact job and rerun "
                   f"{PROG} import {args.job_id} ...; never rebuild or rerun the job to get past it.",
                   code=4)
    print(f"Imported {len(arts)} verified file(s) from {job['kind']} job {args.job_id}; "
          f"settled {args.units:g} CU.")


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
                                                "true_peak": m["true_peak"], **info})
    rec.event("film", "assembled", {"target": t, "duration": info["duration"]})
    print(f"Assembled {out / (t + '.mp4')}: {info['duration']:.1f} s, {m['lufs']:.1f} LUFS, "
          f"TP {m['true_peak']:.1f} dBTP. Maison video stays held (Stream cost not approved).")


def cmd_reel(args):
    rec = _record(args.root)
    n, t = args.n, f"reel-{args.n}"
    folder = rec.root / "reels" / t
    if args.script:
        script = _json(args.script)
        try:
            reel.validate_script(script)
            shots = reel.shot_list(script)
        except ValueError as e:
            raise Stop(f"reel script rejected: {e}", "Fix the script per references/reel-recipe.md")
        if _latest_job(rec, "narration", t, imported=False):
            raise Stop(f"{t} narration was already built from its script", f"{PROG} status --root {rec.root}")
        _write_json(folder / "script.json", script)
        _write_json(folder / "shots.json", shots)
        (folder / "caption.txt").write_text(reel.caption(script, args.hashtags or []) + "\n", encoding="utf-8")
        for kind, name in (("reel_script", "script.json"), ("shot_list", "shots.json"),
                           ("caption", "caption.txt")):
            rec.add_artifact(kind, folder / name, {"target": t})
        rec.event("reel", "scripted", {"target": t, "shots": len(shots)})
        print(f"Reel {n}: {len(shots)} shots of {shots[0]['seconds']} s; caption written.")
        return
    script = _reel_script(rec, n)
    narr, clips_job = _latest_job(rec, "narration", t), _latest_job(rec, "reel_clips", t)
    if script is None or not narr or not clips_job:
        raise Stop(f"{t} needs a script plus imported narration and reel_clips jobs", next_action(rec.root))
    order = [s["id"] for s in _json(clips_job["inputs_zip"].parent / "job.json")["scenes"]]
    by_scene = {a["meta"]["scene"]: rec.root / a["path"]
                for a in _artifacts(rec, "reel_clip", job_id=clips_job["job_id"])}
    clips = [by_scene[s] for s in order]
    units = voice_units(_reel_scene(script, n), {"description": ""}, None, script["language"])
    _, prov = _measured_track(units, rec.root / "narration" / narr["job_id"],
                              folder / "narration.wav", narr["job_id"])
    total = sum(film._duration(c) for c in clips)
    spoken = film._duration(folder / "narration.wav")
    if spoken > total + reel.AUDIO_TOLERANCE_S:
        raise Stop(f"QC failure: narration {spoken:.2f} s is longer than the clips {total:.2f} s; "
                   "narration is never trimmed", "Add or lengthen a shot, then rerun", code=5)
    _ff("-i", folder / "narration.wav", "-af", f"apad=whole_dur={total:.3f}", "-ar", 48000,
        folder / "narration-padded.wav")
    audio = folder / "narration-padded.wav"
    if args.score:
        _ff("-i", args.score, "-t", f"{total:.3f}", "-ar", 48000, folder / "score-cut.wav")
        try:
            mix.duck_and_master(audio, folder / "score-cut.wav", folder / "mix.wav", REEL_LUFS)
        except ValueError as e:
            raise Stop(f"QC failure: {e}", "Re-balance the reel score and rerun", code=5)
        audio = folder / "mix.wav"
    try:
        info = reel.assemble(clips, audio, folder / f"{t}.mp4")
    except ValueError as e:
        raise Stop(f"QC failure: {e}", "Fix the failing input and rerun", code=5)
    _write_json(folder / "narration-provenance.json", prov)
    rec.add_artifact("reel", folder / f"{t}.mp4", {"target": t, **info})
    rec.event("reel", "assembled", {"target": t, "seconds": info["seconds"]})
    print(f"Assembled {folder / (t + '.mp4')}: {info['seconds']:.1f} s, {info['lufs']:.1f} LUFS.")


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
    if args.dry and args.score_dir:
        raise Stop("--dry and --score-dir exclude each other", "Choose one")
    if not args.dry:
        if not args.score_dir:
            raise Stop("Maison audio carries narration with its background score: pass --score-dir "
                       "<dir> holding <unit_id>.wav per chapter (from `earnalism-audiobook-score`), or "
                       "--dry for narration only (recorded in the evidence draft)",
                       "Prepare one score bed per chapter, then rerun bundle-audio --score-dir <dir>")
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
            master, mastered, score_sha = chapter, None, None
            if not args.dry:  # R10: narration + best-fit score, ducked, -16 LUFS
                bed = Path(args.score_dir) / f"{unit['unit_id']}.wav"
                score_sha = sha256_file(bed)
                cut = td / f"unit-{n:03d}-score.wav"
                _ff("-i", bed, "-t", f"{timing[-1]['end']:.3f}", "-ar", 48000, "-ac", 2, cut)
                master = td / f"unit-{n:03d}-mix.wav"
                try:
                    mix.duck_and_master(chapter, cut, master, FILM_LUFS)
                except ValueError as e:
                    raise Stop(f"QC failure: {unit['unit_id']}: {e}",
                               "Re-balance that chapter's score bed and rerun", code=5)
                mastered = "eav.mix.duck_and_master"
            mp3 = bundle / f"unit-{n:03d}.mp3"
            channels = 1 if args.dry else 2  # keep the stereo master's loudness intact
            _ff("-i", master, "-ar", 48000, "-ac", channels, "-c:a", "libmp3lame", "-b:a", "96k", mp3)
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
                "encoder": f"ffmpeg libmp3lame 96 kbps CBR {'mono' if args.dry else 'stereo'} 48 kHz"}
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
            "route": "per-chapter score bed, ducked under speech (eav.mix.duck_and_master, -16 LUFS)",
            "score_sha256": {u: v["score_sha256"] for u, v in prov_units.items()},
            "source_and_licence": None},
        "owner_approval": None})
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
        s, title, month = rec.data["source"], rec.data["title_slug"], _month(args)
        ledger = _ledger(args)
        print(f"{title}: revision {s['revision_id']} ({s['language']}), "
              f"{ledger.spent(title, month):.2f} CU spent/reserved this month for this title, "
              f"{_remaining(ledger, title, month):.2f} CU remaining ({month}).")
        for j in _jobs(rec):
            print(f"  {j['job_id']} {j['kind']} {j['target']}: "
                  f"{'imported' if j['imported'] else 'waiting for Colab'} "
                  f"(forecast {j['forecast_units']:.2f} CU)")


COMMANDS = {"init": cmd_init, "plan": cmd_plan, "job": cmd_job, "import": cmd_import,
            "film": cmd_film, "reel": cmd_reel, "qc": cmd_qc, "status": cmd_status,
            "bundle-audio": cmd_bundle_audio}


def _parser():
    p = argparse.ArgumentParser(prog=PROG, description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--root", required=True)
        s.add_argument("--ledger")
        s.add_argument("--month", help="YYYY-MM (default: current UTC month)")
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
    s = add("film")
    s.add_argument("--film", type=int, default=1)
    s.add_argument("--logo", required=True)
    s.add_argument("--end-card", required=True)
    s.add_argument("--score")
    s.add_argument("--cues-job")
    s = add("reel")
    s.add_argument("n", type=int)
    s.add_argument("--script")
    s.add_argument("--score")
    s.add_argument("--hashtags", nargs="*")
    add("qc")
    add("status")
    s = add("bundle-audio")
    s.add_argument("--out", required=True)
    s.add_argument("--score-dir", help="<unit_id>.wav score bed per chapter (default route)")
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
    print(f"Next: {next_action(args.root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
