import json
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from eav import film, qc
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


SIZE = "320x176"


def _lavfi(path, src, seconds, vf=""):
    sep = ":" if "=" in src else "="
    ff("-f", "lavfi", "-i", f"{src}{sep}s={SIZE}:r=24:d={seconds}", *(["-vf", vf] if vf else []),
       "-pix_fmt", "yuv420p", str(path))


def _luma(path, expr, seconds):
    """A flat-colour video whose luma is the geq expression (N = frame number, T = seconds)."""
    ff("-f", "lavfi", "-i", f"nullsrc=s={SIZE}:r=24:d={seconds},geq=lum='{expr}':cb=128:cr=128",
       "-pix_fmt", "yuv420p", "-crf", "4", str(path))


def _still_png(path):
    ff("-f", "lavfi", "-i", f"testsrc2=s={SIZE}:r=24", "-frames:v", "1", str(path))


class EditGateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_static_7s_flags_r1(self):
        png = self.td / "still.png"
        _still_png(png)
        static, glide_v = self.td / "static.mp4", self.td / "glide.mp4"
        ff("-loop", "1", "-framerate", "24", "-i", str(png), "-t", "7", "-pix_fmt", "yuv420p", str(static))
        ff("-loop", "1", "-framerate", "24", "-i", str(png), "-vf",
           f"zoompan=z='1+0.2*on/168':d=168:s={SIZE}:fps=24", "-t", "7", "-pix_fmt", "yuv420p", str(glide_v))
        for v in (static, glide_v):   # a zoom over one still is still no new information
            gaps = qc.new_info_gaps(v, 0.9)
            self.assertEqual(len(gaps), 1, v.name)
            self.assertGreater(gaps[0][1] - gaps[0][0], 6.0)

    def test_moving_clip_is_not_an_r1_gap(self):
        wan = self.td / "wan.mp4"
        _luma(wan, "128+110*sin(X*Y/700+T*4+X/20)", 8)
        self.assertEqual(qc.new_info_gaps(wan, 0.9), [])
        short = self.td / "short.mp4"      # 4 s of one still: under the 6 s limit
        _lavfi(short, "color=c=gray", 4)
        self.assertEqual(qc.new_info_gaps(short, 0.9), [])

    def test_black_rows_flagged(self):
        bars, clean = self.td / "bars.mp4", self.td / "clean.mp4"
        _lavfi(clean, "testsrc2", 2)
        _lavfi(bars, "testsrc2", 2, "drawbox=x=0:y=0:w=iw:h=12:color=black:t=fill,"
                                     "drawbox=x=0:y=ih-12:w=iw:h=12:color=black:t=fill")
        self.assertEqual(qc.black_bars(clean), [])
        flagged = qc.black_bars(bars)
        self.assertGreaterEqual(len(flagged), 2)
        self.assertLess(flagged[0], 0.6)
        dark = self.td / "dark.mp4"        # a fade to black is not a bar: nothing is visible inside
        _luma(dark, "8", 2)
        self.assertEqual(qc.black_bars(dark), [])

    def test_flash_over_3_per_s_flagged(self):
        fast, slow = self.td / "fast.mp4", self.td / "slow.mp4"
        _luma(fast, "if(mod(floor(N/2),2),235,16)", 3)    # 6 flashes a second
        _luma(slow, "if(mod(floor(T),2),235,16)", 4)      # one flash a second
        self.assertGreater(qc.flashes(fast)["max_per_s"], 3)
        self.assertLessEqual(qc.flashes(slow)["max_per_s"], 3)

    def test_large_jumps_only_at_planned_cuts(self):
        v = self.td / "cuts.mp4"
        _luma(v, "if(mod(floor(T),2),235,16)", 3)         # jumps at 1.0 s and 2.0 s
        self.assertEqual(qc.flashes(v, cuts=[1.0, 2.0])["unplanned"], [])
        self.assertEqual(qc.flashes(v, cuts=[1.0 + 1 / 24, 2.0 - 1 / 24])["unplanned"], [])   # within one frame
        self.assertEqual(len(qc.flashes(v, cuts=[1.0])["unplanned"]), 1)
        self.assertIsNone(qc.flashes(v)["unplanned"])      # no plan known: not judged

    def test_hitch_in_dissolve_flagged(self):
        bad, good, cut = self.td / "bad.mp4", self.td / "good.mp4", self.td / "cut.mp4"
        _luma(bad, "40+4*N+if(gte(N,10),20,0)", 2)
        _luma(good, "40+4*N", 2)
        _luma(cut, "if(gte(N,24),200,40)", 2)             # a hard cut is not a hitch
        hits = qc.frame_hitches(bad)
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0], 10 / 24, delta=1 / 24 + 0.01)
        self.assertEqual(qc.frame_hitches(good), [])
        self.assertEqual(qc.frame_hitches(cut), [])

    def test_hold_hashes_reports_scenes_reusing_a_still(self):
        film_dir = self.td / "film-01"
        (film_dir / "shots").mkdir(parents=True)
        (film_dir / "stills").mkdir()
        shot = lambda n, motion: {"n": n, "motion": motion, "start": n - 1, "end": n}
        plans = {"s1": ["glide", "glide", "static"], "s2": ["glide", "glide"], "s3": ["glide", "wan", "glide"]}
        for sid, motions in plans.items():
            (film_dir / "shots" / f"{sid}.json").write_text(json.dumps(
                {"scene_id": sid, "shots": [shot(i, m) for i, m in enumerate(motions, 1)]}))
            (film_dir / "shots" / f"{sid}.input.json").write_text("{}")     # the planner input is not a plan
        data = {"s1-1": b"a", "s1-2": b"a", "s1-3": b"b", "s2-1": b"c", "s2-2": b"d", "s3-1": b"e", "s3-3": b"e"}
        for k, b in data.items():
            (film_dir / "stills" / f"{k}.png").write_bytes(b)
        self.assertEqual(qc.hold_hashes(film_dir / "shots"), ["s1"])   # s3 reuses it across a Wan beat


