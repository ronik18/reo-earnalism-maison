"""modal-run: cell extraction, the headless executor with fake models, the CLI dry run, the cost."""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from eav import budget, cli, colab_jobs, importer, modal_run
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
    """The batched-narration fakes of test_narration_resume (the notebook batches and uses torch
    dtypes); the colab shim under test supplies google.colab itself."""
    from tests.test_narration_resume import _fake_modules
    mods = _fake_modules()
    mods.pop("google"), mods.pop("google.colab")
    return mods


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
        self.lead = ""  # listdir paths: "" (relative to the volume root) or "/" (absolute)
        self.events = []
        self.secret_dicts = []

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
                return [Entry(fm.lead + p.relative_to(fm.vroot).as_posix())
                        for p in sorted(base.rglob("*")) if p.is_file()]
            def read_file(self, path):
                yield (fm.vroot / path.lstrip("/")).read_bytes()

        class App:
            def __init__(self, name): pass
            def function(self, **kw):
                fm.function_kwargs = kw
                def deco(fn):
                    return types.SimpleNamespace(remote=lambda c, j, a: fm.behavior(fm.vroot, c, j, a))
                return deco
            @contextlib.contextmanager
            def run(self):
                fm.events.append("app.run")
                yield

        class Secret:
            @staticmethod
            def from_dict(d):
                fm.secret_dicts.append(dict(d))
                return ("secret", len(fm.secret_dicts))

        mod.Image, mod.Volume, mod.App, mod.Secret = Image, Volume, App, Secret
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

    def test_run_modal_attaches_hf_token_as_an_in_memory_secret_and_never_leaks_it(self):
        job = self.build()
        fm = FakeModal(self.root / "vol")
        out, err = io.StringIO(), io.StringIO()
        with fakes(), mock.patch.dict(sys.modules, {"modal": fm.module()}), \
                mock.patch.dict(os.environ, {"HF_TOKEN": TOKEN}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = modal_run.run_modal(job["notebook"], job["inputs_zip"], self.root / "dl")
        self.assertEqual(fm.secret_dicts, [{"HF_TOKEN": TOKEN, "HUGGING_FACE_HUB_TOKEN": TOKEN}])
        self.assertEqual(len(fm.function_kwargs["secrets"]), 1)
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue() + json.dumps(result, default=str))
        self.assertNotIn("HF_TOKEN not set", out.getvalue() + err.getvalue())
        for f in (self.root / "dl").rglob("*"):
            if f.is_file():
                self.assertNotIn(TOKEN.encode(), f.read_bytes())

    def test_run_modal_without_hf_token_notes_it_and_attaches_no_secret(self):
        job = self.build()
        fm = FakeModal(self.root / "vol")
        err = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k != "HF_TOKEN"}
        with fakes(), mock.patch.dict(sys.modules, {"modal": fm.module()}), \
                mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err):
            modal_run.run_modal(job["notebook"], job["inputs_zip"], self.root / "dl")
        self.assertEqual(fm.secret_dicts, [])
        self.assertEqual(fm.function_kwargs["secrets"], [])
        self.assertEqual(err.getvalue().count("note: HF_TOKEN not set; gated models will fail"), 1)

    def test_a_failure_message_never_carries_the_token(self):
        job = self.build()
        def boom(vroot, cells, job_id, archive):
            raise RuntimeError(f"auth failed for {TOKEN}")
        fm = FakeModal(self.root / "vol", boom)
        with fakes(), mock.patch.dict(sys.modules, {"modal": fm.module()}), \
                mock.patch.dict(os.environ, {"HF_TOKEN": TOKEN}):
            result = modal_run.run_modal(job["notebook"], job["inputs_zip"], self.root / "dl")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn(TOKEN, result["error"])

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
        self.assertAlmostEqual(result["usd"], result["seconds"] * modal_run.L4_USD_PER_S * 1.25)
        self.assertTrue((result["folder"] / "partial.wav").is_file())
        self.assertFalse((result["folder"] / "manifest.json").exists())

    def test_volume_paths_with_or_without_a_leading_slash(self):
        """B1 M1: listdir's path shape is unverified on real Modal; both shapes land the same."""
        for path in ("job/a.wav", "/job/a.wav", "job/sub/b.wav", "/job/sub/b.wav"):
            self.assertEqual(modal_run.volume_relpath(path, "job").as_posix(),
                             path.lstrip("/")[len("job/"):])
        for bad in ("other/a.wav", "/other/a.wav", "job/../x", "job"):
            with self.assertRaises(ValueError):
                modal_run.volume_relpath(bad, "job")
        job = self.build()
        for lead in ("", "/"):
            fm = FakeModal(self.root / f"vol{len(lead)}")
            fm.lead = lead
            with fakes(), mock.patch.dict(sys.modules, {"modal": fm.module()}):
                result = modal_run.run_modal(job["notebook"], job["inputs_zip"], self.root / f"dl{len(lead)}")
            self.assertEqual(result["status"], "ok", result["error"])
            self.assertTrue((result["folder"] / "manifest.json").is_file())

    def test_on_contact_runs_once_just_before_modal_is_contacted(self):
        job = self.build()
        fm = FakeModal(self.root / "vol")
        with fakes(), mock.patch.dict(sys.modules, {"modal": fm.module()}):
            modal_run.run_modal(job["notebook"], job["inputs_zip"], self.root / "dl",
                                on_contact=lambda: fm.events.append("contact"))
        self.assertEqual(fm.events, ["contact", "app.run"])

    def test_execute_remote_commits_at_the_end_and_at_the_hard_stop(self):
        """B1 M2: the container commits the volume itself, at the end whatever happened, and at the
        hard stop before the main thread is interrupted (a kill at the timeout skips `finally`)."""
        job = self.build()
        cells = modal_run.extract_cells(job["notebook"])
        archive = Path(job["inputs_zip"]).read_bytes()
        commits = []
        with fakes():
            out = modal_run.execute_remote(cells, job["job_id"], archive, str(self.root / "v1"),
                                           commit=lambda: commits.append("commit"))
        self.assertEqual((out, commits), ({"hard_stopped": False}, ["commit"]))
        commits.clear()
        stop = cells[:2] + ["from google.colab import runtime\n"
                            "open(DRIVE_JOB_DIR + '/partial.wav', 'w').write('x')\nruntime.unassign()"]
        with fakes():
            out = modal_run.execute_remote(stop, job["job_id"], archive, str(self.root / "v2"),
                                           commit=lambda: commits.append("commit"))
        self.assertEqual((out, commits), ({"hard_stopped": True}, ["commit", "commit"]))
        commits.clear()
        with self.assertRaises(RuntimeError):
            modal_run.execute_remote(cells[:1] + ["raise RuntimeError('cell failed')"], job["job_id"],
                                     archive, str(self.root / "v3"), commit=lambda: commits.append("c"))
        self.assertEqual(commits, ["c"])

    def test_timer_hard_stop_calls_on_stop_from_the_timer_thread(self):
        import threading
        seen = []
        cells = ["JOB_ID = 'x'",
                 "import threading, time\nfrom google.colab import runtime\n"
                 "threading.Timer(0.2, runtime.unassign).start()\n"
                 "for _ in range(200):\n    time.sleep(0.05)"]
        g = modal_run.run_cells(cells, self.root / "t",
                                on_stop=lambda: seen.append(threading.current_thread().name))
        self.assertTrue(g["HARD_STOPPED"])
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(seen[0], threading.main_thread().name)

    def test_plan_is_offline(self):
        job = self.build()
        with mock.patch.dict(sys.modules, {"modal": None}):
            p = modal_run.plan(job["notebook"], job["inputs_zip"])
        deadline = p["forecast_seconds"]
        self.assertEqual(p["timeout_seconds"], deadline + 900)
        self.assertEqual(p["gpu"], "L4")
        self.assertEqual(p["volume"], f"earnalism-eav-jobs:/jobs/{job['job_id']}")
        self.assertAlmostEqual(p["forecast_usd"], deadline * 0.000222 * 1.25)

    def test_cost_arithmetic(self):
        """I1: wall seconds x the L4 rate x 1.25 (CPU, memory and image build overhead)."""
        self.assertEqual(modal_run.MODAL_OVERHEAD_FACTOR, 1.25)
        self.assertAlmostEqual(modal_run.modal_cost(3600), 0.7992 * 1.25)
        self.assertEqual(modal_run.modal_cost(0), 0)
        self.assertAlmostEqual(modal_run.modal_cost(100), 100 * modal_run.L4_USD_PER_S * 1.25)
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


