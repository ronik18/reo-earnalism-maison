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


if __name__ == "__main__":
    unittest.main()
