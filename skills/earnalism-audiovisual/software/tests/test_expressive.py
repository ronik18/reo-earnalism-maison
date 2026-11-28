"""Expressive narration layer (owner request 28 Nov 2026): a cast.json with `tone` gets composed,
emotion-aware Parler descriptions, punctuation- and structure-aware pauses with jitter, data-driven
segment gaps and room tone instead of digital silence; casts without `tone` and titles without a
cast are unchanged (tests/test_cast.py checks those byte for byte)."""
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

from eav import cast, cli, colab_jobs, expressive, film, mix, narration_join, qc
from eav.budget import Ledger
from eav.record import Record
from eav.voice import voice_units, unit_boundaries
from tests._narration_fakes import FakeModel, fake_modules
from tests.test_cast import SOURCE, TITLE, chosen_voices
from tests.test_cli import RATES, run

TABLE = expressive.load()
QUALITY = TABLE["quality_clause"]
TONE = {"pace": "slow", "expressivity": "slightly expressive", "atmosphere": "hushed and tender",
        "rationale": "a quiet domestic story"}


def rms_dbfs(a) -> float:
    a = np.asarray(a, dtype=np.float64)
    return 20 * np.log10(np.sqrt(np.mean(a ** 2)))


class DescriptionTests(unittest.TestCase):
    def test_every_role_and_emotion_keeps_the_quality_clause_and_the_speaker(self):
        speakers = list(cast.SPEAKERS["male"]) + list(cast.SPEAKERS["female"])
        combos = [("narrator", m) for m in (None, expressive.CALM) + expressive.NARRATION_MOODS]
        combos += [("character", e) for e in (None,) + expressive.SPEECH_EMOTIONS]
        seen = {}
        for tone in (TONE, {**TONE, "pace": "moderate", "expressivity": "expressive"}):
            for speaker in speakers:
                for role, emo in combos:
                    with self.subTest(speaker=speaker, role=role, emotion=emo):
                        d = expressive.describe(TABLE, speaker, tone, role, emo)
                        self.assertTrue(d.startswith(speaker + " "))
                        self.assertTrue(d.endswith(QUALITY))
                        for clause in ("very clear audio", "very close up", "no background noise"):
                            self.assertIn(clause, d)
                        self.assertIn("fluent, natural standard Bengali", d)
                        entry = (TABLE["narration_moods"][emo or "calm"] if role == "narrator"
                                 else TABLE["speech_emotions"][emo or "conversation"])
                        self.assertIn(entry["phrase"], d)
                        self.assertIn(f"at a {entry.get('pace') or tone['pace']} pace", d)
                        self.assertIn(f"{entry.get('expressivity') or tone['expressivity']} "
                                      "intonation", d)
                        if role == "narrator":
                            self.assertIn(f"narrates a {tone['atmosphere']} story", d)
                        else:
                            self.assertIn("conversational tone", d)
                        others = [s for s in speakers if s != speaker]
                        self.assertFalse(any(o in d for o in others))
                        self.assertNotIn("{", d)
                        self.assertEqual(d, expressive.describe(TABLE, speaker, tone, role, emo))
                        seen.setdefault(tone["pace"], set()).add(d)
        # moods and emotions really change the description (per speaker and tone)
        for per_tone in seen.values():
            self.assertEqual(len(per_tone), len(speakers) * (1 + len(expressive.NARRATION_MOODS)
                                                             + len(expressive.SPEECH_EMOTIONS)))

    def test_table_is_complete_and_in_the_mirror(self):
        self.assertEqual(set(TABLE["narration_moods"]), {"calm", *expressive.NARRATION_MOODS})
        self.assertEqual(set(TABLE["speech_emotions"]), set(expressive.SPEECH_EMOTIONS))
        approved = cast.load_voices()["description_template"]
        self.assertIn(QUALITY, approved)  # the approved wording's quality clause, unchanged
        mirror = Path(__file__).resolve().parents[4] / ".agents" / "skills" / \
            "earnalism-audiovisual" / "references" / "expressive.json"
        self.assertEqual(mirror.read_bytes(), expressive.TABLE.read_bytes())
        with self.assertRaises(ValueError):
            expressive.describe(TABLE, "Arnav", TONE, "crowd")

    def test_tone_errors(self):
        self.assertEqual(expressive.tone_errors(TONE), [])
        for bad in ({**TONE, "pace": "fast"}, {**TONE, "expressivity": "very"},
                    {**TONE, "atmosphere": "eerie"}, {**TONE, "atmosphere": "a b c d e f g"},
                    {**TONE, "atmosphere": "ভয় আর বিষাদ"}, {**TONE, "rationale": " "},
                    {**TONE, "extra": 1}, "slow"):
            self.assertTrue(expressive.tone_errors(bad), bad)


