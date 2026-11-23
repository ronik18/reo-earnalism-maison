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

RATES = {k: {"s_per_step": 1.0, "units_per_hour": 10.0}
         for k in ("narration", "stills", "music", "reel_clips")}
COMPUTE = {"steps": 1, "items": 2, "takes": 1, "decode_s": 30, "export_s": 20}
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
                ("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}], "compute": COMPUTE}),
                ("music", {"items": [{"key": "m", "prompt": "soft piano", "seed": 2,
                                      "duration_s": 60}], "compute": COMPUTE})]:
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
        s = self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}], "compute": COMPUTE})
        src = "".join("".join(c["source"]) for c in self.nb(s)["cells"])
        self.assertIn("black-forest-labs/FLUX.1-schnell", src)
        self.assertIn("STEPS = 4", src)
        m = self.build("music", {"items": [{"key": "m", "prompt": "p", "seed": 2,
                                            "duration_s": 30}], "compute": COMPUTE})
        src = "".join("".join(c["source"]) for c in self.nb(m)["cells"])
        self.assertIn("ACE-Step/ACE-Step-v1-3.5B", src)
        self.assertIn("weight_sha256", src)

    def test_forbidden_models_rejected(self):
        with self.assertRaises(ValueError):
            self.build("music", {"model": "facebook/musicgen-small",
                                 "items": [{"key": "m", "prompt": "p", "seed": 1,
                                            "duration_s": 5}], "compute": COMPUTE})
        with self.assertRaises(ValueError):
            self.build("stills", {"model": "black-forest-labs/FLUX.1-dev",
                                  "items": [{"key": "a", "prompt": "p", "seed": 1}], "compute": COMPUTE})
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertFalse(self.ledger.path.exists())

    def test_over_budget_writes_nothing(self):
        self.ledger.reserve("garden-book", "2026-11", 59.9, "earlier")
        before = self.ledger.path.read_bytes()
        rates = {"narration": {"s_per_step": 1000.0, "units_per_hour": 10.0}}
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

    def test_missing_compute_fields_rejected(self):
        base = {"scenes": [SCENE], "preset": PRESET}
        bad = [None] + [{k: v for k, v in COMPUTE.items() if k != drop}
                        for drop in ("steps", "items", "decode_s", "export_s")]
        for compute in bad:
            spec = dict(base) if compute is None else dict(base, compute=compute)
            with self.assertRaises(ValueError):
                self.build("narration", spec)
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertFalse(self.ledger.path.exists())

    def test_write_failure_cleans_up_and_settles_zero(self):
        def boom(kind, plan, job_id, title, job_dir):
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

    def _reel_spec(self):
        art = self.root / "art"
        art.mkdir()
        (art / "a.png").write_bytes(b"fixture-image")
        return {"art_dir": str(art), "prior_attempt_evidence": {"scope": "test only"}, "compute": COMPUTE,
                "shots": [{"id": "garden", "image": "a.png", "seed": 7,
                           "prompt": "Notice the bird, lean gently and smile softly."}]}

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

    def test_reel_clips_real_builder_is_contract_valid(self):
        r = self.build("reel_clips", self._reel_spec())
        self.assertTrue(Path(r["inputs_zip"]).is_file())
        self.assertTrue(Path(r["notebook"]).is_file())


if __name__ == "__main__":
    unittest.main()
