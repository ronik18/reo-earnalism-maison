"""Recorded, deterministic local retouch of small still defects (eav retouch / retouch-undo)."""
import hashlib
import io
import json
import unittest

import numpy as np
from PIL import Image, ImageDraw

from eav import cli, retouch
from eav.record import Record
from tests import test_chunks
from tests.test_cli import run

SKIN = (214, 160, 128)


def _skin(size=(320, 180), seed=3, sigma=5.0) -> Image.Image:
    W, H = size
    rng = np.random.default_rng(seed)
    a = np.array(SKIN, dtype=float) + rng.normal(0, sigma, (H, W, 3))
    return Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8))


def _textured(size=(200, 120)) -> Image.Image:
    W, H = size
    yy, xx = np.mgrid[0:H, 0:W]
    a = np.stack([(xx * 3) % 256, (yy * 5) % 256, (xx * yy) % 256], axis=-1)
    return Image.fromarray(a.astype(np.uint8))


class RetouchFillTests(unittest.TestCase):
    def test_pixels_outside_mask_and_feather_are_byte_identical(self):
        img = _textured()
        regions = [retouch.parse_region("40,30,24,18"), retouch.parse_region("120,70,16,20:rect")]
        out, method = retouch.retouch(img, regions, seed=7)
        a, b = np.asarray(img), np.asarray(out)
        allowed = retouch.changed_mask(regions, img.size)
        self.assertTrue(np.array_equal(a[~allowed], b[~allowed]))
        self.assertFalse(np.array_equal(a[allowed], b[allowed]))
        # the feather really is a band: some changed pixels lie just outside the mask itself
        mask = retouch.region_mask(regions[0], img.size) | retouch.region_mask(regions[1], img.size)
        self.assertTrue((a[allowed & ~mask] != b[allowed & ~mask]).any())
        self.assertEqual(method["feather_px"], 3)
        self.assertEqual(out.mode, img.mode)

    def test_output_is_identical_across_two_runs(self):
        img = _skin()
        regions = [retouch.parse_region("150,80,20,20")]
        sha = hashlib.sha256(img.tobytes()).hexdigest()
        png = []
        for _ in range(2):
            out, method = retouch.retouch(img.copy(), regions, retouch.seed_from_sha(sha))
            buf = io.BytesIO()
            out.save(buf, format="PNG")
            png.append(buf.getvalue())
        self.assertEqual(png[0], png[1])
        self.assertTrue(method["converged"])
        # another seed draws other texture: the noise really is seeded
        other, _ = retouch.retouch(img.copy(), regions, retouch.seed_from_sha("f" * 64))
        self.assertNotEqual(other.tobytes(), Image.open(io.BytesIO(png[0])).tobytes())

    def test_red_dot_on_skin_is_gone(self):
        img = _skin()
        ImageDraw.Draw(img).ellipse((154, 84, 165, 95), fill=(200, 20, 30))  # a bindi dot
        region = retouch.parse_region("150,80,20,20")
        out, _ = retouch.retouch(img, [region], seed=11)
        mask = retouch.region_mask(region, img.size)
        ring = retouch._dilate(mask, 10) & ~retouch._dilate(mask, 4)
        b = np.asarray(out).astype(float)
        inside, around = b[mask].mean(axis=0), b[ring].mean(axis=0)
        self.assertLess(np.abs(inside - around).max(), 3.0, (inside, around))
        before = np.asarray(img).astype(float)[mask].mean(axis=0)
        self.assertGreater(np.abs(before - around).max(), 30.0)  # the dot was there
        # textured, not plastic-smooth: the fill keeps roughly the field's grain
        self.assertGreater(b[mask].std(axis=0).min(), 2.0)

    def test_region_parsing_and_size_refusals(self):
        self.assertEqual(retouch.parse_region("1,2,3,4"),
                         {"x": 1, "y": 2, "w": 3, "h": 4, "shape": "ellipse"})
        self.assertEqual(retouch.parse_region("1,2,3,4:rect")["shape"], "rect")
        for bad in ("1,2,3", "1,2,0,4", "1,2,3,4:circle", "a,b,c,d", ""):
            with self.assertRaises(ValueError, msg=bad):
                retouch.parse_region(bad)
        size = (320, 180)  # 57600 px: 3% = 1728 px, 6% = 3456 px
        with self.assertRaisesRegex(ValueError, "outside"):
            retouch.check_regions([retouch.parse_region("310,10,20,20")], size)
        with self.assertRaisesRegex(ValueError, "outside"):
            retouch.check_regions([retouch.parse_region("-1,10,20,20")], size)
        with self.assertRaisesRegex(ValueError, r"small defects only \(at most 3% per region"):
            retouch.check_regions([retouch.parse_region("0,0,42,42:rect")], size)
        three = [retouch.parse_region(f"{x},10,40,40:rect") for x in (0, 50, 100)]  # 1600 px each
        with self.assertRaisesRegex(ValueError, r"at most 6% in all"):
            retouch.check_regions(three, size)
        self.assertEqual(retouch.check_regions(three[:2], size), [1600, 1600])
        ell = retouch.region_mask(retouch.parse_region("0,0,40,40"), size).sum()
        self.assertLess(ell, 1600)  # an ellipse counts its own pixels, not its box


