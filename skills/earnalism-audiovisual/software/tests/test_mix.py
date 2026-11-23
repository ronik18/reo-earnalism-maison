import tempfile
import unittest
from pathlib import Path

from eav import mix
from tests import _media as m


class MixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.speech = self.d / "speech.wav"
        self.score = self.d / "score.wav"
        m.speech_gap_wav(self.speech, 8, 3, 6)
        m.noise_wav(self.score, 8)

    def tearDown(self):
        self.tmp.cleanup()

    def test_master_hits_target_and_peak(self):
        out = self.d / "master.wav"
        mix.duck_and_master(self.speech, self.score, out, target_lufs=-16)
        got = mix.measure(out)
        self.assertLessEqual(abs(got["lufs"] - (-16)), 1)
        self.assertLessEqual(got["true_peak"], -1.0)

    def test_reel_target(self):
        out = self.d / "master14.wav"
        mix.duck_and_master(self.speech, self.score, out, target_lufs=-14)
        got = mix.measure(out)
        self.assertLessEqual(abs(got["lufs"] - (-14)), 1)
        self.assertLessEqual(got["true_peak"], -1.0)

    def test_score_ducked_under_speech(self):
        out = self.d / "master.wav"
        info = mix.duck_and_master(self.speech, self.score, out, target_lufs=-16)
        x = m.samples(Path(info["score_stem"]))
        win = lambda a, b: x[int(a * 48000):int(b * 48000)]
        pause = m.rms_db(win(0.5, 2.5))
        speaking = m.rms_db(win(3.5, 5.5))
        self.assertGreaterEqual(pause - speaking, 18)

    def test_arrange_cues(self):
        a, b = self.d / "a.wav", self.d / "b.wav"
        m.sine_wav(a, 2, freq=220)
        m.sine_wav(b, 2, freq=880)
        out = self.d / "arr.wav"
        mix.arrange_cues([a, b], [0, 3.0], 6.0, out)
        x = m.samples(out)
        self.assertAlmostEqual(len(x) / 48000, 6.0, delta=0.05)
        self.assertGreater(m.rms_db(x[int(5 * 48000):int(5.5 * 48000)]), -40)

    def test_arrange_cues_bad_boundaries(self):
        a = self.d / "a.wav"
        m.sine_wav(a, 1)
        with self.assertRaises(ValueError):
            mix.arrange_cues([a], [0, 1], 3, self.d / "x.wav")


if __name__ == "__main__":
    unittest.main()
