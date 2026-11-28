"""Inert, hash-bound Colab job bundles (narration, stills, music, reel clips).

Building a bundle spends nothing: it reserves the forecast on the ledger,
writes a notebook (nbformat 4, plain JSON) and an input zip, and records both.
The owner runs the notebook by hand; every notebook starts with RUN = False.
"""
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import cast as cast_mod
from .budget import BudgetExceeded, forecast, forecast_seconds
from .voice import unit_boundaries, voice_units

NARRATION_REPO = "ai4bharat/indic-parler-tts"
NARRATION_REVISION = "7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca"
STILLS_REPO = "black-forest-labs/FLUX.1-schnell"
STILLS_STEPS = 4
# Resolved to an exact commit (plus weight hashes) by the notebook at run time.
MUSIC_REPO = "ACE-Step/ACE-Step-v1-3.5B"
MUSIC_STEPS = 60
REEL_PROFILE = "l4-balanced-v2"
# One reel_clips batch must fit one Wan job (batch.MAX_WALL_SECONDS = 2700 s) at the measured
# ~500 s per finished clip, and the owner's metered Wan authority approves at most 5 CU.
MAX_CLIPS_PER_BATCH = 5
MAX_APPROVED_UNITS = 5.0
DRIVE_ROOT = "/content/drive/MyDrive/earnalism-audiovisual"

KINDS = ("narration", "stills", "music", "reel_clips")
# Long narration/stills jobs are cut into consecutive chunks of at most this many forecast seconds
# (margin included), so each chunk fits one GPU session and resumes cleanly. This is for session
# length only: the caps are checked once against the sum of every chunk (chunk_forecasts).
MAX_CHUNK_SECONDS = 3600
CHUNKED_KINDS = ("narration", "stills")
JOB_SCHEMA = "earnalism.audiovisual-job.v1"
_TEMPLATES = Path(__file__).with_name("templates")
# The segment join the narration cell runs (multi-voice units), embedded verbatim at build time.
_JOIN_SOURCE = Path(__file__).with_name("narration_join.py")
_JOIN_MARK = "# @@eav.narration_join@@\n"
_WAN_DIR = Path(__file__).resolve().parents[3] / "earnalism-video" / "software" / "wan22"
_SAFE = re.compile(r"[a-z0-9][a-z0-9-]*")
_FORBIDDEN = ("musicgen", "flux.1-dev")


def _load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_wan_batch():
    return _load_file("earnalism_wan22_batch_for_eav", _WAN_DIR / "batch.py")


def _load_wan_builder():
    return _load_file("earnalism_wan22_build_batch_colab_for_eav", _WAN_DIR / "build_batch_colab.py")


def _check_model(kind: str, spec: dict, expected: str) -> None:
    for key in ("model", "repo", "model_repo"):
        value = spec.get(key)
        if value is None:
            continue
        low = str(value).lower()
        if any(bad in low for bad in _FORBIDDEN):
            raise ValueError(f"forbidden model: {value!r}")
        if value != expected:
            raise ValueError(f"{kind} job must use {expected!r}, not {value!r}")


def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            z.writestr(info, files[name])
    return buf.getvalue()


def _cell(kind: str, text: str, index: int) -> dict:
    cell = {"id": f"eav-{index:02}", "cell_type": kind, "metadata": {},
            "source": text.splitlines(keepends=True)}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


_GUARD = ('if RUN is not True:\n'
          '    raise RuntimeError("RUN is False; set RUN = True in the first cell to run this job")\n')

_VERIFY = _GUARD + '''import hashlib, json, pathlib, zipfile
from google.colab import drive
drive.mount("/content/drive")
OUT_DIR = pathlib.Path(DRIVE_JOB_DIR)
INPUT_ZIP = OUT_DIR / "inputs.zip"
if not INPUT_ZIP.is_file():
    raise RuntimeError("Copy inputs.zip into " + str(OUT_DIR) + " first")
actual = hashlib.sha256(INPUT_ZIP.read_bytes()).hexdigest()
if actual != INPUT_ZIP_SHA256:
    raise RuntimeError("inputs.zip sha256 mismatch: " + actual)
with zipfile.ZipFile(INPUT_ZIP) as z:
    JOB = json.loads(z.read("job.json"))
if JOB["job_id"] != JOB_ID:
    raise RuntimeError("job.json belongs to a different job")
print("inputs verified for", JOB_ID)
attach_session()
'''

