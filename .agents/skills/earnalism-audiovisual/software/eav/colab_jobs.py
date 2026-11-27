"""Inert, hash-bound Colab job bundles (narration, stills, music, retouch, edit, reel clips).

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
# Retouch (owner 2026-11-25): redraw only small masked regions of an already-chosen still with an
# open inpainting model; the masks come from text-prompted segmentation. Both exact revisions are
# resolved and recorded by the notebook at run time, as for stills. Licences as the Hub card
# metadata states them (read 2026-11-25 through the Hugging Face connector, not the licence text
# itself): SDXL inpainting 0.1 "openrail++" (CreativeML OpenRAIL++-M: commercial use allowed under
# its use restrictions), CLIPSeg rd64-refined "apache-2.0". The notebook re-reads each card's
# `license` field before any download and refuses a value outside LICENCE_ALLOWLIST.
RETOUCH_REPO = "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"
MASK_REPO = "CIDAS/clipseg-rd64-refined"
MODEL_LICENCES = {RETOUCH_REPO: "openrail++", MASK_REPO: "apache-2.0"}
LICENCE_ALLOWLIST = ("apache-2.0", "mit", "openrail++")
RETOUCH_STEPS = 30
RETOUCH_GUIDANCE = 7.5
# Soft CLIPSeg mask -> threshold -> dilate a few px -> union of the regions -> feather.
RETOUCH_MASK = {"threshold": 0.4, "dilate_px": 6, "feather_px": 4}
MAX_REGIONS = 6
STRENGTH_RANGE = (0.5, 1.0)
# Edit (owner 2026-11-25, free test on Colab Pro): an instruction-following image editor repairs
# held shots the open text-to-image models drew wrong (a child widow given a bindi or looking too
# young, a judge with a beard, the Giant at the wrong scale, snow inside rooms). Qwen-Image-Edit-2511
# (Hub card `license: apache-2.0`, ~20.4B params, diffusers QwenImageEditPlusPipeline) takes the
# still to edit first, then up to two reference images, and has a real negative prompt with
# true_cfg_scale. Its revision is resolved and recorded at run time; the notebook re-reads the card
# licence before any download and refuses anything but apache-2.0.
EDIT_REPO = "Qwen/Qwen-Image-Edit-2511"
EDIT_PIPELINE = "QwenImageEditPlusPipeline"
# 0.36.0 is the first release with QwenImageEditPlusPipeline, but 2511's transformer config sets
# zero_cond_t, which QwenImageTransformer2DModel accepts only from 0.37.0 (0.36.0 would drop it
# and run the model wrongly). Checked against both wheels from PyPI on 2026-11-25.
EDIT_DIFFUSERS = "diffusers==0.37.0"
EDIT_LICENCES = {EDIT_REPO: "apache-2.0"}
EDIT_LICENCE_ALLOWLIST = ("apache-2.0",)
EDIT_RATE_STEPS = 40      # rates.json "edit" is measured at 40 steps per image
EDIT_DEFAULT_STEPS = 40
EDIT_STEPS_RANGE = (8, 50)
EDIT_CFG_RANGE = (1.0, 10.0)
EDIT_DEFAULT_CFG = 4.0
# Transformer precision by VRAM (owner 2026-11-26): the first L4 run, 4-bit NF4 everywhere,
# followed the instructions but every image came out grainy with a rough, washed texture.
# >= 70 GiB (A100 80 GB): bf16; 30-70 GiB (A100 40 GB): 8-bit LLM.int8; below (L4): NF4. Both
# quantized loads keep the sensitive modules bf16: the image/text input projections, the
# timestep/text embedding, the final norm and the output projection. Names checked against
# QwenImageTransformer2DModel in the diffusers 0.37.0 wheel (img_in, txt_in, time_text_embed,
# norm_out, proj_out); bitsandbytes skips a Linear whose own name or dotted path prefix matches.
EDIT_BF16_FROM_GIB = 70
EDIT_INT8_FROM_GIB = 30
EDIT_SKIP_MODULES = ("img_in", "txt_in", "time_text_embed", "norm_out", "proj_out")
# Optional top-level spec "min_vram_gib": the GPU cell stops before any download on a smaller GPU.
MIN_VRAM_RANGE = (0, 80)
MAX_EDIT_REFS = 2
MAX_INSTRUCTION = 900
# Appended to every edit instruction: the edit changes only what it names.
EDIT_KEEP = ("Keep everything else unchanged: the same 2D animated feature-film illustration style, "
             "line art, cel shading, colours, faces, composition and framing.")
REEL_PROFILE = "l4-balanced-v2"
# One reel_clips batch must fit one Wan job (batch.MAX_WALL_SECONDS = 2700 s) at the measured
# ~500 s per finished clip, and the owner's metered Wan authority approves at most 5 CU.
MAX_CLIPS_PER_BATCH = 5
MAX_APPROVED_UNITS = 5.0
DRIVE_ROOT = "/content/drive/MyDrive/earnalism-audiovisual"

# film_clips (cinematic film, Task 6): the shot plan's Wan beats (Wan 2.2 TI2V-5B, Apache-2.0) and the
# depth maps the camera glide needs (Depth Anything V2 Small, Apache-2.0; Base and Large are
# non-commercial and refused). The notebook re-reads both cards' `license` before any download.
FILM_REPO = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
FILM_DEPTH_REPO = "depth-anything/Depth-Anything-V2-Small-hf"
FILM_LICENCES = {FILM_REPO: "apache-2.0", FILM_DEPTH_REPO: "apache-2.0"}
FILM_LICENCE_ALLOWLIST = ("apache-2.0",)
FILM_STEPS = 24
FILM_GUIDANCE = 5.0
FILM_FRAMES = 121     # 121 frames at 24 fps = 5.041667 s per clip
FILM_FPS = 24
FILM_DIFFUSERS = "diffusers==0.37.0"
FILM_MIN_VRAM_GIB = 21  # an L4 (22 GB) or larger; the GPU cell stops before any download on less
FILM_A100_FROM_GIB = 24  # a job needing more than this runs on an A100 (rates units_per_hour_a100)
FILM_RES = {(1280, 704): "hd", (896, 512): "sd"}  # the shot plan's wan_res values
# One film_clips job fits one Colab session: the notebook's own hard stop is its forecast, at most 70 minutes
# (spec builder-check "Film animation jobs"). A longer request is split into several jobs (split_film_spec).
FILM_SESSION_S = 4200
# Depth Anything V2 Small in the same run (ESTIMATE until measured; rates.json film_clips may restate them as
# depth_setup_s and depth_s_per_image): model load once, then per image (every item image, every clip's last
# frame and every depth-only still).
DEPTH_SETUP_S = 90
DEPTH_S_PER_IMAGE = 4
_DEPTH_STILL = re.compile(r"[a-z0-9][a-z0-9-]*-[1-9][0-9]*\.png")
FILM_NEGATIVE = ("photorealistic, 3D render, CGI, text, logo, watermark, extra fingers, fused hands, "
                 "duplicate people, face morphing, detached hand, disembodied hand, floating hand, extra "
                 "hand, extra arm, missing arm, floating object, objects flying, blink, closed eyes, "
                 "morphing eyelids, transparent cloth, abrupt cuts, camera shake, camera movement, zoom, "
                 "pan, flicker")

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
# Stills gate (Task 11): every model's licence must be on this list at run time, read from its Hub card
# (a card that cannot be read, or a licence off the list, means the model is not loaded and its checks
# are needs_review). MediaPipe Face/Hand Landmarker are not on the Hub: Apache-2.0 as their model cards
# declare. OWLv2 google/owlv2-base-patch16-ensemble and DINOv2-small facebook/dinov2-small carry
# `license: apache-2.0` on the Hub (read 2026-11-27 through the Hub connector). CLIP was dropped: its card
# has no licence and puts any deployed use out of scope.
GATE_LICENCE_ALLOWLIST = ("apache-2.0", "mit")
# DINOv2-small cosine of a still's person-box crop against the character's anchor still. UNCALIBRATED
# (no measurement on these stills; DINOv2 cosines for the same character in a new pose are usually lower
# than CLIP's): a figure below it sets needs_review only, and needs_review is advisory at pick until the
# title has a gate-calibration.json. Re-tune it from approved stills.
GATE_ANCHOR_PASS = 0.55
# The gate's seconds are part of the stills forecast (gate_s): ESTIMATE, not measured. Set-up covers the
# pip install, the two MediaPipe files and the OWLv2 + DINOv2 downloads; the rest is per still.
GATE_SETUP_S = 300
GATE_PER_STILL_S = 6
GATE_MARKER = "# === gate cell ===\n"
# film_clips sound fetch (optional spec "sfx"): its own wall-clock budget, reserved inside the job forecast.
SFX_BUDGET_S = 480
SFX_EXTENSIONS = ("ogg", "oga", "opus", "wav", "flac", "mp3")
_SFX_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
KINDS = ("narration", "stills", "music", "retouch", "edit", "reel_clips", "film_clips")
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


def _check_mask_model(spec: dict) -> None:
    for key in ("mask_model", "mask_repo"):
        value = spec.get(key)
        if value is not None and value != MASK_REPO:
            raise ValueError(f"retouch masks must use {MASK_REPO!r}, not {value!r}")


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
_GPU = _GUARD + '''import shutil, subprocess
# A GPU first: a CPU-only runtime would install, download and then fail with a confusing CUDA error.
_smi = shutil.which("nvidia-smi")
if not _smi or subprocess.run([_smi, "-L"], capture_output=True).returncode != 0:
    raise RuntimeError("No GPU attached: Runtime -> Disconnect and delete runtime, then Runtime -> "
                       "Change runtime type -> A100 GPU (or L4), Save, Connect, and Run all again")
print(subprocess.run([_smi, "-L"], capture_output=True, text=True).stdout.strip())
_min_gib = globals().get("MIN_VRAM_GIB", 0)
if _min_gib:  # the job's spec min_vram_gib: refuse a smaller GPU before any install or download
    _q = subprocess.run([_smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True)
    try:
        _gib = int(_q.stdout.split()[0]) / 1024  # MiB of the first GPU
    except (IndexError, ValueError):
        raise RuntimeError("could not read the GPU memory from nvidia-smi (" + repr(_q.stdout)
                           + "); this job needs at least %d GiB" % _min_gib) from None
    print("GPU memory %.1f GiB (this job needs at least %d GiB)" % (_gib, _min_gib))
    if _gib < _min_gib:
        raise RuntimeError("This job needs at least %d GiB of GPU memory and this GPU has %.1f GiB: it "
                           "needs an A100 or larger: Runtime -> Change runtime type -> A100, Save, "
                           "Connect, and Run all again (nothing was downloaded)" % (_min_gib, _gib))
'''


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

# Retouch and edit: every repo of the job reachable and each model card's licence on the
# allowlist, printed, before the clock starts and before any install or download.
_LICENCE = _GUARD + '''import os
from huggingface_hub import HfApi
LICENCES = {}
for _repo in LICENCE_REPOS:
    try:
        HfApi().auth_check(_repo, token=os.environ.get("HF_TOKEN"))
        _info = HfApi().model_info(_repo, token=os.environ.get("HF_TOKEN"))
    except Exception as _e:
        raise RuntimeError("No access to " + _repo + " (" + type(_e).__name__ + "); nothing ran") from None
    _card = getattr(_info, "card_data", None) or getattr(_info, "cardData", None) or {}
    _lic = _card.get("license") if hasattr(_card, "get") else getattr(_card, "license", None)
    if not _lic:
        _lic = next((t.split(":", 1)[1] for t in (getattr(_info, "tags", None) or [])
                     if t.startswith("license:")), None)
    _lic = str(_lic).strip().lower() if _lic else None
    print("model card licence:", _repo, "->", _lic, "(allowlist: %s)" % ", ".join(LICENCE_ALLOWLIST))
    if _lic not in LICENCE_ALLOWLIST:
        raise RuntimeError("model card licence of " + _repo + " is " + repr(_lic) + ", not one of "
                           + ", ".join(LICENCE_ALLOWLIST) + ": this job never runs it; tell Claude")
    LICENCES[_repo] = _lic
'''

# Edit only: install the pinned diffusers before the clock and refuse a build without the pipeline
# class (or without the zero_cond_t transformer option 2511 needs) before any weights download.
_EDIT_PREFLIGHT = _GUARD + '''import importlib, inspect, subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", DIFFUSERS_PIN, "transformers",
                "accelerate", "safetensors", "bitsandbytes"], check=True)
importlib.invalidate_caches()
import diffusers
print("diffusers", diffusers.__version__, "(pin: " + DIFFUSERS_PIN + ")")
if not hasattr(diffusers, EDIT_PIPELINE):
    raise RuntimeError("diffusers " + diffusers.__version__ + " has no " + EDIT_PIPELINE + "; install "
                       + DIFFUSERS_PIN + " (Runtime > Restart session, Run all); nothing downloaded")
if "zero_cond_t" not in inspect.signature(diffusers.QwenImageTransformer2DModel.__init__).parameters:
    raise RuntimeError("diffusers " + diffusers.__version__ + " QwenImageTransformer2DModel lacks "
                       "zero_cond_t (needed by " + MODEL_REPO + "); install " + DIFFUSERS_PIN)
print("pipeline OK:", EDIT_PIPELINE)
'''

# film_clips only: install the pinned diffusers before the clock and refuse a build without the Wan
# image-to-video pipeline before any weights download.
_FILM_PREFLIGHT = _GUARD + '''import importlib, subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", DIFFUSERS_PIN, "transformers", "accelerate",
                "safetensors", "ftfy", "sentencepiece", "imageio", "imageio-ffmpeg"], check=True)
importlib.invalidate_caches()
import diffusers
print("diffusers", diffusers.__version__, "(pin: " + DIFFUSERS_PIN + ")")
if not hasattr(diffusers, "WanImageToVideoPipeline"):
    raise RuntimeError("diffusers " + diffusers.__version__ + " has no WanImageToVideoPipeline; "
                       "Runtime > Restart session, Run all")
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
    if (p.is_file() and p.name not in ("manifest.json", "inputs.zip", "exchange.json", "done.json", "done.json.tmp")
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
PACKAGES = {"film_clips": ("diffusers", "transformers", "accelerate", "safetensors", "torch",
                           "huggingface_hub", "imageio", "ftfy"),
            "narration": ("parler_tts", "transformers", "torch", "soundfile", "protobuf"),
            "stills": ("diffusers", "transformers", "accelerate", "sentencepiece", "protobuf",
                       "bitsandbytes", "torch", "mediapipe"),
            "retouch": ("diffusers", "transformers", "accelerate", "safetensors", "torch",
                        "huggingface_hub"),
            "edit": ("diffusers", "transformers", "accelerate", "safetensors", "bitsandbytes",
                     "torch", "huggingface_hub"),
            "music": ("ace-step", "acestep", "torch", "transformers", "diffusers", "huggingface_hub")}
MANIFEST_RESERVE_S = 60


def min_vram_gib(spec: dict) -> int:
    """The job's optional top-level min_vram_gib (default 0: any GPU)."""
    v = spec.get("min_vram_gib", 0)
    lo, hi = MIN_VRAM_RANGE
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError(f"min_vram_gib must be an integer from {lo} to {hi} (GiB of GPU memory; "
                         f"30 needs an A100 40 GB, 70 an A100 80 GB), not {v!r}")
    return v


