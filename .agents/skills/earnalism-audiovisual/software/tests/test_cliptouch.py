"""V1 clip touch-up: a fixed defect removed from a Wan clip into a NEW clip, recorded, gated and adoptable."""
import hashlib
import json
import math
import unittest
from pathlib import Path

import numpy as np

from eav import cli, cliptouch, film
from eav.record import Record
from tests import test_adopt

run = test_adopt.run
W, H = 896, 512
SLOPE_DEG = 17.0
RECT = (300, 200, 342, 224)     # x0, y0, x1, y1 of the glowing cyan rectangle


def slats(w=W, h=H) -> np.ndarray:
    """Dark slats with pale lit edges, running down to the right at SLOPE_DEG (a carriage shutter)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    off = yy - xx * math.tan(math.radians(SLOPE_DEG))
    phase = np.mod(off, 60.0)
    img = np.empty((h, w, 3), np.uint8)
    img[:] = (38, 40, 48)                       # slat face
    img[phase < 14] = (18, 30, 34)              # the dark gap
    img[(phase >= 14) & (phase < 22)] = (190, 160, 120)   # the lit tan edge
    return img


def defect(img) -> np.ndarray:
    out = img.copy()
    x0, y0, x1, y1 = RECT
    out[y0:y1, x0:x1] = (120, 230, 210)
    return out


def clip_frames(n=121, moving=False, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = slats()
    frames = []
    for i in range(n):
        f = np.roll(base, 3 * i, axis=1) if moving else base
        f = np.clip(f.astype(np.int16) + rng.integers(-1, 2, f.shape), 0, 255).astype(np.uint8)
        frames.append(defect(f))
    return np.stack(frames)


ITEM = {"mask": {"box": [290, 190, 352, 234], "select": [{"hue": [150, 200], "sat_min": 0.2}], "grow": 2,
                 "feather": 2},
        "fill": {"method": "along", "angle": SLOPE_DEG}, "mode": "plate"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class ModuleTests(unittest.TestCase):
    def test_fill_along_rebuilds_the_slats_and_their_edges(self):
        clean = slats()
        bad = defect(clean)
        hard = cliptouch.select(bad, ITEM["mask"])
        x0, y0, x1, y1 = RECT
        self.assertTrue(hard[y0:y1, x0:x1].all())
        fixed = cliptouch.fill_along(bad, hard, SLOPE_DEG)
        err = np.abs(fixed[hard].astype(int) - clean[hard].astype(int)).mean()
        self.assertLess(err, 12)   # the gap, the tan edge and the face continue through the mask
        inp = cliptouch.fill(bad, hard, {"method": "telea", "radius": 5})
        self.assertLess(err, np.abs(inp[hard].astype(int) - clean[hard].astype(int)).mean())   # better than inpaint
        self.assertTrue(np.array_equal(fixed[~hard], bad[~hard]))

    def test_validate_refuses_bad_items(self):
        for bad in ({**ITEM, "mask": {"box": [0, 0, W + 1, 10]}},
                    {**ITEM, "mask": {"box": [0, 0, 10, 10], "select": [{"hue": [0, 400]}]}},
                    {**ITEM, "fill": {"method": "along"}},
                    {**ITEM, "fill": {"method": "telea", "radius": 40}},
                    {**ITEM, "mode": "sometimes"}):
            with self.assertRaises(ValueError):
                cliptouch.validate(bad, (W, H))

    def test_apply_clip_writes_a_new_clip_and_never_the_source(self):
        d = Path(self.tmp())
        src = d / "k-1a.mp4"
        cliptouch.write_frames(clip_frames(48), "24/1", src)
        before = sha(src)
        out = d / "out" / "k-1a.mp4"
        meas = cliptouch.apply_clip(src, ITEM, out, d / "out")
        self.assertEqual(sha(src), before)
        self.assertEqual(meas["frames"], 48)
        self.assertGreater(meas["outside_mask"]["psnr_db"], 38)
        got = cliptouch.read_frames(out, (W, H))
        self.assertEqual(len(got), 48)
        x0, y0, x1, y1 = RECT
        roi = got[:, y0:y1, x0:x1].astype(int)
        cyan = (roi[..., 1] - roi[..., 0] > 60) & (roi[..., 2] - roi[..., 0] > 60)
        self.assertEqual(int(cyan.sum()), 0)                     # the rectangle is gone from every frame
        self.assertLess(meas["inside_mask_temporal_std"], 2.0)   # no flicker inside the mask
        for name in ("mask", "before", "after"):
            self.assertTrue((d / "out" / f"k-1a.{name}.png").is_file())
        with self.assertRaises(ValueError):
            cliptouch.apply_clip(src, ITEM, src, d)

    def test_plate_mode_refuses_a_moving_background(self):
        d = Path(self.tmp())
        src = d / "k-1a.mp4"
        cliptouch.write_frames(clip_frames(24, moving=True), "24/1", src)
        with self.assertRaisesRegex(ValueError, "moves"):
            cliptouch.apply_clip(src, ITEM, d / "o.mp4", d)

    def tmp(self):
        import tempfile
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        return t.name


class CliTests(unittest.TestCase):
    """clip-touchup files a job, and adopt binds its touched chain to the Wan shot (test_adopt's record fixtures)."""
    A = test_adopt.AdoptTests
    setUp0, init_and_plan, approve, imported, pilot_folder = A.setUp0, A.init_and_plan, A.approve, A.imported, A.pilot_folder
    write_spec, adopt, adopted_jobs = A.write_spec, A.adopt, A.adopted_jobs

    def setUp(self):
        test_adopt.AdoptTests.setUp(self)
        s = self.sid
        tmp = self.d / "src"
        tmp.mkdir()
        files = {}
        for key in (f"{s}-2a", f"{s}-2b"):
            cliptouch.write_frames(clip_frames(121, seed=len(files)), "24/1", tmp / f"{key}.mp4")
            files[f"clips/{key}.mp4"] = (tmp / f"{key}.mp4").read_bytes()
        items = [{"key": f"{s}-2a", "shot": 2, "width": W, "height": H, "seed": 1, "image": "x.png"},
                 {"key": f"{s}-2b", "shot": 2, "width": W, "height": H, "seed": 2, "continue_from": f"{s}-2a"}]
        self.clips_job = self.imported("film_clips", files, {"items": items}, model={"repo": test_adopt.WAN})
        self.ct_spec = self.d / "clip-touchup.json"

    def write_ct(self, **over):
        s = self.sid
        items = [{"key": k, "reason": "LED-like cyan rectangle between the slats (owner, 28 Nov)",
                  "source": {"job": self.clips_job, "file": f"{k}.mp4"}, **ITEM, **over}
                 for k in (f"{s}-2a", f"{s}-2b")]
        self.ct_spec.write_text(json.dumps({"scene": s, "items": items}), encoding="utf-8")

    def test_clip_touchup_is_recorded_and_adopted_for_the_shot(self):
        self.write_ct()
        src = self.root / "film_clips" / self.clips_job / "clips" / f"{self.sid}-2a.mp4"
        before = sha(src)
        code, out = run("clip-touchup", "--root", self.root, "--film", 1, "--spec", self.ct_spec, "--job-id", "ct-1")
        self.assertEqual(code, 0, out)
        self.assertEqual(sha(src), before)                       # the source clip is never written
        man = json.loads((self.root / "jobs" / "ct-1" / "clip-touchup-manifest.json").read_text())
        row = man["items"][0]
        self.assertEqual(row["source_sha256"], before)
        self.assertEqual(row["output_sha256"], sha(self.root / row["output"]))
        self.assertIn("LED-like", row["reason"])
        self.assertIn("pass", row["motion_gate"])
        self.assertEqual(man["spent_cu"], 0)
        rec = Record.load(self.root)
        job = next(j for j in cli._jobs(rec) if j["job_id"] == "ct-1")
        self.assertTrue(job["imported"])
        self.assertEqual(job["kind"], "clip_touchup")
        self.assertIn("clip_touchup/ct-1/" + f"{self.sid}-2a.motion.json",
                      [a["path"] for a in rec.data["artifacts"] if a["kind"] == "motion_gate"])
        # adopt the touched chain for shot 2, the way a touched still is adopted
        self.write_spec(clips={"2": {"job": "ct-1", "takes": [f"{self.sid}-2a", f"{self.sid}-2b"]}})
        code, out = self.adopt()
        self.assertEqual(code, 0, out)
        items = cli._film_clip_items(Record.load(self.root), "film-01")
        chain = film.pick_wan_clips([c["item"] for c in items.values()], self.sid, 2)
        self.assertEqual(chain, [f"{self.sid}-2a", f"{self.sid}-2b"])
        placed = self.root / "film_clips" / items[chain[0]]["job_id"] / "clips" / f"{chain[0]}.mp4"
        self.assertEqual(sha(placed), row["output_sha256"])
        doc = json.loads(next(j for j in self.adopted_jobs() if j["kind"] == "film_clips")["adoption"].read_text())
        self.assertEqual(doc["binding"]["clips"]["2"]["licence"], {"model": test_adopt.WAN, "licence": "Apache-2.0"})
        self.assertEqual(doc["binding"]["clips"]["2"]["source"]["job_id"], "ct-1")

    def test_clip_touchup_needs_a_reason_and_a_recorded_source(self):
        self.write_ct(reason=" ")
        code, out = run("clip-touchup", "--root", self.root, "--film", 1, "--spec", self.ct_spec, "--job-id", "ct-1")
        self.assertEqual(code, 2, out)
        self.assertIn("reason", out)
        self.write_ct(source={"job": "nope", "file": f"{self.sid}-2a.mp4"})
        code, out = run("clip-touchup", "--root", self.root, "--film", 1, "--spec", self.ct_spec, "--job-id", "ct-1")
        self.assertEqual(code, 2, out)
        self.assertFalse((self.root / "clip_touchup").exists())


if __name__ == "__main__":
    unittest.main()