class PauseTests(unittest.TestCase):
    P = TABLE["pauses"]

    def rule(self, text, boundary="sentence", scene_end=False, change=False, key="s01-001"):
        return expressive.pause_rule(text, boundary, scene_end, change, key, self.P)

    def test_sentence_ends_by_punctuation(self):
        cases = [("সে চলিয়া গেল।", "sentence", 450), ("It ended.", "sentence", 450),
                 ("তুমি কে?", "question_exclaim", 550), ("“ডাক্তার!”", "question_exclaim", 550),
                 ("সে বলিল—", "trailing", 650), ("তারপর…", "trailing", 650),
                 ("And then...", "trailing", 650), ("“আর—”", "trailing", 650),
                 ("no mark", "sentence", 450)]
        for text, rule, base in cases:
            with self.subTest(text=text):
                r = self.rule(text)
                self.assertEqual((r["rule"], r["base_ms"]), (rule, base))
                self.assertLessEqual(abs(r["ms"] - base), base * 0.08 + 1)

    def test_structure_precedence_dialogue_and_jitter(self):
        self.assertEqual(self.rule("এক ভাগ,", "clause")["base_ms"], 150)
        self.assertEqual(self.rule("শেষ?", "paragraph")["rule"], "paragraph")
        self.assertEqual(self.rule("শেষ।", "paragraph")["base_ms"], 900)
        self.assertEqual(self.rule("এক", "heading")["base_ms"], 1400)
        self.assertEqual(self.rule("শেষ।", "paragraph", scene_end=True)["rule"], "scene")
        self.assertEqual(self.rule("এক", "heading", scene_end=True)["rule"], "heading")
        r = self.rule("শেষ।", change=True)
        self.assertEqual((r["rule"], r["dialogue_ms"]), ("sentence+dialogue", 150))
        js = [self.rule("শেষ।", key=f"s01-{i:03d}")["jitter"] for i in range(1, 200)]
        self.assertTrue(all(-0.08 <= j <= 0.08 for j in js))
        self.assertGreater(len(set(js)), 150)  # varied ...
        self.assertEqual(js, [self.rule("শেষ।", key=f"s01-{i:03d}")["jitter"]
                              for i in range(1, 200)])  # ... and deterministic
        self.assertTrue(min(js) < -0.05 and max(js) > 0.05)

    def test_segment_gaps(self):
        segs = [{"text": "রাম বলিল, "}, {"text": "“আমি যাইব।”"}, {"text": " সে "}, {"text": "হাসিল"}]
        self.assertEqual(expressive.segment_gaps(segs, TABLE), [220, 220, 120])

    def test_unit_boundaries_follow_voice_units(self):
        scene = {"scene_id": "s01", "blocks": [
            {"kind": "heading", "text": "এক"},
            {"kind": "paragraph", "text": "প্রথম কথা। " + "দীর্ঘ বাক্য, " * 30 + "শেষ।"},
            {"kind": "paragraph", "text": "আর এক।"}]}
        units = voice_units(scene, {"description": ""}, None, "bn")
        kinds = unit_boundaries(scene, "bn")
        pause = {"clause": 150, "sentence": 400, "heading": 1200, "paragraph": 800, "line": 400}
        self.assertEqual([u["pause_after_ms"] for u in units], [pause[k] for k in kinds])
        self.assertIn("clause", kinds)
        self.assertEqual(kinds[0], "heading")