TOKEN = "hf_FAKE_secret_value_123"


class ModalRunCliTests(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"HF_TOKEN": TOKEN})  # the narration model is gated
        env.start()
        self.addCleanup(env.stop)
        from tests.test_cli import SOURCE, RATES as CLI_RATES
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.titles = self.d.joinpath(*getattr(self, "TITLES", ("titles",)))
        self.root = self.titles / "selfish-giant"
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
        return (self.titles / "allowance-ledger.json").read_bytes()

    def test_modal_request_refuses_a_title_root_outside_production_audiovisual(self):
        (self.d / ".git").mkdir()  # titles/selfish-giant: the workflow would refuse it
        before = self.ledger_bytes()
        code, out = run("modal-request", self.job_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual(code, 2, out)
        self.assertIn("not under production/audiovisual/", out)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertFalse((self.titles / "modal-requests").exists())

    def test_gated_model_without_hf_token_is_refused_before_modal_is_contacted(self):
        before = self.ledger_bytes()
        env = {k: v for k, v in os.environ.items() if k != "HF_TOKEN"}
        fm, patch = self.modal_patch()
        with patch, mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(modal_run, "run_modal", side_effect=AssertionError("contacted")):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual(code, 3, out)
        self.assertIn("HF_TOKEN", out)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(fm.events, [])

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
        self.assertAlmostEqual(line["forecast_usd"], line["forecast_seconds"] * 0.000222 * 1.25, places=4)
        self.assertFalse((self.root / "modal-downloads").exists())
        self.assertEqual(self.ledger_bytes(), before)

    def test_run_releases_the_cu_reservation_then_import_settles_in_usd(self):
        before = json.loads(self.ledger_bytes())
        (reserved,) = [e for e in before if e.get("job_id") == self.job_id]
        ledger = budget.Ledger(self.d / "titles" / "allowance-ledger.json")
        month = cli._month()
        colab_before = ledger.spent(None, month)
        fm, patched = self.modal_patch()
        with fakes(), patched:
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual(code, 0, out)
        line = json.loads(next(l for l in out.splitlines() if l.startswith("{")))
        self.assertEqual((line["status"], line["dry_run"]), ("ok", False))
        self.assertIn("eav.cli import " + self.job_id, line["next"])
        folder = Path(line["folder"])
        self.assertEqual(folder, self.root / "modal-downloads" / self.job_id)
        (entry,) = [e for e in json.loads(self.ledger_bytes()) if e.get("job_id") == self.job_id]
        self.assertEqual((entry["runner"], entry["units"], entry["reserved_units"], entry["state"]),
                         ("modal", 0.0, reserved["units"], "reserved"))
        self.assertTrue(entry["moved_to_modal_at"])
        # the Colab month (and title) remaining grew by exactly the released reservation
        self.assertAlmostEqual(ledger.spent(None, month), colab_before - reserved["units"])
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{colab_before - reserved['units']:.2f} CU this month (all titles)", out)
        self.assertIn("on Modal (0.00 CU of Colab work kept, rest of the reservation released)", out)
        self.assertIn("--units <CU> only for Colab work after the move", out)
        self.assertEqual(json.loads((folder / "manifest.json").read_text())["status"], "COMPLETE")
        code, out = run("import", self.job_id, "--root", self.root, "--from", folder)
        self.assertEqual(code, 0, out)
        self.assertIn("settled from its Modal rows", out)
        (entry,) = [e for e in json.loads(self.ledger_bytes()) if e.get("job_id") == self.job_id]
        usd = ledger.modal_job_usd(self.job_id)[0]
        self.assertEqual((entry["state"], entry["units"], entry["usd"]), ("settled", 0.0, round(usd, 6)))
        self.assertAlmostEqual(ledger.spent(None, month), colab_before - reserved["units"])

    def test_failed_remote_reports_cost_downloads_partial_and_exits_nonzero(self):
        def behavior(vroot, cells, job_id, archive):
            (vroot / job_id).mkdir(parents=True)
            (vroot / job_id / "u1.wav").write_bytes(b"x")
            raise RuntimeError("timed out")

        fm, patched = self.modal_patch(behavior)
        with patched:
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0, "--download", self.d / "dl")
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
            run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        folder = self.root / "modal-downloads" / self.job_id
        self.assertEqual(run("import", self.job_id, "--root", self.root, "--from", folder)[0], 0)
        code, out = run("modal-run", self.job_id, "--root", self.root, "--dry-run")
        self.assertEqual(code, 2)


