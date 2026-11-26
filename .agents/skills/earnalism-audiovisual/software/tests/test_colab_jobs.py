import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from eav import colab_jobs
from eav.budget import BudgetExceeded, Ledger
from eav.record import Record

RATES = {k: {"s_per_step": 1.0, "units_per_hour": 10.0, "decode_s": 30, "export_s": 20}
         for k in ("narration", "stills", "music")}
RATES["reel_clips"] = {"clip_s": 500.0, "units_per_hour": 1.94}
COMPUTE = {"steps": 1, "items": 2, "takes": 1, "decode_s": 30, "export_s": 20}  # narration of SCENE
PRESET = {"description": "A calm warm female voice, very clear, close to the microphone."}
SCENE = {"scene_id": "s01", "text": "The morning was quiet. Rain fell on the roof."}


class ColabJobTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.record = Record.create(self.root / "rec", "garden-book", {"x": 1})
        self.ledger = Ledger(self.root / "ledger.json")
        self.out = self.root / "rec" / "jobs"
        self.out.mkdir()

    def build(self, kind, spec, rates=RATES):
        return colab_jobs.build_job(kind, self.record, spec, self.ledger, rates,
                                    self.out, month="2026-11")

    def narration(self, **kw):
        return self.build("narration", {"scenes": [SCENE], "preset": PRESET, "compute": COMPUTE, **kw})

    def nb(self, result):
        return json.loads(Path(result["notebook"]).read_text())

    def test_notebook_is_inert_by_default(self):
        for kind, spec in [
                ("narration", {"scenes": [SCENE], "preset": PRESET, "compute": COMPUTE}),
                ("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]}),
                ("music", {"items": [{"key": "m", "prompt": "soft piano", "seed": 2,
                                      "duration_s": 60}]})]:
            nb = self.nb(self.build(kind, spec))
            code = [c for c in nb["cells"] if c["cell_type"] == "code"]
            self.assertEqual("".join(code[0]["source"]), "RUN = False")
            for c in code[1:]:
                self.assertIn("RUN is not True", "".join(c["source"]))
            self.assertEqual(nb["nbformat"], 4)

    def test_bundle_hash_checked_in_notebook(self):
        r = self.narration()
        sha = hashlib.sha256(Path(r["inputs_zip"]).read_bytes()).hexdigest()
        src = "".join("".join(c["source"]) for c in self.nb(r)["cells"])
        self.assertIn(sha, src)
        self.assertIn("INPUT_ZIP_SHA256", src)
        self.assertIn("/content/drive/MyDrive/earnalism-audiovisual/garden-book/"
                      + r["job_id"], src)
        self.assertGreater(src.index("hashlib.sha256(INPUT_ZIP"), src.index("RUN = False"))

    def test_narration_job_uses_pinned_revision_and_preset_description(self):
        r = self.narration()
        src = "".join("".join(c["source"]) for c in self.nb(r)["cells"])
        self.assertIn("ai4bharat/indic-parler-tts", src)
        self.assertIn("7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca", src)
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            job = json.loads(z.read("job.json"))
        self.assertEqual(len(job["units"]), 2)
        for u in job["units"]:
            self.assertTrue(u["description"].startswith(PRESET["description"]))

    def test_narration_cell_writes_dry_units_without_pause(self):
        """R8: Colab writes dry per-unit WAVs; film.narration_track inserts every pause."""
        cell = (colab_jobs._TEMPLATES / "narration_cell.py.txt").read_text()
        self.assertNotIn("pause_after_ms", cell)
        self.assertNotIn("np.zeros", cell)
        self.assertNotIn("concatenate", cell)

    def test_narration_job_carries_preset_generation_settings(self):
        """R9: the roster preset's temperature reaches job.json, Parler's generate and the manifest."""
        r = self.build("narration", {"scenes": [SCENE], "compute": COMPUTE,
                                     "preset": {**PRESET, "temperature": 0.91}})
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            job = json.loads(z.read("job.json"))
        self.assertEqual(job["generation"], {"temperature": 0.91})
        manifest = json.loads(Path(r["manifest"]).read_text())
        self.assertEqual(manifest["generation"], {"temperature": 0.91})
        src = "".join("".join(c["source"]) for c in self.nb(r)["cells"])
        self.assertIn('JOB.get("generation"', src)
        self.assertIn("**GENERATION", src)
        self.assertIn('"generation": GENERATION', src)

    def test_narration_generation_settings_validated(self):
        for bad in ({"temperature": 0}, {"temperature": "hot"}, {"temperature": float("nan")}):
            with self.assertRaises(ValueError):
                self.build("narration", {"scenes": [SCENE], "compute": COMPUTE,
                                         "preset": {**PRESET, **bad}})

    def test_stills_and_music_pins(self):
        s = self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]})
        src = "".join("".join(c["source"]) for c in self.nb(s)["cells"])
        self.assertIn("black-forest-labs/FLUX.1-schnell", src)
        self.assertIn("STEPS = 4", src)
        m = self.build("music", {"items": [{"key": "m", "prompt": "p", "seed": 2,
                                            "duration_s": 30}]})
        src = "".join("".join(c["source"]) for c in self.nb(m)["cells"])
        self.assertIn("ACE-Step/ACE-Step-v1-3.5B", src)
        self.assertIn("weight_sha256", src)

    def test_forbidden_models_rejected(self):
        with self.assertRaises(ValueError):
            self.build("music", {"model": "facebook/musicgen-small",
                                 "items": [{"key": "m", "prompt": "p", "seed": 1,
                                            "duration_s": 5}]})
        with self.assertRaises(ValueError):
            self.build("stills", {"model": "black-forest-labs/FLUX.1-dev",
                                  "items": [{"key": "a", "prompt": "p", "seed": 1}]})
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertFalse(self.ledger.path.exists())

    def test_over_budget_writes_nothing(self):
        self.ledger.reserve("garden-book", "2026-11", 59.9, "earlier")
        before = self.ledger.path.read_bytes()
        rates = {"narration": {**RATES["narration"], "s_per_step": 1000.0}}
        with self.assertRaises(BudgetExceeded):
            self.build("narration", {"scenes": [SCENE], "preset": PRESET, "compute": COMPUTE}, rates)
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.ledger.path.read_bytes(), before)

    def test_reserves_records_artifact_and_event(self):
        r = self.narration()
        self.assertAlmostEqual(self.ledger.spent("garden-book", "2026-11"), r["forecast_units"])
        self.assertEqual(self.record.data["artifacts"][-1]["kind"], "colab_job")
        ev = self.record.data["events"][-1]
        self.assertEqual((ev["stage"], ev["result"]), ("job", "built"))

    def test_missing_rate_fields_rejected(self):
        """Forecast inputs come from measured rates.json; nothing is defaulted."""
        base = {"scenes": [SCENE], "preset": PRESET}
        for drop in ("s_per_step", "units_per_hour", "decode_s", "export_s"):
            rates = {"narration": {k: v for k, v in RATES["narration"].items() if k != drop}}
            with self.assertRaisesRegex(ValueError, "measured"):
                self.build("narration", dict(base), rates)
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertFalse(self.ledger.path.exists())

    # --- R21: a spec compute block can never lower the forecast ---------------------------
    def test_forecast_derives_items_and_steps_from_the_job(self):
        items = [{"key": k, "prompt": "a lamp", "seed": i} for i, k in enumerate("abc")]
        r = self.build("stills", {"items": items})
        # 3 stills x 4 pinned FLUX steps x 1 s/step + 30 + 20, x 1.15 margin, at 10 CU/h
        self.assertAlmostEqual(r["forecast_units"], (3 * 4 * 1.0 + 30 + 20) * 1.15 / 3600 * 10)

    def test_spec_compute_that_disagrees_with_the_job_is_refused(self):
        items = [{"key": k, "prompt": "a lamp", "seed": i} for i, k in enumerate("abc")]
        for bad in ({"items": 1}, {"steps": 1}, {"takes": 1, "items": 1}, {"decode_s": 0},
                    {"export_s": 0}, {"items": 3, "steps": 4, "unknown": 1}, "not a dict"):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "compute"):
                self.build("stills", {"items": items, "compute": bad})
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertFalse(self.ledger.path.exists())
        ok = self.build("stills", {"items": items, "compute": {
            "items": 3, "steps": 4, "takes": 1, "decode_s": 30, "export_s": 20}})
        self.assertGreater(ok["forecast_units"], 0)

    def test_narration_compute_counts_voice_units(self):
        with self.assertRaisesRegex(ValueError, "compute"):
            self.narration(compute={**COMPUTE, "items": 1})
        r = self.narration()  # SCENE has two voice units
        self.assertAlmostEqual(r["forecast_units"], (1 * 2 * 1.0 + 30 + 20) * 1.15 / 3600 * 10)

    def test_rates_steps_must_match_the_pinned_settings(self):
        rates = {**RATES, "stills": {**RATES["stills"], "steps": 1}}
        with self.assertRaisesRegex(ValueError, "pinned"):
            self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]}, rates)
        self.assertFalse(self.ledger.path.exists())

    def test_write_failure_cleans_up_and_settles_zero(self):
        def boom(kind, plan, job_id, title, job_dir, *deadline):
            job_dir.mkdir(parents=True)
            (job_dir / "partial.txt").write_text("x")
            raise OSError("disk full")

        with patch.object(colab_jobs, "_write_notebook_bundle", side_effect=boom), \
                patch.object(Ledger, "settle", side_effect=RuntimeError("settle broke")):
            with self.assertRaises(OSError):
                self.narration(job_id="job-a")
        self.assertEqual(list(self.out.iterdir()), [])
        with patch.object(colab_jobs, "_write_notebook_bundle", side_effect=boom):
            with self.assertRaises(OSError):
                self.narration(job_id="job-b")
        entry = [e for e in json.loads(self.ledger.path.read_text())
                 if e["job_id"] == "job-b"][0]
        self.assertEqual((entry["state"], entry["units"]), ("settled", 0))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_artifact_meta_paths_relative(self):
        meta = self.narration()
        a = self.record.data["artifacts"][-1]["meta"]
        self.assertFalse(Path(a["inputs_zip"]).is_absolute())
        self.assertFalse(Path(a["manifest"]).is_absolute())

    def _reel_spec(self, n=1):
        art = self.root / "art"
        art.mkdir()
        (art / "a.png").write_bytes(b"fixture-image")
        return {"art_dir": str(art), "prior_attempt_evidence": {"scope": "test only"},
                "shots": [{"id": f"shot-{i:02d}", "image": "a.png", "seed": 7 + i,
                           "prompt": "Notice the bird, lean gently and smile softly."}
                          for i in range(1, n + 1)]}

    def test_reel_clips_delegates_to_wan22_builder(self):
        seen = {}

        def fake_build(destination, job_path, art):
            seen["job"] = json.loads(Path(job_path).read_text())
            seen["art"] = Path(art)
            destination = Path(destination)
            destination.mkdir(parents=True)
            for n in ("wan22-batch-inputs.zip", "build-manifest.json", "nb.ipynb"):
                (destination / n).write_text("x")
            return destination / "nb.ipynb"

        builder = MagicMock()
        builder.build.side_effect = fake_build
        with patch.object(colab_jobs, "_load_wan_builder", return_value=builder):
            r = self.build("reel_clips", self._reel_spec())
        builder.build.assert_called_once()
        self.assertTrue(seen["job"]["scenes"])
        self.assertTrue(all(s["profile"] == "l4-balanced-v2" for s in seen["job"]["scenes"]))
        self.assertTrue(Path(r["notebook"]).is_file())
        self.assertGreater(r["forecast_units"], 0)

    # --- R20/R22: reel batches fit the Wan job's own limits ----------------------------------
    def test_reel_batch_forecast_uses_measured_seconds_per_clip(self):
        r = self.build("reel_clips", self._reel_spec(5))
        self.assertAlmostEqual(r["forecast_units"], 5 * 500.0 * 1.15 / 3600 * 1.94)
        job = json.loads((Path(r["inputs_zip"]).parent / "job.json").read_text())
        # the Wan wall is bound to the forecast and never above the 2700 s contract cap
        self.assertEqual(job["wall_seconds"], 2700)
        self.assertEqual(colab_jobs.MAX_CLIPS_PER_BATCH, 5)

    def test_small_reel_batch_wall_follows_forecast(self):
        r = self.build("reel_clips", self._reel_spec(2))
        job = json.loads((Path(r["inputs_zip"]).parent / "job.json").read_text())
        self.assertEqual(job["wall_seconds"], 1150)  # ceil(2 x 500 x 1.15)
        self.assertGreaterEqual(r["forecast_units"], job["wall_seconds"] / 3600 * 1.94 - 1e-9)

    def test_reel_batch_over_the_wan_wall_is_refused(self):
        with self.assertRaisesRegex(ValueError, "2700"):
            self.build("reel_clips", self._reel_spec(6))
        self.assertFalse(self.ledger.path.exists())

    def test_reel_batch_the_owner_cannot_authorize_is_refused(self):
        """batch.py: metered authority needs 2 x rate x wall / 3600 <= approved CU <= 5."""
        rates = {**RATES, "reel_clips": {"clip_s": 500.0, "units_per_hour": 4.0}}
        with self.assertRaisesRegex(ValueError, "5 CU"):
            self.build("reel_clips", self._reel_spec(5), rates)
        self.assertFalse(self.ledger.path.exists())

    def test_reel_spec_cannot_set_wall_or_takes(self):
        for extra in ({"wall_seconds": 600}, {"compute": {"items": 1}}, {"compute": {"takes": 2}}):
            spec = self._reel_spec(3)
            spec.update(extra)
            with self.subTest(extra), self.assertRaises(ValueError):
                self.build("reel_clips", spec)
            import shutil
            shutil.rmtree(self.root / "art")
        self.assertFalse(self.ledger.path.exists())

    # --- R25: every notebook kind stops at its forecast wall clock --------------------------
    def kinds(self):
        return [("narration", {"scenes": [SCENE], "preset": PRESET}),
                ("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]}),
                ("music", {"items": [{"key": "m", "prompt": "soft piano", "seed": 2, "duration_s": 60}]})]

    def cells(self, result):
        return ["".join(c["source"]) for c in self.nb(result)["cells"] if c["cell_type"] == "code"]

    def test_notebooks_carry_the_forecast_as_a_hard_stop(self):
        for kind, spec in self.kinds():
            r = self.build(kind, spec)
            seconds = r["forecast_units"] / RATES[kind]["units_per_hour"] * 3600
            src = "\n".join(self.cells(r))
            self.assertIn(f"DEADLINE_SECONDS = {int(seconds)}", src, kind)
            self.assertIn("runtime.unassign", src, kind)
            template = (colab_jobs._TEMPLATES / f"{kind}_cell.py.txt").read_text()
            loop = template[template.index("for "):]
            self.assertIn("if not may_start(last):", loop, kind)  # checked between items
            self.assertIn("EXPECTED", template, kind)

    def test_hard_stop_marks_the_manifest_incomplete(self):
        """Run the notebook's own clock and manifest cells with a stubbed Colab runtime."""
        import sys
        import types
        r = self.build(*self.kinds()[1])
        config, clock, manifest = [c for c in self.cells(r) if "DEADLINE_SECONDS =" in c or "def may_start" in c
                                   or "manifest.json" in c and "write_text" in c]
        unassigned = []
        colab = types.ModuleType("google.colab")
        colab.runtime = types.SimpleNamespace(unassign=lambda: unassigned.append(True))
        out_dir = self.root / "drive-job"
        out_dir.mkdir()
        (out_dir / "a.png").write_bytes(b"png")
        with patch.dict(sys.modules, {"google": types.ModuleType("google"), "google.colab": colab}):
            g = {"RUN": True}
            exec(config, g)
            g["DEADLINE_SECONDS"] = 100
            exec(clock, g)
            g["STOP_GUARD"].cancel()
            self.assertTrue(g["may_start"](10))
            g["JOB_STARTED"] -= 95  # 5 s left: the next 10 s item would cross the stop
            self.assertFalse(g["may_start"](10))
            g.update(OUT_DIR=out_dir, EXPECTED=["a.png"], MODEL_INFO={"repo": "x"})
            exec(manifest, g)
        data = json.loads((out_dir / "manifest.json").read_text())
        self.assertEqual(data["status"], "INCOMPLETE")
        self.assertEqual(set(data["packages"]), set(colab_jobs.PACKAGES["stills"]))  # R26
        self.assertEqual(data["deadline_seconds"], 100)
        g["INCOMPLETE"] = False
        exec(manifest, g)
        self.assertEqual(json.loads((out_dir / "manifest.json").read_text())["status"], "COMPLETE")
        (out_dir / "a.png").unlink()
        (out_dir / "b.png").write_bytes(b"png")
        exec(manifest, g)  # a missing expected output is never COMPLETE
        self.assertEqual(json.loads((out_dir / "manifest.json").read_text())["status"], "INCOMPLETE")

    def test_reel_clips_real_builder_is_contract_valid(self):
        r = self.build("reel_clips", self._reel_spec())
        self.assertTrue(Path(r["inputs_zip"]).is_file())
        self.assertTrue(Path(r["notebook"]).is_file())

    # --- M1: deferred minors ----------------------------------------------------------------
    def test_a_failed_record_write_after_the_bundle_leaves_no_orphan(self):
        """A3 M2: the bundle is written but recording its artifact fails: the folder is removed,
        the reservation settled at 0 and the record keeps no artifact."""
        before = list(self.record.data["artifacts"])
        with patch.object(Record, "_save", side_effect=OSError("record disk full")):
            with self.assertRaises(OSError):
                self.narration(job_id="job-rec")
        self.assertEqual(self.record.data["artifacts"], before)
        self.assertEqual(json.loads(self.record.path.read_text())["artifacts"], before)
        self.assertFalse((self.out / "job-rec").exists())
        entry = [e for e in json.loads(self.ledger.path.read_text()) if e["job_id"] == "job-rec"][0]
        self.assertEqual((entry["state"], entry["units"]), ("settled", 0))

    def test_reel_art_dir_may_list_the_chunk_folders_of_chunked_stills(self):
        """A3 M1: a batch whose keyframes sit in two stills chunk folders is built from both, each
        image from the one folder that holds it; an image in none or in two is refused."""
        c1, c2 = self.root / "stills-c1of2", self.root / "stills-c2of2"
        c1.mkdir()
        c2.mkdir()
        (c1 / "shot-01.png").write_bytes(b"first-chunk")
        (c2 / "shot-02.png").write_bytes(b"second-chunk")
        spec = {"art_dir": [str(c1), str(c2)], "prior_attempt_evidence": {"scope": "test only"},
                "shots": [{"id": f"shot-{i:02d}", "image": f"shot-{i:02d}.png", "seed": i,
                           "prompt": "Notice the bird, lean gently and smile softly."}
                          for i in (1, 2)]}
        r = self.build("reel_clips", spec)
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            self.assertEqual(z.read("inputs/shot-01.png"), b"first-chunk")
            self.assertEqual(z.read("inputs/shot-02.png"), b"second-chunk")
        (c1 / "shot-02.png").write_bytes(b"duplicate")
        with self.assertRaisesRegex(ValueError, "in 2 of the art_dir folders"):
            self.build("reel_clips", {**spec, "shots": spec["shots"][1:]})
        with self.assertRaisesRegex(ValueError, "in 0 of the art_dir folders"):
            self.build("reel_clips", {**spec, "shots": [{**spec["shots"][0], "image": "none.png"}]})
        with self.assertRaisesRegex(ValueError, "folder or a list of folders"):
            self.build("reel_clips", {**spec, "art_dir": []})


if __name__ == "__main__":
    unittest.main()
