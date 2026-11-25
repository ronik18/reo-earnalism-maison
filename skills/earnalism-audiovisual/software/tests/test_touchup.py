"""Touch-up: local, deterministic OpenCV repaint of hand-placed boxes of an imported still.

Owner 2026-11-25: free open models keep drawing details the stories forbid (a bindi, ear studs or
a coloured sari edge on a child widow, a judge's moustache, 1880s wires, corner signatures) and
text-prompted masks missed them. Repaint only hand-placed boxes, locally, as a candidates job."""
import contextlib
import io
import json
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from eav import cli, touchup
from eav.record import Record, sha256_file


def canvas(w=120, h=80, colour=(200, 180, 150)):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = colour
    # a gentle gradient so "unchanged" is a real check, not a flat colour
    img[..., 0] = np.clip(img[..., 0].astype(int) + np.arange(w)[None, :] // 8, 0, 255)
    return img


def outside(a, b, box):
    x0, y0, x1, y1 = box
    keep = np.ones(a.shape[:2], bool)
    keep[y0:y1, x0:x1] = False
    return np.array_equal(a[keep], b[keep])


class TouchupOps(unittest.TestCase):
    def test_inpaint_removes_a_red_dot_and_changes_only_its_box(self):
        img = canvas()
        img[38:44, 58:64] = (200, 20, 30)  # a bindi
        box = [52, 32, 70, 50]
        out, mask = touchup.apply(img, [{"op": "inpaint", "box": box, "radius": 5}])
        self.assertTrue(outside(img, out, box))
        dot = out[38:44, 58:64].astype(int)
        self.assertLess(np.abs(dot - canvas()[38:44, 58:64].astype(int)).max(), 25)
        self.assertEqual(mask.shape, img.shape[:2])
        self.assertEqual(int(mask[41, 61]), 255)
        self.assertTrue(outside(np.zeros_like(mask), mask, box))

    def test_inpaint_colour_mask_touches_only_matching_pixels_and_their_rim(self):
        img = canvas()
        img[38:42, 58:62] = (210, 170, 40)  # a gold stud
        box = [40, 20, 90, 60]
        out, mask = touchup.apply(img, [{"op": "inpaint", "box": box, "radius": 3, "method": "ns",
                                         "mask": "color", "target": "#D2AA28", "tol": 40}])
        self.assertTrue(outside(img, out, [55, 35, 65, 45]))  # far parts of the box untouched too
        self.assertEqual(int(mask[25, 45]), 0)
        self.assertGreater(int(mask[40, 60]), 0)
        self.assertLess(np.abs(out[39, 59].astype(int) - canvas()[39, 59].astype(int)).max(), 25)

    def test_recolor_moves_matching_pixels_to_the_target_keeping_their_lightness(self):
        import cv2
        img = canvas(colour=(245, 245, 240))
        img[60:70, 10:110] = (190, 30, 40)    # red sari edge
        img[64, 10:110] = (120, 15, 20)       # a darker fold line inside it
        box = [0, 55, 120, 75]
        out, _ = touchup.apply(img, [{"op": "recolor", "box": box, "feather": 0, "grow": 0,
                                      "from": {"hue": [330, 20], "sat_min": 0.3}, "to": "#F4F1EA"}])
        self.assertTrue(outside(img, out, box))
        lab_in = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(int)
        lab_out = cv2.cvtColor(out, cv2.COLOR_RGB2LAB).astype(int)
        self.assertLessEqual(np.abs(lab_in[62, 50, 0] - lab_out[62, 50, 0]), 3)  # lightness kept
        self.assertLessEqual(np.abs(lab_in[64, 50, 0] - lab_out[64, 50, 0]), 3)
        hls = cv2.cvtColor(out, cv2.COLOR_RGB2HLS)
        self.assertLess(int(hls[62, 50, 2]), 40)  # no longer saturated red
        self.assertTrue(np.array_equal(out[57, 50], img[57, 50]))  # white saree in the box untouched

    def test_recolor_shade_lifts_to_the_target_and_keeps_the_fold(self):
        img = canvas(colour=(245, 245, 240))
        img[60:70, 10:110] = (190, 30, 40)
        img[64, 10:110] = (120, 15, 20)
        out, _ = touchup.apply(img, [{"op": "recolor", "box": [0, 55, 120, 75], "lightness": "shade",
                                      "from": {"hue": [330, 20], "sat_min": 0.3}, "to": "#F4F1EA"}])
        edge, fold = out[62, 50].astype(int), out[64, 50].astype(int)
        self.assertLess(np.abs(edge - np.array([244, 241, 234])).max(), 12)
        self.assertLess(fold.sum(), edge.sum())  # the fold stays darker

    def test_fill_paints_the_sampled_colour_feathered_inside_the_box(self):
        img = canvas(colour=(90, 110, 170))
        img[10:16, 20:100] = (30, 30, 30)  # a wire across the sky
        box = [15, 5, 105, 21]
        out, mask = touchup.apply(img, [{"op": "fill", "box": box, "sample": [60, 30], "feather": 4}])
        self.assertTrue(outside(img, out, box))
        self.assertTrue(np.array_equal(out[13, 60], img[30, 60]))
        self.assertLess(int(mask[5, 15]), 255)  # feathered at the box edge
        self.assertEqual(int(mask[13, 60]), 255)

    def test_clone_copies_a_nearby_patch(self):
        img = canvas()
        img[10:20, 10:20] = (0, 0, 255)
        img[10:20, 40:50] = (0, 255, 0)
        box = [10, 10, 20, 20]
        out, _ = touchup.apply(img, [{"op": "clone", "box": box, "from": [30, 0], "feather": 0}])
        self.assertTrue(outside(img, out, box))
        self.assertTrue((out[10:20, 10:20] == (0, 255, 0)).all())

    def test_ellipse_mask_leaves_the_box_corners(self):
        img = canvas()
        box = [20, 20, 60, 60]
        out, mask = touchup.apply(img, [{"op": "fill", "box": box, "sample": [5, 5], "mask": "ellipse"}])
        self.assertTrue(np.array_equal(out[20, 20], img[20, 20]))
        self.assertEqual(int(mask[40, 40]), 255)

    def test_line_mask_removes_a_diagonal_stick_inside_its_box_only(self):
        img = canvas()
        for i in range(40):
            img[20 + i, 30 + i] = img[20 + i, 31 + i] = (20, 20, 20)  # a thin diagonal stick
        box = [25, 15, 76, 65]
        out, mask = touchup.apply(img, [{"op": "inpaint", "box": box, "mask": "line",
                                         "line": [30, 20, 70, 60], "width": 6, "radius": 3}])
        self.assertTrue(outside(img, out, box))
        self.assertLess(np.abs(out[40, 50].astype(int) - canvas()[40, 50].astype(int)).max(), 25)
        self.assertEqual(int(mask[40, 30]), 0)  # off the stroke, inside the box: untouched

    def test_deterministic(self):
        img = canvas()
        img[30:40, 30:40] = (10, 200, 10)
        ops = [{"op": "inpaint", "box": [25, 25, 45, 45], "radius": 7},
               {"op": "recolor", "box": [0, 0, 120, 80], "from": {"hue": [80, 160], "sat_min": 0.2},
                "to": "#FFFFFF"}]
        a, ma = touchup.apply(img, ops)
        b, mb = touchup.apply(img, ops)
        self.assertTrue(np.array_equal(a, b) and np.array_equal(ma, mb))

    def test_bad_ops_are_refused(self):
        img = canvas()
        for bad, words in (
                ([], "ops"),
                ([{"op": "blur", "box": [0, 0, 5, 5]}], "op must be"),
                ([{"op": "inpaint", "box": [0, 0, 500, 5], "radius": 5}], "not inside"),
                ([{"op": "inpaint", "box": [5, 5, 5, 9], "radius": 5}], "not inside"),
                ([{"op": "inpaint", "box": [0, 0, 5, 5], "radius": 40}], "radius"),
                ([{"op": "inpaint", "box": [0, 0, 5, 5], "radius": 5, "method": "x"}], "method"),
                ([{"op": "inpaint", "box": [0, 0, 5, 5], "radius": 5, "mask": "color"}], "#RRGGBB"),
                ([{"op": "inpaint", "box": [0, 0, 5, 5], "radius": 5, "mask": "color",
                   "target": "#FF0000"}], "tol"),
                ([{"op": "recolor", "box": [0, 0, 5, 5], "from": {"hue": [0, 400], "sat_min": 0.1},
                   "to": "#FFFFFF"}], "hue"),
                ([{"op": "recolor", "box": [0, 0, 5, 5], "from": {"hue": [0, 40], "sat_min": 0.1},
                   "to": "white"}], "#RRGGBB"),
                ([{"op": "fill", "box": [0, 0, 5, 5], "sample": [500, 1]}], "sample"),
                ([{"op": "clone", "box": [0, 0, 5, 5], "from": [-3, 0]}], "clone source"),
                ([{"op": "clone", "box": [0, 0, 5, 5], "from": [9, 0], "seed": 1}], "unknown"),
                ([{"op": "inpaint", "box": [0, 0, 5, 5], "radius": 3, "mask": "line", "width": 3}], "line"),
                ([{"op": "inpaint", "box": [0, 0, 5, 5], "radius": 3, "width": 3}], "line/width")):
            with self.assertRaises(ValueError, msg=bad) as caught:
                touchup.apply(img, bad)
            self.assertIn(words, str(caught.exception), bad)


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue()


from tests.test_cli import CliTests  # noqa: E402  (reuses its title root, plan and fake jobs)


def _only_touchup(cls):
    for name in [n for n in dir(CliTests) if n.startswith("test_")]:
        setattr(cls, name, None)
    return cls


@_only_touchup
class TouchupCli(CliTests):
    def ready(self):
        """film_ready with the base stills recorded as artifacts and an imported retouch job."""
        self.film_ready()
        rec = Record.load(self.root)
        base = [j for j in cli._jobs(rec) if j["kind"] == "stills"][0]["job_id"]
        for p in sorted((self.root / "stills" / base).iterdir()):
            rec.add_artifact("stills", p, {"job_id": base, "job_kind": "stills"})
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        first = f"{scenes[0]['scene_id']}-1"
        second = f"{scenes[1]['scene_id']}-1"

        def outputs(rec, job_id, job_dir, out):
            img = np.zeros((180, 320, 3), np.uint8)
            img[:] = (0, 90, 0)
            img[50:56, 100:106] = (220, 20, 30)
            Image.fromarray(img).save(out / f"{first}--c1.png")
            Image.new("L", (320, 180), 255).save(out / f"{first}--mask.png")
            for name in (f"{first}--c1.png", f"{first}--mask.png"):
                rec.add_artifact("retouch_mask" if "mask" in name else "retouch", out / name,
                                 {"job_id": job_id, "job_kind": "retouch"})
        retouch = self.fake_job("retouch", "film-01", outputs)
        return scenes, first, second, base, retouch

    def spec(self, items):
        path = self.d / "touchup.json"
        path.write_text(json.dumps({"items": items}), encoding="utf-8")
        return path

    def touch(self, items, job_id="touchup-film-01"):
        return run("touchup", "--root", self.root, "--film", 1, "--spec", self.spec(items),
                   "--job-id", job_id)

    def item(self, key, job, name, box=(95, 45, 111, 61)):
        return {"key": key, "source": {"job": job, "file": name},
                "ops": [{"op": "inpaint", "box": list(box), "radius": 5}]}

    def test_touchup_writes_one_candidate_and_mask_per_item_and_records_the_job(self):
        scenes, first, second, base, retouch = self.ready()
        code, out = self.touch([self.item(first, retouch, f"{first}--c1.png"),
                                self.item(second, base, f"{second}.png", box=(10, 10, 40, 40))])
        self.assertEqual(code, 0, out)
        folder = self.root / "touchup" / "touchup-film-01"
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         sorted([f"{first}--c1.png", f"{first}--mask.png",
                                 f"{second}--c1.png", f"{second}--mask.png"]))
        src = np.asarray(Image.open(self.root / "retouch" / retouch / f"{first}--c1.png"))
        got = np.asarray(Image.open(folder / f"{first}--c1.png"))
        self.assertTrue(outside(src, got, [95, 45, 111, 61]))
        self.assertLess(int(got[52, 102, 0]), 60)  # the red dot is gone
        rec = Record.load(self.root)
        job = next(j for j in cli._jobs(rec) if j["job_id"] == "touchup-film-01")
        self.assertEqual((job["kind"], job["target"], job["imported"]), ("touchup", "film-01", True))
        arts = {Path(a["path"]).name: a for a in rec.data["artifacts"]
                if a["meta"].get("job_id") == "touchup-film-01"}
        self.assertEqual(arts[f"{first}--c1.png"]["kind"], "touchup")
        self.assertEqual(arts[f"{first}--mask.png"]["kind"], "touchup_mask")
        meta = arts[f"{first}--c1.png"]["meta"]
        self.assertEqual(meta["source"], f"retouch/{retouch}/{first}--c1.png")
        self.assertEqual(meta["source_sha256"],
                         sha256_file(self.root / "retouch" / retouch / f"{first}--c1.png"))
        self.assertEqual(meta["ops"][0]["op"], "inpaint")
        manifest = json.loads((self.root / "jobs" / "touchup-film-01" / "touchup-manifest.json").read_text())
        self.assertEqual(manifest["spec_sha256"],
                         sha256_file(self.root / "jobs" / "touchup-film-01" / "touchup.json"))
        row = next(r for r in manifest["items"] if r["key"] == first)
        self.assertEqual(row["candidate_sha256"], sha256_file(folder / f"{first}--c1.png"))
        self.assertEqual(row["ops"], meta["ops"])
        self.assertTrue(any(e["stage"] == "import" and e["result"] == "accepted"
                            and e["detail"]["job_id"] == "touchup-film-01" for e in rec.data["events"]))

    def test_touchup_refusals_leave_nothing_behind(self):
        scenes, first, second, base, retouch = self.ready()
        before = (self.root / "record.json").read_text()
        cases = [
            ([self.item("f99s001-1", base, f"{first}.png")], "not a still of"),
            ([self.item(first, "stills-nope", f"{first}.png")], "not an imported stills or retouch"),
            ([self.item(first, base, f"{first}--c7.png")], "not a recorded still"),
            ([self.item(first, retouch, f"{first}--mask.png")], "not a recorded still"),
            ([self.item(first, base, f"{second}.png")], "another still's file"),
            ([self.item(first, base, f"{first}.png"), self.item(first, base, f"{first}.png")], "twice"),
            ([self.item(f"{first}--c1", base, f"{first}.png")], "must be a still key"),
            ([self.item(first, base, f"{first}.png", box=(0, 0, 999, 10))], "not inside"),
        ]
        for items, words in cases:
            code, out = self.touch(items)
            self.assertEqual(code, 2, out)
            self.assertIn(words, out, items)
        (self.root / "stills" / base / f"{first}.png").write_bytes(b"changed")
        code, out = self.touch([self.item(first, base, f"{first}.png")])
        self.assertIn("sha256", out)
        self.assertEqual((self.root / "record.json").read_text(), before)
        self.assertFalse((self.root / "touchup").exists())
        self.assertFalse((self.root / "jobs" / "touchup-film-01").exists())

    def test_job_id_must_be_new(self):
        scenes, first, second, base, retouch = self.ready()
        self.assertEqual(self.touch([self.item(first, base, f"{first}.png")])[0], 0)
        code, out = self.touch([self.item(first, base, f"{first}.png")])
        self.assertEqual(code, 2, out)
        self.assertIn("not new", out)
        code, out = self.touch([self.item(first, base, f"{first}.png")], job_id=retouch)
        self.assertIn("not new", out)

    def test_pick_and_film_patch_the_picked_touchup_and_never_the_mask(self):
        scenes, first, second, base, retouch = self.ready()
        self.assertEqual(self.touch([self.item(first, retouch, f"{first}--c1.png")])[0], 0)
        job = "touchup-film-01"
        code, out = self.film_run()
        self.assertEqual(code, 0, out)  # unpicked: base stays, touchup is never the base
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"]["base"], base)
        self.assertIn(job, art["meta"]["stills"]["unpicked"])
        for bad in ({f"{first}--mask": 1}, {first: 2}):
            self.assertNotEqual(self.pick(job, bad)[0], 0, bad)
        code, out = self.pick(job, {first: 1})
        self.assertEqual(code, 0, out)
        code, out = self.film_run()
        self.assertEqual(code, 0, out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"], {"base": base, "patches": [job], "unpicked": [retouch]})
        merged = self.root / "film" / "film-01" / "stills"
        names = sorted(p.name for p in merged.iterdir())
        self.assertEqual(names, sorted(f"{sc['scene_id']}-1.png" for sc in scenes))
        self.assertEqual((merged / f"{first}.png").read_bytes(),
                         (self.root / "touchup" / job / f"{first}--c1.png").read_bytes())

    def test_status_lists_the_touchup_job_as_imported(self):
        scenes, first, second, base, retouch = self.ready()
        self.assertEqual(self.touch([self.item(first, base, f"{first}.png")])[0], 0)
        code, out = run("status", "--root", self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("touchup-film-01 touchup film-01: imported", out)


del CliTests  # its tests run in test_cli


if __name__ == "__main__":
    unittest.main()