# R25: the hard stop counts from this cell (run right after the config) and equals the forecast
# seconds the ledger reserved, minus what earlier sessions of the same job already used. Items start only while they can still finish before it; a Timer
# unassigns the runtime at the stop itself, as the Wan notebook does.
_CLOCK = _GUARD + '''import hashlib, json, os, threading, time
BOOKKEEPING = ("progress.jsonl", "sessions.jsonl")  # resume records: never outputs


def _rows(name):
    rows = []
    path = OUT_DIR / name
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a line torn by a disconnect
            if isinstance(row, dict):
                rows.append(row)
    return rows


_APPEND_LOCK = globals().get("_APPEND_LOCK") or threading.Lock()


def _append(name, row):
    # the heartbeat thread and the main thread both append: one writer at a time
    with _APPEND_LOCK:
        path = OUT_DIR / name
        torn = path.is_file() and path.stat().st_size > 0 and path.read_bytes()[-1:] != b"\\n"
        with open(path, "a") as f:
            f.write(("\\n" if torn else "") + json.dumps(row, sort_keys=True) + "\\n")
            f.flush()
            os.fsync(f.fileno())


def session_seconds():
    # started -> seconds, the latest line per session (this one once it has started)
    latest = {}
    for row in _rows("sessions.jsonl"):
        if "started" in row and isinstance(row.get("seconds"), (int, float)):
            latest[row["started"]] = row["seconds"]
    return latest


def note_session():
    _append("sessions.jsonl", {"started": JOB_STARTED, "seconds": round(time.time() - JOB_STARTED, 1)})


def resume_done(names):
    # Finished = present AND matching its progress.jsonl line written for THIS inputs.zip (a line
    # of other inputs proves nothing); a file without one is deleted (redone).
    logged = {}
    for row in _rows("progress.jsonl"):
        if isinstance(row.get("file"), str) and isinstance(row.get("sha256"), str) \\
                and row.get("zip") == INPUT_ZIP_SHA256:
            logged[row["file"]] = row["sha256"]
    done = set()
    for name in names:
        path = OUT_DIR / name
        if not path.is_file():
            continue
        if logged.get(name) == hashlib.sha256(path.read_bytes()).hexdigest():
            done.add(name)
        else:
            path.unlink()
            print("redo", name, "(no matching progress line)")
    return done


def record_item(key, name, item_s=None, segments_s=None):
    # item_s: the seconds this item (or its batch) took; a resumed session starts from it.
    # segments_s: a joined multi-voice unit's seconds per segment (the manifest reports them)
    digest = hashlib.sha256((OUT_DIR / name).read_bytes()).hexdigest()
    row = {"key": key, "file": name, "sha256": digest, "zip": INPUT_ZIP_SHA256}
    if isinstance(item_s, (int, float)) and not isinstance(item_s, bool) and item_s >= 0:
        row["item_s"] = round(item_s, 1)
    if segments_s is not None:
        row["segments_s"] = [round(float(x), 3) for x in segments_s]
    _append("progress.jsonl", row)
    note_session()


def last_item_seconds():
    # The latest recorded item (or batch) time, so a resumed session's first item starts only if
    # it can finish before the stop; 0.0 before any item of this job finished.
    times = [r["item_s"] for r in _rows("progress.jsonl") if r.get("zip") == INPUT_ZIP_SHA256
             and isinstance(r.get("item_s"), (int, float))]
    return float(times[-1]) if times else 0.0


def _hard_stop():
    try:
        note_session()
    except Exception as e:  # Drive may have dropped; the runtime must still be released
        print("could not record the session seconds:", e)
    finally:
        runtime.unassign()


def _heartbeat():
    while not HEARTBEAT_STOP.wait(HEARTBEAT_S):
        try:
            note_session()  # a session killed mid-batch (OOM, disconnect) is still charged
        except Exception:
            pass


def attach_session():
    # Run once OUT_DIR is known (after the Drive mount): shorten the stop by what earlier sessions
    # used, charge this session from JOB_STARTED, and start the heartbeat.
    global PRIOR_SECONDS, EFFECTIVE_DEADLINE, STOP_GUARD, SESSION_ATTACHED
    if SESSION_ATTACHED:
        return
    PRIOR_SECONDS = sum(v for k, v in session_seconds().items() if k != JOB_STARTED)
    EFFECTIVE_DEADLINE = DEADLINE_SECONDS - PRIOR_SECONDS
    remaining = EFFECTIVE_DEADLINE - (time.time() - JOB_STARTED)
    if remaining <= 0:
        note_session()
        raise RuntimeError("reserved time used up: close the job with the CU Colab shows")
    STOP_GUARD.cancel()
    STOP_GUARD = threading.Timer(remaining, _hard_stop)
    STOP_GUARD.daemon = True
    STOP_GUARD.start()
    note_session()
    SESSION_ATTACHED = True
    threading.Thread(target=_heartbeat, daemon=True).start()
    print("reserved %d s, %d s used by earlier sessions" % (DEADLINE_SECONDS, PRIOR_SECONDS))


# R25: the hard stop is armed here, right after the config, for the full reserved seconds; the
# verify cell then calls attach_session() to take off what earlier sessions used.
HEARTBEAT_S = globals().get("HEARTBEAT_S", 20)
HEARTBEAT_STOP = globals().get("HEARTBEAT_STOP") or threading.Event()
if "JOB_STARTED" not in globals():
    JOB_STARTED = time.time()
    PRIOR_SECONDS = 0
    EFFECTIVE_DEADLINE = DEADLINE_SECONDS
    SESSION_ATTACHED = False
    from google.colab import runtime
    STOP_GUARD = threading.Timer(DEADLINE_SECONDS, _hard_stop)
    STOP_GUARD.daemon = True
    STOP_GUARD.start()
INCOMPLETE = False


def may_start(last_item_s):
    # Between items: start the next one only if it (and the manifest) fits before the hard stop.
    global INCOMPLETE
    left = EFFECTIVE_DEADLINE - (time.time() - JOB_STARTED)
    if left < last_item_s + MANIFEST_RESERVE_S:
        INCOMPLETE = True
        print("HARD STOP: %.0f s left of the %d s still reserved; no further item starts" % (left, EFFECTIVE_DEADLINE))
        return False
    return True


print("hard stop armed:", DEADLINE_SECONDS, "s from now")
'''

