"""Edit: instruction-following repair of held film shots with Qwen-Image-Edit-2511 (Apache-2.0).

Open text-to-image models drew some shots wrong in ways a mask cannot fix: a child widow with a
bindi or jewellery or looking too young, a judge with a beard, the Giant at the wrong scale, snow
inside a room, fruit out of season, palms missing their reverent marks. Owner 2026-11-25: fix
them with an instruction-following image editor (the still to edit first, then up to two
reference images), as candidates, then review and pick. The model has a real negative prompt and
"remove ..." instructions are the point, so the positive-only wording rule does not apply."""
import contextlib
import hashlib
import io
import json
import math
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from eav import cli, colab_jobs, exchange, importer
from eav.budget import MARGIN, Ledger
from eav.importer import ImportHeld
from eav.record import Record

RATES = {k: {"s_per_step": 1.0, "units_per_hour": 10.0, "decode_s": 30, "export_s": 20}
         for k in ("narration", "stills", "music", "retouch", "edit")}
BASE_JOB = "stills-film-01-r5"
CAND_JOB = "stills-film-01-r9"
RETOUCH_JOB = "retouch-film-01-r1"
TOUCHUP_JOB = "touchup-film-01-r1"
OTHER_FILM_JOB = "stills-film-02-r1"
SOURCE_FILE = "f01s007-4--c2.png"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def png(colour=(200, 120, 90), size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


def imported(rec, kind, job_id, target, files: dict):
    """An imported image job exactly as the record keeps one (target, artifacts, accepted)."""
    rec.event("cli", "job_target", {"job_id": job_id, "target": target, "kind": kind})
    folder = rec.root / kind / job_id
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
        art = f"{kind}_mask" if name.endswith("--mask.png") else kind
        rec.add_artifact(art, folder / name, {"job_id": job_id, "job_kind": kind})
    rec.event("import", "accepted", {"job_id": job_id, "kind": kind})


def item(**over):
    base = {"key": "f01s007-4", "source": {"job": CAND_JOB, "file": SOURCE_FILE},
            "refs": [{"job": BASE_JOB, "file": "f01s008-1.png"}],
            "instruction": "Remove the red dot from her forehead and the gold studs from her ears; "
                           "she is a fourteen-year-old widow in a plain white cotton sari.",
            "negative": "bindi, jewellery, earrings, coloured sari border, adult face",
            "seed": 123, "candidates": 2, "steps": 40, "true_cfg_scale": 4.0}
    base.update(over)
    return base


class EditBuildTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.record = Record.create(self.root / "rec", "bicharak", {"x": 1})
        self.ledger = Ledger(self.root / "ledger.json")
        self.out = self.root / "rec" / "jobs"
        self.out.mkdir()
        self.source = png()
        self.ref = png((4, 5, 6))
        imported(self.record, "stills", BASE_JOB, "film-01",
                 {"f01s007-4.png": png((1, 2, 3)), "f01s008-1.png": self.ref})
        imported(self.record, "stills", CAND_JOB, "film-01",
                 {SOURCE_FILE: self.source, "f01s007-4--c1.png": png((9, 9, 9))})
        imported(self.record, "retouch", RETOUCH_JOB, "film-01",
                 {"f01s008-1--c1.png": png((7, 7, 7)), "f01s008-1--mask.png": png((255, 255, 255))})
        imported(self.record, "touchup", TOUCHUP_JOB, "film-01",
                 {"f01s007-4--c1.png": png((8, 8, 8)), "f01s007-4--mask.png": png((0, 0, 0))})
        imported(self.record, "stills", OTHER_FILM_JOB, "film-02", {"f02s001-1.png": png((3, 3, 3))})

    def build(self, *items, **spec):
        return colab_jobs.build_job("edit", self.record,
                                    {"target": "film-01", "items": list(items) or [item()], **spec},
                                    self.ledger, RATES, self.out, month="2026-11")

    def refused(self, *items, words=(), **spec):
        with self.assertRaises(ValueError) as caught:
            self.build(*items, **spec)
        for w in words:
            self.assertIn(w, str(caught.exception))
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.ledger._load(), [])
        return str(caught.exception)

    def payload(self, r):
        with zipfile.ZipFile(r["inputs_zip"]) as z:
            return json.loads(z.read("job.json")), {n: z.read(n) for n in z.namelist()}

    def src(self, r):
        nb = json.loads(Path(r["notebook"]).read_text())
        return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]

    # --- spec validation ----------------------------------------------------------------------
    def test_a_valid_spec_builds_one_item_per_candidate_with_source_and_refs_inside(self):
        r = self.build()
        job, files = self.payload(r)
        self.assertEqual(job["kind"], "edit")
        self.assertEqual(job["model"], colab_jobs.EDIT_REPO)
        self.assertEqual([(i["key"], i["seed"]) for i in job["items"]],
                         [("f01s007-4--c1", 123), ("f01s007-4--c2", 124)])
        first = job["items"][0]
        self.assertEqual((first["base"], first["candidate"], first["steps"], first["true_cfg_scale"]),
                         ("f01s007-4", 1, 40, 4.0))
        self.assertEqual(first["source_sha256"], sha(self.source))
        self.assertEqual(files[first["source"]], self.source)
        self.assertEqual(first["source_job"], CAND_JOB)
        self.assertEqual(len(first["refs"]), 1)
        ref = first["refs"][0]
        self.assertEqual((ref["job"], ref["file"], ref["sha256"]), (BASE_JOB, "f01s008-1.png", sha(self.ref)))
        self.assertEqual(files[ref["member"]], self.ref)
        self.assertTrue(first["instruction"].startswith("Remove the red dot"))
        self.assertTrue(first["instruction"].endswith(colab_jobs.EDIT_KEEP))
        self.assertEqual(first["negative"], "bindi, jewellery, earrings, coloured sari border, adult face")
        self.assertEqual(sorted(files), sorted(["job.json", first["source"], ref["member"]]))

    def test_sources_may_come_from_retouch_and_touchup_jobs_and_refs_from_any_film(self):
        r = self.build(item(source={"job": TOUCHUP_JOB, "file": "f01s007-4--c1.png"},
                            refs=[{"job": RETOUCH_JOB, "file": "f01s008-1--c1.png"},
                                  {"job": OTHER_FILM_JOB, "file": "f02s001-1.png"}]))
        job, files = self.payload(r)
        self.assertEqual(job["items"][0]["source_job"], TOUCHUP_JOB)
        self.assertEqual([x["job"] for x in job["items"][0]["refs"]], [RETOUCH_JOB, OTHER_FILM_JOB])
        self.build(item(key="f01s008-1", source={"job": RETOUCH_JOB, "file": "f01s008-1--c1.png"}, refs=[]),
                   job_id="edit-b")

    def test_no_refs_is_allowed_and_more_than_two_is_refused(self):
        three = [{"job": BASE_JOB, "file": "f01s008-1.png"}] * 3
        self.refused(item(refs=three), words=("refs",))
        self.refused(item(refs={"job": BASE_JOB}), words=("refs",))
        self.build(item(refs=[]))
        self.build(item(refs=None), job_id="edit-b")

    def test_a_source_or_ref_whose_bytes_differ_from_the_record_is_refused(self):
        (self.record.root / "stills" / BASE_JOB / "f01s008-1.png").write_bytes(png((0, 0, 0)))
        self.refused(words=("sha256", "f01s008-1.png"))
        (self.record.root / "stills" / BASE_JOB / "f01s008-1.png").write_bytes(self.ref)
        (self.record.root / "stills" / CAND_JOB / SOURCE_FILE).write_bytes(png((0, 0, 0)))
        self.refused(words=("sha256", SOURCE_FILE))

    def test_a_source_that_is_not_a_recorded_image_of_this_film_is_refused(self):
        self.refused(item(source={"job": "stills-nope", "file": SOURCE_FILE}), words=("stills-nope",))
        self.refused(item(source={"job": CAND_JOB, "file": "f01s007-4--c7.png"}),
                     words=("f01s007-4--c7.png",))
        self.refused(item(source={"job": TOUCHUP_JOB, "file": "f01s007-4--mask.png"}),
                     words=("f01s007-4--mask.png",))
        self.refused(item(source={"job": CAND_JOB, "file": "../x/" + SOURCE_FILE}), words=("x",))
        # a recorded image, but of another film
        self.refused(item(key="f01s007-4", source={"job": OTHER_FILM_JOB, "file": "f02s001-1.png"}),
                     words=(OTHER_FILM_JOB,))
        # built but never imported, and imported then closed
        self.record.event("cli", "job_target", {"job_id": "stills-x", "target": "film-01", "kind": "stills"})
        self.refused(item(source={"job": "stills-x", "file": SOURCE_FILE}), words=("stills-x",))
        self.record.event("job", "closed", {"job_id": CAND_JOB})
        self.refused(words=(CAND_JOB,))

    def test_a_ref_that_is_not_a_recorded_image_is_refused(self):
        for ref, word in (({"job": BASE_JOB, "file": "nope.png"}, "nope.png"),
                          ({"job": "stills-nope", "file": "f01s008-1.png"}, "stills-nope"),
                          ({"job": RETOUCH_JOB, "file": "f01s008-1--mask.png"}, "--mask"),
                          ({"file": "f01s008-1.png"}, "ref"), ("f01s008-1.png", "ref")):
            with self.subTest(ref=ref):
                self.refused(item(refs=[ref]), words=(word,))

    def test_a_key_outside_the_film_or_not_the_sources_key_is_refused(self):
        self.refused(item(key="f09s001-1"), words=("f09s001-1",))
        self.refused(item(key="f01s008-1"), words=("f01s008-1",))  # source is f01s007-4's file
        self.refused(item(key="f01s007-4--c1"), words=("--cN",))
        self.refused(item(), item(), words=("twice",))
        self.refused(item(), target="film-03", words=("film-03",))

    def test_limits_on_candidates_steps_cfg_and_instruction(self):
        for bad, words in ((item(candidates=0), "candidates"), (item(candidates=5), "candidates"),
                           (item(candidates=True), "candidates"),
                           (item(steps=7), "steps"), (item(steps=51), "steps"), (item(steps=40.0), "steps"),
                           (item(steps=True), "steps"),
                           (item(true_cfg_scale=0.5), "true_cfg_scale"),
                           (item(true_cfg_scale="4"), "true_cfg_scale"),
                           (item(instruction=""), "instruction"), (item(instruction=None), "instruction"),
                           (item(instruction="x" * 901), "900"),
                           (item(negative="x" * 901), "900"), (item(negative=3), "negative"),
                           (item(seed="1"), "seed"),
                           (item(instruction="make it a photorealistic photograph"), "house style")):
            with self.subTest(bad={k: v for k, v in bad.items() if k not in ("refs", "source")}):
                self.refused(bad, words=(words,))
        self.build(item(candidates=1, steps=8, instruction="x" * 900, negative="y" * 900))
        self.build(item(candidates=4, steps=50), job_id="edit-b")

    def test_defaults_for_steps_cfg_negative_and_candidates(self):
        it = item()
        for k in ("steps", "true_cfg_scale", "negative", "candidates", "refs"):
            it.pop(k)
        job, _ = self.payload(self.build(it))
        self.assertEqual(len(job["items"]), 1)
        first = job["items"][0]
        self.assertEqual((first["steps"], first["true_cfg_scale"], first["negative"], first["refs"]),
                         (colab_jobs.EDIT_DEFAULT_STEPS, 4.0, " ", []))

    def test_the_positive_only_wording_rule_does_not_apply_to_edits(self):
        """Exempt by design: the model has a real negative prompt and edits say what to remove."""
        r = self.build(item(instruction="Remove the beard: no beard, not a moustache, without stubble; "
                                        "he isn't old.",
                            negative="no snow indoors, nothing out of season"))
        first = self.payload(r)[0]["items"][0]
        self.assertTrue(first["instruction"].startswith("Remove the beard: no beard"))
        self.assertEqual(first["negative"], "no snow indoors, nothing out of season")
        # the style words stay allowed in the negative prompt (that is what it is for)
        self.build(item(negative="photorealistic, photograph, 3D render"), job_id="edit-b")

    def test_only_the_pinned_edit_model_is_allowed(self):
        self.refused(model="Qwen/Qwen-Image-Edit-2509", words=("edit",))
        self.refused(model="black-forest-labs/FLUX.1-dev", words=("forbidden",))
        self.build(model=colab_jobs.EDIT_REPO)

    # --- job build ----------------------------------------------------------------------------
    def test_the_forecast_is_reserved_and_follows_candidates_and_steps(self):
        one = self.build(item(candidates=1, steps=40))
        self.assertAlmostEqual(self.ledger.spent("bicharak", "2026-11"), one["forecast_units"])
        rate = RATES["edit"]
        per_step = rate["s_per_step"] * MARGIN / 3600 * rate["units_per_hour"]
        two = self.build(item(candidates=2, steps=40), job_id="edit-b")
        self.assertAlmostEqual(two["forecast_units"] - one["forecast_units"], 40 * per_step)
        # mixed steps: steps x images never falls below the job's real step total
        mixed = self.build(item(candidates=1, steps=8),
                           item(key="f01s008-1", source={"job": BASE_JOB, "file": "f01s008-1.png"},
                                refs=[], candidates=2, steps=50), job_id="edit-c")
        compute = colab_jobs.derive_compute("edit", {"items": [item(candidates=1, steps=8),
                                                               item(candidates=2, steps=50)]}, RATES, 3)
        self.assertEqual((compute["items"], compute["steps"]), (3, math.ceil((8 + 100) / 3)))
        self.assertGreaterEqual(compute["steps"] * compute["items"], 108)
        self.assertAlmostEqual(mixed["forecast_units"] - one["forecast_units"],
                               (compute["steps"] * 3 - 40) * per_step)
        ev = self.record.data["events"][-1]
        self.assertEqual((ev["stage"], ev["result"], ev["detail"]["kind"]), ("job", "built", "edit"))
        build = json.loads(Path(two["manifest"]).read_text())
        self.assertEqual(build["model"]["repo"], colab_jobs.EDIT_REPO)
        self.assertEqual(build["licences"], {"recorded": {colab_jobs.EDIT_REPO: "apache-2.0"},
                                             "allowlist": ["apache-2.0"]})
        self.assertEqual(build["diffusers"], colab_jobs.EDIT_DIFFUSERS)

    def test_rates_are_measured_at_the_reference_steps_and_never_defaulted(self):
        rates = {k: v for k, v in RATES.items() if k != "edit"}
        with self.assertRaises(ValueError):
            colab_jobs.build_job("edit", self.record, {"target": "film-01", "items": [item()]},
                                 self.ledger, rates, self.out, month="2026-11")
        rates = {**RATES, "edit": {**RATES["edit"], "steps": 30}}
        with self.assertRaises(ValueError) as caught:
            colab_jobs.build_job("edit", self.record, {"target": "film-01", "items": [item()]},
                                 self.ledger, rates, self.out, month="2026-11")
        self.assertIn(str(colab_jobs.EDIT_RATE_STEPS), str(caught.exception))
        rates = {**RATES, "edit": {**RATES["edit"], "steps": colab_jobs.EDIT_RATE_STEPS}}
        colab_jobs.build_job("edit", self.record, {"target": "film-01", "items": [item()]},
                             self.ledger, rates, self.out, month="2026-11")
        self.assertEqual(self.ledger._load()[-1]["state"], "reserved")

    def test_the_notebook_has_the_guards_gpu_check_licence_allowlist_and_pipeline_preflight(self):
        cells = self.src(self.build())
        src = "\n".join(cells)
        self.assertEqual(cells[0], "RUN = False")
        for c in cells[1:]:
            self.assertIn("RUN is not True", c)
        gpu = next(i for i, c in enumerate(cells) if "nvidia-smi" in c)
        access = next(i for i, c in enumerate(cells) if "auth_check(MODEL_REPO" in c)
        licence = next(i for i, c in enumerate(cells) if "LICENCE_ALLOWLIST" in c and "card" in c)
        preflight = next(i for i, c in enumerate(cells) if "EDIT_PIPELINE" in c and "pip" in c)
        clock = next(i for i, c in enumerate(cells) if "STOP_GUARD" in c)
        generate = next(i for i, c in enumerate(cells) if "enable_model_cpu_offload()" in c)
        self.assertLess(gpu, access)
        self.assertLess(access, licence)
        self.assertLess(licence, preflight)
        self.assertLess(preflight, clock)
        self.assertLess(clock, generate)
        self.assertIn("LICENCE_ALLOWLIST = ('apache-2.0',)", src)
        self.assertIn("LICENCE_REPOS = (MODEL_REPO,)", src)
        self.assertIn(f"MODEL_REPO = {colab_jobs.EDIT_REPO!r}", src)
        self.assertIn(f"DIFFUSERS_PIN = {colab_jobs.EDIT_DIFFUSERS!r}", src)
        self.assertIn("EDIT_PIPELINE = 'QwenImageEditPlusPipeline'", src)
        self.assertIn("QwenImageEditPlusPipeline", cells[generate])
        self.assertIn('bnb_4bit_quant_type="nf4"', cells[generate])
        self.assertIn("BF16_FROM_GIB = 70", src)
        self.assertIn("INT8_FROM_GIB = 30", src)
        self.assertNotIn("NF4_BELOW_GIB", src)
        self.assertIn("negative_prompt=", cells[generate])
        self.assertIn("true_cfg_scale=", cells[generate])
        self.assertIn('logging.getLogger("bitsandbytes', cells[generate])
        self.assertIn("per image", cells[generate])
        self.assertIn('EXPECTED = [i["key"] + ".png" for i in JOB["items"]]', src)
        self.assertIn("if not may_start(last):", src)
        self.assertIn("exchange.json", src)
        self.assertIn("source_sha256", src)
        self.assertNotIn("MASK_REPO", src)

    def run_licence(self, licences):
        cells = self.src(self.build())
        config = next(c for c in cells if "DRIVE_JOB_DIR =" in c)
        cell = next(c for c in cells if "LICENCE_ALLOWLIST" in c and "card" in c)
        seen = []

        class Api:
            def auth_check(self, repo, token=None):
                pass

            def model_info(self, repo, token=None):
                seen.append(repo)
                return types.SimpleNamespace(card_data={"license": licences[repo]}, tags=[])
        hub = types.ModuleType("huggingface_hub")
        hub.HfApi = Api
        g = {"RUN": True}
        exec(config, g)
        out = io.StringIO()
        with patch.dict(sys.modules, {"huggingface_hub": hub}), contextlib.redirect_stdout(out):
            exec(cell, g)
        return seen, out.getvalue(), g

    def test_the_licence_preflight_allows_only_apache_2_0(self):
        seen, printed, g = self.run_licence({colab_jobs.EDIT_REPO: "apache-2.0"})
        self.assertEqual(seen, [colab_jobs.EDIT_REPO])
        self.assertIn("apache-2.0", printed)
        self.assertEqual(g["LICENCES"], {colab_jobs.EDIT_REPO: "apache-2.0"})
        for bad in ("openrail++", "mit", "other", None):
            with self.subTest(licence=bad), self.assertRaises(RuntimeError):
                self.run_licence({colab_jobs.EDIT_REPO: bad})

    def run_preflight(self, diffusers_module):
        cells = self.src(self.build())
        config = next(c for c in cells if "DRIVE_JOB_DIR =" in c)
        cell = next(c for c in cells if "EDIT_PIPELINE" in c and "pip" in c)
        g = {"RUN": True}
        exec(config, g)
        calls = []
        out = io.StringIO()
        with patch.dict(sys.modules, {"diffusers": diffusers_module}), \
                patch("subprocess.run", lambda *a, **k: calls.append(a[0])), \
                contextlib.redirect_stdout(out):
            exec(cell, g)
        return calls, out.getvalue()

    def fake_diffusers(self, pipeline=True, zero_cond_t=True):
        mod = types.ModuleType("diffusers")
        mod.__version__ = "0.37.0"

        class Transformer:
            if zero_cond_t:
                def __init__(self, num_layers=60, zero_cond_t=False):
                    pass
            else:
                def __init__(self, num_layers=60):
                    pass
        mod.QwenImageTransformer2DModel = Transformer
        if pipeline:
            mod.QwenImageEditPlusPipeline = type("QwenImageEditPlusPipeline", (), {})
        return mod

    def test_the_pipeline_preflight_installs_the_pin_and_refuses_a_diffusers_without_the_class(self):
        calls, printed = self.run_preflight(self.fake_diffusers())
        self.assertIn(colab_jobs.EDIT_DIFFUSERS, calls[0])
        self.assertIn("0.37.0", printed)
        with self.assertRaises(RuntimeError) as caught:
            self.run_preflight(self.fake_diffusers(pipeline=False))
        self.assertIn("QwenImageEditPlusPipeline", str(caught.exception))
        with self.assertRaises(RuntimeError) as caught:
            self.run_preflight(self.fake_diffusers(zero_cond_t=False))
        self.assertIn("zero_cond_t", str(caught.exception))

    def helpers(self):
        template = (colab_jobs._TEMPLATES / "edit_cell.py.txt").read_text()
        ns = {}
        exec(template[template.index("# --- helpers"):template.index("# --- end helpers")], ns)
        return ns

    def test_precision_by_vram_bf16_from_70_int8_from_30_else_nf4(self):
        # the first L4 run (NF4 everywhere) came out grainy and washed: 4-bit is the last resort
        ns = self.helpers()
        for gib, want in ((22.5, "nf4"), (29.9, "nf4"), (30.0, "int8"), (39.4, "int8"),
                          (69.9, "int8"), (70.0, "bf16"), (79.3, "bf16")):
            self.assertEqual(ns["precision_for"](gib, 70, 30), want, gib)
        self.assertEqual((colab_jobs.EDIT_BF16_FROM_GIB, colab_jobs.EDIT_INT8_FROM_GIB), (70, 30))

    def test_quantized_loads_keep_the_sensitive_modules_bf16_and_print_them(self):
        # input/output projections, timestep/text embedding and the final norm of
        # QwenImageTransformer2DModel at diffusers 0.37.0 stay bf16 in the int8 and nf4 loads
        self.assertEqual(colab_jobs.EDIT_SKIP_MODULES,
                         ("img_in", "txt_in", "time_text_embed", "norm_out", "proj_out"))
        cells = self.src(self.build())
        src = "\n".join(cells)
        generate = next(c for c in cells if "enable_model_cpu_offload()" in c)
        self.assertIn(f"SKIP_MODULES = {list(colab_jobs.EDIT_SKIP_MODULES)!r}", src)
        self.assertIn("load_in_8bit=True", generate)
        self.assertIn("load_in_4bit=True", generate)
        self.assertEqual(generate.count("llm_int8_skip_modules=SKIPPED"), 2)
        self.assertIn('if PRECISION == "int8":', generate)
        self.assertIn('elif PRECISION == "nf4":', generate)
        self.assertIn('print("kept in bf16 (not quantized):"', generate)
        self.assertIn('"transformer_kept_bf16": SKIPPED', generate)
        self.assertIn("enable_model_cpu_offload()", generate)
        ns = self.helpers()
        self.assertEqual(ns["kept_bf16"]("bf16", ["img_in"]), [])
        self.assertEqual(ns["kept_bf16"]("int8", ("img_in", "proj_out")), ["img_in", "proj_out"])
        self.assertEqual(ns["kept_bf16"]("nf4", ("img_in",)), ["img_in"])

    def test_the_vae_decodes_in_float32(self):
        generate = next(c for c in self.src(self.build()) if "enable_model_cpu_offload()" in c)
        self.assertIn("pipe.vae.to(torch.float32)", generate)
        self.assertIn('output_type="latent"', generate)
        self.assertIn("pipe.vae.to(torch.bfloat16)", generate)  # the inputs' encode stays bf16
        self.assertLess(generate.index("pipe.vae.to(torch.float32)"),
                        generate.index("pipe.vae.decode("))
        self.assertIn('"vae_decode": "float32"', generate)

    # --- min_vram_gib ------------------------------------------------------------------------
    def config(self, r):
        return next(c for c in self.src(r) if "DRIVE_JOB_DIR =" in c)

    def test_min_vram_gib_defaults_to_0_and_is_written_to_the_notebook_and_manifest(self):
        r = self.build()
        self.assertIn("MIN_VRAM_GIB = 0\n", self.config(r))
        self.assertEqual(json.loads(Path(r["manifest"]).read_text())["min_vram_gib"], 0)
        r = self.build(job_id="edit-a100", min_vram_gib=30)
        self.assertIn("MIN_VRAM_GIB = 30\n", self.config(r))
        self.assertEqual(json.loads(Path(r["manifest"]).read_text())["min_vram_gib"], 30)
        nb = json.loads(Path(r["notebook"]).read_text())
        self.assertEqual(nb["metadata"]["colab"]["gpuType"], "A100")
        self.build(job_id="edit-80", min_vram_gib=80)

    def test_min_vram_gib_must_be_an_integer_from_0_to_80(self):
        for bad in (-1, 81, 40.5, True, "40", None):
            with self.subTest(value=bad):
                self.refused(min_vram_gib=bad, words=("min_vram_gib", "0 to 80"))

    def gpu_cell(self, min_gib, mib):
        cells = self.src(self.build(job_id=f"edit-v{min_gib}-{mib}", min_vram_gib=min_gib))
        cell = next(c for c in cells if "nvidia-smi" in c)
        calls = []

        def run(args, **kw):
            calls.append(list(args))
            out = "GPU 0: NVIDIA A100" if "-L" in args else f"{mib}\n"
            return types.SimpleNamespace(returncode=0, stdout=out)
        out = io.StringIO()
        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
                patch("subprocess.run", run), contextlib.redirect_stdout(out):
            exec(cell, {"RUN": True, "MIN_VRAM_GIB": min_gib})
        return calls, out.getvalue()

    def test_the_gpu_cell_refuses_a_gpu_below_min_vram_gib_before_any_download(self):
        with self.assertRaises(RuntimeError) as caught:
            self.gpu_cell(30, 23034)  # an L4
        msg = str(caught.exception)
        self.assertIn("needs an A100 or larger: Runtime -> Change runtime type -> A100", msg)
        self.assertIn("22.5 GiB", msg)
        self.assertIn("30 GiB", msg)
        calls, printed = self.gpu_cell(30, 40960)  # an A100 40 GB
        self.assertIn("40.0 GiB", printed)
        calls, printed = self.gpu_cell(0, 23034)  # no minimum: memory is not queried
        self.assertFalse(any("--query-gpu=memory.total" in " ".join(c) for c in calls))
        cells = self.src(self.build(job_id="edit-order", min_vram_gib=30))
        gpu = next(i for i, c in enumerate(cells) if "nvidia-smi" in c)
        access = next(i for i, c in enumerate(cells) if "auth_check(MODEL_REPO" in c)
        self.assertLess(gpu, access)

    def test_the_deadline_follows_the_edit_rate_in_rates_json_as_is(self):
        rates = {**RATES, "edit": {**RATES["edit"], "s_per_step": 10.0}}
        r = colab_jobs.build_job("edit", self.record, {"target": "film-01", "items": [item()]},
                                 self.ledger, rates, self.out, month="2026-11")
        want = (40 * 10.0 * 2 + 30 + 20) * MARGIN
        self.assertIn(f"DEADLINE_SECONDS = {int(want)}\n", self.config(r))
        generate = next(c for c in self.src(r) if "enable_model_cpu_offload()" in c)
        self.assertIn("s per image", generate)

    def test_the_model_runs_near_one_megapixel_and_the_output_returns_at_the_source_size(self):
        ns = self.helpers()
        for size in ((1344, 768), (1024, 1024), (768, 1344), (61, 45)):
            w, h = ns["edit_size"](*size)
            self.assertEqual((w % 32, h % 32), (0, 0), size)
            self.assertAlmostEqual(w * h / (1024 * 1024), 1.0, delta=0.08)
            self.assertAlmostEqual(w / h, size[0] / size[1], delta=0.05)
            out = ns["fit_back"](Image.new("RGB", (w, h), (1, 2, 3)), size)
            self.assertEqual(out.size, size)
            self.assertEqual(out.mode, "RGB")
        same = Image.new("RGB", (64, 48), (5, 6, 7))
        self.assertEqual(ns["fit_back"](same, (64, 48)).tobytes(), same.tobytes())
        self.assertEqual(ns["fit_back"](Image.new("RGBA", (64, 48)), (64, 48)).mode, "RGB")

    def test_the_licence_and_pin_constants(self):
        self.assertEqual(colab_jobs.EDIT_REPO, "Qwen/Qwen-Image-Edit-2511")
        self.assertEqual(colab_jobs.EDIT_LICENCES, {colab_jobs.EDIT_REPO: "apache-2.0"})
        self.assertEqual(colab_jobs.EDIT_LICENCE_ALLOWLIST, ("apache-2.0",))
        self.assertEqual(colab_jobs.EDIT_DIFFUSERS, "diffusers==0.37.0")
        self.assertIn("edit", colab_jobs.KINDS)
        self.assertIn("edit", exchange.KINDS)
        self.assertEqual(colab_jobs.pinned_steps("edit"), colab_jobs.EDIT_RATE_STEPS)