def _template_cells(kind, template: Path) -> list:
    """The job's own cells: a stills template carries its gate cell after the stills, split at the marker
    (the gate's licence allowlist and anchor threshold are baked in from this module)."""
    text = template.read_text(encoding="utf-8")
    if kind != "stills" or GATE_MARKER not in text:
        return [text]
    stills, gate = text.split(GATE_MARKER, 1)
    config = (f"GATE_LICENCE_ALLOWLIST = {GATE_LICENCE_ALLOWLIST!r}\n"
              f"GATE_ANCHOR_PASS = {GATE_ANCHOR_PASS!r}\n"
              f"GATE_SETUP_S = {GATE_SETUP_S!r}\nGATE_PER_STILL_S = {GATE_PER_STILL_S!r}")
    return [stills.rstrip("\n") + "\n", gate.replace("GATE_CONFIG_HERE", config, 1)]


def _notebook(kind, job_id, title, zip_sha, repo, revision, steps, template, deadline_s,
              min_vram=0, clip_s=None, sfx=False) -> bytes:
    retouch, edit, film = kind == "retouch", kind == "edit", kind == "film_clips"
    config = (_GUARD +
              f"import pathlib\nJOB_ID = {job_id!r}\nTITLE = {title!r}\nKIND = {kind!r}\n"
              f"INPUT_ZIP_SHA256 = {zip_sha!r}\nMODEL_REPO = {repo!r}\n"
              f"MODEL_REVISION = {revision!r}\nSTEPS = {steps!r}\n"
              f"DRIVE_JOB_DIR = {DRIVE_ROOT + '/' + title + '/' + job_id!r}\n"
              f"# Hard wall-clock stop = the forecast seconds reserved on the ledger (R25)\n"
              f"DEADLINE_SECONDS = {int(deadline_s)}\nMANIFEST_RESERVE_S = {MANIFEST_RESERVE_S}\n"
              f"PACKAGES = {PACKAGES[kind]!r}\nEXCHANGE_SCHEMA = {EXCHANGE_SCHEMA!r}\n"
              f"# The GPU cell stops before any download below this much GPU memory (0: any GPU)\n"
              f"MIN_VRAM_GIB = {int(min_vram)}\n")
    if retouch:
        config += (f"MASK_REPO = {MASK_REPO!r}\nLICENCE_ALLOWLIST = {LICENCE_ALLOWLIST!r}\n"
                   f"LICENCE_REPOS = (MODEL_REPO, MASK_REPO)\n"
                   f"GUIDANCE = {RETOUCH_GUIDANCE!r}\nMASK = {RETOUCH_MASK!r}\n")
    if edit:
        config += (f"LICENCE_ALLOWLIST = {EDIT_LICENCE_ALLOWLIST!r}\nLICENCE_REPOS = (MODEL_REPO,)\n"
                   f"EDIT_PIPELINE = {EDIT_PIPELINE!r}\nDIFFUSERS_PIN = {EDIT_DIFFUSERS!r}\n"
                   f"# transformer bf16 from BF16_FROM_GIB of VRAM, 8-bit from INT8_FROM_GIB, else NF4;\n"
                   f"# quantized loads keep SKIP_MODULES bf16\n"
                   f"BF16_FROM_GIB = {EDIT_BF16_FROM_GIB}\nINT8_FROM_GIB = {EDIT_INT8_FROM_GIB}\n"
                   f"SKIP_MODULES = {list(EDIT_SKIP_MODULES)!r}\n")
    if film:
        config += (f"GUIDANCE = {FILM_GUIDANCE!r}\nFRAMES = {FILM_FRAMES}\nFPS = {FILM_FPS}\n"
                   f"LICENCE_ALLOWLIST = {FILM_LICENCE_ALLOWLIST!r}\nDEPTH_REPO = {FILM_DEPTH_REPO!r}\n"
                   f"LICENCE_REPOS = (MODEL_REPO, DEPTH_REPO)\nDIFFUSERS_PIN = {FILM_DIFFUSERS!r}\n"
                   f"# measured seconds per finished clip by resolution (this job's GPU class), for may_start\n"
                   f"CLIP_S = {clip_s!r}\n")
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
    parts = [("markdown", intro), ("code", "RUN = False"), ("code", config), ("code", _GPU), ("code", _ACCESS),
             *([("code", _LICENCE)] if retouch or edit or film else []),
             *([("code", _EDIT_PREFLIGHT)] if edit else []),
             *([("code", _FILM_PREFLIGHT)] if film else []), ("code", _CLOCK),
             ("code", _VERIFY),
             *([("code", (_TEMPLATES / "sfx_cell.py.txt").read_text(encoding="utf-8"))] if film and sfx else []),
             *[("code", t) for t in _template_cells(kind, template)],
             ("code", _MANIFEST)]
    nb = {"nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"},
                       "language_info": {"name": "python"},
                       "colab": {"name": f"earnalism_{kind}_{job_id}.ipynb",
                                 "gpuType": "A100" if min_vram > 24 else "L4"}},
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
    if kind == "retouch":
        return RETOUCH_STEPS
    if kind == "edit":
        return EDIT_RATE_STEPS  # the steps the edit rate is measured at; items carry their own
    if kind == "reel_clips":
        return _load_wan_batch().w.PROFILES[REEL_PROFILE]["steps"]
    if kind == "film_clips":
        return FILM_STEPS
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
    positive = ("clip_s", "units_per_hour", "s_per_step")
    if kind == "film_clips":
        positive = ("clip_s_hd", "clip_s_hd_a100", "clip_s_sd", "units_per_hour_l4", "units_per_hour_a100")
        needed = positive + ("decode_s", "export_s")
    missing = [k for k in needed if not isinstance(rate, dict) or not _measured(
        rate.get(k), positive=k in positive)]
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
    if kind == "edit":  # steps x images is never below the job's real step total
        steps = math.ceil(sum(_edit_steps(s) * _candidates(s, kind) for s in spec.get("items") or [])
                          / items)
    compute = {"kind": kind, "steps": steps, "items": items, "takes": 1}
    if kind != "reel_clips":
        compute.update(decode_s=rate["decode_s"], export_s=rate["export_s"])
    if kind == "stills":  # the gate's set-up and per-still seconds (ESTIMATE, rates.json may restate them)
        compute["gate_s"] = (rate.get("gate_setup_s", GATE_SETUP_S) + rate.get("gate_s_per_still", GATE_PER_STILL_S)
                             * items)
    if kind == "film_clips":  # clips by resolution and the GPU the job needs: both set the forecast
        items_ = _film_items(spec)
        shapes = [FILM_RES[(c["width"], c["height"])] for c in items_]
        compute.update(hd=shapes.count("hd"), sd=shapes.count("sd"),
                       gpu="a100" if film_min_vram(spec) > FILM_A100_FROM_GIB else "l4")
        images = len({i["image"] for i in items_ if i["image"]} | set(film_depth_stills(spec))) + len(items_)
        compute["depth_s"] = (rate.get("depth_setup_s", DEPTH_SETUP_S)    # C1: the depth maps are work too
                              + rate.get("depth_s_per_image", DEPTH_S_PER_IMAGE) * images)
        if _film_sfx(spec):  # the sound stage runs before the clips, inside the forecast the clock enforces
            compute["sfx_s"] = SFX_BUDGET_S
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


