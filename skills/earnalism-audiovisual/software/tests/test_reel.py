import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from eav import mix, qc, reel
from tests._media import ff, noise_wav


def _script(n_words=110, hook="Why rich people never rest", length=60):
    lines = [hook] + ["word " * 10 for _ in range((n_words - 5) // 10)]
    cur = sum(len(x.split()) for x in lines)
    lines.append("tail " * (n_words - cur))
    return {"length": length, "language": "en", "hook": hook, "lines": lines, "loop_close": hook}


def _frame(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True,
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).astype(int)


class ScriptTests(unittest.TestCase):
    def test_hook_over_8_words_rejected(self):
        s = _script(hook="one two three four five six seven eight nine")
        with self.assertRaises(ValueError):
            reel.validate_script(s)

    def test_word_budget_60s(self):
        for n in (99, 126):
            s = _script(n)
            self.assertEqual(sum(len(x.split()) for x in s["lines"]), n)
            with self.assertRaises(ValueError):
                reel.validate_script(s)
        reel.validate_script(_script(110))
        reel.validate_script(_script(220, length=120))
        with self.assertRaises(ValueError):
            reel.validate_script(_script(110, length=120))

    def test_shot_lengths_in_range(self):
        for length in (60, 120):
            s = _script(110 if length == 60 else 220, length=length)
            shots = reel.shot_list(s)
            self.assertTrue(all(5.0 <= x["seconds"] <= 7.5 for x in shots))
            self.assertAlmostEqual(sum(x["seconds"] for x in shots), length, delta=1)
            self.assertEqual([x["shot"] for x in shots], list(range(1, len(shots) + 1)))

    def test_caption_hashtags(self):
        s = _script()
        c = reel.caption(s, ["#a", "#b", "#c", "#earnalism"])
        tags = [w for w in c.split() if w.startswith("#")]
        self.assertLessEqual(len(tags), 5)
        for t in ("#earnalism", "#learnalism", "#theearnalism"):
            self.assertIn(t, tags)
        self.assertEqual(len(tags), len(set(tags)))
        self.assertNotIn("#c", tags)
        head, body, foot = c.split("\n\n")[0], c.split("\n\n")[1], c.split("\n\n")[-1]
        self.assertTrue(head.startswith("Why Rich People Never Rest "))
        self.assertTrue(foot.startswith("#earnalism"))
        self.assertIn("tail", body)


class AssembleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        td = Path(cls.td.name)
        cls.clips = [td / "a.mp4", td / "b.mp4"]
        for p, src in zip(cls.clips, ("testsrc2=s=128x224:d=3", "life=s=128x224:mold=10:r=24:ratio=0.1:death_color=#C83232:life_color=#00ff00,scale=128:224")):
            ff("-f", "lavfi", "-i", f"{src}" if "life" in src else f"{src}:r=24", "-f", "lavfi", "-i", "sine=f=440:d=3",
               "-pix_fmt", "yuv420p", "-t", "3", "-shortest", str(p))
        cls.audio = td / "n.wav"
        noise_wav(cls.audio, 6)
        cls.out = td / "r.mp4"
        cls.info = reel.assemble(cls.clips, cls.audio, cls.out)
        cls.nolabel = td / "r2.mp4"
        reel.assemble(cls.clips, cls.audio, cls.nolabel, label_text="")

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_assembled_reel_is_1080x1920_and_minus14(self):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(self.out)],
                           capture_output=True, text=True).stdout.strip()
        self.assertEqual(r, "1080,1920")
        m = mix.measure(self.out)
        self.assertLessEqual(abs(m["lufs"] + 14), 1)
        self.assertLessEqual(m["true_peak"], -1.0)
        self.assertEqual(self.info["width"], 1080)

    def test_label_only_in_first_3s(self):
        d1 = np.abs(_frame(self.out, 1) - _frame(self.nolabel, 1)).sum()
        d4 = np.abs(_frame(self.out, 4) - _frame(self.nolabel, 4)).sum()
        self.assertGreater(d1, 0)
        self.assertEqual(d4, 0)

    def test_loop_score_high_after_dissolve(self):
        self.assertGreater(qc.loop_score(self.out), 0.9)


if __name__ == "__main__":
    unittest.main()
