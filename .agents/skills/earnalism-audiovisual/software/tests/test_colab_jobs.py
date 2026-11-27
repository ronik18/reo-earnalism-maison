import contextlib
import hashlib
import io
import json
import tarfile
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
RATES["film_clips"] = {"clip_s_hd": 900, "clip_s_hd_a100": 215, "clip_s_sd": 435,
                       "units_per_hour_l4": 2.4, "units_per_hour_a100": 4.5,
                       "decode_s": 900, "export_s": 120}
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

    def test_narration_install_pins_parler_and_restores_protobuf_before_import(self):
        """Colab 2026-11-23: parler-tts pulls descript-audiotools, which resolves protobuf 4.25,
        and transformers then fails on `google.protobuf.runtime_version` (added in 5.26)."""
        cell = (colab_jobs._TEMPLATES / "narration_cell.py.txt").read_text()
        self.assertIn("parler-tts.git@d108732cd57788ec86bc857d99a6cabd66663d68", cell)
        upgrade = cell.index('"protobuf>=5.26,<7"')
        self.assertLess(cell.index("parler-tts.git@"), upgrade)
        self.assertLess(upgrade, cell.index("from parler_tts import"))
        self.assertLess(upgrade, cell.index("from transformers import"))
        # An old protobuf already imported in this process cannot be replaced: stop with the fix.
        self.assertIn('"google.protobuf" in sys.modules', cell)
        self.assertIn("Runtime > Restart session", cell)
        self.assertIn("protobuf", colab_jobs.PACKAGES["narration"])

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

    def job_json(self, r):
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            return json.loads(z.read("job.json"))

    def test_default_narration_job_json_has_no_style_fields(self):
        job = self.job_json(self.narration())
        self.assertEqual(sorted(job), ["generation", "job_id", "kind", "model", "schema", "title", "units"])

    def test_expressive_narration_groups_directs_and_records_the_style(self):
        style = {"group": True, "pauses": True, "direct": True}
        r = self.narration(style=style, compute={**COMPUTE, "items": 1},
                           directions={"s01-001": {"emotion": "Sad", "clause": "Softly."}})
        job = self.job_json(r)
        self.assertEqual(job["voice_style"], style)
        self.assertEqual(len(job["units"]), 1)  # the two short sentences are one unit
        self.assertEqual(job["units"][0]["text"], SCENE["text"])
        self.assertIn("sad tone. Softly.", job["units"][0]["description"])
        self.assertEqual(job["directions"], {"s01-001": {"emotion": "Sad", "clause": "Softly."}})

    def test_directions_for_unknown_units_are_refused_before_anything_is_written(self):
        with self.assertRaisesRegex(ValueError, "unknown unit"):
            self.narration(style={"group": True, "direct": True}, compute={**COMPUTE, "items": 1},
                           directions={"s01-002": {"emotion": "Sad"}})
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertFalse(self.ledger.path.exists())

    def test_audition_job_renders_every_variant_and_is_marked(self):
        passages = {"narration": "The giant came home. He was tired.",
                    "dialogue": "\u201cWho are you?\u201d he asked.",
                    "emotional": "She wept."}
        spec = {"audition": {"passages": passages, "language": "en", "variants": [
            {"name": "control", "preset_key": "en_tisha::story",
             "preset": {**PRESET, "temperature": 0.91}, "style": None},
            {"name": "mary-storyteller", "preset_key": "mary::storyteller",
             "preset": {"description": "Mary speaks warmly.", "speaker": "Mary", "temperature": 0.91},
             "style": {"group": True, "pauses": True, "direct": True}}]}}
        r = self.build("narration", spec)
        job = self.job_json(r)
        self.assertEqual(job["audition"]["variants"],
                         {"control": "en_tisha::story", "mary-storyteller": "mary::storyteller"})
        keys = [u["unit_key"] for u in job["units"]]
        self.assertIn("control__narration-002", keys)
        self.assertIn("mary-storyteller__narration-001", keys)
        self.assertEqual(job["generation"], {"temperature": 0.91})
        bad = json.loads(json.dumps(spec))
        bad["audition"]["variants"][1]["preset"]["temperature"] = 1.2
        with self.assertRaisesRegex(ValueError, "generation"):
            self.build("narration", bad)

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

    def test_stills_fit_an_l4(self):
        # FLUX's bf16 transformer (~24 GB) does not fit an L4 (22 GB): load it 8-bit there, and
        # never hold it with the text encoders (~10 GB): encode every prompt first, then free them
        s = self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]})
        src = "".join("".join(c["source"]) for c in self.nb(s)["cells"])
        self.assertIn("gpu.total_memory >= 30 * 2**30", src)
        self.assertIn("BitsAndBytesConfig(load_in_8bit=True)", src)
        self.assertIn('"bitsandbytes"', src)
        self.assertIn("transformer_precision", src)
        self.assertNotIn("enable_model_cpu_offload", src)
        encode, free, load = (src.index("encode_prompt("), src.index("del enc"),
                              src.index('subfolder="transformer"'))
        self.assertLess(encode, free)
        self.assertLess(free, load)
        self.assertIn("text_encoder_2=None", src)
        self.assertIn("prompt_embeds=pe", src)

    def test_every_gpu_job_stops_early_without_a_gpu(self):
        # a CPU-only runtime failed late with "Torch not compiled with CUDA enabled"; check first
        s = self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]})
        cells = ["".join(c["source"]) for c in self.nb(s)["cells"]]
        gpu = next(i for i, c in enumerate(cells) if "nvidia-smi" in c)
        access = next(i for i, c in enumerate(cells) if "auth_check" in c)
        clock = next(i for i, c in enumerate(cells) if "DEADLINE_SECONDS" in c and "threading" in c)
        self.assertIn("No GPU attached", cells[gpu])
        self.assertIn("if RUN is not True", cells[gpu])
        self.assertLess(gpu, access)
        self.assertLess(access, clock)

    def test_gpu_cell_refuses_a_cpu_runtime(self):
        from unittest import mock
        s = self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]})
        cell = next("".join(c["source"]) for c in self.nb(s)["cells"] if "nvidia-smi" in "".join(c["source"]))
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                exec(cell, {"RUN": True})
        self.assertIn("No GPU attached", str(caught.exception))
        with self.assertRaises(RuntimeError):
            exec(cell, {"RUN": False})  # the guard still refuses before RUN = True

    def test_stills_silence_the_8bit_cast_warning(self):
        # the per-matmul bitsandbytes cast warning floods the output on an L4; log it once
        s = self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]})
        src = "".join("".join(c["source"]) for c in self.nb(s)["cells"])
        self.assertIn('logging.getLogger("bitsandbytes.autograd._functions").setLevel(logging.ERROR)', src)
        self.assertLess(src.index('if QUANT == "int8":'), src.index("bitsandbytes.autograd._functions"))
        self.assertLess(src.index("bitsandbytes.autograd._functions"), src.index('subfolder="transformer"'))

    def test_stills_put_the_house_style_first(self):
        # CLIP reads 77 tokens and T5 256: the look must survive truncation
        s = self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]})
        cell = [c for c in self.nb(s)["cells"] if "def look_first" in "".join(c["source"])][0]
        src = "".join(cell["source"])
        ns = {}
        exec(src[src.index("def look_first"):src.index("# Phase 1")], ns)
        self.assertEqual(ns["look_first"]("A judge at dusk. Earnalism house style: 2D animated."),
                         "Earnalism house style: 2D animated. A judge at dusk.")
        self.assertEqual(ns["look_first"]("no style here"), "no style here")

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
        # plus the gate's seconds, not margined: set-up 300 s + 6 s per still (ESTIMATE)
        self.assertAlmostEqual(r["forecast_units"], ((3 * 4 * 1.0 + 30 + 20) * 1.15 + 300 + 6 * 3) / 3600 * 10)

    def test_stills_forecast_includes_gate_seconds_and_rates_may_restate_them(self):
        items = [{"key": k, "prompt": "a lamp", "seed": i} for i, k in enumerate("abc")]
        from eav import colab_jobs as cj
        self.assertEqual(cj.derive_compute("stills", {"items": items}, RATES, 3)["gate_s"], 300 + 6 * 3)
        rates = {**RATES, "stills": {**RATES["stills"], "gate_setup_s": 100, "gate_s_per_still": 10}}
        self.assertEqual(cj.derive_compute("stills", {"items": items}, rates, 3)["gate_s"], 130)
        from eav.budget import forecast_seconds
        c = cj.derive_compute("stills", {"items": items}, RATES, 3)
        self.assertEqual(forecast_seconds(c, RATES) - forecast_seconds({**c, "gate_s": 0}, RATES), 318)

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

    def test_the_notebook_itself_is_never_an_output(self):
        """Colab 2026-11-23: the job's notebook lives in the Drive job folder and was listed as an
        output of every run (narration-film-01-r4, stills-film-01-r5, music-film-01-r4)."""
        import sys
        import types
        r = self.build(*self.kinds()[1])
        config, clock, manifest = [c for c in self.cells(r) if "DEADLINE_SECONDS =" in c or "def may_start" in c
                                   or "manifest.json" in c and "write_text" in c]
        colab = types.ModuleType("google.colab")
        colab.runtime = types.SimpleNamespace(unassign=lambda: None)
        out_dir = self.root / "drive-job"
        out_dir.mkdir()
        (out_dir / "a.png").write_bytes(b"png")
        (out_dir / "stills.ipynb").write_text("{}")
        (out_dir / "Copy of stills.ipynb").write_text("{}")
        with patch.dict(sys.modules, {"google": types.ModuleType("google"), "google.colab": colab}):
            g = {"RUN": True}
            exec(config, g)
            exec(clock, g)
            g["STOP_GUARD"].cancel()
            g.update(OUT_DIR=out_dir, EXPECTED=["a.png"], MODEL_INFO={"repo": "x"})
            exec(manifest, g)
        data = json.loads((out_dir / "manifest.json").read_text())
        self.assertEqual(sorted(data["outputs"]), ["a.png"])
        self.assertEqual(data["status"], "COMPLETE")

    def test_reel_clips_real_builder_is_contract_valid(self):
        r = self.build("reel_clips", self._reel_spec())
        self.assertTrue(Path(r["inputs_zip"]).is_file())
        self.assertTrue(Path(r["notebook"]).is_file())