T5_MAX = 256  # FLUX.1-schnell's T5 limit: tokens past it are cut (the stills template says the same)
# Refuse above this estimate, well under T5_MAX: calibrated on the six recorded truncated stills jobs
# (bicharak r8-house, r9, r10, pilot2, pilot4, pilot5), whose truncated prompts all estimate 188 or more
# with estimate_t5_tokens, against the clean pilot6 prompt at 178. Some clean prompts (up to ~207 on the
# older estimate) must now be shortened; that is the intended cost.
T5_ESTIMATE_LIMIT = 180


def estimate_t5_tokens(text: str) -> int:
    """A calibrated estimate of the T5 token count (no tokenizer is installed here): every word is one
    piece, a word over 6 letters (names, Bengali words, compounds that SentencePiece splits into 2-3) is
    1.8, a punctuation mark 0.5, rounded up. Judged only by the recorded truncations (T5_ESTIMATE_LIMIT),
    not as an exact count."""
    total = 0.0
    for piece in re.findall(r"\w+|[^\w\s]", text):
        total += (1.8 if len(piece) > 6 else 1.0) if (piece[0].isalnum() or piece[0] == "_") else 0.5
    return math.ceil(total)


def negative_words(prompt: str) -> list:
    """The negative words a prompt uses (lowercase, in order); FLUX draws what they name."""
    return [m.group(0).lower() for m in NEGATIVE_WORDS.finditer(prompt)]


