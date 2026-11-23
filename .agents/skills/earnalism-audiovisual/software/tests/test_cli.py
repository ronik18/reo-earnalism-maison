"""Orchestrator CLI: every command prints the next owner action; gates exit non-zero."""
import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
import os
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from eav import cli, mix
from eav.record import Record
from eav.text import sentences

PARAS = [
    ("a1", "heading", "The Garden"),
    ("a2", "paragraph", "Every afternoon the children played in the garden. It was large and lovely."),
    ("a3", "paragraph", "The giant came back. He had been away for seven years."),
]
SOURCE = {
    "language": "en", "edition_id": "e-1", "revision_id": "r-1",
    "content_sha256": "c" * 64, "rights": {"reader": ["preview", "read"]},
    "public_domain_evidence": True, "state": "live", "assets": [], "timing_maps": [],
    "units": [
        {"unit_id": "u-1", "title": "One",
         "paragraphs": [{"anchor_id": a, "kind": k, "text": t} for a, k, t in PARAS[:2]]},
        {"unit_id": "u-2", "title": "Two",
         "paragraphs": [{"anchor_id": PARAS[2][0], "kind": PARAS[2][1], "text": PARAS[2][2]}]},
    ],
}
RATES = {"narration": {"s_per_step": 2.0, "units_per_hour": 5.0, "steps": 1,
                       "decode_s": 10, "export_s": 10}}


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue()


REEL = {"length": 60, "language": "en", "hook": "This giant built a wall against children.",
        "loop_close": "And the wall rose again around the garden."}
REEL["lines"] = ([REEL["hook"]] + ["The children played in the garden every single afternoon."] * 11
                 + [REEL["loop_close"]])


