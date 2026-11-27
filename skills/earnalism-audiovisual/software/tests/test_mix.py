import tempfile
import tracemalloc
import unittest
from unittest import mock

import numpy as np
from pathlib import Path

from eav import mix, retime
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

    def test_duck_db_out_of_range_refuses(self):
        for bad in (10, 25):
            with self.assertRaises(ValueError):
                mix.duck_and_master(self.speech, self.score, self.d / "o.wav", -16, duck_db=bad)

    def test_gate_miss_raises(self):
        with mock.patch.object(mix, "measure", return_value={"lufs": -16.0, "true_peak": -0.2}):
            with self.assertRaises(ValueError):
                mix.duck_and_master(self.speech, self.score, self.d / "o.wav", -16)
        with mock.patch.object(mix, "measure", return_value={"lufs": -12.0, "true_peak": -3.0}):
            with self.assertRaises(ValueError):
                mix.duck_and_master(self.speech, self.score, self.d / "o.wav", -16)

    def test_envelope_float32_and_bounded_memory(self):
        fr = mix._frame_gain_db(self.speech, 19)
        self.assertEqual(fr.dtype, np.float32)
        self.assertEqual(mix._gain_for(0, 1000, fr).dtype, np.float32)
        long_s, long_c = self.d / "ls.wav", self.d / "lc.wav"
        m.speech_gap_wav(long_s, 150, 10, 140)
        m.noise_wav(long_c, 150)
        full_stereo_f32 = 150 * 48000 * 2 * 4  # ~57 MB per whole-file array
        with mock.patch.object(mix, "CHUNK_FRAMES", 300):  # 3 s chunks
            tracemalloc.start()
            try:
                mix.duck_and_master(long_s, long_c, self.d / "lo.wav", -16)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
        self.assertLess(peak, full_stereo_f32 // 4)

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


def _tone(seconds, amp=0.3, freq=220.0):
    t = np.arange(int(seconds * 48000)) / 48000
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _gap(seconds):
    return np.zeros(int(seconds * 48000), np.float32)


def narration_fixture(path: Path) -> None:
    """~34 s: 1.5 s speech / 1.0 s pause for the first 10 s, then loud and quiet stretches (LRA ~5-6)."""
    parts = []
    for _ in range(4):
        parts += [_tone(1.5), _gap(1.0)]
    for _ in range(4):
        parts += [_tone(2.7), _gap(0.3)]
    for _ in range(4):
        parts += [_tone(2.7, amp=0.12), _gap(0.3)]
    retime.write(path, np.concatenate(parts))


class AudiobookMasterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.narr = self.d / "narration.wav"
        narration_fixture(self.narr)
        self.bed = self.d / "bed.wav"
        m.noise_wav(self.bed, 12)
        self.title, self.author, self.closing = (self.d / f"{n}.wav" for n in ("t", "a", "c"))
        retime.write(self.title, _tone(1.2, freq=300))
        retime.write(self.author, _tone(0.9, freq=330))
        retime.write(self.closing, _tone(0.8, freq=260))

    def tearDown(self):
        self.tmp.cleanup()

    def probe(self, path):
        import json
        import subprocess
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "stream=codec_name,channels,bit_rate", "-of", "json", str(path)],
                             check=True, capture_output=True, text=True).stdout
        return json.loads(out)["streams"][0]

    def master_part(self, name="out.mp3", **cues):
        out = self.d / name
        return mix.master_audiobook(self.narr, {"part": self.bed, **cues}, out), out

    def test_audiobook_master_meets_targets_after_encode(self):
        info, out = self.master_part(opening=[self.title, self.author], closing=self.closing)
        s = self.probe(out)
        self.assertEqual((s["codec_name"], s["channels"], s["bit_rate"]), ("mp3", 1, "64000"))
        got = mix.measure(out)  # measured on the encoded file, not on the PCM
        self.assertLessEqual(abs(got["lufs"] - (-18)), 1)
        self.assertLessEqual(got["true_peak"], -2.0)
        self.assertGreaterEqual(got["lra"], 4.0)
        self.assertLessEqual(got["lra"], 8.0)
        for k in ("lufs", "true_peak", "lra"):
            self.assertAlmostEqual(info[k], got[k], delta=0.2)

    def test_flat_narration_misses_the_lra_gate(self):
        flat = self.d / "flat.wav"
        retime.write(flat, np.concatenate([_tone(2.7), _gap(0.3)] * 8))
        with self.assertRaisesRegex(ValueError, "LRA"):
            mix.master_audiobook(flat, {}, self.d / "flat.mp3")

    def test_opens_with_title_and_author_and_ends_with_closing_then_3s_room_tone(self):
        info, out = self.master_part(opening=[self.title, self.author], closing=self.closing)
        narr_s = len(m.samples(self.narr)) / 48000
        lead = 1.0 + 1.2 + 0.8 + 0.9 + 1.5  # lead-in, title, gap, author, gap before the body
        self.assertAlmostEqual(info["voice_offset_s"], lead, delta=0.3)  # minus the 40 ms joins
        # spec order: narration, 3 s of room tone, the closing word, then room tone (>= 1 s)
        self.assertAlmostEqual(info["closing_start_s"], info["voice_offset_s"] + narr_s + 3.0, delta=0.1)
        self.assertGreaterEqual(info["duration_s"], info["closing_start_s"] + 0.8 + 1.0)
        x = m.samples(out)
        self.assertGreater(m.rms_db(x[int(1.2 * 48000):int(2.0 * 48000)]), -35)  # the title is spoken
        gap = x[int((info["closing_start_s"] - 2.5) * 48000):int((info["closing_start_s"] - 0.3) * 48000)]
        self.assertLess(m.rms_db(gap), -45)        # 3 s of room tone before the closing word
        self.assertGreater(m.rms_db(gap), -90)
        tail = x[-int(0.8 * 48000):]
        self.assertLess(m.rms_db(tail), -45)       # room tone, not speech or a bed
        self.assertGreater(m.rms_db(tail), -90)    # and never digital zero

    def stem(self, info):
        return m.samples(Path(info["bed_stem"]))

    def test_bed_at_least_24lu_under_voice(self):
        info, out = self.master_part()
        self.assertGreaterEqual(info["bed_under_voice_lu"], 24.0)
        stem = self.d / "stem.wav"
        retime.write(stem, self.stem(info))
        self.assertGreaterEqual(mix.measure(out)["lufs"] - mix.measure(stem)["lufs"], 24.0)

    def test_bed_only_at_intro_outro_and_part_changes(self):
        info, _ = self.master_part()
        x = self.stem(info)
        self.assertGreater(m.rms_db(x[int(2.0 * 48000):int(3.0 * 48000)]), -90)   # part change at the start
        self.assertEqual(float(np.abs(x[int(20 * 48000):int(28 * 48000)]).max()), 0.0)  # none mid-chapter

    def test_bed_ducks_6_db_under_speech(self):
        info, _ = self.master_part()
        x = self.stem(info)
        open_bed = m.rms_db(x[int(0.7 * 48000):int(1.3 * 48000)])    # before the voice enters (1.5 s)
        under = m.rms_db(x[int(2.0 * 48000):int(2.8 * 48000)])
        self.assertAlmostEqual(open_bed - under, 6.0, delta=1.0)

    def test_no_pumping_in_a_longer_heading_pause(self):
        long_pause = self.d / "long.wav"
        retime.write(long_pause, np.concatenate([_tone(1.5), _gap(1.6), _tone(1.5), _gap(1.6), _tone(2.0)] * 3))
        with mock.patch.object(mix, "LRA_LU", (0.0, 20.0)):
            info = mix.master_audiobook(long_pause, {"part": self.bed}, self.d / "lp.mp3")
        x = m.samples(Path(info["bed_stem"]))
        lvl = lambda a, b: m.rms_db(x[int(a * 48000):int(b * 48000)])
        # voice 1.5-3.0 s, 1.6 s pause 3.0-4.6 s, voice 4.6-6.1 s
        for a, b in ((3.2, 3.8), (3.8, 4.5)):
            self.assertLess(abs(lvl(a, b) - lvl(2.0, 2.8)), 3.0)

    def test_memory_is_chunked_on_a_ten_minute_part(self):
        long_s = self.d / "ten.wav"
        m.speech_gap_wav(long_s, 600, 3, 590)
        whole = 600 * 48000 * 4  # one whole-part float32 array
        with mock.patch.object(mix, "LRA_LU", (0.0, 20.0)):
            tracemalloc.start()
            try:
                mix.master_audiobook(long_s, {"part": self.bed}, self.d / "ten.mp3")
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
        self.assertLess(peak, whole // 3)

    def test_no_score_pumping_in_pauses(self):
        info, _ = self.master_part()
        x = self.stem(info)
        lvl = lambda a, b: m.rms_db(x[int(a * 48000):int(b * 48000)])
        # voice 1.5-3.0 s, pause 3.0-4.0 s, voice 4.0-5.5 s
        speech = (lvl(2.0, 2.8) + lvl(4.3, 5.2)) / 2
        for a, b in ((3.2, 3.5), (3.5, 3.9)):
            self.assertLess(abs(lvl(a, b) - speech), 3.0)


if __name__ == "__main__":
    unittest.main()


class LoudnormStatsTests(unittest.TestCase):
    BLOCK = ('{\n\t"input_i" : "-20.1",\n\t"input_tp" : "-3.0",\n\t"target_offset" : "0.2"\n}')

    def test_ffmpeg6_json_last(self):
        err = "size=N/A time=00:00:08\n[Parsed_loudnorm_0 @ 0x55d]\n" + self.BLOCK + "\n"
        self.assertEqual(mix.loudnorm_stats(err)["input_i"], "-20.1")

    def test_ffmpeg8_trailing_summary_with_stray_brace(self):
        err = ("[Parsed_loudnorm_0 @ 0x55d]\n" + self.BLOCK + "\n"
               "[out#0/null @ 0x1] video:0KiB audio:2KiB {muxing overhead: unknown}\n"
               "size=N/A time=00:00:08 {x}\n")
        s = mix.loudnorm_stats(err)
        self.assertEqual(s["input_tp"], "-3.0")

    def test_no_block_raises(self):
        with self.assertRaises(ValueError):
            mix.loudnorm_stats("[out#0/null] nothing here {stray}\n")
