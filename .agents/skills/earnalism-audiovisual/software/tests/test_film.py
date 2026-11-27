import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from eav import film, mix
from tests import _media as m

PLAN = {"series": "x", "films": [{"unit_ids": [], "scenes": [
    {"scene_id": "s1", "text": "One. Two."}, {"scene_id": "s2", "text": "Three."}]}]}
UNITS = [
    {"unit_key": "s1-001", "text": "One.", "description": "d", "pause_after_ms": 400},
    {"unit_key": "s1-002", "text": "Two.", "description": "d", "pause_after_ms": 800},
    {"unit_key": "s2-001", "text": "Three.", "description": "d", "pause_after_ms": 800},
]


def probe(path, stream, entry):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream,
                          "-show_entries", f"stream={entry}", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)["streams"][0][entry]


class FilmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.wavs = self.d / "wavs"
        self.wavs.mkdir()
        for u in UNITS:
            m.sine_wav(self.wavs / f"{u['unit_key']}.wav", 1.5)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_unit_refuses(self):
        (self.wavs / "s2-001.wav").unlink()
        with self.assertRaises(ValueError):
            film.narration_track(UNITS, self.wavs, self.d / "n.wav")

    def test_duplicate_unit_refuses(self):
        with self.assertRaises(ValueError):
            film.narration_track(UNITS + [UNITS[0]], self.wavs, self.d / "n.wav")

    def test_narration_timing(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        self.assertAlmostEqual(t[0]["start"], 0)
        self.assertAlmostEqual(t[0]["end"], 1.5, delta=0.02)
        self.assertAlmostEqual(t[1]["start"], 1.9, delta=0.02)
        self.assertAlmostEqual(m.samples(self.d / "n.wav").size / 48000, t[-1]["end"], delta=0.05)

    def test_pause_inserted_once_total_is_speech_plus_pauses(self):
        """R8: narration_track is the only place pauses are added; ends are speech ends."""
        durs = [1.2, 0.7, 0.9]
        for u, d in zip(UNITS, durs):
            m.sine_wav(self.wavs / f"{u['unit_key']}.wav", d)
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        for row, d in zip(t, durs):
            self.assertAlmostEqual(row["end"] - row["start"], d, delta=0.02)
        total = m.samples(self.d / "n.wav").size / 48000
        self.assertAlmostEqual(total, sum(durs) + 0.4 + 0.8, delta=0.03)  # no pause after last
        self.assertAlmostEqual(t[-1]["end"], total, delta=0.03)

    def test_subtitles_cover_timing(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        srt = film.subtitles(t, UNITS)
        cues = [b.split("\n") for b in srt.strip().split("\n\n")]
        self.assertEqual(len(cues), 3)

        def sec(s):
            h, mi, rest = s.split(":")
            sc, ms = rest.split(",")
            return int(h) * 3600 + int(mi) * 60 + int(sc) + int(ms) / 1000
        spans = [tuple(sec(x) for x in c[1].split(" --> ")) for c in cues]
        for (a, b), (c, _) in zip(spans, spans[1:]):
            self.assertLess(a, b)
            self.assertLessEqual(b, c)
        dur = m.samples(self.d / "n.wav").size / 48000
        self.assertAlmostEqual(spans[-1][1], dur, delta=0.05)

    def test_assemble_duration_matches_audio(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        mixed = self.d / "mixed.wav"
        m.sine_wav(mixed, t[-1]["end"] + 0.5, freq=330)
        stills = self.d / "stills"
        stills.mkdir()
        for name, col in (("s1", "red"), ("s2", "blue")):
            Image.new("RGB", (320, 180), col).save(stills / f"{name}.png")
        logo, card = self.d / "logo.png", self.d / "card.png"
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(logo)
        Image.new("RGB", (320, 180), "black").save(card)
        out = self.d / "film.mp4"
        info = film.assemble(PLAN, t, stills, mixed, logo, card, out)
        self.assertEqual((probe(out, "v:0", "width"), probe(out, "v:0", "height")), (1920, 1080))
        v = float(probe(out, "v:0", "duration"))
        a = float(probe(out, "a:0", "duration"))
        self.assertAlmostEqual(v, a, delta=0.1)
        self.assertAlmostEqual(v, info["duration"], delta=0.15)

    def test_video_end_card_is_appended_whole_with_its_own_sound(self):
        """The approved END is a 3 s video with its own sound (earnalism-video): it is appended
        unchanged in length, its audio follows the film's, and nothing of the score bleeds in."""
        t, stills, logo = self._assemble_inputs()
        mixed = self.d / "mixed.wav"
        m.ff("-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={t[-1]['end']}", str(mixed))  # silent bed
        end = self.d / "END.mp4"
        m.ff("-f", "lavfi", "-i", "color=c=navy:s=320x180:r=30:d=2", "-f", "lavfi",
             "-i", "sine=frequency=1000:sample_rate=48000:duration=2", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(end))
        out = self.d / "film-end.mp4"
        info = film.assemble(PLAN, t, stills, mixed, logo, end, out, size=(320, 180))
        self.assertAlmostEqual(info["duration"], t[-1]["end"] + 2.0, delta=0.1)
        self.assertAlmostEqual(float(probe(out, "v:0", "duration")), info["duration"], delta=0.15)
        self.assertAlmostEqual(float(probe(out, "a:0", "duration")), info["duration"], delta=0.15)
        tail, body = self.d / "tail.wav", self.d / "body.wav"
        m.ff("-ss", f"{t[-1]['end'] + 0.5:.3f}", "-t", "1", "-i", str(out), "-ac", "1", str(tail))
        m.ff("-ss", "0.5", "-t", "1", "-i", str(out), "-ac", "1", str(body))
        self.assertGreater(m.rms_db(m.samples(tail)), -30)   # the END's own sound
        self.assertLess(m.rms_db(m.samples(body)), -60)      # the silent bed stays silent

    def test_encoded_film_keeps_the_true_peak_gate(self):
        """বিচারক film-01: a -1.5 dBTP mix came out of the AAC encode at -0.9 dBTP and failed QC.
        The encoded film is measured and, if over -1 dBTP, its body audio is lowered to fit."""
        t, stills, logo = self._assemble_inputs()
        hot = self.d / "hot.wav"
        m.ff("-f", "lavfi", "-i", f"aevalsrc=0.97*sin(2*PI*997*t)|0.97*sin(2*PI*997*t):s=48000:d={t[-1]['end']}",
             str(hot))  # stereo, about -0.3 dBTP before encoding
        out = self.d / "film-hot.mp4"
        film.assemble(PLAN, t, stills, hot, logo, logo, out, size=(320, 180))
        self.assertLessEqual(mix.measure(out)["true_peak"], -1.0)

    def test_peaky_mix_keeps_loudness_with_a_true_peak_limiter_not_a_gain_cut(self):
        """A quiet bed with a few full-scale clicks (peaky narration) used to force a broadband
        gain cut that cost more than 0.5 LU; the body limiter must trim only the peaks."""
        t, stills, logo = self._assemble_inputs()
        dur = t[-1]["end"]
        peaky = self.d / "peaky.wav"
        click = "if(lt(mod(t,0.5),0.0005),0.95,0)"
        m.ff("-f", "lavfi", "-i", f"aevalsrc='0.16*sin(2*PI*220*t)+{click}|0.16*sin(2*PI*220*t)+{click}'"
             f":s=48000:d={dur}", str(peaky))
        before = mix.measure(peaky)
        self.assertGreater(before["true_peak"], film.TP_MAX)
        out = self.d / "film-peaky.mp4"
        info = film.assemble(PLAN, t, stills, peaky, logo, logo, out, size=(320, 180))
        after = mix.measure(out)
        self.assertLessEqual(after["true_peak"], film.TP_MAX)
        self.assertAlmostEqual(after["lufs"], before["lufs"], delta=0.5)
        self.assertEqual(info["body_gain_db"], 0)
        self.assertFalse(info["body_gain_fallback"])
        self.assertLess(info["body_ceiling_db"], 0)

    def test_logo_lockup_matches_the_approved_landscape_placement(self):
        """earnalism-video EDITORIAL_PRESENTATION: landscape lockup at x1510/y48, about 362 px
        of the 2400x720 lockup on 1920x1080 (the first film used 9 %, 173 px: barely legible)."""
        self.assertAlmostEqual(film.LOGO_WIDTH_FRAC * 1920, 362, delta=10)
        self.assertAlmostEqual(film.LOGO_MARGIN_FRAC * 1920, 48, delta=2)

    def test_scene_is_lightened_softly_behind_the_logo(self):
        """Owner 2026-11-24: lighten the area behind the logo. earnalism-video forbids a solid,
        feathered or translucent rectangular backing, so the scene gets a soft oval glow that
        fades to nothing: bright at the lockup, untouched away from it, no hard edge."""
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        stills = self.d / "dark"
        stills.mkdir()
        for name in ("s1", "s2"):
            Image.new("RGB", (640, 360), (10, 10, 12)).save(stills / f"{name}.png")
        clear = self.d / "clear.png"
        Image.new("RGBA", (240, 72), (0, 0, 0, 0)).save(clear)  # invisible lockup: only the glow shows
        out = self.d / "glow.mp4"
        W, H = 640, 360
        film.assemble(PLAN, t, stills, self.d / "n.wav", clear, clear, out, size=(W, H))
        frame = self.d / "glow.png"
        m.ff("-ss", "1", "-i", str(out), "-frames:v", "1", str(frame))
        img = Image.open(frame).convert("L")
        lw = int(W * film.LOGO_WIDTH_FRAC)
        mg = int(W * film.LOGO_MARGIN_FRAC)
        cx, cy = W - mg - lw // 2, mg + int(lw * 0.3) // 2
        self.assertGreater(img.getpixel((cx, cy)), 70)                # lightened behind the logo
        self.assertLess(img.getpixel((20, H - 20)), 25)               # far corner untouched
        row = [img.getpixel((x, cy)) for x in range(cx - lw, cx + 1)]
        self.assertLess(max(abs(a - b) for a, b in zip(row, row[1:])), 12)  # no hard edge

    def _assemble_inputs(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        stills = self.d / "stills"
        stills.mkdir(exist_ok=True)
        for name in ("s1", "s2"):
            Image.new("RGB", (64, 36), "red").save(stills / f"{name}.png")
        logo = self.d / "logo.png"
        Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(logo)
        return t, stills, logo

    def _call(self, plan, timing, **kw):
        _, stills, logo = self._assemble_inputs()
        return film.assemble(plan, timing, stills, self.d / "n.wav", logo, logo,
                             self.d / "f.mp4", size=(320, 180), **kw)

    def test_assemble_omitted_unit_refuses(self):
        t, _, _ = self._assemble_inputs()
        with self.assertRaises(ValueError):
            self._call(PLAN, t[:-1])
        with self.assertRaises(ValueError):
            self._call(PLAN, [t[0], t[2]])

    def test_assemble_duplicate_timing_key_refuses(self):
        t, _, _ = self._assemble_inputs()
        with self.assertRaises(ValueError):
            self._call(PLAN, t + [dict(t[0])])

    def test_assemble_series_plan_needs_film_selection(self):
        t, _, _ = self._assemble_inputs()
        series = {"series": "x", "films": PLAN["films"] + PLAN["films"]}
        with self.assertRaises(ValueError):
            self._call(series, t)
        info = self._call(series, t, film=0)
        self.assertEqual(info["scenes"], 2)
        with self.assertRaises(ValueError):
            self._call(series, t, film=5)

    def test_grouped_storyteller_units_time_and_subtitle(self):
        """Grouped units keep stable keys; timing, subtitles and the plan check follow them."""
        from eav.voice import EXPRESSIVE, voice_units
        units = [u for sc in PLAN["films"][0]["scenes"]
                 for u in voice_units(sc, {"description": "d"}, None, "en", EXPRESSIVE)]
        self.assertEqual([u["unit_key"] for u in units], ["s1-001", "s2-001"])
        self.assertEqual(units[0]["text"], "One. Two.")
        t = film.narration_track(units, self.wavs, self.d / "n.wav")
        self.assertEqual(len(film.subtitles(t, units).strip().split("\n\n")), 2)
        film._check_timing(PLAN["films"][0]["scenes"], t, "en", EXPRESSIVE)
        with self.assertRaises(ValueError):  # the default style expects s1-002 too
            film._check_timing(PLAN["films"][0]["scenes"], t, "en")
        stills = self.d / "stills"
        stills.mkdir()
        for name in ("s1", "s2"):
            Image.new("RGB", (320, 180), "red").save(stills / f"{name}.png")
        logo, card = self.d / "logo.png", self.d / "card.png"
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(logo)
        Image.new("RGB", (320, 180), "black").save(card)
        info = film.assemble(PLAN, t, stills, self.d / "n.wav", logo, card, self.d / "f.mp4",
                             size=(320, 180), style=EXPRESSIVE)
        self.assertEqual(info["scenes"], 2)

    def test_assemble_missing_still_refuses(self):
        t = film.narration_track(UNITS, self.wavs, self.d / "n.wav")
        (self.d / "stills").mkdir()
        with self.assertRaises(ValueError):
            film.assemble(PLAN, t, self.d / "stills", self.d / "n.wav",
                          self.d / "l.png", self.d / "c.png", self.d / "f.mp4")


BN_LONG = ("যৌবনের শেষে শুভ্র শরৎকালের ন্যায় একটি গভীর প্রশান্ত প্রগাঢ় সুন্দর বয়স আসে যখন জীবনের ফল ফলিবার এবং শস্য "
           "পাকিবার সময়। তখন আর উদ্দাম যৌবনের বসন্তচঞ্চলতা শোভা পায় না। আমাদের আয়ত্তের অতীত কুহকিনী দুরাশার "
           "কল্পনালোক হইতে সমস্ত উদ্‌ভ্রান্ত বাসনাকে প্রত্যাহরণ করিয়া আপন ক্ষুদ্র ক্ষমতার গৃহপ্রাচীরমধ্যে "
           "প্রতিষ্ঠিত করিয়াছি; তখন যৌবন-লাবণ্য অল্পে অল্পে বিশীর্ণ হইয়া আসিতে থাকে।")
BN_SHORT = "প্রথম পরিচ্ছেদ।"
BN_CAP_UNITS = [{"unit_key": "c-001", "text": BN_SHORT}, {"unit_key": "c-002", "text": BN_LONG},
                {"unit_key": "c-003", "text": "অনেক অবস্থান্তরের পর অবশেষে ক্ষীরোদা আশ্রয় পাইল।"}]
BN_CAP_TIMING = [{"unit_key": "c-001", "start": 0.0, "end": 2.2},
                 {"unit_key": "c-002", "start": 2.6, "end": 2.6 + len(BN_LONG) / 11.0},
                 {"unit_key": "c-003", "start": 2.6 + len(BN_LONG) / 11.0 + 0.6,
                  "end": 2.6 + len(BN_LONG) / 11.0 + 0.6 + 5.0}]
MARKS = ("M",)


def vtt_cues(text):
    """[(start_s, end_s, [lines])] from a WebVTT string."""
    import re
    assert text.startswith("WEBVTT\n\n")
    out = []
    for block in text.split("\n\n")[1:]:
        if not block.strip():
            continue
        lines = block.strip("\n").split("\n")
        if lines[0].isdigit():          # a cue identifier (srt_to_vtt keeps the SRT index)
            lines = lines[1:]
        mt = re.fullmatch(r"(\d\d):(\d\d):(\d\d)\.(\d{3}) --> (\d\d):(\d\d):(\d\d)\.(\d{3})", lines[0])
        assert mt, lines[0]
        g = list(map(int, mt.groups()))
        out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
                    lines[1:]))
    return out


def lavfi_clip(path, seconds, size="320x180", color="0", fps=24):
    m.ff("-f", "lavfi", "-i", f"testsrc2=s={size}:r={fps}:d={seconds}", "-vf", f"hue=h={int(color) * 90}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), str(path))


def frame_count(path):
    return int(subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=nb_read_frames", "-of", "csv=p=0", str(path)], check=True, capture_output=True,
        text=True).stdout.strip())


class ShotFilmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # ---------------------------------------------------------------- assemble_shots
    def _clips(self, n=3, seconds=1):
        out = []
        for i in range(n):
            p = self.d / f"c{i}.mp4"
            lavfi_clip(p, seconds, color=str(i))
            out.append(p)
        return out

    def test_assemble_shots_frame_exact_lengths(self):
        clips = self._clips()
        audio = self.d / "a.wav"
        m.sine_wav(audio, 3.0)
        out = self.d / "f.mp4"
        info = film.assemble_shots(clips, [1.0, 1.0, 1.0], [0.5, 0.0], audio, out)
        # 72 frames, minus a 12-frame dissolve and a 1-frame (hard cut) xfade
        self.assertEqual(info["frames"], 72 - 12 - 1)
        self.assertEqual(frame_count(out), 59)
        self.assertEqual(probe(out, "v:0", "r_frame_rate"), "24/1")
        self.assertAlmostEqual(float(probe(out, "a:0", "duration")), 59 / 24, delta=0.06)

    def test_assemble_shots_refuses_inconsistent_inputs(self):
        clips, audio = self._clips(), self.d / "a.wav"
        m.sine_wav(audio, 3.0)
        with self.assertRaises(ValueError):   # one transition too few
            film.assemble_shots(clips, [1.0, 1.0, 1.0], [0.5], audio, self.d / "f.mp4")
        with self.assertRaises(ValueError):   # a dissolve longer than the shot it eats
            film.assemble_shots(clips, [1.0, 1.0, 1.0], [0.9, 0.9], audio, self.d / "f.mp4")
        with self.assertRaises(ValueError):   # a clip with fewer frames than its length
            film.assemble_shots(clips, [2.0, 1.0, 1.0], [0.5, 0.0], audio, self.d / "f.mp4")

    def test_edit_lengths_put_every_cut_on_its_frame(self):
        lens, trans = film.edit_lengths([2.0, 1.5, 3.0], [0.8, 0.0], 24)
        frames = [round(x * 24) for x in lens]
        ov = [max(1, round(x * 24)) for x in trans]
        self.assertEqual(sum(frames) - sum(ov), round(6.5 * 24))   # the film is as long as the narration
        self.assertEqual(ov[1], 1)                                  # a hard cut is a 1-frame xfade
        # the centre of the dissolve is the planned boundary (frame 48)
        first_out = frames[0] - ov[0]

        self.assertAlmostEqual((first_out + ov[0] / 2) / 24, 2.0, delta=1 / 24)

    def test_assemble_shots_cards_logo_end_and_caption_track(self):
        clips, audio = self._clips(2), self.d / "a.wav"
        m.sine_wav(audio, 2.0)
        logo, endc = self.d / "logo.png", self.d / "end.png"
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(logo)
        Image.new("RGB", (320, 180), "black").save(endc)
        title, credits = self.d / "t.png", self.d / "cr.png"
        Image.new("RGB", (640, 360), "navy").save(title)
        Image.new("RGB", (640, 360), "green").save(credits)
        vtt = self.d / "c.vtt"
        vtt.write_text("WEBVTT\n\n00:00:02.000 --> 00:00:03.500\nhello\n\n", encoding="utf-8")
        out = self.d / "f.mp4"
        info = film.assemble_shots(clips, [1.0, 1.0], [0.0], audio, out, logo=logo, end_card=endc,
                                   title_card=title, credits_card=credits, title_s=1.0, credits_s=1.0,
                                   captions_vtt=vtt)
        self.assertEqual(info["frames"], 47)
        self.assertAlmostEqual(info["duration"], 1.0 + 47 / 24 + 1.0 + 3.0, delta=0.05)
        self.assertEqual((probe(out, "v:0", "width"), probe(out, "v:0", "height")), (320, 180))
        self.assertAlmostEqual(float(probe(out, "v:0", "duration")), info["duration"], delta=0.1)
        self.assertEqual(probe(out, "s:0", "codec_name"), "mov_text")

    def test_card_fades_advance_every_frame_through_the_hitch_detector(self):
        """I1/F12: the skill's own title and credits cards (the dark Maison canvas) fade evenly in and out, so qc's
        hitch gate passes on them; before, the 8-bit fade (and qc's fast-path scaler) stepped every other frame."""
        from eav import qc
        card = film.cards("বিচারক", "রবীন্দ্রনাথ ঠাকুর", "Subhajit", self.d / "cards")
        clips, audio = self._clips(1, 3), self.d / "a.wav"
        m.sine_wav(audio, 3.0)
        out = self.d / "cards.mp4"
        film.assemble_shots(clips, [3.0], [], audio, out, title_card=Path(card["cards"]["title"]),
                            credits_card=Path(card["cards"]["credits"]), title_s=4.0, credits_s=5.0, fade_out_s=1.0)
        self.assertEqual(qc.frame_hitches(out), [])
        import numpy as np
        luma, _ = qc._luma_series(out)
        ramp = np.diff(luma[:12])                        # the title fade-in: every frame moves up
        self.assertTrue((ramp > 0.3).all(), ramp)

    def test_assemble_shots_fades_out_at_the_end_of_the_picture(self):
        clips, audio = self._clips(2, 2), self.d / "a.wav"
        m.sine_wav(audio, 4.0, amp=0.5)
        out = self.d / "f.mp4"
        film.assemble_shots(clips, [2.0, 2.0], [0.0], audio, out, fade_out_s=1.0)
        last, mid = self.d / "last.wav", self.d / "mid.wav"
        m.ff("-ss", "3.8", "-t", "0.2", "-i", str(out), "-ac", "1", str(last))
        m.ff("-ss", "1.0", "-t", "0.2", "-i", str(out), "-ac", "1", str(mid))
        self.assertLess(m.rms_db(m.samples(last)), m.rms_db(m.samples(mid)) - 15)
        self.assertGreater(m.rms_db(m.samples(last)), -90)   # a fade, never digital silence at the join

    def test_no_digital_silence_under_cards_and_end(self):
        """The title stretch, the credits stretch and a silent END carry room tone, never exact zero samples."""
        import numpy as np
        clips, audio = self._clips(2), self.d / "a.wav"
        m.sine_wav(audio, 2.0)
        endc, title, credits = self.d / "end.png", self.d / "t.png", self.d / "cr.png"
        for p_, c in ((endc, "black"), (title, "navy"), (credits, "green")):
            Image.new("RGB", (320, 180), c).save(p_)
        out = self.d / "f.mp4"
        info = film.assemble_shots(clips, [1.0, 1.0], [0.0], audio, out, end_card=endc, title_card=title,
                                   credits_card=credits, title_s=1.0, credits_s=1.0, fade_out_s=0.5)
        x = m.samples(out)
        self.assertAlmostEqual(len(x) / 48000, info["duration"], delta=0.1)
        zero = np.concatenate(([0], (x == 0).astype(np.int8), [0]))
        edges = np.flatnonzero(np.diff(zero))
        longest = max(((b - a) for a, b in zip(edges[::2], edges[1::2])), default=0)
        self.assertLess(longest / 48000, 0.05)
        self.assertLess(m.rms_db(x[:int(0.8 * 48000)]), -55)     # quiet, not silent: -62...-68 dBFS tone
        self.assertGreater(m.rms_db(x[:int(0.8 * 48000)]), -80)

    def test_burned_captions_change_the_picture_not_the_length(self):
        clips, audio = self._clips(1, 2), self.d / "a.wav"
        m.sine_wav(audio, 2.0)
        vtt = self.d / "c.vtt"
        vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n" + BN_SHORT + "\n\n", encoding="utf-8")
        plain, burned = self.d / "p.mp4", self.d / "b.mp4"
        film.assemble_shots(clips, [2.0], [], audio, plain, fade_out_s=0)
        film.assemble_shots(clips, [2.0], [], audio, burned, captions_vtt=vtt, burn=True, fade_out_s=0)
        self.assertEqual(frame_count(plain), frame_count(burned))
        with self.assertRaises(Exception):
            probe(burned, "s:0", "codec_name")   # burned-in: no soft track
        a, b = self.d / "a.png", self.d / "b.png"
        m.ff("-i", str(plain), "-vf", "select=eq(n\\,10)", "-frames:v", "1", str(a))
        m.ff("-i", str(burned), "-vf", "select=eq(n\\,10)", "-frames:v", "1", str(b))
        import numpy as np
        self.assertGreater(float(np.abs(np.asarray(Image.open(a)).astype(int)
                                        - np.asarray(Image.open(b)).astype(int)).mean()), 0.05)

    # ---------------------------------------------------------------- captions
    def _cues(self, **kw):
        timing = kw.pop("timing", BN_CAP_TIMING)
        units = kw.pop("units", BN_CAP_UNITS)
        return vtt_cues(film.captions(timing, units, "bn", **kw))

    def test_caption_cue_limits(self):
        cues = self._cues()
        self.assertGreaterEqual(len(cues), 4)
        prev_end = 0.0
        for s, e, lines in cues:
            self.assertLessEqual(len(lines), 2)
            for ln in lines:
                self.assertLessEqual(len(ln), 42, ln)
            self.assertGreaterEqual(e - s, 1.0 - 1e-9)
            self.assertLessEqual(e - s, 7.0 + 1e-9)
            self.assertLessEqual(film._visible_len(" ".join(lines)) / (e - s), 15.0 + 1e-9, lines)
            self.assertGreaterEqual(s, prev_end - 1e-9)   # never overlapping
            prev_end = e

    def test_caption_cues_reproduce_the_source_text_exactly(self):
        cues = self._cues()
        got = "".join("".join(lines) for _, _, lines in cues)
        want = "".join(u["text"] for u in BN_CAP_UNITS)
        strip = lambda s: "".join(s.split())
        self.assertEqual(strip(got), strip(want))   # only whitespace at the splits differs; ZWNJ kept
        self.assertIn("‌", got)

    def test_caption_wrap_keeps_bengali_graphemes(self):
        import unicodedata
        for _, _, lines in self._cues():
            for ln in lines:
                self.assertNotEqual(ln[-1], "্", ln)                       # never ends with a hasanta
                self.assertNotIn(ln[-1], "‌‍")
                self.assertFalse(unicodedata.category(ln[0]).startswith("M"), ln)   # no dependent vowel sign first
                self.assertNotIn(ln[0], "‌‍")

    def test_caption_split_only_at_spaces_or_punctuation(self):
        text = BN_LONG
        # a hard-to-wrap run: one unbreakable 50-character word is refused, never cut inside a cluster
        word = "ক্ষ" * 25
        with self.assertRaises(ValueError):
            film.captions([{"unit_key": "u", "start": 0, "end": 9}], [{"unit_key": "u", "text": word}], "bn")
        self.assertIn(text.split()[0], film.captions(BN_CAP_TIMING, BN_CAP_UNITS, "bn"))
        # a hyphenated compound may split after its hyphen, and nowhere else inside the word
        comp = "যৌবন-লাবণ্য" * 4
        lines = vtt_cues(film.captions([{"unit_key": "u", "start": 0, "end": 6.5}],
                                       [{"unit_key": "u", "text": comp}], "bn"))
        self.assertEqual("".join("".join(c[2]) for c in lines), comp)

    def test_caption_too_fast_narration_is_refused_not_squeezed(self):
        fast = [{"unit_key": "c-001", "start": 0.0, "end": 1.0}, {"unit_key": "c-002", "start": 1.5, "end": 4.0}]
        units = [{"unit_key": "c-001", "text": BN_LONG[:120]}, {"unit_key": "c-002", "text": "পরে।"}]
        with self.assertRaises(ValueError):
            film.captions(fast, units, "bn")

    def test_caption_short_unit_is_held_to_one_second_in_the_pause(self):
        tm = [{"unit_key": "a", "start": 0.0, "end": 0.4}, {"unit_key": "b", "start": 2.0, "end": 4.0}]
        un = [{"unit_key": "a", "text": "Yes."}, {"unit_key": "b", "text": "Then she left."}]
        cues = vtt_cues(film.captions(tm, un, "en"))
        self.assertAlmostEqual(cues[0][1] - cues[0][0], 1.0, places=2)
        self.assertLessEqual(cues[0][1], 2.0)

    def test_caption_offset_shifts_the_film_timeline(self):
        a = vtt_cues(film.captions(BN_CAP_TIMING, BN_CAP_UNITS, "bn"))
        b = vtt_cues(film.captions(BN_CAP_TIMING, BN_CAP_UNITS, "bn", offset=4.0))
        self.assertAlmostEqual(b[0][0] - a[0][0], 4.0, places=3)

    def test_caption_unknown_unit_refuses(self):
        with self.assertRaises(ValueError):
            film.captions([{"unit_key": "zzz", "start": 0, "end": 2}], BN_CAP_UNITS, "bn")

    # ---------------------------------------------------------------- render_shot
    def _image(self, name="still.png"):
        p = self.d / name
        Image.new("RGB", (64, 36), "teal").save(p)
        return p

    def _fake_render(self, calls):
        def render(image, depth, out, seconds, **kw):
            calls.append({"image": image, "depth": depth, "seconds": seconds, **kw})
            m.ff("-f", "lavfi", "-i", "color=c=black:s=64x36:r=24:d=0.5", "-c:v", "libx264", str(out))
            return {"frames": int(round(seconds * kw.get("fps", 24))), "base_overscan": 1.03}
        return render

    def test_render_shot_cache_hit_skips_render(self):
        from unittest import mock
        calls = []
        shot = {"n": 1, "scene_id": "s1", "motion": "glide", "seconds": 2.0,
                "camera": {"move": "push", "zoom": 0.1, "pan_x": 0.0, "ease": "both"}}
        assets = {"image": self._image(), "depth": self._image("depth.png")}
        cache = self.d / "cache"
        with mock.patch("eav.glide.render", side_effect=self._fake_render(calls)):
            first = film.render_shot(shot, assets, cache)
            second = film.render_shot(dict(shot), assets, cache)
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["zoom"], 0.1)
            self.assertEqual(calls[0]["seconds"], 2.0)
            Image.new("RGB", (64, 36), "red").save(assets["image"])      # an input changed: re-render
            third = film.render_shot(shot, assets, cache)
            self.assertNotEqual(third, first)
            self.assertEqual(len(calls), 2)
            film.render_shot({**shot, "seconds": 2.5}, assets, cache)    # the shot changed: re-render
            self.assertEqual(len(calls), 3)

    def test_render_shot_pull_back_must_keep_the_frame_filled(self):
        from unittest import mock
        calls = []
        shot = {"n": 8, "scene_id": "s1", "motion": "glide", "seconds": 2.0,
                "camera": {"move": "pull", "zoom": -0.12, "pan_x": 0.0, "ease": "out", "zoom0": 1.16}}
        assets = {"image": self._image(), "depth": self._image("depth.png")}
        with mock.patch("eav.glide.render", side_effect=self._fake_render(calls)):
            with self.assertRaises(ValueError):    # 1.16 * (1 - 0.12 * 1.2) = 0.993 < 1: an edge band
                film.render_shot(shot, assets, self.d / "cache")
            self.assertEqual(calls, [])
            shot["camera"]["zoom0"] = 1.2
            film.render_shot(shot, assets, self.d / "cache")
            self.assertEqual(calls[0]["zoom0"], 1.2)
            shot["camera"].pop("zoom0")            # no zoom0 at all: 1.0 * 0.856 < 1
            with self.assertRaises(ValueError):
                film.render_shot(shot, assets, self.d / "cache")

    def test_render_shot_static_and_wan_make_exact_frames(self):
        still = self._image()
        static = film.render_shot({"n": 1, "scene_id": "s", "motion": "static", "seconds": 1.5,
                                   "camera": {"move": "none", "zoom": 0.0, "pan_x": 0.0, "ease": "none"}},
                                  {"image": still}, self.d / "cache")
        self.assertEqual(frame_count(static), 36)
        a, b = self.d / "w1.mp4", self.d / "w2.mp4"
        lavfi_clip(a, 1, size="1280x704")
        lavfi_clip(b, 1, size="1280x704")
        wan = film.render_shot({"n": 2, "scene_id": "s", "motion": "wan", "wan_res": "1280x704", "seconds": 1.75,
                                "camera": {"move": "none", "zoom": 0.0, "pan_x": 0.0, "ease": "none"}},
                               {"clips": [a, b]}, self.d / "cache")
        self.assertEqual(frame_count(wan), 42)
        self.assertEqual((probe(wan, "v:0", "width"), probe(wan, "v:0", "height")), (1920, 1080))
        with self.assertRaisesRegex(ValueError, "continuation"):   # I3: a chain shorter than the shot never freezes
            film.render_shot({"n": 3, "scene_id": "s", "motion": "wan", "wan_res": "1280x704", "seconds": 1.5,
                              "camera": {"move": "none", "zoom": 0.0, "pan_x": 0.0, "ease": "none"}},
                             {"clips": [a]}, self.d / "cache")
        with self.assertRaises(ValueError):   # a wan shot with no clip never falls back to a still
            film.render_shot({"n": 2, "scene_id": "s", "motion": "wan", "seconds": 1.0, "camera": {}},
                             {"clips": []}, self.d / "cache")

    # ---------------------------------------------------------------- picking the Wan clip of a shot
    def test_pick_wan_clips_follows_continuations_and_refuses_ambiguity(self):
        items = [{"key": "s1-6", "shot": 6}, {"key": "s1-6x", "shot": 6, "continue_from": "s1-6"},
                 {"key": "s1-9a", "shot": 9}, {"key": "s1-9b", "shot": 9}, {"key": "s2-6", "shot": 6}]
        self.assertEqual(film.pick_wan_clips(items, "s1", 6), ["s1-6", "s1-6x"])
        with self.assertRaises(ValueError):
            film.pick_wan_clips(items, "s1", 9)                       # two takes: someone must choose
        self.assertEqual(film.pick_wan_clips(items, "s1", 9, {"s1/9": "s1-9b"}), ["s1-9b"])
        with self.assertRaises(ValueError):
            film.pick_wan_clips(items, "s1", 9, {"s1/9": "s1-9z"})    # a pick that is not a take
        with self.assertRaises(ValueError):
            film.pick_wan_clips(items, "s3", 1)

    # ---------------------------------------------------------------- cards
    def test_cards_contain_ai_disclosure_text(self):
        meta = film.cards("বিচারক", "রবীন্দ্রনাথ ঠাকুর", "Mitali (ElevenLabs)", self.d / "cards")
        saved = json.loads((self.d / "cards" / "cards.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, meta)
        self.assertEqual(saved["title_line"], "বিচারক — রবীন্দ্রনাথ ঠাকুর")
        self.assertEqual(saved["author"], "রবীন্দ্রনাথ ঠাকুর")
        self.assertEqual(saved["voice"], "Mitali (ElevenLabs)")
        self.assertEqual(saved["disclosure"]["en"], "Illustrations and narration are AI-generated")
        self.assertEqual(saved["disclosure"]["bn"], "ছবি ও কণ্ঠ এআই-নির্মিত")
        self.assertEqual(saved["disclosure"]["text"],
                         "Illustrations and narration are AI-generated / ছবি ও কণ্ঠ এআই-নির্মিত")
        for role in ("latin_display", "latin_text", "bengali_display", "bengali_text"):
            f = saved["fonts"][role]
            self.assertTrue(Path(f["file"]).is_file())
            self.assertEqual(f["sha256"], hashlib.sha256(Path(f["file"]).read_bytes()).hexdigest())
        for name in ("title", "credits"):
            img = Image.open(saved["cards"][name])
            self.assertEqual(img.size, (1920, 1080))
            import numpy as np
            self.assertGreater(len(np.unique(np.asarray(img.convert("L").resize((96, 54))))), 5)  # not blank
        self.assertEqual(saved["engine"], "pillow-raqm")

    def test_cards_shape_bengali_conjuncts(self):
        """With a shaping engine the conjunct ক্ষ is one glyph: the text is narrower than its parts."""
        from PIL import ImageFont
        self.assertTrue(film._shaping_available())
        meta = film.cards("ক্ষ", "রবীন্দ্রনাথ ঠাকুর", "v", self.d / "c2")
        font = ImageFont.truetype(meta["fonts"]["bengali_display"]["file"], 100, layout_engine=ImageFont.Layout.RAQM)
        self.assertLess(font.getlength("ক্ষ"), font.getlength("ক") + font.getlength("্") + font.getlength("ষ") - 1)


class FixRoundOneTests(unittest.TestCase):
    """Review of Task 8: R10 true peak, mix/picture drift, camera fields, SRT, faster-than-15-cps captions."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # ---- 1. true peak -1.5 for shot films, -1.0 kept for the old assemble
    def test_shot_film_true_peak_gate_is_minus_one_and_a_half(self):
        self.assertEqual(film.SHOT_TP_MAX, -1.5)
        self.assertEqual(film.TP_MAX, -1.0)
        clips = []
        for i in range(2):
            p = self.d / f"c{i}.mp4"
            lavfi_clip(p, 2)
            clips.append(p)
        peaky = self.d / "peaky.wav"
        click = "if(lt(mod(t,0.5),0.0005),0.95,0)"
        m.ff("-f", "lavfi", "-i", f"aevalsrc='0.16*sin(2*PI*220*t)+{click}|0.16*sin(2*PI*220*t)+{click}'"
             ":s=48000:d=4", str(peaky))
        out = self.d / "f.mp4"
        info = film.assemble_shots(clips, [2.0, 2.0], [0.0], peaky, out, fade_out_s=0)
        self.assertLessEqual(mix.measure(out)["true_peak"], -1.5)
        self.assertFalse(info["body_gain_fallback"])

    # ---- 2. scene mixes are held to their frame-aligned scene length
    def test_scene_frames_use_the_same_cumulative_rounding_as_the_picture(self):
        self.assertEqual(film.scene_frames([11.51, 11.51, 11.51], 24), [276, 276, 277])
        self.assertEqual(sum(film.scene_frames([11.51, 11.51, 11.51], 24)), round(34.53 * 24))

    def test_join_scene_mixes_keeps_audio_within_a_frame_of_picture(self):
        secs = [2.0, 2.3, 1.7, 2.1, 2.0]
        mixes = []
        for i, sec in enumerate(secs):
            p = self.d / f"s{i}.wav"
            m.sine_wav(p, sec - 0.1)            # each mix 0.1 s short of its scene
            mixes.append(p)
        frames = film.scene_frames(secs, 24)
        out = self.d / "film.wav"
        film.join_scene_mixes(mixes, frames, out, 24)
        got = m.samples(out).size / 48000
        self.assertAlmostEqual(got, sum(frames) / 24, delta=1 / 24)
        # a long mix is cut, too
        m.sine_wav(mixes[0], secs[0] + 0.14)
        film.join_scene_mixes(mixes, frames, out, 24)
        self.assertAlmostEqual(m.samples(out).size / 48000, sum(frames) / 24, delta=1 / 24)

    def test_shots_must_tile_the_scene(self):
        good = [{"n": 1, "start": 0.0, "end": 5.0}, {"n": 2, "start": 5.0, "end": 9.0}]
        film.check_shot_coverage("s", good, 9.0)
        for bad in ([{"n": 1, "start": 0.2, "end": 9.0}],                                   # starts late
                    [{"n": 1, "start": 0.0, "end": 5.0}, {"n": 2, "start": 5.5, "end": 9.0}],  # gap
                    [{"n": 1, "start": 0.0, "end": 5.5}, {"n": 2, "start": 5.0, "end": 9.0}],  # overlap
                    [{"n": 1, "start": 0.0, "end": 8.0}]):                                 # ends early
            with self.assertRaises(ValueError):
                film.check_shot_coverage("s", bad, 9.0)

    # ---- 3. camera fields reach render_shot; flat glide needs no depth
    def test_flat_glide_renders_without_a_depth_map(self):
        from unittest import mock
        img = self.d / "still.png"
        Image.new("RGB", (64, 36), "teal").save(img)
        calls = []

        def render(image, depth, out, seconds, **kw):
            calls.append((depth, kw))
            m.ff("-f", "lavfi", "-i", "color=c=black:s=64x36:r=24:d=0.5", "-c:v", "libx264", str(out))
            return {"frames": int(round(seconds * 24)), "base_overscan": 1.03}
        shot = {"n": 1, "scene_id": "s", "motion": "glide", "seconds": 1.0,
                "camera": {"move": "push", "zoom": 0.15, "pan_x": 0, "ease": "out", "flat": True}}
        with mock.patch("eav.glide.render", side_effect=render):
            film.render_shot(shot, {"image": img}, self.d / "cache")
        self.assertIsNone(calls[0][0])
        self.assertTrue(calls[0][1]["flat"])

    def test_flat_glide_really_renders(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV not installed")
        img = self.d / "still.png"
        Image.new("RGB", (192, 108), "teal").save(img)
        shot = {"n": 1, "scene_id": "s", "motion": "glide", "seconds": 0.25,
                "camera": {"move": "push", "zoom": 0.1, "pan_x": 0, "ease": "both", "flat": True}}
        out = film.render_shot(shot, {"image": img}, self.d / "cache")
        self.assertEqual(frame_count(out), 6)

    def test_shot_assets_for_a_flat_glide_need_no_depth_map(self):
        from types import SimpleNamespace
        from eav import cli
        stills = self.d / "stills"
        stills.mkdir()
        Image.new("RGB", (64, 36), "teal").save(stills / "s1-1.png")
        shot = {"n": 1, "motion": "glide", "camera": {"flat": True}}
        got = cli._shot_assets(SimpleNamespace(root=self.d), "film-01", "s1", shot, {}, {}, stills)
        self.assertEqual(set(got), {"image"})
        with self.assertRaises(cli.Stop):   # not flat: a depth map is required
            cli._shot_assets(SimpleNamespace(root=self.d), "film-01", "s1",
                             {"n": 1, "motion": "glide", "camera": {}}, {}, {}, stills)

    # ---- 4. SRT
    def test_captions_srt_matches_the_webvtt_cues(self):
        v = vtt_cues(film.captions(BN_CAP_TIMING, BN_CAP_UNITS, "bn", offset=4.0))
        srt = film.captions(BN_CAP_TIMING, BN_CAP_UNITS, "bn", offset=4.0, fmt="srt")
        self.assertTrue(srt.startswith("1\n00:00:04,000 --> "))
        from eav import film_bundle
        back = vtt_cues(film_bundle.srt_to_vtt(srt))
        self.assertEqual(back, v)
        with self.assertRaises(ValueError):
            film.captions(BN_CAP_TIMING, BN_CAP_UNITS, "bn", fmt="ass")

    # ---- 5. faster than 15 cps: extend, merge, refuse
    FAST = "আমি এখনই সেই পুরাতন ঘরে ফিরিয়া যাইব।"   # 32 visible characters

    def _caps(self, timing, units, **kw):
        return vtt_cues(film.captions(timing, units, "bn", **kw))

    def test_too_fast_unit_next_to_silence_is_extended_within_the_allowance(self):
        tm = [{"unit_key": "a", "start": 5.0, "end": 6.5}, {"unit_key": "b", "start": 12.0, "end": 14.0}]
        un = [{"unit_key": "a", "text": self.FAST}, {"unit_key": "b", "text": "পরে।"}]
        cues = self._caps(tm, un)
        s, e, _ = cues[0]
        self.assertGreaterEqual(s, 5.0 - 0.3 - 1e-9)
        self.assertLessEqual(e, 6.5 + 1.0 + 1e-9)
        self.assertLessEqual(film._visible_len(self.FAST) / (e - s), 15.0 + 1e-9)
        self.assertTrue(s < 5.0 or e > 6.5)     # it really used the allowance

    def test_unit_between_tight_neighbours_merges_with_a_neighbour(self):
        tm = [{"unit_key": "a", "start": 0.0, "end": 2.5}, {"unit_key": "b", "start": 2.5, "end": 4.0},
              {"unit_key": "c", "start": 4.0, "end": 8.0}]
        un = [{"unit_key": "a", "text": "ভোর হইল।"}, {"unit_key": "b", "text": self.FAST},
              {"unit_key": "c", "text": "সে চলিয়া গেল।"}]
        cues = self._caps(tm, un)
        joined = ["".join("".join(c[2]) for c in cues)][0]
        self.assertEqual("".join(joined.split()), "".join("".join(u["text"] for u in un).split()))
        prev = 0.0
        for s, e, lines in cues:
            self.assertGreaterEqual(s, prev - 1e-9)
            self.assertLessEqual(len(lines), 2)
            self.assertTrue(all(len(ln) <= 42 for ln in lines))
            self.assertTrue(1.0 - 1e-9 <= e - s <= 7.0 + 1e-9)
            self.assertLessEqual(film._visible_len(" ".join(lines)) / (e - s), 15.0 + 1e-9)
            prev = e
        self.assertLess(len(cues), 3)           # a merge happened

    def test_a_merge_never_crosses_a_chapter_heading(self):
        tm = [{"unit_key": "a", "start": 0.0, "end": 3.0}, {"unit_key": "b", "start": 3.1, "end": 4.2},
              {"unit_key": "h", "start": 4.2, "end": 6.2}]
        un = [{"unit_key": "a", "text": "ভোর হইল।"}, {"unit_key": "b", "text": self.FAST},
              {"unit_key": "h", "text": "দ্বিতীয় পরিচ্ছেদ।"}]
        cues = self._caps(tm, un)
        self.assertEqual(cues[-1][2], ["দ্বিতীয় পরিচ্ছেদ।"])          # the heading keeps its own cue
        self.assertEqual(len(cues), 2)                                  # b merged with the previous unit a
        self.assertIn("ভোর হইল।", " ".join(cues[0][2]))
        self.assertIn("আমি এখনই", " ".join(cues[0][2]))

    def test_hold_grows_to_one_and_a_half_seconds_before_a_heading(self):
        tm = [{"unit_key": "a", "start": 0.0, "end": 0.5}, {"unit_key": "h", "start": 9.0, "end": 11.0}]
        un = [{"unit_key": "a", "text": self.FAST}, {"unit_key": "h", "text": "দ্বিতীয় পরিচ্ছেদ।"}]
        cues = self._caps(tm, un)
        self.assertGreater(cues[0][1], 0.5 + 1.0 + 1e-6)    # 27 chars need 1.8 s: 0.5 + 1.5 is allowed
        self.assertLessEqual(cues[0][1], 0.5 + 1.5 + 1e-9)

    def test_impossible_caption_is_still_refused(self):
        tm = [{"unit_key": "a", "start": 0.0, "end": 1.0}, {"unit_key": "b", "start": 1.0, "end": 2.0}]
        un = [{"unit_key": "a", "text": BN_LONG[:110]}, {"unit_key": "b", "text": BN_LONG[110:230]}]
        with self.assertRaises(ValueError):
            self._caps(tm, un)

    def test_extension_never_overlaps_the_neighbour_cues(self):
        tm = [{"unit_key": "a", "start": 0.0, "end": 1.5}, {"unit_key": "b", "start": 2.0, "end": 3.6},
              {"unit_key": "c", "start": 3.9, "end": 7.9}]
        un = [{"unit_key": "a", "text": self.FAST}, {"unit_key": "b", "text": self.FAST},
              {"unit_key": "c", "text": "সে চলিয়া গেল।"}]
        prev = -1.0
        for s, e, _ in self._caps(tm, un):
            self.assertGreaterEqual(s, prev - 1e-9)
            prev = e


if __name__ == "__main__":
    unittest.main()
