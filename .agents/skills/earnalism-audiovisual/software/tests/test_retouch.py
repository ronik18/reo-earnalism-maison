"""Retouch: open-licence inpainting of small masked regions of an already-chosen still.

FLUX.1-schnell keeps drawing culturally-default details the story forbids (a bindi and ear studs on
a child widow, a beard on Judge Mohit, overhead wires in an 1880s lane). Owner 2026-11-25: redraw
only those regions with an open inpainting model, as candidates, then review and pick."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from eav import cli, colab_jobs, importer
from eav.budget import MARGIN, Ledger
from eav.importer import ImportHeld
from eav.record import Record

RATES = {k: {"s_per_step": 1.0, "units_per_hour": 10.0, "decode_s": 30, "export_s": 20}
         for k in ("narration", "stills", "music", "retouch")}
SOURCE_JOB = "stills-film-01-r9"
SOURCE_FILE = "f01s007-4--c2.png"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def png(colour=(200, 120, 90), size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


def imported_stills(rec, job_id, target, files: dict):
    """An imported stills job exactly as the record keeps one (target, artifacts, accepted)."""
    rec.event("cli", "job_target", {"job_id": job_id, "target": target, "kind": "stills"})
    folder = rec.root / "stills" / job_id
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
        rec.add_artifact("stills", folder / name, {"job_id": job_id, "job_kind": "stills"})
    rec.event("import", "accepted", {"job_id": job_id, "kind": "stills"})


def item(**over):
    base = {"key": "f01s007-4", "source": {"job": SOURCE_JOB, "file": SOURCE_FILE},
            "regions": [{"find": "red dot on the forehead",
                         "prompt": "smooth bare forehead skin, same skin tone"},
                        {"find": "small gold earrings",
                         "prompt": "bare earlobes, same skin tone"}],
            "prompt": "a young Bengali widow in a plain white cotton sari, 1880s courtyard",
            "seed": 123, "candidates": 3, "strength": 0.85}
    base.update(over)
    return base


class RetouchBuildTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.record = Record.create(self.root / "rec", "bicharak", {"x": 1})
        self.ledger = Ledger(self.root / "ledger.json")
        self.out = self.root / "rec" / "jobs"
        self.out.mkdir()
        self.source = png()
        imported_stills(self.record, "stills-film-01-r5", "film-01",
                        {"f01s007-4.png": png((1, 2, 3)), "f01s008-1.png": png((4, 5, 6))})
        imported_stills(self.record, SOURCE_JOB, "film-01",
                        {SOURCE_FILE: self.source, "f01s007-4--c1.png": png((9, 9, 9))})

    def build(self, *items, **spec):
        return colab_jobs.build_job("retouch", self.record,
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
    def test_a_valid_spec_builds_one_item_per_candidate_with_the_source_inside(self):
        r = self.build()
        job, files = self.payload(r)
        self.assertEqual(job["kind"], "retouch")
        self.assertEqual([(i["key"], i["seed"]) for i in job["items"]],
                         [("f01s007-4--c1", 123), ("f01s007-4--c2", 124), ("f01s007-4--c3", 125)])
        self.assertEqual(job["masks"], ["f01s007-4--mask"])
        first = job["items"][0]
        self.assertEqual(first["base"], "f01s007-4")
        self.assertEqual(first["strength"], 0.85)
        self.assertEqual(first["source_sha256"], sha(self.source))
        self.assertEqual(files[first["source"]], self.source)
        self.assertEqual([g["find"] for g in first["regions"]],
                         ["red dot on the forehead", "small gold earrings"])
        self.assertTrue(first["prompt"].endswith(colab_jobs.HOUSE_STYLE))
        self.assertEqual(first["source_job"], SOURCE_JOB)

    def test_a_source_whose_bytes_differ_from_the_record_is_refused(self):
        (self.record.root / "stills" / SOURCE_JOB / SOURCE_FILE).write_bytes(png((0, 0, 0)))
        self.refused(words=("sha256", SOURCE_FILE))

    def test_a_source_that_is_not_an_imported_stills_file_is_refused(self):
        self.refused(item(source={"job": "stills-film-01-r99", "file": SOURCE_FILE}),
                     words=("stills-film-01-r99",))
        self.refused(item(source={"job": SOURCE_JOB, "file": "f01s007-4--c7.png"}),
                     words=("f01s007-4--c7.png",))
        self.record.event("cli", "job_target", {"job_id": "stills-x", "target": "film-01",
                                                "kind": "stills"})
        self.refused(item(source={"job": "stills-x", "file": SOURCE_FILE}), words=("stills-x",))

    def test_a_key_outside_the_film_or_not_the_sources_key_is_refused(self):
        self.refused(item(key="f09s001-1", source={"job": SOURCE_JOB, "file": SOURCE_FILE}),
                     words=("f09s001-1",))
        # f01s008-1 is a film key, but the source file is another key's still
        self.refused(item(key="f01s008-1"), words=("f01s008-1",))
        self.refused(item(), target="film-02", words=("film-02",))

    def test_a_negative_word_in_a_region_or_scene_prompt_is_refused(self):
        bad = item(regions=[{"find": "red dot", "prompt": "forehead without a dot"}])
        self.assertIn("'without'", self.refused(bad, words=("f01s007-4",)))
        self.refused(item(prompt="a widow, no jewellery"), words=("'no'",))

    def test_find_texts_are_mask_queries_and_may_name_what_is_not_wanted(self):
        r = self.build(item(regions=[{"find": "not the hair: the earring, no other jewellery",
                                      "prompt": "bare earlobe"}]))
        self.assertEqual(self.payload(r)[0]["items"][0]["regions"][0]["find"],
                         "not the hair: the earring, no other jewellery")

    def test_limits_on_regions_strength_and_candidates(self):
        region = {"find": "beard", "prompt": "smooth clean-shaven chin"}
        for bad, words in ((item(regions=[]), "regions"), (item(regions=[region] * 7), "regions"),
                           (item(regions=[{"find": "", "prompt": "x"}]), "find"),
                           (item(regions=[{"find": "beard"}]), "prompt"),
                           (item(strength=0.4), "strength"), (item(strength=1.01), "strength"),
                           (item(strength=True), "strength"), (item(strength="0.8"), "strength"),
                           (item(candidates=0), "candidates"), (item(candidates=5), "candidates"),
                           (item(candidates=True), "candidates")):
            with self.subTest(bad=bad):
                self.refused(bad, words=(words,))
        self.build(item(regions=[region] * 6, strength=0.5, candidates=1))

    def test_duplicate_keys_and_another_style_are_refused(self):
        self.refused(item(), item(), words=("twice",))
        self.refused(item(prompt="a widow, photorealistic"), words=("house style",))

    def test_only_the_pinned_inpainting_and_mask_models_are_allowed(self):
        self.refused(model="runwayml/stable-diffusion-inpainting", words=("retouch",))
        self.refused(model="black-forest-labs/FLUX.1-dev", words=("forbidden",))
        self.refused(mask_model="facebook/sam-vit-huge", words=(colab_jobs.MASK_REPO,))
        self.build(model=colab_jobs.RETOUCH_REPO, mask_model=colab_jobs.MASK_REPO)

    # --- job build ----------------------------------------------------------------------------
    def test_the_forecast_is_reserved_and_scales_with_candidates(self):
        one = self.build(item(candidates=1))
        self.assertAlmostEqual(self.ledger.spent("bicharak", "2026-11"), one["forecast_units"])
        three = self.build(item(), job_id="retouch-b")
        rate = RATES["retouch"]
        per_image = colab_jobs.RETOUCH_STEPS * rate["s_per_step"] * MARGIN / 3600 * rate["units_per_hour"]
        self.assertAlmostEqual(three["forecast_units"] - one["forecast_units"], 2 * per_image)
        ev = self.record.data["events"][-1]
        self.assertEqual((ev["stage"], ev["result"], ev["detail"]["kind"]), ("job", "built", "retouch"))
        build = json.loads(Path(three["manifest"]).read_text())
        self.assertEqual(build["model"]["repo"], colab_jobs.RETOUCH_REPO)
        self.assertEqual(build["mask_model"]["repo"], colab_jobs.MASK_REPO)

    def test_a_missing_retouch_rate_is_refused(self):
        rates = {k: v for k, v in RATES.items() if k != "retouch"}
        with self.assertRaises(ValueError):
            colab_jobs.build_job("retouch", self.record, {"target": "film-01", "items": [item()]},
                                 self.ledger, rates, self.out, month="2026-11")

    def test_the_notebook_has_the_stills_guards_and_the_licence_allowlist(self):
        cells = self.src(self.build())
        src = "\n".join(cells)
        self.assertEqual(cells[0], "RUN = False")
        for c in cells[1:]:
            self.assertIn("RUN is not True", c)
        gpu = next(i for i, c in enumerate(cells) if "nvidia-smi" in c)
        access = next(i for i, c in enumerate(cells) if "auth_check(MODEL_REPO" in c)
        licence = next(i for i, c in enumerate(cells) if "LICENCE_ALLOWLIST" in c and "card" in c)
        clock = next(i for i, c in enumerate(cells) if "STOP_GUARD" in c)
        self.assertLess(gpu, access)
        self.assertLess(access, licence)
        self.assertLess(licence, clock)
        self.assertIn("LICENCE_ALLOWLIST = ('apache-2.0', 'mit', 'openrail++')", src)
        self.assertIn(f"MODEL_REPO = {colab_jobs.RETOUCH_REPO!r}", src)
        self.assertIn(f"MASK_REPO = {colab_jobs.MASK_REPO!r}", src)
        self.assertIn(f"STEPS = {colab_jobs.RETOUCH_STEPS}", src)
        self.assertIn('"--mask.png"', src.replace("'", '"'))
        self.assertIn('EXPECTED = [i["key"] + ".png" for i in JOB["items"]] + [m + ".png" for m in JOB["masks"]]', src)
        self.assertIn("if not may_start(last):", src)
        self.assertIn("exchange.json", src)
        self.assertIn("source_sha256", src)

    def run_licence(self, licences, auth_error=None):
        cells = self.src(self.build())
        config = next(c for c in cells if "DRIVE_JOB_DIR =" in c)
        cell = next(c for c in cells if "LICENCE_ALLOWLIST" in c and "card" in c)
        seen = []

        class Api:
            def auth_check(self, repo, token=None):
                if auth_error:
                    raise auth_error

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

    def test_the_preflight_prints_each_licence_and_refuses_one_off_the_allowlist(self):
        ok = {colab_jobs.RETOUCH_REPO: "openrail++", colab_jobs.MASK_REPO: "apache-2.0"}
        seen, printed, g = self.run_licence(ok)
        self.assertEqual(sorted(seen), sorted(ok))
        self.assertIn("openrail++", printed)
        self.assertIn("apache-2.0", printed)
        self.assertEqual(g["LICENCES"], ok)
        with self.assertRaises(RuntimeError) as caught:
            self.run_licence({**ok, colab_jobs.MASK_REPO: "cc-by-nc-4.0"})
        self.assertIn("cc-by-nc-4.0", str(caught.exception))
        with self.assertRaises(RuntimeError):
            self.run_licence({**ok, colab_jobs.RETOUCH_REPO: None})
        with self.assertRaises(RuntimeError):
            self.run_licence(ok, auth_error=PermissionError("403"))

    def test_recorded_licences_are_on_the_allowlist(self):
        self.assertEqual(set(colab_jobs.MODEL_LICENCES), {colab_jobs.RETOUCH_REPO, colab_jobs.MASK_REPO})
        self.assertTrue(set(colab_jobs.MODEL_LICENCES.values()) <= set(colab_jobs.LICENCE_ALLOWLIST))

    def test_the_mask_and_composite_helpers(self):
        """The template's pure-PIL helpers: pad to multiples of 8, soft mask, composite back."""
        template = (colab_jobs._TEMPLATES / "retouch_cell.py.txt").read_text()
        ns = {}
        exec(template[template.index("# --- helpers"):template.index("# --- end helpers")], ns)
        img = Image.new("RGB", (61, 45), (10, 20, 30))
        padded = ns["pad8"](img)
        self.assertEqual(padded.size, (64, 48))
        self.assertEqual(padded.crop((0, 0, 61, 45)).tobytes(), img.tobytes())
        soft = [Image.new("L", (61, 45), 0), Image.new("L", (61, 45), 0)]
        soft[0].paste(230, (10, 10, 14, 14))
        soft[1].paste(90, (40, 30, 44, 34))  # under the threshold: not part of the mask
        mask = ns["union_mask"](soft, threshold=0.4, dilate_px=3, feather_px=2)
        self.assertEqual(mask.size, (61, 45))
        self.assertEqual(mask.getpixel((12, 12)), 255)
        self.assertEqual(mask.getpixel((42, 32)), 0)
        self.assertEqual(mask.getpixel((0, 0)), 0)
        self.assertGreater(mask.getpixel((8, 12)), 0)  # dilated past the found pixels
        generated = Image.new("RGB", (64, 48), (250, 0, 0))
        out = ns["composite"](img, generated, mask)
        self.assertEqual(out.size, (61, 45))
        self.assertEqual(out.getpixel((0, 0)), (10, 20, 30))  # outside the mask: the source, exactly
        self.assertEqual(out.getpixel((12, 12)), (250, 0, 0))


