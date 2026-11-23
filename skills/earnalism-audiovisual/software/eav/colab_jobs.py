"""Inert, hash-bound Colab job bundles (narration, stills, music, reel clips).

Building a bundle spends nothing: it reserves the forecast on the ledger,
writes a notebook (nbformat 4, plain JSON) and an input zip, and records both.
The owner runs the notebook by hand; every notebook starts with RUN = False.
"""
import hashlib
import importlib.util
import io
import json
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .budget import BudgetExceeded, forecast
from .voice import voice_units

NARRATION_REPO = "ai4bharat/indic-parler-tts"
NARRATION_REVISION = "7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca"
STILLS_REPO = "black-forest-labs/FLUX.1-schnell"
STILLS_STEPS = 4
# Resolved to an exact commit (plus weight hashes) by the notebook at run time.
MUSIC_REPO = "ACE-Step/ACE-Step-v1-3.5B"
REEL_PROFILE = "l4-balanced-v2"
DRIVE_ROOT = "/content/drive/MyDrive/earnalism-audiovisual"

KINDS = ("narration", "stills", "music", "reel_clips")
JOB_SCHEMA = "earnalism.audiovisual-job.v1"
_TEMPLATES = Path(__file__).with_name("templates")
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
'''

_MANIFEST = _GUARD + '''import hashlib, json
outputs = {}
for p in sorted(OUT_DIR.iterdir()):
    if p.is_file() and p.name not in ("manifest.json", "inputs.zip"):
        outputs[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
if not outputs:
    raise RuntimeError("no outputs were produced")
manifest = {"schema": "earnalism.audiovisual-outputs.v1", "job_id": JOB_ID, "title": TITLE,
            "kind": KIND, "input_zip_sha256": INPUT_ZIP_SHA256, "model": MODEL_INFO,
            "outputs": outputs}
(OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\\n")
print("manifest.json written:", len(outputs), "files")
'''


def _notebook(kind, job_id, title, zip_sha, repo, revision, steps, template) -> bytes:
    config = (_GUARD +
              f"import pathlib\nJOB_ID = {job_id!r}\nTITLE = {title!r}\nKIND = {kind!r}\n"
              f"INPUT_ZIP_SHA256 = {zip_sha!r}\nMODEL_REPO = {repo!r}\n"
              f"MODEL_REVISION = {revision!r}\nSTEPS = {steps!r}\n"
              f"DRIVE_JOB_DIR = {DRIVE_ROOT + '/' + title + '/' + job_id!r}\n")
    intro = (f"# Earnalism {kind} job `{job_id}`\n\n**Prepared, not run.** Input zip SHA256 "
             f"`{zip_sha}`. Copy `inputs.zip` to `{DRIVE_ROOT}/{title}/{job_id}/` in Drive, set "
             f"`RUN = True` in the first cell, then run all. Outputs and `manifest.json` "
             f"(sha256 of every output) land in the same folder.\n")
    # The generation cell may call setup that sets OUT_DIR; the verify cell sets JOB/OUT_DIR.
    parts = [("markdown", intro), ("code", "RUN = False"), ("code", config),
             ("code", _VERIFY), ("code", template.read_text(encoding="utf-8")),
             ("code", _MANIFEST)]
    nb = {"nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"},
                       "language_info": {"name": "python"},
                       "colab": {"name": f"earnalism_{kind}_{job_id}.ipynb",
                                 "gpuType": "L4"}},
          "cells": [_cell(k, t, i) for i, (k, t) in enumerate(parts)]}
    return (json.dumps(nb, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def _compute(kind: str, spec: dict, items: int, steps: int, takes: int = 1) -> dict:
    c = dict(spec.get("compute") or {})
    return {"kind": kind, "steps": c.get("steps", steps), "items": c.get("items", items),
            "takes": c.get("takes", takes), "decode_s": c.get("decode_s", 0),
            "export_s": c.get("export_s", 0)}


def _plan(kind: str, record, spec: dict) -> dict:
    """Validate the spec; return everything needed to write, without touching disk."""
    if kind == "narration":
        _check_model(kind, spec, NARRATION_REPO)
        units = []
        for scene in spec["scenes"]:
            units += voice_units(scene, spec["preset"], spec.get("clause"),
                                 spec.get("language", "en"))
        if not units:
            raise ValueError("no voice units")
        return {"payload": {"units": units}, "repo": NARRATION_REPO,
                "revision": NARRATION_REVISION, "steps": 1,
                "compute": _compute(kind, spec, len(units), 1)}
    if kind == "stills":
        _check_model(kind, spec, STILLS_REPO)
        items = [{"key": s["key"], "prompt": s["prompt"], "seed": int(s["seed"]),
                  "width": int(s.get("width", 1024)), "height": int(s.get("height", 1024))}
                 for s in spec["items"]]
        if not items:
            raise ValueError("no stills requested")
        return {"payload": {"items": items}, "repo": STILLS_REPO,
                "revision": "resolved-at-run-time", "steps": STILLS_STEPS,
                "compute": _compute(kind, spec, len(items), STILLS_STEPS)}
    if kind == "music":
        _check_model(kind, spec, MUSIC_REPO)
        items = [{"key": t["key"], "prompt": t["prompt"], "seed": int(t["seed"]),
                  "duration_s": float(t["duration_s"]),
                  "lyrics": t.get("lyrics", "[instrumental]")} for t in spec["items"]]
        if not items:
            raise ValueError("no tracks requested")
        return {"payload": {"items": items}, "repo": MUSIC_REPO,
                "revision": "resolved-at-run-time", "steps": 60,
                "compute": _compute(kind, spec, len(items), 60)}
    raise ValueError(f"unknown job kind: {kind!r}")


def _reel_job(spec: dict, job_id: str) -> dict:
    batch = _load_wan_batch()
    shape = batch.w.PROFILES[REEL_PROFILE]
    art = Path(spec["art_dir"])
    evidence = spec.get("prior_attempt_evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("reel_clips spec needs prior_attempt_evidence (a non-empty dict)")
    scenes = []
    for shot in spec["shots"]:
        digest = hashlib.sha256((art / shot["image"]).read_bytes()).hexdigest()
        scenes.append({
            "id": shot["id"], "image": shot["image"], "image_sha256": digest,
            "profile": REEL_PROFILE,
            **{k: shape[k] for k in ("width", "height", "frames", "fps")},
            "inference_steps": shape["steps"], "guidance_scale": shape["guidance"],
            "seed": int(shot["seed"]), "prompt": shot["prompt"]})
    job = {"schema": batch.SCHEMA, "run_id": job_id, "model": batch.w.MODEL,
           "model_revision": batch.w.REVISION, "private": True,
           "publication_approved": False,
           "wall_seconds": int(spec.get("wall_seconds", batch.MAX_WALL_SECONDS)),
           "max_attempts": len(scenes),
           "max_output_seconds": sum(s["frames"] / s["fps"] for s in scenes),
           "prior_attempt_evidence": evidence, "scenes": scenes}
    batch.validate(job)  # raises ValueError for anything the contract rejects
    return job


def build_job(kind: str, record, spec: dict, ledger, rates: dict, out: Path,
              month: str = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")
    title = record.data["title_slug"]
    job_id = spec.get("job_id") or f"{kind.replace('_', '-')}-{uuid.uuid4().hex[:8]}"
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
        job = _reel_job(spec, job_id)
        plan = {"compute": _compute(kind, spec, len(job["scenes"]), 24)}
    else:
        plan = _plan(kind, record, spec)
    units = forecast(plan["compute"], rates)

    ledger.reserve(title, month, units, job_id)  # BudgetExceeded: nothing written
    try:
        if kind == "reel_clips":
            result = _write_reel(job, spec, job_dir)
        else:
            result = _write_notebook_bundle(kind, plan, job_id, title, job_dir)
    except BaseException:
        ledger.settle(job_id, 0)  # release the reservation; nothing ran
        raise
    result.update(job_id=job_id, forecast_units=units)
    record.add_artifact("colab_job", Path(result["notebook"]), {
        "job_id": job_id, "job_kind": kind, "forecast_units": units, "month": month,
        "inputs_zip": str(result["inputs_zip"]), "manifest": str(result["manifest"])})
    record.event("job", "built", {"job_id": job_id, "kind": kind, "forecast_units": units})
    return {"job_id": job_id, "notebook": result["notebook"],
            "inputs_zip": result["inputs_zip"], "manifest": result["manifest"],
            "forecast_units": units}


def _write_notebook_bundle(kind, plan, job_id, title, job_dir: Path) -> dict:
    job_json = {"schema": JOB_SCHEMA, "kind": kind, "job_id": job_id, "title": title,
                "model": plan["repo"], **plan["payload"]}
    archive = _zip_bytes({"job.json": (json.dumps(job_json, indent=2, sort_keys=True)
                                       + "\n").encode("utf-8")})
    zip_sha = hashlib.sha256(archive).hexdigest()
    nb = _notebook(kind, job_id, title, zip_sha, plan["repo"], plan["revision"],
                   plan["steps"], _TEMPLATES / f"{kind}_cell.py.txt")
    manifest = {"schema": "earnalism.audiovisual-build.v1", "job_id": job_id, "kind": kind,
                "title": title, "inputs_sha256": zip_sha,
                "notebook_sha256": hashlib.sha256(nb).hexdigest(),
                "model": {"repo": plan["repo"], "revision": plan["revision"]},
                "drive_dir": f"{DRIVE_ROOT}/{title}/{job_id}",
                "authority_created": False}
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
        notebook = builder.build(job_dir, job_path, Path(spec["art_dir"]))
    return {"notebook": Path(notebook), "inputs_zip": job_dir / "wan22-batch-inputs.zip",
            "manifest": job_dir / "build-manifest.json"}
