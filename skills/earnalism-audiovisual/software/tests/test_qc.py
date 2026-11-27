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
        # a name is a whole word of the file stem: "rain" is not in "train", "door" is not in "indoor"
        wrong = [{"path": "foley/train.wav", "at": 0.0, "dur": 12.0}, {"path": "foley/indoor-room.wav", "at": 0.0, "dur": 12.0}]
        self.assertEqual(len(qc.sound_on_picture(self.PLAN, wrong)), 3)


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


class DigitalZeroTests(unittest.TestCase):
    def test_zero_runs_on_the_delivered_audio(self):
        rate = 48000
        t = np.arange(6 * rate) / rate
        body = 0.3 * np.sin(2 * np.pi * 220 * t)
        floor = np.random.default_rng(3).standard_normal(len(t)) * 5e-4        # room tone, about -63 dBFS
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            silent_title = body.copy()
            silent_title[:rate] = 0.0                                            # exact zero under the title card
            toned = body.copy()
            toned[:rate] = floor[:rate]
            hole = toned.copy()
            hole[3 * rate:3 * rate + 4800] = 0.0                                 # 100 ms inside the body
            tail = toned.copy()
            tail[-int(1.6 * rate):] = 0.0                                        # the final fade tail
            for name, x in (("silent", silent_title), ("toned", toned), ("hole", hole), ("tail", tail)):
                _wav(td / f"{name}.wav", x)
            self.assertEqual(qc.digital_zero_runs(td / "silent.wav", 1.6), [(0.0, 1.0)])
            self.assertEqual(qc.digital_zero_runs(td / "toned.wav", 1.6), [])
            self.assertEqual(len(qc.digital_zero_runs(td / "hole.wav", 1.6)), 1)
            self.assertEqual(qc.digital_zero_runs(td / "tail.wav", 1.6), [])     # only the fade tail is exempt
            self.assertEqual(len(qc.digital_zero_runs(td / "tail.wav")), 1)


def _fixture(root, scene="s1", gain=1.0, ambience_db=None, margin=17.0, recorded=17.0, peak_db=-200.0, sfx=(), seed=1):
    """One scene of a film folder: plan, voice, scene mix (+ mix.json as cue writes it)."""
    for d in ("shots", "stills", "voice", "audio"):
        (root / d).mkdir(parents=True, exist_ok=True)
    voice, mixed = _speech_and_music(margin_db=margin, seed=seed)
    if ambience_db is not None:        # ambience ambience_db under the music: music rms is voice rms - margin
        amb = np.random.default_rng(seed + 50).standard_normal(len(voice))
        music_rms = 0.3 / np.sqrt(2) * 10 ** (-margin / 20)
        mixed = mixed + amb / amb.std() * music_rms * 10 ** (-ambience_db / 20)
    _wav(root / "voice" / f"{scene}.wav", voice)
    _wav(root / "audio" / f"{scene}.mix.wav", mixed * gain)
    (root / "shots" / f"{scene}.json").write_text(json.dumps({"scene_id": scene, "seconds": 4.0, "shots": [
        {"n": 1, "motion": "glide", "start": 0.0, "end": 4.0, "sound": {"sfx": list(sfx)}}]}))
    (root / "audio" / f"{scene}.mix.json").write_text(json.dumps(
        {"voice_over_music_db": recorded, "music_bus_peak_rms_db": peak_db,
         "fx": {"ambience": [{"path": "rain.wav", "at": 0.0, "dur": 4.0}], "foley": []}}))
    return voice, mixed * gain


def _film_audio(root, voice_mix, video):
    """The delivered film: a picture with the scene's mix as its audio (room tone is in the mix itself)."""
    _wav(root / "delivered.wav", voice_mix)
    ff("-i", str(video), "-i", str(root / "delivered.wav"), "-c:v", "copy", "-c:a", "aac", "-shortest",
       str(root / "film.mp4"))
    return root / "film.mp4"


class FilmGateRunTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.fd = self.td / "film-01"
        self.video = self.td / "picture.mp4"
        _lavfi(self.video, "testsrc2", 4)
        timing = [{"unit_key": "a", "start": 0.5, "end": 3.0}]
        self.vtt = film.captions(timing, [{"unit_key": "a", "text": "A quiet line."}], "en")

    def tearDown(self):
        self._td.cleanup()

    def run_gates(self, scenes=("s1",), **fixture):
        voice, mixed = None, None
        for sid in scenes:
            voice, mixed = _fixture(self.fd, sid, **fixture)
        (self.fd / "film-01.vtt").write_text(self.vtt)
        self.film = _film_audio(self.td, mixed, self.video)
        return qc.film_gates(self.film, self.fd, list(scenes), "en")

    def test_gates_run_over_a_film_folder(self):
        checks, detail, not_run = self.run_gates(sfx=["rain"])
        self.assertEqual(not_run, {})
        self.assertTrue(all(checks.values()), checks)
        self.assertEqual(set(checks), {"new_info", "holds", "black_bars", "hitches", "flashes", "sound_on_picture",
                                       "captions", "margin", "digital_zero", "peak_silence"})

    def test_margin_is_judged_per_scene_not_over_the_film(self):
        """Two scenes at 17 dB voice over music whose masters differ by 1.6 dB (each is loudness-normalised with
        its own gain) pass: one fit over the whole film would read 15.5 dB."""
        _fixture(self.fd, "s1")
        _fixture(self.fd, "s2", gain=10 ** (1.6 / 20), seed=2)
        (self.fd / "film-01.vtt").write_text(self.vtt)
        voice, mixed = _speech_and_music()
        film_audio = _film_audio(self.td, np.concatenate([mixed, mixed * 10 ** (1.6 / 20)]), self.video)
        checks, detail, not_run = qc.film_gates(film_audio, self.fd, ["s1", "s2"], "en")
        self.assertTrue(checks["margin"], detail["margin"])
        self.assertAlmostEqual(detail["margin"]["s2"]["residual_db"], 17.0, delta=0.6)

    def test_ambience_is_judged_on_the_residual(self):
        checks, detail, _ = self.run_gates(ambience_db=2.0)
        m = detail["margin"]["s1"]
        self.assertTrue(m["music_ok"])                              # cue's recorded music-only margin is 17
        self.assertAlmostEqual(m["residual_db"], 14.9, delta=0.5)   # music + ambience only 15 dB under the voice
        self.assertEqual(m["residual_ok"], m["residual_db"] >= qc.RESIDUAL_MARGIN_MIN)
        checks, detail, _ = self.run_gates(ambience_db=6.0)
        self.assertTrue(checks["margin"], detail["margin"])

    def test_a_scene_at_12_db_fails(self):
        checks, detail, _ = self.run_gates(margin=12.0)
        self.assertFalse(checks["margin"])
        self.assertFalse(detail["margin"]["s1"]["residual_ok"])
        checks, detail, _ = self.run_gates(recorded=14.0)           # the cue's own record outside 16-18
        self.assertFalse(checks["margin"])
        self.assertFalse(detail["margin"]["s1"]["music_ok"])

    def test_peak_silence_gate(self):
        self.assertTrue(self.run_gates(peak_db=-85.0)[0]["peak_silence"])
        self.assertFalse(self.run_gates(peak_db=-60.0)[0]["peak_silence"])
        _fixture(self.fd)
        info = json.loads((self.fd / "audio" / "s1.mix.json").read_text())
        del info["music_bus_peak_rms_db"]
        (self.fd / "audio" / "s1.mix.json").write_text(json.dumps(info))
        self.assertIn("peak_silence", qc.film_gates(self.film, self.fd, ["s1"], "en")[2])

    def test_digital_zero_is_checked_on_the_delivered_film(self):
        voice, mixed = _fixture(self.fd)
        (self.fd / "film-01.vtt").write_text(self.vtt)
        holed = mixed.copy()
        holed[48000:48000 + 4800] = 0.0
        checks, detail, _ = qc.film_gates(_film_audio(self.td, holed, self.video), self.fd, ["s1"], "en")
        self.assertFalse(checks["digital_zero"])
        silent = mixed.copy()
        silent[:48000] = 0.0                                        # exact-zero title silence
        checks, _, _ = qc.film_gates(_film_audio(self.td, silent, self.video), self.fd, ["s1"], "en")
        self.assertFalse(checks["digital_zero"])
        checks, _, _ = qc.film_gates(_film_audio(self.td, mixed, self.video), self.fd, ["s1"], "en")
        self.assertTrue(checks["digital_zero"])

    def test_gates_that_cannot_run_are_named(self):
        self.run_gates(sfx=["rain"])
        (self.fd / "voice" / "s1.wav").unlink()
        (self.fd / "film-01.vtt").unlink()
        info = json.loads((self.fd / "audio" / "s1.mix.json").read_text())
        del info["fx"]
        (self.fd / "audio" / "s1.mix.json").write_text(json.dumps(info))
        checks, detail, not_run = qc.film_gates(self.film, self.fd, ["s1"], "en")
        self.assertEqual(set(not_run), {"margin", "captions", "sound_on_picture"})
        self.assertNotIn("margin", checks)
        (self.fd / "shots" / "s1.json").unlink()                     # a missing plan is named, not a traceback
        self.assertTrue(qc.film_gates(self.film, self.fd, ["s1"], "en")[2])

    def test_sound_on_picture_keeps_misses_when_a_scene_has_no_fx(self):
        _fixture(self.fd, "s1", sfx=["door"])
        _fixture(self.fd, "s2", sfx=["door"], seed=2)
        info = json.loads((self.fd / "audio" / "s2.mix.json").read_text())
        del info["fx"]
        (self.fd / "audio" / "s2.mix.json").write_text(json.dumps(info))
        (self.fd / "film-01.vtt").write_text(self.vtt)
        voice, mixed = _speech_and_music()
        checks, detail, not_run = qc.film_gates(_film_audio(self.td, mixed, self.video), self.fd, ["s1", "s2"], "en")
        self.assertIn("sound_on_picture", not_run)
        self.assertEqual(detail["sound_on_picture"], ["s1 shot 1: door"])   # s1's miss survives
        self.assertFalse(checks["sound_on_picture"])


if __name__ == "__main__":
    unittest.main()