def _wav(path, x, rate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def _speech_and_music(seconds=4.0, margin_db=17.0, rate=48000, seed=1):
    t = np.arange(int(seconds * rate)) / rate
    voice = 0.3 * np.sin(2 * np.pi * 220 * t) * ((t > 0.5) & (t < 3.5))
    noise = np.random.default_rng(seed).standard_normal(len(t))
    noise *= 0.3 / np.sqrt(2) * 10 ** (-margin_db / 20) / noise.std()    # voice rms is 0.3/sqrt(2)
    return voice, voice + noise


class AudioGateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_margin_is_estimated_from_the_residual(self):
        for margin, ok in ((17.0, True), (10.0, False), (22.0, False)):
            voice, mixed = _speech_and_music(margin_db=margin)
            _wav(self.td / "v.wav", voice)
            _wav(self.td / "m.wav", mixed)
            r = qc.audio_gates(self.td / "m.wav", self.td / "v.wav")
            self.assertAlmostEqual(r["margin_db"], margin, delta=0.6)
            self.assertEqual(r["margin_ok"], ok, margin)

    def test_digital_zero_flagged(self):
        voice, mixed = _speech_and_music()
        _wav(self.td / "v.wav", voice)
        hole = mixed.copy()
        hole[48000:48000 + 4800] = 0.0           # 100 ms of exact zeros
        brief = mixed.copy()
        brief[48000:48000 + 1440] = 0.0          # 30 ms: allowed
        for name, x, runs in (("hole", hole, 1), ("brief", brief, 0), ("clean", mixed, 0)):
            _wav(self.td / f"{name}.wav", x)
            r = qc.audio_gates(self.td / f"{name}.wav", self.td / "v.wav")
            self.assertEqual(len(r["digital_zero"]), runs, name)
            self.assertEqual(r["digital_zero_ok"], runs == 0)

    def test_true_peak_limit_follows_the_film_kind(self):
        voice, mixed = _speech_and_music()
        mixed = mixed / np.abs(mixed).max() * 10 ** (-1.2 / 20)     # peaks at -1.2 dBFS
        _wav(self.td / "v.wav", voice)
        _wav(self.td / "m.wav", mixed)
        legacy = qc.audio_gates(self.td / "m.wav", self.td / "v.wav")
        shots = qc.audio_gates(self.td / "m.wav", self.td / "v.wav", shots=True)
        self.assertTrue(legacy["true_peak_ok"])
        self.assertFalse(shots["true_peak_ok"])
        self.assertEqual((legacy["true_peak_max"], shots["true_peak_max"]), (-1.0, film.SHOT_TP_MAX))


class SoundOnPictureTests(unittest.TestCase):
    PLAN = {"shots": [{"n": 1, "start": 0.0, "end": 5.0, "sound": {"sfx": ["rain", "door"]}},
                      {"n": 2, "start": 5.0, "end": 9.0, "sound": {"sfx": ["door"]}},
                      {"n": 3, "start": 9.0, "end": 12.0, "sound": {"sfx": []}}]}

    def test_every_listed_sfx_needs_an_entry_over_its_shot(self):
        fx = [{"path": "amb/rain-loop.wav", "at": 0.0, "dur": 12.0},
              {"path": "foley/door.wav", "at": 6.0, "dur": 1.0}]
        # door is placed in shot 2 only: shot 1 lists it too and has none
        self.assertEqual(qc.sound_on_picture(self.PLAN, fx), ["shot 1: door"])
        fx.append({"path": "foley/door.wav", "at": 4.5, "dur": 1.0})     # starts in shot 1
        self.assertEqual(qc.sound_on_picture(self.PLAN, fx), [])
        self.assertEqual(qc.sound_on_picture(self.PLAN, []), ["shot 1: rain", "shot 1: door", "shot 2: door"])


class CaptionGateTests(unittest.TestCase):
    def test_written_captions_meet_the_limits(self):
        timing = [{"unit_key": "a", "start": 0.0, "end": 3.0}, {"unit_key": "b", "start": 3.5, "end": 7.0}]
        units = [{"unit_key": "a", "text": "One quiet line of the story."}, {"unit_key": "b", "text": "Then another follows it."}]
        for fmt in ("vtt", "srt"):
            text = film.captions(timing, units, "en", fmt=fmt)
            self.assertEqual(qc.check_captions(text, "en"), [], fmt)

    def test_violations_are_reported(self):
        vtt = ("WEBVTT\n\n00:00:00.000 --> 00:00:00.500\nToo short\n\n"
               "00:00:01.000 --> 00:00:09.500\nToo long on screen\n\n"
               "00:00:10.000 --> 00:00:13.000\none\ntwo\nthree\n\n"
               "00:00:14.000 --> 00:00:17.000\n" + "x" * 43 + "\n\n"
               "00:00:18.000 --> 00:00:19.500\n" + "দ" * 40 + "\n")
        found = qc.check_captions(vtt, "bn")
        joined = " | ".join(found)
        for word in ("duration", "3 lines", "43 characters", "characters/s"):
            self.assertIn(word, joined)
        self.assertGreaterEqual(len(found), 5)


class FilmGatesTests(unittest.TestCase):
    def test_planned_cuts_follow_the_edit(self):
        plans = [{"seconds": 4.0, "shots": [{"start": 0.0, "end": 2.5}, {"start": 2.5, "end": 4.0}]},
                 {"seconds": 3.0, "shots": [{"start": 0.0, "end": 3.0}]}]
        cuts = qc.planned_cuts(plans)
        lead = film.TITLE_S
        self.assertEqual(cuts[:4], [lead, lead + 2.5, lead + 4.0, lead + 7.0])
        self.assertEqual(cuts[-1], lead + 7.0 + film.CREDITS_S)


class FilmGateRunTests(unittest.TestCase):
    def test_gates_run_over_a_film_folder(self):
        with tempfile.TemporaryDirectory() as td:
            fd = Path(td) / "film-01"
            for d in ("shots", "stills", "voice", "audio"):
                (fd / d).mkdir(parents=True)
            video = Path(td) / "film.mp4"
            _lavfi(video, "testsrc2", 4)
            sp = {"scene_id": "s1", "seconds": 4.0, "shots": [
                {"n": 1, "motion": "glide", "start": 0.0, "end": 4.0, "sound": {"sfx": ["rain"]}}]}
            (fd / "shots" / "s1.json").write_text(json.dumps(sp))
            voice, mixed = _speech_and_music()
            _wav(fd / "voice" / "s1.wav", voice)
            _wav(fd / "audio" / "film.mix.wav", mixed)
            (fd / "audio" / "s1.mix.json").write_text(json.dumps(
                {"fx": {"base": "x", "ambience": [{"path": "rain.wav", "at": 0.0, "dur": 4.0}], "foley": []}}))
            timing = [{"unit_key": "a", "start": 0.5, "end": 3.0}]
            (fd / "film-01.vtt").write_text(film.captions(timing, [{"unit_key": "a", "text": "A quiet line."}], "en"))
            checks, detail, not_run = qc.film_gates(video, fd, ["s1"], "en")
            self.assertEqual(not_run, [])
            self.assertTrue(all(checks.values()), checks)
            self.assertEqual(set(checks), {"new_info", "holds", "black_bars", "hitches", "flashes",
                                           "sound_on_picture", "captions", "margin", "digital_zero"})
            (fd / "audio" / "s1.mix.json").write_text(json.dumps({"fx": {"ambience": [], "foley": []}}))
            checks, detail, _ = qc.film_gates(video, fd, ["s1"], "en")
            self.assertFalse(checks["sound_on_picture"])
            self.assertEqual(detail["sound_on_picture"], ["s1 shot 1: rain"])
            (fd / "audio" / "film.mix.wav").unlink()
            self.assertTrue(qc.film_gates(video, fd, ["s1"], "en")[2])


if __name__ == "__main__":
    unittest.main()