_MANIFEST = _GUARD + '''import hashlib, json, time
import importlib.metadata as _md
outputs = {}
for p in sorted(OUT_DIR.iterdir()):
    if p.is_file() and p.name not in ("manifest.json", "inputs.zip") + BOOKKEEPING:
        outputs[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
if not outputs:
    raise RuntimeError("no outputs were produced")
packages = {}  # R26: the resolved versions (and VCS commits) that actually ran
for _name in PACKAGES:
    try:
        _dist = _md.distribution(_name)
        _url = json.loads(_dist.read_text("direct_url.json") or "{}")
        _commit = _url.get("vcs_info", {}).get("commit_id")
        packages[_name] = _dist.version + (" @ " + _commit if _commit else "")
    except _md.PackageNotFoundError:
        packages[_name] = None
note_session()
_sessions = session_seconds()
complete = not INCOMPLETE and all(name in outputs for name in EXPECTED)
manifest = {"schema": "earnalism.audiovisual-outputs.v1", "job_id": JOB_ID, "title": TITLE,
            "kind": KIND, "input_zip_sha256": INPUT_ZIP_SHA256, "model": MODEL_INFO,
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "deadline_seconds": DEADLINE_SECONDS,
            "elapsed_seconds": round(sum(_sessions.values()), 1), "sessions": len(_sessions),
            "packages": packages, "outputs": outputs}
# a joined multi-voice narration unit: its seconds per segment, from the latest progress line of
# each output of these inputs (per-segment truncation QC); absent for single-voice jobs
_segments = {}
for _row in _rows("progress.jsonl"):
    if _row.get("zip") == INPUT_ZIP_SHA256 and _row.get("file") in outputs \\
            and isinstance(_row.get("segments_s"), list):
        _segments[_row["key"]] = _row["segments_s"]
if _segments:
    manifest["segment_seconds"] = _segments
(OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\\n")
print("manifest.json written:", manifest["status"], len(outputs), "files")
if not complete:
    print("INCOMPLETE: import refuses this folder; close the job with the CU Colab shows")
'''

# Distributions whose resolved versions each manifest records (R26).
PACKAGES = {"narration": ("parler_tts", "transformers", "torch", "soundfile"),
            "stills": ("diffusers", "transformers", "accelerate", "sentencepiece", "protobuf", "torch"),
            "music": ("ace-step", "acestep", "torch", "transformers", "diffusers", "huggingface_hub", "torchcodec", "torchaudio")}
MANIFEST_RESERVE_S = 60


def _cell_source(template: Path) -> str:
    text = template.read_text(encoding="utf-8")
    if _JOIN_MARK in text:
        text = text.replace(_JOIN_MARK, _JOIN_SOURCE.read_text(encoding="utf-8") + "\n")
    return text


