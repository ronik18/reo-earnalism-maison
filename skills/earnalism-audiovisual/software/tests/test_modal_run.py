"""modal-run: cell extraction, the headless executor with fake models, the CLI dry run, the cost."""
import contextlib
import io
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from eav import cli, colab_jobs, importer, modal_run
from eav.budget import Ledger
from eav.record import Record

RATES = {k: {"s_per_step": 100.0, "units_per_hour": 10.0, "decode_s": 30, "export_s": 20}
         for k in ("narration", "stills", "music")}
PRESET = {"description": "A calm warm female voice, very clear, close to the microphone."}
SCENE = {"scene_id": "s01", "text": "The morning was quiet. Rain fell on the roof."}
COMPUTE = {"steps": 1, "items": 2, "takes": 1, "decode_s": 30, "export_s": 20}


class _Arr:
    def cpu(self): return self
    def numpy(self): return self
    def squeeze(self): return self
    def astype(self, _): return b"fake-audio"


class _Tok:
    def __init__(self, *a, **k): pass
    @classmethod
    def from_pretrained(cls, *a, **k): return cls()
    def __call__(self, text, return_tensors=None):
        return types.SimpleNamespace(input_ids=1, attention_mask=1, to=lambda dev: types.SimpleNamespace(
            input_ids=1, attention_mask=1))


class _Model:
    config = types.SimpleNamespace(sampling_rate=24000,
                                   text_encoder=types.SimpleNamespace(_name_or_path="fake-t5"))
    @classmethod
    def from_pretrained(cls, *a, **k): return cls()
    def to(self, device): return self
    def generate(self, **k): return _Arr()


def fake_modules():
    sf = types.ModuleType("soundfile")
    sf.write = lambda path, wav, rate: Path(path).write_bytes(b"RIFF" + bytes(wav) + str(rate).encode())
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    parler = types.ModuleType("parler_tts")
    parler.ParlerTTSForConditionalGeneration = _Model
    tf = types.ModuleType("transformers")
    tf.AutoTokenizer = _Tok
    return {"soundfile": sf, "torch": torch, "parler_tts": parler, "transformers": tf}


@contextlib.contextmanager
def fakes():
    dist = mock.Mock(version="1.0", read_text=lambda name: None)
    with mock.patch.dict(sys.modules, fake_modules()), \
            mock.patch("subprocess.run") as pip, \
            mock.patch("importlib.metadata.distribution", return_value=dist):
        yield pip


class FakeModal:
    """Just enough of the modal client for run_modal: the 'remote' runs behavior(...) in-process
    against a directory standing in for the volume."""

    def __init__(self, vroot, behavior=None):
        self.vroot, self.behavior = Path(vroot), behavior or self.default
        self.image_python, self.function_kwargs = None, {}

    @staticmethod
    def default(vroot, cells, job_id, archive):
        return modal_run.execute_remote(cells, job_id, archive, volume_mount=str(vroot))

    def module(self):
        fm = self
        mod = types.ModuleType("modal")

        class Image:
            @staticmethod
            def debian_slim(python_version=None):
                fm.image_python = python_version
                return Image()
            def apt_install(self, *a): return self
            def pip_install(self, *a): return self
            def env(self, *a): return self
            def add_local_python_source(self, *a): return self

        class Entry:
            def __init__(self, path):
                self.path, self.type = path, types.SimpleNamespace(name="FILE")

        class Volume:
            @staticmethod
            def from_name(name, create_if_missing=False):
                return Volume()
            def commit(self): pass
            def listdir(self, path, recursive=False):
                base = fm.vroot / path.strip("/")
                if not base.is_dir():
                    raise FileNotFoundError(path)
                return [Entry(p.relative_to(fm.vroot).as_posix()) for p in sorted(base.rglob("*"))
                        if p.is_file()]
            def read_file(self, path):
                yield (fm.vroot / path).read_bytes()

        class App:
            def __init__(self, name): pass
            def function(self, **kw):
                fm.function_kwargs = kw
                def deco(fn):
                    return types.SimpleNamespace(remote=lambda c, j, a: fm.behavior(fm.vroot, c, j, a))
                return deco
            @contextlib.contextmanager
            def run(self):
                yield

        mod.Image, mod.Volume, mod.App = Image, Volume, App
        return mod


class ModalRunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.record = Record.create(self.root / "rec", "garden-book", {"x": 1})
        self.ledger = Ledger(self.root / "ledger.json")
        self.out = self.root / "rec" / "jobs"
        self.out.mkdir()

    def build(self, kind="narration", spec=None):
        spec = spec or {"scenes": [SCENE], "preset": PRESET, "compute": COMPUTE}
        return colab_jobs.build_job(kind, self.record, spec, self.ledger, RATES, self.out,
                                    month="2026-11")

    def test_extract_cells_drops_only_the_run_false_cell(self):
        job = self.build()
        nb = json.loads(Path(job["notebook"]).read_text())
        code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
        cells = modal_run.extract_cells(job["notebook"])
        self.assertEqual(cells, code[1:])
        self.assertEqual(len(cells), 5)
        self.assertNotIn("RUN = False", cells)

    def test_extract_cells_refuses_malformed_notebooks(self):
        job = self.build()
        nb = json.loads(Path(job["notebook"]).read_text())

        def refuse(mutate, pattern):
            bad = json.loads(json.dumps(nb))
            mutate(bad)
            p = self.root / "bad.ipynb"
            p.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, pattern):
                modal_run.extract_cells(p)

        code_idx = [i for i, c in enumerate(nb["cells"]) if c["cell_type"] == "code"]
        refuse(lambda b: b["cells"][code_idx[0]].update(source=["RUN = True"]), "RUN = False")
        refuse(lambda b: b["cells"][code_idx[1]].update(
            source=[l for l in b["cells"][code_idx[1]]["source"] if "DEADLINE_SECONDS = " not in l]),
            "DEADLINE_SECONDS")
        refuse(lambda b: b["cells"][code_idx[1]].update(
            source=[l.replace("KIND = 'narration'", "KIND = 'reel_clips'")
                    for l in b["cells"][code_idx[1]]["source"]]), "reel_clips")
        refuse(lambda b: b.pop("cells"), "not a readable notebook")
        p = self.root / "garbage.ipynb"
        p.write_text("not json")
        with self.assertRaises(ValueError):
            modal_run.extract_cells(p)

    def test_shim_unassign_exits_and_drive_mount_records(self):
        ns = {}
        exec(modal_run.colab_shim("/jobs/x"), ns)
        ns["drive"].mount("/content/drive")
        self.assertEqual(ns["drive"].mounted, ["/content/drive"])
        with self.assertRaises(SystemExit):
            ns["runtime"].unassign()

    def test_run_local_produces_complete_importable_folder(self):
        job = self.build()
        work = self.root / "work"
        with fakes() as pip:
            result = modal_run.run_local(job["notebook"], job["inputs_zip"], work)
        self.assertTrue(pip.called)
        folder = result["folder"]
        self.assertEqual(folder, work / job["job_id"])
        self.assertGreaterEqual(result["seconds"], 0)
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "COMPLETE")
        self.assertEqual(len(manifest["outputs"]), 2)
        self.assertNotIn("google.colab", sys.modules)  # shim removed afterwards
        arts = importer.import_job(self.record, {
            "job_id": job["job_id"], "kind": "narration", "notebook": job["notebook"],
            "inputs_zip": job["inputs_zip"], "manifest": job["manifest"]},
            folder, self.ledger, 0.5)
        self.assertEqual(len(arts), 2)

    def test_unassign_mid_run_leaves_folder_and_no_manifest(self):
        job = self.build()
        cells = modal_run.extract_cells(job["notebook"])
        cells.insert(3, "from google.colab import runtime\nruntime.unassign()")
        folder = self.root / "stopped"
        folder.mkdir()
        (folder / "inputs.zip").write_bytes(Path(job["inputs_zip"]).read_bytes())
        with fakes():
            g = modal_run.run_cells(cells, folder)
        self.assertFalse((folder / "manifest.json").exists())
        self.assertTrue(g["HARD_STOPPED"])

    def test_timer_thread_unassign_stops_the_main_execution(self):
        """C1: colab_jobs fires unassign() from a Timer thread; no later cell may run."""
        folder = self.root / "timer"
        cells = ["JOB_ID = 'x'",
                 "import threading, time\nfrom google.colab import runtime\n"
                 "threading.Timer(0.2, runtime.unassign).start()\n"
                 "for _ in range(200):\n    time.sleep(0.05)\nREACHED_END_OF_LONG_CELL = True",
                 "open(DRIVE_JOB_DIR + '/later.txt', 'w').write('ran')"]
        started = time.monotonic()
        g = modal_run.run_cells(cells, folder)
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(g["HARD_STOPPED"])
        self.assertNotIn("REACHED_END_OF_LONG_CELL", g)
        self.assertFalse((folder / "later.txt").exists())

    def test_real_keyboard_interrupt_is_not_swallowed(self):
        with self.assertRaises(KeyboardInterrupt):
            modal_run.run_cells(["JOB_ID = 'x'", "raise KeyboardInterrupt()"], self.root / "ki")

    def test_remote_python_matches_local_interpreter(self):
        self.assertEqual(modal_run.remote_python_version(),
                         f"{sys.version_info.major}.{sys.version_info.minor}")

    def test_run_modal_with_fake_modal(self):
        job = self.build()
        fm = FakeModal(self.root / "vol")
        with fakes(), mock.patch.dict(sys.modules, {"modal": fm.module()}):
            result = modal_run.run_modal(job["notebook"], job["inputs_zip"], self.root / "dl")
        self.assertEqual(fm.image_python, modal_run.remote_python_version())
        self.assertEqual(fm.function_kwargs["timeout"],
                         modal_run.plan(job["notebook"], job["inputs_zip"])["timeout_seconds"])
        self.assertEqual(fm.function_kwargs["gpu"], "L4")
        self.assertEqual(result["status"], "ok")
        self.assertTrue((result["folder"] / "inputs.zip").is_file())

    def test_run_modal_failure_still_reports_cost_and_downloads_partial(self):
        job = self.build()

        def behavior(vroot, cells, job_id, archive):
            (vroot / job_id).mkdir(parents=True)
            (vroot / job_id / "partial.wav").write_bytes(b"x")
            raise RuntimeError("function timed out")

        fm = FakeModal(self.root / "vol", behavior)
        with mock.patch.dict(sys.modules, {"modal": fm.module()}):
            result = modal_run.run_modal(job["notebook"], job["inputs_zip"], self.root / "dl")
        self.assertEqual(result["status"], "failed")
        self.assertIn("function timed out", result["error"])
        self.assertGreaterEqual(result["seconds"], 0)
        self.assertAlmostEqual(result["usd"], result["seconds"] * modal_run.L4_USD_PER_S)
        self.assertTrue((result["folder"] / "partial.wav").is_file())
        self.assertFalse((result["folder"] / "manifest.json").exists())

    def test_plan_is_offline(self):
        job = self.build()
        with mock.patch.dict(sys.modules, {"modal": None}):
            p = modal_run.plan(job["notebook"], job["inputs_zip"])
        deadline = p["forecast_seconds"]
        self.assertEqual(p["timeout_seconds"], deadline + 900)
        self.assertEqual(p["gpu"], "L4")
        self.assertEqual(p["volume"], f"earnalism-eav-jobs:/jobs/{job['job_id']}")
        self.assertAlmostEqual(p["forecast_usd"], deadline * 0.000222)

    def test_cost_arithmetic(self):
        self.assertAlmostEqual(modal_run.modal_cost(3600), 0.7992)
        self.assertEqual(modal_run.modal_cost(0), 0)
        self.assertAlmostEqual(modal_run.modal_cost(100), 100 * modal_run.L4_USD_PER_S)
        self.assertEqual(modal_run.L4_USD_PER_S, 0.000222)

    def test_module_imports_without_modal(self):
        job = self.build()
        with mock.patch.dict(sys.modules, {"modal": None}):  # as if not installed
            with self.assertRaises(ImportError):
                modal_run.run_modal(job["notebook"], job["inputs_zip"], self.root)


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue()


