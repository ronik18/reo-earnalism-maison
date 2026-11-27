"""Run a built narration/stills/music notebook headlessly (on a Modal GPU, or locally as a dry run).

The notebook is the single source of truth: this module executes the notebook's own code cells
(everything after the inert `RUN = False` cell) in one shared namespace with `RUN = True`, with a
tiny `google.colab` shim installed so the Drive-mount and runtime-unassign calls work unchanged.
The job folder it leaves behind is exactly what Colab would have written to Drive, so the
unchanged `eav import` accepts it. Nothing here touches the ledger, a record or any secret;
Modal authentication comes from the environment the `modal` client reads.
"""
import ast
import hashlib
import json
import os
import shutil
import _thread
import sys
import tempfile
import threading
import time
import types
from pathlib import Path, PurePosixPath

# One Modal GPU per job kind: narration and music fit an L4 (24 GB, ~22 GB usable); stills need an
# L40S (48 GB) because the FLUX.1-schnell transformer alone is ~24 GB in bf16 (an L4 ran out of memory).
GPU_FOR_KIND = {"narration": "L4", "music": "L4", "stills": "L40S"}
# Modal's published per-second GPU rates (Oct-Nov 2026). CPU and memory are billed on top; they are
# covered by MODAL_OVERHEAD_FACTOR, not listed here.
USD_PER_S = {"L4": 0.000222, "L40S": 0.000542}
# Every Modal figure (the pending worst case and the recorded spend) is wall seconds x the job
# kind's GPU rate x this factor: it covers the CPU and memory surcharges and the image build that the
# GPU rate leaves out. It stays an estimate: `eav modal-settle` replaces a row with the billed amount.
MODAL_OVERHEAD_FACTOR = 1.25
APP_NAME = "earnalism-eav"
VOLUME_NAME = "earnalism-eav-jobs"
VOLUME_MOUNT = "/jobs"
TIMEOUT_MARGIN_S = 900  # setup, pip and model download; the notebook's own clock bounds compute
# Image build and GPU queue before the function starts (not bounded by its timeout): used only to
# decide whether a run may still be going in the next UTC month (both months' caps are checked).
STARTUP_ALLOWANCE_S = 1800
RUNNABLE_KINDS = ("narration", "stills", "music")
# Hugging Face repos that need an accepted-terms read token; modal-run refuses them without HF_TOKEN.
GATED_REPOS = {"ai4bharat/indic-parler-tts"}
HF_NOTE = "note: HF_TOKEN not set; gated models will fail"
CONFIG_NAMES = ("JOB_ID", "KIND", "INPUT_ZIP_SHA256", "DEADLINE_SECONDS", "DRIVE_JOB_DIR")


def _code_cells(notebook_path) -> list:
    try:
        nb = json.loads(Path(notebook_path).read_text(encoding="utf-8"))
        return ["".join(c["source"]) if isinstance(c["source"], list) else str(c["source"])
                for c in nb["cells"] if c["cell_type"] == "code"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"not a readable notebook: {notebook_path}: {e}") from None


def read_config(cell_source: str) -> dict:
    """The literal NAME = value assignments of the config cell."""
    try:
        tree = ast.parse(cell_source)
    except SyntaxError as e:
        raise ValueError(f"config cell does not parse: {e}") from None
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def extract_cells(notebook_path) -> list:
    """The notebook's code cells in order, without the first `RUN = False` cell.

    ValueError for a reel_clips notebook or any notebook whose structure differs from the
    colab_jobs builder (first code cell `RUN = False`, then a config cell defining JOB_ID, KIND,
    INPUT_ZIP_SHA256, DEADLINE_SECONDS and DRIVE_JOB_DIR)."""
    code = _code_cells(notebook_path)
    if len(code) < 3 or code[0].strip() != "RUN = False":
        raise ValueError("not an eav job notebook: the first code cell must be `RUN = False`")
    cells = code[1:]
    config = read_config(cells[0])
    if config.get("KIND") == "reel_clips":
        raise ValueError("reel_clips notebooks cannot run here (they need the Wan worker)")
    missing = [n for n in CONFIG_NAMES if n not in config]
    if missing:
        raise ValueError("config cell does not define " + ", ".join(missing))
    if config["KIND"] not in RUNNABLE_KINDS:
        raise ValueError(f"unsupported job kind: {config['KIND']!r}")
    deadline = config["DEADLINE_SECONDS"]
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or deadline <= 0:
        raise ValueError("config cell DEADLINE_SECONDS is not a positive number")
    return cells


