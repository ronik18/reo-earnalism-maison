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

from .budget import BudgetExceeded, forecast, forecast_seconds
from .voice import audition_units, validate_directions, voice_units

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

# Owner 2026-11-24: one look for every book's stills, the 2D animated feature-film illustration
# of the বিচারক stills he chose. Appended to every stills prompt by the job builder (prompts carry
# content, period, palette and light only); a prompt asking for another look is refused.
HOUSE_STYLE = ("Earnalism house style: 2D animated feature-film illustration, clean confident line art, "
               "soft cel shading with gentle painterly gradients, expressive faces with large luminous "
               "eyes, consistent character designs, cinematic composition, clean image edges and plain "
               "uncluttered corners, hand-drawn cel animation look.")
# FLUX.1-schnell runs at guidance 0 with no negative prompt: "no bindi" paints a bindi. A stills
# prompt (house style included) says only what is in the picture.
NEGATIVE_WORDS = re.compile(r"\b(no|not|without|never|none|nor)\b|n't", re.IGNORECASE)
MAX_CANDIDATES = 4
CANDIDATE_SUFFIX = re.compile(r"--c\d+$")
STYLE_CONFLICTS = ("photoreal", "photograph", "oil-on-canvas", "realism", "watercolour", "watercolor",
                   "gouache", "3d render", "not a cartoon", "not anime", "not a flat illustration")
KINDS = ("narration", "stills", "music", "reel_clips")
JOB_SCHEMA = "earnalism.audiovisual-job.v1"
EXCHANGE_SCHEMA = "earnalism.colab-exchange.v1"
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
# R2 exchange (references/colab-exchange.md): exchange.json in this Drive folder carries two
# short-lived single-object URLs (GET inputs.zip, PUT outputs.tar). They are capabilities: never
# print them, never copy them elsewhere.
EXCHANGE = None
if (OUT_DIR / "exchange.json").is_file():
    import time, urllib.request
    from datetime import datetime
    EXCHANGE = json.loads((OUT_DIR / "exchange.json").read_text())
    if EXCHANGE.get("schema") != EXCHANGE_SCHEMA or EXCHANGE.get("job_id") != JOB_ID:
        raise RuntimeError("exchange.json belongs to a different job; ask Claude for this job's exchange.json")
    _left = datetime.fromisoformat(EXCHANGE["expires_at"].replace("Z", "+00:00")).timestamp() - time.time()
    if _left < DEADLINE_SECONDS + MANIFEST_RESERVE_S + 300:
        raise RuntimeError("the exchange URLs expire before this job's hard stop (%.0f s left); "
                           "ask Claude to re-sign them before running" % _left)
    if not INPUT_ZIP.is_file():
        with urllib.request.urlopen(EXCHANGE["inputs"]["url"], timeout=600) as _r:
            if not 200 <= _r.status < 300:
                raise RuntimeError("inputs.zip download failed: HTTP %d" % _r.status)
            _data = _r.read()
        _sha = hashlib.sha256(_data).hexdigest()
        if _sha != INPUT_ZIP_SHA256 or _sha != EXCHANGE["inputs"]["sha256"]:
            raise RuntimeError("downloaded inputs.zip sha256 mismatch: " + _sha + " (not kept)")
        INPUT_ZIP.write_bytes(_data)
        print("inputs.zip downloaded from the exchange:", len(_data), "bytes")
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

# R25: the hard stop counts from this cell (run right after the config) and equals the forecast
# seconds the ledger reserved. Items start only while they can still finish before it; a Timer
# unassigns the runtime at the stop itself, as the Wan notebook does.
# Model access, checked before the clock starts and before any install (Colab 2026-11-23: a gated
# model failed only after the install). Gated repos need their terms accepted on Hugging Face and a
# token in the Colab secret HF_TOKEN; the token is exported so every later download uses it.
_ACCESS = _GUARD + '''import os
_token, _secret_problem = None, None
try:
    from google.colab import userdata
    _token = userdata.get("HF_TOKEN") or None
except Exception as _e:  # no secret, notebook access not granted, or the prompt timed out
    _secret_problem = type(_e).__name__
    _token = os.environ.get("HF_TOKEN") or None
if _token:
    os.environ["HF_TOKEN"] = _token
from huggingface_hub import HfApi
try:
    HfApi().auth_check(MODEL_REPO, token=_token)
except Exception as _e:
    _fix = ("accept the model's terms at https://huggingface.co/" + MODEL_REPO + " with your Hugging "
            "Face account, put a Read token from https://huggingface.co/settings/tokens in the Colab "
            "secret HF_TOKEN (key icon in the left sidebar, Notebook access on), then Runtime > "
            "Restart session and Run all")
    if _secret_problem:
        _fix += " (the HF_TOKEN secret could not be read: %s; grant access if Colab asks)" % _secret_problem
    raise RuntimeError("No access to " + MODEL_REPO + " (" + type(_e).__name__ + "): " + _fix) from None
print("model access OK:", MODEL_REPO, "(token from HF_TOKEN)" if _token else "(public)")
'''