class ModalRunCliTests(unittest.TestCase):
    def setUp(self):
        from tests.test_cli import SOURCE, RATES as CLI_RATES
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / "selfish-giant"
        src = self.d / "src.json"
        src.write_text(json.dumps(SOURCE))
        rates = self.d / "rates.json"
        rates.write_text(json.dumps({"narration": {**CLI_RATES["narration"], "s_per_step": 100.0}}))
        self.assertEqual(run("init", src, "--root", self.root)[0], 0)
        self.assertEqual(run("plan", "--root", self.root)[0], 0)
        self.assertEqual(run("job", "narration", "--root", self.root, "--rates", rates)[0], 0)
        self.job_id = next((self.root / "jobs").iterdir()).name

    def modal_patch(self, behavior=None):
        fm = FakeModal(self.d / "vol", behavior)
        return fm, mock.patch.dict(sys.modules, {"modal": fm.module()})

    def ledger_bytes(self):
        return (self.d / "titles" / "allowance-ledger.json").read_bytes()

    def test_dry_run_only_checks_and_prints_the_plan(self):
        before = self.ledger_bytes()
        with mock.patch.dict(sys.modules, {"modal": None}), \
                mock.patch("subprocess.run") as pip, \
                mock.patch.object(modal_run, "run_cells", side_effect=AssertionError("executed")):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertFalse(pip.called)
        line = json.loads(next(l for l in out.splitlines() if l.startswith("{")))
        self.assertTrue(line["dry_run"])
        self.assertEqual(line["job_id"], self.job_id)
        self.assertEqual((line["gpu"], line["timeout_seconds"]),
                         ("L4", line["forecast_seconds"] + 900))
        self.assertEqual(line["volume"], f"earnalism-eav-jobs:/jobs/{self.job_id}")
        self.assertAlmostEqual(line["forecast_usd"], line["forecast_seconds"] * 0.000222, places=4)
        self.assertFalse((self.root / "modal-downloads").exists())
        self.assertEqual(self.ledger_bytes(), before)

    def test_run_then_import_and_ledger_untouched_by_the_run(self):
        before = self.ledger_bytes()
        fm, patched = self.modal_patch()
        with fakes(), patched:
            code, out = run("modal-run", self.job_id, "--root", self.root)
        self.assertEqual(code, 0, out)
        line = json.loads(next(l for l in out.splitlines() if l.startswith("{")))
        self.assertEqual((line["status"], line["dry_run"]), ("ok", False))
        self.assertIn("eav.cli import " + self.job_id, line["next"])
        folder = Path(line["folder"])
        self.assertEqual(folder, self.root / "modal-downloads" / self.job_id)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(json.loads((folder / "manifest.json").read_text())["status"], "COMPLETE")
        code, out = run("import", self.job_id, "--root", self.root, "--from", folder, "--units", 0.5)
        self.assertEqual(code, 0, out)
        self.assertNotEqual(self.ledger_bytes(), before)

    def test_failed_remote_reports_cost_downloads_partial_and_exits_nonzero(self):
        def behavior(vroot, cells, job_id, archive):
            (vroot / job_id).mkdir(parents=True)
            (vroot / job_id / "u1.wav").write_bytes(b"x")
            raise RuntimeError("timed out")

        fm, patched = self.modal_patch(behavior)
        with patched:
            code, out = run("modal-run", self.job_id, "--root", self.root, "--download", self.d / "dl")
        self.assertEqual(code, 2, out)
        line = json.loads(next(l for l in out.splitlines() if l.startswith("{")))
        self.assertEqual(line["status"], "failed")
        self.assertIn("timed out", line["error"])
        self.assertIn("usd", line)
        self.assertIn("seconds", line)
        self.assertIn(f"close {self.job_id}", line["next"])
        self.assertIn("resume", line["next"])
        self.assertTrue((self.d / "dl" / self.job_id / "u1.wav").is_file())

    def test_refuses_superseded_job(self):
        self.assertEqual(run("supersede", self.job_id, "--root", self.root, "--reason", "no")[0], 0)
        code, out = run("modal-run", self.job_id, "--root", self.root, "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("superseded", out)
        self.assertFalse((self.root / "modal-downloads").exists())

    def test_refuses_unknown_job_and_changed_inputs(self):
        code, out = run("modal-run", "nope", "--root", self.root, "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("unknown job", out)
        zip_path = self.root / "jobs" / self.job_id / "inputs.zip"
        zip_path.write_bytes(zip_path.read_bytes() + b"x")
        code, out = run("modal-run", self.job_id, "--root", self.root, "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("does not match", out)

    def test_refuses_imported_job(self):
        fm, patched = self.modal_patch()
        with fakes(), patched:
            run("modal-run", self.job_id, "--root", self.root)
        folder = self.root / "modal-downloads" / self.job_id
        self.assertEqual(run("import", self.job_id, "--root", self.root, "--from", folder,
                             "--units", 0.5)[0], 0)
        code, out = run("modal-run", self.job_id, "--root", self.root, "--dry-run")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