def _candidates(item: dict, kind: str = "stills") -> int:
    n = item.get("candidates", 1)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_CANDIDATES:
        raise ValueError(f"{kind} item {item.get('key')!r} candidates must be an integer from 1 to "
                         f"{MAX_CANDIDATES}, not {n!r}")
    return n


def job_items(kind: str, spec: dict) -> int:
    """How many items the job really generates (voice units, stills images, cues or shots);
    a stills item with candidates counts once per candidate image."""
    if kind == "narration":
        return len(narration_units(spec))
    if kind == "stills":
        return sum(_candidates(s) for s in spec.get("items") or [])
    if kind in ("retouch", "edit"):
        return sum(_candidates(s, kind) for s in spec.get("items") or [])
    if kind == "film_clips":   # every clip and every depth-only still is generated work
        return len(spec.get("items") or []) + len(spec.get("depth_stills") or [])
    return len(spec.get("shots" if kind == "reel_clips" else "items") or [])


def _check_prompt(kind: str, key, prompt) -> None:
    """Positive-only wording and the house style, as for stills (references/visual-style.md)."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"{kind} item {key!r} needs a non-empty prompt")
    clash = [w for w in STYLE_CONFLICTS if w in prompt.lower()]
    if clash:
        raise ValueError(f"{kind} prompt {key!r} asks for {clash[0]!r}, which conflicts with "
                         f"the house style (references/visual-style.md); describe the content only")
    negative = negative_words(prompt)
    if negative:
        raise ValueError(f"{kind} prompt {key!r} uses the negative word {negative[0]!r}: "
                         "the generator has no negative prompt and draws what it names; "
                         "describe what is there instead (e.g. 'bare forehead', 'clean-shaven')"
                         " (references/visual-style.md, Prompt wording)")


def _imported_stills(record) -> dict:
    """{job_id: target} of the record's imported, un-ended stills jobs."""
    events = record.data["events"]
    targets = {e["detail"]["job_id"]: e["detail"].get("target") for e in events
               if e["stage"] == "cli" and e["result"] == "job_target"
               and e["detail"].get("kind", "stills") == "stills"}
    done = {e["detail"].get("job_id") for e in events if e["stage"] == "import" and e["result"] == "accepted"}
    ended = {e["detail"].get("job_id") for e in events if e["stage"] == "job"
             and e["result"] in ("superseded", "closed", "superseding", "closing")}
    built = {a["meta"].get("job_id") for a in record.data["artifacts"]
             if a["kind"] == "colab_job" and a["meta"].get("job_kind") == "stills"}
    stills = {a["meta"].get("job_id") for a in record.data["artifacts"] if a["kind"] == "stills"}
    return {j: t for j, t in targets.items()
            if j in done and j not in ended and (j in built or j in stills)}


def _retouch_items(record, spec: dict) -> tuple:
    """Validate a retouch spec against the record; returns (job items, masks, sources zip map)."""
    target = spec.get("target")
    jobs = _imported_stills(record)
    files = {}  # (job, file) -> recorded sha256
    film_keys = set()
    for a in record.data["artifacts"]:
        jid = a["meta"].get("job_id")
        if a["kind"] != "stills" or jid not in jobs:
            continue
        name = Path(a["path"]).name
        files[(jid, name)] = a["sha256"]
        if jobs[jid] == target:
            film_keys.add(CANDIDATE_SUFFIX.sub("", Path(name).stem))
    if not film_keys:
        raise ValueError(f"{target!r} has no imported stills to retouch")
    items, masks, sources, seen = [], [], {}, set()
    for s in spec.get("items") or []:
        key = s.get("key")
        if not isinstance(key, str) or CANDIDATE_SUFFIX.search(key) or key.endswith("--mask"):
            raise ValueError(f"retouch key {key!r} must be a still key (no --cN or --mask)")
        if key in seen:
            raise ValueError(f"retouch key {key!r} appears twice; one item per still")
        seen.add(key)
        if key not in film_keys:
            raise ValueError(f"retouch key {key!r} is not a still of {target}")
        src = s.get("source") or {}
        job, name = src.get("job"), src.get("file")
        if job not in jobs or jobs[job] != target:
            raise ValueError(f"retouch {key!r}: source job {job!r} is not an imported stills job of {target}")
        if (job, name) not in files or Path(str(name)).name != name:
            raise ValueError(f"retouch {key!r}: {name!r} is not an imported file of stills job {job}")
        if CANDIDATE_SUFFIX.sub("", Path(name).stem) != key:
            raise ValueError(f"retouch {key!r}: source {name!r} is another still's file")
        path = record.root / "stills" / job / name
        data = path.read_bytes() if path.is_file() else b""
        digest = hashlib.sha256(data).hexdigest()
        if digest != files[(job, name)]:
            raise ValueError(f"retouch {key!r}: {job}/{name} sha256 {digest[:12]} differs from the "
                             f"record's {files[(job, name)][:12]}; the still changed since import")
        regions = s.get("regions")
        if not isinstance(regions, list) or not 1 <= len(regions) <= MAX_REGIONS:
            raise ValueError(f"retouch {key!r} needs 1 to {MAX_REGIONS} regions")
        clean = []
        for g in regions:
            if not isinstance(g, dict) or not isinstance(g.get("find"), str) or not g["find"].strip():
                raise ValueError(f"retouch {key!r}: every region needs a find text (the mask query)")
            # find describes what to locate, so it may name the unwanted thing; prompt is drawn
            _check_prompt("retouch", key, g.get("prompt"))
            clean.append({"find": g["find"].strip(), "prompt": g["prompt"].strip()})
        _check_prompt("retouch", key, s.get("prompt"))
        prompt = s["prompt"].rstrip() + " " + HOUSE_STYLE
        _check_prompt("retouch", key, prompt)
        strength = s.get("strength")
        lo, hi = STRENGTH_RANGE
        if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not lo <= strength <= hi:
            raise ValueError(f"retouch {key!r} strength must be a number from {lo} to {hi}, not {strength!r}")
        n, seed = _candidates(s, "retouch"), int(s["seed"])
        member = f"sources/{job}--{name}"
        sources[member] = data
        items += [{"key": f"{key}--c{c}", "base": key, "candidate": c, "seed": seed + c - 1,
                   "source": member, "source_job": job, "source_file": name, "source_sha256": digest,
                   "regions": clean, "prompt": prompt, "strength": float(strength)}
                  for c in range(1, n + 1)]
        masks.append(f"{key}--mask")
    if not items:
        raise ValueError("no stills to retouch")
    return items, masks, sources


