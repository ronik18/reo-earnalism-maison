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


    def test_contact_sheet_of_a_long_film_stays_encodable(self):
        """বিচারক film-01 (1116 s) at one thumb per second made a 224-row sheet that JPEG
        cannot encode (> 65500 px). Long videos are sampled more sparsely, capped tiles."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            v = td / "long.mp4"
            ff("-f", "lavfi", "-i", "color=c=navy:s=64x36:r=1:d=1500", "-pix_fmt", "yuv420p", str(v))
            sheet = td / "sheet.jpg"
            qc.contact_sheet(v, sheet)
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                                  "-of", "csv=p=0", str(sheet)], check=True, capture_output=True,
                                 text=True).stdout.strip()
            width, height = map(int, out.split(","))
            self.assertLessEqual(height, 20 * 320)
            self.assertGreaterEqual(height, 320)

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
