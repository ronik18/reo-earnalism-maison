"""Multi-voice narration casting (owner decision 28 Nov 2026): specs/cast.json + the owner's chosen
voices make film narration multi-voice; each segment is synthesized on its own with its voice and
joined into the unit's one WAV; truncation QC works per segment; titles without a cast file are
unchanged byte for byte; `eav audition` builds the listening job."""
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

from eav import cast, cli, colab_jobs, importer, narration_join, qc
from eav.budget import Ledger
from eav.record import Record
from eav.voice import voice_units
from tests._narration_fakes import FakeModel, fake_modules
from tests.test_cli import RATES, run

ROSTER = cli.ROSTER
PARAS = [
    ("a1", "heading", "এক"),
    ("a2", "paragraph", "রাম বলিল, “আমি কাল সকালে বাজারে যাইব।” সীতা হাসিয়া কহিল, “তুমি তো রোজই "
                        "এই কথা বল।” তারপর দুজনেই চুপ করিয়া রহিল, আর বাহিরে বৃষ্টি পড়িতে লাগিল "
                        "অনেকক্ষণ ধরিয়া।"),
    ("a3", "paragraph", "গ্রামের পথে সন্ধ্যা নামিল এবং দূরের মন্দিরে শাঁখ বাজিয়া উঠিল ধীরে ধীরে "
                        "সকলের অজান্তে।"),
]
SOURCE = {
    "language": "bn", "edition_id": "e-bn", "revision_id": "r-bn-1",
    "content_sha256": "d" * 64, "rights": {"reader": ["preview", "read"]},
    "public_domain_evidence": True, "state": "live", "assets": [], "timing_maps": [],
    "units": [{"unit_id": "u-1", "title": "এক",
               "paragraphs": [{"anchor_id": a, "kind": k, "text": t} for a, k, t in PARAS]}],
}
TITLE = "ramsita"


def chosen_voices(male=("Arnav", "Arjun"), female=("Riya", "Aditi")) -> dict:
    v = cast.load_voices()
    t = v["description_template"]
    return {**v, "status": "chosen", "chosen_by": "owner", "chosen_at": "2026-11-28",
            "male": [{"speaker": n, "description": t.format(speaker=n)} for n in male],
            "female": [{"speaker": n, "description": t.format(speaker=n)} for n in female]}


class CastTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / TITLE
        self.ledger = self.d / "titles" / "allowance-ledger.json"
        self.src = self.d / "src.json"
        self.src.write_text(json.dumps(SOURCE, ensure_ascii=False), encoding="utf-8")
        self.rates = self.d / "rates.json"
        self.rates.write_text(json.dumps(RATES), encoding="utf-8")
        self.voices = self.d / "voices.json"
        self.voices.write_text(json.dumps(chosen_voices()), encoding="utf-8")
        patcher = mock.patch.object(cast, "VOICES", self.voices)
        patcher.start()
        self.addCleanup(patcher.stop)

    # ---------------------------------------------------------------- helpers
    def init_and_plan(self):
        self.assertEqual(run("init", self.src, "--root", self.root, "--slug", TITLE)[0], 0)
        self.assertEqual(run("plan", "--root", self.root)[0], 0)
        return cli._plan_units(json.loads((self.root / "plan.json").read_text()))

    def cast_doc(self, units, **extra):
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
            doc["units"][u["unit_key"]] = [{"text": t[:i], "role": "narrator"},
                                           {"text": t[i:], "role": "character", "speaker": who}]
        doc.update(extra)
        return doc

    def write_cast(self, doc):
        (self.root / "specs").mkdir(exist_ok=True)
        (self.root / "specs" / "cast.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                         encoding="utf-8")

    def job(self, *extra):
        return run("job", "narration", "--root", self.root, "--rates", self.rates, *extra)

    def job_json(self, job_id):
        with zipfile.ZipFile(self.root / "jobs" / job_id / "inputs.zip") as z:
            return json.loads(z.read("job.json"))

    def only_job(self):
        return next((self.root / "jobs").iterdir()).name

    def ledger_rows(self):
        return json.loads(self.ledger.read_text()) if self.ledger.exists() else []

    def tone(self, path, seconds, freq):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=f={freq}:d={seconds}:r=24000", "-ac", "1", str(path)], check=True)

    def fake_outputs(self, job_id, seg_seconds=None, report=True):
        """The downloaded job folder: one WAV per unit; a segmented unit lasts its segments plus
        the gaps, and the manifest reports its segment seconds (as the runner does)."""
        rows = self.job_json(job_id)["units"]
        folder = self.d / "download" / job_id
        folder.mkdir(parents=True)
        outputs, report_ = {}, {}
        for i, u in enumerate(rows):
            if u.get("segments"):
                secs = [(seg_seconds or {}).get((u["unit_key"], n)) or round(len(s["text"]) / 12, 2)
                        for n, s in enumerate(u["segments"], 1)]
                report_[u["unit_key"]] = secs
                total = narration_join.joined_seconds(secs)
            else:
                total = round(len(u["text"]) / 12, 2)
            wav = folder / f"{u['unit_key']}.wav"
            self.tone(wav, total, 200 + 20 * i)
            outputs[wav.name] = hashlib.sha256(wav.read_bytes()).hexdigest()
        zip_sha = hashlib.sha256((self.root / "jobs" / job_id / "inputs.zip").read_bytes()).hexdigest()
        manifest = {"schema": "earnalism.audiovisual-outputs.v1", "job_id": job_id, "title": TITLE,
                    "kind": "narration", "input_zip_sha256": zip_sha,
                    "model": {"repo": "ai4bharat/indic-parler-tts", "revision": "x"},
                    "status": "COMPLETE", "packages": {"parler_tts": "0.2.2"}, "outputs": outputs}
        if report and report_:
            manifest["segment_seconds"] = report_
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder

    def cast_job(self, **extra):
        units = self.init_and_plan()
        self.write_cast(self.cast_doc(units, **extra))
        code, out = self.job()
        self.assertEqual(code, 0, out)
        return self.only_job(), units, out

    # ---------------------------------------------------------------- voices roster
    def test_voice_template_is_the_approved_arnav_description(self):
        v = json.loads(cast.VOICES.read_text()) if cast.VOICES.exists() else None
        real = cast.load_voices(Path(cast.__file__).resolve().parents[2] / "references" / "voices.json")
        # The owner picked from audition-15a5c974 (28 Nov 2026): Arnav, Arjun; Aditi, Riya.
        self.assertEqual(real["status"], "chosen")
        self.assertEqual(real["audition_job_id"], "audition-15a5c974")
        self.assertEqual([v["speaker"] for v in real["male"]], ["Arnav", "Arjun"])
        self.assertEqual([v["speaker"] for v in real["female"]], ["Aditi", "Riya"])
        for v in real["male"] + real["female"]:
            self.assertEqual(v["description"], real["description_template"].format(speaker=v["speaker"]))
        roster = json.loads(ROSTER.read_text())["profiles"]["bn_arnav"]["presets"]["story"]
        self.assertEqual(real["description_template"].format(speaker="Arnav"), roster["description"])
        self.assertEqual(real["speakers"], {"male": list(cast.SPEAKERS["male"]),
                                            "female": list(cast.SPEAKERS["female"])})
        pending = {**real, "status": "audition_pending", "male": None, "female": None,
                   "chosen_by": None, "chosen_at": None, "audition_job_id": None}
        with self.assertRaises(cast.VoicesNotChosen):
            cast.chosen(pending)
        self.assertIsNotNone(v)

    def test_choice_rules(self):
        for bad in (chosen_voices(male=("Arnav", "Arnav")), chosen_voices(male=("Arnav", "Riya"))):
            with self.assertRaises(ValueError):
                cast.chosen(bad)
        doc = {"narrator": {"gender": "male"}, "characters": {
            "a": {"gender": "male"}, "b": {"gender": "female"}}}
        who = cast.resolve(doc, chosen_voices())
        self.assertEqual(who["narrator"]["speaker"], "Arnav")
        self.assertEqual(who["characters"]["a"]["speaker"], "Arjun")  # same gender: the other voice
        self.assertEqual(who["characters"]["b"]["speaker"], "Riya")   # opposite: its primary
        who = cast.resolve({**doc, "narrator_voice": "secondary"}, chosen_voices())
        self.assertEqual(who["narrator"]["speaker"], "Arjun")
        self.assertEqual(who["characters"]["a"]["speaker"], "Arnav")
        self.assertEqual(who["characters"]["b"]["speaker"], "Riya")
        who = cast.resolve({"narrator": {"gender": "female"}, "characters": doc["characters"]},
                           chosen_voices())
        self.assertEqual((who["narrator"]["speaker"], who["characters"]["a"]["speaker"],
                          who["characters"]["b"]["speaker"]), ("Riya", "Arnav", "Aditi"))

    # ---------------------------------------------------------------- job building
    def test_no_cast_title_job_json_unchanged_and_voices_never_read(self):
        units = self.init_and_plan()
        with mock.patch.object(cast, "VOICES", self.d / "missing.json"):
            code, out = self.job("--job-id", "narration-plain01")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Multi-voice", out)
        raw = zipfile.ZipFile(self.root / "jobs" / "narration-plain01" / "inputs.zip").read("job.json")
        plan = json.loads((self.root / "plan.json").read_text())
        preset = {k: v for k, v in plan["voice"].items()
                  if k == "description" or k in colab_jobs.GENERATION_KEYS}
        want = {"schema": colab_jobs.JOB_SCHEMA, "kind": "narration", "job_id": "narration-plain01",
                "title": TITLE, "model": colab_jobs.NARRATION_REPO,
                "units": [u for sc in plan["plan"]["films"][0]["scenes"]
                          for u in voice_units(sc, preset, None, "bn")],
                "generation": {"temperature": 0.91}, "batch": colab_jobs.DEFAULT_BATCH}
        self.assertEqual(raw, (json.dumps(want, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        self.assertEqual(len(units), len(want["units"]))

    def test_cast_segments_carry_the_right_voices(self):
        job_id, units, out = self.cast_job()
        self.assertIn("Multi-voice", out)
        self.assertIn("narrator Arnav (male, primary)", out)
        job = self.job_json(job_id)
        self.assertEqual(job["cast"]["narrator"], {"gender": "male", "slot": "primary",
                                                   "speaker": "Arnav"})
        self.assertEqual(job["cast"]["characters"], {"রাম": "Arjun", "সীতা": "Riya"})
        tmpl = cast.load_voices()["description_template"]
        segmented = [u for u in job["units"] if u.get("segments")]
        self.assertEqual(len(segmented), 2)
        for u in job["units"]:
            self.assertEqual(u["description"], tmpl.format(speaker="Arnav"))
            self.assertEqual(u["voice"], "Arnav")
            if u.get("segments"):
                self.assertEqual("".join(s["text"] for s in u["segments"]), u["text"])
                nar, ch = u["segments"]
                self.assertEqual((nar["role"], nar["speaker"], nar["voice"]), ("narrator", None, "Arnav"))
                self.assertEqual(nar["description"], tmpl.format(speaker="Arnav"))
                want = "Arjun" if ch["speaker"] == "রাম" else "Riya"
                self.assertEqual((ch["role"], ch["voice"]), ("character", want))
                self.assertEqual(ch["description"], tmpl.format(speaker=want))
        # forecast items are the Parler generations (2 segmented units of 2 segments each)
        build = json.loads((self.root / "jobs" / job_id / "build-manifest.json").read_text())
        self.assertEqual(build["model"]["repo"], colab_jobs.NARRATION_REPO)
        row = self.ledger_rows()[0]
        plain = colab_jobs.derive_compute("narration", {}, RATES, len(job["units"]))
        cast_c = colab_jobs.derive_compute("narration", {}, RATES, len(job["units"]) + 2)
        from eav import budget
        self.assertAlmostEqual(row["units"], budget.forecast(cast_c, RATES))
        self.assertGreater(row["units"], budget.forecast(plain, RATES))

    def test_narrator_voice_override_alternates_the_story_voice(self):
        job_id, _, out = self.cast_job(narrator_voice="secondary")
        job = self.job_json(job_id)
        self.assertEqual(job["cast"]["narrator"]["speaker"], "Arjun")
        self.assertEqual(job["cast"]["characters"], {"রাম": "Arnav", "সীতা": "Riya"})

    def test_stale_cast_is_refused_before_any_reservation(self):
        units = self.init_and_plan()
        doc = self.cast_doc(units)
        key = next(iter(doc["units"]))
        bad_text = json.loads(json.dumps(doc))
        bad_text["units"][key][0]["text"] += "x"
        for bad, why in ((bad_text, "do not join to the unit text exactly"),
                         ({**doc, "source_revision": "r-old"}, "source_revision"),
                         ({**doc, "source_sha256": "0" * 64}, "source_sha256"),
                         ({**doc, "units": {"f09s009-001": doc["units"][key]}},
                          "not a voice unit of the current source")):
            self.write_cast(bad)
            code, out = self.job()
            self.assertEqual(code, 2, out)
            self.assertIn("does not fit the current source", out)
            self.assertIn(why, out)
            self.assertIn("Re-annotate", out)
            self.assertEqual(self.ledger_rows(), [])
            self.assertFalse((self.root / "jobs").exists() and any((self.root / "jobs").iterdir()))

    def test_voices_not_chosen_refuses_cast_jobs(self):
        units = self.init_and_plan()
        self.write_cast(self.cast_doc(units))
        real = cast.load_voices(Path(cast.__file__).resolve().parents[2] / "references" / "voices.json")
        self.voices.write_text(json.dumps({**real, "status": "audition_pending", "male": None,
                                           "female": None, "chosen_by": None, "chosen_at": None,
                                           "audition_job_id": None}))
        code, out = self.job()
        self.assertEqual(code, 2, out)
        self.assertIn("voices not chosen yet — run the audition", out)
        self.assertIn("audition --root", out)
        self.assertEqual(self.ledger_rows(), [])

    def test_reel_narration_stays_single_voice(self):
        units = self.init_and_plan()
        self.write_cast(self.cast_doc(units))
        spec = {"scenes": [{"scene_id": "r1", "text": "রাম বলিল।"}], "preset": {"description": "d"},
                "language": "bn"}
        self.assertEqual(colab_jobs.narration_units(spec)[0]["description"], "d")

    # ---------------------------------------------------------------- runner
    def test_join_segments(self):
        rate = 1000
        a, b = np.ones(100, dtype="float32"), np.full(50, 0.5, dtype="float32")
        joined, secs = narration_join.join_segments([a, b], rate)
        gap = int(rate * narration_join.SEGMENT_GAP_MS / 1000)
        self.assertEqual(len(joined), 100 + gap + 50)
        self.assertEqual(secs, [0.1, 0.05])
        self.assertAlmostEqual(narration_join.joined_seconds(secs), len(joined) / rate)
        self.assertTrue(np.all(joined[100:100 + gap] == 0))  # the silence between voices
        fade = int(rate * narration_join.EDGE_FADE_MS / 1000)
        # outer edges untouched, inner edges faded (no click into or out of the gap)
        self.assertEqual(joined[0], 1.0)
        self.assertEqual(joined[-1], 0.5)
        self.assertLess(joined[99], 0.2)
        self.assertLess(joined[100 + gap], 0.1)
        self.assertTrue(np.all(np.diff(joined[100 - fade:100]) <= 0))
        self.assertTrue(np.all(joined[fade:100 - fade] == 1.0))
        one, secs = narration_join.join_segments([a], rate)  # a single segment: unchanged
        self.assertTrue(np.array_equal(one, a))
        with self.assertRaises(ValueError):
            narration_join.join_segments([], rate)
        self.assertGreaterEqual(narration_join.SEGMENT_GAP_MS, 120)
        self.assertLessEqual(narration_join.SEGMENT_GAP_MS, 200)

    def test_notebook_synthesizes_each_segment_with_its_voice_and_joins(self):
        rec = Record.create(self.d / "rec", "garden-book", {"x": 1})
        ledger = Ledger(self.d / "ledger.json")
        scene = {"scene_id": "s01", "text": "Tom said, “Come here.” The rain fell all night long."}
        units = voice_units(scene, {"description": "x"}, None, "en")
        k = units[0]["unit_key"]
        i = units[0]["text"].index("“")
        jc = {"cast_sha256": "c" * 64,
              "narrator": {"gender": "female", "slot": "primary", "speaker": "Riya",
                           "description": "Riya narrates."},
              "characters": {"Tom": {"gender": "male", "slot": "primary", "speaker": "Arnav",
                                     "description": "Arnav speaks."}},
              "segments": {k: [{"text": units[0]["text"][:i], "role": "narrator", "speaker": None,
                                "voice": "Riya", "description": "Riya narrates."},
                               {"text": units[0]["text"][i:], "role": "character", "speaker": "Tom",
                                "voice": "Arnav", "description": "Arnav speaks."}]}}
        r = colab_jobs.build_job("narration", rec, {"scenes": [scene], "preset": {"description": "x"},
                                                    "cast": jc, "batch": 2},
                                 ledger, {"narration": RATES["narration"]}, self.d / "rec" / "jobs",
                                 month="2026-11")
        drive = self.d / "drive"
        drive.mkdir()
        shutil.copy(r["inputs_zip"], drive / "inputs.zip")
        nb = json.loads(Path(r["notebook"]).read_text())
        cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
        self.assertIn("def join_segments", cells[4])  # embedded verbatim from eav.narration_join
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
                exec(cells[2], g)
                exec(cells[3], g)
                exec(cells[4], g)
                exec(cells[5], g)
            finally:
                g["STOP_GUARD"].cancel()
                g["HEARTBEAT_STOP"].set()
        # 3 generations (2 segments + 1 plain unit) in batches of 2, with their own descriptions
        prompts = [len(c["prompt_input_ids"]) for c in FakeModel.calls]
        self.assertEqual(prompts, [2, 1])
        man = json.loads((drive / "manifest.json").read_text())
        self.assertEqual(man["status"], "COMPLETE")
        self.assertEqual(set(man["segment_seconds"]), {k})
        segs = man["segment_seconds"][k]
        # the fake model writes 3 samples per prompt token at 100 Hz; the joined WAV holds both
        # segments plus one 150 ms gap
        lens = [len(units[0]["text"][:i]) * 3, len(units[0]["text"][i:]) * 3]
        self.assertEqual(segs, [round(n / 100, 3) for n in lens])
        raw = (drive / f"{k}.wav").read_bytes()
        samples = np.frombuffer(raw[:-3], dtype="float32")  # fake soundfile appends the rate
        self.assertEqual(len(samples), sum(lens) + 15)
        self.assertTrue(np.all(samples[lens[0]:lens[0] + 15] == 0))
        self.assertNotIn("segment_seconds", json.dumps(
            {kk: vv for kk, vv in man.items() if kk != "segment_seconds"}))
        # the plain unit is written as before (its own samples only)
        plain = units[1]["unit_key"]
        raw = (drive / f"{plain}.wav").read_bytes()
        self.assertEqual(len(np.frombuffer(raw[:-3], dtype="float32")), len(units[1]["text"]) * 3)

    # ---------------------------------------------------------------- QC
    def test_per_segment_suspects_against_a_per_voice_median(self):
        rows = [{"unit_key": f"u{i}", "voice": "Arnav", "chars": 60, "seconds": 5.0} for i in range(5)]
        rows += [{"unit_key": f"v{i}", "voice": "Riya", "chars": 60, "seconds": 3.0} for i in range(4)]
        # Riya speaks faster overall: 20 chars/s is normal for her, but for Arnav (12) it is cut off
        rows.append({"unit_key": "x", "segment": 2, "voice": "Arnav", "chars": 60, "seconds": 3.0})
        rows.append({"unit_key": "y", "segment": 1, "voice": "Riya", "chars": 60, "seconds": 3.0})
        found = qc.truncation_suspects(rows)
        self.assertEqual([(s["unit_key"], s["segment"], s["voice"]) for s in found], [("x", 2, "Arnav")])
        self.assertIn("Arnav median", found[0]["reasons"][0])
        # rows without a voice keep the one job median (single-voice jobs as before)
        plain = [{"unit_key": r["unit_key"], "chars": r["chars"], "seconds": r["seconds"]} for r in rows]
        self.assertEqual(qc.truncation_suspects(plain), [])

    def test_cut_segment_inside_a_joined_unit_is_caught_and_gates_the_film(self):
        job_id, units, _ = self.cast_job()
        job = self.job_json(job_id)
        seg_unit = next(u for u in job["units"] if u.get("segments"))
        key = seg_unit["unit_key"]
        # the character line came back far too short (the fixture's lines are short, so the
        # ratio test's character floor is lowered for them)
        cut = {(key, 2): 0.3}
        folder = self.fake_outputs(job_id, cut)
        with mock.patch.object(qc, "MIN_RATIO_CHARS", 10):
            code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 0.5)
            self.assertEqual(code, 0, out)
            self.assertIn(f"{key} segment 2 (", out)
            self.assertIn("suspect_truncated", out)
            rec = Record.load(self.root)
            accepted = next(e["detail"] for e in rec.data["events"]
                            if e["stage"] == "import" and e["detail"].get("job_id") == job_id)
            self.assertEqual(accepted["segment_seconds"][key][1], 0.3)
            narr = cli._latest_job(rec, "narration", "film-01")
            film_units = [u for u in units if u["unit_key"] in {x["unit_key"] for x in job["units"]}]
            with self.assertRaises(cli.Stop) as stop:
                cli._truncation_gate(rec, [(narr, film_units)], set(), "film film-01")
            self.assertEqual(stop.exception.code, 5)
            self.assertIn(f"--redo-units {job_id}:{key}", stop.exception.next_action)
            # accepted once per unit, even with several suspect segments
            self.assertTrue(cli._truncation_gate(rec, [(narr, film_units)], {key}, "film"))

    def test_import_checks_the_segment_report(self):
        job_id, _, _ = self.cast_job()
        rows = self.job_json(job_id)["units"]
        seg = {u["unit_key"]: [1.0] * len(u["segments"]) for u in rows if u.get("segments")}
        self.assertEqual(importer.segment_seconds_of(rows, {"segment_seconds": seg}), seg)
        self.assertIsNone(importer.segment_seconds_of(rows, {}))
        k = next(iter(seg))
        for bad in ({k: [1.0]}, {**seg, k: [1.0, -1]}, {**seg, "zz": [1.0]}, {**seg, k: "1"}):
            with self.assertRaises(ValueError):
                importer.segment_seconds_of(rows, {"segment_seconds": bad})
        folder = self.fake_outputs(job_id)
        man = json.loads((folder / "manifest.json").read_text())
        man["segment_seconds"][k] = [1.0]
        (folder / "manifest.json").write_text(json.dumps(man))
        code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 0.5)
        self.assertEqual(code, 4, out)
        self.assertIn("segment_seconds", out)

    def test_provenance_records_segment_voices(self):
        job_id, units, _ = self.cast_job()
        folder = self.fake_outputs(job_id)
        self.assertEqual(run("import", job_id, "--root", self.root, "--from", folder,
                             "--units", 0.5)[0], 0)
        rec = Record.load(self.root)
        narr = cli._latest_job(rec, "narration", "film-01")
        job = self.job_json(job_id)
        film_units = [u for u in units if u["unit_key"] in {x["unit_key"] for x in job["units"]}]
        _, prov = cli._measured_track(rec, film_units, narr, self.d / "track.wav")
        self.assertEqual(prov["cast"], job["cast"])
        seg = next(u for u in job["units"] if u.get("segments"))
        self.assertEqual([v["voice"] for v in prov["unit_voices"][seg["unit_key"]]],
                         [s["voice"] for s in seg["segments"]])
        plain = next(u for u in job["units"] if not u.get("segments"))
        self.assertEqual(prov["unit_voices"][plain["unit_key"]],
                         [{"voice": "Arnav", "role": "narrator", "speaker": None}])

    # ---------------------------------------------------------------- redo
    def test_redo_carries_segments_unchanged(self):
        job_id, _, _ = self.cast_job()
        job = self.job_json(job_id)
        seg = next(u for u in job["units"] if u.get("segments"))
        folder = self.fake_outputs(job_id)
        self.assertEqual(run("import", job_id, "--root", self.root, "--from", folder,
                             "--units", 0.5)[0], 0)
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--redo-units", f"{job_id}:{seg['unit_key']}")
        self.assertEqual(code, 0, out)
        redo = self.job_json(f"{job_id}-u1")
        self.assertEqual(redo["units"], [seg])
        self.assertEqual(redo["cast"], job["cast"])
        # its forecast counts both segment generations
        plan = colab_jobs._redo_plan(job, json.loads((self.root / "jobs" / job_id /
                                                      "build-manifest.json").read_text()),
                                     [seg["unit_key"]], RATES)
        self.assertEqual(plan["compute"]["items"], len(seg["segments"]))
        # import of the redo: its own segment report decides the new take
        rfolder = self.fake_outputs(f"{job_id}-u1")
        code, out = run("import", f"{job_id}-u1", "--root", self.root, "--from", rfolder,
                        "--units", 0.1)
        self.assertEqual(code, 0, out)
        self.assertIn("passed the truncation check", out)
        rec = Record.load(self.root)
        v = cli._voices(rec, cli._latest_job(rec, "narration", "film-01"))
        self.assertEqual(len(v[seg["unit_key"]]["segment_seconds"]), len(seg["segments"]))

    # ---------------------------------------------------------------- chunks
    def test_chunks_end_on_unit_boundaries(self):
        units = [{"segments": [1, 2, 3]}, {}, {"segments": [1, 2]}, {}, {}]
        compute = {"kind": "narration", "steps": 1, "items": 8, "takes": 1, "decode_s": 0,
                   "export_s": 0}
        rates = {"narration": {"s_per_step": 1000.0, "units_per_hour": 1.0}}
        with mock.patch.object(colab_jobs, "forecast_seconds",
                               side_effect=lambda c, r: c["items"] * 1000.0):
            got = colab_jobs.narration_chunks(units, compute, rates)
            self.assertEqual(got, [(1, 3), (2, 3), (2, 2)])  # 3 | 1+2 | 1+1
            self.assertEqual(sum(n for n, _ in got), len(units))
            plain = [{}] * 7
            self.assertEqual(colab_jobs.narration_chunks(plain, {**compute, "items": 7}, rates),
                             [(k, k) for k in colab_jobs.chunk_sizes({**compute, "items": 7}, rates)])

    # ---------------------------------------------------------------- audition / status
    def test_audition_job_build(self):
        units = self.init_and_plan()
        self.write_cast(self.cast_doc(units))
        self.voices.write_text(json.dumps(cast.load_voices(
            Path(cast.__file__).resolve().parents[2] / "references" / "voices.json")))
        code, out = run("audition", "--root", self.root, "--rates", self.rates, "--from", TITLE)
        self.assertEqual(code, 0, out)
        job_id = self.only_job()
        self.assertTrue(job_id.startswith("audition-"), job_id)
        self.assertIn(f"Built audition job {job_id}: 18 takes", out)
        job = self.job_json(job_id)
        self.assertEqual(job["kind"], "narration")
        self.assertEqual(len(job["units"]), 18)
        passages = job["audition"]["passages"]
        self.assertEqual([p["passage"] for p in passages], list(cast.AUDITION_PASSAGES))
        self.assertIn("আমি কাল", passages[1]["text"])
        self.assertIn("তুমি তো", passages[2]["text"])
        self.assertNotIn("“", passages[0]["text"])
        speakers = {u["voice"] for u in job["units"]}
        self.assertEqual(speakers, set(cast.SPEAKERS["male"] + cast.SPEAKERS["female"]))
        for u in job["units"]:
            self.assertTrue(u["description"].startswith(u["voice"] + " speaks"))
            self.assertTrue(u["unit_key"].startswith(u["voice"].lower() + "-"))
        self.assertEqual(job["generation"], {"temperature": 0.91})
        rows = self.ledger_rows()
        self.assertEqual([(r["job_id"], r["state"]) for r in rows], [(job_id, "reserved")])
        # it narrates nothing: film-01 still needs its own narration job
        rec = Record.load(self.root)
        self.assertIsNone(cli._latest_job(rec, "narration", "film-01", imported=False))
        # same passages and voices again: refused; the modal request flow is the same as any job
        code, out = run("audition", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 2, out)
        self.assertIn("already built", out)
        # import: per-speaker listening set and stats
        folder = self.d / "download" / job_id
        folder.mkdir(parents=True)
        outputs = {}
        for i, u in enumerate(job["units"]):
            secs = round(len(u["text"]) / 12, 2)
            if u["unit_key"] == "tapan-female-line":
                secs = 0.3
            wav = folder / f"{u['unit_key']}.wav"
            self.tone(wav, secs, 200 + 10 * i)
            outputs[wav.name] = hashlib.sha256(wav.read_bytes()).hexdigest()
        zip_sha = hashlib.sha256((self.root / "jobs" / job_id / "inputs.zip").read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": job_id, "title": TITLE,
            "kind": "narration", "input_zip_sha256": zip_sha,
            "model": {"repo": "ai4bharat/indic-parler-tts", "revision": "x"}, "status": "COMPLETE",
            "packages": {"parler_tts": "0.2.2"}, "outputs": outputs}))
        with mock.patch.object(qc, "MIN_RATIO_CHARS", 10):
            code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 0.2)
        self.assertEqual(code, 0, out)
        self.assertIn("Audition listening set", out)
        self.assertIn("Tapan (male)", out)
        self.assertIn("SUSPECT_TRUNCATED: female-line", out)
        listen = self.root / "audition" / job_id
        for name in cast.SPEAKERS["male"] + cast.SPEAKERS["female"]:
            self.assertEqual(sorted(p.name for p in (listen / name).iterdir()),
                             sorted(f"{p}.wav" for p in cast.AUDITION_PASSAGES))
        info = json.loads((listen / "listening-set.json").read_text())
        self.assertEqual(info["stats"]["Tapan"]["suspect"][0]["passage"], "female-line")
        self.assertEqual(info["stats"]["Riya"]["suspect"], [])

    def test_audition_refuses_a_stale_cast(self):
        units = self.init_and_plan()
        doc = self.cast_doc(units, source_revision="r-old")
        self.write_cast(doc)
        code, out = run("audition", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 2, out)
        self.assertIn("does not fit the current source", out)

    def test_status_shows_the_cast(self):
        units = self.init_and_plan()
        code, out = run("status", "--root", self.root)
        self.assertIn("cast: none (single-voice", out)
        self.write_cast(self.cast_doc(units))
        code, out = run("status", "--root", self.root)
        self.assertIn("(next film narration): narrator Arnav (male, primary); characters রাম Arjun, "
                      "সীতা Riya; 2 segmented unit(s)", out)
        self.assertEqual(self.job()[0], 0)
        code, out = run("status", "--root", self.root)
        self.assertIn("narrator Arnav (male, primary); characters রাম Arjun, সীতা Riya; "
                      "2 segmented unit(s) of", out)
        self.assertNotIn("(next film narration)", out)


if __name__ == "__main__":
    unittest.main()
