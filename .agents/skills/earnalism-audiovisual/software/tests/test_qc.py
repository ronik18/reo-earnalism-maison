import subprocess
import tempfile
import unittest
from pathlib import Path

from eav import qc
from tests._media import ff


def _clip(path, color, seconds=2, size="64x112"):
    ff("-f", "lavfi", "-i", f"color=c={color}:s={size}:r=24:d={seconds}", "-pix_fmt", "yuv420p", str(path))


class QcTests(unittest.TestCase):
    def test_loop_score_range_and_contact_sheet(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # gradient that changes over time: first and last frames differ
            v = td / "v.mp4"
            ff("-f", "lavfi", "-i", "testsrc2=s=128x224:r=24:d=3", "-pix_fmt", "yuv420p", str(v))
            s = qc.loop_score(v)
            self.assertTrue(0.0 <= s <= 1.0)
            same = td / "same.mp4"
            _clip(same, "red")
            self.assertGreater(qc.loop_score(same), 0.99)
            self.assertLess(s, 0.9)
            sheet = td / "sheet.jpg"
            qc.contact_sheet(v, sheet, every_s=1.0)
            self.assertGreater(sheet.stat().st_size, 0)


class OnsetTests(unittest.TestCase):
    def test_speech_onset_measures_leading_silence(self):
        with tempfile.TemporaryDirectory() as td:
            for lead in (0.0, 0.3):
                wav = Path(td) / f"{lead}.wav"
                ff("-f", "lavfi", "-i", "sine=f=300:d=1:r=24000", "-af", f"adelay={int(lead * 1000)}",
                   "-ac", "1", str(wav))
                self.assertAlmostEqual(qc.speech_onset(wav), lead, delta=0.02)
            silent = Path(td) / "silent.wav"
            ff("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=1", str(silent))
            self.assertIsNone(qc.speech_onset(silent))


class TruncationTests(unittest.TestCase):
    """V1: Parler stops at ~30.2 s; flag units at the cap or spoken implausibly fast."""

    def rows(self, *pairs):
        return [{"unit_key": f"s-{i:03d}", "chars": c, "seconds": s} for i, (c, s) in enumerate(pairs, 1)]

    def test_thresholds(self):
        self.assertEqual(qc.TRUNCATION_CAP_S, 29.0)
        self.assertEqual(qc.CPS_RATIO, 1.6)

    def test_clean_job_has_no_suspect(self):
        self.assertEqual(qc.truncation_suspects(self.rows((110, 10.0), (55, 5.0), (220, 19.0))), [])

    def test_duration_at_the_cap(self):
        # 330 chars in 30.0 s is the median rate itself; only the duration flags it
        got = qc.truncation_suspects(self.rows((110, 10.0), (120, 11.0), (330, 30.0), (100, 28.99)))
        self.assertEqual([g["unit_key"] for g in got], ["s-003"])
        self.assertIn("29.0", got[0]["reasons"][0])
        got = qc.truncation_suspects(self.rows((110, 10.0), (319, 29.0)))
        self.assertEqual([g["unit_key"] for g in got], ["s-002"])

    def test_chars_per_second_over_1_6_x_median(self):
        # median 11 chars/s: 17.6 is the boundary (not flagged), 18 is over it
        rows = self.rows((110, 10.0), (110, 10.0), (110, 10.0), (176, 10.0), (180, 10.0))
        self.assertEqual([g["unit_key"] for g in qc.truncation_suspects(rows)], ["s-005"])
        got = qc.truncation_suspects(self.rows((110, 10.0), (110, 10.0), (785, 30.2)))
        self.assertEqual(len(got[0]["reasons"]), 2)  # at the cap and far too fast
        self.assertEqual(got[0]["chars_per_s"], 25.99)

    def test_short_units_are_left_out_of_the_ratio_test(self):
        """V1 M-3: a unit under MIN_RATIO_CHARS is mostly breath: the ratio test never flags it; the
        duration cap still applies, and no audio is always suspect."""
        self.assertEqual(qc.MIN_RATIO_CHARS, 40)
        rows = self.rows(*[(110, 10.0)] * 6, (26, 0.5), (39, 1.0), (40, 1.0))
        # 26 / 0.5 = 52 and 39 / 1.0 = 39 chars/s are far over 1.6 x the median, but they are short;
        # 40 / 1.0 = 40 is long enough to be tested
        self.assertEqual([g["unit_key"] for g in qc.truncation_suspects(rows)], ["s-009"])
        got = qc.truncation_suspects(self.rows(*[(110, 10.0)] * 4, (12, 0.0), (30, 29.5)))
        self.assertEqual([(g["unit_key"], g["reasons"][0][:8]) for g in got],
                         [("s-005", "no audio"), ("s-006", "duration")])

    def test_narration_suspects_measures_the_wavs(self):
        with tempfile.TemporaryDirectory() as td:
            units = []
            for i, (chars, secs) in enumerate([(44, 2.0), (44, 2.0), (132, 2.0)], 1):
                key = f"f01s001-{i:03d}"
                ff("-f", "lavfi", "-i", f"sine=f=300:d={secs}:r=24000", "-ac", "1", str(Path(td) / f"{key}.wav"))
                units.append({"unit_key": key, "text": "x" * chars})
            got = qc.narration_suspects(units, td)
            self.assertEqual([g["unit_key"] for g in got], ["f01s001-003"])
            self.assertAlmostEqual(got[0]["seconds"], 2.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
