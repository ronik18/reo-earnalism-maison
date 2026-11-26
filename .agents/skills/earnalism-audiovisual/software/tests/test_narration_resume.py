"""Narration notebook: batched generation and resume after a disconnect, run with fakes."""
import importlib.metadata
import json
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from eav import colab_jobs, importer
from eav.budget import Ledger
from eav.importer import ImportHeld
from eav.record import Record
from tests._narration_fakes import FakeModel, fake_modules as _fake_modules

RATES = {k: {"s_per_step": 1.0, "units_per_hour": 10.0, "decode_s": 30, "export_s": 20}
         for k in ("narration", "stills", "music")}
PRESET = {"description": "A calm warm female voice, very clear.", "temperature": 0.7}
SCENE = {"scene_id": "s01", "text": "One quiet morning. Rain fell. The lamp burned low. "
                                    "A door opened. Someone laughed. Then silence returned."}


class NarrationResumeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.record = Record.create(self.root / "rec", "garden-book", {"x": 1})
        self.ledger = Ledger(self.root / "ledger.json")
        self.out = self.root / "rec" / "jobs"
        self.out.mkdir()
        self.job = self.build()
        self.drive = self.root / "drive"
        self.drive.mkdir()
        shutil.copy(self.job["inputs_zip"], self.drive / "inputs.zip")
        nb = json.loads(Path(self.job["notebook"]).read_text())
        self.cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
        FakeModel.calls, FakeModel.with_lengths = [], True

    def build(self, **spec):
        return colab_jobs.build_job("narration", self.record,
                                    {"scenes": [SCENE], "preset": PRESET, **spec},
                                    self.ledger, RATES, self.out, month="2026-11")

    def session(self, deadline=1000, stop_after_batches=None, modules=None, manifest=True,
                heartbeat_s=None, generate=True, keep_alive=False):
        """Run the notebook's cells in fresh globals, as a new Colab runtime would."""
        g = self.g = {}
        calls = [0]
        if heartbeat_s:
            g["HEARTBEAT_S"] = heartbeat_s
        try:
            with patch.dict(sys.modules, modules or _fake_modules()), \
                    patch("subprocess.run"), \
                    patch.object(importlib.metadata, "distribution", self._dist):
                run, config, clock, verify, gen, man = self.cells
                exec(run, g)
                g["RUN"] = True
                exec(config, g)
                g.update(DRIVE_JOB_DIR=str(self.drive), DEADLINE_SECONDS=deadline)
                exec(clock, g)  # arms the stop before the Drive mount (R25)
                exec(verify, g)
                if stop_after_batches is not None:
                    def may_start(last):
                        calls[0] += 1
                        if calls[0] > stop_after_batches:
                            g["INCOMPLETE"] = True
                            return False
                        return True
                    g["may_start"] = may_start
                if generate:
                    exec(gen, g)
                if manifest:
                    exec(man, g)
        finally:  # a test never leaves a timer or heartbeat running
            if "STOP_GUARD" in g:
                g["STOP_GUARD"].cancel()
            if "HEARTBEAT_STOP" in g and not keep_alive:
                g["HEARTBEAT_STOP"].set()
        return g

    @staticmethod
    def _dist(name):
        return types.SimpleNamespace(version="1.0", read_text=lambda f: None)

    def manifest(self):
        return json.loads((self.drive / "manifest.json").read_text())

    def lines(self, name):
        return [json.loads(x) for x in (self.drive / name).read_text().splitlines()]

    def import_folder(self):
        return importer.import_job(self.record, self.job, self.drive, self.ledger, 0.1)

    # --- builder ---------------------------------------------------------------------------
    def test_batch_defaults_to_8_and_is_pinned_in_job_json(self):
        import zipfile
        with zipfile.ZipFile(self.job["inputs_zip"]) as z:
            self.assertEqual(json.loads(z.read("job.json"))["batch"], 8)
        job = self.build(batch=3, job_id="narration-b3")
        with zipfile.ZipFile(job["inputs_zip"]) as z:
            self.assertEqual(json.loads(z.read("job.json"))["batch"], 3)
        self.assertNotEqual(job["inputs_zip"], self.job["inputs_zip"])

    def test_sdpa_refused_falls_back_to_default_attention(self):
        FakeModel.refuse_sdpa = True
        try:
            self.session()
        finally:
            FakeModel.refuse_sdpa = False
        self.assertNotIn("attn_implementation", FakeModel.load)
        m = self.manifest()
        self.assertEqual(m["model"]["attention"], "default")
        self.assertEqual(m["status"], "COMPLETE")

    def test_invalid_batch_refused(self):
        for bad in (0, 33, -1, 2.5, "8", True, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.build(batch=bad, job_id="narration-bad")

    # --- speed -----------------------------------------------------------------------------
    def test_batched_bf16_generation_trimmed_by_audios_length(self):
        g = self.session()
        units = g["JOB"]["units"]
        self.assertGreaterEqual(len(units), 5)
        self.assertEqual(FakeModel.load["torch_dtype"], "bf16")
        self.assertEqual(FakeModel.load["attn_implementation"], "sdpa")
        self.assertEqual([len(c["input_ids"]) for c in FakeModel.calls],
                         [8, len(units) - 8] if len(units) > 8 else [len(units)])
        for call in FakeModel.calls:
            self.assertIs(call["return_dict_in_generate"], True)
            self.assertEqual(call["temperature"], 0.7)
            self.assertIs(call["do_sample"], True)
        m = self.manifest()
        self.assertEqual(m["model"]["batch"], 8)
        self.assertEqual(m["model"]["attention"], "sdpa")
        self.assertEqual(m["status"], "COMPLETE")
        for u in units:  # each WAV is its own length, not the padded batch length
            raw = (self.drive / (u["unit_key"] + ".wav")).read_bytes()
            self.assertEqual((len(raw) - 3) // 4, len(u["text"]) * 3)

    def test_float16_without_bf16_and_zero_trim_fallback(self):
        FakeModel.with_lengths = False
        self.session(modules=_fake_modules(bf16=False))
        self.assertEqual(FakeModel.load["torch_dtype"], "fp16")
        raw = (self.drive / (json.loads(
            (self.drive / "progress.jsonl").read_text().splitlines()[0])["file"])).read_bytes()
        self.assertNotEqual(np.frombuffer(raw[:-3], dtype="float32")[-1], 0.0)

    def test_small_batch_makes_more_generate_calls(self):
        self.job = self.build(batch=2, job_id="narration-b2")
        shutil.copy(self.job["inputs_zip"], self.drive / "inputs.zip")
        nb = json.loads(Path(self.job["notebook"]).read_text())
        self.cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
        g = self.session()
        n = len(g["JOB"]["units"])
        self.assertEqual([len(c["input_ids"]) for c in FakeModel.calls],
                         [2] * (n // 2) + [n % 2] * (n % 2))

    # --- resume ----------------------------------------------------------------------------
    def test_two_sessions_complete_and_import(self):
        self.job = self.build(batch=2, job_id="narration-b2r")
        shutil.copy(self.job["inputs_zip"], self.drive / "inputs.zip")
        nb = json.loads(Path(self.job["notebook"]).read_text())
        self.cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
        g1 = self.session(stop_after_batches=1)
        total = len(g1["JOB"]["units"])
        self.assertEqual(self.manifest()["status"], "INCOMPLETE")
        self.assertEqual(len(self.lines("progress.jsonl")), 2)
        self.assertEqual(self.manifest()["sessions"], 1)
        with self.assertRaises(ImportHeld):
            self.import_folder()
        FakeModel.calls = []
        self.session()
        self.assertEqual(sum(len(c["input_ids"]) for c in FakeModel.calls), total - 2)
        m = self.manifest()
        self.assertEqual((m["status"], m["sessions"]), ("COMPLETE", 2))
        self.assertNotIn("progress.jsonl", m["outputs"])
        self.assertNotIn("sessions.jsonl", m["outputs"])
        self.assertEqual(len(m["outputs"]), total)
        self.assertGreaterEqual(m["elapsed_seconds"], 0)
        artifacts = self.import_folder()
        self.assertTrue(artifacts)

    def test_tampered_wav_is_regenerated_on_resume(self):
        g = self.session(stop_after_batches=0, manifest=False)
        self.assertFalse(list(self.drive.glob("*.wav")))
        self.session(stop_after_batches=1, manifest=False)
        done = sorted(self.drive.glob("*.wav"))
        self.assertGreater(len(done), 0)
        original = done[0].read_bytes()
        done[0].write_bytes(b"tampered")
        stray = self.drive / "orphan-no-line.wav"  # not an expected unit: never deleted
        stray.write_bytes(b"x")
        FakeModel.calls = []
        self.session()
        self.assertEqual(done[0].read_bytes(), original)
        self.assertTrue(stray.exists())
        self.assertEqual(sum(len(c["input_ids"]) for c in FakeModel.calls),
                         len(g["JOB"]["units"]) - len(done) + 1)
        (self.drive / "late-extra.txt").write_text("x")  # appeared after the manifest
        with self.assertRaises(ImportHeld) as ctx:
            self.import_folder()
        self.assertIn("late-extra.txt", str(ctx.exception))

    def test_unlogged_expected_file_is_deleted_and_redone(self):
        g = self.session(stop_after_batches=1, manifest=False)
        key = g["JOB"]["units"][0]["unit_key"]
        (self.drive / "progress.jsonl").write_text("")  # lines lost; the file alone proves nothing
        before = (self.drive / (key + ".wav")).read_bytes()
        self.session()
        self.assertEqual((self.drive / (key + ".wav")).read_bytes(), before)
        self.assertEqual(self.manifest()["status"], "COMPLETE")

    def test_import_ignores_only_the_two_bookkeeping_files(self):
        self.session()
        (self.drive / "notes.txt").write_text("x")
        with self.assertRaises(ImportHeld):
            self.import_folder()
        (self.drive / "notes.txt").unlink()
        self.import_folder()

    # --- time across sessions ---------------------------------------------------------------
    def test_clock_refuses_when_earlier_sessions_used_all_reserved_time(self):
        self.session(deadline=500, stop_after_batches=1, manifest=False)
        rows = self.lines("sessions.jsonl")
        (self.drive / "sessions.jsonl").write_text(
            json.dumps({"started": rows[0]["started"], "seconds": 0}) + "\n"
            + json.dumps({"started": rows[0]["started"], "seconds": 500}) + "\n")
        with self.assertRaisesRegex(RuntimeError, "reserved time used up"):
            self.session(deadline=500, manifest=False)

    def test_effective_deadline_is_reduced_by_earlier_sessions(self):
        (self.drive / "sessions.jsonl").write_text(
            json.dumps({"started": 1.0, "seconds": 0}) + "\n"
            + json.dumps({"started": 1.0, "seconds": 300}) + "\n")
        g = self.session(deadline=1000, manifest=False)
        self.assertEqual(g["EFFECTIVE_DEADLINE"], 700)
        self.assertEqual(g["PRIOR_SECONDS"], 300)

    def test_session_killed_mid_batch_is_charged_by_the_heartbeat(self):
        """A runtime dying during pip/model load/a batch writes no item line; the heartbeat has
        already charged its elapsed time, so the next session gets less than the full deadline."""
        self.session(deadline=1000, manifest=False, generate=False, heartbeat_s=0.02,
                     keep_alive=True)
        time.sleep(0.3)
        seconds = max(r["seconds"] for r in self.lines("sessions.jsonl"))
        self.assertGreater(seconds, 0.1)  # still ticking with no finished item
        self.g["HEARTBEAT_STOP"].set()  # "killed": the globals are abandoned
        time.sleep(0.1)
        charged = sum(self.session_rows().values())
        g2 = self.session(deadline=1000, manifest=False, generate=False)
        self.assertEqual(g2["PRIOR_SECONDS"], charged)
        self.assertLess(g2["EFFECTIVE_DEADLINE"], 1000)

    def session_rows(self):
        latest = {}
        for r in self.lines("sessions.jsonl"):
            latest[r["started"]] = r["seconds"]
        return latest

    def test_hard_stop_unassigns_even_when_drive_write_fails(self):
        g = self.session(manifest=False, generate=False)
        unassigned = []
        g["runtime"] = types.SimpleNamespace(unassign=lambda: unassigned.append(True))

        def boom():
            raise OSError("Drive disconnected")
        g["note_session"] = boom
        g["_hard_stop"]()
        self.assertEqual(unassigned, [True])


    # --- M1: deferred minors ----------------------------------------------------------------
    def test_progress_lines_written_for_other_inputs_are_not_trusted(self):
        """A1 M4: a line proves a WAV only for this job's inputs.zip (a reused folder's stale WAVs
        with lines of other inputs are regenerated)."""
        g = self.session(stop_after_batches=1, manifest=False)
        lines = self.lines("progress.jsonl")
        self.assertEqual({x["zip"] for x in lines}, {g["INPUT_ZIP_SHA256"]})
        (self.drive / "progress.jsonl").write_text("".join(
            json.dumps({**x, "zip": "0" * 64}) + "\n" for x in lines))
        FakeModel.calls = []
        self.session()
        self.assertEqual(sum(len(c["input_ids"]) for c in FakeModel.calls), len(g["JOB"]["units"]))
        self.assertEqual(self.manifest()["status"], "COMPLETE")

    def test_a_resumed_session_starts_only_if_the_last_batch_time_still_fits(self):
        """A1 M1: the first batch of a resumed session uses the last recorded batch time, not 0."""
        self.job = self.build(batch=2, job_id="narration-b2m1")
        shutil.copy(self.job["inputs_zip"], self.drive / "inputs.zip")
        nb = json.loads(Path(self.job["notebook"]).read_text())
        self.cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
        self.session(stop_after_batches=1, manifest=False)
        lines = self.lines("progress.jsonl")
        self.assertTrue(all(isinstance(x["item_s"], float) for x in lines))
        (self.drive / "progress.jsonl").write_text("".join(
            json.dumps({**x, "item_s": 950.0}) + "\n" for x in lines))
        FakeModel.calls = []
        g = self.session(deadline=1000)  # ~1000 s left < 950 s + the manifest reserve
        self.assertEqual(FakeModel.calls, [])
        self.assertEqual(g["last_item_seconds"](), 950.0)
        self.assertEqual(self.manifest()["status"], "INCOMPLETE")
        (self.drive / "progress.jsonl").write_text("".join(
            json.dumps({**x, "item_s": 5.0}) + "\n" for x in lines))
        self.session(deadline=1000)
        self.assertEqual(self.manifest()["status"], "COMPLETE")

    def test_the_prompt_tokenizer_is_made_to_pad_on_the_left(self):
        """A1 M3: the notebook sets left padding itself and refuses a tokenizer that ignores it
        (the fake model asserts the padding side of every batch it gets)."""
        from tests import _narration_fakes as nf

        class Stubborn(nf.FakeTokenizer):
            @property
            def padding_side(self):
                return "right"

            @padding_side.setter
            def padding_side(self, value):
                pass
        mods = _fake_modules()
        mods["transformers"].AutoTokenizer = Stubborn
        with self.assertRaisesRegex(RuntimeError, "does not pad on the left"):
            self.session(modules=mods)
        self.session()  # the normal tokenizer: generate() saw left-padded prompts
        self.assertTrue(FakeModel.calls)

    def test_appends_from_two_threads_never_tear_a_line(self):
        """The heartbeat thread and the main thread append to the same files under one lock."""
        import threading
        g = self.session(manifest=False, generate=False)
        self.assertTrue(hasattr(g["_APPEND_LOCK"], "acquire"))
        def many(tag):
            for i in range(200):
                g["_append"]("sessions.jsonl", {"started": tag, "seconds": i, "pad": "x" * 300})
        threads = [threading.Thread(target=many, args=(t,)) for t in (1.0, 2.0)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows = (self.drive / "sessions.jsonl").read_text().splitlines()
        parsed = [json.loads(r) for r in rows]  # every line is whole JSON
        self.assertEqual(sum(1 for r in parsed if r["started"] in (1.0, 2.0)), 400)

    def test_rerunning_the_cells_after_the_time_is_used_up_repeats_the_refusal(self):
        """A1 M2: a used-up job refuses the same way on a second Run all in the same runtime
        (never a NameError)."""
        (self.drive / "sessions.jsonl").write_text(json.dumps({"started": 1.0, "seconds": 2000}) + "\n")
        g = {}
        try:
            with patch.dict(sys.modules, _fake_modules()), patch("subprocess.run"):
                run, config, clock, verify = self.cells[:4]
                exec(run, g)
                g["RUN"] = True
                exec(config, g)
                g.update(DRIVE_JOB_DIR=str(self.drive), DEADLINE_SECONDS=1000)
                for _ in range(2):
                    exec(clock, g)
                    with self.assertRaisesRegex(RuntimeError, "reserved time used up"):
                        exec(verify, g)
        finally:
            g.get("STOP_GUARD") and g["STOP_GUARD"].cancel()
            g.get("HEARTBEAT_STOP") and g["HEARTBEAT_STOP"].set()


if __name__ == "__main__":
    unittest.main()