_CLOCK = _GUARD + '''import threading, time
if "JOB_STARTED" not in globals():
    JOB_STARTED = time.time()
    from google.colab import runtime
    STOP_GUARD = threading.Timer(DEADLINE_SECONDS, runtime.unassign)
    STOP_GUARD.daemon = True
    STOP_GUARD.start()
INCOMPLETE = False


def may_start(last_item_s):
    """Between items: start the next one only if it (and the manifest) fits before the hard stop."""
    global INCOMPLETE
    left = DEADLINE_SECONDS - (time.time() - JOB_STARTED)
    if left < last_item_s + MANIFEST_RESERVE_S:
        INCOMPLETE = True
        print("HARD STOP: %.0f s left of the %d s forecast; no further item starts" % (left, DEADLINE_SECONDS))
        return False
    return True


print("hard stop armed:", DEADLINE_SECONDS, "s from now")
'''

_MANIFEST = _GUARD + '''import hashlib, json, time
import importlib.metadata as _md
outputs = {}
for p in sorted(OUT_DIR.iterdir()):
    if (p.is_file() and p.name not in ("manifest.json", "inputs.zip", "exchange.json")
            and p.suffix != ".ipynb"):  # Colab keeps the job notebook in this folder
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
complete = not INCOMPLETE and all(name in outputs for name in EXPECTED)
manifest = {"schema": "earnalism.audiovisual-outputs.v1", "job_id": JOB_ID, "title": TITLE,
            "kind": KIND, "input_zip_sha256": INPUT_ZIP_SHA256, "model": MODEL_INFO,
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "deadline_seconds": DEADLINE_SECONDS,
            "elapsed_seconds": round(time.time() - JOB_STARTED, 1),
            "packages": packages, "outputs": outputs}
(OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\\n")
print("manifest.json written:", manifest["status"], len(outputs), "files")
if not complete:
    print("INCOMPLETE: import refuses this folder; close the job with the CU Colab shows")
if globals().get("EXCHANGE") is not None:  # R2 exchange: one uncompressed tar, PUT once
    import os, tarfile, tempfile, urllib.error, urllib.request
    _fd, _tar = tempfile.mkstemp(suffix=".tar")  # local disk, never the Drive job folder
    os.close(_fd)
    with tarfile.open(_tar, "w", format=tarfile.PAX_FORMAT) as _t:
        for _name in ["manifest.json"] + sorted(outputs):
            _t.add(str(OUT_DIR / _name), arcname=_name, recursive=False)
    _size = os.path.getsize(_tar)
    _headers = dict(EXCHANGE["outputs"]["headers"], **{"Content-Length": str(_size)})
    with open(_tar, "rb") as _body:
        _req = urllib.request.Request(EXCHANGE["outputs"]["url"], data=_body, method="PUT",
                                      headers=_headers)
        try:
            with urllib.request.urlopen(_req, timeout=1800) as _r:
                _status = _r.status
        except urllib.error.HTTPError as _e:
            _status = _e.code
    os.unlink(_tar)
    print("outputs.tar upload: HTTP", _status, "(%d bytes)" % _size)
    if not 200 <= _status < 300:
        raise RuntimeError("outputs.tar upload failed: HTTP %d; the outputs stay in Drive, tell Claude"
                           % _status)
    print("outputs uploaded to the exchange; tell Claude the CU Colab shows")
'''

# Distributions whose resolved versions each manifest records (R26).
PACKAGES = {"narration": ("parler_tts", "transformers", "torch", "soundfile", "protobuf"),
            "stills": ("diffusers", "transformers", "accelerate", "sentencepiece", "protobuf",
                       "bitsandbytes", "torch"),
            "music": ("ace-step", "acestep", "torch", "transformers", "diffusers", "huggingface_hub")}
MANIFEST_RESERVE_S = 60