def gated_model_repo(notebook_path):
    """The notebook's MODEL_REPO if it is one of GATED_REPOS, else None."""
    cells = _code_cells(notebook_path)
    config = read_config(cells[1]) if len(cells) > 1 else {}
    repo = config.get("MODEL_REPO")
    return repo if repo in GATED_REPOS else None


def colab_shim(job_dir: str) -> str:
    """Source of a `google.colab` stand-in. `drive.mount(path)` only records the path (the Drive
    folder is job_dir, applied by `run_cells` right after the config cell); `runtime.unassign()`
    flushes and stops the main execution from any thread (flag plus interrupt_main), as
    unassigning a Colab runtime ends the notebook."""
    return f'''import sys
import threading
import _thread
JOB_DIR = {str(job_dir)!r}


class drive:
    mounted = []

    @staticmethod
    def mount(path, *args, **kwargs):
        drive.mounted.append(path)


class runtime:
    stopped = False
    closed = False  # set by the executor once the cells are over: a later stop does nothing
    lock = threading.Lock()
    interrupted = threading.Event()  # the main thread has been sent its interrupt
    on_stop = None  # set by the executor: on Modal, commit the volume before anything else

    @staticmethod
    def unassign():
        """The hard stop. The notebook calls it from a Timer thread, where SystemExit would only
        end that thread, so also interrupt the main thread that is running the cells."""
        with runtime.lock:
            if runtime.closed:  # every cell already ran (or failed): nothing is left to stop
                return
            runtime.stopped = True
        sys.stdout.flush()
        sys.stderr.flush()
        if runtime.on_stop is not None:
            try:
                runtime.on_stop()
            except Exception as e:  # the stop itself must still happen
                print(f"hard stop: on_stop failed: {{type(e).__name__}}: {{e}}", file=sys.stderr)
        if threading.current_thread() is not threading.main_thread():
            _thread.interrupt_main()
            runtime.interrupted.set()
            return
        runtime.interrupted.set()
        raise SystemExit("runtime unassigned")
'''


class _Shim:
    """Install the shim as google / google.colab for the duration of a run, then restore."""

    def __init__(self, job_dir):
        self.job_dir, self.saved = job_dir, {}

    def __enter__(self):
        import importlib.machinery
        mod = types.ModuleType("google.colab")
        # Libraries such as transformers probe importlib.util.find_spec("google.colab"); a module in
        # sys.modules with __spec__ None makes that raise ValueError, so give the shim a real spec.
        mod.__spec__ = importlib.machinery.ModuleSpec("google.colab", None)
        exec(compile(colab_shim(self.job_dir), "<colab_shim>", "exec"), mod.__dict__)
        pkg = sys.modules.get("google") or types.ModuleType("google")
        if not hasattr(pkg, "__path__"):
            pkg.__path__ = []
        if getattr(pkg, "__spec__", None) is None:
            pkg.__spec__ = importlib.machinery.ModuleSpec("google", None, is_package=True)
        for name, value in (("google", pkg), ("google.colab", mod)):
            self.saved[name] = sys.modules.get(name)
            sys.modules[name] = value
        self.runtime = mod.runtime
        return mod

    def __exit__(self, *exc):
        for name, old in self.saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


INTERRUPT_WAIT_S = 5.0  # how long the executor waits for a stop's interrupt to reach it


def run_cells(cells: list, job_dir, on_stop=None) -> dict:
    """Execute the cells in one shared namespace with RUN = True; DRIVE_JOB_DIR is overridden
    right after the config cell. runtime.unassign() (from any thread) is the hard stop: it calls
    on_stop first (if given), then no later cell runs (so no manifest is written; the stop flag is
    also checked before each cell) and the namespace has HARD_STOPPED = True. A stop that fires
    only after the last cell finished is absorbed here (the run is complete, HARD_STOPPED False),
    never surfacing later as a KeyboardInterrupt. Any other exception propagates. Returns the
    namespace."""
    job_dir = str(job_dir)
    Path(job_dir).mkdir(parents=True, exist_ok=True)
    g = {"__name__": "__main__", "RUN": True, "HARD_STOPPED": False}
    finished = False
    with _Shim(job_dir) as shim:
        rt = shim.runtime
        rt.on_stop = on_stop
        try:
            try:
                for i, source in enumerate(cells):
                    if rt.stopped:  # the stop fired between cells: no later cell starts
                        raise SystemExit("runtime unassigned")
                    exec(compile(source, f"<eav cell {i}>", "exec"), g)
                    if i == 0:
                        g["DRIVE_JOB_DIR"] = job_dir
                finished = True
            finally:
                guard = g.get("STOP_GUARD")
                if guard is not None:
                    guard.cancel()
                with rt.lock:  # from here a stop does nothing; one already under way is awaited
                    rt.closed = True
                    stopping = rt.stopped
                if stopping:  # take its interrupt here, inside this try, never after it
                    rt.interrupted.wait(INTERRUPT_WAIT_S)
                    for _ in range(10):
                        time.sleep(0.01)
                sys.stdout.flush()
        except (SystemExit, KeyboardInterrupt):
            if not rt.stopped:
                raise  # a real Ctrl-C or sys.exit in a cell, not the hard stop
        g["HARD_STOPPED"] = rt.stopped and not finished
    return g


