"""Stills and music notebooks: skip finished items and resume after a disconnect, with fakes."""
import importlib.metadata
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from eav import colab_jobs, importer
from eav.budget import Ledger
from eav.importer import ImportHeld
from eav.record import Record

RATES = {k: {"s_per_step": 1.0, "units_per_hour": 10.0, "decode_s": 30, "export_s": 20}
         for k in ("narration", "stills", "music")}
STILLS = [{"key": "still-%d" % i, "prompt": "a lamp %d" % i, "seed": i, "width": 64,
           "height": 64} for i in range(4)]
CUES = [{"key": "cue-%d" % i, "prompt": "soft piano %d" % i, "seed": i, "duration_s": 5}
        for i in range(4)]
GENERATED = []


class FakeImage:
    def __init__(self, tag):
        self.tag = tag

    def save(self, path):
        Path(path).write_bytes(("png:" + self.tag).encode())


class FakeFlux:
    @classmethod
    def from_pretrained(cls, repo, **kw):
        return cls()

    def enable_model_cpu_offload(self):
        pass

    def __call__(self, prompt, **kw):
        GENERATED.append(prompt)
        return types.SimpleNamespace(images=[FakeImage(prompt + str(kw["generator"].seed))])


class FakeAce:
    suffix = None  # some ACE-Step versions write <save_path stem><suffix>.wav and return its path

    def __init__(self, checkpoint_dir=None, dtype=None):
        pass

    def __call__(self, prompt, save_path, **kw):
        GENERATED.append(prompt)
        path = Path(save_path)
        if FakeAce.suffix is not None:
            path = path.with_name(path.stem + FakeAce.suffix + ".wav")
        path.write_bytes(("wav:" + prompt + str(kw["manual_seeds"])).encode())
        return [str(path), str(path.with_suffix(".json"))]


class FakeHfApi:
    def model_info(self, repo):
        return types.SimpleNamespace(sha="a" * 40)


def _modules(weights):
    torch = types.ModuleType("torch")
    torch.bfloat16 = "bf16"

    class Gen:
        def __init__(self, device):
            self.seed = None

        def manual_seed(self, s):
            self.seed = s
            return self
    torch.Generator = Gen
    diff = types.ModuleType("diffusers")
    diff.FluxPipeline = FakeFlux
    hub = types.ModuleType("huggingface_hub")
    hub.HfApi = FakeHfApi
    hub.snapshot_download = lambda repo, revision=None: str(weights)
    ace = types.ModuleType("acestep")
    ace_p = types.ModuleType("acestep.pipeline_ace_step")
    ace_p.ACEStepPipeline = FakeAce
    colab = types.ModuleType("google.colab")
    colab.drive = types.SimpleNamespace(mount=lambda p: None)
    colab.runtime = types.SimpleNamespace(unassign=lambda: None)
    return {"torch": torch, "diffusers": diff, "huggingface_hub": hub, "acestep": ace,
            "acestep.pipeline_ace_step": ace_p, "google": types.ModuleType("google"),
            "google.colab": colab}


