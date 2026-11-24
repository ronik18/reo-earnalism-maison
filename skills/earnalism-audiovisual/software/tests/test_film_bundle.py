"""bundle-film: SRT to VTT, faststart check and the Maison R2 film bundle."""
import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from eav import cli, film_bundle
from eav.record import Record

SRT = "1\n00:00:00,000 --> 00:00:01,500\nHello there.\n\n2\n00:00:01,500 --> 00:00:03,250\nSecond cue.\n"
UNIT = str(uuid.uuid4())


def make_mp4(path, faststart=True, vcodec="libx264", acodec="aac", audio=True):
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1:r=10"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=220:d=1"]
    args += ["-c:v", vcodec, "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", acodec]
    if faststart:
        args += ["-movflags", "+faststart"]
    subprocess.run([*args, str(path)], check=True)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def make_root(tmp, qc="pass", qc_sha=None, **mp4_kw):
    root = Path(tmp) / "title"
    rec = Record.create(root, "t", {"language": "en"})
    out = root / "film" / "film-01"
    out.mkdir(parents=True)
    mp4 = out / "film-01.mp4"
    make_mp4(mp4, **mp4_kw)
    (out / "film-01.srt").write_text(SRT, encoding="utf-8")
    rec.add_artifact("subtitles", out / "film-01.srt", {"target": "film-01"})
    rec.add_artifact("film", mp4, {"target": "film-01"})
    rec.event("film", "assembled", {"target": "film-01"})
    if qc:
        report = root / "qc" / "report.json"
        report.parent.mkdir()
        report.write_text(json.dumps({"result": qc, "items": {"film-01": {
            "sha256": qc_sha or sha(mp4), "checks": {"loudness": qc}}}}), encoding="utf-8")
        rec.add_artifact("qc_report", report, {"failed": []})
        rec.event("qc", qc, {"failed": []})
    return root


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(argv))
    return code, buf.getvalue()


class SrtTests(unittest.TestCase):
    def test_srt_to_vtt_converts_timestamps(self):
        vtt = film_bundle.srt_to_vtt(SRT)
        self.assertTrue(vtt.startswith("WEBVTT\n\n"))
        self.assertIn("00:00:00.000 --> 00:00:01.500", vtt)
        self.assertIn("00:00:01.500 --> 00:00:03.250", vtt)
        self.assertLess(vtt.index("Hello there."), vtt.index("Second cue."))
        self.assertNotIn(",", vtt.replace("Hello there.", ""))

    def test_srt_to_vtt_refuses_empty(self):
        for text in ("", "  \n\n"):
            with self.assertRaises(ValueError):
                film_bundle.srt_to_vtt(text)


class FaststartTests(unittest.TestCase):
    def test_is_faststart_true_for_faststart(self):
        with tempfile.TemporaryDirectory() as t:
            fast, slow = Path(t) / "f.mp4", Path(t) / "s.mp4"
            make_mp4(fast, True)
            make_mp4(slow, False)
            self.assertTrue(film_bundle.is_faststart(fast))
            self.assertFalse(film_bundle.is_faststart(slow))

    def test_refuses_non_faststart_mp4(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(t, faststart=False)
            code, out = run("bundle-film", "--root", str(root), "--film", "film-01",
                            "--unit-id", UNIT, "--out", str(Path(t) / "b"))
            self.assertEqual(code, 2)
            self.assertIn("faststart", out)
            self.assertFalse((Path(t) / "b" / "film.json").exists())


class BundleTests(unittest.TestCase):
    def test_bundle_film_writes_manifest_with_hashes(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(t)
            b = Path(t) / "b"
            code, out = run("bundle-film", "--root", str(root), "--film", "film-01",
                            "--unit-id", UNIT, "--out", str(b))
            self.assertEqual(code, 0, out)
            m = json.loads((b / "film.json").read_text())
            self.assertEqual(m["schema"], "earnalism.audiovisual-film-bundle.v1")
            (u,) = m["units"]
            self.assertEqual(u["unit_id"], UNIT)
            self.assertEqual((u["mp4"], u["vtt"]), ("film.mp4", "film.vtt"))
            self.assertEqual(u["mp4_sha256"], sha(b / "film.mp4"))
            self.assertEqual(u["vtt_sha256"], sha(b / "film.vtt"))
            self.assertEqual(u["bytes"], (b / "film.mp4").stat().st_size)
            self.assertAlmostEqual(u["duration_ms"], 1000, delta=150)
            self.assertTrue((b / "film.vtt").read_text().startswith("WEBVTT"))

    def test_bundle_film_refuses_without_qc(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(t, qc=None)
            code, out = run("bundle-film", "--root", str(root), "--film", "film-01",
                            "--unit-id", UNIT, "--out", str(Path(t) / "b"))
            self.assertEqual(code, 2)
            self.assertIn("qc", out)

    def test_refuses_failed_qc_and_stale_qc_hash(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(t, qc="fail")
            self.assertEqual(run("bundle-film", "--root", str(root), "--film", "film-01",
                                 "--unit-id", UNIT, "--out", str(Path(t) / "b"))[0], 2)
        with tempfile.TemporaryDirectory() as t:
            root = make_root(t, qc_sha="0" * 64)
            code, out = run("bundle-film", "--root", str(root), "--film", "film-01",
                            "--unit-id", UNIT, "--out", str(Path(t) / "b"))
            self.assertEqual(code, 2)
            self.assertIn("sha256", out)

    def test_refuses_wrong_streams_and_bad_unit_id(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(t, audio=False)
            code, out = run("bundle-film", "--root", str(root), "--film", "film-01",
                            "--unit-id", UNIT, "--out", str(Path(t) / "b"))
            self.assertEqual(code, 2)
            self.assertIn("stream", out)
        with tempfile.TemporaryDirectory() as t:
            root = make_root(t)
            code, _ = run("bundle-film", "--root", str(root), "--film", "film-01",
                          "--unit-id", "nope", "--out", str(Path(t) / "b"))
            self.assertEqual(code, 2)

    def test_refuses_over_one_gib(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(t)
            with mock.patch.object(film_bundle, "MAX_BYTES", 10):
                code, out = run("bundle-film", "--root", str(root), "--film", "film-01",
                                "--unit-id", UNIT, "--out", str(Path(t) / "b"))
            self.assertEqual(code, 2)
            self.assertIn("bytes", out)


if __name__ == "__main__":
    unittest.main()