def _edit_steps(item: dict) -> int:
    n = item.get("steps", EDIT_DEFAULT_STEPS) if isinstance(item, dict) else None
    lo, hi = EDIT_STEPS_RANGE
    if isinstance(n, bool) or not isinstance(n, int) or not lo <= n <= hi:
        key = item.get("key") if isinstance(item, dict) else None
        raise ValueError(f"edit item {key!r} steps must be an integer from {lo} to {hi}, not {n!r}")
    return n


IMAGE_KINDS = ("stills", "retouch", "touchup")  # imported jobs whose images an edit may read


def _imported_images(record) -> tuple:
    """({job_id: (kind, target)}, {(job_id, file name): (path, recorded sha256)}) of the record's
    imported, un-ended stills, retouch and touchup jobs (review masks excluded)."""
    events = record.data["events"]
    targets = {e["detail"]["job_id"]: (e["detail"].get("kind", "stills"), e["detail"].get("target"))
               for e in events if e["stage"] == "cli" and e["result"] == "job_target"
               and e["detail"].get("kind", "stills") in IMAGE_KINDS}
    done = {e["detail"].get("job_id") for e in events if e["stage"] == "import" and e["result"] == "accepted"}
    ended = {e["detail"].get("job_id") for e in events if e["stage"] == "job"
             and e["result"] in ("superseded", "closed", "superseding", "closing")}
    jobs = {j: kt for j, kt in targets.items() if j in done and j not in ended}
    files = {}
    for a in record.data["artifacts"]:
        jid = a["meta"].get("job_id")
        if jid in jobs and a["kind"] == jobs[jid][0] and not a["path"].endswith("--mask.png"):
            files[(jid, Path(a["path"]).name)] = (record.root / a["path"], a["sha256"])
    return {j: kt for j, kt in jobs.items() if any(k[0] == j for k in files)}, files


def _edit_text(key, field, value, allow_empty=False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"edit {key!r} needs a {'' if allow_empty else 'non-empty '}{field} text")
    if len(value) > MAX_INSTRUCTION:
        raise ValueError(f"edit {key!r} {field} is {len(value)} characters; at most {MAX_INSTRUCTION}")
    return value.strip()


def _edit_items(record, spec: dict) -> tuple:
    """Validate an edit spec against the record; returns (job items, zip members).

    The positive-only wording rule of stills and retouch does not apply: Qwen-Image-Edit has a real
    negative prompt (true CFG) and an edit instruction says what to change, "remove ..." included
    (references/visual-style.md, Edit). Another look is still refused in the instruction."""
    target = spec.get("target")
    jobs, files = _imported_images(record)
    film_keys = {CANDIDATE_SUFFIX.sub("", Path(name).stem) for (jid, name) in files
                 if jobs[jid] == ("stills", target)}
    if not film_keys:
        raise ValueError(f"{target!r} has no imported stills to edit")

    def recorded(key, what, ref, film=None):
        if not isinstance(ref, dict):
            raise ValueError(f"edit {key!r}: {what} must be {{job, file}}, not {ref!r}")
        job, name = ref.get("job"), ref.get("file")
        if job not in jobs or (film is not None and jobs[job][1] != film):
            raise ValueError(f"edit {key!r}: {what} job {job!r} is not an imported stills, retouch or "
                             f"touchup job{' of ' + film if film else ''}")
        if not isinstance(name, str) or Path(name).name != name or (job, name) not in files:
            raise ValueError(f"edit {key!r}: {what} {name!r} is not a recorded image of {job} "
                             "(review --mask files never count)")
        path, digest_rec = files[(job, name)]
        data = path.read_bytes() if path.is_file() else b""
        digest = hashlib.sha256(data).hexdigest()
        if digest != digest_rec:
            raise ValueError(f"edit {key!r}: {what} {job}/{name} sha256 {digest[:12]} differs from the "
                             f"record's {digest_rec[:12]}; the image changed since import")
        return job, name, data, digest

    items, members, seen = [], {}, set()
    for s in spec.get("items") or []:
        key = s.get("key") if isinstance(s, dict) else None
        if not isinstance(key, str) or CANDIDATE_SUFFIX.search(key) or key.endswith("--mask"):
            raise ValueError(f"edit key {key!r} must be a still key (no --cN or --mask)")
        if key in seen:
            raise ValueError(f"edit key {key!r} appears twice; one item per still")
        seen.add(key)
        if key not in film_keys:
            raise ValueError(f"edit key {key!r} is not a still of {target}")
        job, name, data, digest = recorded(key, "source", s.get("source"), film=target)
        if CANDIDATE_SUFFIX.sub("", Path(name).stem) != key:
            raise ValueError(f"edit {key!r}: source {name!r} is another still's file")
        source = f"sources/{job}--{name}"
        members[source] = data
        raw_refs = s.get("refs") if s.get("refs") is not None else []
        if not isinstance(raw_refs, list) or len(raw_refs) > MAX_EDIT_REFS:
            raise ValueError(f"edit {key!r} refs must be a list of 0 to {MAX_EDIT_REFS} {{job, file}}")
        refs = []
        for r in raw_refs:
            rjob, rname, rdata, rdigest = recorded(key, "ref", r)
            member = f"refs/{rjob}--{rname}"
            members[member] = rdata
            refs.append({"member": member, "job": rjob, "file": rname, "sha256": rdigest})
        instruction = _edit_text(key, "instruction", s.get("instruction"))
        clash = [w for w in STYLE_CONFLICTS if w in instruction.lower()]
        if clash:
            raise ValueError(f"edit instruction {key!r} asks for {clash[0]!r}, which conflicts with the "
                             "house style (references/visual-style.md); name the content to change")
        negative = _edit_text(key, "negative", s.get("negative", " "), allow_empty=True) or " "
        cfg = s.get("true_cfg_scale", EDIT_DEFAULT_CFG)
        lo, hi = EDIT_CFG_RANGE
        if isinstance(cfg, bool) or not isinstance(cfg, (int, float)) or not lo <= cfg <= hi:
            raise ValueError(f"edit {key!r} true_cfg_scale must be a number from {lo} to {hi}, not {cfg!r}")
        seed = s.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError(f"edit {key!r} seed must be a non-negative integer, not {seed!r}")
        n, steps = _candidates(s, "edit"), _edit_steps(s)
        items += [{"key": f"{key}--c{c}", "base": key, "candidate": c, "seed": seed + c - 1,
                   "source": source, "source_job": job, "source_file": name, "source_sha256": digest,
                   "refs": refs, "instruction": instruction + " " + EDIT_KEEP, "negative": negative,
                   "steps": steps, "true_cfg_scale": float(cfg)} for c in range(1, n + 1)]
    if not items:
        raise ValueError("no stills to edit")
    return items, members