class RetouchImportTests(unittest.TestCase):
    build = RetouchBuildTests.build

    def setUp(self):
        RetouchBuildTests.setUp(self)
        self.job = self.build()
        self.dl = self.root / "download"
        self.dl.mkdir()

    def download(self, names):
        files = {n: png((len(n), 1, 2)) for n in names}
        for n, d in files.items():
            (self.dl / n).write_bytes(d)
        (self.dl / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": self.job["job_id"],
            "kind": "retouch", "input_zip_sha256": sha(Path(self.job["inputs_zip"]).read_bytes()),
            "model": {"repo": colab_jobs.RETOUCH_REPO}, "status": "COMPLETE",
            "packages": {"diffusers": "0.35.0"}, "outputs": {n: sha(d) for n, d in files.items()}}))

    def test_candidates_and_the_mask_import_into_the_retouch_folder(self):
        names = [f"f01s007-4--c{c}.png" for c in (1, 2, 3)] + ["f01s007-4--mask.png"]
        self.download(names)
        arts = importer.import_job(self.record, self.job, self.dl, self.ledger, 0.4)
        self.assertEqual(sorted((a["kind"], Path(a["path"]).name) for a in arts),
                         sorted([("retouch", n) for n in names[:3]]
                                + [("retouch_mask", "f01s007-4--mask.png")]))
        self.assertTrue(all(a["path"].startswith(f"retouch/{self.job['job_id']}/") for a in arts))
        self.assertEqual(self.ledger._load()[-1]["state"], "settled")

    def test_a_missing_mask_holds(self):
        self.download([f"f01s007-4--c{c}.png" for c in (1, 2, 3)])
        with self.assertRaises(ImportHeld) as caught:
            importer.import_job(self.record, self.job, self.dl, self.ledger, 0.4)
        self.assertIn("f01s007-4--mask", str(caught.exception))
        self.assertFalse((self.record.root / "retouch").exists())


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue()