class RetouchCliTests(unittest.TestCase):
    _base = test_chunks.ChunkCliTests  # its fixture helpers, not its tests
    setUp, set_rates, jobs = _base.setUp, _base.set_rates, _base.jobs
    fake_outputs, import_chunk = _base.fake_outputs, _base.import_chunk
    keyed_spec, film_args = _base.keyed_spec, _base.film_args

    def ready(self):
        """Imported narration and one still per scene (keys <scene_id>-01)."""
        self.assertEqual(run("job", "narration", "--root", self.root, "--rates", self.rates,
                             "--job-id", "narr")[0], 0)
        self.import_chunk(self.root / "jobs" / "narr", "narration")
        self.keys = [f"{sc['scene_id']}-01" for sc in self.scenes]
        self.build_stills("st", self.keys, 0)
        self.key = self.keys[0]

    def build_stills(self, job_id, keys, seed0):
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec",
                        self.keyed_spec(f"{job_id}.json", keys, seed0), "--job-id", job_id)
        self.assertEqual(code, 0, out)
        for d in self.jobs():
            if d.name == job_id or d.name.startswith(job_id + "-c"):
                self.import_chunk(d, "stills")

    def retouch(self, *extra, key=None, reason="bindi dot on the widow's forehead"):
        return run("retouch", key or self.key, "--root", self.root, "--film", 1,
                   "--region", "150,80,20,20", *extra, "--reason", reason)

    def have(self):
        return cli._stills_by_key(Record.load(self.root), "film-01")

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_retouch_records_provenance_and_supplies_the_key_in_film(self):
        self.ready()
        src = self.have()[self.key]["path"]
        code, out = self.retouch("--region", "20,20,10,8:rect")
        self.assertEqual(code, 0, out)
        self.assertIn("Retouched film-01 key", out)
        made = self.root / "stills" / "retouch" / f"{self.key}-1.png"
        self.assertTrue(made.is_file())
        rec = Record.load(self.root)
        [art] = [a for a in rec.data["artifacts"] if a["kind"] == "still_retouch"]
        m = art["meta"]
        self.assertEqual(art["path"], f"stills/retouch/{self.key}-1.png")
        self.assertEqual(m["source_path"], src.relative_to(self.root).as_posix())
        self.assertEqual(m["source_sha256"], self.sha(src))
        self.assertEqual(m["source_job_id"], self.have()[self.key]["job_id"])
        self.assertIsNone(m["source_retouch"])
        self.assertEqual(m["regions"], [{"x": 150, "y": 80, "w": 20, "h": 20, "shape": "ellipse"},
                                        {"x": 20, "y": 20, "w": 10, "h": 8, "shape": "rect"}])
        self.assertEqual(m["method"]["name"], retouch.METHOD)
        self.assertEqual(m["method"]["noise_seed"], retouch.seed_from_sha(m["source_sha256"]))
        self.assertEqual(m["output_sha256"], self.sha(made))
        self.assertEqual(m["reason"], "bindi dot on the widow's forehead")
        [ev] = [e for e in rec.data["events"] if e["stage"] == "retouch"]
        self.assertEqual(ev["result"], "applied")
        for k in ("source_path", "source_sha256", "source_job_id", "regions", "method",
                  "output_sha256", "reason"):
            self.assertEqual(ev["detail"][k], m[k], k)
        # per key: the retouch replaces only its key; the other keys keep their imports
        have = self.have()
        self.assertEqual(have[self.key]["path"], made)
        for k in self.keys[1:]:
            self.assertNotIn("retouch", have[k])
            self.assertEqual(have[k]["path"].parent.name, "st")
        code, out = run("status", "--root", self.root)
        self.assertIn(f"retouched {self.key}: stills/retouch/{self.key}-1.png (from {m['source_path']}; "
                      "bindi dot on the widow's forehead)", out)
        # deterministic: the same command elsewhere gives the same bytes
        code, out = run(*self.film_args())
        self.assertEqual(code, 0, out)
        self.assertIn(f"retouched: {self.key} (stills/retouch/{self.key}-1.png)", out)
        film = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        sbk = film["meta"]["stills_by_key"]
        self.assertEqual(sbk[self.key]["job_id"], m["source_job_id"])
        self.assertEqual(sbk[self.key]["retouch"]["path"], art["path"])
        self.assertEqual(sbk[self.key]["retouch"]["sha256"], m["output_sha256"])
        self.assertEqual(sbk[self.key]["retouch"]["source_sha256"], m["source_sha256"])
        self.assertEqual(sbk[self.key]["retouch"]["reason"], m["reason"])
        self.assertEqual(film["meta"]["retouched_keys"], [self.key])
        self.assertEqual({k: v for k, v in sbk.items() if k != self.key},
                         {k: "st" for k in self.keys[1:]})

    def test_refusals_leave_the_record_untouched(self):
        self.ready()
        before = (self.root / "record.json").read_bytes()
        cases = [
            (("retouch", "nokey-01", "--root", self.root, "--film", 1, "--region", "1,1,4,4",
              "--reason", "x"), "has no current still for key 'nokey-01'"),
            (("retouch", self.key, "--root", self.root, "--film", 1, "--region", "310,170,20,20",
              "--reason", "x"), "lies outside the 320x180 image"),
            (("retouch", self.key, "--root", self.root, "--film", 1, "--region", "0,0,42,42:rect",
              "--reason", "x"), "small defects only"),
            (("retouch", self.key, "--root", self.root, "--film", 1, *sum(
                (("--region", f"{x},10,40,40:rect") for x in (0, 50, 100)), ()), "--reason", "x"),
             "at most 6% in all"),
            (("retouch", self.key, "--root", self.root, "--film", 1, "--region", "1,1,4,4",
              "--reason", "  "), "--reason is empty"),
            (("retouch", self.key, "--root", self.root, "--region", "1,1,4,4", "--reason", "x"),
             "exactly once"),
            (("retouch", self.key, "--root", self.root, "--film", 1, "--target", "film-01",
              "--region", "1,1,4,4", "--reason", "x"), "exactly once"),
            (("retouch", self.key, "--root", self.root, "--film", 1, "--reason", "x"),
             "at least one --region"),
            (("retouch", self.key, "--root", self.root, "--film", 1, "--region", "1,1,4:rect",
              "--reason", "x"), "x,y,w,h"),
            (("retouch", self.key, "--root", self.root, "--film", 2, "--region", "1,1,4,4",
              "--reason", "x"), "film-02 has no current still"),
        ]
        for argv, msg in cases:
            code, out = run(*argv)
            self.assertEqual(code, 2, out)
            self.assertIn(msg, out)
            self.assertNotIn("Traceback", out)
        self.assertEqual((self.root / "record.json").read_bytes(), before)
        self.assertFalse((self.root / "stills" / "retouch").exists()
                         and any((self.root / "stills" / "retouch").iterdir()))
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec",
                        self.keyed_spec("r.json", [self.key], 5), "--job-id", "retouch")
        self.assertEqual(code, 2, out)
        self.assertIn("--job-id retouch is reserved", out)

    def test_retouches_chain_and_undo_retires_the_newest(self):
        self.ready()
        imported = self.have()[self.key]["path"]
        self.assertEqual(self.retouch()[0], 0)
        code, out = run("retouch", self.key, "--root", self.root, "--target", "film-01",
                        "--region", "20,20,12,12", "--reason", "small earring")
        self.assertEqual(code, 0, out)
        first = self.root / "stills" / "retouch" / f"{self.key}-1.png"
        second = self.root / "stills" / "retouch" / f"{self.key}-2.png"
        arts = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "still_retouch"]
        self.assertEqual(arts[1]["meta"]["source_path"], f"stills/retouch/{self.key}-1.png")
        self.assertEqual(arts[1]["meta"]["source_sha256"], self.sha(first))
        self.assertEqual(arts[1]["meta"]["source_retouch"], f"stills/retouch/{self.key}-1.png")
        self.assertEqual(arts[1]["meta"]["source_job_id"], arts[0]["meta"]["source_job_id"])
        # n+1 starts from n: the first region stays painted over in the second
        a1, a2 = np.asarray(Image.open(first)), np.asarray(Image.open(second))
        m1 = retouch.changed_mask([arts[0]["meta"]["regions"][0]], (320, 180))
        m2 = retouch.changed_mask(arts[1]["meta"]["regions"], (320, 180))
        self.assertTrue(np.array_equal(a1[m1 & ~m2], a2[m1 & ~m2]))
        self.assertEqual(self.have()[self.key]["path"], second)
        code, out = run("retouch-undo", self.key, "--root", self.root, "--film", 1, "--reason", "")
        self.assertEqual(code, 2, out)
        self.assertIn("--reason is empty", out)
        code, out = run("retouch-undo", self.key, "--root", self.root, "--film", 1,
                        "--reason", "earring was in the costume notes")
        self.assertEqual(code, 0, out)
        self.assertIn(f"now supplied by stills/retouch/{self.key}-1.png", out)
        self.assertEqual(self.have()[self.key]["path"], first)
        self.assertTrue(second.is_file())  # kept on record
        self.assertEqual(run("retouch-undo", self.key, "--root", self.root, "--film", 1,
                             "--reason", "owner prefers the original")[0], 0)
        self.assertEqual(self.have()[self.key]["path"], imported)
        self.assertNotIn("retouch", self.have()[self.key])
        code, out = run("retouch-undo", self.key, "--root", self.root, "--film", 1, "--reason", "x")
        self.assertEqual(code, 2, out)
        self.assertIn("has no current retouch", out)
        undone = [e["detail"]["path"] for e in Record.load(self.root).data["events"]
                  if e["stage"] == "retouch" and e["result"] == "undone"]
        self.assertEqual(undone, [f"stills/retouch/{self.key}-2.png", f"stills/retouch/{self.key}-1.png"])
        # a number is never reused; the new retouch starts from the import again
        self.assertEqual(self.retouch()[0], 0)
        third = self.root / "stills" / "retouch" / f"{self.key}-3.png"
        self.assertEqual(self.have()[self.key]["path"], third)
        self.assertEqual(third.read_bytes(), first.read_bytes())  # same source, same regions

    def test_a_newer_import_makes_the_retouch_stale(self):
        self.ready()
        self.assertEqual(self.retouch()[0], 0)
        made = self.root / "stills" / "retouch" / f"{self.key}-1.png"
        self.build_stills("st-new", [self.key], 700)
        have = self.have()
        self.assertEqual(have[self.key]["job_id"], "st-new")
        self.assertEqual(have[self.key]["path"], self.root / "stills" / "st-new" / f"{self.key}.png")
        self.assertNotIn("retouch", have[self.key])
        code, out = run("status", "--root", self.root)
        self.assertIn(f"stale retouch {self.key}: stills/retouch/{self.key}-1.png was made from st", out)
        self.assertNotIn(f"retouched {self.key}:", out)
        code, out = run("retouch-undo", self.key, "--root", self.root, "--film", 1, "--reason", "x")
        self.assertEqual(code, 2, out)
        self.assertIn(f"stale, already unused: stills/retouch/{self.key}-1.png", out)
        # retouching the new still starts from it, numbered on
        self.assertEqual(self.retouch()[0], 0)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "still_retouch"][-1]
        self.assertEqual((art["meta"]["n"], art["meta"]["source_job_id"]), (2, "st-new"))
        self.assertEqual(run("retouch-undo", self.key, "--root", self.root, "--film", 1,
                             "--reason", "x")[0], 0)
        # retiring the newer job: its source import is current again, and so is the first retouch
        self.assertEqual(run("retire", "st-new", "--root", self.root, "--reason", "originals")[0], 0)
        self.assertEqual(self.have()[self.key]["path"], made)

    def test_a_modified_retouch_stops_the_film(self):
        self.ready()
        self.assertEqual(self.retouch()[0], 0)
        made = self.root / "stills" / "retouch" / f"{self.key}-1.png"
        Image.new("RGB", (320, 180), (0, 0, 0)).save(made)
        code, out = run(*self.film_args())
        self.assertEqual(code, 2, out)
        self.assertIn("no longer match their recorded sha256", out)
        code, out = run("status", "--root", self.root)
        self.assertIn("MODIFIED or missing since recorded", out)
        self.assertIn(f"Restore stills/retouch/{self.key}-1.png from git", cli.next_action(self.root))


if __name__ == "__main__":
    unittest.main()