class EditImportTests(unittest.TestCase):
    build = EditBuildTests.build

    def setUp(self):
        EditBuildTests.setUp(self)
        self.job = self.build()
        self.dl = self.root / "download"
        self.dl.mkdir()

    def download(self, names):
        files = {n: png((len(n), 1, 2)) for n in names}
        for n, d in files.items():
            (self.dl / n).write_bytes(d)
        (self.dl / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": self.job["job_id"],
            "kind": "edit", "input_zip_sha256": sha(Path(self.job["inputs_zip"]).read_bytes()),
            "model": {"repo": colab_jobs.EDIT_REPO}, "status": "COMPLETE",
            "packages": {"diffusers": "0.37.0"}, "outputs": {n: sha(d) for n, d in files.items()}}))

    def test_candidates_import_into_the_edit_folder(self):
        names = ["f01s007-4--c1.png", "f01s007-4--c2.png"]
        self.download(names)
        arts = importer.import_job(self.record, self.job, self.dl, self.ledger, 0.6)
        self.assertEqual(sorted((a["kind"], Path(a["path"]).name) for a in arts),
                         [("edit", n) for n in names])
        self.assertTrue(all(a["path"].startswith(f"edit/{self.job['job_id']}/") for a in arts))
        self.assertEqual(self.ledger._load()[-1]["state"], "settled")

    def test_a_missing_candidate_holds(self):
        self.download(["f01s007-4--c1.png"])
        with self.assertRaises(ImportHeld) as caught:
            importer.import_job(self.record, self.job, self.dl, self.ledger, 0.6)
        self.assertIn("f01s007-4--c2", str(caught.exception))
        self.assertFalse((self.record.root / "edit").exists())


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue()