from tests.test_cli import CliTests  # noqa: E402  (reuses its title root, plan and fake jobs)


def _only_retouch(cls):
    """Reuse CliTests' fixtures; its own tests run in test_cli, not again here."""
    for name in [n for n in dir(CliTests) if n.startswith("test_")]:
        setattr(cls, name, None)
    return cls


@_only_retouch
class RetouchCli(CliTests):
    def retouch_ready(self):
        """film_ready, the base stills recorded as artifacts, and an imported retouch job."""
        self.film_ready()
        rec = Record.load(self.root)
        base = [j for j in cli._jobs(rec) if j["kind"] == "stills"][0]["job_id"]
        for p in sorted((self.root / "stills" / base).iterdir()):
            rec.add_artifact("stills", p, {"job_id": base, "job_kind": "stills"})
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        first = f"{scenes[0]['scene_id']}-1"

        def outputs(rec, job_id, job_dir, out):
            for c in (1, 2):
                Image.new("RGB", (320, 180), (0, 50 * c, 0)).save(out / f"{first}--c{c}.png")
            Image.new("L", (320, 180), 255).save(out / f"{first}--mask.png")
        return scenes, first, base, self.fake_job("retouch", "film-01", outputs)

    def test_job_retouch_builds_from_an_imported_still_and_reserves_its_forecast(self):
        scenes, first, base, _ = self.retouch_ready()
        spec = self.d / "retouch.json"
        spec.write_text(json.dumps({"items": [{
            "key": first, "source": {"job": base, "file": f"{first}.png"},
            "regions": [{"find": "beard", "prompt": "smooth clean-shaven chin"}],
            "prompt": "Judge Mohit at his desk, 1880s", "seed": 5, "candidates": 2, "strength": 0.9}]}))
        rates = self.d / "rates-retouch.json"
        rates.write_text(json.dumps({"retouch": {"s_per_step": 1.0, "units_per_hour": 1.94,
                                                 "steps": colab_jobs.RETOUCH_STEPS,
                                                 "decode_s": 60, "export_s": 30}}))
        code, out = run("job", "retouch", "--root", self.root, "--rates", rates, "--spec", spec,
                        "--film", 1, "--job-id", "retouch-film-01-r1")
        self.assertEqual(code, 0, out)
        self.assertIn("Built retouch job retouch-film-01-r1 for film-01", out)
        self.assertIn("exchange-stage retouch-film-01-r1", out)
        entry = json.loads(self.ledger.read_text())[-1]
        self.assertEqual((entry["job_id"], entry["state"]), ("retouch-film-01-r1", "reserved"))
        self.assertTrue((self.root / "jobs" / "retouch-film-01-r1" / "retouch.ipynb").is_file())

    def test_pick_and_film_patch_the_picked_retouch_over_the_base_and_never_the_mask(self):
        scenes, first, base, job = self.retouch_ready()
        code, out = self.film_run()
        self.assertEqual(code, 0, out)  # unpicked: the base still stays
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"], {"base": base, "patches": [], "unpicked": [job]})
        for bad in ({f"{first}--mask": 1}, {first: 3}, {first: "mask"}):
            self.assertNotEqual(self.pick(job, bad)[0], 0, bad)
        code, out = self.pick(job, {first: 2})
        self.assertEqual(code, 0, out)
        pick = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "stills_pick"][-1]
        self.assertEqual(pick["meta"]["choices"][first]["file"], f"retouch/{job}/{first}--c2.png")
        code, out = self.film_run()
        self.assertEqual(code, 0, out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"], {"base": base, "patches": [job]})
        merged = self.root / "film" / "film-01" / "stills"
        names = sorted(p.name for p in merged.iterdir())
        self.assertEqual(names, sorted(f"{sc['scene_id']}-1.png" for sc in scenes))
        self.assertFalse([n for n in names if "--" in n])
        self.assertEqual((merged / f"{first}.png").read_bytes(),
                         (self.root / "retouch" / job / f"{first}--c2.png").read_bytes())

    def test_a_retouch_job_is_never_the_base(self):
        scenes, first, base, job = self.retouch_ready()
        code, out = self.film_run()
        self.assertEqual(code, 0, out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"]["base"], base)


del CliTests  # its tests run in test_cli


if __name__ == "__main__":
    unittest.main()