def film_min_vram(spec: dict) -> int:
    """The GPU memory a film_clips job needs: the spec's min_vram_gib, never below the Wan floor."""
    return max(min_vram_gib(spec), FILM_MIN_VRAM_GIB)


def film_depth_stills(spec: dict) -> dict:
    """The job's depth-only stills, {name: {"path", "sha256"?}}: the picked stills of a scene's glide shots, named
    <scene>-<n>.png, whose depth maps the glide needs (C1). The spec lists them as names inside art_dir, or (as
    `job film_clips` fills them in from the scene's picks) as {name: {"path", "sha256"}}."""
    raw = spec.get("depth_stills")
    if raw is None:
        return {}
    if isinstance(raw, list):
        art = spec.get("art_dir")
        if raw and not art:
            raise ValueError("film_clips depth_stills named by file need art_dir (the folder holding them)")
        raw = {n: {"path": str(Path(art) / n)} if isinstance(n, str) else n for n in raw}
    if not isinstance(raw, dict):
        raise ValueError("film_clips depth_stills must be a list of <scene>-<n>.png names inside art_dir")
    out = {}
    for name, row in raw.items():
        if not isinstance(name, str) or not _DEPTH_STILL.fullmatch(name) or not isinstance(row, dict):
            raise ValueError(f"film_clips depth still {name!r} must be named <scene>-<n>.png (the glide shot's key)")
        path = Path(row.get("path", ""))
        if not path.is_file():
            raise ValueError(f"film_clips depth still {name!r} is not a file: {path}")
        sha = row.get("sha256")
        if sha is not None and hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError(f"film_clips depth still {name!r} ({path}) changed since it was picked")
        out[name] = {"path": str(path), **({"sha256": sha} if sha else {})}
    return out


def _film_items(spec: dict) -> list:
    """Validate and normalise a film_clips spec's items (the shot plan's Wan beats)."""
    items = spec.get("items")
    if items is None and spec.get("depth_stills"):
        items = []   # a depth-only job: the glide stills of a scene with no Wan shot left to make
    if not isinstance(items, list) or (not items and not spec.get("depth_stills")):
        raise ValueError("a film_clips job needs at least one item (or depth_stills only)")
    out, seen = [], set()
    for n, s in enumerate(items):
        if not isinstance(s, dict):
            raise ValueError(f"film_clips item {n} must be an object")
        key = s.get("key")
        if not isinstance(key, str) or not _SAFE.fullmatch(key):
            raise ValueError(f"film_clips item {n} key must be lowercase letters, digits and hyphens, "
                             f"not {key!r}")
        if key.startswith("sfx-"):
            raise ValueError(f"film_clips key {key!r} must not start with \"sfx-\" (that prefix names the "
                             "fetched sound files)")
        if key in seen:
            raise ValueError(f"film_clips key {key!r} is used twice")
        res = (s.get("width"), s.get("height"))
        if res not in FILM_RES:
            raise ValueError(f"film_clips item {key!r} must be 1280x704 or 896x512 (the shot plan's "
                             f"wan_res), not {res[0]!r}x{res[1]!r}")
        seed = s.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError(f"film_clips item {key!r} needs an integer seed")
        shot = s.get("shot")
        if shot is not None and (isinstance(shot, bool) or not isinstance(shot, int) or shot < 1):
            raise ValueError(f"film_clips item {key!r} shot must be a shot number of the plan (1, 2, ...)")
        cont, image = s.get("continue_from"), s.get("image")
        if cont is not None and cont not in seen:
            raise ValueError(f"film_clips item {key!r} continue_from {cont!r} must name an earlier item "
                             "of this job")
        if image is None and cont is None:
            raise ValueError(f"film_clips item {key!r} needs an image (or continue_from)")
        if image is not None and (not isinstance(image, str) or image != Path(image).name
                                  or not image.lower().endswith(".png")):
            raise ValueError(f"film_clips item {key!r} image must be a .png file name inside art_dir, "
                             f"not {image!r}")
        prompt = s.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"film_clips item {key!r} needs a non-empty prompt")
        seen.add(key)
        out.append({"key": key, "image": image, "width": res[0], "height": res[1], "seed": seed,
                    "prompt": prompt.strip(), "continue_from": cont,
                    **({"shot": shot} if shot is not None else {})})
    return out


def _film_sfx(spec: dict) -> dict:
    """The optional sound fetch: {"sfx": {"<name>": "<search words>"}} (lowercase name; a Commons search)."""
    sfx = spec.get("sfx")
    if sfx is None:
        return {}
    if not isinstance(sfx, dict) or not sfx:
        raise ValueError("film_clips sfx must be an object {\"<name>\": \"<search words>\"} "
                         "(omit it for no sound fetch)")
    out = {}
    for name, query in sfx.items():
        if not isinstance(name, str) or not _SFX_NAME.fullmatch(name):
            raise ValueError(f"film_clips sfx name {name!r} must be lowercase letters, digits and hyphens")
        if not isinstance(query, str) or not query.strip() or len(query) > 120:
            raise ValueError(f"film_clips sfx {name!r} needs search words (1-120 characters)")
        out[name] = query.strip()
    return out


def _chains(items: list) -> list:
    """The items grouped into continue_from chains, each in order (the take first)."""
    by_key = {i["key"]: i for i in items}
    kids = {}
    for i in items:
        if i.get("continue_from"):
            kids.setdefault(i["continue_from"], []).append(i["key"])
    out = []

    def walk(key, chain):
        chain = chain + [by_key[key]]
        if key not in kids:
            out.append(chain)
        for k in kids.get(key, []):
            walk(k, chain)
    for i in items:
        if not i.get("continue_from"):
            walk(i["key"], [])
    return out


def check_film_plan(spec: dict, plan: dict, covered=()) -> None:
    """A spec that declares "scene" is bound to that scene's approved shot plan: every item names (shot)
    a motion == "wan" shot at that shot's wan_res, every take's continue_from chain covers the shot's render
    length (its span plus its transition halves, shotplan.render_frames; I3: never a frozen last frame), and every
    wan shot has at least one item here or in another active film_clips job of the scene (`covered`: their shot
    numbers; several takes of a shot are allowed). Raises ValueError otherwise."""
    from . import shotplan
    wan = {s["n"]: s for s in plan["shots"] if s["motion"] == "wan"}
    need = shotplan.render_frames(plan["shots"])
    taken = set()
    items = _film_items(spec)
    for item in items:
        n = item.get("shot")
        if n is None:
            raise ValueError(f"film_clips item {item['key']!r} needs \"shot\": the number of a wan shot of "
                             f"scene {plan['scene_id']} (wan shots: {', '.join(map(str, sorted(wan))) or 'none'})")
        if n not in wan:
            raise ValueError(f"film_clips item {item['key']!r} names shot {n}, which is not a motion == "
                             f"\"wan\" shot of the approved plan of scene {plan['scene_id']} (wan shots: "
                             f"{', '.join(map(str, sorted(wan))) or 'none'})")
        want = wan[n]["wan_res"]
        if f"{item['width']}x{item['height']}" != want:
            raise ValueError(f"film_clips item {item['key']!r} is {item['width']}x{item['height']} but "
                             f"shot {n} of the approved plan is {want}")
        taken.add(n)
    for chain in _chains(items):
        n = chain[0].get("shot")
        if any(c.get("shot") != n for c in chain):
            raise ValueError(f"film_clips chain of {chain[0]['key']!r} mixes shots: a continuation continues its shot")
        have = shotplan.chain_frames(len(chain))
        if have < need[n]:
            raise ValueError(f"shot {n} of scene {plan['scene_id']} renders {need[n]} frames ({need[n] / FILM_FPS:.2f} s "
                             f"with its transition halves) but the take ending {chain[-1]['key']!r} chains "
                             f"{len(chain)} clip(s) = {have} frames: add continuation item(s) (continue_from) up to "
                             f"{shotplan.clips_for(need[n])} clips, each with its own action")
    missing = sorted(set(wan) - taken - set(covered))
    if missing:
        raise ValueError(f"the approved plan of scene {plan['scene_id']} has wan shot(s) with no "
                         f"film_clips item: shot {', '.join(map(str, missing))}")


