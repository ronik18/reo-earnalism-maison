"""ElevenLabs take import: tagged-script checks and sample-exact slicing of one take per scene."""
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from eav import take

RATE = 24000


def write_wav(path: Path, x: np.ndarray, rate=RATE):
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def tone(seconds, freq=220.0, rate=RATE):
    t = np.arange(int(round(seconds * rate))) / rate
    return 0.3 * np.sin(2 * np.pi * freq * t)


def gap(seconds, rate=RATE):
    return np.zeros(int(round(seconds * rate)))


def pcm(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-acodec",
                          "pcm_s16le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype="<i2")


def units(*texts, scene="s1"):
    return [{"unit_key": f"{scene}-{i:03d}", "text": t} for i, t in enumerate(texts, 1)]


class ScriptTests(unittest.TestCase):
    SCENE = "Every afternoon the children played in the garden. It was large and lovely."

    def test_strip_tags(self):
        self.assertEqual(take.strip_tags("[sad] Hello [long pause] world."), "Hello world.")
        self.assertEqual(take.strip_tags("garden [pause]. Next"), "garden. Next")
        self.assertEqual(take.strip_tags("“[whispers] Who are you?”"), "“Who are you?”")
        self.assertEqual(take.strip_tags("[sad] [softly] One.\n\n[long pause] Two."), "One. Two.")

    def test_tagged_script_passes(self):
        tagged = "[softly] Every afternoon the children played in the garden.\n[pause] It was large and lovely."
        self.assertEqual(take.check_script(self.SCENE, tagged), self.SCENE)

    def test_changed_word_or_punctuation_refused(self):
        for bad in ("[softly] Every afternoon the kids played in the garden. It was large and lovely.",
                    "Every afternoon the children played in the garden It was large and lovely.",
                    "Every afternoon the children played in the garden. It was large and lovely. Yes.",
                    "It was large and lovely. Every afternoon the children played in the garden.",
                    "[softly Every afternoon the children played in the garden. It was large and lovely.",
                    "Every afternoon the children played in the[pause]garden. It was large and lovely.",
                    ""):
            with self.assertRaises(ValueError, msg=bad):
                take.check_script(self.SCENE, bad)

    def test_brackets_in_the_book_text_must_survive(self):
        src = "He wrote [sic] in the margin."
        self.assertEqual(take.check_script(src, "[softly] He wrote [sic] in the margin."), src)
        self.assertEqual(take.check_script(src, "He wrote [sad] [sic] [pause] in the margin."), src)
        for bad in ("He wrote [sick] in the margin.", "He wrote in the margin.",
                    "[softly] He wrote sic in the margin."):
            with self.assertRaises(ValueError, msg=bad):
                take.check_script(src, bad)

    def test_empty_tag_refused(self):
        with self.assertRaises(ValueError):
            take.check_script("One.", "[] One.")


class SliceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)

    def slice(self, x, us, name="take.wav"):
        src = self.d / name
        write_wav(src, x)
        out = self.d / "out"
        out.mkdir(exist_ok=True)
        return src, out, take.slice_take(src, us, out)

    def assert_exact(self, src, out, info, us):
        joined = np.concatenate([pcm(out / f"{u['unit_key']}.wav") for u in us])
        ref = pcm(src)
        self.assertEqual(len(joined), len(ref))
        self.assertTrue(np.array_equal(joined, ref))
        self.assertEqual(info["samples"], len(ref))

    def test_cuts_in_silence_midpoints_and_concatenation_is_exact(self):
        us = units("A short one.", "This sentence is a fair bit longer than that.", "End.")
        # leading 0.2 s, tones with an 80 ms comma dip inside the long one, 0.4/0.6 s gaps
        x = np.concatenate([gap(0.2), tone(0.8), gap(0.4), tone(1.4), gap(0.08), tone(1.3),
                            gap(0.6), tone(0.5, 330), gap(0.15)])
        src, out, info = self.slice(x, us)
        self.assert_exact(src, out, info, us)
        mids = [0.2 + 0.8 + 0.2, 0.2 + 0.8 + 0.4 + 1.4 + 0.08 + 1.3 + 0.3]
        cuts = [b["at_s"] for b in info["boundaries"]]
        for got, want in zip(cuts, mids):
            self.assertAlmostEqual(got, want, delta=0.02)
        self.assertEqual([b["method"] for b in info["boundaries"]], ["silence", "silence"])
        self.assertEqual(info["estimated"], [])
        self.assertEqual([b["after"] for b in info["boundaries"]], ["s1-001", "s1-002"])

    def test_two_boundaries_never_share_one_silence_and_stay_monotonic(self):
        # character-proportional expectations both fall near the first silence
        us = units("A b.", "C d.", "This last unit is very much longer than the first two together.")
        x = np.concatenate([tone(1.0), gap(0.3), tone(3.0), gap(0.3), tone(1.0)])
        src, out, info = self.slice(x, us)
        self.assert_exact(src, out, info, us)
        cuts = [b["at_s"] for b in info["boundaries"]]
        self.assertAlmostEqual(cuts[0], 1.15, delta=0.02)
        self.assertAlmostEqual(cuts[1], 4.45, delta=0.02)

    def test_too_few_silences_estimates_and_records_it(self):
        us = units("One two three.", "Four five six.", "Seven eight nine.")
        # only one usable silence; the second join has a 40 ms low-energy dip only
        x = np.concatenate([tone(1.0), gap(0.4), tone(1.0), tone(0.04) * 0.02, tone(1.0, 330)])
        src, out, info = self.slice(x, us)
        self.assert_exact(src, out, info, us)
        methods = [b["method"] for b in info["boundaries"]]
        self.assertEqual(sorted(methods), ["estimated", "silence"])
        est = [b for b in info["boundaries"] if b["method"] == "estimated"]
        self.assertEqual(info["estimated"], [est[0]["after"]])
        self.assertEqual(est[0]["after"], "s1-002")
        self.assertAlmostEqual(est[0]["at_s"], 2.42, delta=0.05)  # the dip, inside +-400 ms

    def test_single_unit_is_the_whole_take(self):
        us = units("Only.")
        src, out, info = self.slice(np.concatenate([gap(0.1), tone(0.5), gap(0.1)]), us)
        self.assert_exact(src, out, info, us)
        self.assertEqual(info["boundaries"], [])

    def test_mp3_take_slices_exactly_against_its_decoded_pcm(self):
        us = units("A short one.", "And then another one.")
        wav = self.d / "src.wav"
        write_wav(wav, np.concatenate([tone(0.7), gap(0.5), tone(0.9)]))
        mp3 = self.d / "take.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libmp3lame",
                        "-b:a", "128k", str(mp3)], check=True)
        out = self.d / "out"
        out.mkdir()
        info = take.slice_take(mp3, us, out)
        self.assert_exact(mp3, out, info, us)
        self.assertEqual(info["boundaries"][0]["method"], "silence")

    def test_silent_or_empty_take_refused(self):
        with self.assertRaises(ValueError):
            self.slice(gap(1.0), units("One.", "Two."))


if __name__ == "__main__":
    unittest.main()
