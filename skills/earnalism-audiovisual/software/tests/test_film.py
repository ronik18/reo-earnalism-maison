import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from eav import film, mix
from tests import _media as m

PLAN = {"series": "x", "films": [{"unit_ids": [], "scenes": [
    {"scene_id": "s1", "text": "One. Two."}, {"scene_id": "s2", "text": "Three."}]}]}
UNITS = [
    {"unit_key": "s1-001", "text": "One.", "description": "d", "pause_after_ms": 400},
    {"unit_key": "s1-002", "text": "Two.", "description": "d", "pause_after_ms": 800},
    {"unit_key": "s2-001", "text": "Three.", "description": "d", "pause_after_ms": 800},
]


def probe(path, stream, entry):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream,
                          "-show_entries", f"stream={entry}", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)["streams"][0][entry]


class FilmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.wavs = self.d / "wavs"
        self.wavs.mkdir()
        for u in UNITS:
            m.sine_wav(self.wavs / f"{u['unit_key']}.wav", 1.5)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_unit_refuses(self):
        (self.wavs / "s2-001.wav").unlink()
        with self.assertRaises(ValueError):
            film.narration_track(UNITS, self.wavs, self.d / "n.wav")

    def test_duplicate_unit_refuses(self):
        with self.assertRaises(ValueError):
            film.narration_track(UNITS + [UNITS[0]], self.wavs, self.d / "n.wav")

    def test_narration_timing(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        self.assertAlmostEqual(t[0]["start"], 0)
        self.assertAlmostEqual(t[0]["end"], 1.5, delta=0.02)
        self.assertAlmostEqual(t[1]["start"], 1.9, delta=0.02)
        self.assertAlmostEqual(m.samples(self.d / "n.wav").size / 48000, t[-1]["end"], delta=0.05)

    def test_subtitles_cover_timing(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        srt = film.subtitles(t, UNITS)
        cues = [b.split("\n") for b in srt.strip().split("\n\n")]
        self.assertEqual(len(cues), 3)

        def sec(s):
            h, mi, rest = s.split(":")
            sc, ms = rest.split(",")
            return int(h) * 3600 + int(mi) * 60 + int(sc) + int(ms) / 1000
        spans = [tuple(sec(x) for x in c[1].split(" --> ")) for c in cues]
        for (a, b), (c, _) in zip(spans, spans[1:]):
            self.assertLess(a, b)
            self.assertLessEqual(b, c)
        dur = m.samples(self.d / "n.wav").size / 48000
        self.assertAlmostEqual(spans[-1][1], dur, delta=0.05)

    def test_assemble_duration_matches_audio(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        mixed = self.d / "mixed.wav"
        m.sine_wav(mixed, t[-1]["end"] + 0.5, freq=330)
        stills = self.d / "stills"
        stills.mkdir()
        for name, col in (("s1", "red"), ("s2", "blue")):
            Image.new("RGB", (320, 180), col).save(stills / f"{name}.png")
        logo, card = self.d / "logo.png", self.d / "card.png"
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(logo)
        Image.new("RGB", (320, 180), "black").save(card)
        out = self.d / "film.mp4"
        info = film.assemble(PLAN, t, stills, mixed, logo, card, out)
        self.assertEqual((probe(out, "v:0", "width"), probe(out, "v:0", "height")), (1920, 1080))
        v = float(probe(out, "v:0", "duration"))
        a = float(probe(out, "a:0", "duration"))
        self.assertAlmostEqual(v, a, delta=0.1)
        self.assertAlmostEqual(v, info["duration"], delta=0.15)

    def test_assemble_missing_still_refuses(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        (self.d / "stills").mkdir()
        with self.assertRaises(ValueError):
            film.assemble(PLAN, t, self.d / "stills", self.d / "n.wav",
                          self.d / "l.png", self.d / "c.png", self.d / "f.mp4")


if __name__ == "__main__":
    unittest.main()