def _check_depth_model(spec: dict) -> None:
    for field in ("depth_repo", "depth_model"):
        value = spec.get(field)
        if value is not None and value != FILM_DEPTH_REPO:
            raise ValueError(f"film_clips depth must use {FILM_DEPTH_REPO!r} (Apache-2.0); the Base and "
                             f"Large depth models are non-commercial, not {value!r}")


def _film_files(spec: dict, items: list) -> dict:
    art = spec.get("art_dir")
    names = sorted({i["image"] for i in items if i["image"]})
    if names and not art:
        raise ValueError("a film_clips spec needs art_dir (the folder holding the item images)")
    files = {}
    for name in names:
        path = Path(art) / name
        if not path.is_file():
            raise ValueError(f"film_clips image {name!r} is not in art_dir {art}")
        files[name] = path.read_bytes()
    for name, row in film_depth_stills(spec).items():
        data = Path(row["path"]).read_bytes()
        if name in files and files[name] != data:
            raise ValueError(f"film_clips depth still {name!r} has the name of a different item image")
        files[name] = data
    return files


def _film_seconds(compute: dict, rates: dict) -> float:
    return forecast_seconds(compute, rates)


def split_film_spec(spec: dict, rates: dict) -> list:
    """The spec as one or more film_clips specs, each forecast within one Colab session (FILM_SESSION_S): items
    stay with their continue_from chain, packed in order; the depth stills and the sound fetch ride in the first
    job. Raises ValueError when one chain alone does not fit a session."""
    items = _film_items(spec)
    chains = _chains(items)
    depth = film_depth_stills(spec)

    def part(chs, first):
        sub = {k: v for k, v in spec.items() if k not in ("items", "depth_stills", "sfx", "job_id", "compute")}
        sub["items"] = [dict(i, **({} if i.get("continue_from") else {"continue_from": None})) for c in chs for i in c]
        seen, uniq = set(), []
        for i in sub["items"]:      # a chain shared by two takes lists its head once
            if i["key"] not in seen:
                seen.add(i["key"])
                uniq.append(i)
        sub["items"] = uniq
        if first:
            if depth:
                sub["depth_stills"] = depth
            if spec.get("sfx"):
                sub["sfx"] = spec["sfx"]
        return sub

    def secs(sub):
        return _film_seconds(derive_compute("film_clips", sub, rates, job_items("film_clips", sub)), rates)
    if not chains:
        return [part([], True)]
    families = {}
    for ch in chains:    # takes that share a head stay in one job (a continuation needs its head's last frame)
        families.setdefault(ch[0]["key"], []).append(ch)
    out, cur = [], []
    for fam in families.values():
        ch = [i for c in fam for i in c]
        if secs(part([ch], not out and not cur)) > FILM_SESSION_S:
            raise ValueError(f"the take(s) from {ch[0]['key']!r} ({len(ch)} clip(s)) alone need more than one "
                             f"Colab session ({FILM_SESSION_S} s): use the A100 (min_vram_gib 30) or 896x512")
        if cur and secs(part(cur + [ch], not out)) > FILM_SESSION_S:
            out.append(part(cur, not out))
            cur = []
        cur.append(ch)
    out.append(part(cur, not out))
    return out