class RoomToneTests(unittest.TestCase):
    def test_room_tone_is_soft_deterministic_and_faded(self):
        rate = 48000
        a = narration_join.room_tone(rate, rate, -62.0, 7, 10, 0.5)
        self.assertEqual(a.dtype, np.float32)
        self.assertTrue(np.array_equal(a, narration_join.room_tone(rate, rate, -62.0, 7, 10, 0.5)))
        self.assertFalse(np.array_equal(a, narration_join.room_tone(rate, rate, -62.0, 8, 10, 0.5)))
        self.assertAlmostEqual(rms_dbfs(a[480:-480]), -62.0, delta=0.5)
        self.assertLess(np.abs(a).max(), 10 ** (-45 / 20))  # far under any peak limit
        self.assertLess(abs(a[0]), 1e-5)
        self.assertLess(abs(a[-1]), 1e-5)
        self.assertGreater(np.abs(a[480:960]).max(), 0)
        self.assertEqual(len(narration_join.room_tone(0, rate)), 0)
        # pinned: a numpy upgrade must not change the bed
        self.assertEqual(hashlib.sha256(narration_join.room_tone(4800, 48000, -62.0, 1).tobytes())
                         .hexdigest()[:16], "22708f1237974139")

    def test_join_with_gaps_and_room_tone(self):
        rate = 1000
        a, b, c = np.ones(100, "float32"), np.full(50, 0.5, "float32"), np.full(80, 0.25, "float32")
        room = {"dbfs": -62.0, "seed": 11, "fade_ms": 10, "smooth_ms": 0.5}
        joined, secs = narration_join.join_segments([a, b, c], rate, gaps_ms=[220, 120], room=room)
        self.assertEqual(len(joined), 100 + 220 + 50 + 120 + 80)
        self.assertAlmostEqual(narration_join.joined_seconds(secs, gaps_ms=[220, 120]),
                               len(joined) / rate)
        gap = joined[100:320]
        self.assertFalse(np.all(gap == 0))  # room tone, not digital silence
        self.assertAlmostEqual(rms_dbfs(gap[10:-10]), -62.0, delta=1.0)
        self.assertEqual(joined[0], 1.0)
        self.assertEqual(joined[-1], 0.25)
        with self.assertRaises(ValueError):
            narration_join.join_segments([a, b], rate, gaps_ms=[220, 120])
        silent, _ = narration_join.join_segments([a, b], rate, gaps_ms=[220])
        self.assertTrue(np.all(silent[100:320] == 0))  # gaps without room: silence

    def _wav(self, path, seconds, freq):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=f={freq}:d={seconds}:r=24000", "-ac", "1", str(path)], check=True)

    def test_narration_track_room_tone_keeps_timing_loudness_and_peak(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            units = []
            for i, (s, p) in enumerate([(1.2, 683), (0.9, 1300), (1.5, 450), (1.0, 0)]):
                k = f"s01-{i + 1:03d}"
                self._wav(td / f"{k}.wav", s, 220 + 40 * i)
                units.append({"unit_key": k, "text": "x", "pause_after_ms": p})
            room = expressive.room_settings(TABLE)
            silent = film.narration_track(units, td, td / "silent.wav")
            toned = film.narration_track(units, td, td / "toned.wav", room=room)
            self.assertEqual(silent, toned)
            self.assertAlmostEqual(film._duration(td / "silent.wav"), film._duration(td / "toned.wav"),
                                   delta=0.002)
            pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(td / "toned.wav"), "-f", "f32le",
                                  "-"], check=True, capture_output=True).stdout
            x = np.frombuffer(pcm, dtype=np.float32)
            for a, b in zip(toned, toned[1:]):
                gap = x[int(a["end"] * 48000) + 500:int(b["start"] * 48000) - 500]
                self.assertGreater(len(gap), 0)
                self.assertFalse(np.all(gap == 0))
                self.assertAlmostEqual(rms_dbfs(gap), -62.0, delta=1.5)
            spch = x[int(toned[0]["start"] * 48000) + 100:int(toned[0]["end"] * 48000) - 100]
            self.assertGreater(rms_dbfs(spch), -25)  # speech untouched (an ffmpeg sine is -21 dBFS)
            m = mix.master(td / "toned.wav", td / "master.wav", cli.FILM_LUFS)
            self.assertLessEqual(m["true_peak"], -1.0)
            # the preview cut points come from the measured timing exactly as before
            pauses = [[round(a["end"] * 1000), round(b["start"] * 1000)]
                      for a, b in zip(toned, toned[1:]) if b["start"] > a["end"]]
            self.assertEqual(len(pauses), 3)


class ExpressiveJobTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / TITLE
        self.src = self.d / "src.json"
        self.src.write_text(json.dumps(SOURCE, ensure_ascii=False), encoding="utf-8")
        self.rates = self.d / "rates.json"
        self.rates.write_text(json.dumps(RATES), encoding="utf-8")
        self.voices = self.d / "voices.json"
        self.voices.write_text(json.dumps(chosen_voices()), encoding="utf-8")
        patcher = mock.patch.object(cast, "VOICES", self.voices)
        patcher.start()
        self.addCleanup(patcher.stop)

    def init_and_plan(self):
        self.assertEqual(run("init", self.src, "--root", self.root, "--slug", TITLE)[0], 0)
        self.assertEqual(run("plan", "--root", self.root)[0], 0)
        return cli._plan_units(json.loads((self.root / "plan.json").read_text()))

    def cast_doc(self, units, tone=True, moods=None):
        doc = {"schema": "eav.cast/1", "title": TITLE, "source_revision": SOURCE["revision_id"],
               "source_sha256": SOURCE["content_sha256"],
               "narrator": {"gender": "male", "rationale": "a male storyteller"},
               "characters": {"রাম": {"gender": "male", "note": ""},
                              "সীতা": {"gender": "female", "note": ""}},
               "units": {}, "notes": ""}
        for u in units:
            t = u["text"]
            if "“" not in t:
                continue
            i = t.index("“")
            who = "রাম" if "আমি কাল" in t else "সীতা"
            seg = {"text": t[i:], "role": "character", "speaker": who}
            if tone:
                seg["emotion"] = "command" if who == "রাম" else "happy"
            doc["units"][u["unit_key"]] = [{"text": t[:i], "role": "narrator"}, seg]
        if tone:
            doc["tone"] = dict(TONE)
            plain = [u["unit_key"] for u in units if u["unit_key"] not in doc["units"]]
            doc["narration_moods"] = moods if moods is not None else {plain[-1]: "sad"}
        return doc

    def write_cast(self, doc):
        (self.root / "specs").mkdir(exist_ok=True)
        (self.root / "specs" / "cast.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                         encoding="utf-8")

    def job_json(self, job_id):
        with zipfile.ZipFile(self.root / "jobs" / job_id / "inputs.zip") as z:
            return json.loads(z.read("job.json"))

    def build(self, doc=None):
        units = self.init_and_plan()
        doc = doc or self.cast_doc(units)
        self.write_cast(doc)
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--job-id", "narration-x1")
        self.assertEqual(code, 0, out)
        return units, doc, self.job_json("narration-x1"), out

    # ---------------------------------------------------------------- validation
    def test_validation_of_the_optional_fields(self):
        units = self.init_and_plan()
        s = SOURCE
        args = (TITLE, s["revision_id"], s["content_sha256"], units)
        good = self.cast_doc(units)
        self.assertEqual(cast.validate(good, *args), [])
        self.assertEqual(cast.validate(self.cast_doc(units, tone=False), *args), [])
        k = next(iter(good["units"]))
        plain = [u["unit_key"] for u in units if u["unit_key"] not in good["units"]]

        def broken(fn):
            d = json.loads(json.dumps(good))
            fn(d)
            return cast.validate(d, *args)
        cases = {
            "tone.pace": lambda d: d["tone"].update(pace="fast"),
            "tone.atmosphere": lambda d: d["tone"].update(atmosphere="eerie"),
            "not a voice unit": lambda d: d["narration_moods"].update({"zz-001": "sad"}),
            "is not one of": lambda d: d["narration_moods"].update({plain[0]: "calm"}),
            "needs emotion": lambda d: d["units"][k][1].pop("emotion"),
            "one of conversation": lambda d: d["units"][k][1].update(emotion="joy"),
            "not emotion": lambda d: d["units"][k][0].update(emotion="sad"),
            "needs tone": lambda d: d.pop("tone"),
            "keep it to clear": lambda d: d["narration_moods"].update(
                {u["unit_key"]: "fear" for u in units}),
        }
        for want, fn in cases.items():
            with self.subTest(want=want):
                errors = broken(fn)
                self.assertTrue(any(want in e for e in errors), errors)

    # ---------------------------------------------------------------- job rows
    def test_job_rows_carry_composed_descriptions_pauses_and_room_tone(self):
        units, doc, job, out = self.build()
        self.assertIn("Expressive layer", out)
        self.assertIn("tone slow/slightly expressive/'hushed and tender'", out)
        ex = job["cast"]["expressive"]
        self.assertEqual(ex["tone"], TONE)
        self.assertEqual(ex["table_sha256"], expressive.table_sha256())
        self.assertEqual(ex["room_tone"]["dbfs"], -62.0)
        rows = {u["unit_key"]: u for u in job["units"]}
        mood_key = next(iter(doc["narration_moods"]))
        for key, u in rows.items():
            mood = doc["narration_moods"].get(key, "calm")
            self.assertEqual(u["mood"], mood)
            self.assertEqual(u["description"],
                             expressive.describe(TABLE, "Arnav", TONE, "narrator", mood))
            self.assertIn("pause_rule", u)
            self.assertEqual(u["pause_after_ms"], u["pause_rule"]["ms"])
            self.assertEqual(u["room_tone"]["seed"], expressive.unit_seed(key, "room:"))
            for s in u.get("segments") or []:
                self.assertTrue(s["description"].startswith(s["voice"] + " "))
                self.assertTrue(s["description"].endswith(QUALITY))
                if s["role"] == "character":
                    self.assertEqual(s["description"], expressive.describe(
                        TABLE, s["voice"], TONE, "character", s["emotion"]))
            if u.get("segments"):
                self.assertEqual(u["segment_gaps_ms"], [220] * (len(u["segments"]) - 1))
        self.assertIn("sad tone", rows[mood_key]["description"])
        self.assertEqual(rows[mood_key]["description"].split()[0], "Arnav")
        first = job["units"][0]
        self.assertEqual(first["pause_rule"]["rule"], "heading")
        # into and out of dialogue the pause grows by 150 ms
        keys = [u["unit_key"] for u in job["units"]]
        for a, b in zip(keys, keys[1:]):
            va = (rows[a].get("segments") or [{"role": "narrator", "speaker": None}])[-1]
            vb = (rows[b].get("segments") or [{"role": "narrator", "speaker": None}])[0]
            change = (va["role"], va.get("speaker")) != (vb["role"], vb.get("speaker"))
            self.assertEqual(rows[a]["pause_rule"]["dialogue_ms"], 150 if change else 0)
        self.assertTrue(any(u["pause_rule"]["dialogue_ms"] for u in job["units"]))
        # the plan's own units are untouched (film re-derives them; the job rows carry the pauses)
        self.assertEqual({u["pause_after_ms"] for u in units} - {150, 400, 800, 1200}, set())

    def test_cast_without_tone_has_no_expressive_fields(self):
        units = self.init_and_plan()
        self.write_cast(self.cast_doc(units, tone=False))
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--job-id", "narration-plain-cast")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Expressive layer", out)
        job = self.job_json("narration-plain-cast")
        self.assertNotIn("expressive", job["cast"])
        text = json.dumps(job, ensure_ascii=False)
        for k in ("pause_rule", "room_tone", "segment_gaps_ms", '"mood"', '"emotion"'):
            self.assertNotIn(k, text)
        self.assertEqual([u["pause_after_ms"] for u in job["units"]],
                         [u["pause_after_ms"] for u in units[:len(job["units"])]])

    # ---------------------------------------------------------------- runner
    def test_notebook_joins_with_the_rows_gaps_and_room_tone(self):
        rec = Record.create(self.d / "rec", "garden-book", {"x": 1})
        ledger = Ledger(self.d / "ledger.json")
        scene = {"scene_id": "s01", "text": "Tom said, “Come here.” The rain fell all night long."}
        units = voice_units(scene, {"description": "x"}, None, "en")
        k = units[0]["unit_key"]
        i = units[0]["text"].index("“")
        doc = {"narrator": {"gender": "female"}, "characters": {"Tom": {"gender": "male"}},
               "tone": TONE, "narration_moods": {units[1]["unit_key"]: "fear"},
               "units": {k: [{"text": units[0]["text"][:i], "role": "narrator"},
                             {"text": units[0]["text"][i:], "role": "character", "speaker": "Tom",
                              "emotion": "command"}]}}
        jc = cast.job_cast(doc, chosen_voices(), "c" * 64)
        r = colab_jobs.build_job("narration", rec, {"scenes": [scene], "preset": {"description": "x"},
                                                    "cast": jc, "batch": 2},
                                 ledger, {"narration": RATES["narration"]}, self.d / "rec" / "jobs",
                                 month="2026-11")
        drive = self.d / "drive"
        drive.mkdir()
        shutil.copy(r["inputs_zip"], drive / "inputs.zip")
        job = json.loads(zipfile.ZipFile(r["inputs_zip"]).read("job.json"))
        self.assertEqual(job["units"][0]["segment_gaps_ms"], [220])
        self.assertIn("fearful", job["units"][1]["description"])
        self.assertIn("commanding", job["units"][0]["segments"][1]["description"])
        nb = json.loads(Path(r["notebook"]).read_text())
        cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
        FakeModel.calls, FakeModel.with_lengths = [], True
        g = {}
        with mock.patch.dict(sys.modules, fake_modules()), mock.patch("subprocess.run"), \
                mock.patch.object(importlib.metadata, "distribution",
                                  side_effect=importlib.metadata.PackageNotFoundError):
            exec(cells[0], g)
            g["RUN"] = True
            exec(cells[1], g)
            g.update(DRIVE_JOB_DIR=str(drive), DEADLINE_SECONDS=1000)
            try:
                for c in cells[2:6]:
                    exec(c, g)
            finally:
                g["STOP_GUARD"].cancel()
                g["HEARTBEAT_STOP"].set()
        man = json.loads((drive / "manifest.json").read_text())
        self.assertEqual(man["status"], "COMPLETE")
        lens = [len(units[0]["text"][:i]) * 3, len(units[0]["text"][i:]) * 3]  # 100 Hz fake model
        samples = np.frombuffer((drive / f"{k}.wav").read_bytes()[:-3], dtype="float32")
        self.assertEqual(len(samples), sum(lens) + 22)  # the row's 220 ms gap at 100 Hz
        gap = samples[lens[0]:lens[0] + 22]
        self.assertFalse(np.all(gap == 0))
        want = narration_join.room_tone(22, 100, -62.0, job["units"][0]["room_tone"]["seed"], 10, 0.5)
        self.assertTrue(np.allclose(gap, want))

    # ---------------------------------------------------------------- assembly / provenance / qc
    def fake_outputs(self, job_id):
        rows = self.job_json(job_id)["units"]
        folder = self.d / "download" / job_id
        folder.mkdir(parents=True)
        outputs, report = {}, {}
        for i, u in enumerate(rows):
            if u.get("segments"):
                secs = [round(len(s["text"]) / 12, 2) for s in u["segments"]]
                report[u["unit_key"]] = secs
                total = narration_join.joined_seconds(secs, gaps_ms=u["segment_gaps_ms"])
            else:
                total = round(len(u["text"]) / 12, 2)
            wav = folder / f"{u['unit_key']}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"sine=f={200 + 20 * i}:d={total}:r=24000", "-ac", "1", str(wav)],
                           check=True)
            outputs[wav.name] = hashlib.sha256(wav.read_bytes()).hexdigest()
        zip_sha = hashlib.sha256((self.root / "jobs" / job_id / "inputs.zip").read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": job_id, "title": TITLE,
            "kind": "narration", "input_zip_sha256": zip_sha,
            "model": {"repo": "ai4bharat/indic-parler-tts", "revision": "x"}, "status": "COMPLETE",
            "packages": {"parler_tts": "0.2.2"}, "outputs": outputs, "segment_seconds": report}),
            encoding="utf-8")
        return folder

    def test_track_uses_the_job_pauses_with_room_tone_and_records_provenance(self):
        units, doc, job, _ = self.build()
        folder = self.fake_outputs("narration-x1")
        self.assertEqual(run("import", "narration-x1", "--root", self.root, "--from", folder,
                             "--units", 0.5)[0], 0)
        rec = Record.load(self.root)
        narr = cli._latest_job(rec, "narration", "film-01")
        rows = {u["unit_key"]: u for u in job["units"]}
        film_units = [u for u in units if u["unit_key"] in rows]
        timing, prov = cli._measured_track(rec, film_units, narr, self.d / "track.wav")
        for a, b in zip(timing, timing[1:]):
            self.assertAlmostEqual(b["start"] - a["end"], rows[a["unit_key"]]["pause_after_ms"] / 1000,
                                   delta=0.002)
        ex = prov["expressive"]
        self.assertEqual(ex["tone"], TONE)
        self.assertEqual(ex["room_tone"]["dbfs"], -62.0)
        self.assertEqual(ex["room_tone"]["method"], "eav.narration_join.room_tone")
        self.assertEqual(set(ex["unit_pauses"]), set(rows))
        k0 = film_units[0]["unit_key"]
        self.assertEqual(ex["unit_pauses"][k0]["rule"], rows[k0]["pause_rule"]["rule"])
        self.assertFalse(ex["unit_pauses"][film_units[-1]["unit_key"]]["applied"])
        seg_key = next(k for k, u in rows.items() if u.get("segments"))
        self.assertEqual(ex["unit_pauses"][seg_key]["segment_gaps_ms"], rows[seg_key]["segment_gaps_ms"])
        voices = prov["unit_voices"][seg_key]
        self.assertEqual([v["description"] for v in voices],
                         [s["description"] for s in rows[seg_key]["segments"]])
        self.assertEqual(voices[1]["emotion"], rows[seg_key]["segments"][1]["emotion"])
        self.assertEqual(voices[0]["mood"], "calm")
        # per-segment QC still applies with the unit's own (longer) gaps
        qrows = qc.narration_rows(film_units, cli._one_dir(rec, narr), cli._voices(rec, narr))
        self.assertTrue(any(r.get("segment") for r in qrows if r["unit_key"] == seg_key))

    # ---------------------------------------------------------------- style audition
    def test_style_audition_builds_four_takes_in_the_chosen_voices(self):
        units = self.init_and_plan()
        doc = self.cast_doc(units)
        plain = [u for u in units if u["unit_key"] not in doc["units"]
                 and 20 <= len(u["text"]) <= 160]
        doc["narration_moods"] = {plain[-1]["unit_key"]: "fear"}
        self.write_cast(doc)
        passages, rows = cast.style_audition(doc, units, chosen_voices())
        self.assertEqual([p["passage"] for p in passages],
                         ["style-calm", "style-fear", "style-line-command", "style-line-happy"])
        self.assertEqual([p["voice"] for p in passages], ["Arnav", "Arnav", "Arjun", "Riya"])
        self.assertEqual(rows[1]["description"],
                         expressive.describe(TABLE, "Arnav", TONE, "narrator", "fear"))
        self.assertEqual(rows[2]["unit_key"], "arjun-style-line-command")
        code, out = run("audition", "--root", self.root, "--rates", self.rates, "--style-audition")
        self.assertEqual(code, 0, out)
        self.assertIn("expressive layer in the chosen voices", out)
        job_id = next(p.name for p in (self.root / "jobs").iterdir())
        self.assertTrue(job_id.startswith("style-audition-"))
        job = self.job_json(job_id)
        self.assertEqual([u["unit_key"] for u in job["units"]], [r["unit_key"] for r in rows])
        self.assertTrue(job["audition"]["style"])
        self.assertEqual(job["audition"]["speakers"], {"male": ["Arjun", "Arnav"], "female": ["Riya"]})
        ledger = json.loads((self.d / "titles" / "allowance-ledger.json").read_text())
        self.assertEqual([r["job_id"] for r in ledger], [job_id])  # reserved like any job
        # a cast without tone is refused before anything is reserved
        self.write_cast(self.cast_doc(units, tone=False))
        code, out = run("audition", "--root", self.root, "--rates", self.rates, "--style-audition",
                        "--job-id", "style-audition-again")
        self.assertEqual(code, 2, out)
        self.assertIn("no tone", out)
        self.assertEqual(len(json.loads((self.d / "titles" / "allowance-ledger.json").read_text())), 1)


if __name__ == "__main__":
    unittest.main()
