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

    def test_pause_inserted_once_total_is_speech_plus_pauses(self):
        """R8: narration_track is the only place pauses are added; ends are speech ends."""
        durs = [1.2, 0.7, 0.9]
        for u, d in zip(UNITS, durs):
            m.sine_wav(self.wavs / f"{u['unit_key']}.wav", d)
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        for row, d in zip(t, durs):
            self.assertAlmostEqual(row["end"] - row["start"], d, delta=0.02)
        total = m.samples(self.d / "n.wav").size / 48000
        self.assertAlmostEqual(total, sum(durs) + 0.4 + 0.8, delta=0.03)  # no pause after last
        self.assertAlmostEqual(t[-1]["end"], total, delta=0.03)

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

    def test_video_end_card_is_appended_whole_with_its_own_sound(self):
        """The approved END is a 3 s video with its own sound (earnalism-video): it is appended
        unchanged in length, its audio follows the film's, and nothing of the score bleeds in."""
        t, stills, logo = self._assemble_inputs()
        mixed = self.d / "mixed.wav"
        m.ff("-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={t[-1]['end']}", str(mixed))  # silent bed
        end = self.d / "END.mp4"
        m.ff("-f", "lavfi", "-i", "color=c=navy:s=320x180:r=30:d=2", "-f", "lavfi",
             "-i", "sine=frequency=1000:sample_rate=48000:duration=2", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(end))
        out = self.d / "film-end.mp4"
        info = film.assemble(PLAN, t, stills, mixed, logo, end, out, size=(320, 180))
        self.assertAlmostEqual(info["duration"], t[-1]["end"] + 2.0, delta=0.1)
        self.assertAlmostEqual(float(probe(out, "v:0", "duration")), info["duration"], delta=0.15)
        self.assertAlmostEqual(float(probe(out, "a:0", "duration")), info["duration"], delta=0.15)
        tail, body = self.d / "tail.wav", self.d / "body.wav"
        m.ff("-ss", f"{t[-1]['end'] + 0.5:.3f}", "-t", "1", "-i", str(out), "-ac", "1", str(tail))
        m.ff("-ss", "0.5", "-t", "1", "-i", str(out), "-ac", "1", str(body))
        self.assertGreater(m.rms_db(m.samples(tail)), -30)   # the END's own sound
        self.assertLess(m.rms_db(m.samples(body)), -60)      # the silent bed stays silent

    def test_encoded_film_keeps_the_true_peak_gate(self):
        """বিচারক film-01: a -1.5 dBTP mix came out of the AAC encode at -0.9 dBTP and failed QC.
        The encoded film is measured and, if over -1 dBTP, its body audio is lowered to fit."""
        t, stills, logo = self._assemble_inputs()
        hot = self.d / "hot.wav"
        m.ff("-f", "lavfi", "-i", f"aevalsrc=0.97*sin(2*PI*997*t)|0.97*sin(2*PI*997*t):s=48000:d={t[-1]['end']}",
             str(hot))  # stereo, about -0.3 dBTP before encoding
        out = self.d / "film-hot.mp4"
        film.assemble(PLAN, t, stills, hot, logo, logo, out, size=(320, 180))
        self.assertLessEqual(mix.measure(out)["true_peak"], -1.0)

    def test_logo_lockup_matches_the_approved_landscape_placement(self):
        """earnalism-video EDITORIAL_PRESENTATION: landscape lockup at x1510/y48, about 362 px
        of the 2400x720 lockup on 1920x1080 (the first film used 9 %, 173 px: barely legible)."""
        self.assertAlmostEqual(film.LOGO_WIDTH_FRAC * 1920, 362, delta=10)
        self.assertAlmostEqual(film.LOGO_MARGIN_FRAC * 1920, 48, delta=2)

    def _assemble_inputs(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        stills = self.d / "stills"
        stills.mkdir(exist_ok=True)
        for name in ("s1", "s2"):
            Image.new("RGB", (64, 36), "red").save(stills / f"{name}.png")
        logo = self.d / "logo.png"
        Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(logo)
        return t, stills, logo

    def _call(self, plan, timing, **kw):
        _, stills, logo = self._assemble_inputs()
        return film.assemble(plan, timing, stills, self.d / "n.wav", logo, logo,
                             self.d / "f.mp4", size=(320, 180), **kw)

    def test_assemble_omitted_unit_refuses(self):
        t, _, _ = self._assemble_inputs()
        with self.assertRaises(ValueError):
            self._call(PLAN, t[:-1])
        with self.assertRaises(ValueError):
            self._call(PLAN, [t[0], t[2]])

    def test_assemble_duplicate_timing_key_refuses(self):
        t, _, _ = self._assemble_inputs()
        with self.assertRaises(ValueError):
            self._call(PLAN, t + [dict(t[0])])

    def test_assemble_series_plan_needs_film_selection(self):
        t, _, _ = self._assemble_inputs()
        series = {"series": "x", "films": PLAN["films"] + PLAN["films"]}
        with self.assertRaises(ValueError):
            self._call(series, t)
        info = self._call(series, t, film=0)
        self.assertEqual(info["scenes"], 2)
        with self.assertRaises(ValueError):
            self._call(series, t, film=5)

    def test_assemble_missing_still_refuses(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        (self.d / "stills").mkdir()
        with self.assertRaises(ValueError):
            film.assemble(PLAN, t, self.d / "stills", self.d / "n.wav",
                          self.d / "l.png", self.d / "c.png", self.d / "f.mp4")


if __name__ == "__main__":
    unittest.main()