def fake_runner(usd, status="ok", seconds=100.0, calls=None):
    """A stand-in for modal_run.run_modal: no Modal client, a canned bill."""
    def runner(notebook, inputs_zip, download_dir, gpu="L4", on_contact=None):
        if calls is not None:
            calls.append(download_dir)
        if on_contact is not None:
            on_contact()
        folder = Path(download_dir) / "job"
        folder.mkdir(parents=True, exist_ok=True)
        return {"seconds": seconds, "usd": usd, "folder": folder, "status": status,
                "error": None if status != "failed" else "RuntimeError: boom"}
    return runner


class ModalCapTests(unittest.TestCase):
    """B2: the 30 USD UTC-month Modal cap, spend rows on the ledger, units from Modal rows."""
    MONTH = "2026-11"

    modal_patch = ModalRunCliTests.modal_patch

    def setUp(self):
        ModalRunCliTests.setUp(self)
        self.ledger = budget.Ledger(self.titles / "allowance-ledger.json")
        p = mock.patch.object(cli, "_MONTH", self.MONTH)
        p.start()
        self.addCleanup(p.stop)
        plan = modal_run.plan(self.root / "jobs" / self.job_id / "narration.ipynb",
                              self.root / "jobs" / self.job_id / "inputs.zip")
        self.timeout_s = plan["timeout_seconds"]

    def with_worst_case(self, usd):
        """Make the worst case (deadline + 900 s at the L4 rate x the overhead factor) equal usd."""
        return mock.patch.object(modal_run, "L4_USD_PER_S",
                                 usd / (self.timeout_s * modal_run.MODAL_OVERHEAD_FACTOR))

    def seed(self, usd, job_id="other-job", month=None):
        self.ledger.record_modal_spend(month or self.MONTH, job_id, usd, 1.0, "ok", "t")

    def go(self, runner, *extra):
        if "--colab-units" not in extra:
            extra = (*extra, "--colab-units", 0)
        with mock.patch.object(modal_run, "run_modal", runner):
            return run("modal-run", self.job_id, "--root", self.root, *extra)

    def test_cap_refusal_at_the_boundary(self):
        self.seed(29.50)
        calls = []
        with self.with_worst_case(0.60):
            code, out = self.go(fake_runner(0.1, calls=calls))
        self.assertEqual(code, 3, out)
        self.assertEqual(calls, [])  # Modal was never contacted
        for word in ("29.50", "0.60", "0.50"):  # spent, forecast, remaining
            self.assertIn(word, out)
        self.assertEqual(self.ledger.modal_month_usd(self.MONTH), 29.50)

    def test_cap_allows_just_under(self):
        self.seed(29.00)
        with self.with_worst_case(0.60):
            code, out = self.go(fake_runner(0.1))
        self.assertEqual(code, 0, out)
        self.assertAlmostEqual(self.ledger.modal_month_usd(self.MONTH), 29.10)

    def test_cap_exactly_reached_is_allowed_and_other_months_do_not_count(self):
        self.seed(29.40)
        self.seed(30.0, month="2026-10")
        with self.with_worst_case(0.60):
            self.assertEqual(self.go(fake_runner(0.1))[0], 0)

    def test_spend_recorded_on_success_failure_and_hard_stop(self):
        for usd, status in ((0.11, "ok"), (0.22, "failed"), (0.33, "hard_stopped")):
            code, out = self.go(fake_runner(usd, status, seconds=12.5))
            self.assertEqual(code, 2 if status == "failed" else 0, out)
        rows = self.ledger.modal_rows(job_id=self.job_id)
        self.assertEqual([(r["usd"], r["status"], r["seconds"]) for r in rows],
                         [(0.11, "ok", 12.5), (0.22, "failed", 12.5), (0.33, "hard_stopped", 12.5)])
        self.assertTrue(all(r["at"] for r in rows))

    def test_spend_recorded_before_printing(self):
        def boom(*a, **k):
            raise RuntimeError("print crashed")
        with mock.patch.object(cli.json, "dumps", boom):
            with self.assertRaises(RuntimeError):
                self.go(fake_runner(0.4))
        self.assertEqual(self.ledger.modal_month_usd(self.MONTH), 0.4)

    def test_normal_run_leaves_exactly_one_row_with_the_actual_amount(self):
        self.go(fake_runner(0.37, seconds=5.0))
        rows = self.ledger.modal_rows(job_id=self.job_id)
        self.assertEqual([(r["usd"], r["status"], r["seconds"]) for r in rows], [(0.37, "ok", 5.0)])

    def test_interrupted_run_leaves_pending_worst_case_that_blocks_and_modal_settle_replaces(self):
        def interrupted(*a, **k):
            raise KeyboardInterrupt()
        with self.with_worst_case(0.60), mock.patch.object(modal_run, "run_modal", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        rows = self.ledger.modal_rows(job_id=self.job_id)
        self.assertEqual([r["status"] for r in rows], ["pending"])
        self.assertAlmostEqual(rows[0]["usd"], 0.60)
        self.seed(29.0)  # 0.60 pending + 29.00 + 0.60 worst case of a new run > 30
        calls = []
        with self.with_worst_case(0.60):
            code, out = self.go(fake_runner(0.1, calls=calls))
        self.assertEqual((code, calls), (3, []))
        code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.25)
        self.assertEqual(code, 0, out)
        rows = self.ledger.modal_rows(job_id=self.job_id)
        self.assertEqual([(r["status"], r["usd"]) for r in rows], [("settled", 0.25)])
        self.assertEqual(self.ledger.modal_units(self.job_id), 2.5)
        code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.25)
        self.assertEqual(code, 2, out)  # nothing pending any more

    def test_import_and_close_refuse_while_a_row_is_pending(self):
        """B4 M2: never settle the job from a pending worst case; modal-settle first."""
        def interrupted(*a, **k):
            raise KeyboardInterrupt()
        with mock.patch.object(modal_run, "run_modal", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        before = (self.ledger.path.read_bytes(), (self.root / "record.json").read_bytes())
        folder = self.d / "out"
        folder.mkdir()
        for argv in (("import", self.job_id, "--root", self.root, "--from", folder),
                     ("close", self.job_id, "--root", self.root, "--reason", "died")):
            code, out = run(*argv)
            self.assertEqual(code, 2, out)
            self.assertIn("pending Modal row", out)
            self.assertIn("modal-settle", out)
        self.assertEqual((self.ledger.path.read_bytes(), (self.root / "record.json").read_bytes()), before)
        self.assertEqual(run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.05)[0], 0)
        code, out = run("close", self.job_id, "--root", self.root, "--reason", "died")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.entry()["usd"], 0.05)

    def test_modal_settle_reconciles_a_finished_row_from_the_bill(self):
        """I1: the recorded figure is an estimate; the billed amount replaces it, estimate kept."""
        self.go(fake_runner(0.0227, "failed", seconds=102.0))
        self.go(fake_runner(0.40, "hard_stopped"))
        first, second = [r["run_id"] for r in self.ledger.modal_rows(job_id=self.job_id)]
        code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0)
        self.assertEqual(code, 2, out)  # two unbilled rows: --run names one
        self.assertIn("--run", out)
        code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0, "--run", first)
        self.assertEqual(code, 0, out)
        self.assertIn(first, out)
        code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.35)
        self.assertEqual(code, 0, out)  # the one unbilled row left
        rows = self.ledger.modal_rows(job_id=self.job_id)
        self.assertEqual([(r["run_id"], r["usd"], r["estimated_usd"], r["status"], r["billed"]) for r in rows],
                         [(first, 0.0, 0.0227, "failed", True), (second, 0.35, 0.40, "hard_stopped", True)])
        self.assertAlmostEqual(self.ledger.modal_month_usd(self.MONTH), 0.35)
        code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.1, "--run", "x#1")
        self.assertEqual(code, 2, out)

    def colab_cu(self):
        data = cli.Record.load(self.root).data
        return (self.ledger.spent(None, self.MONTH),
                self.ledger.spent(data["title_slug"], None, data["source"].get("edition_id")))

    def entry(self):
        return next(e for e in json.loads(self.ledger.path.read_text()) if e.get("job_id") == self.job_id)

    def test_import_settles_from_every_modal_session_in_usd(self):
        self.go(fake_runner(0.25, "failed"))
        self.go(fake_runner(0.30))
        cu = self.colab_cu()
        fm, patched = self.modal_patch()
        with fakes(), patched:
            run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)  # a real (fake-modal) run for the folder
        folder = self.root / "modal-downloads" / self.job_id
        usd = self.ledger.modal_job_usd(self.job_id)[0]
        code, out = run("import", self.job_id, "--root", self.root, "--from", folder, "--units", -1)
        self.assertEqual(code, 2, out)
        code, out = run("import", self.job_id, "--root", self.root, "--from", folder)
        self.assertEqual(code, 0, out)
        self.assertIn(f"settled from its Modal rows at {usd:.4f} USD plus 0 CU of Colab work", out)
        self.assertEqual((self.entry()["state"], self.entry()["units"], self.entry()["usd"],
                          self.entry()["cu_equivalent"]),
                         ("settled", 0, round(usd, 6), round(usd / 0.10, 2)))
        self.assertEqual(self.colab_cu(), cu)  # Modal dollars never reach the CU caps

    def test_modal_run_requires_colab_units_and_never_lowers_them(self):
        before = self.ledger.path.read_bytes()
        calls = []
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.1, calls=calls)):
            code, out = run("modal-run", self.job_id, "--root", self.root)
        self.assertEqual((code, calls), (2, []))
        self.assertIn("--colab-units is required", out)
        self.assertEqual(self.ledger.path.read_bytes(), before)
        self.assertEqual(self.go(fake_runner(0.1, "failed"), "--colab-units", 0.4)[0], 2)
        code, out = self.go(fake_runner(0.1, calls=calls), "--colab-units", 0.3)
        self.assertEqual((code, calls), (2, []))
        self.assertIn("would lower it", out)

    def test_colab_then_modal_keeps_the_colab_cu_on_the_caps(self):
        """Colab ran 0.5 CU and hard-stopped; the job resumes on Modal: 0.5 CU stay counted."""
        reserved = self.entry()["units"]
        cu_before = self.colab_cu()
        self.go(fake_runner(0.20, "hard_stopped"), "--colab-units", 0.5)
        e = self.entry()
        self.assertEqual((e["runner"], e["units"], e["colab_units"], e["reserved_units"]),
                         ("modal", 0.5, 0.5, reserved))
        self.assertAlmostEqual(self.colab_cu()[0], cu_before[0] - reserved + 0.5)
        self.assertAlmostEqual(self.colab_cu()[1], cu_before[1] - reserved + 0.5)
        code, out = run("close", self.job_id, "--root", self.root, "--reason", "died")
        self.assertEqual(code, 0, out)
        self.assertIn("at 0.2000 USD plus 0.5 CU of Colab work", out)
        self.assertEqual((self.entry()["state"], self.entry()["units"], self.entry()["usd"]),
                         ("settled", 0.5, 0.2))
        self.assertAlmostEqual(self.colab_cu()[0], cu_before[0] - reserved + 0.5)
        code, out = run("status", "--root", self.root)
        self.assertIn("closed (ran, not imported; 0.20 USD on Modal + 0.50 CU Colab settled)", out)

    def test_modal_then_colab_settles_the_colab_portion_too(self):
        """Modal ran first and stopped; the rest ran in Colab (0.7 CU): both portions settle."""
        reserved = self.entry()["units"]
        cu_before = self.colab_cu()
        self.go(fake_runner(0.30, "failed"))  # Modal first: --colab-units 0
        self.assertAlmostEqual(self.colab_cu()[0], cu_before[0] - reserved)
        code, out = run("close", self.job_id, "--root", self.root, "--reason", "rest in Colab, lost",
                        "--units", 0.7)
        self.assertEqual(code, 0, out)
        self.assertIn("at 0.3000 USD plus 0.7 CU of Colab work", out)
        self.assertEqual((self.entry()["units"], self.entry()["usd"]), (0.7, 0.3))
        self.assertAlmostEqual(self.colab_cu()[0], cu_before[0] - reserved + 0.7)
        self.assertAlmostEqual(self.colab_cu()[1], cu_before[1] - reserved + 0.7)

    def test_both_portions_add_up_across_switches(self):
        """Colab 0.5 CU, then Modal, then Colab again 0.3 CU: 0.8 CU on the caps plus the USD."""
        self.go(fake_runner(0.10, "failed"), "--colab-units", 0.5)
        code, out = run("close", self.job_id, "--root", self.root, "--reason", "x", "--units", 0.3)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.entry()["units"], self.entry()["usd"]), (0.8, 0.1))

    def test_supersede_refuses_a_job_that_ran_on_modal(self):
        self.go(fake_runner(0.43, "failed"))
        before_ledger = self.ledger.path.read_bytes()
        before_record = (self.root / "record.json").read_bytes()
        code, out = run("supersede", self.job_id, "--root", self.root, "--reason", "never ran")
        self.assertEqual(code, 2, out)
        self.assertIn("ran on Modal; supersede is for never-run jobs", out)
        self.assertIn(f"close {self.job_id}", out)
        self.assertEqual(self.ledger.path.read_bytes(), before_ledger)
        self.assertEqual((self.root / "record.json").read_bytes(), before_record)

    def test_old_ledger_job_with_modal_rows_but_no_move_settles_in_usd(self):
        """A ledger written before the move was recorded: Modal rows alone make it a Modal job."""
        self.seed(0.40, job_id=self.job_id)
        code, out = run("close", self.job_id, "--root", self.root, "--reason", "died")
        self.assertEqual(code, 0, out)
        e = self.entry()
        self.assertEqual((e["units"], e["usd"], e["runner"]), (0, 0.4, "modal"))
        self.assertGreater(e["reserved_units"], 0)

    def test_colab_jobs_still_require_units(self):
        code, out = run("close", self.job_id, "--root", self.root, "--reason", "died")
        self.assertEqual(code, 2, out)
        self.assertIn("--units is required", out)
        folder = self.d / "nothing"
        folder.mkdir()
        code, out = run("import", self.job_id, "--root", self.root, "--from", folder)
        self.assertEqual(code, 2, out)
        self.assertIn("--units is required", out)
        code, out = run("close", self.job_id, "--root", self.root, "--reason", "died", "--units", 0.7)
        self.assertEqual(code, 0, out)
        self.assertIn("settled at the actual 0.7 CU", out)
        self.assertAlmostEqual(self.colab_cu()[0], 0.7)  # Colab CU caps still count Colab work
        entry = next(e for e in json.loads(self.ledger.path.read_text()) if e.get("job_id") == self.job_id)
        self.assertNotIn("runner", entry)

    def test_status_shows_the_month_and_title_spend(self):
        code, out = run("status", "--root", self.root)
        self.assertIn("modal: $0.00 of $30.00 this month; title: $0.00 of $6.00", out)
        self.go(fake_runner(1.234))
        self.seed(2.0)  # another title's job: the month only
        code, out = run("status", "--root", self.root)
        self.assertIn("modal: $3.23 of $30.00 this month; title: $1.23 of $6.00", out)

    def test_title_cap_refusal_at_the_boundary(self):
        """The month has dollars left but the title is at its 6 USD lifetime cap: refused."""
        self.seed(5.50, job_id=self.job_id, month="2026-10")  # lifetime: an earlier month counts
        before = self.ledger.path.read_bytes()
        calls = []
        with self.with_worst_case(0.60):
            code, out = self.go(fake_runner(0.1, calls=calls))
        self.assertEqual(code, 3, out)
        self.assertEqual(calls, [])  # Modal was never contacted
        for word in ("title cap", "5.50", "0.60", "0.50"):
            self.assertIn(word, out)
        self.assertEqual(self.ledger.path.read_bytes(), before)  # no release, no pending row

    def test_title_cap_allows_just_under(self):
        self.seed(5.30, job_id=self.job_id)
        with self.with_worst_case(0.60):
            code, out = self.go(fake_runner(0.1))
        self.assertEqual(code, 0, out)
        data = cli.Record.load(self.root).data
        self.assertAlmostEqual(self.ledger.modal_title_usd(
            data["title_slug"], data["source"].get("edition_id")), 5.40)

    def test_month_cap_still_binds_with_title_room(self):
        self.seed(29.50)
        with self.with_worst_case(0.60):
            code, out = self.go(fake_runner(0.1))
        self.assertEqual(code, 3, out)
        self.assertIn("month cap", out)

    def test_reservation_caps_unchanged_by_modal_rows(self):
        self.seed(20.0, job_id=self.job_id)
        self.ledger.reserve("other-title", self.MONTH, 60, "x1")
        with self.assertRaises(budget.BudgetExceeded):
            self.ledger.reserve("other-title", self.MONTH, 1, "x2")  # 60 per title still binds
        old = self.d / "old-ledger.json"
        old.write_text(json.dumps([{"job_id": "j", "title": "t", "month": "2026-11",
                                    "units": 1.0, "state": "reserved"}]))
        self.assertEqual(budget.Ledger(old).modal_month_usd("2026-11"), 0.0)
        self.assertIsNone(budget.Ledger(old).modal_units("j"))
        budget.Ledger(old).settle("j", 2.0)
        self.assertEqual(budget.Ledger(old).spent(None, "2026-11"), 2.0)


if __name__ == "__main__":
    unittest.main()
