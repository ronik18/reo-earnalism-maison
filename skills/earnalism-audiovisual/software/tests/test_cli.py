"""Orchestrator CLI: every command prints the next owner action; gates exit non-zero."""
import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
import os
import shutil
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


def speech_seconds(text: str) -> float:
    """A fake unit WAV's length at an even 20 characters/second, so none is suspect_truncated."""
    return round(len(text) / 20, 2)


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
                    self.wav(out / f"{u['unit_key']}.wav", speech_seconds(u["text"]))

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
                         "../../shared/ledger.json")
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
        self.assertEqual(json.loads(pinned.read_text())[0]["edition_id"], "e-1")

    def test_moved_title_root_still_sees_its_ledger(self):
        """R17: the pin is relative to the record root, so a checkout elsewhere keeps the caps."""
        self.init_and_plan()
        self.assertEqual(Record.load(self.root).data["ledger"], "../allowance-ledger.json")
        from eav.budget import Ledger
        Ledger(self.ledger).reserve("selfish-giant", "2026-01", 59.99, "old-job")
        moved = self.d / "owner-mac" / "titles"
        shutil.copytree(self.d / "titles", moved)
        shutil.rmtree(self.d / "titles")
        code, out = run("job", "narration", "--root", moved / "selfish-giant", "--rates", self.rates)
        self.assertEqual(code, 3, out)
        self.assertIn("Budget exceeded", out)
        code, out = run("status", "--root", moved / "selfish-giant")
        self.assertIn("59.99 CU spent/reserved for this title", out)
        code, out = run("status", "--root", moved / "selfish-giant", "--ledger", moved / "allowance-ledger.json")
        self.assertEqual(code, 0, out)

    def test_absolute_ledger_pin_is_refused(self):
        self.init_and_plan()
        data = json.loads((self.root / "record.json").read_text())
        data["ledger"] = str(self.ledger.resolve())
        (self.root / "record.json").write_text(json.dumps(data))
        for argv in (("status", "--root", self.root),
                     ("job", "narration", "--root", self.root, "--rates", self.rates)):
            code, out = run(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn("absolute", out)
            self.assertIn("Next:", out)
            self.assertIn("init", out)

    def test_supersede_releases_reservation_and_is_never_next(self):
        """R19: a never-run job can be superseded; it is shown as such and never offered."""
        job_id, _ = self.build_narration()
        code, out = run("supersede", job_id, "--root", self.root, "--reason", "replaced before any run")
        self.assertEqual(code, 0, out)
        entry = next(e for e in json.loads(self.ledger.read_text()) if e["job_id"] == job_id)
        self.assertEqual((entry["state"], entry["units"]), ("settled", 0))
        rec = Record.load(self.root)
        ev = [e for e in rec.data["events"] if e["stage"] == "job" and e["result"] == "superseded"]
        self.assertEqual(ev[-1]["detail"], {"job_id": job_id, "reason": "replaced before any run"})
        nxt = cli.next_action(self.root)
        self.assertNotIn(job_id, nxt)
        self.assertIn("job narration", nxt)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{job_id} narration film-01: superseded", out)
        self.assertNotIn("waiting for Colab", out)
        code, out = run("supersede", job_id, "--root", self.root, "--reason", "again")
        self.assertNotEqual(code, 0)

    # --- R23: a job that ran but cannot be imported settles its ACTUAL units --------------------
    def test_close_settles_actual_units_and_is_never_next(self):
        job_id, job_dir = self.build_narration()
        code, out = run("close", job_id, "--root", self.root, "--units", 1.2,
                        "--reason", "Colab crashed before the manifest cell")
        self.assertEqual(code, 0, out)
        entry = next(e for e in json.loads(self.ledger.read_text()) if e["job_id"] == job_id)
        self.assertEqual((entry["state"], entry["units"]), ("settled", 1.2))
        ev = [e for e in Record.load(self.root).data["events"] if e["result"] == "closed"][-1]
        self.assertEqual(ev["detail"], {"job_id": job_id, "units": 1.2, "ran": True, "imported": False,
                                        "reason": "Colab crashed before the manifest cell"})
        self.assertFalse(any(e["result"] == "superseded" for e in Record.load(self.root).data["events"]))
        nxt = cli.next_action(self.root)
        self.assertNotIn(job_id, nxt)
        self.assertIn("job narration", nxt)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{job_id} narration film-01: closed (ran, not imported; 1.20 CU settled)", out)
        folder, _ = self.fake_colab_outputs(job_id, job_dir)
        for argv in (("import", job_id, "--root", self.root, "--from", folder, "--units", 1),
                     ("close", job_id, "--root", self.root, "--units", 1, "--reason", "again"),
                     ("supersede", job_id, "--root", self.root, "--reason", "never ran")):
            code, out = run(*argv)
            self.assertNotEqual(code, 0, argv)
        self.assertEqual(next(e for e in json.loads(self.ledger.read_text())
                              if e["job_id"] == job_id)["units"], 1.2)

    def test_close_refuses_imported_job_and_bad_units(self):
        job_id, folder, _ = self.imported()
        code, out = run("close", job_id, "--root", self.root, "--units", 1, "--reason", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("imported", out)
        job_id2 = self.build_second_narration()
        for bad in (-1, "nan"):
            code, out = run("close", job_id2, "--root", self.root, "--units", bad, "--reason", "x")
            self.assertNotEqual(code, 0, bad)
        code, out = run("close", job_id2, "--root", self.root, "--reason", "no units")  # Colab job
        self.assertNotEqual(code, 0)
        self.assertIn("--units is required", out)

    def build_second_narration(self):
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates, "--job-id", "narr-two")
        self.assertEqual(code, 0, out)
        return "narr-two"

    def test_supersede_interrupted_before_settle_resumes(self):
        """R23: the record event is written first (pending), so a failure leaves a resumable state."""
        job_id, job_dir = self.build_narration()
        from eav.budget import Ledger
        with mock.patch.object(Ledger, "settle", side_effect=OSError("disk full")):
            code, out = run("supersede", job_id, "--root", self.root, "--reason", "replaced")
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(self.ledger.read_text())[0]["state"], "reserved")
        self.assertIn(f"supersede|close {job_id}", cli.next_action(self.root))
        folder, _ = self.fake_colab_outputs(job_id, job_dir)
        code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 1)
        self.assertNotEqual(code, 0)  # an interrupted supersede is never imported
        code, out = run("supersede", job_id, "--root", self.root, "--reason", "replaced")
        self.assertEqual(code, 0, out)
        entry = json.loads(self.ledger.read_text())[0]
        self.assertEqual((entry["state"], entry["units"]), ("settled", 0))
        self.assertIn("job narration", cli.next_action(self.root))

    def test_supersede_interrupted_after_settle_resumes(self):
        job_id, _ = self.build_narration()
        real = Record.event

        def flaky(rec, stage, result, detail):
            if result == "superseded":
                raise OSError("crash")
            return real(rec, stage, result, detail)
        with mock.patch.object(Record, "event", flaky):
            code, out = run("supersede", job_id, "--root", self.root, "--reason", "replaced")
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(self.ledger.read_text())[0]["state"], "settled")
        code, out = run("supersede", job_id, "--root", self.root, "--reason", "replaced")
        self.assertEqual(code, 0, out)
        rec = Record.load(self.root)
        self.assertEqual(len([e for e in rec.data["events"] if e["result"] == "superseded"]), 1)

    def test_close_interrupted_resumes_with_the_recorded_units(self):
        job_id, _ = self.build_narration()
        from eav.budget import Ledger
        with mock.patch.object(Ledger, "settle", side_effect=OSError("disk full")):
            run("close", job_id, "--root", self.root, "--units", 0.7, "--reason", "lost download")
        code, out = run("close", job_id, "--root", self.root, "--units", 0.9, "--reason", "lost download")
        self.assertNotEqual(code, 0)  # the recorded units win; nothing is re-decided on resume
        self.assertIn("0.7", out)
        code, out = run("close", job_id, "--root", self.root, "--units", 0.7, "--reason", "lost download")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(self.ledger.read_text())[0]["units"], 0.7)

    def test_supersede_refuses_imported_job(self):
        job_id, folder, _ = self.imported()
        before = self.ledger.read_text()
        code, out = run("supersede", job_id, "--root", self.root, "--reason", "oops")
        self.assertNotEqual(code, 0)
        self.assertIn("imported", out)
        self.assertEqual(self.ledger.read_text(), before)

    def test_supersede_needs_a_reason(self):
        job_id, _ = self.build_narration()
        with self.assertRaises(SystemExit):
            run("supersede", job_id, "--root", self.root)

    def test_job_has_no_month_flag(self):
        self.init_and_plan()
        with self.assertRaises(SystemExit):
            run("job", "narration", "--root", self.root, "--rates", self.rates, "--month", "2026-10")

    def test_title_cap_counts_earlier_months(self):
        self.init_and_plan()
        ledger = self.root / Record.load(self.root).data["ledger"]
        from eav.budget import Ledger
        Ledger(ledger).reserve("selfish-giant", "2026-01", 59.99, "old-job")
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 3, out)
        self.assertIn("Budget exceeded", out)

    # --- R20: reel shots come from measured narration; clips come in batches -------------------
    CLIP = 121 / 24

    def reel_narrated(self, unit_seconds=4.25, script=REEL):
        """Script reel 1 and fake its imported narration (13 lines -> 13 units, 12 x 400 ms)."""
        if not (self.root / "plan.json").exists():
            self.film_done()
        path = self.d / "reel.json"
        path.write_text(json.dumps(script))
        code, out = run("reel", 1, "--root", self.root, "--script", path)
        self.assertEqual(code, 0, out)
        from eav.voice import voice_units
        units = voice_units(cli._reel_scene(script, 1), {"description": ""}, None, "en")

        def narr(rec, job_id, job_dir, out):
            for u in units:
                self.wav(out / f"{u['unit_key']}.wav", unit_seconds)
        return self.fake_job("narration", "reel-1", narr), units

    def reel_stills(self, shots):
        def stills(rec, job_id, job_dir, out):
            for k, sh in enumerate(shots):
                Image.new("RGB", (64, 112), (10 * k, 80, 120)).save(out / f"{sh['id']}.png")
        return self.fake_job("stills", "reel-1", stills)

    def clip_batch(self, ids):
        def clips(rec, job_id, job_dir, out):
            (job_dir / "job.json").write_text(json.dumps({"scenes": [{"id": i} for i in ids]}))
            for k, i in enumerate(ids):
                clip = out / f"{i}.mp4"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                                f"color=c=0x{20 * k:02x}4060:s=180x320:d={self.CLIP:.6f}:r=24",
                                "-pix_fmt", "yuv420p", str(clip)], check=True)
                rec.add_artifact("reel_clip", clip, {"job_id": job_id, "scene": i})
        return self.fake_job("reel_clips", "reel-1", clips)

    def test_plan_shots_from_measured_narration(self):
        self.reel_narrated(4.25)  # 13 x 4.25 + 12 x 0.4 = 60.05 s
        code, out = run("reel", 1, "--root", self.root, "--plan-shots")
        self.assertEqual(code, 0, out)
        shots = json.loads((self.root / "reels" / "reel-1" / "shots.json").read_text())
        self.assertEqual(len(shots), 12)  # ceil(60.05 / 5.0417)
        self.assertTrue(all(abs(x["seconds"] - self.CLIP) < 1e-3 for x in shots[:-1]))
        self.assertGreaterEqual(sum(x["seconds"] for x in shots), 60.05)
        self.assertEqual(shots[0]["line"], REEL["hook"])
        ev = [e for e in Record.load(self.root).data["events"] if e["result"] == "shots_planned"][-1]
        self.assertAlmostEqual(ev["detail"]["narration_seconds"], 60.05, delta=0.05)
        code, out = run("reel", 1, "--root", self.root, "--plan-shots")
        self.assertNotEqual(code, 0)  # planned once; re-planning would desynchronise stills/clips

    def film_done(self):
        """Film 1 imported and assembled (faked), so next_action moves on to the reels."""
        self.film_ready()
        rec = Record.load(self.root)
        (self.root / "film" / "film-01").mkdir(parents=True)
        (self.root / "film" / "film-01" / "film-01.mp4").write_bytes(b"x")
        rec.add_artifact("film", self.root / "film" / "film-01" / "film-01.mp4", {"target": "film-01"})

    def test_reel_script_no_longer_plans_shots(self):
        self.film_done()
        path = self.d / "reel.json"
        path.write_text(json.dumps(REEL))
        code, out = run("reel", 1, "--root", self.root, "--script", path)
        self.assertEqual(code, 0, out)
        self.assertFalse((self.root / "reels" / "reel-1" / "shots.json").exists())
        nxt = cli.next_action(self.root)
        self.assertIn("job narration", nxt)
        self.assertIn("--reel 1", nxt)

    def test_plan_shots_refuses_narration_that_does_not_fit(self):
        self.reel_narrated(5.5)  # 13 x 5.5 + 4.8 = 76.3 s for a 60 s reel
        code, out = run("reel", 1, "--root", self.root, "--plan-shots")
        self.assertEqual(code, 5, out)
        self.assertIn("measured narration", out)
        self.assertFalse((self.root / "reels" / "reel-1" / "shots.json").exists())
        self.assertIn("--script", cli.next_action(self.root))
        # a misfit narration frees the script for a rewrite; the new script needs new narration
        short = dict(REEL, lines=[REEL["hook"]] + REEL["lines"][1:11] + [REEL["loop_close"]])
        path = self.d / "short.json"
        path.write_text(json.dumps(short))
        code, out = run("reel", 1, "--root", self.root, "--script", path)
        self.assertEqual(code, 0, out)
        self.assertIn("job narration", cli.next_action(self.root))

    def test_reel_script_refused_once_its_narration_is_built(self):
        self.reel_narrated(4.25)
        path = self.d / "reel.json"
        code, out = run("reel", 1, "--root", self.root, "--script", path)
        self.assertNotEqual(code, 0)
        self.assertIn("narration was already built", out)

    def test_plan_shots_needs_imported_narration(self):
        self.init_and_plan()
        path = self.d / "reel.json"
        path.write_text(json.dumps(REEL))
        run("reel", 1, "--root", self.root, "--script", path)
        code, out = run("reel", 1, "--root", self.root, "--plan-shots")
        self.assertNotEqual(code, 0)
        self.assertIn("narration", out)

    def planned_reel(self):
        self.reel_narrated(4.25)
        self.assertEqual(run("reel", 1, "--root", self.root, "--plan-shots")[0], 0)
        shots = json.loads((self.root / "reels" / "reel-1" / "shots.json").read_text())
        stills = self.reel_stills(shots)
        return shots, stills

    def clips_spec(self, stills_job, ids, name="clips.json"):
        spec = self.d / name
        spec.write_text(json.dumps({
            "art_dir": str(self.root / "stills" / stills_job),
            "prior_attempt_evidence": {"scope": "test only"},
            "shots": [{"id": i, "image": f"{i}.png", "seed": 40 + k,
                       "prompt": "The lamp flame flickers; camera locked-off."}
                      for k, i in enumerate(ids)]}))
        return spec

    def reel_rates(self):
        self.rates.write_text(json.dumps({**RATES, "reel_clips": {
            "clip_s": 500.0, "units_per_hour": 1.94, "steps": 24}}), encoding="utf-8")

    def test_reel_clips_next_action_names_uncovered_shots_and_spec_keys(self):
        shots, stills = self.planned_reel()
        nxt = cli.next_action(self.root)
        for key in ("job reel_clips", "art_dir", "prior_attempt_evidence", "shots", "id", "image",
                    "seed", "prompt", "reel-recipe.md", "shot-01", "shot-05", "at most 5"):
            self.assertIn(key, nxt, key)
        self.assertNotIn("shot-06", nxt)
        self.clip_batch([x["id"] for x in shots[:5]])
        nxt = cli.next_action(self.root)
        self.assertIn("shot-06", nxt)
        self.assertNotIn("shot-05", nxt)

    def test_reel_clips_batch_must_name_uncovered_planned_shots(self):
        shots, stills = self.planned_reel()
        self.reel_rates()
        ids = [x["id"] for x in shots]
        base = ("job", "reel_clips", "--reel", 1, "--root", self.root, "--rates", self.rates, "--spec")
        code, out = run(*base, self.clips_spec(stills, ["shot-99"], "bad.json"))
        self.assertNotEqual(code, 0)
        self.assertIn("not planned", out)
        code, out = run(*base, self.clips_spec(stills, ids[:6], "six.json"))
        self.assertNotEqual(code, 0)
        self.assertIn("at most 5", out)
        code, out = run(*base, self.clips_spec(stills, ids[:5], "b1.json"), "--job-id", "reel-clips-b1")
        self.assertEqual(code, 0, out)
        code, out = run(*base, self.clips_spec(stills, ids[4:9], "b2.json"))
        self.assertNotEqual(code, 0)
        self.assertIn("shot-05", out)
        self.assertIn("already", out)
        entry = [e for e in json.loads(self.ledger.read_text()) if e["job_id"] == "reel-clips-b1"][0]
        self.assertAlmostEqual(entry["units"], 5 * 500 * 1.15 / 3600 * 1.94)

    def test_reel_clips_owner_steps_follow_the_wan_notebook(self):
        """R22: the real Wan flags and the owner-written authority file, never RUN = True."""
        shots, stills = self.planned_reel()
        self.reel_rates()
        code, out = run("job", "reel_clips", "--reel", 1, "--root", self.root, "--rates", self.rates,
                        "--spec", self.clips_spec(stills, [x["id"] for x in shots[:5]]),
                        "--job-id", "reel-clips-b1")
        self.assertEqual(code, 0, out)
        nxt = cli.next_action(self.root)
        job_sha = hashlib.sha256((self.root / "jobs" / "reel-clips-b1" / "job.json").read_bytes()).hexdigest()
        for key in ("RUN_BATCH", "VERIFY_INPUTS", "BEGIN_ALLOCATION", "SETUP_BATCH", "GENERATE_BATCH",
                    "EXPORT_AND_DOWNLOAD", "LOCAL_IMPORT_VERIFIED", "DISCONNECT_RUNTIME",
                    "/content/wan22-batch-authority.json", "earnalism.wan22-batch-authority.v1",
                    "owner_authorized", job_sha, "evidence_ref", "observed_units_per_hour",
                    "approved_compute_units", "allocation_started_at", "free_runtime_confirmed",
                    "2700", "never writes", "archive_sha256", "import reel-clips-b1", "close reel-clips-b1"):
            self.assertIn(key, nxt, key)
        self.assertNotIn("RUN = True", nxt)

    def test_reel_assembles_from_several_clip_batches(self):
        shots, stills = self.planned_reel()
        ids = [x["id"] for x in shots]
        narr_id = [j["job_id"] for j in cli._jobs(Record.load(self.root)) if j["kind"] == "narration"][-1]
        batches = [self.clip_batch(ids[i:i + 5]) for i in range(0, len(ids), 5)]
        self.assertEqual(len(batches), 3)
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
        self.assertEqual(reel_art["meta"]["clip_jobs"], batches)
        self.assertEqual(reel_art["meta"]["clips"], 12)
        self.assertAlmostEqual(reel_art["meta"]["seconds"], sum(x["seconds"] for x in shots), delta=0.05)
        self.assertGreaterEqual(reel_art["meta"]["seconds"], 60.05)

    # --- R27: assembly and clips are bound to the narration the shots were planned from -------
    def test_new_reel_narration_after_shots_planned_is_refused(self):
        self.planned_reel()
        code, out = run("job", "narration", "--reel", 1, "--root", self.root, "--rates", self.rates)
        self.assertNotEqual(code, 0)
        for key in ("planned", "supersede", "close", "--plan-shots"):
            self.assertIn(key, out, key)
        self.assertEqual(len([j for j in cli._jobs(Record.load(self.root)) if j["target"] == "reel-1"
                              and j["kind"] == "narration"]), 1)

    def test_reel_refuses_narration_other_than_the_planned_one(self):
        shots, stills = self.planned_reel()
        ids = [x["id"] for x in shots]
        for i in range(0, len(ids), 5):
            self.clip_batch(ids[i:i + 5])
        from eav.voice import voice_units
        units = voice_units(cli._reel_scene(REEL, 1), {"description": ""}, None, "en")

        def narr(rec, job_id, job_dir, out):  # a newer reel narration slipped in past the gate
            for u in units:
                self.wav(out / f"{u['unit_key']}.wav", 4.3)
        newer = self.fake_job("narration", "reel-1", narr)
        code, out = run("reel", 1, "--root", self.root)
        self.assertNotEqual(code, 0)
        self.assertIn(newer, out)
        self.assertIn("planned", out)
        self.assertFalse(any(a["kind"] == "reel" for a in Record.load(self.root).data["artifacts"]))

    def test_reel_clips_refused_when_shots_json_is_not_the_planned_one(self):
        shots, stills = self.planned_reel()
        self.reel_rates()
        path = self.root / "reels" / "reel-1" / "shots.json"
        path.write_text(json.dumps(shots[:3]))
        code, out = run("job", "reel_clips", "--reel", 1, "--root", self.root, "--rates", self.rates,
                        "--spec", self.clips_spec(stills, [x["id"] for x in shots[:3]]))
        self.assertNotEqual(code, 0)
        self.assertIn("shots.json", out)
        self.assertFalse(self.ledger.exists())  # nothing reserved

    def test_revoicing_a_reel_retires_its_plan_first(self):
        shots, stills = self.planned_reel()
        self.reel_rates()
        code, out = run("job", "reel_clips", "--reel", 1, "--root", self.root, "--rates", self.rates,
                        "--spec", self.clips_spec(stills, [x["id"] for x in shots[:5]]), "--job-id", "rc-b1")
        self.assertEqual(code, 0, out)
        path = self.d / "reel.json"
        code, out = run("reel", 1, "--root", self.root, "--script", path)
        self.assertNotEqual(code, 0)  # an active batch of the plan blocks re-voicing
        self.assertIn("rc-b1", out)
        self.assertEqual(run("supersede", "rc-b1", "--root", self.root, "--reason", "re-voice")[0], 0)
        code, out = run("reel", 1, "--root", self.root, "--script", path)
        self.assertEqual(code, 0, out)
        code, out = run("job", "narration", "--reel", 1, "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)

    def test_reel_refuses_until_every_planned_shot_has_a_clip(self):
        shots, stills = self.planned_reel()
        self.clip_batch([x["id"] for x in shots[:5]])
        code, out = run("reel", 1, "--root", self.root)
        self.assertNotEqual(code, 0)
        self.assertIn("shot-06", out)

    # --- item 4: --dry is mastered with the same gate ----------------------------------------
    def test_bundle_audio_dry_is_mastered_to_film_target(self):
        self.reviewed()
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
        self.reviewed()
        bundle = self.d / "bundle"
        with mock.patch.object(cli.mix, "master",
                               side_effect=ValueError("master misses gate: {'true_peak': -0.2}")):
            code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertEqual(code, 5)
        self.assertIn("misses gate", out)
        self.assertFalse(bundle.exists())

    # --- item 5 ---------------------------------------------------------------------------------
    def test_bundle_audio_refuses_score_shorter_than_chapter(self):
        self.reviewed()
        scores = self.d / "short"
        scores.mkdir()
        for u in SOURCE["units"]:
            self.noise(scores / f"{u['unit_id']}.wav", 0.5)
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "bundle",
                        "--score-dir", scores, "--score-route", "vcsl")
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


    def test_film_refuses_suspect_truncated_until_owner_accepts_and_qc_lists_it(self):
        self.film_ready()
        plan = json.loads((self.root / "plan.json").read_text())
        from eav.voice import voice_units
        units = [u for sc in plan["plan"]["films"][0]["scenes"]
                 for u in voice_units(sc, {"description": ""}, None, "en")]
        key = next(u["unit_key"] for u in units if u["text"].startswith("Every afternoon"))
        self.wav(next(self.root.glob(f"narration/*/{key}.wav")), 0.5)  # 100 chars/s: cut off
        bed = self.d / "bed.wav"
        self.noise(bed, 30)
        base = ("film", "--root", self.root, "--logo", self.d / "logo.png",
                "--end-card", self.d / "end.png", "--score", bed, "--score-route", "vcsl")
        code, out = run(*base)
        self.assertEqual(code, 5, out)
        self.assertIn(f"suspect_truncated narration unit(s) {key}", out)
        self.assertFalse((self.root / "film" / "film-01" / "film-01.mp4").exists())
        code, out = run(*base, "--accept-qc", key)
        self.assertEqual(code, 0, out)
        film_art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(film_art["meta"]["qc_accepted"], [key])
        self.assertEqual([s["unit_key"] for s in film_art["meta"]["suspect_truncated"]], [key])
        code, out = run("qc", "--root", self.root)
        self.assertIn(key, out)
        item = json.loads((self.root / "qc" / "report.json").read_text())["items"]["film-01"]
        self.assertEqual([s["unit_key"] for s in item["suspect_truncated"]], [key])
        self.assertEqual(item["qc_accepted"], [key])
        self.assertNotIn("suspect_truncated", item["checks"])  # advisory, never a qc failure


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

    def test_spec_compute_block_cannot_lower_the_forecast(self):
        """R21: compute is derived from the spec's real items; a disagreeing block is refused."""
        self.init_and_plan()
        stills = {"items": [{"key": f"f01s001-{i}", "prompt": "a lamp", "seed": i} for i in range(1, 4)]}
        rates = {"stills": {"s_per_step": 10.0, "units_per_hour": 5.0, "steps": 4,
                            "decode_s": 10, "export_s": 10}}
        self.rates.write_text(json.dumps(rates), encoding="utf-8")
        spec = self.d / "stills.json"
        spec.write_text(json.dumps({**stills, "compute": {"steps": 4, "items": 1, "takes": 1,
                                                           "decode_s": 10, "export_s": 10}}))
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec", spec)
        self.assertEqual(code, 2, out)
        self.assertIn("compute", out)
        self.assertFalse(self.ledger.exists())
        spec.write_text(json.dumps(stills))
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec", spec)
        self.assertEqual(code, 0, out)
        entry = json.loads(self.ledger.read_text())[0]
        self.assertAlmostEqual(entry["units"], (4 * 10.0 * 3 + 10 + 10) * 1.15 / 3600 * 5.0)

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

    def fake_colab_outputs(self, job_id, job_dir, seconds=None):
        """What the owner downloads from Drive: one WAV per unit plus manifest.json.
        seconds: unit -> WAV length or None, to override a unit (e.g. one cut off)."""
        folder = self.d / "download" / job_id
        folder.mkdir(parents=True)
        with zipfile.ZipFile(job_dir / "inputs.zip") as z:
            units = json.loads(z.read("job.json"))["units"]
        outputs = {}
        for i, u in enumerate(units):
            wav = folder / f"{u['unit_key']}.wav"
            d = (seconds and seconds(u)) or speech_seconds(u["text"])
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"sine=f={200 + 20 * i}:d={d}:r=24000", "-ac", "1",
                            str(wav)], check=True)
            outputs[wav.name] = hashlib.sha256(wav.read_bytes()).hexdigest()
        zip_sha = hashlib.sha256((job_dir / "inputs.zip").read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": job_id, "title": "selfish-giant",
            "kind": "narration", "input_zip_sha256": zip_sha,
            "model": {"repo": "ai4bharat/indic-parler-tts", "revision": "x"}, "status": "COMPLETE",
            "packages": {"parler_tts": "0.2.2"},
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

    def imported(self, seconds=None):
        job_id, job_dir = self.build_narration()
        folder, units = self.fake_colab_outputs(job_id, job_dir, seconds)
        code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 1.5)
        self.assertEqual(code, 0, out)
        self.import_out = out
        return job_id, folder, units

    def reviewed(self, seconds=None):
        """Narration imported, film 1 assembled (faked) and a passing qc after it (R26)."""
        got = self.imported(seconds)
        rec = Record.load(self.root)
        (self.root / "film" / "film-01").mkdir(parents=True, exist_ok=True)
        (self.root / "film" / "film-01" / "film-01.mp4").write_bytes(b"x")
        rec.add_artifact("film", self.root / "film" / "film-01" / "film-01.mp4", {"target": "film-01"})
        rec.event("film", "assembled", {"target": "film-01"})
        rec.event("qc", "pass", {"failed": []})
        return got

    @staticmethod
    def cut_off(u):
        """The 50-character sentence came back in 0.5 s: 100 chars/s, 5 x the 20 chars/s median."""
        return 0.5 if u["text"].startswith("Every afternoon") else None

    def test_import_lists_suspect_truncated_units_but_still_imports(self):
        job_id, _, units = self.imported(self.cut_off)
        key = next(u["unit_key"] for u in units if self.cut_off(u))
        self.assertIn("suspect_truncated", self.import_out)
        self.assertIn(key, self.import_out)
        self.assertEqual(self.import_out.count("chars/s ("), 1)  # only that unit
        rec = Record.load(self.root)
        self.assertTrue(any(e["stage"] == "import" and e["result"] == "accepted"
                            and e["detail"]["job_id"] == job_id for e in rec.data["events"]))

    def test_import_of_clean_narration_reports_no_suspect(self):
        job_id, _, _ = self.imported()
        self.assertIn(f"No suspect_truncated narration unit in {job_id}", self.import_out)

    def test_bundle_audio_refuses_suspect_truncated_until_owner_accepts(self):
        _, _, units = self.reviewed(self.cut_off)
        key = next(u["unit_key"] for u in units if self.cut_off(u))
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertEqual(code, 5, out)
        self.assertIn("suspect_truncated", out)
        self.assertIn(f"--accept-qc {key}", out)
        self.assertFalse((self.d / "b").exists())
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b", "--dry",
                        "--accept-qc", "f99s999-001")
        self.assertNotEqual(code, 0)
        self.assertIn("not narration units", out)
        self.assertFalse((self.d / "b").exists())
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b", "--dry",
                        "--accept-qc", key)
        self.assertEqual(code, 0, out)
        ev = [e for e in Record.load(self.root).data["events"] if e["stage"] == "bundle_audio"][-1]
        self.assertEqual(ev["detail"]["qc_accepted"], [key])
        self.assertEqual([s["unit_key"] for s in ev["detail"]["suspect_truncated"]], [key])

    def test_bundle_audio_needs_a_passing_qc_of_the_film(self):
        self.imported()
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertNotEqual(code, 0)
        self.assertIn("qc", out)
        self.assertFalse((self.d / "b").exists())
        rec = Record.load(self.root)
        (self.root / "film" / "film-01").mkdir(parents=True)
        (self.root / "film" / "film-01" / "film-01.mp4").write_bytes(b"x")
        rec.add_artifact("film", self.root / "film" / "film-01" / "film-01.mp4", {"target": "film-01"})
        rec.event("film", "assembled", {"target": "film-01"})
        rec.event("qc", "fail", {"failed": ["film-01:loudness"]})
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertNotEqual(code, 0)
        rec.event("qc", "pass", {"failed": []})
        rec.event("film", "assembled", {"target": "film-01"})  # re-assembled after that qc
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertNotEqual(code, 0)
        rec.event("qc", "pass", {"failed": []})
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertEqual(code, 0, out)

    # --- R26: caps keyed by edition_id; one title root per edition -----------------------------
    def test_title_cap_is_keyed_by_edition_not_slug(self):
        self.init_and_plan()
        from eav.budget import Ledger
        Ledger(self.ledger).reserve("another-slug", "2026-01", 59.99, "old-job", edition_id="e-1",
                                    root="selfish-giant")
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 3, out)
        self.assertIn("59.99 CU spent/reserved for this title", run("status", "--root", self.root)[1])

    def test_init_refuses_a_second_root_for_the_same_edition(self):
        self.init_and_plan()
        self.assertEqual(run("job", "narration", "--root", self.root, "--rates", self.rates)[0], 0)
        entry = json.loads(self.ledger.read_text())[0]
        self.assertEqual((entry["edition_id"], entry["root"]), ("e-1", "selfish-giant"))
        other = self.d / "titles" / "giant-again"
        code, out = run("init", self.src, "--root", other, "--slug", "giant-again")
        self.assertNotEqual(code, 0)
        self.assertIn("e-1", out)
        self.assertIn("selfish-giant", out)
        self.assertFalse((other / "record.json").exists())

    def test_init_needs_the_edition_id(self):
        self.src.write_text(json.dumps({**SOURCE, "edition_id": None}), encoding="utf-8")
        code, out = run("init", self.src, "--root", self.root)
        self.assertNotEqual(code, 0)
        self.assertIn("edition_id", out)

    def test_qc_checks_the_reel_hook_starts_within_200_ms(self):
        self.init_and_plan()
        folder = self.root / "reels" / "reel-1"
        folder.mkdir(parents=True)
        rec = Record.load(self.root)
        for tag, lead in (("late", 0.5), ("ok", 0.05)):
            narration = folder / "narration.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"sine=f=300:d=2:r=48000", "-af", f"adelay={int(lead * 1000)}",
                            "-ac", "1", str(narration)], check=True)
            video = folder / f"reel-1-{tag}.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=108x192:d=2.5:r=24",
                            "-i", str(narration), "-shortest", "-pix_fmt", "yuv420p", str(video)], check=True)
            rec.add_artifact("reel", video, {"target": "reel-1", "width": 1080, "height": 1920})
            run("qc", "--root", self.root)
            report = json.loads((self.root / "qc" / "report.json").read_text())
            self.assertEqual(report["items"]["reel-1"]["checks"]["hook_onset"],
                             "fail" if tag == "late" else "pass", tag)
            self.assertAlmostEqual(report["items"]["reel-1"]["hook_onset_s"], lead, delta=0.03)

    def scores(self):
        d = self.d / "scores"
        d.mkdir()
        for u in SOURCE["units"]:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "anoisesrc=d=8:c=pink:r=48000:a=0.2", "-ac", "2",
                            str(d / f"{u['unit_id']}.wav")], check=True)
        return d

    def test_bundle_audio_refuses_without_score_unless_dry(self):
        self.reviewed()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle)
        self.assertNotEqual(code, 0)
        self.assertIn("score", out)
        self.assertIn("--dry", out)
        self.assertFalse(bundle.exists())
        self.assertFalse((self.root / "maison").exists())

    def test_bundle_audio_refuses_missing_chapter_score(self):
        self.reviewed()
        scores = self.scores()
        (scores / "u-2.wav").unlink()
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "bundle",
                        "--score-dir", scores, "--score-route", "vcsl")
        self.assertNotEqual(code, 0)
        self.assertIn("u-2", out)
        self.assertFalse((self.d / "bundle").exists())

    def test_bundle_audio_records_score_route_and_licence(self):
        """R24: the evidence draft names the score route and its licence for the clearance record."""
        self.reviewed()
        scores = self.scores()
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b0", "--score-dir", scores)
        self.assertNotEqual(code, 0)
        self.assertIn("--score-route", out)
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b1", "--score-dir", scores,
                        "--score-route", "ace-step:music-none")
        self.assertNotEqual(code, 0)
        self.assertFalse((self.d / "b1").exists())
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b2", "--score-dir", scores,
                        "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        ev = json.loads((self.root / "maison" / "audiovisual-clearance-evidence.draft.json").read_text())
        self.assertEqual(ev["music"]["route"], "vcsl")
        self.assertEqual(ev["music"]["licence"], "CC0-1.0")
        self.assertIn("VCSL", ev["music"]["source_and_licence"])
        self.assertIsNone(ev["music"]["music_job_id"])
        for field in ("term_per_territory", "text_source_licence", "cover_provenance", "territories"):
            self.assertIn(field, ev["owner_must_complete"])

    def test_bundle_audio_ace_step_route_names_its_music_job(self):
        self.reviewed()

        def cues(rec, job_id, job_dir, out):
            self.noise(out / "cue-1.wav", 1)
        music = self.fake_job("music", "film-01", cues)
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "b", "--score-dir",
                        self.scores(), "--score-route", f"ace-step:{music}")
        self.assertEqual(code, 0, out)
        ev = json.loads((self.root / "maison" / "audiovisual-clearance-evidence.draft.json").read_text())
        self.assertEqual((ev["music"]["route"], ev["music"]["licence"], ev["music"]["music_job_id"]),
                         (f"ace-step:{music}", "Apache-2.0", music))
        self.assertIn("ACE-Step", ev["music"]["source_and_licence"])

    def test_bundle_audio_dry_is_recorded(self):
        self.reviewed()
        code, out = run("bundle-audio", "--root", self.root, "--out", self.d / "bundle", "--dry")
        self.assertEqual(code, 0, out)
        timing = json.loads((self.d / "bundle" / "timing.json").read_text())
        self.assertTrue(all(u["mastered_with"] == "eav.mix.master"
                            for u in timing["provenance"]["units"].values()))
        ev = json.loads((self.root / "maison" / "audiovisual-clearance-evidence.draft.json").read_text())
        self.assertIs(ev["dry_narration"], True)
        self.assertIsNone(ev["music"])

    def test_preview_needs_a_bundle_and_refuses_a_chapter_without_a_pause(self):
        self.reviewed()
        code, out = run("preview", "--root", self.root, "--bundle", self.d / "none", "--out", self.d / "pv")
        self.assertEqual(code, 2, out)
        self.assertFalse((self.d / "pv").exists())
        bundle = self.d / "bundle"
        self.assertEqual(run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")[0], 0)
        code, out = run("preview", "--root", self.root, "--bundle", bundle, "--out", self.d / "pv")
        self.assertEqual(code, 5, out)  # the fixture chapter is too short to hold a >= 10 s cut
        self.assertFalse((self.d / "pv").exists())

    def test_bundle_audio_before_narration_import_stops_and_writes_nothing(self):
        self.build_narration()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertNotEqual(code, 0)
        self.assertIn("qc", out)  # R26: no passing qc of an assembled film yet
        rec = Record.load(self.root)  # even with one faked, the narration must be imported
        (self.root / "film" / "film-01").mkdir(parents=True)
        (self.root / "film" / "film-01" / "film-01.mp4").write_bytes(b"x")
        rec.add_artifact("film", self.root / "film" / "film-01" / "film-01.mp4", {"target": "film-01"})
        rec.event("qc", "pass", {"failed": []})
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertNotEqual(code, 0)
        self.assertIn("narration not imported", out)
        self.assertFalse(bundle.exists())
        self.assertFalse((self.root / "maison").exists())

    def test_bundle_audio_writes_measured_timing_with_provenance(self):
        job_id, folder, units = self.reviewed()
        scores = self.scores()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--score-dir", scores, "--score-route", "vcsl")
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
        # a2 = two sentences (2.5 s and 1.2 s WAVs) with a 400 ms pause: measured, not estimated
        a2 = segs[1]
        first, second = sentences(PARAS[1][2])
        self.assertAlmostEqual((a2["end_ms"] - a2["start_ms"]) / 1000,
                               speech_seconds(first) + 0.4 + speech_seconds(second), delta=0.05)
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