from tests.test_cli import CliTests  # noqa: E402  (reuses its title root, plan and fake jobs)


def _only_edit(cls):
    """Reuse CliTests' fixtures; its own tests run in test_cli, not again here."""
    for name in [n for n in dir(CliTests) if n.startswith("test_")]:
        setattr(cls, name, None)
    return cls


@_only_edit
class EditCli(CliTests):
    def edit_ready(self):
        """hold_ready (four shots per scene, recorded as artifacts) and an imported edit job."""
        sid, base = self.hold_ready()
        rec = Record.load(self.root)
        for p in sorted((self.root / "stills" / base).iterdir()):
            rec.add_artifact("stills", p, {"job_id": base, "job_kind": "stills"})
        key = f"{sid}-2"

        def outputs(rec, job_id, job_dir, out):
            for c in (1, 2):
                Image.new("RGB", (64, 36), (0, 50 * c, 200)).save(out / f"{key}--c{c}.png")
        return sid, base, key, self.fake_job("edit", "film-01", outputs)

    def test_job_edit_builds_from_an_imported_still_and_reserves_its_forecast(self):
        sid, base, key, _ = self.edit_ready()
        spec = self.d / "edit.json"
        spec.write_text(json.dumps({"items": [{
            "key": key, "source": {"job": base, "file": f"{key}.png"},
            "refs": [{"job": base, "file": f"{sid}-1.png"}],
            "instruction": "Remove the beard; Judge Mohit is clean-shaven.", "negative": "beard",
            "seed": 5, "candidates": 2, "steps": 40, "true_cfg_scale": 4.0}], "min_vram_gib": 30}))
        rates = self.d / "rates-edit.json"
        rates.write_text(json.dumps({"edit": {"s_per_step": 3.75, "units_per_hour": 1.94,
                                              "steps": colab_jobs.EDIT_RATE_STEPS,
                                              "decode_s": 1500, "export_s": 120}}))
        code, out = run("job", "edit", "--root", self.root, "--rates", rates, "--spec", spec,
                        "--film", 1, "--job-id", "edit-film-01-r1")
        self.assertEqual(code, 0, out)
        self.assertIn("Built edit job edit-film-01-r1 for film-01", out)
        self.assertIn("exchange-stage edit-film-01-r1", out)
        entry = json.loads(self.ledger.read_text())[-1]
        self.assertEqual((entry["job_id"], entry["state"]), ("edit-film-01-r1", "reserved"))
        self.assertTrue((self.root / "jobs" / "edit-film-01-r1" / "edit.ipynb").is_file())
        build = json.loads((self.root / "jobs" / "edit-film-01-r1" / "build-manifest.json").read_text())
        self.assertEqual(build["min_vram_gib"], 30)
        code, out = run("job", "edit", "--root", self.root, "--rates", rates, "--spec", spec,
                        "--reel", 1, "--job-id", "edit-film-01-r2")
        self.assertNotEqual(code, 0, out)
        self.assertIn("--film", out)

    def test_pick_and_film_patch_the_picked_edit_over_the_base(self):
        sid, base, key, job = self.edit_ready()
        files, meta = self.merged()
        self.assertEqual(meta, {"base": base, "patches": [], "unpicked": [job]})
        self.assertNotEqual(self.pick(job, {key: 3})[0], 0)
        code, out = self.pick(job, {key: 2})
        self.assertEqual(code, 0, out)
        pick = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "stills_pick"][-1]
        self.assertEqual(pick["meta"]["choices"][key]["file"], f"edit/{job}/{key}--c2.png")
        files, meta = self.merged()
        self.assertEqual(meta, {"base": base, "patches": [job]})
        self.assertEqual(files[key], (self.root / "edit" / job / f"{key}--c2.png").read_bytes())
        self.assertFalse([k for k in files if "--" in k])

    def test_a_picked_edit_overrides_a_hold_for_its_key(self):
        sid, base, key, job = self.edit_ready()
        self.assertEqual(self.hold("--keys", f"{key},{sid}-3")[0], 0)
        files, meta = self.merged()  # unpicked: both held keys are substituted
        self.assertEqual(files[key], self.shot(base, sid, 1))
        self.assertEqual(meta["held"], [key, f"{sid}-3"])
        self.assertEqual(self.pick(job, {key: 1})[0], 0)
        files, meta = self.merged()
        edited = (self.root / "edit" / job / f"{key}--c1.png").read_bytes()
        self.assertEqual(files[key], edited)  # the picked edit, not a substitute
        self.assertEqual(meta["held"], [f"{sid}-3"])
        self.assertEqual(meta["released_by_edit"], [key])
        self.assertNotIn(key, meta["substitutes"])
        self.assertEqual(files[f"{sid}-3"], edited)  # the previous approved shot is now the edit

    def test_an_edit_pick_releasing_every_held_key_leaves_no_hold(self):
        sid, base, key, job = self.edit_ready()
        self.assertEqual(self.hold("--keys", key)[0], 0)
        self.assertEqual(self.pick(job, {key: 2})[0], 0)
        files, meta = self.merged()
        self.assertNotIn("held", meta)
        self.assertNotIn("substitutes", meta)
        self.assertEqual(meta["released_by_edit"], [key])
        self.assertEqual(files[key], (self.root / "edit" / job / f"{key}--c2.png").read_bytes())

    def test_a_picked_retouch_does_not_release_a_hold(self):
        sid, base, key, _ = self.edit_ready()

        def outputs(rec, job_id, job_dir, out):
            Image.new("RGB", (64, 36), (9, 9, 9)).save(out / f"{key}--c1.png")
            Image.new("L", (64, 36), 255).save(out / f"{key}--mask.png")
        job = self.fake_job("retouch", "film-01", outputs)
        self.assertEqual(self.hold("--keys", key)[0], 0)
        self.assertEqual(self.pick(job, {key: 1})[0], 0)
        files, meta = self.merged()
        self.assertEqual(meta["held"], [key])
        self.assertNotIn("released_by_edit", meta)
        self.assertEqual(files[key], self.shot(base, sid, 1))


del CliTests  # its tests run in test_cli


if __name__ == "__main__":
    unittest.main()