def _notebook(kind, job_id, title, zip_sha, repo, revision, steps, template, deadline_s) -> bytes:
    config = (_GUARD +
              f"import pathlib\nJOB_ID = {job_id!r}\nTITLE = {title!r}\nKIND = {kind!r}\n"
              f"INPUT_ZIP_SHA256 = {zip_sha!r}\nMODEL_REPO = {repo!r}\n"
              f"MODEL_REVISION = {revision!r}\nSTEPS = {steps!r}\n"
              f"DRIVE_JOB_DIR = {DRIVE_ROOT + '/' + title + '/' + job_id!r}\n"
              f"# Hard wall-clock stop = the forecast seconds reserved on the ledger (R25)\n"
              f"DEADLINE_SECONDS = {int(deadline_s)}\nMANIFEST_RESERVE_S = {MANIFEST_RESERVE_S}\n"
              f"PACKAGES = {PACKAGES[kind]!r}\nEXCHANGE_SCHEMA = {EXCHANGE_SCHEMA!r}\n")
    intro = (f"# Earnalism {kind} job `{job_id}`\n\n**Prepared, not run.** Input zip SHA256 "
             f"`{zip_sha}`. Set `RUN = True` in the first cell, then run all. With the R2 exchange "
             f"(`exchange.json` in `{DRIVE_ROOT}/{title}/{job_id}/`) the notebook downloads "
             f"`inputs.zip` itself and uploads the outputs when it finishes; without it, copy "
             f"`inputs.zip` into that Drive folder first. Outputs and `manifest.json` "
             f"(sha256 of every output) land in the same folder.\n\n**Hard stop:** "
             f"{int(deadline_s)} s (the reserved forecast) from the clock cell. No item starts after "
             f"it and the runtime is unassigned at it; a stopped run's manifest says INCOMPLETE and "
             f"cannot be imported.\n")
    # The generation cell may call setup that sets OUT_DIR; the verify cell sets JOB/OUT_DIR.
    parts = [("markdown", intro), ("code", "RUN = False"), ("code", config), ("code", _ACCESS),
             ("code", _CLOCK),
             ("code", _VERIFY), ("code", template.read_text(encoding="utf-8")),
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
    """Every voice unit of a narration spec: film/reel scenes, or an audition's variants."""
    if "audition" in spec:
        a = spec["audition"]
        return audition_units(a["passages"], [(v["name"], v["preset"], v.get("style"))
                                              for v in a["variants"]],
                              a.get("language", "en"), a.get("directions"))
    lang, style, directions = spec.get("language", "en"), spec.get("style"), spec.get("directions")
    units = []
    for scene in spec["scenes"]:
        units += voice_units(scene, spec["preset"], spec.get("clause"), lang, style,
                             {} if directions is not None else None)
    if directions is not None:
        validate_directions(directions, units)
        units = []
        for scene in spec["scenes"]:
            units += voice_units(scene, spec["preset"], spec.get("clause"), lang, style, directions)
    return units


def negative_words(prompt: str) -> list:
    """The negative words a prompt uses (lowercase, in order); FLUX draws what they name."""
    return [m.group(0).lower() for m in NEGATIVE_WORDS.finditer(prompt)]


def _candidates(item: dict) -> int:
    n = item.get("candidates", 1)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_CANDIDATES:
        raise ValueError(f"stills item {item.get('key')!r} candidates must be an integer from 1 to "
                         f"{MAX_CANDIDATES}, not {n!r}")
    return n


def job_items(kind: str, spec: dict) -> int:
    """How many items the job really generates (voice units, stills images, cues or shots);
    a stills item with candidates counts once per candidate image."""
    if kind == "narration":
        return len(narration_units(spec))
    if kind == "stills":
        return sum(_candidates(s) for s in spec.get("items") or [])
    return len(spec.get("shots" if kind == "reel_clips" else "items") or [])


def _plan(kind: str, record, spec: dict, rates: dict) -> dict:
    """Validate the spec; return everything needed to write, without touching disk."""
    compute = derive_compute(kind, spec, rates, job_items(kind, spec))
    if kind == "narration":
        _check_model(kind, spec, NARRATION_REPO)
        units = narration_units(spec)
        if not units:
            raise ValueError("no voice units")
        payload = {"units": units}
        if "audition" in spec:
            variants = spec["audition"]["variants"]
            gens = [_generation(v["preset"]) for v in variants]
            if any(g != gens[0] for g in gens):
                raise ValueError("audition variants must share the control's pinned generation "
                                 "settings, so only the description differs")
            payload.update(generation=gens[0], audition={
                "variants": {v["name"]: v["preset_key"] for v in variants},
                "passages": sorted(spec["audition"]["passages"]),
                "film_narration": False})
        else:
            payload["generation"] = _generation(spec["preset"])
            if spec.get("style"):
                payload["voice_style"] = spec["style"]
            if spec.get("directions"):
                payload["directions"] = spec["directions"]
        return {"payload": payload,
                "repo": NARRATION_REPO,
                "revision": NARRATION_REVISION, "steps": 1, "compute": compute}
    if kind == "stills":
        _check_model(kind, spec, STILLS_REPO)
        items = []
        for s in spec["items"]:
            clash = [w for w in STYLE_CONFLICTS if w in s["prompt"].lower()]
            if clash:
                raise ValueError(f"stills prompt {s['key']!r} asks for {clash[0]!r}, which conflicts with "
                                 f"the house style (references/visual-style.md); describe the content only")
            if CANDIDATE_SUFFIX.search(str(s["key"])):
                raise ValueError(f"stills key {s['key']!r} ends like a candidate file (--cN); "
                                 "use candidates instead")
            prompt = s["prompt"].rstrip() + " " + HOUSE_STYLE
            negative = negative_words(prompt)
            if negative:
                raise ValueError(f"stills prompt {s['key']!r} uses the negative word {negative[0]!r}: "
                                 "FLUX.1-schnell has no negative prompt and draws what it names; "
                                 "describe what is there instead (e.g. 'bare forehead', 'clean-shaven')"
                                 " (references/visual-style.md, Prompt wording)")
            n, seed = _candidates(s), int(s["seed"])
            size = {"width": int(s.get("width", 1024)), "height": int(s.get("height", 1024))}
            if n == 1:
                items.append({"key": s["key"], "prompt": prompt, "seed": seed, **size})
                continue
            # one entry per candidate image, so EXPECTED, the deadline and the manifest see each file
            items += [{"key": f"{s['key']}--c{c}", "base": s["key"], "candidate": c,
                       "prompt": prompt, "seed": seed + c - 1, **size} for c in range(1, n + 1)]
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
           "wall_seconds": wall,
           "max_attempts": len(scenes),
           "max_output_seconds": sum(s["frames"] / s["fps"] for s in scenes),
           "prior_attempt_evidence": evidence, "scenes": scenes}
    batch.validate(job)  # raises ValueError for anything the contract rejects
    return job