class RoundTwo:
    """Fix round 2: pinned ledger, no --month, spec docs, dry mastering, score provenance."""

    def fake_job(self, kind, target, files):
        """A built-and-imported job as the record sees it (no Colab)."""
        rec = Record.load(self.root)
        job_id = f"{kind.replace('_', '-')}-{len(rec.data['artifacts']):04d}"
        job_dir = self.root / "jobs" / job_id
        job_dir.mkdir(parents=True)
        for name in ("inputs.zip", "build-manifest.json", "nb.ipynb"):
            (job_dir / name).write_text("{}")
        rec.add_artifact("colab_job", job_dir / "nb.ipynb", {
            "job_id": job_id, "job_kind": kind, "forecast_units": 0.0, "month": "2026-11",
            "inputs_zip": f"jobs/{job_id}/inputs.zip", "manifest": f"jobs/{job_id}/build-manifest.json"})
        rec.event("cli", "job_target", {"job_id": job_id, "target": target, "kind": kind})
        out = self.root / kind / job_id
        out.mkdir(parents=True)
        files(rec, job_id, job_dir, out)
        rec.event("import", "accepted", {"job_id": job_id})
        return job_id

    def wav(self, path, seconds, freq=300):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=f={freq}:d={seconds}:r=24000", "-ac", "1", str(path)], check=True)

    def noise(self, path, seconds):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"anoisesrc=d={seconds}:c=pink:r=48000:a=0.2", "-ac", "2", str(path)], check=True)

    def film_ready(self):
        self.init_and_plan()
        plan = json.loads((self.root / "plan.json").read_text())
        scenes = plan["plan"]["films"][0]["scenes"]
        from eav.voice import voice_units

        def narr(rec, job_id, job_dir, out):
            for sc in scenes:
                for u in voice_units(sc, {"description": ""}, None, "en"):
                    self.wav(out / f"{u['unit_key']}.wav", 0.8)

        def stills(rec, job_id, job_dir, out):
            for i, sc in enumerate(scenes):
                Image.new("RGB", (320, 180), (60 * i, 90, 120)).save(out / f"{sc['scene_id']}-1.png")

        self.fake_job("narration", "film-01", narr)
        self.fake_job("stills", "film-01", stills)
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(self.d / "logo.png")
        Image.new("RGB", (320, 180), (0, 0, 0)).save(self.d / "end.png")

    # --- R11: pinned ledger, lifetime cap, no --month --------------------------------------
    def test_ledger_is_pinned_at_init(self):
        pinned = self.d / "shared" / "ledger.json"
        code, out = run("init", self.src, "--root", self.root, "--ledger", pinned)
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads((self.root / "record.json").read_text())["ledger"],
                         str(pinned.resolve()))
        self.assertEqual(run("plan", "--root", self.root)[0], 0)
        other = self.d / "other-ledger.json"
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--ledger", other)
        self.assertNotEqual(code, 0)
        self.assertIn("pinned", out)
        with mock.patch.dict(os.environ, {"EAV_LEDGER": str(other)}):
            code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertNotEqual(code, 0)
        self.assertIn("pinned", out)
        self.assertFalse(other.exists())
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(json.loads(pinned.read_text())), 1)

    def test_job_has_no_month_flag(self):
        self.init_and_plan()
        with self.assertRaises(SystemExit):
            run("job", "narration", "--root", self.root, "--rates", self.rates, "--month", "2026-10")

    def test_title_cap_counts_earlier_months(self):
        self.init_and_plan()
        ledger = Record.load(self.root).data["ledger"]
        from eav.budget import Ledger
        Ledger(Path(ledger)).reserve("selfish-giant", "2026-01", 59.99, "old-job")
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 3, out)
        self.assertIn("Budget exceeded", out)

    # --- item 1: reel_clips next action names the spec keys -----------------------------------
    def test_reel_clips_next_action_names_spec_keys(self):
        self.film_ready()
        rec = Record.load(self.root)
        (self.root / "film" / "film-01").mkdir(parents=True)
        (self.root / "film" / "film-01" / "film-01.mp4").write_bytes(b"x")
        rec.add_artifact("film", self.root / "film" / "film-01" / "film-01.mp4", {"target": "film-01"})
        script = self.d / "reel.json"
        script.write_text(json.dumps(REEL))
        self.assertEqual(run("reel", 1, "--root", self.root, "--script", script)[0], 0)
        self.fake_job("stills", "reel-1", lambda *a: None)
        nxt = cli.next_action(self.root)
        for key in ("job reel_clips", "art_dir", "prior_attempt_evidence", "shots", "id", "image",
                    "seed", "prompt", "reel-recipe.md"):
            self.assertIn(key, nxt, key)

    # --- item 4: --dry is mastered with the same gate ----------------------------------------
    def test_bundle_audio_dry_is_mastered_to_film_target(self):
        self.imported()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertEqual(code, 0, out)
        for mp3 in bundle.glob("*.mp3"):
            m = mix.measure(mp3)
            self.assertAlmostEqual(m["lufs"], -16.0, delta=1.0)
            self.assertLessEqual(m["true_peak"], -1.0)
        prov = json.loads((bundle / "timing.json").read_text())["provenance"]
        self.assertTrue(all(u["mastered_with"] == "eav.mix.master" for u in prov["units"].values()))

    def test_bundle_audio_dry_gate_miss_exits_with_gate_error(self):
        self.imported()
        bundle = self.d / "bundle"
        with mock.patch.object(cli.mix, "master",
                               side_effect=ValueError("master misses gate: {'true_peak': -0.2}")):
            code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertEqual(code, 5)
        self.assertIn("misses gate", out)
        self.assertFalse(bundle.exists())

    # --- item 5 ---------------------------------------------------------------------------------
    def test_bundle_audio_refuses_score_shorter_than_chapter(self):
        self.imported()
        scores = self.d / "short"
        scores.mkdir()
        for u in SOURCE["units"]:
            self.noise(scores / f"{u['unit_id']}.wav", 0.5)
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "bundle",
                        "--score-dir", scores)
        self.assertNotEqual(code, 0)
        self.assertIn("shorter", out)
        self.assertFalse((self.d / "bundle").exists())

    def test_unexpected_value_error_prints_next_not_traceback(self):
        def boom(args):
            raise ValueError("bad value from a helper")
        with mock.patch.dict(cli.COMMANDS, {"status": boom}):
            code, out = run("status", "--root", self.root)
        self.assertEqual(code, 2)
        self.assertIn("STOP: bad value from a helper", out)
        self.assertIn("Next:", out)
        self.assertNotIn("Traceback", out)

    def test_film_records_score_provenance(self):
        self.film_ready()
        bed = self.d / "bed.wav"
        self.noise(bed, 30)
        base = ("film", "--root", self.root, "--logo", self.d / "logo.png",
                "--end-card", self.d / "end.png", "--score", bed)
        code, out = run(*base)
        self.assertNotEqual(code, 0)
        self.assertIn("--score-route", out)
        short = self.d / "short.wav"
        self.noise(short, 1)
        code, out = run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                        self.d / "end.png", "--score", short, "--score-route", "vcsl")
        self.assertNotEqual(code, 0)
        self.assertIn("shorter", out)
        code, out = run(*base, "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        film_art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(film_art["meta"]["score"], {
            "route": "vcsl", "sha256": hashlib.sha256(bed.read_bytes()).hexdigest()})

    def test_reel_records_narration_and_score_provenance(self):
        self.init_and_plan()
        script = self.d / "reel.json"
        script.write_text(json.dumps(REEL))
        self.assertEqual(run("reel", 1, "--root", self.root, "--script", script)[0], 0)
        from eav.voice import voice_units
        units = voice_units(cli._reel_scene(REEL, 1), {"description": ""}, None, "en")

        def narr(rec, job_id, job_dir, out):
            for u in units:
                self.wav(out / f"{u['unit_key']}.wav", 3.0)

        def clips(rec, job_id, job_dir, out):
            ids = [f"shot-{i:02d}" for i in range(10)]
            (job_dir / "job.json").write_text(json.dumps({"scenes": [{"id": i} for i in ids]}))
            for k, i in enumerate(ids):
                clip = out / f"{i}.mp4"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                                f"color=c=0x{20 * k:02x}4060:s=180x320:d=6:r=24", "-pix_fmt", "yuv420p",
                                str(clip)], check=True)
                rec.add_artifact("reel_clip", clip, {"job_id": job_id, "scene": i})

        narr_id = self.fake_job("narration", "reel-1", narr)
        self.fake_job("reel_clips", "reel-1", clips)
        bed = self.d / "bed.wav"
        self.noise(bed, 70)
        code, out = run("reel", 1, "--root", self.root, "--score", bed, "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        rec = Record.load(self.root)
        prov = [a for a in rec.data["artifacts"] if a["kind"] == "narration_provenance"]
        self.assertEqual(len(prov), 1)
        self.assertEqual(json.loads((self.root / prov[0]["path"]).read_text())["narration_job_id"], narr_id)
        reel_art = [a for a in rec.data["artifacts"] if a["kind"] == "reel"][-1]
        self.assertEqual(reel_art["meta"]["score"]["sha256"], hashlib.sha256(bed.read_bytes()).hexdigest())
        self.assertEqual(reel_art["meta"]["score"]["route"], "vcsl")


class CliTests(RoundTwo, unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / "selfish-giant"
        self.ledger = self.d / "titles" / "allowance-ledger.json"
        self.src = self.d / "selfish-giant.json"
        self.src.write_text(json.dumps(SOURCE), encoding="utf-8")
        self.rates = self.d / "rates.json"
        self.rates.write_text(json.dumps(RATES), encoding="utf-8")

    def init_and_plan(self):
        self.assertEqual(run("init", self.src, "--root", self.root)[0], 0)
        self.assertEqual(run("plan", "--root", self.root)[0], 0)

    def test_cli_status_on_empty_root_says_init(self):
        code, out = run("status", "--root", self.root)
        self.assertEqual(code, 0)
        self.assertIn("python3 -m eav.cli init", out)

    def test_cli_status_on_fresh_root_says_next_step_is_plan(self):
        code, out = run("init", self.src, "--root", self.root)
        self.assertEqual(code, 0, out)
        code, out = run("status", "--root", self.root)
        self.assertEqual(code, 0)
        self.assertIn("Next:", out)
        self.assertIn("python3 -m eav.cli plan --root", out)

    def test_init_refuses_source_without_public_domain_clearance(self):
        self.src.write_text(json.dumps({**SOURCE, "public_domain_evidence": False}), encoding="utf-8")
        code, out = run("init", self.src, "--root", self.root)
        self.assertNotEqual(code, 0)
        self.assertIn("STOP", out)
        self.assertIn("public-domain", out)
        self.assertFalse((self.root / "record.json").exists())

    def test_cli_job_over_budget_exits_nonzero_with_message(self):
        self.init_and_plan()
        self.rates.write_text(json.dumps(
            {"narration": {**RATES["narration"], "s_per_step": 100000.0}}), encoding="utf-8")
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertNotEqual(code, 0)
        self.assertIn("Budget exceeded", out)
        self.assertIn("Next:", out)
        self.assertFalse(self.ledger.exists() and json.loads(self.ledger.read_text()))
        self.assertFalse((self.root / "jobs").exists() and any((self.root / "jobs").iterdir()))

    def test_job_needs_measured_rates(self):
        self.init_and_plan()
        self.rates.write_text(json.dumps({"narration": {"s_per_step": 2.0,
                                                        "units_per_hour": 5.0}}), encoding="utf-8")
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertNotEqual(code, 0)
        self.assertIn("measured", out)

    def test_plan_and_narration_job_carry_roster_temperature(self):
        job_id, job_dir = self.build_narration()
        plan = json.loads((self.root / "plan.json").read_text())
        self.assertEqual(plan["voice"]["preset_key"], "en_tisha::story")
        self.assertEqual(plan["voice"]["temperature"], 0.91)
        with zipfile.ZipFile(job_dir / "inputs.zip") as z:
            self.assertEqual(json.loads(z.read("job.json"))["generation"], {"temperature": 0.91})

    def build_narration(self):
        self.init_and_plan()
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)
        job_dir = next((self.root / "jobs").iterdir())
        return job_dir.name, job_dir

    def test_status_after_job_tells_owner_to_run_colab_then_import(self):
        job_id, _ = self.build_narration()
        code, out = run("status", "--root", self.root)
        self.assertEqual(code, 0)
        self.assertIn("RUN = True", out)
        self.assertIn(f"python3 -m eav.cli import {job_id} --root", out)
        self.assertIn("--units", out)

    def fake_colab_outputs(self, job_id, job_dir):
        """What the owner downloads from Drive: one WAV per unit plus manifest.json."""
        folder = self.d / "download" / job_id
        folder.mkdir(parents=True)
        with zipfile.ZipFile(job_dir / "inputs.zip") as z:
            units = json.loads(z.read("job.json"))["units"]
        outputs = {}
        for i, u in enumerate(units):
            wav = folder / f"{u['unit_key']}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"sine=f={200 + 20 * i}:d={0.6 + 0.1 * i}:r=24000", "-ac", "1",
                            str(wav)], check=True)
            outputs[wav.name] = hashlib.sha256(wav.read_bytes()).hexdigest()
        zip_sha = hashlib.sha256((job_dir / "inputs.zip").read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": job_id, "title": "selfish-giant",
            "kind": "narration", "input_zip_sha256": zip_sha,
            "model": {"repo": "ai4bharat/indic-parler-tts", "revision": "x"},
            "outputs": outputs}), encoding="utf-8")
        return folder, units

    def test_import_held_exits_nonzero_and_keeps_waiting(self):
        job_id, job_dir = self.build_narration()
        folder, _ = self.fake_colab_outputs(job_id, job_dir)
        next(folder.glob("*.wav")).write_bytes(b"tampered")
        code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 1.5)
        self.assertNotEqual(code, 0)
        self.assertIn("Import held", out)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"import {job_id}", out)

    def imported(self):
        job_id, job_dir = self.build_narration()
        folder, units = self.fake_colab_outputs(job_id, job_dir)
        code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 1.5)
        self.assertEqual(code, 0, out)
        return job_id, folder, units

    def scores(self):
        d = self.d / "scores"
        d.mkdir()
        for u in SOURCE["units"]:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "anoisesrc=d=8:c=pink:r=48000:a=0.2", "-ac", "2",
                            str(d / f"{u['unit_id']}.wav")], check=True)
        return d

    def test_bundle_audio_refuses_without_score_unless_dry(self):
        self.imported()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle)
        self.assertNotEqual(code, 0)
        self.assertIn("score", out)
        self.assertIn("--dry", out)
        self.assertFalse(bundle.exists())
        self.assertFalse((self.root / "maison").exists())

    def test_bundle_audio_refuses_missing_chapter_score(self):
        self.imported()
        scores = self.scores()
        (scores / "u-2.wav").unlink()
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "bundle",
                        "--score-dir", scores)
        self.assertNotEqual(code, 0)
        self.assertIn("u-2", out)
        self.assertFalse((self.d / "bundle").exists())

    def test_bundle_audio_dry_is_recorded(self):
        self.imported()
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "bundle", "--dry")
        self.assertEqual(code, 0, out)
        timing = json.loads((self.d / "bundle" / "timing.json").read_text())
        self.assertTrue(all(u["mastered_with"] == "eav.mix.master"
                            for u in timing["provenance"]["units"].values()))
        ev = json.loads((self.root / "maison" / "audiovisual-clearance-evidence.draft.json").read_text())
        self.assertIs(ev["dry_narration"], True)
        self.assertIsNone(ev["music"])

    def test_bundle_audio_before_narration_import_stops_and_writes_nothing(self):
        self.build_narration()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertNotEqual(code, 0)
        self.assertIn("narration not imported", out)
        self.assertFalse(bundle.exists())
        self.assertFalse((self.root / "maison").exists())

    def test_bundle_audio_writes_measured_timing_with_provenance(self):
        job_id, folder, units = self.imported()
        scores = self.scores()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--score-dir", scores)
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in bundle.iterdir()),
                         ["timing.json", "unit-001.mp3", "unit-002.mp3"])
        timing = json.loads((bundle / "timing.json").read_text())
        self.assertEqual([r["unit_id"] for r in timing["units"]], ["u-1", "u-2"])
        for row in timing["units"]:
            self.assertEqual(set(row), {"unit_id", "mp3", "segments"})
            probe = json.loads(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=bit_rate",
                 "-of", "json", str(bundle / row["mp3"])], check=True, capture_output=True,
                text=True).stdout)
            self.assertEqual(probe["streams"][0]["bit_rate"], "96000")
            dur_ms = round(float(probe["format"]["duration"]) * 1000)
            last = 0
            for seg in row["segments"]:
                self.assertEqual(seg["start_offset_chars"], 0)
                self.assertGreaterEqual(seg["start_ms"], last)
                self.assertGreater(seg["end_ms"], seg["start_ms"])
                self.assertLessEqual(seg["end_ms"], dur_ms)
                last = seg["end_ms"]
        texts = {a: t for a, _, t in PARAS}
        segs = [s for r in timing["units"] for s in r["segments"]]
        self.assertEqual([s["anchor_id"] for s in segs], ["a1", "a2", "a3"])
        for s in segs:
            self.assertEqual(s["end_offset_chars"], len(texts[s["anchor_id"]]))
        # a2 = two sentences of 0.7 s and 0.8 s with a 400 ms pause: measured, not estimated
        a2 = segs[1]
        self.assertAlmostEqual((a2["end_ms"] - a2["start_ms"]) / 1000,
                               0.7 + 0.4 + 0.8, delta=0.05)
        prov = timing["provenance"]
        self.assertEqual(prov["method"], "eav.film.narration_track")
        self.assertEqual(prov["measured_with"], "ffprobe")
        self.assertEqual(prov["narration_job_id"], job_id)
        wavs = {u["unit_key"]: hashlib.sha256((folder / f"{u['unit_key']}.wav").read_bytes()
                                              ).hexdigest() for u in units}
        self.assertEqual({k: v for r in prov["units"].values() for k, v in r["wav_sha256"].items()},
                         wavs)
        evidence = json.loads((self.root / "maison" / "audiovisual-clearance-evidence.draft.json")
                              .read_text())
        self.assertEqual(evidence["schema"], "earnalism.audiovisual-clearance-evidence.v1")
        self.assertEqual(evidence["source_content_sha256"], SOURCE["content_sha256"])
        self.assertEqual(evidence["formats"], ["reader", "audio"])
        self.assertEqual(sorted(evidence["audio_sha256"]), sorted(
            hashlib.sha256((bundle / r["mp3"]).read_bytes()).hexdigest() for r in timing["units"]))
        self.assertEqual(evidence["territories"], [])
        self.assertEqual(evidence["owner_approval"], None)
        self.assertIn("DRAFT", evidence["status"])
        self.assertIn("attach_audiovisual_audio stage", out)
        # R10: scored by default, mastered to the film target
        for unit_id, row in prov["units"].items():
            self.assertEqual(row["mastered_with"], "eav.mix.duck_and_master")
            self.assertEqual(row["score_sha256"], hashlib.sha256(
                (scores / f"{unit_id}.wav").read_bytes()).hexdigest())
        for row in timing["units"]:
            lufs = mix.measure(bundle / row["mp3"])["lufs"]
            self.assertAlmostEqual(lufs, -16.0, delta=1.0)
        self.assertIs(evidence["dry_narration"], False)
        self.assertEqual(sorted(evidence["music"]["score_sha256"].values()), sorted(
            hashlib.sha256((scores / f"{u['unit_id']}.wav").read_bytes()).hexdigest()
            for u in SOURCE["units"]))


class SentenceSanity(unittest.TestCase):
    def test_fixture_a2_has_two_sentences(self):
        self.assertEqual(len(sentences(PARAS[1][2])), 2)


if __name__ == "__main__":
    unittest.main()