def _notebook(kind, job_id, title, zip_sha, repo, revision, steps, template, deadline_s) -> bytes:
    config = (_GUARD +
              f"import pathlib\nJOB_ID = {job_id!r}\nTITLE = {title!r}\nKIND = {kind!r}\n"
              f"INPUT_ZIP_SHA256 = {zip_sha!r}\nMODEL_REPO = {repo!r}\n"
              f"MODEL_REVISION = {revision!r}\nSTEPS = {steps!r}\n"
              f"DRIVE_JOB_DIR = {DRIVE_ROOT + '/' + title + '/' + job_id!r}\n"
              f"# Hard wall-clock stop = the forecast seconds reserved on the ledger (R25)\n"
              f"DEADLINE_SECONDS = {int(deadline_s)}\nMANIFEST_RESERVE_S = {MANIFEST_RESERVE_S}\n"
              f"PACKAGES = {PACKAGES[kind]!r}\n")
    intro = (f"# Earnalism {kind} job `{job_id}`\n\n**Prepared, not run.** Input zip SHA256 "
             f"`{zip_sha}`. Copy `inputs.zip` to `{DRIVE_ROOT}/{title}/{job_id}/` in Drive, set "
             f"`RUN = True` in the first cell, then run all. Outputs and `manifest.json` "
             f"(sha256 of every output) land in the same folder.\n\n**Hard stop:** "
             f"{int(deadline_s)} s (the reserved forecast) from the clock cell. No item starts after "
             f"it and the runtime is unassigned at it; a stopped run's manifest says INCOMPLETE and "
             f"cannot be imported.\n\n**Disconnected?** Run all again: finished items are kept "
             f"(`progress.jsonl`, checked by sha256) and the run continues where it stopped, "
             f"within the same reserved time (`sessions.jsonl` counts what earlier runs used).\n")
    # The clock arms the stop first; the verify cell sets JOB/OUT_DIR and attaches the session.
    parts = [("markdown", intro), ("code", "RUN = False"), ("code", config), ("code", _CLOCK),
             ("code", _VERIFY), ("code", _cell_source(template)),
             ("code", _MANIFEST)]
    nb = {"nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"},
                       "language_info": {"name": "python"},
                       "colab": {"name": f"earnalism_{kind}_{job_id}.ipynb",
                                 "gpuType": "L4"}},
          "cells": [_cell(k, t, i) for i, (k, t) in enumerate(parts)]}
    return (json.dumps(nb, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


# Pinned Parler generation settings a roster preset may carry (R9). Anything else in the
# preset (keys, hashes, status) is metadata and never reaches generate().
GENERATION_KEYS = ("temperature", "top_p", "top_k", "do_sample", "repetition_penalty",
                   "max_new_tokens", "min_new_tokens")


def _generation(preset: dict) -> dict:
    out = {}
    for k in GENERATION_KEYS:
        if k not in preset:
            continue
        v = preset[k]
        if k == "do_sample":
            ok = isinstance(v, bool)
        elif k in ("top_k", "max_new_tokens", "min_new_tokens"):
            ok = isinstance(v, int) and not isinstance(v, bool) and v > 0
        else:
            ok = (isinstance(v, (int, float)) and not isinstance(v, bool) and v == v
                  and 0 < v <= (1 if k == "top_p" else 5))
        if not ok:
            raise ValueError(f"preset generation setting {k!r} invalid: {v!r}")
        out[k] = v
    return out


DEFAULT_BATCH = 8


def _batch(spec: dict) -> int:
    """Units per generate() call; pinned in job.json, so it is part of the job identity."""
    v = spec.get("batch", DEFAULT_BATCH)
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 32:
        raise ValueError(f"narration batch must be an integer from 1 to 32, not {v!r}")
    return v


def pinned_steps(kind: str) -> int:
    """The step count each job kind is pinned to; a forecast never uses another one."""
    if kind == "narration":
        return 1  # one "step" is one voice unit
    if kind == "stills":
        return STILLS_STEPS
    if kind == "music":
        return MUSIC_STEPS
    if kind == "reel_clips":
        return _load_wan_batch().w.PROFILES[REEL_PROFILE]["steps"]
    raise ValueError(f"unknown job kind: {kind!r}")


def reel_clip_seconds() -> float:
    """Length of one pinned Wan clip: frames / fps (121 / 24 = 5.041667 s)."""
    shape = _load_wan_batch().w.PROFILES[REEL_PROFILE]
    return shape["frames"] / shape["fps"]


def _measured(value, positive=False) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def derive_compute(kind: str, spec: dict, rates: dict, items: int) -> dict:
    """Forecast inputs, derived from the job's real item count, the pinned steps and the measured
    rates (R21). A spec `compute` block can only restate them: any disagreement is refused, so
    it can never lower the forecast."""
    rate = rates.get(kind) if isinstance(rates, dict) else None
    needed = ("clip_s", "units_per_hour") if kind == "reel_clips" else (
        "s_per_step", "units_per_hour", "decode_s", "export_s")
    missing = [k for k in needed if not isinstance(rate, dict) or not _measured(
        rate.get(k), positive=k in ("clip_s", "units_per_hour", "s_per_step"))]
    if missing:
        raise ValueError(f"rates.json has no measured {', '.join(missing)} for {kind}; forecasts "
                         "are never defaulted (references/compute-budget.md)")
    steps = pinned_steps(kind)
    if "steps" in rate and rate["steps"] != steps:
        raise ValueError(f"rates.json {kind} steps {rate['steps']!r} differ from the pinned {steps}; "
                         "measure the pinned settings")
    if "takes" in rate and rate["takes"] != 1:
        raise ValueError(f"rates.json {kind} takes must be 1 (one start per item; Wan allows one "
                         "start per shot)")
    if isinstance(items, bool) or not isinstance(items, int) or items <= 0:
        raise ValueError(f"a {kind} job needs at least one item")
    compute = {"kind": kind, "steps": steps, "items": items, "takes": 1}
    if kind != "reel_clips":
        compute.update(decode_s=rate["decode_s"], export_s=rate["export_s"])
    declared = spec.get("compute")
    if declared is not None:
        if not isinstance(declared, dict):
            raise ValueError("spec compute must be an object; it is derived from the job, so omit it")
        bad = sorted(k for k, v in declared.items()
                     if k not in compute or isinstance(v, bool) or v != compute[k])
        if bad:
            raise ValueError(f"spec compute disagrees with the job on {', '.join(bad)}: the forecast is "
                             f"derived from the job ({items} items, {steps} pinned steps, 1 take) and "
                             "the measured rates.json; remove the compute block")
    return compute


def narration_units(spec: dict) -> list:
    """The job's voice unit rows; with spec["cast"] (eav.cast.job_cast) every unit carries the
    narrator's voice and a cast unit its segments (each synthesized on its own, then joined)."""
    units, bounds = [], []
    for scene in spec["scenes"]:
        units += voice_units(scene, spec["preset"], spec.get("clause"), spec.get("language", "en"))
        kinds = unit_boundaries(scene, spec.get("language", "en"))
        bounds += [(k, i == len(kinds) - 1) for i, k in enumerate(kinds)]  # (boundary, scene end)
    if spec.get("cast"):  # with the expressive layer also each unit's pause rule and room tone
        units = cast_mod.apply(units, spec["cast"], spec.get("clause"), bounds)
    return units


def job_items(kind: str, spec: dict) -> int:
    """How many items the job really generates (Parler generations: one per voice unit, or one per
    segment of a multi-voice unit; stills, cues or shots)."""
    if kind == "narration":
        if spec.get("units") is not None:  # prepared rows (the audition)
            return cast_mod.pieces(spec["units"])
        return cast_mod.pieces(narration_units(spec))
    return len(spec.get("shots" if kind == "reel_clips" else "items") or [])


def narration_chunks(units: list, compute: dict, rates: dict) -> list:
    """(units, items) of each chunk of a narration job. Chunks always end on a unit boundary: with
    one item per unit this is chunk_sizes exactly; a multi-voice job (several generations in some
    units) packs whole units, in order, up to the most items one chunk can hold."""
    counts = [len(u.get("segments") or [None]) for u in units]
    if all(c == 1 for c in counts):
        return [(k, k) for k in chunk_sizes(compute, rates)]
    if forecast_seconds(compute, rates) <= MAX_CHUNK_SECONDS:
        return [(len(units), sum(counts))]

    def fits(k):
        return forecast_seconds({**compute, "items": k}, rates) <= MAX_CHUNK_SECONDS

    per = 0
    while per < compute["items"] and fits(per + 1):
        per += 1
    out, n, items = [], 0, 0
    for c in counts:
        if c > per:
            raise ValueError(f"one narration unit of {c} segments alone is forecast over "
                             f"{MAX_CHUNK_SECONDS} s; it cannot be cut into session-length chunks")
        if items + c > per:
            out.append((n, items))
            n, items = 0, 0
        n, items = n + 1, items + c
    out.append((n, items))
    return out


def chunk_sizes(compute: dict, rates: dict) -> list:
    """Item counts of the consecutive chunks a job is cut into: [items] when its forecast is at most
    MAX_CHUNK_SECONDS (or the kind is not chunked), else the fewest chunks, as even as possible, each
    forecast (same formula, its own decode_s/export_s overhead) at most MAX_CHUNK_SECONDS."""
    items = compute["items"]
    if compute["kind"] not in CHUNKED_KINDS or forecast_seconds(compute, rates) <= MAX_CHUNK_SECONDS:
        return [items]

    def fits(k):
        return forecast_seconds({**compute, "items": k}, rates) <= MAX_CHUNK_SECONDS

    per = 0
    while per < items and fits(per + 1):
        per += 1
    if per == 0:
        raise ValueError(f"one {compute['kind']} item alone is forecast over {MAX_CHUNK_SECONDS} s; "
                         "it cannot be cut into session-length chunks")
    n = -(-items // per)
    base, extra = divmod(items, n)
    return [base + 1] * extra + [base] * (n - extra)


def chunk_forecasts(compute: dict, rates: dict) -> list:
    """(items, forecast units) of each chunk; the caps are checked once against their sum."""
    return [(k, forecast({**compute, "items": k}, rates)) for k in chunk_sizes(compute, rates)]


def _plan(kind: str, record, spec: dict, rates: dict) -> dict:
    """Validate the spec; return everything needed to write, without touching disk."""
    compute = derive_compute(kind, spec, rates, job_items(kind, spec))
    if kind == "narration":
        _check_model(kind, spec, NARRATION_REPO)
        # prepared rows (the audition), else the scenes' voice units (with the cast, if any)
        units = [dict(u) for u in spec["units"]] if spec.get("units") is not None \
            else narration_units(spec)
        if not units:
            raise ValueError("no voice units")
        payload = {"units": units, "generation": _generation(spec["preset"]), "batch": _batch(spec)}
        if spec.get("cast"):  # multi-voice: who voices the story (single-voice jobs are unchanged)
            payload["cast"] = cast_mod.summary(spec["cast"])
        if spec.get("audition"):
            payload["audition"] = spec["audition"]
        return {"payload": payload,
                "repo": NARRATION_REPO,
                "revision": NARRATION_REVISION, "steps": 1, "compute": compute}
    if kind == "stills":
        _check_model(kind, spec, STILLS_REPO)
        items = [{"key": s["key"], "prompt": s["prompt"], "seed": int(s["seed"]),
                  "width": int(s.get("width", 1024)), "height": int(s.get("height", 1024))}
                 for s in spec["items"]]
        if not items:
            raise ValueError("no stills requested")
        return {"payload": {"items": items}, "repo": STILLS_REPO,
                "revision": "resolved-at-run-time", "steps": STILLS_STEPS, "compute": compute}
    if kind == "music":
        _check_model(kind, spec, MUSIC_REPO)
        items = [{"key": t["key"], "prompt": t["prompt"], "seed": int(t["seed"]),
                  "duration_s": float(t["duration_s"]),
                  "lyrics": t.get("lyrics", "[instrumental]")} for t in spec["items"]]
        if not items:
            raise ValueError("no tracks requested")
        return {"payload": {"items": items}, "repo": MUSIC_REPO,
                "revision": "resolved-at-run-time", "steps": MUSIC_STEPS, "compute": compute}
    raise ValueError(f"unknown job kind: {kind!r}")


def art_images(spec: dict) -> dict:
    """image basename -> its file. art_dir is one folder, a list of folders (the chunk folders
    of a chunked stills job: each shot's image is taken from the one folder that holds it), or a
    map image name -> file (the stills the per-key rule uses when a newer stills job replaced some
    keys, so one name can be in two folders)."""
    dirs = spec.get("art_dir")
    if isinstance(dirs, dict):
        out = {}
        for shot in spec.get("shots") or []:
            name = shot.get("image")
            if not isinstance(name, str) or not name or Path(name).name != name:
                raise ValueError(f"shot {shot.get('id')!r}: image must be a file name in art_dir")
            f = dirs.get(name)
            if not isinstance(f, (str, Path)) or Path(f).name != name or not Path(f).is_file():
                raise ValueError(f"shot {shot.get('id')!r}: art_dir maps no existing file named {name}")
            out[name] = Path(f)
        return out
    dirs = [dirs] if isinstance(dirs, (str, Path)) else dirs
    if not isinstance(dirs, list) or not dirs or not all(isinstance(d, (str, Path)) for d in dirs):
        raise ValueError("reel_clips spec art_dir must be a folder or a list of folders")
    out = {}
    for shot in spec.get("shots") or []:
        name = shot.get("image")
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError(f"shot {shot.get('id')!r}: image must be a file name inside art_dir")
        hits = [Path(d) / name for d in dirs if (Path(d) / name).is_file()]
        if len(hits) != 1:
            raise ValueError(f"shot {shot.get('id')!r}: {name} is in {len(hits)} of the art_dir "
                             "folders; it must be in exactly one")
        out[name] = hits[0]
    return out


def _reel_job(spec: dict, job_id: str, seconds: float, rate: dict) -> dict:
    """One Wan batch: its wall is bound to the forecast and it must be one the owner can
    authorize under batch.py (wall <= 2700 s; 2 x rate x wall / 3600 <= approved CU <= 5)."""
    batch = _load_wan_batch()
    shape = batch.w.PROFILES[REEL_PROFILE]
    if "wall_seconds" in spec:
        raise ValueError("wall_seconds is derived from the forecast; remove it from the clips spec")
    n, clip_s, uph = len(spec["shots"]), rate["clip_s"], rate["units_per_hour"]
    fit = max(1, min(MAX_CLIPS_PER_BATCH, int(batch.MAX_WALL_SECONDS // clip_s)))
    if n > fit or n * clip_s > batch.MAX_WALL_SECONDS:
        raise ValueError(f"{n} clips need about {n * clip_s:.0f} s at the measured {clip_s:g} s per "
                         f"clip, but one Wan job's wall is {batch.MAX_WALL_SECONDS} s: put at most "
                         f"{fit} shots in each reel_clips batch")
    wall = int(min(batch.MAX_WALL_SECONDS, math.ceil(seconds)))
    need = 2 * uph * wall / 3600
    if need > MAX_APPROVED_UNITS or seconds / 3600 * uph > MAX_APPROVED_UNITS:
        raise ValueError(f"the owner's Wan authority would have to approve {need:.2f} CU "
                         f"(2 x {uph:g} CU/h x {wall} s), over the Wan worker's "
                         f"{MAX_APPROVED_UNITS:g} CU per-batch limit; use fewer shots per batch")
    images = art_images(spec)
    evidence = spec.get("prior_attempt_evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("reel_clips spec needs prior_attempt_evidence (a non-empty dict)")
    scenes = []
    for shot in spec["shots"]:
        digest = hashlib.sha256(images[shot["image"]].read_bytes()).hexdigest()
        scenes.append({
            "id": shot["id"], "image": shot["image"], "image_sha256": digest,
            "profile": REEL_PROFILE,
            **{k: shape[k] for k in ("width", "height", "frames", "fps")},
            "inference_steps": shape["steps"], "guidance_scale": shape["guidance"],
            "seed": int(shot["seed"]), "prompt": shot["prompt"]})
    job = {"schema": batch.SCHEMA, "run_id": job_id, "model": batch.w.MODEL,
           "model_revision": batch.w.REVISION, "private": True,
           "publication_approved": False,
           "wall_seconds": wall,
           "max_attempts": len(scenes),
           "max_output_seconds": sum(s["frames"] / s["fps"] for s in scenes),
           "prior_attempt_evidence": evidence, "scenes": scenes}
    batch.validate(job)  # raises ValueError for anything the contract rejects
    return job


def _items(kind: str, rows: list) -> int:
    """Forecast items of a slice of a job's rows (narration: its Parler generations)."""
    return cast_mod.pieces(rows) if kind == "narration" else len(rows)


def _chunk_plan(kind: str, plan: dict, spec: dict, rates: dict, chunk: dict) -> dict:
    """The validated full job's plan cut to items [start, stop); compute derived for that slice."""
    key = "units" if kind == "narration" else "items"
    rows = plan["payload"][key][chunk["start"]:chunk["stop"]]
    if not rows or chunk["stop"] - chunk["start"] != len(rows):
        raise ValueError(f"chunk {chunk['index']} of {chunk['of']} is outside the job's items")
    bare = {k: v for k, v in spec.items() if k != "compute"}  # the full job's block was checked
    return {**plan, "payload": {**plan["payload"], key: rows},
            "compute": derive_compute(kind, bare, rates, _items(kind, rows)),
            "chunk": {"index": chunk["index"], "of": chunk["of"], "group": chunk["group"]}}


def new_job_id(kind: str) -> str:
    return f"{kind.replace('_', '-')}-{uuid.uuid4().hex[:8]}"


def chunk_job_id(group: str, index: int, of: int) -> str:
    """Chunk ids keep the job id scheme with a suffix: <kind>-<hex8>-c<index>of<of> (1-based)."""
    return f"{group}-c{index}of{of}"


def replacement_job_id(group: str, index: int, of: int, k: int) -> str:
    """The k-th rebuild (1, 2, ...) of one chunk: <group>-c<index>of<of>-r<k>."""
    return f"{chunk_job_id(group, index, of)}-r{k}"


def _replacement_plan(kind: str, old: dict, build: dict, rates: dict) -> dict:
    """A closed/superseded chunk's exact work again: the same payload (items in the same order,
    generation, batch), model and revision, read from its own job.json and build manifest; only the
    forecast is derived afresh from the measured rates."""
    if kind not in CHUNKED_KINDS or old.get("kind") != kind or not isinstance(old.get("chunk"), dict):
        raise ValueError(f"only a {'/'.join(CHUNKED_KINDS)} chunk can be replaced")
    repo = NARRATION_REPO if kind == "narration" else STILLS_REPO
    model = build.get("model") or {}
    if old.get("model") != repo or model.get("repo") != repo or not model.get("revision"):
        raise ValueError(f"the chunk was built with {old.get('model')!r}, not {repo!r}")
    key = "units" if kind == "narration" else "items"
    payload = {k: v for k, v in old.items()
               if k not in ("schema", "kind", "job_id", "title", "model", "chunk")}
    if not payload.get(key):
        raise ValueError("the chunk's job.json holds no items")
    return {"payload": payload, "repo": repo, "revision": model["revision"],
            "steps": pinned_steps(kind),
            "compute": derive_compute(kind, {}, rates, _items(kind, payload[key])),
            "chunk": {k: old["chunk"][k] for k in ("index", "of", "group")}}


def redo_job_id(source_job_id: str, k: int) -> str:
    """The k-th per-unit narration redo (1, 2, ...) of one job or chunk: <source job id>-u<k>."""
    return f"{source_job_id}-u{k}"


def _redo_plan(old: dict, build: dict, unit_keys: list, rates: dict) -> dict:
    """Only the named units of a narration job (or chunk) again, in the source job's order, with
    its exact unit rows (text, voice description, pause), generation settings, batch, model and
    revision, read from its own job.json and build manifest; the forecast is derived afresh for
    those units from the measured rates. The job carries redo = {source_job_id, unit_keys} and no
    chunk block: it is a plain job."""
    if old.get("kind") != "narration":
        raise ValueError("only narration units are redone")
    model = build.get("model") or {}
    if old.get("model") != NARRATION_REPO or model.get("repo") != NARRATION_REPO \
            or not model.get("revision"):
        raise ValueError(f"the source job was built with {old.get('model')!r}, not {NARRATION_REPO!r}")
    if build.get("generation", old.get("generation")) != old.get("generation"):
        raise ValueError("the source job's build manifest and job.json disagree on generation")
    wanted = list(dict.fromkeys(unit_keys))
    if not wanted or len(wanted) != len(unit_keys):
        raise ValueError("name each unit to redo once")
    rows = [u for u in old.get("units") or [] if u.get("unit_key") in wanted]
    missing = [k for k in wanted if k not in {u["unit_key"] for u in rows}]
    if missing:
        raise ValueError(f"unit(s) {', '.join(missing)} are not in job {old.get('job_id')}")
    payload = {k: v for k, v in old.items()
               if k not in ("schema", "kind", "job_id", "title", "model", "chunk", "redo", "units")}
    payload["units"] = [dict(u) for u in rows]
    return {"payload": payload, "repo": NARRATION_REPO, "revision": model["revision"],
            "steps": pinned_steps("narration"),
            "compute": derive_compute("narration", {}, rates, cast_mod.pieces(rows)),
            "redo": {"source_job_id": old["job_id"], "unit_keys": [u["unit_key"] for u in rows]}}


def build_job(kind: str, record, spec: dict, ledger, rates: dict, out: Path,
              month: str = None, chunk: dict = None, replace: dict = None,
              redo: dict = None) -> dict:
    """Build an inert bundle under out/<job_id>/.

    The forecast is reserved on the ledger before anything is written. If the
    write fails, the partial directory is removed and the reservation settled
    at 0 units; the settled entry stays in the ledger, so a retry needs a new
    job_id. spec['compute'] (measured steps, items, decode_s, export_s) is required.

    chunk = {"index", "of", "group", "start", "stop"} builds items [start, stop) of the
    validated full job as its own job chunk_job_id(group, index, of) (narration, stills only);
    its job.json and build manifest carry chunk = {"index", "of", "group"}.
    replace = {"job_json", "build", "k"} rebuilds a closed/superseded chunk's exact slice as
    replacement_job_id(group, index, of, k), with the same chunk block.
    redo = {"job_json", "build", "unit_keys", "k"} builds only those units of a narration job (or
    chunk) as redo_job_id(source, k) (_redo_plan); its job.json and manifest carry redo.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")
    if (chunk is not None or replace is not None) and kind not in CHUNKED_KINDS:
        raise ValueError(f"{kind} jobs are never chunked")
    title = record.data["title_slug"]
    if redo is not None and (kind != "narration" or chunk is not None or replace is not None):
        raise ValueError("a redo is a plain narration job")
    if redo is not None:
        job_id = redo_job_id(redo["job_json"]["job_id"], redo["k"])
    elif replace is not None:
        chunk = replace["job_json"]["chunk"]
        job_id = replacement_job_id(chunk["group"], chunk["index"], chunk["of"], replace["k"])
    elif chunk is not None:
        job_id = chunk_job_id(chunk["group"], chunk["index"], chunk["of"])
    else:
        job_id = spec.get("job_id") or new_job_id(kind)
    if not _SAFE.fullmatch(job_id) or not _SAFE.fullmatch(title):
        raise ValueError("job_id and title slug must be lowercase letters, digits and hyphens")
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    out = Path(out)
    job_dir = out / job_id
    try:
        out.resolve().relative_to(record.root.resolve())
    except ValueError:
        raise ValueError("out must be inside the record root") from None
    if job_dir.exists():
        raise FileExistsError(f"bundle already exists: {job_dir}")

    # Validate and forecast everything before any ledger or disk change.
    if kind == "reel_clips":
        _check_model(kind, spec, _load_wan_batch().w.MODEL)
        plan = {"compute": derive_compute(kind, spec, rates, job_items(kind, spec))}
        job = _reel_job(spec, job_id, forecast_seconds(plan["compute"], rates), rates[kind])
    elif replace is not None:
        plan = _replacement_plan(kind, replace["job_json"], replace["build"], rates)
    elif redo is not None:
        plan = _redo_plan(redo["job_json"], redo["build"], redo["unit_keys"], rates)
    else:
        plan = _plan(kind, record, spec, rates)
        if chunk is not None:
            plan = _chunk_plan(kind, plan, spec, rates, chunk)
    units = forecast(plan["compute"], rates)

    edition_id = (record.data.get("source") or {}).get("edition_id")
    root = Path(os.path.relpath(record.root.resolve(), ledger.path.parent.resolve())).as_posix()
    # BudgetExceeded: nothing written; the title cap is keyed by edition_id (R26)
    ledger.reserve(title, month, units, job_id, edition_id=edition_id,
                   root=root if edition_id else None)
    extra = {k: plan[k] for k in ("chunk", "redo") if k in plan}
    artifacts = list(record.data["artifacts"])
    try:  # the bundle and its record artifact are written together, or neither stays
        if kind == "reel_clips":
            result = _write_reel(job, spec, job_dir)
        else:
            result = _write_notebook_bundle(kind, plan, job_id, title, job_dir,
                                            forecast_seconds(plan["compute"], rates))
        result.update(job_id=job_id, forecast_units=units)
        record.add_artifact("colab_job", Path(result["notebook"]), {
            **extra, "job_id": job_id, "job_kind": kind, "forecast_units": units, "month": month,
            "inputs_zip": Path(result["inputs_zip"]).resolve().relative_to(
                record.root.resolve()).as_posix(),
            "manifest": Path(result["manifest"]).resolve().relative_to(
                record.root.resolve()).as_posix()})
    except BaseException:
        shutil.rmtree(job_dir, ignore_errors=True)
        if len(record.data["artifacts"]) != len(artifacts):
            record.data["artifacts"] = artifacts  # the save failed: drop the in-memory artifact
            try:
                record._save()
            except Exception:
                pass
        try:
            ledger.settle(job_id, 0)  # release the reservation; nothing ran
        except Exception:
            pass  # never mask the original error
        raise
    record.event("job", "built", {"job_id": job_id, "kind": kind, "forecast_units": units, **extra})
    return {"job_id": job_id, "notebook": result["notebook"],
            "inputs_zip": result["inputs_zip"], "manifest": result["manifest"],
            "forecast_units": units}


def _write_notebook_bundle(kind, plan, job_id, title, job_dir: Path, deadline_s: float) -> dict:
    job_json = {"schema": JOB_SCHEMA, "kind": kind, "job_id": job_id, "title": title,
                "model": plan["repo"], **plan["payload"]}
    for k in ("chunk", "redo"):
        if k in plan:
            job_json[k] = plan[k]
    archive = _zip_bytes({"job.json": (json.dumps(job_json, indent=2, sort_keys=True)
                                       + "\n").encode("utf-8")})
    zip_sha = hashlib.sha256(archive).hexdigest()
    nb = _notebook(kind, job_id, title, zip_sha, plan["repo"], plan["revision"],
                   plan["steps"], _TEMPLATES / f"{kind}_cell.py.txt", deadline_s)
    manifest = {"schema": "earnalism.audiovisual-build.v1", "job_id": job_id, "kind": kind,
                "title": title, "inputs_sha256": zip_sha,
                "notebook_sha256": hashlib.sha256(nb).hexdigest(),
                "model": {"repo": plan["repo"], "revision": plan["revision"]},
                "drive_dir": f"{DRIVE_ROOT}/{title}/{job_id}",
                "deadline_seconds": int(deadline_s), "authority_created": False}
    if "generation" in plan["payload"]:
        manifest["generation"] = plan["payload"]["generation"]
    for k in ("chunk", "redo"):
        if k in plan:
            manifest[k] = plan[k]
    job_dir.mkdir(parents=True)
    paths = {"notebook": job_dir / f"{kind}.ipynb", "inputs_zip": job_dir / "inputs.zip",
             "manifest": job_dir / "build-manifest.json"}
    paths["notebook"].write_bytes(nb)
    paths["inputs_zip"].write_bytes(archive)
    paths["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
    return paths


def _write_reel(job: dict, spec: dict, job_dir: Path) -> dict:
    builder = _load_wan_builder()
    with tempfile.TemporaryDirectory() as tmp:
        job_path = Path(tmp) / "job.json"
        job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
        art = Path(tmp) / "art"  # the batch's images, from one or several art_dir folders
        art.mkdir()
        for name, path in art_images(spec).items():
            shutil.copyfile(path, art / name)
        notebook = builder.build(job_dir, job_path, art)
    return {"notebook": Path(notebook), "inputs_zip": job_dir / "wan22-batch-inputs.zip",
            "manifest": job_dir / "build-manifest.json"}
