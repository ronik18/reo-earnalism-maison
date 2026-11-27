import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from eav import cli, motiongate

W, H, N = 160, 90, 49


def write_clip(path: Path, order, shifts=None, kernel=61, contrast=150):
    """A textured scene panning 1 px per source frame; `order` maps output frame -> source frame; `shifts`
    overrides the pan of a source frame (a one-frame jump)."""
    rng = np.random.default_rng(7)
    raw = rng.random((H, W * 4))
    k = np.ones(kernel) / kernel                                          # smooth, so a small pan is a small difference
    for ax in (0, 1):
        raw = np.apply_along_axis(lambda v: np.convolve(np.r_[v[-kernel:], v, v[:kernel]], k, "valid")[:len(v)], ax, raw)
    tex = (40 + (raw - raw.min()) / (raw.max() - raw.min()) * contrast).astype(np.uint8)
    frames = []
    for src in order:
        x = (shifts or {}).get(src, src)
        f = np.roll(tex, -x, axis=1)[:, :W]
        frames.append(np.stack([f, f, f], axis=-1))
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
                          str(path)], stdin=subprocess.PIPE)
    p.communicate(b"".join(f.tobytes() for f in frames))
    assert p.returncode == 0
    return path


class MotionGateTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def test_smooth_clip_passes(self):
        r = motiongate.check_clip(write_clip(self.d / "s.mp4", range(N)))
        self.assertTrue(r["pass"], r)
        self.assertFalse(r["needs_review"], r)
        self.assertEqual((r["near_duplicate_runs"], r["diff_spikes"]), ([], []))

    def test_periodic_near_duplicate_frames_flagged(self):
        order = [i - (i % 4 == 3) for i in range(N)]            # every 4th frame repeats its predecessor
        r = motiongate.check_clip(write_clip(self.d / "d.mp4", order))
        self.assertFalse(r["pass"], r)
        self.assertGreaterEqual(len(r["near_duplicate_runs"]), 3)
        self.assertIn("stutter", " ".join(r["notes"]))

    def test_real_scale_slow_pan_passes_and_the_same_clip_with_a_jump_fails(self):
        # Wan takes move slowly: median difference well under 1 on the 160x90 grey frames
        slow = dict(kernel=121, contrast=20)
        ok = motiongate.check_clip(write_clip(self.d / "slow.mp4", range(N), **slow), sheet=False)
        self.assertTrue(0.1 < ok["measured"]["median_diff"] < 0.6, ok["measured"])
        self.assertTrue(ok["pass"], ok)
        self.assertFalse(ok["needs_review"], ok)
        bad = motiongate.check_clip(write_clip(self.d / "slowj.mp4", range(N), shifts={20: 100}, **slow), sheet=False)
        self.assertFalse(bad["pass"], bad)
        self.assertTrue(bad["diff_spikes"][0]["clear"])

    def test_near_static_clip_is_needs_review_but_still_measured(self):
        r = motiongate.check_clip(write_clip(self.d / "still.mp4", [0] * N), sheet=False)
        self.assertTrue(r["pass"] and r["needs_review"], r)
        self.assertIn("nearly static", " ".join(r["notes"]))
        self.assertIn("ratio_base", r["measured"])
        self.assertIn("periodic_starts", r["measured"])

    def test_near_static_clip_with_a_jump_still_fails(self):
        order = [0] * N
        order[20] = 1
        r = motiongate.check_clip(write_clip(self.d / "sj2.mp4", order, shifts={1: 150}), sheet=False)
        self.assertFalse(r["pass"], r)

    def test_quick_localised_change_that_continues_does_not_fail(self):
        # a region changes over 2 frames and stays (a blink/turn on a still background): performed action
        slow = dict(kernel=121, contrast=20)
        base = write_clip(self.d / "b.mp4", range(N), **slow)
        fr = motiongate._frames(base, motiongate.THRESHOLDS)
        out = []
        for i, f in enumerate(fr):
            f = f.copy()
            k = min(max(i - 19, 0), 2) / 2                    # frames 20-21 ramp to a +120 patch that stays
            f[20:70, 40:120] = np.clip(f[20:70, 40:120].astype(np.float32) + 120 * k, 0, 255).astype(np.uint8)
            out.append(f)
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
                              "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
                              str(self.d / "patch.mp4")], stdin=subprocess.PIPE)
        p.communicate(b"".join(f.tobytes() for f in out))
        r = motiongate.check_clip(self.d / "patch.mp4", sheet=False)
        self.assertTrue(r["pass"], r)
        self.assertTrue(r["diff_spikes"], r)                   # seen, and recorded with back/fwd and a kind
        self.assertEqual(r["diff_spikes"][0]["kind"], "motion")
        self.assertIn("back", r["diff_spikes"][0])

    def test_single_duplicate_is_not_stutter(self):
        order = list(range(N))
        order[20] = 19
        r = motiongate.check_clip(write_clip(self.d / "one.mp4", order))
        self.assertTrue(r["pass"], r)

    def test_difference_spike_flagged(self):
        r = motiongate.check_clip(write_clip(self.d / "j.mp4", range(N), shifts={20: 20 + 80}))
        self.assertFalse(r["pass"], r)
        self.assertTrue(r["diff_spikes"], r)
        self.assertTrue(r["diff_spikes"][0]["clear"])

    def test_contact_sheet_every_4_frames(self):
        mp4 = write_clip(self.d / "c.mp4", range(N))
        r = motiongate.check_clip(mp4)
        sheet = Path(r["contact_sheet"])
        self.assertEqual(sheet.parent, mp4.parent)
        tiles = -(-N // 4)                                       # frames 0, 4, ..., 48
        with Image.open(sheet) as im:
            cols, rows = 8, -(-tiles // 8)
            self.assertEqual(im.width, cols * (W + 2) + 2)
            self.assertEqual(im.height, rows * (H + 2) + 2)
        # tile 1 is frame 4: it matches frame 4 of the clip, not frame 1
        with Image.open(sheet) as im:
            t1 = np.asarray(im.convert("L"), dtype=np.float32)[2:2 + H, 2 + (W + 2):2 + (W + 2) + W]
        fr = motiongate._frames(mp4, motiongate.THRESHOLDS).astype(np.float32)
        self.assertLess(abs(t1 - fr[4]).mean(), abs(t1 - fr[1]).mean())

    def test_gate_clip_writes_motion_json_and_leaves_the_clip_alone(self):
        mp4 = write_clip(self.d / "g.mp4", range(N))
        before = mp4.read_bytes()
        r = motiongate.gate_clip(mp4)
        self.assertEqual(mp4.read_bytes(), before)
        j = json.loads((self.d / "g.motion.json").read_text())
        self.assertEqual(j["contact_sheet"], "g.contact.png")
        self.assertFalse(j["thresholds_calibrated"])
        self.assertIn("median_diff", j["measured"])
        self.assertEqual(j["thresholds"]["spike_rel"], motiongate.THRESHOLDS["spike_rel"])
        self.assertTrue(r["pass"])

    def test_undecodable_clip_needs_review_never_fails(self):
        bad = self.d / "bad.mp4"
        bad.write_bytes(b"not a video")
        r = motiongate.gate_clip(bad)
        self.assertTrue(r["pass"] and r["needs_review"])

    def test_cli_motiongate(self):
        mp4 = write_clip(self.d / "k.mp4", [i - (i % 4 == 3) for i in range(N)])
        out = self.d / "out"
        cli.cmd_motiongate(SimpleNamespace(clips=[str(self.d)], out=str(out)))
        self.assertTrue((out / "k.motion.json").is_file())
        self.assertFalse((self.d / "k.motion.json").exists())

    def test_film_refuses_failed_take_without_override(self):
        root = self.d / "rec"
        clips = root / "film_clips" / "job1" / "clips"
        clips.mkdir(parents=True)
        mp4 = write_clip(clips / "s1-1a.mp4", [i - (i % 4 == 3) for i in range(N)])
        motiongate.gate_clip(mp4)
        items = {"s1-1a": {"job_id": "job1", "item": {"key": "s1-1a", "shot": 1}}}
        shot = {"n": 1, "motion": "wan"}
        rec = SimpleNamespace(root=root)
        with self.assertRaises(cli.Stop) as cm:
            cli._shot_assets(rec, "film-01", "s1", shot, items, {}, root / "stills")
        self.assertIn("motion gate", str(cm.exception))
        (root / "picks").mkdir()
        (root / "picks" / "gate-overrides.json").write_text(json.dumps({"s1-1a": "owner accepted the stutter"}))
        got = cli._shot_assets(rec, "film-01", "s1", shot, items, {}, root / "stills")
        self.assertEqual(got["clips"], [mp4])

    def test_film_does_not_refuse_needs_review_or_ungated_take(self):
        root = self.d / "rec"
        clips = root / "film_clips" / "job1" / "clips"
        clips.mkdir(parents=True)
        mp4 = write_clip(clips / "s1-1a.mp4", range(N))
        (clips / "s1-1a.motion.json").write_text(json.dumps({"pass": True, "needs_review": True, "notes": ["x"]}))
        items = {"s1-1a": {"job_id": "job1", "item": {"key": "s1-1a", "shot": 1}}}
        got = cli._shot_assets(SimpleNamespace(root=root), "film-01", "s1", {"n": 1, "motion": "wan"}, items, {}, root)
        self.assertEqual(got["clips"], [mp4])


if __name__ == "__main__":
    unittest.main()
