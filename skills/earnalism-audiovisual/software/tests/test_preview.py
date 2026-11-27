import tempfile
import unittest
from pathlib import Path

from eav import film, preview
from tests import _media as m


def gap_wav(path: Path, total: float, tone_end: float, gap_end: float):
    expr = f"0.3*sin(2*PI*220*t)*(lt(t\\,{tone_end})+gt(t\\,{gap_end}))"
    m.ff("-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:d={total}", "-ac", "1", str(path))


class PreviewClipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_clip_bounds(self):
        src = self.d / "chapter.wav"
        gap_wav(src, 200, 100, 102)  # tone, a 2 s pause at 100-102 s, tone again
        out = self.d / "preview.mp3"
        rec = preview.cut_preview(src, out, "unit-1")
        self.assertLessEqual(rec["duration_ms"], preview.MAX_DURATION_MS)
        self.assertLessEqual(rec["bytes"], preview.MAX_BYTES)
        self.assertEqual(rec["bytes"], out.stat().st_size)
        self.assertEqual(rec["duration_ms"], round(film._duration(out) * 1000))
        self.assertEqual((rec["quality_kbps"], rec["content_type"], rec["prepared"]), (96, "audio/mpeg", True))
        self.assertAlmostEqual(rec["cut_at_ms"], 101000, delta=300)  # ends inside the pause
        self.assertTrue(rec["measurement_evidence"].strip())
        # every field library.audio_preview.prepared_clip checks, except the server-assigned asset_id
        for key in ("unit_id", "sha256", "duration_ms", "quality_kbps", "prepared", "measurement_evidence"):
            self.assertIn(key, rec)
        self.assertNotIn("asset_id", rec)

    def test_no_qualifying_silence_in_window_refuses(self):
        src = self.d / "chapter.wav"
        gap_wav(src, 400, 125, 130)  # the only pause is past the bound
        with self.assertRaises(ValueError):
            preview.cut_preview(src, self.d / "p.mp3", "u")
        self.assertFalse((self.d / "p.mp3").exists())

    def test_no_silence_refuses(self):
        src = self.d / "tone.wav"
        m.sine_wav(src, 150)
        with self.assertRaises(ValueError):
            preview.cut_preview(src, self.d / "p.mp3", "u")

    def test_score_bed_under_speech_cuts_at_a_narration_pause_from_timing(self):
        src = self.d / "scored.wav"
        m.sine_wav(src, 150)  # a continuous bed: no silence anywhere
        segments = [{"start_ms": 0, "end_ms": 40000}, {"start_ms": 41000, "end_ms": 90000},
                    {"start_ms": 91600, "end_ms": 125000}, {"start_ms": 126000, "end_ms": 150000}]
        rec = preview.cut_preview(src, self.d / "p.mp3", "u", segments)
        self.assertEqual(rec["cut_method"], "pause")
        self.assertAlmostEqual(rec["cut_at_ms"], 90800, delta=5)  # the latest pause within the bound
        self.assertLessEqual(rec["duration_ms"], preview.MAX_DURATION_MS)
        self.assertIn("narration pause", rec["measurement_evidence"])

    def test_pause_points_are_gap_midpoints(self):
        self.assertEqual(preview.pause_points([{"start_ms": 2000, "end_ms": 3000},
                                               {"start_ms": 0, "end_ms": 1000}]), [1.5])