class _Response:
    def __init__(self, status, body=b""):
        self.status, self._body = status, body

    def read(self, *a):
        body, self._body = self._body, b""
        return body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ExchangeNotebookTests(unittest.TestCase):
    """The R2 exchange inside the built notebooks (inputs download, outputs upload)."""
    setUp, build, nb = ColabJobTests.setUp, ColabJobTests.build, ColabJobTests.nb
    kinds, cells = ColabJobTests.kinds, ColabJobTests.cells

    def run_cell(self, cell, g, urlopen):
        import sys
        import types
        drive = types.SimpleNamespace(mount=lambda path: None)
        colab = types.ModuleType("google.colab")
        colab.drive = drive
        with patch.dict(sys.modules, {"google": types.ModuleType("google"), "google.colab": colab}), \
                patch("urllib.request.urlopen", urlopen):
            exec(cell, g)

    def setup_job(self, kind="stills"):
        r = self.build(kind, dict(self.kinds())[kind])
        cells = self.cells(r)
        config = next(c for c in cells if "DRIVE_JOB_DIR =" in c)
        verify = next(c for c in cells if "INPUT_ZIP_SHA256:" in c or "!= INPUT_ZIP_SHA256" in c)
        manifest = next(c for c in cells if "manifest.json" in c and "write_text" in c)
        drive_dir = self.root / "drive" / r["job_id"]
        drive_dir.mkdir(parents=True)
        g = {"RUN": True}
        exec(config, g)
        g["DRIVE_JOB_DIR"] = str(drive_dir)
        g["JOB_STARTED"] = __import__("time").time()
        return r, verify, manifest, drive_dir, g

    def exchange(self, drive_dir, r, hours=6, url="https://acc.r2.cloudflarestorage.com/b/in?sig"):
        raw = Path(r["inputs_zip"]).read_bytes()
        from datetime import datetime, timedelta, timezone
        data = {"schema": "earnalism.colab-exchange.v1", "job_id": r["job_id"], "title": "garden-book",
                "inputs": {"url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
                "outputs": {"url": "https://acc.r2.cloudflarestorage.com/b/out?sig", "method": "PUT",
                            "headers": {"Content-Type": "application/x-tar"}},
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()}
        (drive_dir / "exchange.json").write_text(json.dumps(data))
        return raw

    def test_every_notebook_carries_the_exchange_code(self):
        for kind, spec in self.kinds():
            src = "\n".join(self.cells(self.build(kind, spec)))
            self.assertIn("exchange.json", src, kind)
            self.assertIn('EXCHANGE["inputs"]["url"]', src, kind)
            self.assertIn('EXCHANGE["outputs"]["url"]', src, kind)
            self.assertIn("tarfile", src, kind)
            # the unchanged sha256 check still runs after any download
            self.assertGreater(src.index("hashlib.sha256(INPUT_ZIP.read_bytes())"),
                               src.index('EXCHANGE["inputs"]["url"]'), kind)

    def test_inputs_are_downloaded_then_verified(self):
        r, verify, _, drive_dir, g = self.setup_job()
        raw = self.exchange(drive_dir, r)
        seen = []

        def urlopen(req, timeout=None):
            seen.append(getattr(req, "full_url", req))
            return _Response(200, raw)
        self.run_cell(verify, g, urlopen)
        self.assertEqual(seen, ["https://acc.r2.cloudflarestorage.com/b/in?sig"])
        self.assertEqual((drive_dir / "inputs.zip").read_bytes(), raw)
        self.assertEqual(g["JOB"]["job_id"], r["job_id"])

    def test_tampered_download_is_refused_and_not_kept(self):
        r, verify, _, drive_dir, g = self.setup_job()
        self.exchange(drive_dir, r)
        with self.assertRaises(RuntimeError) as ctx:
            self.run_cell(verify, g, lambda req, timeout=None: _Response(200, b"PK-not-the-zip"))
        self.assertIn("sha256", str(ctx.exception))
        self.assertFalse((drive_dir / "inputs.zip").exists())

    def test_present_inputs_zip_is_not_downloaded_again(self):
        r, verify, _, drive_dir, g = self.setup_job()
        self.exchange(drive_dir, r)
        (drive_dir / "inputs.zip").write_bytes(Path(r["inputs_zip"]).read_bytes())

        def urlopen(req, timeout=None):
            raise AssertionError("no download when inputs.zip is present")
        self.run_cell(verify, g, urlopen)

    def test_expired_exchange_stops_before_any_gpu_work(self):
        r, verify, _, drive_dir, g = self.setup_job()
        self.exchange(drive_dir, r, hours=0.01)
        with self.assertRaises(RuntimeError) as ctx:
            self.run_cell(verify, g, lambda req, timeout=None: _Response(200, b""))
        self.assertIn("expire", str(ctx.exception))

    def manifest_run(self, status_code):
        r, verify, manifest, drive_dir, g = self.setup_job()
        raw = self.exchange(drive_dir, r)
        self.run_cell(verify, g, lambda req, timeout=None: _Response(200, raw))
        (drive_dir / "a.png").write_bytes(b"png-a")
        g.update(OUT_DIR=drive_dir, EXPECTED=["a.png"], MODEL_INFO={"repo": "x"}, INCOMPLETE=False)
        sent = []

        def urlopen(req, timeout=None):
            body = req.data.read() if hasattr(req.data, "read") else req.data
            sent.append((req.full_url, req.get_method(), dict(req.header_items()), body))
            if status_code >= 400:
                import urllib.error
                raise urllib.error.HTTPError(req.full_url, status_code, "denied", {}, io.BytesIO(b""))
            return _Response(status_code)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.run_cell(manifest, g, urlopen)
        return sent, out.getvalue(), drive_dir

    def test_outputs_are_tarred_and_put_to_the_signed_url(self):
        sent, out, drive_dir = self.manifest_run(200)
        [(url, method, headers, body)] = sent
        self.assertEqual((url, method), ("https://acc.r2.cloudflarestorage.com/b/out?sig", "PUT"))
        headers = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(headers["content-type"], "application/x-tar")
        self.assertEqual(int(headers["content-length"]), len(body))
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:") as tar:
            members = tar.getmembers()
        self.assertEqual(sorted(m.name for m in members), ["a.png", "manifest.json"])
        self.assertTrue(all(m.isreg() for m in members))
        self.assertIn("200", out)
        manifest = json.loads((drive_dir / "manifest.json").read_text())
        self.assertEqual(set(manifest["outputs"]), {"a.png"})  # not exchange.json, not inputs.zip

    def test_failed_upload_raises_and_never_claims_success(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.manifest_run(403)
        self.assertIn("403", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class HouseStyleTests(unittest.TestCase):
    """Owner 2026-11-24: every book's stills use the 2D animated feature-film look of the বিচারক
    stills he picked (f01s007-6, f01s012-2, f01s018-1, f01s017-3, f01s007-2)."""
    setUp, build, nb = ColabJobTests.setUp, ColabJobTests.build, ColabJobTests.nb

    def payload(self, r):
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            return json.loads(z.read("job.json"))

    def test_every_stills_prompt_carries_the_house_style(self):
        r = self.build("stills", {"items": [{"key": "a", "prompt": "a lamp on a sill", "seed": 1}]})
        prompt = self.payload(r)["items"][0]["prompt"]
        self.assertTrue(prompt.startswith("a lamp on a sill"))
        self.assertTrue(prompt.endswith(colab_jobs.HOUSE_STYLE))
        self.assertIn("2D animated", colab_jobs.HOUSE_STYLE)

    def test_a_prompt_asking_for_another_style_is_refused(self):
        for clash in ("oil-on-canvas realism", "photorealistic portrait", "storybook watercolour",
                      "not a cartoon"):
            with self.assertRaises(ValueError) as caught:
                self.build("stills", {"items": [{"key": "a", "prompt": f"a lamp, {clash}", "seed": 1}]})
            self.assertIn("house style", str(caught.exception))

class MusicInstallTests(unittest.TestCase):
    """ACE-Step pins spacy==3.8.4, which has no Python 3.13 build (Colab runs 3.13 since 2026)."""

    def test_music_installs_pinned_ace_step_without_its_unbuildable_pins(self):
        cell = (colab_jobs._TEMPLATES / "music_cell.py.txt").read_text()
        self.assertIn('"--no-deps"', cell)
        self.assertIn("ACE-Step.git@1bee4c9f5b43e30995f8d4d33b3919197ce1bd68", cell)
        self.assertIn('"spacy>=3.8.5,<3.9"', cell)
        self.assertNotIn("spacy==3.8.4", cell)
        self.assertIn('"transformers==4.50.0"', cell)
        # the dependencies are installed before the package is imported
        self.assertLess(cell.index('"spacy>=3.8.5,<3.9"'), cell.index("from acestep"))

    def test_music_reloads_huggingface_hub_after_the_install(self):
        # Colab 2026-11-27: the access check imports Colab's huggingface_hub before the install
        # swaps it for a transformers-4.50-compatible one; the mixed modules then fail with
        # "cannot import name 'refresh_xet_connection_info'". Pin it and import it afresh.
        cell = (colab_jobs._TEMPLATES / "music_cell.py.txt").read_text()
        self.assertIn('"huggingface_hub>=0.30,<1.0"', cell)
        purge = cell.index('startswith(("huggingface_hub", "hf_xet"))')
        self.assertLess(cell.index('"huggingface_hub>=0.30,<1.0"'), purge)
        self.assertLess(purge, cell.index("from huggingface_hub import"))


class AccessPreflightTests(unittest.TestCase):
    """Colab 2026-11-23: a gated model failed only after the install; check access first."""
    setUp, build, nb = ColabJobTests.setUp, ColabJobTests.build, ColabJobTests.nb
    kinds, cells = ColabJobTests.kinds, ColabJobTests.cells

    def access_cell(self, kind):
        cells = self.cells(self.build(kind, dict(self.kinds())[kind]))
        index = next(i for i, c in enumerate(cells) if "auth_check(MODEL_REPO" in c)
        clock = next(i for i, c in enumerate(cells) if "STOP_GUARD" in c)
        config = next(c for c in cells if "DRIVE_JOB_DIR =" in c)
        return cells[index], index, clock, config

    def run_access(self, kind, secret=None, secret_error=None, auth_error=None):
        import sys
        import types
        cell, _, _, config = self.access_cell(kind)
        g = {"RUN": True}
        exec(config, g)
        userdata = types.SimpleNamespace()

        def get(name):
            if secret_error:
                raise secret_error
            return secret
        userdata.get = get
        colab = types.ModuleType("google.colab")
        colab.userdata = userdata
        seen = {}

        class Api:
            def auth_check(self, repo, token=None):
                seen["call"] = (repo, token)
                if auth_error:
                    raise auth_error
        hub = types.ModuleType("huggingface_hub")
        hub.HfApi = Api
        with patch.dict(sys.modules, {"google": types.ModuleType("google"), "google.colab": colab,
                                      "huggingface_hub": hub}), patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("HF_TOKEN", None)
            exec(cell, g)
            return seen, os.environ.get("HF_TOKEN")

    def test_every_notebook_checks_model_access_before_the_clock(self):
        for kind in ("narration", "stills", "music"):
            cell, index, clock, _ = self.access_cell(kind)
            self.assertLess(index, clock, kind)
            self.assertNotIn("pip", cell, kind)

    def test_gated_model_without_access_stops_with_the_fix(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_access("stills", secret="hf_x", auth_error=PermissionError("403 gated"))
        message = str(caught.exception)
        self.assertIn("https://huggingface.co/black-forest-labs/FLUX.1-schnell", message)
        self.assertIn("HF_TOKEN", message)

    def test_missing_secret_on_a_gated_model_names_the_colab_secret(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_access("narration", secret_error=KeyError("HF_TOKEN"),
                            auth_error=PermissionError("401"))
        self.assertIn("key icon", str(caught.exception))

    def test_access_ok_exports_the_token_for_later_downloads(self):
        seen, token = self.run_access("stills", secret="hf_token_value")
        self.assertEqual(seen["call"], ("black-forest-labs/FLUX.1-schnell", "hf_token_value"))
        self.assertEqual(token, "hf_token_value")

    def test_open_model_runs_without_a_secret(self):
        seen, token = self.run_access("music", secret_error=KeyError("HF_TOKEN"))
        self.assertEqual(seen["call"], ("ACE-Step/ACE-Step-v1-3.5B", None))


class PositivePromptTests(unittest.TestCase):
    """FLUX.1-schnell runs at guidance 0 with no negative prompt: 'no bindi' paints a bindi.
    Owner 2026-11-24: stills prompts are positive-only, and a redone shot gets candidates."""
    setUp, build, nb = ColabJobTests.setUp, ColabJobTests.build, ColabJobTests.nb
    payload = HouseStyleTests.payload

    def stills(self, *items):
        return self.build("stills", {"items": list(items)})

    def test_house_style_is_the_approved_positive_text(self):
        self.assertEqual(colab_jobs.HOUSE_STYLE, (
            "Earnalism house style: 2D animated feature-film illustration, clean confident line art, "
            "soft cel shading with gentle painterly gradients, expressive faces with large luminous "
            "eyes, consistent character designs, cinematic composition, clean image edges and plain "
            "uncluttered corners, hand-drawn cel animation look."))
        self.assertEqual(colab_jobs.negative_words(colab_jobs.HOUSE_STYLE), [])
        r = self.stills({"key": "a", "prompt": "a lamp on a sill", "seed": 1})
        self.assertTrue(self.payload(r)["items"][0]["prompt"].endswith(colab_jobs.HOUSE_STYLE))

    def test_each_negative_word_is_refused(self):
        for word, prompt in (("no", "Hemshashi, No bindi"), ("not", "a judge, not bearded"),
                             ("without", "a sari without borders"), ("never", "never smiling"),
                             ("none", "jewellery: none"), ("nor", "neither rings nor bangles"),
                             ("n't", "a judge who doesn't wear a beard")):
            with self.subTest(word=word):
                with self.assertRaises(ValueError) as caught:
                    self.stills({"key": "f01s002-1", "prompt": prompt, "seed": 1})
                msg = str(caught.exception)
                self.assertIn("f01s002-1", msg)
                self.assertIn(repr(word), msg)
                self.assertIn("describe what is there instead (e.g. 'bare forehead', "
                              "'clean-shaven')", msg)
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.ledger._load(), [])

    def test_words_that_only_contain_a_negative_are_allowed(self):
        self.stills({"key": "a", "prompt": "snow on a knot of notes, nothing else, a nook, "
                                           "a nordic notice, a nones bell", "seed": 1})

    def test_candidates_expand_into_seeded_files_and_scale_the_forecast(self):
        one = self.stills({"key": "a", "prompt": "a lamp", "seed": 7})
        three = self.stills({"key": "a", "prompt": "a lamp", "seed": 7, "candidates": 3},
                            {"key": "b", "prompt": "a door", "seed": 2})
        items = self.payload(three)["items"]
        self.assertEqual([(i["key"], i["seed"]) for i in items],
                         [("a--c1", 7), ("a--c2", 8), ("a--c3", 9), ("b", 2)])
        self.assertEqual({i["prompt"] for i in items[:3]}, {items[0]["prompt"]})
        self.assertEqual([(i.get("base"), i.get("candidate")) for i in items],
                         [("a", 1), ("a", 2), ("a", 3), (None, None)])
        self.assertEqual(json.loads(Path(three["manifest"]).read_text())["kind"], "stills")
        from eav.budget import MARGIN
        rate = RATES["stills"]
        per_image = colab_jobs.STILLS_STEPS * rate["s_per_step"] * MARGIN / 3600 * rate["units_per_hour"]
        gate = colab_jobs.GATE_PER_STILL_S / 3600 * rate["units_per_hour"]
        # four images against one: the forecast grows by exactly three images' worth (gate seconds included)
        self.assertAlmostEqual(three["forecast_units"] - one["forecast_units"], 3 * (per_image + gate))
        self.assertEqual(colab_jobs.job_items("stills", {"items": [
            {"key": "a", "candidates": 3}, {"key": "b"}]}), 4)
        src = "".join("".join(c["source"]) for c in self.nb(three)["cells"])
        self.assertIn('EXPECTED = [item["key"] + ".png" for item in JOB["items"]]', src)
        self.assertIn("by_text[text] = (pe.cpu(), pooled.cpu())", src)  # one encode per prompt

    def test_candidates_must_be_an_int_from_1_to_4(self):
        for bad in (0, 5, "2", True, 2.0):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as caught:
                    self.stills({"key": "a", "prompt": "a lamp", "seed": 1, "candidates": bad})
                self.assertIn("candidates", str(caught.exception))

    def test_a_key_that_looks_like_a_candidate_file_is_refused(self):
        with self.assertRaises(ValueError):
            self.stills({"key": "a--c2", "prompt": "a lamp", "seed": 1})


class FilmClipsTests(unittest.TestCase):
    """film_clips: Wan 2.2 TI2V-5B beats plus Depth Anything V2 Small depth maps (cinematic film, Task 6)."""
    setUp, build, nb, cells = (ColabJobTests.setUp, ColabJobTests.build, ColabJobTests.nb, ColabJobTests.cells)

    def spec(self, n=2, **kw):
        art = self.root / "art"
        art.mkdir(exist_ok=True)
        (art / "f01s014-12.png").write_bytes(b"png-one")
        items = [{"key": f"f01s014-{i:02}", "image": "f01s014-12.png", "width": 1280, "height": 704,
                  "seed": 41000 + i, "prompt": "A girl slowly turns her face, static locked-off camera.",
                  "continue_from": None} for i in range(n)]
        return {"art_dir": str(art), "items": items, **kw}

    def template(self):
        return (colab_jobs._TEMPLATES / "film_clips_cell.py.txt").read_text()

    def test_film_clips_kind_builds_valid_notebook(self):
        import ast
        r = self.build("film_clips", self.spec())
        codes = self.cells(r)
        for c in codes:
            ast.parse(c)
        src = "\n".join(codes)
        self.assertIn("Wan-AI/Wan2.2-TI2V-5B-Diffusers", src)
        self.assertIn("depth-anything/Depth-Anything-V2-Small-hf", src)
        self.assertIn("MIN_VRAM_GIB = 21", src)
        self.assertIn("quality=10", src)
        self.assertEqual(codes[0], "RUN = False")
        for c in codes[1:]:
            self.assertIn("RUN is not True", c)
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            job = json.loads(z.read("job.json"))
            self.assertIn("f01s014-12.png", z.namelist())
        self.assertEqual(job["kind"], "film_clips")
        self.assertEqual([i["key"] for i in job["items"]], ["f01s014-00", "f01s014-01"])
        self.assertEqual(job["frames"], 121)
        self.assertEqual(job["fps"], 24)

    def test_film_clips_forecast_uses_measured_rates(self):
        r = self.build("film_clips", self.spec(4))
        rate = RATES["film_clips"]
        setup = rate["decode_s"] + rate["export_s"]
        self.assertAlmostEqual(r["forecast_units"], (4 * 900 * 1.15 + setup) / 3600 * 2.4)

    def test_film_clips_forecast_sd_and_a100(self):
        spec = self.spec(2)
        for i in spec["items"]:
            i["width"], i["height"] = 896, 512
        sd = self.build("film_clips", spec)
        setup = 900 + 120
        self.assertAlmostEqual(sd["forecast_units"], (2 * 435 * 1.15 + setup) / 3600 * 2.4)
        big = self.spec(2, min_vram_gib=30, job_id="film-a100")
        a100 = self.build("film_clips", big)
        self.assertAlmostEqual(a100["forecast_units"], (2 * 215 * 1.15 + setup) / 3600 * 4.5)
        nb = self.nb(a100)
        self.assertEqual(nb["metadata"]["colab"]["gpuType"], "A100")
        self.assertIn("MIN_VRAM_GIB = 30", "\n".join(self.cells(a100)))

    def test_film_clips_forecast_rides_the_ledger(self):
        r = self.build("film_clips", self.spec(2))
        self.assertAlmostEqual(self.ledger.spent("garden-book", "2026-11"), r["forecast_units"])
        with self.assertRaises(BudgetExceeded):
            self.build("film_clips", self.spec(120, job_id="film-big"))

    def test_film_clips_resume_skips_finished_keys(self):
        t = self.template()
        start = t.index("# --- journal helper begin")
        end = t.index("# --- journal helper end")
        g = {"RUN": True}
        import hashlib as _h, pathlib as _p
        exec("import hashlib, json, pathlib\n" + t[start:end], g)
        out = _p.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(out, ignore_errors=True))
        (out / "a.mp4").write_bytes(b"clip-a")
        (out / "b.mp4").write_bytes(b"clip-b")
        (out / "done.json").write_text(json.dumps({
            "a": _h.sha256(b"clip-a").hexdigest(),    # finished
            "b": _h.sha256(b"other").hexdigest(),     # recorded but the file differs: redo
            "c": _h.sha256(b"gone").hexdigest()}))    # recorded but the file is missing: redo
        self.assertEqual(g["remaining_keys"](out, ["a", "b", "c", "d"]), ["b", "c", "d"])
        (out / "done.json").unlink()
        self.assertEqual(g["remaining_keys"](out, ["a", "b"]), ["a", "b"])
        g["record_done"](out, "a")
        self.assertEqual(g["remaining_keys"](out, ["a", "b"]), ["b"])

    def test_film_clips_negative_prompt_lists_hand_and_eye_terms(self):
        r = self.build("film_clips", self.spec())
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            neg = json.loads(z.read("job.json"))["negative_prompt"].lower()
        for term in ("detached hand", "disembodied hand", "floating hand", "extra hand", "extra arm",
                     "floating object", "objects flying", "blink", "closed eyes", "morphing eyelids",
                     "transparent cloth", "camera movement"):
            self.assertIn(term, neg)

    def test_film_clips_refuses_depth_base_or_large(self):
        for repo in ("depth-anything/Depth-Anything-V2-Base-hf", "depth-anything/Depth-Anything-V2-Large-hf"):
            with self.assertRaises(ValueError) as caught:
                self.build("film_clips", self.spec(depth_repo=repo))
            self.assertIn("Depth-Anything-V2-Small-hf", str(caught.exception))
        self.build("film_clips", self.spec(depth_repo="depth-anything/Depth-Anything-V2-Small-hf"))
        t = self.template()
        self.assertIn('DEPTH_REPO != "depth-anything/Depth-Anything-V2-Small-hf"', t)

    def test_film_clips_licence_allowlist_is_apache_only_for_both_repos(self):
        src = "\n".join(self.cells(self.build("film_clips", self.spec())))
        self.assertIn("LICENCE_ALLOWLIST = ('apache-2.0',)", src)
        self.assertIn("LICENCE_REPOS = (MODEL_REPO, DEPTH_REPO)", src)

    def test_film_clips_template_checks_vram_deadline_and_outputs(self):
        t = self.template()
        for needle in ("if not may_start(", "EXPECTED", ".last.png", ".last-depth.png", ".depth.png",
                       "quality=10", "done.json", "np.uint16"):
            self.assertIn(needle, t)

    def test_film_clips_item_validation(self):
        bad = [({"items": []}, "at least one"),
               ({"items": [{"key": "a", "image": "f01s014-12.png", "width": 1000, "height": 704, "seed": 1,
                            "prompt": "p", "continue_from": None}]}, "1280x704 or 896x512"),
               ({"items": [{"key": "a", "image": "f01s014-12.png", "width": 1280, "height": 704, "seed": 1,
                            "prompt": "p", "continue_from": "zz"}]}, "continue_from")]
        for patch_, word in bad:
            spec = self.spec()
            spec.update(patch_)
            with self.assertRaises(ValueError) as caught:
                self.build("film_clips", spec)
            self.assertIn(word, str(caught.exception))
        spec = self.spec(2)
        spec["items"][1]["key"] = spec["items"][0]["key"]
        with self.assertRaises(ValueError):
            self.build("film_clips", spec)
        # a continuation starts from the earlier clip's last frame and may omit its own image
        spec = self.spec(2)
        spec["items"][1].update(continue_from=spec["items"][0]["key"], image=None)
        self.build("film_clips", spec)

    # --- fix round 1 -----------------------------------------------------------------------
    def test_film_clips_config_bakes_measured_seconds_per_resolution(self):
        src = "\n".join(self.cells(self.build("film_clips", self.spec())))
        self.assertIn("CLIP_S = {'hd': 900, 'sd': 435}", src)
        a100 = "\n".join(self.cells(self.build("film_clips", self.spec(min_vram_gib=30, job_id="film-a"))))
        self.assertIn("CLIP_S = {'hd': 215, 'sd': 435}", a100)

    def test_film_clips_may_start_uses_per_resolution_estimates(self):
        import sys, time, types
        t = self.template()
        helper = t[t.index("# --- estimate helper begin"):t.index("# --- estimate helper end")]
        clock = next(c for c in self.cells(self.build("film_clips", self.spec())) if "def may_start" in c)
        colab = types.ModuleType("google.colab")
        colab.runtime = types.SimpleNamespace(unassign=lambda: None)
        google = types.ModuleType("google")
        google.colab = colab
        g = {"RUN": True, "DEADLINE_SECONDS": 1000, "MANIFEST_RESERVE_S": 60, "CLIP_S": {"hd": 900, "sd": 435}}
        with patch.dict(sys.modules, {"google": google, "google.colab": colab}):
            exec(clock, g)
        exec(helper, g)
        g["JOB_STARTED"] = time.time() - 500          # about 500 s left
        hd = {"width": 1280, "height": 704}
        sd = {"width": 896, "height": 512}
        self.assertTrue(g["may_start"](g["clip_need"](sd, {})))                 # 435 + 60 fits
        self.assertFalse(g["may_start"](g["clip_need"](hd, {})))                # the first clip is HD
        g["INCOMPLETE"] = False
        self.assertFalse(g["may_start"](g["clip_need"](hd, {"sd": 100.0})))     # an SD last time says nothing about HD
        g["INCOMPLETE"] = False
        self.assertFalse(g["may_start"](g["clip_need"](sd, {"sd": 460.0})))     # the last SD clip was slower
        self.assertEqual(g["clip_need"](hd, {"hd": 950.0}), 950.0)

    def test_film_clips_export_has_no_silent_quality_fallback(self):
        t = self.template()
        self.assertEqual(t.count("export_to_video(frames"), 1)  # no second, softer export call
        self.assertNotIn("fps=FPS)\n", t)  # every export passes quality=10
        self.assertIn("except TypeError as e:\n            raise RuntimeError", t)
        self.assertIn("quality=10", t)
        self.assertIn("near-lossless", t)
        self.assertIn("raise RuntimeError", t[t.index("quality=10") - 400:t.index("quality=10") + 600])


class StillsGateTests(unittest.TestCase):
    """Task 11: the character-and-period gate cell after the stills (Colab) and its anchor input."""
    setUp, build, nb, cells = (ColabJobTests.setUp, ColabJobTests.build, ColabJobTests.nb, ColabJobTests.cells)

    def stills(self, **kw):
        return self.build("stills", {"items": [{"key": "a", "prompt": "a lamp", "seed": 1, "candidates": 2}], **kw})

    def gate_src(self, r=None):
        r = r or self.stills()
        return next(c for c in self.cells(r) if "GATE_LABELS" in c)

    def gate_ns(self):
        src = self.gate_src()
        ns = {}
        exec(src[src.index("GATE_LICENCE_ALLOWLIST ="):src.index("# --- gate helper end")], ns)
        return ns

    def test_stills_notebook_has_gate_cell_and_allowlist(self):
        import ast
        codes = self.cells(self.stills())
        gate = self.gate_src(self.stills(job_id="stills-b"))
        ast.parse(gate)
        idx = [i for i, c in enumerate(codes) if "GATE_LABELS" in c]
        self.assertEqual(len(idx), 1)
        self.assertGreater(idx[0], max(i for i, c in enumerate(codes) if "def look_first" in c))
        self.assertLess(idx[0], min(i for i, c in enumerate(codes) if "manifest.json written" in c))
        self.assertIn("RUN is not True", gate)
        for label in ("gas cylinder", "air conditioner", "electric cable", "spotlight", "modern eyeglasses",
                      "plastic", "utility pole", "modern high-rise building"):
            self.assertIn(label, gate)
        for model in ("google/owlv2-base-patch16-ensemble", "facebook/dinov2-small", "face_landmarker",
                      "hand_landmarker"):
            self.assertIn(model, gate)
        self.assertNotIn("clip-vit", gate)   # CLIP's card puts any deployed use out of scope
        self.assertIn("GATE_LICENCE_ALLOWLIST = ('apache-2.0', 'mit')", gate)
        self.assertIn(".gate.json", gate)
        self.assertIn("_gate_time_ok(", gate)
        self.assertNotIn("may_start(", gate)   # running out of time must not mark the stills INCOMPLETE
        self.assertIn("mediapipe", colab_jobs.PACKAGES["stills"])

    def test_gate_is_guarded_so_a_failure_cannot_stop_the_manifest(self):
        gate = self.gate_src()
        # the intent is recorded before anything can fail; pip, imports and model loads sit in run_gate,
        # which is called inside try/except
        self.assertLess(gate.index('MODEL_INFO["gate"] = GATE_INFO'), gate.index("def run_gate"))
        self.assertIn("try:\n    run_gate()\nexcept Exception", gate)
        self.assertNotIn("check=True", gate[:gate.index("def _load_models")])
        self.assertEqual(gate.count('"pip", "install"'), 1)
        self.assertLess(gate.index("def _load_models"), gate.index('"pip", "install"'))
        self.assertIn("try:\n        subprocess.run([sys.executable", gate)

    def test_gate_plan_skips_when_incomplete_or_short_of_time(self):
        plan = self.gate_ns()["gate_plan"]
        self.assertEqual(plan(5000, False, 10, 300, 6, 60), (True, None))
        self.assertEqual(plan(5000, True, 10, 300, 6, 60)[0], False)           # INCOMPLETE: skip
        run, why = plan(400, False, 10, 300, 6, 60)                            # needs 300 + 60 + 60
        self.assertFalse(run)
        self.assertIn("400", why)
        self.assertEqual(plan(420, False, 10, 300, 6, 60), (True, None))

    def test_gate_licence_check_fails_closed(self):
        ns = self.gate_ns()
        g = ns["gate_licence"]
        self.assertEqual(g("m", "Apache-2.0", "mit"), ("apache-2.0", None))
        self.assertEqual(g("m", None, "mit")[0], "mit")                        # card read, no licence field
        self.assertIn("declared", g("m", None, "mit")[1])
        self.assertIsNone(g("m", "cc-by-nc-4.0", "mit")[0])
        self.assertIsNone(g("m", None, None)[0])
        self.assertIsNone(g("m", None, "gpl-3.0")[0])
        lic, why = g("owlv2", None, "apache-2.0", card_read=False)             # card unreadable: not loaded
        self.assertIsNone(lic)
        self.assertIn("could not be read", why)
        self.assertIsNone(g("owlv2", "apache-2.0", "apache-2.0", card_read=False)[0])

    def test_models_load_only_at_the_checked_revision(self):
        gate = self.gate_src()
        self.assertIn("revision=rev", gate)
        self.assertNotIn("revision=None", gate)
        self.assertIn("rev, read = info.sha, bool(info.sha)", gate)

    def test_eyes_and_frontal_from_landmarks(self):
        ns = self.gate_ns()
        self.assertEqual(ns["face_report"](ns["synthetic_face"](open_eyes=2, yaw=0.5)), {"eyes": 2, "frontal": True})
        self.assertEqual(ns["face_report"](ns["synthetic_face"](open_eyes=1, yaw=0.5)), {"eyes": 1, "frontal": True})
        self.assertEqual(ns["face_report"](ns["synthetic_face"](open_eyes=1, yaw=0.9)), {"eyes": 1, "frontal": False})

    def test_hand_attachment_heuristic(self):
        ns = self.gate_ns()
        person = [(100, 100, 500, 900)]
        self.assertIs(ns["hand_detached"]((300, 800), person, [], 1000.0), False)
        self.assertIs(ns["hand_detached"]((900, 300), person, [], 1000.0), True)
        self.assertIsNone(ns["hand_detached"]((900, 300), [], [], 1000.0))

    def test_crop_box_is_the_largest_person_box_clipped(self):
        cb = self.gate_ns()["crop_box"]
        self.assertEqual(cb([(10, 10, 100, 100), (50, -20, 400, 600)], (300, 500)), (50, 0, 300, 500))
        self.assertIsNone(cb([], (300, 500)))
        self.assertIsNone(cb([(10, 10, 20, 20)], (300, 500)))

    def test_decide_matrix(self):
        ns = self.gate_ns()
        d = ns["decide"]
        ok_face = [{"eyes": 2, "frontal": True}]
        base = dict(faces=ok_face, hands=[False], anachronisms=[], possible=[], similarity=0.9, anchor=True)
        r = d(**base)
        self.assertEqual((r["pass"], r["needs_review"], r["eyes"], r["hands_detached"]), (True, False, 2, False))
        self.assertTrue(set(r) >= {"eyes", "hands_detached", "anachronisms", "anchor_similarity", "pass",
                                   "needs_review"})
        r = d(**{**base, "faces": [{"eyes": 1, "frontal": True}]})
        self.assertEqual((r["pass"], r["needs_review"]), (False, False))        # frontal with one eye: certain fail
        r = d(**{**base, "faces": [{"eyes": 1, "frontal": False}]})
        self.assertEqual((r["pass"], r["needs_review"]), (False, True))
        r = d(**{**base, "hands": [True]})
        self.assertEqual((r["pass"], r["needs_review"], r["hands_detached"]), (False, False, True))
        r = d(**{**base, "hands": [None]})
        self.assertEqual((r["pass"], r["needs_review"]), (False, True))
        r = d(**{**base, "anachronisms": ["gas cylinder"]})
        self.assertEqual((r["pass"], r["needs_review"], r["anachronisms"]), (False, False, ["gas cylinder"]))
        r = d(**{**base, "possible": ["plastic"]})
        self.assertEqual((r["pass"], r["needs_review"]), (False, True))
        r = d(**{**base, "similarity": 0.1})
        self.assertEqual((r["pass"], r["needs_review"]), (False, True))         # never an automatic fail
        for k in ("faces", "hands", "anachronisms", "similarity"):               # a check that did not run
            r = d(**{**base, k: None})
            self.assertEqual((r["pass"], r["needs_review"]), (False, True), k)
        r = d(**{**base, "faces": []})                                           # character expected, no face
        self.assertEqual((r["pass"], r["needs_review"]), (False, True))
        r = d(faces=[], hands=[], anachronisms=[], possible=[], similarity=None, anchor=False)
        self.assertEqual((r["pass"], r["needs_review"], r["anchor_similarity"]), (True, False, None))
        # a fail that also has something unclear is a certain fail (needs_review false): pick keys on that
        r = d(**{**base, "anachronisms": ["plastic"], "hands": [None]})
        self.assertEqual((r["pass"], r["needs_review"]), (False, False))

    def test_no_hands_detected_is_a_valid_result_a_model_error_is_not(self):
        d = self.gate_ns()["decide"]
        base = dict(faces=[{"eyes": 2, "frontal": True}], anachronisms=[], possible=[], similarity=None,
                    anchor=False)
        none_found = d(hands=[], **base)
        self.assertEqual((none_found["pass"], none_found["notes"]), (True, []))
        broke = d(hands=None, errors={"hands": "RuntimeError: hand model not loaded"}, **base)
        self.assertEqual((broke["pass"], broke["needs_review"]), (False, True))
        self.assertIn("hand check did not run: RuntimeError: hand model not loaded", broke["notes"])
        owl = d(**{**base, "anachronisms": None, "possible": None}, hands=[],
                errors={"owl": "AttributeError: post_process"})
        self.assertIn("period check did not run: AttributeError: post_process", owl["notes"])

    def test_owl_post_processing_works_under_either_transformers_name(self):
        ns = self.gate_ns()
        texts = ["gas cylinder", "person"]
        calls = []

        class Newer:
            def post_process_grounded_object_detection(self, outputs, threshold, target_sizes, text_labels):
                calls.append(("grounded", text_labels))
                return [{"scores": [0.4], "text_labels": ["gas cylinder"], "labels": [0], "boxes": [[1, 2, 3, 4]]}]

        class Older:
            def post_process_object_detection(self, outputs, threshold, target_sizes):
                calls.append(("legacy", None))
                return [{"scores": [0.2], "labels": [1], "boxes": [[5, 6, 7, 8]]}]

        class Neither:
            pass
        self.assertEqual(ns["owl_detect"](Newer(), object(), None, 0.15, texts), [(0.4, "gas cylinder", [1.0, 2.0, 3.0, 4.0])])
        self.assertEqual(ns["owl_detect"](Older(), object(), None, 0.15, texts), [(0.2, "person", [5.0, 6.0, 7.0, 8.0])])
        self.assertEqual([c[0] for c in calls], ["grounded", "legacy"])
        self.assertEqual(calls[0][1], [texts])
        with self.assertRaises(AttributeError):
            ns["owl_detect"](Neither(), object(), None, 0.15, texts)

    def test_anchor_goes_into_inputs_zip_and_candidates_inherit_it(self):
        art = self.root / "anchors"
        art.mkdir()
        (art / "hemshashi.png").write_bytes(b"anchor-png")
        r = self.build("stills", {"art_dir": str(art), "items": [
            {"key": "a", "prompt": "a lamp", "seed": 1, "candidates": 2, "anchor": "hemshashi.png"},
            {"key": "b", "prompt": "a door", "seed": 5}]})
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            job = json.loads(z.read("job.json"))
            self.assertEqual(z.read("anchors/hemshashi.png"), b"anchor-png")
        by = {i["key"]: i for i in job["items"]}
        self.assertEqual(by["a--c1"]["anchor"], "anchors/hemshashi.png")
        self.assertEqual(by["a--c2"]["anchor"], "anchors/hemshashi.png")
        self.assertNotIn("anchor", by["b"])

    def test_anchor_must_be_a_png_in_art_dir(self):
        art = self.root / "anchors"
        art.mkdir()
        for bad, spec in (("../x.png", {}), ("missing.png", {"art_dir": str(art)}),
                          ("a.jpg", {"art_dir": str(art)}), ("a.png", {})):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as c:
                    self.build("stills", {**spec, "items": [{"key": "a", "prompt": "a lamp", "seed": 1,
                                                             "anchor": bad}]})
                self.assertIn("anchor", str(c.exception))


class SfxCellTests(unittest.TestCase):
    """Task 11: the optional CC0 sound fetch of a film_clips job (Wikimedia Commons, no key)."""
    setUp, build, nb, cells = (ColabJobTests.setUp, ColabJobTests.build, ColabJobTests.nb, ColabJobTests.cells)
    spec = FilmClipsTests.spec

    def template(self):
        return (colab_jobs._TEMPLATES / "sfx_cell.py.txt").read_text()

    def ns(self, **extra):
        t = self.template()
        ns = {"RUN": True}
        # everything but the final dispatch (which needs the Colab OUT_DIR/JOB); extras override after
        exec(t[t.index("import json, re, time"):t.index("if (OUT_DIR / \"sfx-licences.json\").is_file()")], ns)
        ns.update(extra)
        return ns

    def test_sfx_cell_keeps_only_cc0_or_worldwide_public_domain(self):
        ok = self.ns()["sfx_licence_ok"]
        for lic in ("CC0", "CC0 1.0", "Public domain", "public domain", "PD", "cc-0"):
            self.assertTrue(ok(lic), lic)
        # country-limited public-domain tags and every attribution licence are refused (47-region policy)
        for lic in ("PD-US", "PD-USGov", "PD-USGov-NASA", "PD-old-70", "PD-old", "PD-Art", "PD-UK-unknown",
                    "Public domain in the US", "CC BY 4.0", "CC BY-SA 3.0", "GFDL", "", None, "Attribution",
                    "CC BY-NC 4.0"):
            self.assertFalse(ok(lic), lic)

    def test_extension_comes_from_the_url_path_never_the_query(self):
        ns = self.ns()
        url = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Birds.ogg?utm_source=x&utm_campaign=org&utm_x=1.org"
        self.assertEqual(ns["sfx_ext"](url), "ogg")
        self.assertEqual(ns["sfx_ext"]("https://u.org/a/b/Crow.OGA"), "oga")
        self.assertIsNone(ns["sfx_ext"]("https://u.org/a/b/noext?x=.ogg"))
        self.assertIsNone(ns["sfx_ext"]("https://u.org/a/b/Page.html"))
        name = ns["sfx_filename"]("birds", 1, ns["sfx_ext"](url))
        self.assertEqual(name, "sfx-birds-1.ogg")
        self.assertRegex(name, r"^[A-Za-z0-9._-]+$")
        self.assertIsNone(ns["sfx_filename"]("birds", 1, None))
        self.assertIsNone(ns["sfx_filename"]("bi rds&x", 1, "ogg"))

    def test_relevance_needs_a_whole_query_word_in_the_file_title(self):
        rel = self.ns()["sfx_relevant"]
        self.assertFalse(rel("File:Tooth brushing.ogg", "broom sweeping"))
        self.assertFalse(rel("File:Berlin mall ambience.ogg", "crowd murmur"))
        self.assertTrue(rel("File:Crowd in a market.ogg", "crowd murmur"))
        self.assertTrue(rel("File:Crow call 3.ogg", "crows cawing morning"))   # plural stem
        self.assertFalse(rel("File:Crowd noise.ogg", "crows cawing morning"))  # "crow" is not "crowd"
        self.assertTrue(rel("File:Crows at dawn.ogg", "crows cawing morning"))
        self.assertTrue(rel("File:Broom sweeping floor.wav", "broom sweeping"))
        self.assertFalse(rel("File:Anything.ogg", "of the"))

    def meta(self, title, lic, url="https://upload.wikimedia.org/x/Crow.ogg?utm_a=b", size=1000, code=None,
             cats=None):
        """A page as the Commons API returns it: imageinfo.extmetadata (LicenseShortName, License) plus
        prop=categories (hidden ones included: licence categories live there)."""
        code = code if code is not None else {"CC0": "cc0", "Public domain": "pd"}.get(lic, "")
        page = {"title": title, "imageinfo": [{"url": url, "size": size, "descriptionurl": "https://c/wiki/" + title,
                                               "extmetadata": {"LicenseShortName": {"value": lic},
                                                               "License": {"value": code},
                                                               "Artist": {"value": "<a>Ann</a>"}}}]}
        if cats is not None:
            page["categories"] = [{"ns": 14, "title": "Category:" + c} for c in cats]
        return page

    def test_pick_files_applies_licence_relevance_extension_and_size(self):
        ns = self.ns()
        pages = [self.meta("File:Crow call.ogg", "CC BY 4.0"),
                 self.meta("File:Crow flock.ogg", "CC0"),
                 self.meta("File:Mall.ogg", "CC0"),
                 self.meta("File:Crow US.ogg", "PD-US"),
                 self.meta("File:Crow nasa.ogg", "Public domain", cats=["PD NASA", "PD-USGov-NASA"]),
                 self.meta("File:Crow big.ogg", "CC0", size=99_000_000),
                 self.meta("File:Crow page.ogg", "CC0", url="https://u.org/Crow"),
                 self.meta("File:Crow morning.ogg", "Public domain", cats=["PD-self", "Self-published work"])]
        got = ns["sfx_pick"](pages, "crows cawing", "crows", limit=2)
        self.assertEqual([g["file"] for g in got], ["sfx-crows-1.ogg", "sfx-crows-2.ogg"])
        self.assertEqual([g["title"] for g in got], ["File:Crow flock.ogg", "File:Crow morning.ogg"])
        self.assertEqual(got[0]["licence"], "CC0")
        self.assertEqual(got[0]["basis"]["rule"], "cc0")
        self.assertEqual(got[1]["basis"], {"rule": "author-release", "categories": ["PD-self", "Self-published work"]})
        self.assertEqual(got[0]["author"], "Ann")
        self.assertTrue(got[0]["page"].startswith("https://commons.wikimedia.org/wiki/File:Crow_flock"))

    def test_public_domain_needs_an_author_release_basis_and_no_country_or_age_basis(self):
        """Commons reports PD-USGov-NASA and PD-old/PD-Art files as LicenseShortName "Public domain" /
        License "pd", so the licence field alone cannot tell worldwide from country-limited public domain."""
        pick = self.ns()["sfx_pick"]

        def kept(page):
            return [g["title"] for g in pick([page], "crow", "crows")]
        nasa = self.meta("File:Crow nasa.ogg", "Public domain", cats=["PD NASA", "PD-USGov-NASA", "Audio files"])
        old = self.meta("File:Crow old.ogg", "Public domain", cats=["PD-old-70", "PD-Art (PD-old-100)"])
        usgov = self.meta("File:Crow gov.ogg", "Public domain", cats=["Works of the United States government"])
        exempt = self.meta("File:Crow ex.ogg", "Public domain", cats=["PD-self", "PD-Italy-exempt"])
        mixed = self.meta("File:Crow mix.ogg", "Public domain", cats=["PD-self", "PD-US"])
        us_only = self.meta("File:Crow usonly.ogg", "Public domain", cats=["PD US", "Self-published work"])
        none_known = self.meta("File:Crow unk.ogg", "Public domain", cats=["Audio files", "Birds"])
        uncategorised = self.meta("File:Crow nocat.ogg", "Public domain")          # categories not returned
        wrong_code = self.meta("File:Crow code.ogg", "Public domain", code="cc-by", cats=["PD-self"])
        cc0 = self.meta("File:Crow cc0.ogg", "CC0", cats=[])                       # CC0 needs no category
        self_pd = self.meta("File:Crow self.ogg", "Public domain", cats=["PD-self", "Self-published work"])
        released = self.meta("File:Crow rel.ogg", "Public domain", cats=["Public domain due to author's release"])
        selfpub = self.meta("File:Crow pub.ogg", "Public domain", cats=["Self-published work"])
        for page in (nasa, old, usgov, exempt, mixed, us_only, none_known, uncategorised, wrong_code):
            self.assertEqual(kept(page), [], page["title"])
        for page in (cc0, self_pd, released, selfpub):
            self.assertEqual(kept(page), [page["title"]], page["title"])
        got = pick([self_pd], "crow", "crows")[0]
        self.assertEqual(got["basis"], {"rule": "author-release", "categories": ["PD-self", "Self-published work"]})
        self.assertEqual(pick([cc0], "crow", "crows")[0]["basis"], {"rule": "cc0", "categories": []})

    def test_the_stage_asks_for_categories_in_the_same_imageinfo_query(self):
        urls = []
        out = self.root / "out"
        out.mkdir()

        def opener(url):
            urls.append(url)
            if "list=search" in url:
                return {"query": {"search": [{"title": "File:Crow self.ogg"}]}}
            return {"query": {"pages": {"1": self.meta("File:Crow self.ogg", "Public domain",
                                                       cats=["PD-self", "Self-published work"])}}}
        ns = self.ns(OUT_DIR=out, JOB={"sfx": {"crows": "crows"}}, _sfx_open=opener,
                     _sfx_fetch=lambda url: b"x", _sfx_sleep=lambda s: None)
        ns["run_sfx_stage"]()
        self.assertEqual(len(urls), 2)                         # one search, one imageinfo+categories query
        self.assertIn("prop=imageinfo%7Ccategories", urls[1])
        self.assertIn("cllimit=max", urls[1])
        lic = json.loads((out / "sfx-licences.json").read_text())
        self.assertEqual(lic["sfx-crows-1.ogg"]["basis"]["rule"], "author-release")

    def test_api_error_response_does_not_raise_and_retries_three_times(self):
        calls = []

        def opener(url):
            calls.append(url)
            return {"error": {"code": "maxlag"}}
        ns = self.ns(_sfx_open=opener, _sfx_sleep=lambda s: None)
        self.assertIsNone(ns["sfx_api"]({"action": "query"}))
        self.assertEqual(len(calls), 3)
        self.assertEqual(ns["sfx_search_pages"]({"error": {"code": "x"}}), [])
        self.assertEqual(ns["sfx_search_pages"](None), [])

    def test_run_never_fails_the_job_and_writes_licences(self):
        out = self.root / "out"
        out.mkdir()
        ns = self.ns(OUT_DIR=out, JOB={"sfx": {"crows": "crows cawing"}}, _sfx_sleep=lambda s: None)

        def boom(url):
            raise OSError("network down")
        ns["_sfx_open"] = boom
        ns["run_sfx_stage"]()                                # must not raise
        self.assertEqual(json.loads((out / "sfx-licences.json").read_text()), {})

    def test_run_downloads_kept_files_with_clean_names(self):
        out = self.root / "out"
        out.mkdir()
        pages = {"query": {"pages": {"1": self.meta("File:Crow flock.ogg", "CC0"),
                                     "2": self.meta("File:Mall.ogg", "CC0")}}}

        def opener(url):
            if "list=search" in url:
                return {"query": {"search": [{"title": "File:Crow flock.ogg"}, {"title": "File:Mall.ogg"}]}}
            return pages
        ns = self.ns(OUT_DIR=out, JOB={"sfx": {"crows": "crows cawing"}}, _sfx_open=opener,
                     _sfx_fetch=lambda url: b"OggS-bytes", _sfx_sleep=lambda s: None)
        ns["run_sfx_stage"]()
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["sfx-crows-1.ogg", "sfx-licences.json"])
        lic = json.loads((out / "sfx-licences.json").read_text())
        self.assertEqual(lic["sfx-crows-1.ogg"]["licence"], "CC0")
        self.assertEqual(set(lic["sfx-crows-1.ogg"]), {"title", "page", "licence", "author", "basis"})
        self.assertEqual(lic["sfx-crows-1.ogg"]["basis"]["rule"], "cc0")

    def test_sfx_spec_adds_the_cell_before_wan_and_reserves_its_budget(self):
        import ast
        plain = self.build("film_clips", self.spec(job_id="film-plain"))
        with_sfx = self.build("film_clips", self.spec(job_id="film-sfx", sfx={"crows": "crows cawing morning"}))
        for c in self.cells(with_sfx):
            ast.parse(c)
        codes = self.cells(with_sfx)
        i_sfx = next(i for i, c in enumerate(codes) if "def run_sfx_stage" in c)
        i_wan = next(i for i, c in enumerate(codes) if "WanImageToVideoPipeline" in c and "def fit" in c)
        i_clock = next(i for i, c in enumerate(codes) if "def may_start" in c)
        i_verify = next(i for i, c in enumerate(codes) if "inputs verified for" in c)
        self.assertTrue(i_clock < i_verify < i_sfx < i_wan)
        self.assertFalse(any("def run_sfx_stage" in c for c in self.cells(plain)))
        self.assertGreater(with_sfx["forecast_units"], plain["forecast_units"])
        self.assertIn("SFX_BUDGET_S = 480", "\n".join(codes))
        with zipfile.ZipFile(with_sfx["inputs_zip"]) as z:
            self.assertEqual(json.loads(z.read("job.json"))["sfx"], {"crows": "crows cawing morning"})
        with zipfile.ZipFile(plain["inputs_zip"]) as z:
            self.assertNotIn("sfx", json.loads(z.read("job.json")))

    def test_sfx_spec_validation(self):
        for bad in ({"Crows": "x"}, {"crows": ""}, {"crows": 5}, ["crows"], {}, {"a b": "x"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as c:
                    self.build("film_clips", self.spec(sfx=bad))
                self.assertIn("sfx", str(c.exception))


class StillsT5LimitTests(unittest.TestCase):
    """FLUX.1-schnell's T5 reads 256 tokens; a longer house-style-first prompt loses its tail (the character
    lines). The builder refuses at a calibrated estimate (no tokenizer is installed locally)."""
    setUp, build, nb, cells = (ColabJobTests.setUp, ColabJobTests.build, ColabJobTests.nb, ColabJobTests.cells)
    FIXTURE = Path(__file__).with_name("fixtures") / "t5_recorded_prompts.json"

    @staticmethod
    def words(n):
        base = ("a veiled mother stands at the courtyard gate holding a brass pot while crows gather "
                "on the clay wall behind her and morning light crosses the dusty ground").split()
        return " ".join((base * (n // len(base) + 1))[:n]) + "."

    def test_estimate_is_calibrated_to_count_long_words_and_punctuation_higher(self):
        est = colab_jobs.estimate_t5_tokens
        self.assertEqual(est("a lamp"), 2)
        self.assertEqual(est("extraordinarily, beautifully"), 5)   # 2 x 1.8 + 0.5, rounded up
        self.assertEqual(colab_jobs.T5_ESTIMATE_LIMIT, 180)

    def test_every_recorded_truncated_prompt_is_refused_and_the_clean_pilot6_prompt_passes(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        est = lambda p: colab_jobs.estimate_t5_tokens(p.rstrip() + " " + colab_jobs.HOUSE_STYLE)
        self.assertEqual(sorted(data["truncated"]), ["stills-film-01-r10", "stills-film-01-r8-house",
                                                     "stills-film-01-r9", "stills-pilot2-f01s014",
                                                     "stills-pilot4-f01s014", "stills-pilot5-f01s014"])
        for job, prompts in data["truncated"].items():
            for key, prompt in prompts.items():
                with self.subTest(job=job, key=key):
                    with self.assertRaises(ValueError) as c:
                        self.build("stills", {"items": [{"key": "a", "prompt": prompt, "seed": 1}]})
                    self.assertIn("'a'", str(c.exception))
                    self.assertRegex(str(c.exception), r"about \d+ tokens")
                    self.assertGreater(est(prompt), colab_jobs.T5_ESTIMATE_LIMIT)
        for prompt in data["clean"]["stills-pilot6-f01s014"].values():
            self.assertEqual(len(prompt.split()), 85)
            self.assertLessEqual(est(prompt), colab_jobs.T5_ESTIMATE_LIMIT)
            self.build("stills", {"items": [{"key": "a", "prompt": prompt, "seed": 1}]})

    def test_a_210_word_prompt_is_refused_and_a_short_one_passes(self):
        with self.assertRaises(ValueError) as c:
            self.build("stills", {"items": [{"key": "f01s014-3", "prompt": self.words(210), "seed": 1}]})
        self.assertIn("f01s014-3", str(c.exception))
        self.assertEqual(list(self.out.iterdir()), [])
        self.build("stills", {"items": [{"key": "a", "prompt": self.words(60), "seed": 1}]})
