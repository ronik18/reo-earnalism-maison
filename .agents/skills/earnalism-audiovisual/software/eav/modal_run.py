"""Run a built narration/stills/music notebook headlessly (on a Modal GPU, or locally as a dry run).

The notebook is the single source of truth: this module executes the notebook's own code cells
(everything after the inert `RUN = False` cell) in one shared namespace with `RUN = True`, with a
tiny `google.colab` shim installed so the Drive-mount and runtime-unassign calls work unchanged.
The job folder it leaves behind is exactly what Colab would have written to Drive, so the
unchanged `eav import` accepts it. Nothing here touches the ledger, a record or any secret;
Modal authentication comes from the environment the `modal` client reads.
"""
import ast
import json
import sys
import time
import types
from pathlib import Path

# Modal's published L4 rate (about $0.80 per hour). The CPU and memory surcharges are not
# modelled, so the figure is a floor on the real bill, not the bill itself.
L4_USD_PER_S = 0.000222
APP_NAME = "earnalism-eav"
VOLUME_NAME = "earnalism-eav-jobs"
VOLUME_MOUNT = "/jobs"
TIMEOUT_MARGIN_S = 900  # setup, pip and model download; the notebook's own clock bounds compute
RUNNABLE_KINDS = ("narration", "stills", "music")
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


def colab_shim(job_dir: str) -> str:
    """Source of a `google.colab` stand-in. `drive.mount(path)` only records the path (the Drive
    folder is job_dir, applied by `run_cells` right after the config cell); `runtime.unassign()`
    flushes and raises SystemExit, as unassigning a Colab runtime ends the notebook."""
    return f'''import sys
JOB_DIR = {str(job_dir)!r}


class drive:
    mounted = []

    @staticmethod
    def mount(path, *args, **kwargs):
        drive.mounted.append(path)


class runtime:
    @staticmethod
    def unassign():
        sys.stdout.flush()
        sys.stderr.flush()
        raise SystemExit("runtime unassigned")
'''


class _Shim:
    """Install the shim as google / google.colab for the duration of a run, then restore."""

    def __init__(self, job_dir):
        self.job_dir, self.saved = job_dir, {}

    def __enter__(self):
        mod = types.ModuleType("google.colab")
        exec(compile(colab_shim(self.job_dir), "<colab_shim>", "exec"), mod.__dict__)
        pkg = sys.modules.get("google") or types.ModuleType("google")
        if not hasattr(pkg, "__path__"):
            pkg.__path__ = []
        for name, value in (("google", pkg), ("google.colab", mod)):
            self.saved[name] = sys.modules.get(name)
            sys.modules[name] = value
        return mod

    def __exit__(self, *exc):
        for name, old in self.saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def run_cells(cells: list, job_dir) -> dict:
    """Execute the cells in one shared namespace with RUN = True; DRIVE_JOB_DIR is overridden
    right after the config cell. A SystemExit (runtime.unassign) ends the run quietly; any other
    exception propagates. Returns the namespace."""
    job_dir = str(job_dir)
    Path(job_dir).mkdir(parents=True, exist_ok=True)
    g = {"__name__": "__main__", "RUN": True}
    with _Shim(job_dir):
        try:
            for i, source in enumerate(cells):
                exec(compile(source, f"<eav cell {i}>", "exec"), g)
                if i == 0:
                    g["DRIVE_JOB_DIR"] = job_dir
        except SystemExit:
            pass
        finally:
            guard = g.get("STOP_GUARD")
            if guard is not None:
                guard.cancel()
            sys.stdout.flush()
    return g


def _prepare(notebook, inputs_zip):
    cells = extract_cells(notebook)
    return cells, read_config(cells[0]), Path(inputs_zip).read_bytes()


def run_local(notebook, inputs_zip, work_dir) -> dict:
    """The executor in-process (dry run / tests): work_dir/<job_id>/ gets inputs.zip, the
    notebook's outputs and manifest.json. A rerun resumes in the same folder."""
    cells, config, archive = _prepare(notebook, inputs_zip)
    folder = Path(work_dir) / config["JOB_ID"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "inputs.zip").write_bytes(archive)
    started = time.monotonic()
    run_cells(cells, folder)
    return {"seconds": time.monotonic() - started, "folder": folder}


def modal_cost(seconds: float) -> float:
    """USD for the measured seconds at the published L4 rate (no CPU/memory surcharge)."""
    return seconds * L4_USD_PER_S


def execute_remote(cells: list, job_id: str, archive: bytes, volume_mount: str = VOLUME_MOUNT) -> None:
    """Runs inside the Modal container: write inputs.zip into the volume folder, run the cells."""
    folder = Path(volume_mount) / job_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "inputs.zip").write_bytes(archive)
    run_cells(cells, folder)


def run_modal(notebook, inputs_zip, download_dir, gpu="L4") -> dict:
    """Run the notebook on a Modal GPU, then download the job folder to download_dir/<job_id>/.

    Returns {"seconds": measured wall seconds of the remote call (cold start included),
    "usd": seconds * L4_USD_PER_S, "folder": the download folder}. The cost is the L4 rate only;
    Modal's CPU and memory surcharges are not modelled. The folder lives on the persistent
    volume `earnalism-eav-jobs` at /jobs/<job_id>, so rerunning the same job resumes from it.
    The function timeout is DEADLINE_SECONDS + 900 s; the notebook's own clock enforces the
    reserved compute seconds. Needs modal installed and authenticated; it is imported here,
    never at module top level."""
    cells, config, archive = _prepare(notebook, inputs_zip)
    job_id, deadline = config["JOB_ID"], int(config["DEADLINE_SECONDS"])
    import modal  # optional dependency, only needed to launch

    app = modal.App(APP_NAME)
    image = (modal.Image.debian_slim(python_version="3.11")
             .apt_install("git", "ffmpeg", "libsndfile1")  # git: the cells pip-install from GitHub
             .pip_install("torch", "soundfile", "huggingface_hub")
             .env({"HF_HOME": f"{VOLUME_MOUNT}/hf-cache"})
             .add_local_python_source("eav"))
    volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

    @app.function(image=image, gpu=gpu, volumes={VOLUME_MOUNT: volume},
                  timeout=deadline + TIMEOUT_MARGIN_S, serialized=True)
    def remote(cells_, job_id_, archive_):
        from eav.modal_run import execute_remote
        try:
            execute_remote(cells_, job_id_, archive_)
        finally:
            volume.commit()

    started = time.monotonic()
    with app.run():
        remote.remote(cells, job_id, archive)
    seconds = time.monotonic() - started
    dest = Path(download_dir) / job_id
    dest.mkdir(parents=True, exist_ok=True)
    for entry in volume.listdir(f"/{job_id}", recursive=True):
        if getattr(entry.type, "name", str(entry.type)).upper() != "FILE":
            continue
        target = dest / Path(entry.path).relative_to(job_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as fh:
            for chunk in volume.read_file(entry.path):
                fh.write(chunk)
    return {"seconds": seconds, "usd": modal_cost(seconds), "folder": dest}
