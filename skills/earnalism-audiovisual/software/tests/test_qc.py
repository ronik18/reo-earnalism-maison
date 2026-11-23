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


if __name__ == "__main__":
    unittest.main()