def build_job(kind: str, record, spec: dict, ledger, rates: dict, out: Path,
              month: str = None) -> dict:
    """Build an inert bundle under out/<job_id>/.

    The forecast is reserved on the ledger before anything is written. If the
    write fails, the partial directory is removed and the reservation settled
    at 0 units; the settled entry stays in the ledger, so a retry needs a new
    job_id. spec['compute'] (measured steps, items, decode_s, export_s) is required.
    """
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
        plan = {"compute": derive_compute(kind, spec, rates, job_items(kind, spec))}
        job = _reel_job(spec, job_id, forecast_seconds(plan["compute"], rates), rates[kind])
    else:
        plan = _plan(kind, record, spec, rates)
    units = forecast(plan["compute"], rates)

    edition_id = (record.data.get("source") or {}).get("edition_id")
    root = Path(os.path.relpath(record.root.resolve(), ledger.path.parent.resolve())).as_posix()
    # BudgetExceeded: nothing written; the title cap is keyed by edition_id (R26)
    ledger.reserve(title, month, units, job_id, edition_id=edition_id,
                   root=root if edition_id else None)
    try:
        if kind == "reel_clips":
            result = _write_reel(job, spec, job_dir)
        else:
            result = _write_notebook_bundle(kind, plan, job_id, title, job_dir,
                                            forecast_seconds(plan["compute"], rates))
    except BaseException:
        shutil.rmtree(job_dir, ignore_errors=True)
        try:
            ledger.settle(job_id, 0)  # release the reservation; nothing ran
        except Exception:
            pass  # never mask the original error
        raise
    result.update(job_id=job_id, forecast_units=units)
    record.add_artifact("colab_job", Path(result["notebook"]), {
        "job_id": job_id, "job_kind": kind, "forecast_units": units, "month": month,
        "inputs_zip": Path(result["inputs_zip"]).resolve().relative_to(
            record.root.resolve()).as_posix(),
        "manifest": Path(result["manifest"]).resolve().relative_to(
            record.root.resolve()).as_posix()})
    record.event("job", "built", {"job_id": job_id, "kind": kind, "forecast_units": units})
    return {"job_id": job_id, "notebook": result["notebook"],
            "inputs_zip": result["inputs_zip"], "manifest": result["manifest"],
            "forecast_units": units}


def _write_notebook_bundle(kind, plan, job_id, title, job_dir: Path, deadline_s: float) -> dict:
    job_json = {"schema": JOB_SCHEMA, "kind": kind, "job_id": job_id, "title": title,
                "model": plan["repo"], **plan["payload"]}
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
