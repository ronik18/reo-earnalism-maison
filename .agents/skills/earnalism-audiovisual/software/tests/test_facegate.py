"""Face and eye anomaly gate (owner request 28 Nov 2026): synthetic cartoon faces, clip persistence, the sheet,
the CLI command, qc's faces gate and the scene 14 evidence (when the local media is present)."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from eav import cli, facegate
from eav.record import Record

SKIN, OUTLINE, WHITE, PUPIL, WALL = (176, 112, 70), (40, 22, 14), (246, 242, 234), (16, 10, 8), (236, 220, 178)
REPO = next(p for p in Path(__file__).resolve().parents if (p / "AGENTS.md").is_file())
EVIDENCE = REPO / "production" / "audiovisual" / "bicharak"
TAKE_9P = EVIDENCE / "film_clips" / "motion-pilot6-f01s014" / "clips" / "f01s014-9p.mp4"
STILL_9 = EVIDENCE / "pilot" / "v6" / "art" / "f01s014-9.png"
STILL_9_FIXED = EVIDENCE / "pilot" / "v6" / "art" / "f01s014-9-onepupil.png"   # touch-up r2, fb63974
TAKE_14X = EVIDENCE / "pilot" / "v5" / "root" / "film_clips" / "clips-f01s014-fix-r1" / "clips" / "f01s014-14x.mp4"
SHA_9P = "2a13b6d59363b4fe19a6212d8132d07b5af1efec2fba8386afb78c6ee106ea63"


def face(w=640, h=360, left="one", right="one", glow=False, dx=0, eye_w=56, eye_h=40, cx=320, cy=170):
    """A flat cartoon face: a skin disc, two outlined eye whites, pupils per eye ("one", "two", "none")."""
    im = Image.new("RGB", (w, h), WALL)
    d = ImageDraw.Draw(im)
    d.ellipse([cx - 150, cy - 140, cx + 150, cy + 170], fill=SKIN)
    for ex, kind in ((cx - 70, left), (cx + 70, right)):
        box = [ex - eye_w // 2, cy - eye_h // 2, ex + eye_w // 2, cy + eye_h // 2]
        d.ellipse(box, fill=WHITE, outline=OUTLINE, width=3)
        px = ex + dx
        if kind == "one":
            d.ellipse([px - 9, cy - 9, px + 9, cy + 9], fill=PUPIL)
            d.ellipse([px - 4, cy - 6, px - 1, cy - 3], fill=WHITE)            # a specular highlight
        elif kind == "two":
            for off in (-13, 13):
                d.ellipse([px + off - 8, cy - 8, px + off + 8, cy + 8], fill=PUPIL)
                d.ellipse([px + off - 3, cy - 5, px + off, cy - 2], fill=WHITE)
    d.arc([cx - 40, cy + 70, cx + 40, cy + 110], 20, 160, fill=OUTLINE, width=3)
    if glow:
        d.rectangle([20, 25, 90, 70], fill=(50, 44, 40))                       # dark slats ...
        d.rectangle([40, 40, 60, 50], fill=(150, 250, 235))                   # ... and a pale cyan LED-like light
    return im


def write_clip(path: Path, frames):
    w, h = frames[0].size
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                          "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)],
                         stdin=subprocess.PIPE)
    p.communicate(b"".join(np.asarray(f, np.uint8).tobytes() for f in frames))
    assert p.returncode == 0
    return path


class FaceGateStillTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def still(self, name, im):
        p = self.d / name
        im.save(p)
        return p

    def test_normal_face_passes_with_two_eyes_one_pupil_each(self):
        r = facegate.check(self.still("ok.png", face()))
        self.assertTrue(r["pass"], r["notes"])
        self.assertFalse(r["needs_review"], r["notes"])
        eyes = [e for e in r["frames"][0]["eyes"] if e["skin"] >= facegate.THRESHOLDS["skin_min"]]
        self.assertEqual(sorted(len(e["pupils"]) for e in eyes), [1, 1])
        self.assertEqual(len(r["frames"][0]["pairs"]), 1)

    def test_double_pupil_fails_a_still(self):
        r = facegate.check(self.still("two.png", face(right="two")))
        self.assertFalse(r["pass"])
        self.assertEqual([(f["kind"], f["severity"]) for f in r["findings"]], [("double_pupil", "fail")])
        self.assertIn("two pupils in one eye", r["notes"][0])

    def test_missing_pupil_in_an_open_eye_fails_a_still(self):
        r = facegate.check(self.still("none.png", face(left="none")))
        self.assertFalse(r["pass"])
        self.assertEqual([(f["kind"], f["severity"]) for f in r["findings"]], [("missing_pupil", "fail")])

    def test_double_pupil_fails_under_fair_skin_night_and_moonlight(self):
        """I1: the gate must not go blind outside the warm daylight palette."""
        global SKIN
        saved = SKIN
        try:
            for skin in ((236, 200, 178), (250, 215, 190), (176, 112, 70), (120, 75, 45)):
                SKIN = skin
                for name, gain in (("day", (1, 1, 1)), ("night", (0.45, 0.45, 0.45)),
                                   ("moon", (0.36, 0.44, 0.68))):
                    lit = lambda im: Image.fromarray(np.clip(np.asarray(im, np.float32) * gain, 0, 255).astype(np.uint8))
                    bad = facegate.check(self.still("bad.png", lit(face(right="two"))))
                    self.assertEqual([(f["kind"], f["severity"]) for f in bad["findings"]], [("double_pupil", "fail")],
                                     (skin, name))
                    ok = facegate.check(self.still("ok.png", lit(face())))
                    self.assertTrue(ok["pass"] and not ok["needs_review"] and ok["face_frames"] == 1, (skin, name))
        finally:
            SKIN = saved

    def test_an_extreme_close_up_eye_is_judged_on_its_own(self):
        """I1: one eye filling the frame (scene 14 shot 5) is judged, not dropped as too big."""
        def eye(kind):
            im = Image.new("RGB", (640, 360), SKIN)
            d = ImageDraw.Draw(im)
            d.ellipse([170, 90, 470, 270], fill=WHITE, outline=OUTLINE, width=6)
            if kind == "one":
                d.ellipse([280, 140, 360, 220], fill=PUPIL)
                d.ellipse([300, 155, 315, 170], fill=WHITE)
            elif kind == "two":
                for cx in (250, 390):
                    d.ellipse([cx - 32, 148, cx + 32, 212], fill=PUPIL)
                    d.ellipse([cx - 14, 158, cx - 4, 168], fill=WHITE)
            return im
        ok = facegate.check(self.still("eye.png", eye("one")), key="eye")
        self.assertEqual(ok["face_frames"], 1, ok["notes"])
        self.assertTrue(ok["pass"] and not ok["needs_review"], ok["notes"])
        self.assertIn("double_pupil", [f["kind"] for f in facegate.check(self.still("e2.png", eye("two")))["findings"]])
        self.assertEqual([f["kind"] for f in facegate.check(self.still("e0.png", eye("none")))["findings"]],
                         ["missing_pupil"])

    def test_no_face_with_a_character_expected_is_not_judged_review(self):
        wall = self.still("wall.png", Image.new("RGB", (320, 180), WALL))
        r = facegate.check(wall, expect_face=True)
        self.assertTrue(r["pass"])
        self.assertTrue(r["needs_review"])
        self.assertTrue(r["not_judged"])
        self.assertEqual([f["kind"] for f in r["findings"]], ["not_judged"])
        self.assertFalse(facegate.check(wall)["needs_review"])           # nothing expected: noted, not a finding

    def test_pupil_pressed_into_the_corner_is_not_missing(self):
        r = facegate.check(self.still("side.png", face(dx=-20)))       # both pupils look hard left
        self.assertNotIn("missing_pupil", [f["kind"] for f in r["findings"]], r["notes"])

    def test_cyan_glow_is_listed_for_review(self):
        r = facegate.check(self.still("glow.png", face(glow=True)))
        self.assertTrue(r["pass"])
        self.assertTrue(r["needs_review"])
        self.assertEqual([f["kind"] for f in r["findings"]], ["glow"])

    def test_no_face_is_not_judged(self):
        r = facegate.check(self.still("wall.png", Image.new("RGB", (320, 180), WALL)))
        self.assertTrue(r["pass"])
        self.assertEqual(r["face_frames"], 0)
        self.assertTrue(r["not_judged"])
        self.assertIn("NOT JUDGED", " ".join(r["notes"]))

    def test_gate_writes_json_and_sheet_and_never_touches_the_source(self):
        src = self.still("two.png", face(right="two"))
        before = src.read_bytes()
        out = self.d / "out"
        r = facegate.gate(src, out)
        self.assertEqual(src.read_bytes(), before)
        doc = json.loads((out / "two.face.json").read_text())
        self.assertFalse(doc["thresholds_calibrated"])
        self.assertEqual(doc["thresholds"]["double_persist"], facegate.THRESHOLDS["double_persist"])
        self.assertEqual(doc["sha256"], facegate.sha256_file(src))
        self.assertIn("not measured", doc["identity"])
        self.assertEqual(r["sheet"], "two.faces.png")
        sheet = Image.open(out / "two.faces.png").convert("RGB")
        a = np.asarray(sheet)
        self.assertTrue(((a[..., 0] > 200) & (a[..., 1] < 40) & (a[..., 2] < 40)).any(), "flagged tile boxed in red")
        again = facegate.gate(src, out)                                   # reused: same sha256 and thresholds
        self.assertEqual(again["frames"], r["frames"])

    def test_fails_closed_without_opencv(self):
        saved = facegate.cv2
        facegate.cv2 = None
        try:
            self.assertFalse(facegate.available())
            with self.assertRaises(facegate.Unavailable):
                facegate.check(self.still("ok.png", face()))
        finally:
            facegate.cv2 = saved


class FaceGateClipTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def test_persistent_double_pupil_fails_and_its_frames_are_listed(self):
        frames = [face() for _ in range(8)] + [face(right="two") for _ in range(12)] + [face() for _ in range(4)]
        r = facegate.check(write_clip(self.d / "c.mp4", frames))
        self.assertFalse(r["pass"])
        dbl = [f for f in r["findings"] if f["kind"] == "double_pupil"]
        self.assertEqual(len(dbl), 1)
        self.assertEqual(dbl[0]["severity"], "fail")
        self.assertTrue(set(dbl[0]["frames"]) <= set(range(8, 20)), dbl[0]["frames"])
        self.assertGreaterEqual(len(dbl[0]["frames"]), facegate.THRESHOLDS["double_persist"])
        self.assertEqual(dbl[0]["times"][0], round(dbl[0]["frames"][0] / 24, 3))

    def test_a_one_sample_double_is_only_review(self):
        frames = [face() for _ in range(10)] + [face(right="two")] + [face() for _ in range(9)]
        r = facegate.check(write_clip(self.d / "c.mp4", frames), {"step": 1})
        self.assertTrue(r["pass"], r["notes"])
        self.assertTrue(r["needs_review"])
        self.assertEqual([(f["kind"], f["severity"], f["frames"]) for f in r["findings"]],
                         [("double_pupil", "review", [10])])

    def test_clean_clip_passes_and_gets_a_sheet(self):
        frames = [face(dx=(i % 6) - 3) for i in range(16)]
        clip = write_clip(self.d / "ok.mp4", frames)
        r = facegate.gate(clip, self.d / "out")
        self.assertTrue(r["pass"], r["notes"])
        self.assertFalse(r["needs_review"], r["notes"])
        self.assertEqual(r["sampled"], 8)                                  # every 2nd frame
        self.assertTrue((self.d / "out" / "ok.faces.png").is_file())

    def test_persistent_missing_pupil_fails_a_clip(self):
        frames = [face() for _ in range(4)] + [face(left="none") for _ in range(12)]
        r = facegate.check(write_clip(self.d / "m.mp4", frames))
        self.assertFalse(r["pass"])
        miss = [f for f in r["findings"] if f["kind"] == "missing_pupil"]
        self.assertEqual([f["severity"] for f in miss], ["fail"])
        self.assertGreaterEqual(len(miss[0]["frames"]), facegate.THRESHOLDS["missing_persist"])

    def test_a_clip_without_a_face_where_one_is_expected_is_not_judged(self):
        frames = [Image.new("RGB", (320, 180), WALL) for _ in range(8)]
        r = facegate.check(write_clip(self.d / "w.mp4", frames), expect_face=True)
        self.assertTrue(r["needs_review"])
        nj = [f for f in r["findings"] if f["kind"] == "not_judged"]
        self.assertEqual(nj[0]["frames"], [0, 2, 4, 6])

    def test_sudden_eye_change_is_review(self):
        frames = [face(w=960, h=540) for _ in range(6)] + [face(w=960, h=540, eye_w=100, eye_h=70) for _ in range(6)]
        r = facegate.check(write_clip(self.d / "m.mp4", frames), {"step": 1})
        self.assertIn("morph", [f["kind"] for f in r["findings"]], r["notes"])
        self.assertTrue(r["pass"])


class FaceGateCliTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def run_cli(self, *argv):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main([str(a) for a in argv])
        return code, buf.getvalue()

    def test_facegate_command_on_a_folder(self):
        folder = self.d / "media"
        folder.mkdir()
        face().save(folder / "ok.png")
        face(left="two").save(folder / "bad.png")
        code, out = self.run_cli("facegate", folder, "--out", self.d / "out")
        self.assertEqual(code, 5, out)
        self.assertIn("FAIL   bad.png", out)
        self.assertIn("pass   ok.png", out)
        self.assertTrue((self.d / "out" / "bad.face.json").is_file())
        code, out = self.run_cli("facegate", folder / "ok.png", "--out", self.d / "out")
        self.assertEqual(code, 0, out)

    def test_facegate_command_expect_face_and_fails_closed(self):
        wall = self.d / "wall.png"
        Image.new("RGB", (320, 180), WALL).save(wall)
        code, out = self.run_cli("facegate", wall, "--out", self.d / "o1", "--expect-face")
        self.assertEqual(code, 0, out)
        self.assertIn("REVIEW wall.png", out)
        self.assertIn("not judged", out)
        saved = facegate.cv2
        facegate.cv2 = None
        try:
            code, out = self.run_cli("facegate", wall, "--out", self.d / "o2")
        finally:
            facegate.cv2 = saved
        self.assertEqual(code, 2, out)
        self.assertIn("cannot run", out)


def _shots_film(test, still_im, override=None, shot_extra=None, face_media=None):
    """A minimal shots film with one glide shot whose picked still is `still_im`, ready for qc."""
    test.init_and_plan()
    fd = test.root / "film" / "film-01"
    for sub in ("shots", "stills", "voice", "audio"):
        (fd / sub).mkdir(parents=True, exist_ok=True)
    still_im.save(fd / "stills" / "s1-1.png")
    video = fd / "film-01.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:d=4:r=24",
                    "-f", "lavfi", "-i", "sine=f=220:d=4:r=48000", "-shortest", "-pix_fmt", "yuv420p",
                    str(video)], check=True)
    (fd / "shots" / "s1.json").write_text(json.dumps({"scene_id": "s1", "seconds": 4.0, "shots": [
        {"n": 1, "motion": "glide", "start": 0.0, "end": 4.0, "sound": {"sfx": []}, **(shot_extra or {})}]}))
    if override:
        (test.root / "picks").mkdir(exist_ok=True)
        (test.root / "picks" / "gate-overrides.json").write_text(json.dumps(override))
    Record.load(test.root).add_artifact("film", video, {"target": "film-01", "mode": "shots", "scenes": ["s1"],
                                                        **({"face_media": face_media} if face_media is not None else {})})


try:
    from tests.test_cli import RATES, SOURCE, run as _run
except ImportError:  # pragma: no cover
    from test_cli import RATES, SOURCE, run as _run


class FaceGateQcTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / "selfish-giant"
        self.src = self.d / "selfish-giant.json"
        self.src.write_text(json.dumps(SOURCE), encoding="utf-8")
        (self.d / "rates.json").write_text(json.dumps(RATES), encoding="utf-8")

    def init_and_plan(self):
        self.assertEqual(_run("init", self.src, "--root", self.root)[0], 0)
        self.assertEqual(_run("plan", "--root", self.root)[0], 0)

    def test_qc_fails_a_double_pupil_and_lists_it(self):
        _shots_film(self, face(right="two"))
        code, out = _run("qc", "--root", self.root)
        self.assertEqual(code, 5, out)
        report = json.loads((self.root / "qc" / "report.json").read_text())
        item = report["items"]["film-01"]
        self.assertEqual(item["checks"]["faces"], "fail")
        self.assertIn("film-01:faces", report["failed"])
        flagged = item["faces"]["flagged"]
        self.assertEqual([(f["shot"], f["key"], f["kind"], f["severity"]) for f in flagged],
                         [(1, "s1-1", "double_pupil", "fail")])
        self.assertEqual(item["faces"]["sheets"]["s1"], "qc/s1-faces.jpg")
        self.assertTrue((self.root / "qc" / "s1-faces.jpg").is_file())
        self.assertTrue((self.root / "qc" / "faces" / "s1" / "s1-1.face.json").is_file())
        self.assertIn("FACE FAIL s1 shot 1 s1-1", out)

    def test_qc_passes_a_double_pupil_with_a_recorded_override(self):
        _shots_film(self, face(right="two"), {"faces:s1-1": "owner: a reflection on her eye, not a pupil"})
        _run("qc", "--root", self.root)
        report = json.loads((self.root / "qc" / "report.json").read_text())
        item = report["items"]["film-01"]
        self.assertEqual(item["checks"]["faces"], "pass")
        self.assertEqual(item["faces"]["flagged"][0]["override"], "owner: a reflection on her eye, not a pupil")
        self.assertTrue(any("override" in a for a in report["advisory_only"]))

    def test_qc_fails_a_missing_pupil_on_a_still(self):
        _shots_film(self, face(left="none"))
        code, _ = _run("qc", "--root", self.root)
        report = json.loads((self.root / "qc" / "report.json").read_text())
        self.assertEqual(code, 5)
        self.assertEqual(report["items"]["film-01"]["checks"]["faces"], "fail")
        self.assertEqual([(f["kind"], f["severity"]) for f in report["items"]["film-01"]["faces"]["flagged"]],
                         [("missing_pupil", "fail")])

    def test_qc_faces_review_is_advisory(self):
        _shots_film(self, face(glow=True))
        _run("qc", "--root", self.root)
        report = json.loads((self.root / "qc" / "report.json").read_text())
        self.assertEqual(report["items"]["film-01"]["checks"]["faces"], "pass")
        self.assertTrue(any("FACE REVIEW" in a and "glow" in a for a in report["advisory_only"]))

    def test_qc_lists_a_shot_with_a_character_but_no_face_judged(self):
        """I1: the shot plan names a character, the still shows none the gate can judge: not a silent pass."""
        _shots_film(self, Image.new("RGB", (320, 180), WALL), shot_extra={"bible_refs": ["hemshashi"],
                                                                            "framing": "close-up"})
        code, out = _run("qc", "--root", self.root)
        report = json.loads((self.root / "qc" / "report.json").read_text())
        faces = report["items"]["film-01"]["faces"]
        self.assertEqual(faces["items"]["s1-1"]["verdict"], "review")
        self.assertEqual(faces["not_judged"], ["s1 shot 1 s1-1"])
        self.assertTrue(any("NOT JUDGED" in a for a in report["advisory_only"]))
        self.assertIn("FACE NOT JUDGED s1 shot 1 s1-1", out)

    def test_qc_judges_the_media_recorded_in_the_cut_and_fails_a_stale_cut(self):
        """I3: the cut was assembled with a double-pupil still; the pick was then replaced by a clean one without
        rebuilding. qc judges the recorded still (it fails) and reports the stale cut."""
        cut = self.d / "cut-still.png"
        face(right="two").save(cut)
        rel = Path("stills") / "old" / "s1-1--c1.png"
        _shots_film(self, face(), face_media=[{"scene": "s1", "shot": 1, "kind": "still", "key": "s1-1",
                                               "path": rel.as_posix(), "sha256": facegate.sha256_file(cut),
                                               "expect_face": False}])
        (self.root / rel).parent.mkdir(parents=True)
        (self.root / rel).write_bytes(cut.read_bytes())
        code, out = _run("qc", "--root", self.root)
        self.assertEqual(code, 5, out)
        faces = json.loads((self.root / "qc" / "report.json").read_text())["items"]["film-01"]["faces"]
        self.assertEqual([f["kind"] for f in faces["flagged"]], ["double_pupil"])     # the cut's still, not the pick
        self.assertEqual(len(faces["stale"]), 1)
        self.assertIn("FACE STALE s1 shot 1", out)
        (self.root / rel).write_bytes(b"changed")                                   # the recorded media is gone
        _run("qc", "--root", self.root)
        report = json.loads((self.root / "qc" / "report.json").read_text())
        self.assertIn("changed since the cut was assembled", report["items"]["film-01"]["not_run"]["faces"])

    def test_qc_faces_not_run_when_a_shot_has_no_media(self):
        _shots_film(self, face())
        (self.root / "film" / "film-01" / "stills" / "s1-1.png").unlink()
        _run("qc", "--root", self.root)
        report = json.loads((self.root / "qc" / "report.json").read_text())
        self.assertIn("faces", report["items"]["film-01"]["not_run"])
        self.assertIn("film-01:not_run:faces", report["failed"])


@unittest.skipUnless(TAKE_9P.is_file() and STILL_9.is_file(), "scene 14 evidence is local production media")
class SceneFourteenEvidenceTests(unittest.TestCase):
    """28 Nov 2026: the owner saw two pupils in the veiled mother's eye at 0:51 of scene 14 v7 (shot 11, 2.3 s into
    take f01s014-9p, about frame 55). The take's start still carries the same double pupil (FLUX drew it; Wan kept
    it), so it is flagged too; take 14x of the same mother is clean."""

    def test_take_9p_fails_around_the_frames_the_owner_saw(self):
        self.assertEqual(facegate.sha256_file(TAKE_9P), SHA_9P)
        r = facegate.check(TAKE_9P)
        self.assertFalse(r["pass"])
        dbl = [f for f in r["findings"] if f["kind"] == "double_pupil" and f["severity"] == "fail"]
        self.assertTrue(dbl)
        frames = set(dbl[0]["frames"])
        self.assertTrue({50, 54, 56, 60} <= frames, sorted(frames))
        self.assertGreaterEqual(len(frames), 40)

    def test_start_still_carries_the_same_double_pupil(self):
        r = facegate.check(STILL_9)
        self.assertEqual([(f["kind"], f["severity"]) for f in r["findings"]], [("double_pupil", "fail")])

    @unittest.skipUnless(STILL_9_FIXED.is_file(), "the retouched start still is local production media")
    def test_retouched_start_still_passes(self):
        r = facegate.check(STILL_9_FIXED, expect_face=True)
        self.assertTrue(r["pass"] and not r["needs_review"], r["notes"])
        self.assertEqual(r["face_frames"], 1)

    @unittest.skipUnless(TAKE_14X.is_file(), "take 14x is local production media")
    def test_take_14x_of_the_same_mother_passes(self):
        r = facegate.check(TAKE_14X)
        self.assertTrue(r["pass"], r["notes"])
        self.assertFalse([f for f in r["findings"] if f["kind"] == "double_pupil"])


if __name__ == "__main__":
    unittest.main()