class _Base:
    kind = items = ext = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.weights = self.root / "weights"
        self.weights.mkdir()
        (self.weights / "w.safetensors").write_bytes(b"w")
        self.record = Record.create(self.root / "rec", "garden-book", {"x": 1})
        self.ledger = Ledger(self.root / "ledger.json")
        out = self.root / "rec" / "jobs"
        out.mkdir()
        self.job = colab_jobs.build_job(self.kind, self.record, {"items": self.items},
                                        self.ledger, RATES, out, month="2026-11")
        self.drive = self.root / "drive"
        self.drive.mkdir()
        shutil.copy(self.job["inputs_zip"], self.drive / "inputs.zip")
        nb = json.loads(Path(self.job["notebook"]).read_text())
        self.cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
        GENERATED.clear()

    def session(self, stop_after=None, manifest=True):
        g = {}
        try:
            with patch.dict(sys.modules, _modules(self.weights)), patch("subprocess.run"), \
                    patch.object(importlib.metadata, "distribution",
                                 lambda n: types.SimpleNamespace(
                                     version="1.0", read_text=lambda f: None)):
                run, config, clock, verify, gen, man = self.cells
                exec(run, g)
                g["RUN"] = True
                exec(config, g)
                g.update(DRIVE_JOB_DIR=str(self.drive), DEADLINE_SECONDS=1000)
                exec(clock, g)
                exec(verify, g)
                if stop_after is not None:
                    calls = [0]

                    def may_start(last):
                        calls[0] += 1
                        if calls[0] > stop_after:
                            g["INCOMPLETE"] = True
                            return False
                        return True
                    g["may_start"] = may_start
                exec(gen, g)
                if manifest:
                    exec(man, g)
        finally:
            if "STOP_GUARD" in g:
                g["STOP_GUARD"].cancel()
            if "HEARTBEAT_STOP" in g:
                g["HEARTBEAT_STOP"].set()
        return g

    def manifest(self):
        return json.loads((self.drive / "manifest.json").read_text())

    def import_folder(self):
        return importer.import_job(self.record, self.job, self.drive, self.ledger, 0.1)

    def test_two_sessions_complete_and_import(self):
        self.session(stop_after=2)
        m = self.manifest()
        self.assertEqual((m["status"], m["sessions"]), ("INCOMPLETE", 1))
        progress = [json.loads(x) for x in
                    (self.drive / "progress.jsonl").read_text().splitlines()]
        self.assertEqual([p["file"] for p in progress],
                         [i["key"] + self.ext for i in self.items[:2]])
        with self.assertRaises(ImportHeld):
            self.import_folder()
        GENERATED.clear()
        self.session()
        self.assertEqual(len(GENERATED), 2)  # only the two missing items
        m = self.manifest()
        self.assertEqual((m["status"], m["sessions"]), ("COMPLETE", 2))
        self.assertEqual(sorted(m["outputs"]), sorted(i["key"] + self.ext for i in self.items))
        self.assertTrue(self.import_folder())

    def test_tampered_output_is_regenerated(self):
        self.session(stop_after=2, manifest=False)
        victim = self.drive / (self.items[0]["key"] + self.ext)
        original = victim.read_bytes()
        victim.write_bytes(b"tampered")
        GENERATED.clear()
        self.session()
        self.assertEqual(victim.read_bytes(), original)
        self.assertEqual(len(GENERATED), 3)  # the tampered one plus the two never done
        self.assertEqual(self.manifest()["status"], "COMPLETE")
        self.assertTrue(self.import_folder())


    def test_a_file_written_but_never_recorded_is_redone(self):
        """A2: a crash between the write and its progress line leaves a stale file: it is deleted
        and generated again, never trusted."""
        self.session(stop_after=1, manifest=False)
        stale = self.drive / (self.items[1]["key"] + self.ext)
        stale.write_bytes(b"half-written before the crash")  # no progress line for it
        GENERATED.clear()
        self.session()
        self.assertEqual(len(GENERATED), 3)
        self.assertNotEqual(stale.read_bytes(), b"half-written before the crash")
        self.assertEqual(self.manifest()["status"], "COMPLETE")
        self.assertTrue(self.import_folder())

    def test_progress_lines_carry_the_inputs_zip_and_item_seconds(self):
        """A1 M1/M4: each line is bound to this job's inputs.zip and records the item time."""
        g = self.session(stop_after=2, manifest=False)
        lines = [json.loads(x) for x in (self.drive / "progress.jsonl").read_text().splitlines()]
        self.assertEqual({p["zip"] for p in lines}, {g["INPUT_ZIP_SHA256"]})
        self.assertTrue(all(isinstance(p["item_s"], float) for p in lines))


class StillsResumeTests(_Base, unittest.TestCase):
    kind, items, ext = "stills", STILLS, ".png"


class MusicResumeTests(_Base, unittest.TestCase):
    kind, items, ext = "music", CUES, ".wav"

    def tearDown(self):
        FakeAce.suffix = None

    def test_a_cue_written_under_another_name_is_moved_to_the_expected_one(self):
        """A2: ACE-Step's real output name is not guaranteed; the WAV it reports is placed at
        <key>.wav before it is recorded, so a paid cue is never lost (or left as an extra file)."""
        FakeAce.suffix = "_output_0"
        self.session()
        m = self.manifest()
        self.assertEqual(m["status"], "COMPLETE")
        self.assertEqual(sorted(m["outputs"]), sorted(c["key"] + ".wav" for c in CUES))
        self.assertFalse(list(self.drive.glob("*_output_0.wav")))
        self.assertTrue(self.import_folder())

    def test_no_wav_for_a_cue_stops_the_run_with_a_clear_error(self):
        class Silent(FakeAce):
            def __call__(self, prompt, save_path, **kw):
                return []
        with patch.object(sys.modules[__name__], "FakeAce", Silent):
            with self.assertRaisesRegex(RuntimeError, "ACE-Step wrote no single WAV"):
                self.session()


if __name__ == "__main__":
    unittest.main()