def _prepare(notebook, inputs_zip, expected_sha256=None):
    """(cells, config, inputs.zip bytes). With expected_sha256 the bytes that will be sent are the
    ones checked (one read, so the file cannot change between the check and the run)."""
    cells = extract_cells(notebook)
    archive = Path(inputs_zip).read_bytes()
    if expected_sha256 is not None and hashlib.sha256(archive).hexdigest() != expected_sha256:
        raise ValueError(f"{inputs_zip} does not match its build manifest (sha256)")
    return cells, read_config(cells[0]), archive


def run_local(notebook, inputs_zip, work_dir) -> dict:
    """The executor in-process (dry run / tests): work_dir/<job_id>/ gets inputs.zip, the
    notebook's outputs and manifest.json. A rerun resumes in the same folder."""
    cells, config, archive = _prepare(notebook, inputs_zip)
    folder = Path(work_dir) / config["JOB_ID"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "inputs.zip").write_bytes(archive)
    started = time.monotonic()
    g = run_cells(cells, folder)
    return {"seconds": time.monotonic() - started, "folder": folder,
            "hard_stopped": g["HARD_STOPPED"]}


def gpu_for_kind(kind) -> str:
    """The Modal GPU for a job kind; an unknown kind is refused."""
    if kind not in GPU_FOR_KIND:
        raise ValueError(f"no Modal GPU for job kind {kind!r}; expected one of {sorted(GPU_FOR_KIND)}")
    return GPU_FOR_KIND[kind]


def modal_cost(seconds: float, gpu: str) -> float:
    """Estimated USD for wall seconds on a GPU: its per-second rate x MODAL_OVERHEAD_FACTOR
    (CPU, memory, build)."""
    if gpu not in USD_PER_S:
        raise ValueError(f"no Modal rate for GPU {gpu!r}; expected one of {sorted(USD_PER_S)}")
    return seconds * USD_PER_S[gpu] * MODAL_OVERHEAD_FACTOR