def _stills_anchor(spec: dict, item: dict, files: dict):
    """A stills item's optional "anchor": the character's anchor still, a .png inside the spec's art_dir.
    It rides in inputs.zip as anchors/<name> and the gate compares the item's still (CLIP similarity) to it."""
    name = item.get("anchor")
    if name is None:
        return None
    if not isinstance(name, str) or name != Path(name).name or not name.lower().endswith(".png"):
        raise ValueError(f"stills item {item.get('key')!r} anchor must be a .png file name inside art_dir, "
                         f"not {name!r}")
    art = spec.get("art_dir")
    if not art:
        raise ValueError(f"stills item {item.get('key')!r} has an anchor, so the spec needs art_dir "
                         "(the folder holding the anchor stills)")
    path = Path(art) / name
    if not path.is_file():
        raise ValueError(f"stills item {item.get('key')!r} anchor {name!r} is not in art_dir {art}")
    files["anchors/" + name] = path.read_bytes()
    return "anchors/" + name


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
        items, files = [], {}
        for s in spec["items"]:
            clash = [w for w in STYLE_CONFLICTS if w in s["prompt"].lower()]
            if clash:
                raise ValueError(f"stills prompt {s['key']!r} asks for {clash[0]!r}, which conflicts with "
                                 f"the house style (references/visual-style.md); describe the content only")
            if CANDIDATE_SUFFIX.search(str(s["key"])):
                raise ValueError(f"stills key {s['key']!r} ends like a candidate file (--cN); "
                                 "use candidates instead")
            prompt = s["prompt"].rstrip() + " " + HOUSE_STYLE
            tokens = estimate_t5_tokens(prompt)  # look_first reorders the same tokens
            if tokens > T5_ESTIMATE_LIMIT:
                raise ValueError(f"stills prompt {s['key']!r} (with the house style) is about {tokens} tokens "
                                 f"by the calibrated estimate, over its limit of {T5_ESTIMATE_LIMIT} "
                                 f"(FLUX.1-schnell's T5 cuts at {T5_MAX}): the tail, usually the character "
                                 "lines, would be cut. Shorten the prompt (the house style alone is about "
                                 f"{estimate_t5_tokens(HOUSE_STYLE)} tokens)")
            negative = negative_words(prompt)
            if negative:
                raise ValueError(f"stills prompt {s['key']!r} uses the negative word {negative[0]!r}: "
                                 "FLUX.1-schnell has no negative prompt and draws what it names; "
                                 "describe what is there instead (e.g. 'bare forehead', 'clean-shaven')"
                                 " (references/visual-style.md, Prompt wording)")
            n, seed = _candidates(s), int(s["seed"])
            size = {"width": int(s.get("width", 1024)), "height": int(s.get("height", 1024))}
            anchor = _stills_anchor(spec, s, files)
            extra = {"anchor": anchor} if anchor else {}
            if n == 1:
                items.append({"key": s["key"], "prompt": prompt, "seed": seed, **size, **extra})
                continue
            # one entry per candidate image, so EXPECTED, the deadline and the manifest see each file
            items += [{"key": f"{s['key']}--c{c}", "base": s["key"], "candidate": c,
                       "prompt": prompt, "seed": seed + c - 1, **size, **extra} for c in range(1, n + 1)]
        if not items:
            raise ValueError("no stills requested")
        return {"payload": {"items": items}, "files": files, "repo": STILLS_REPO,
                "revision": "resolved-at-run-time", "steps": STILLS_STEPS, "compute": compute}
    if kind == "music":
        _check_model(kind, spec, MUSIC_REPO)
        for t in spec["items"]:
            if t.get("role") not in (None, "drone", "solo", "phrase"):
                raise ValueError(f"music item {t.get('key')!r} role must be drone, solo or phrase (the cue's stem "
                                 f"families), not {t.get('role')!r}")
        items = [{"key": t["key"], "prompt": t["prompt"], "seed": int(t["seed"]),
                  "duration_s": float(t["duration_s"]),
                  "lyrics": t.get("lyrics", "[instrumental]"), **({"role": t["role"]} if t.get("role") else {})}
                 for t in spec["items"]]
        if not items:
            raise ValueError("no tracks requested")
        return {"payload": {"items": items, **({"scene": spec["scene"]} if spec.get("scene") else {})},
                "repo": MUSIC_REPO,
                "revision": "resolved-at-run-time", "steps": MUSIC_STEPS, "compute": compute}
    if kind == "retouch":
        _check_model(kind, spec, RETOUCH_REPO)
        _check_mask_model(spec)
        items, masks, sources = _retouch_items(record, spec)
        return {"payload": {"items": items, "masks": masks, "mask": dict(RETOUCH_MASK),
                            "mask_model": MASK_REPO, "target": spec["target"]},
                "files": sources, "repo": RETOUCH_REPO, "mask_repo": MASK_REPO,
                "revision": "resolved-at-run-time", "steps": RETOUCH_STEPS, "compute": compute,
                "licences": {"recorded": dict(MODEL_LICENCES), "allowlist": list(LICENCE_ALLOWLIST)}}
    if kind == "film_clips":
        _check_model(kind, spec, FILM_REPO)
        _check_depth_model(spec)
        items = _film_items(spec)
        sfx = _film_sfx(spec)
        files = _film_files(spec, items)
        depth = {n: hashlib.sha256(files[n]).hexdigest() for n in film_depth_stills(spec)}
        return {"payload": {"items": items, "negative_prompt": FILM_NEGATIVE, "steps": FILM_STEPS,
                            "guidance": FILM_GUIDANCE, "frames": FILM_FRAMES, "fps": FILM_FPS,
                            "depth_model": FILM_DEPTH_REPO, **({"sfx": sfx} if sfx else {}),
                            **({"depth_stills": depth} if depth else {}),
                            **({"scene": spec["scene"]} if spec.get("scene") else {})},
                "files": files, "repo": FILM_REPO, "revision": "resolved-at-run-time",
                "steps": FILM_STEPS, "compute": compute, "diffusers": FILM_DIFFUSERS,
                "clip_s": {"hd": rates[kind]["clip_s_hd_a100" if compute["gpu"] == "a100" else "clip_s_hd"],
                           "sd": rates[kind]["clip_s_sd"]},
                "licences": {"recorded": dict(FILM_LICENCES), "allowlist": list(FILM_LICENCE_ALLOWLIST)}}
    if kind == "edit":
        _check_model(kind, spec, EDIT_REPO)
        items, members = _edit_items(record, spec)
        return {"payload": {"items": items, "target": spec["target"], "pipeline": EDIT_PIPELINE},
                "files": members, "repo": EDIT_REPO, "revision": "resolved-at-run-time",
                "steps": compute["steps"], "compute": compute, "diffusers": EDIT_DIFFUSERS,
                "licences": {"recorded": dict(EDIT_LICENCES), "allowlist": list(EDIT_LICENCE_ALLOWLIST)}}
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
    min_vram = min_vram_gib(spec)
    if kind == "film_clips":
        min_vram = film_min_vram(spec)
    if kind == "reel_clips" and min_vram:
        raise ValueError("min_vram_gib applies to the Colab notebook jobs; reel_clips runs on the Wan "
                         "worker's own GPU profile")
    if kind == "reel_clips":
        _check_model(kind, spec, _load_wan_batch().w.MODEL)
        plan = {"compute": derive_compute(kind, spec, rates, job_items(kind, spec))}
        job = _reel_job(spec, job_id, forecast_seconds(plan["compute"], rates), rates[kind])
    else:
        plan = _plan(kind, record, spec, rates)
    if kind == "film_clips" and forecast_seconds(plan["compute"], rates) > FILM_SESSION_S:
        raise ValueError(f"this film_clips job needs about {forecast_seconds(plan['compute'], rates):.0f} s, over one "
                         f"Colab session ({FILM_SESSION_S} s, the notebook's hard stop): split it "
                         "(split_film_spec; `job film_clips` splits a scene's spec itself)")
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
                                            forecast_seconds(plan["compute"], rates), min_vram)
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


def resume_notebook(notebook: Path, out: Path, deadline_s: float, resume_id: str, keys: list) -> Path:
    """A copy of a film_clips notebook for a resumed session of the SAME job (same job id, inputs.zip and Drive
    folder, so done.json skips the finished clips): only its hard stop is re-armed, at `deadline_s`, the seconds the
    resume ledger entry `resume_id` reserved for the remaining `keys`."""
    nb = json.loads(Path(notebook).read_text(encoding="utf-8"))
    hit = 0
    for cell in nb["cells"]:
        src = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        new = re.sub(r"^DEADLINE_SECONDS = \d+$", f"DEADLINE_SECONDS = {int(deadline_s)}", src, flags=re.M)
        if cell["cell_type"] == "markdown" and "**Hard stop:**" in new:
            new = re.sub(r"\*\*Hard stop:\*\* \d+ s", f"**Hard stop:** {int(deadline_s)} s", new)
            new += (f"\n**Resumed session `{resume_id}`:** run this notebook only after the first session stopped; the "
                    f"Drive folder's done.json skips every finished clip. It may make: {', '.join(keys)}.\n")
        hit += new != src
        cell["source"] = new.splitlines(keepends=True)
    if not hit:
        raise ValueError(f"{notebook} has no DEADLINE_SECONDS to re-arm")
    Path(out).write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return Path(out)


def _write_notebook_bundle(kind, plan, job_id, title, job_dir: Path, deadline_s: float,
                           min_vram: int = 0) -> dict:
    job_json = {"schema": JOB_SCHEMA, "kind": kind, "job_id": job_id, "title": title,
                "model": plan["repo"], **plan["payload"]}
    archive = _zip_bytes({"job.json": (json.dumps(job_json, indent=2, sort_keys=True)
                                       + "\n").encode("utf-8"), **plan.get("files", {})})
    zip_sha = hashlib.sha256(archive).hexdigest()
    nb = _notebook(kind, job_id, title, zip_sha, plan["repo"], plan["revision"],
                   plan["steps"], _TEMPLATES / f"{kind}_cell.py.txt", deadline_s, min_vram, plan.get("clip_s"),
                   sfx=bool(plan["payload"].get("sfx")))
    manifest = {"schema": "earnalism.audiovisual-build.v1", "job_id": job_id, "kind": kind,
                "title": title, "inputs_sha256": zip_sha,
                "notebook_sha256": hashlib.sha256(nb).hexdigest(),
                "model": {"repo": plan["repo"], "revision": plan["revision"]},
                "drive_dir": f"{DRIVE_ROOT}/{title}/{job_id}",
                "deadline_seconds": int(deadline_s), "min_vram_gib": min_vram,
                "authority_created": False}
    if "generation" in plan["payload"]:
        manifest["generation"] = plan["payload"]["generation"]
    if "mask_repo" in plan:
        manifest["mask_model"] = {"repo": plan["mask_repo"], "revision": "resolved-at-run-time"}
    if "licences" in plan:
        manifest["licences"] = plan["licences"]
    if "diffusers" in plan:
        manifest["diffusers"] = plan["diffusers"]
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