def remote_python_version() -> str:
    """The image must run the local minor version: the function is cloudpickled (serialized)."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def plan(notebook, inputs_zip) -> dict:
    """What run_modal would do, computed offline: nothing is executed or contacted."""
    cells, config, _ = _prepare(notebook, inputs_zip)
    deadline = int(config["DEADLINE_SECONDS"])
    gpu = gpu_for_kind(config["KIND"])
    return {"job_id": config["JOB_ID"], "kind": config["KIND"], "cells": len(cells),
            "gpu": gpu, "app": APP_NAME, "python_version": remote_python_version(),
            "timeout_seconds": deadline + TIMEOUT_MARGIN_S,
            "volume": f"{VOLUME_NAME}:{VOLUME_MOUNT}/{config['JOB_ID']}",
            "forecast_seconds": deadline, "forecast_usd": modal_cost(deadline, gpu)}


def execute_remote(cells: list, job_id: str, archive: bytes, volume_mount: str = VOLUME_MOUNT,
                   commit=None) -> dict:
    """Runs inside the Modal container: write inputs.zip into the volume folder, run the cells.
    commit (the volume's commit, looked up inside the container) runs at the hard stop, before the
    main thread is interrupted, and again at the end, whatever happened."""
    folder = Path(volume_mount) / job_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "inputs.zip").write_bytes(archive)
    try:
        g = run_cells(cells, folder, on_stop=commit)
    finally:
        if commit is not None:
            commit()
    return {"hard_stopped": g["HARD_STOPPED"]}


def _commit_volume():
    """Inside the container: commit the job volume, looked up by name (no captured handle)."""
    import modal
    modal.Volume.from_name(VOLUME_NAME).commit()


def volume_relpath(path: str, job_id: str):
    """A volume listdir path, with or without a leading "/", relative to the job folder (posix);
    ValueError if it is outside it or climbs out."""
    rel = PurePosixPath(str(path).lstrip("/"))
    rel = rel.relative_to(job_id)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError(f"volume path {path!r} is not a file inside {job_id}/")
    return rel


def _download(volume, job_id, dest: Path) -> None:
    """The volume's job folder into dest, exactly: it lands in a fresh sibling folder first and then
    replaces dest, so a file an earlier download left there (and the volume no longer holds) never
    stays behind to make `import` refuse an "extra" file. A failed download still leaves what it
    got (for inspection) and re-raises."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=f".{dest.name}-"))
    try:
        try:
            for entry in list(volume.listdir(f"/{job_id}", recursive=True)):
                if getattr(entry.type, "name", str(entry.type)).upper() != "FILE":
                    continue
                target = tmp / volume_relpath(entry.path, job_id)
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "wb") as fh:
                    for chunk in volume.read_file(entry.path):
                        fh.write(chunk)
        finally:  # this run's files, complete or not, replace whatever an earlier download left
            if dest.exists():
                shutil.rmtree(dest)
            os.replace(tmp, dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def run_modal(notebook, inputs_zip, download_dir, on_contact=None,
              expected_sha256=None) -> dict:
    """Run the notebook on a Modal GPU, then download the job folder to download_dir/<job_id>/.

    Returns {"seconds": wall seconds measured locally around the remote call (cold start
    included), "usd": modal_cost(seconds, gpu), "folder", "status": "ok" | "hard_stopped" |
    "failed", "error": text or None}. A failed or timed-out remote call still returns (it was
    paid for) and still downloads whatever the volume holds. The cost is an estimate (modal_cost:
    the job kind's GPU rate x MODAL_OVERHEAD_FACTOR; GPU_FOR_KIND picks the GPU). on_contact() is called once, immediately before Modal
    is first contacted (the workflow records modal_contacted_at). The folder lives on the persistent volume
    `earnalism-eav-jobs` at /jobs/<job_id>, so rerunning the same job resumes from it. The
    HF_TOKEN, if set in the launching environment, is attached as an in-memory Modal secret
    (HF_TOKEN and HUGGING_FACE_HUB_TOKEN). The
    function timeout is DEADLINE_SECONDS + 900 s; the notebook's own clock enforces the reserved
    compute seconds. The image's Python equals the local minor version (serialized function).
    Needs modal installed and authenticated; it is imported here, never at module top level.
    expected_sha256 (the build manifest's inputs_sha256): the bytes sent are the bytes checked.
    The download replaces download_dir/<job_id>/ with exactly what the volume holds."""
    cells, config, archive = _prepare(notebook, inputs_zip, expected_sha256)
    job_id, deadline = config["JOB_ID"], int(config["DEADLINE_SECONDS"])
    gpu = gpu_for_kind(config["KIND"])
    import modal  # optional dependency, only needed to launch

    token = os.environ.get("HF_TOKEN") or ""
    secrets = []
    if token:  # built in memory from the launching environment; never written, printed or returned
        secrets = [modal.Secret.from_dict({"HF_TOKEN": token, "HUGGING_FACE_HUB_TOKEN": token})]
    else:
        print(HF_NOTE, file=sys.stderr)
    app = modal.App(APP_NAME)
    image = (modal.Image.debian_slim(python_version=remote_python_version())
             .apt_install("git", "ffmpeg", "libsndfile1")  # git: the cells pip-install from GitHub
             .pip_install("torch", "soundfile", "huggingface_hub")
             .env({"HF_HOME": f"{VOLUME_MOUNT}/hf-cache"})
             .add_local_python_source("eav"))
    volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

    @app.function(image=image, gpu=gpu, volumes={VOLUME_MOUNT: volume},
                  timeout=deadline + TIMEOUT_MARGIN_S, serialized=True,
                  secrets=secrets)
    def remote(cells_, job_id_, archive_):
        from eav.modal_run import _commit_volume, execute_remote
        return execute_remote(cells_, job_id_, archive_, commit=_commit_volume)

    if on_contact is not None:
        on_contact()
    status, error, outcome = "ok", None, {}
    started = time.monotonic()
    try:
        with app.run():
            outcome = remote.remote(cells, job_id, archive) or {}
    except Exception as e:  # remote failure or timeout: the seconds were still billed
        status, error = "failed", f"{type(e).__name__}: {e}"
    seconds = time.monotonic() - started
    if status == "ok" and outcome.get("hard_stopped"):
        status = "hard_stopped"
    dest = Path(download_dir) / job_id
    try:
        _download(volume, job_id, dest)
    except Exception as e:
        status = "failed"
        error = (error + "; " if error else "") + f"download: {type(e).__name__}: {e}"
        dest.mkdir(parents=True, exist_ok=True)
    if token and error:  # no error text (remote call or download) ever carries the token
        error = error.replace(token, "***")
    return {"seconds": seconds, "usd": modal_cost(seconds, gpu), "folder": dest,
            "status": status, "error": error}
