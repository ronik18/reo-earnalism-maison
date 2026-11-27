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

    def film_ready(self, narration=True, init=True):
        if init:
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

        if narration:
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
        with self.assertRaises(SystemExit):
            run("close", job_id2, "--root", self.root, "--reason", "no units")

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
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", bundle, "--dry")
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
            code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", bundle, "--dry")
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
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "bundle",
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


    def test_film_shots_refuses_a_scene_without_an_approved_shot_plan(self):
        self.film_ready()
        shots = ("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card", self.d / "end.png",
                 "--shots", "--title", "T", "--author", "A", "--narrator", "V")
        code, out = run(*shots)
        self.assertNotEqual(code, 0)
        self.assertIn("no shot plan", out)                       # R11: the paper edit comes first
        self.assertFalse([a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"])
        code, out = run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                        self.d / "end.png", "--shots")
        self.assertNotEqual(code, 0)
        self.assertIn("--title", out)                           # the cards are not optional

    def test_film_shots_assembles_approved_scenes_end_to_end(self):
        """Two approved scenes of static shots, their scene mixes, cards, captions: one 24 fps film."""
        self.shots_end_to_end()

    def shots_end_to_end(self, narration=True, init=True):
        import re
        from eav import shotplan
        self.film_ready(narration, init)
        plan = json.loads((self.root / "plan.json").read_text())
        scenes = plan["plan"]["films"][0]["scenes"]
        fdir = self.root / "film" / "film-01"

        def shot_stills(rec, job_id, job_dir, out):   # one still per shot: <scene>-<n>
            for i, sc in enumerate(scenes):
                for n in (1, 2):
                    Image.new("RGB", (320, 180), (60 * i, 90, 40 * n)).save(out / f"{sc['scene_id']}-{n}.png")
        self.fake_job("stills", "film-01", shot_stills)
        for sc in scenes:
            clauses = [c.strip() for c in re.split(r"(?<=[.])\s+|\n\n", sc["text"]) if c.strip()]
            k = len(clauses)
            first = [(i * 5.5 / (k - 1) + (0.3 if i else 0.0), (i + 1) * 5.5 / (k - 1)) for i in range(k - 1)]
            spans = first + [(6.2, 11.5)]
            timing = [{"start": round(a, 3), "end": round(b, 3), "text": t} for (a, b), t in zip(spans, clauses)]
            shot = lambda b, tr, **kw: {"beats": b, "subject": "a room", "framing": "wide", "motion": "static",
                                        "layer": "present", "transition_in": tr, "bible_refs": [],
                                        "sound": {"sfx": [], "music": None}, **kw}
            inp = {"spine": "s", "fidelity": "f", "motifs": ["m"], "timing": timing, "peak": {"shot": 2, "at": 9.0},
                   "shots": [shot([0, k - 2], "cut"), shot([k - 1, k - 1], "dissolve", plants=[1])]}
            paths = shotplan.paths(fdir, sc["scene_id"])
            paths["dir"].mkdir(parents=True, exist_ok=True)
            paths["input"].write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")
            sp = shotplan.plan({**inp, "scene_id": sc["scene_id"], "text": sc["text"]}, timing, {"characters": {}})
            shotplan.write(fdir, shotplan.approve(sp, "claude", "reviewer", input_sha256=shotplan.input_sha256(paths["input"])))
            (fdir / "audio").mkdir(exist_ok=True)
            self.wav(fdir / "audio" / f"{sc['scene_id']}.mix.wav", 11.5)
            loud = fdir / "audio" / f"{sc['scene_id']}.mix.wav"      # the gate wants about -16 LUFS
            tmpw = loud.with_name("tmp.wav")
            for _ in range(3):
                g = -16.0 - mix.measure(loud)["lufs"]
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(loud), "-af", f"volume={g}dB", str(tmpw)],
                               check=True)
                tmpw.replace(loud)
        args = ("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card", self.d / "end.png",
                "--shots", "--title", "The Garden", "--author", "An Author", "--narrator", "A Voice", "--burn")
        with mock.patch.object(cli.film, "ENCODE_PRESET", "ultrafast"), \
                mock.patch.object(cli.film, "FRAME", (640, 360)):     # a small frame keeps the test fast
            code, out = run(*args)
        self.assertEqual(code, 0, out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        mp4 = self.root / art["path"]
        self.assertEqual(art["meta"]["mode"], "shots")
        # 2 scenes x 11.5 s at 24 fps: each cut is a 1-frame xfade, each dissolve 19 frames, all on their frames
        self.assertEqual(art["meta"]["frames"], len(scenes) * 276)
        self.assertAlmostEqual(art["meta"]["duration"], art["meta"]["picture_s"] + 4.0 + 5.0 + 3.0, delta=0.05)
        self.assertTrue((fdir / "film-01.burned.mp4").is_file())

        def streams(path):
            return subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                   str(path)], check=True, capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(streams(mp4)), ["audio", "subtitle", "video"])           # soft mov_text track
        self.assertEqual(sorted(streams(fdir / "film-01.burned.mp4")), ["audio", "video"])   # burned: none
        self.assertTrue((fdir / "film-01.vtt").read_text(encoding="utf-8").startswith("WEBVTT"))
        arts = Record.load(self.root).data["artifacts"]
        self.assertTrue([a for a in arts if a["kind"] == "subtitles" and a["meta"]["target"] == "film-01"])  # bundle-film
        self.assertTrue((fdir / "film-01.srt").read_text(encoding="utf-8").startswith("1\n"))
        self.assertLessEqual(art["meta"]["true_peak"], -1.5)
        self.assertLessEqual(abs(art["meta"]["lufs"] + 16), 1.0)
        self.assertTrue((fdir / "cards" / "cards.json").is_file())
        self.assertGreater(len(list((fdir / "shots-cache").glob("*.mp4"))), 1)
        self.assertTrue(mp4.is_file())

    def test_film_applies_a_later_partial_stills_job_as_a_patch(self):
        """বিচারক film-01: nine Judge Mohit stills came out bearded. A later stills job that
        regenerates only some keys replaces those keys; every other still stays from the base."""
        self.film_ready()
        rec = Record.load(self.root)
        base = [j for j in cli._jobs(rec) if j["kind"] == "stills"][-1]["job_id"]
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        first = scenes[0]["scene_id"]

        def patch(rec, job_id, job_dir, out):
            Image.new("RGB", (320, 180), (255, 0, 0)).save(out / f"{first}-1.png")
        fix = self.fake_job("stills", "film-01", patch)
        bed = self.d / "bed.wav"
        self.noise(bed, 30)
        code, out = run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                        self.d / "end.png", "--score", bed, "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"], {"base": base, "patches": [fix]})
        merged = self.root / "film" / "film-01" / "stills"
        self.assertEqual(sorted(p.stem for p in merged.iterdir()),
                         sorted(f"{sc['scene_id']}-1" for sc in scenes))
        self.assertEqual((merged / f"{first}-1.png").read_bytes(),
                         (self.root / "stills" / fix / f"{first}-1.png").read_bytes())
        if len(scenes) > 1:
            other = f"{scenes[1]['scene_id']}-1.png"
            self.assertEqual((merged / other).read_bytes(),
                             (self.root / "stills" / base / other).read_bytes())


    # --- candidates per shot: review, pick, film ------------------------------------------
    def candidates_ready(self, picked_colour=(0, 200, 0)):
        """film_ready plus a later stills job with three candidates for the first scene's still."""
        self.film_ready()
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        first = f"{scenes[0]['scene_id']}-1"

        def cands(rec, job_id, job_dir, out):
            for c in (1, 2, 3):
                colour = picked_colour if c == 2 else (10 * c, 0, 0)
                Image.new("RGB", (320, 180), colour).save(out / f"{first}--c{c}.png")
        return scenes, first, self.fake_job("stills", "film-01", cands)

    def film_run(self):
        bed = self.d / "bed.wav"
        if not bed.exists():
            self.noise(bed, 30)
        return run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                   self.d / "end.png", "--score", bed, "--score-route", "vcsl")

    def pick(self, job, choices):
        path = self.d / "choices.json"
        path.write_text(json.dumps(choices), encoding="utf-8")
        return run("pick", "--root", self.root, "--job", job, "--choices", path)

    def test_pick_records_the_chosen_candidates_with_their_sha256(self):
        scenes, first, job = self.candidates_ready()
        code, out = self.pick(job, {first: 2})
        self.assertEqual(code, 0, out)
        rec = Record.load(self.root)
        art = [a for a in rec.data["artifacts"] if a["kind"] == "stills_pick"][-1]
        chosen = self.root / "stills" / job / f"{first}--c2.png"
        self.assertEqual(art["meta"]["job_id"], job)
        self.assertEqual(art["meta"]["choices"], {first: {
            "candidate": 2, "file": f"stills/{job}/{first}--c2.png",
            "sha256": hashlib.sha256(chosen.read_bytes()).hexdigest()}})
        self.assertEqual(json.loads((self.root / art["path"]).read_text())["choices"],
                         art["meta"]["choices"])
        self.assertTrue(any(e["stage"] == "pick" and e["result"] == "recorded"
                            and e["detail"]["job_id"] == job for e in rec.data["events"]))

    def gated_ready(self, gates, intended=True):
        """candidates_ready whose candidates carry <key>--cN.gate.json from {n: gate dict}; the stills
        artifacts keep MODEL_INFO.gate (the gate's recorded intent) unless intended=False (a legacy job)."""
        self.film_ready()
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        first = f"{scenes[0]['scene_id']}-1"

        def cands(rec, job_id, job_dir, out):
            for c in (1, 2, 3):
                png = out / f"{first}--c{c}.png"
                Image.new("RGB", (320, 180), (10 * c, 0, 0)).save(png)
                rec.add_artifact("stills", png, {"job_id": job_id, "model": (
                    {"gate": {"intended": True}} if intended else {"repo": "flux"})})
                if c in gates:
                    (out / f"{first}--c{c}.gate.json").write_text(json.dumps(gates[c]))
        return first, self.fake_job("stills", "film-01", cands)

    def calibrate(self):
        (self.root / "gate-calibration.json").write_text(json.dumps({"anchor_pass": 0.5}))

    PASS = {"eyes": 2, "hands_detached": False, "anachronisms": [], "anchor_similarity": 0.9,
            "pass": True, "needs_review": False, "notes": []}
    FAIL = {**PASS, "anachronisms": ["gas cylinder"], "pass": False, "notes": ["anachronism: gas cylinder"]}
    REVIEW = {**PASS, "pass": False, "needs_review": True, "notes": ["profile face with 1 visible eye(s)"]}

    def pick_with(self, job, choices, *flags):
        path = self.d / "choices.json"
        path.write_text(json.dumps(choices), encoding="utf-8")
        return run("pick", "--root", self.root, "--job", job, "--choices", path, *flags)

    def picks(self):
        return [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "stills_pick"]

    def test_pick_refuses_a_certain_fail_without_override_fail(self):
        first, job = self.gated_ready({1: self.PASS, 2: self.FAIL, 3: self.REVIEW})
        code, out = self.pick(job, {first: 2})
        self.assertNotEqual(code, 0, out)
        self.assertIn("STOP", out)
        self.assertIn("gas cylinder", out)
        self.assertIn(f'--override-fail {first}=', out)
        self.assertFalse(self.picks())
        code, out = self.pick_with(job, {first: 2}, "--override", f"{first}=looks fine")   # wrong flag for a fail
        self.assertNotEqual(code, 0, out)
        self.assertFalse(self.picks())
        self.assertEqual(self.pick(job, {first: 1})[0], 0)                                  # a pass is pickable

    def test_override_fail_records_the_reason_per_key(self):
        first, job = self.gated_ready({1: self.PASS, 2: self.FAIL})
        code, out = self.pick_with(job, {first: 2}, "--override-fail",
                                   f"{first}=owner viewed it: the cylinder is a period lamp")
        self.assertEqual(code, 0, out)
        rec = Record.load(self.root)
        art = self.picks()[-1]
        ov = art["meta"]["overrides"][first]
        self.assertEqual((ov["reason"], ov["candidate"], ov["level"]),
                         ("owner viewed it: the cylinder is a period lamp", 2, "fail"))
        self.assertEqual(ov["gate"]["anachronisms"], ["gas cylinder"])
        self.assertEqual(json.loads((self.root / art["path"]).read_text())["overrides"], art["meta"]["overrides"])
        ev = [e for e in rec.data["events"] if e["stage"] == "pick" and e["result"] == "recorded"][-1]
        self.assertEqual(ev["detail"]["overrides"], {first: "owner viewed it: the cylinder is a period lamp"})

    def test_needs_review_is_advisory_until_the_title_is_calibrated(self):
        first, job = self.gated_ready({1: self.PASS, 3: self.REVIEW})
        code, out = self.pick(job, {first: 3})
        self.assertEqual(code, 0, out)
        self.assertIn("WARNING", out)
        self.assertIn("profile face", out)
        art = self.picks()[-1]
        self.assertEqual(art["meta"]["advisories"][first]["candidate"], 3)
        self.assertNotIn("overrides", art["meta"])
        ev = [e for e in Record.load(self.root).data["events"] if e["stage"] == "pick"][-1]
        self.assertIn(first, ev["detail"]["advisories"])

    def test_needs_review_blocks_after_calibration_and_takes_a_per_key_override(self):
        first, job = self.gated_ready({1: self.PASS, 3: self.REVIEW})
        self.calibrate()
        code, out = self.pick(job, {first: 3})
        self.assertNotEqual(code, 0, out)
        self.assertIn(f"--override {first}=", out)
        self.assertFalse(self.picks())
        code, out = self.pick_with(job, {first: 3}, "--override", f"{first}=owner checked the profile")
        self.assertEqual(code, 0, out)
        ov = self.picks()[-1]["meta"]["overrides"][first]
        self.assertEqual((ov["reason"], ov["level"]), ("owner checked the profile", "review"))
        for bad in ("noequals", f"{first}=", "=why"):
            code, out = self.pick_with(job, {first: 3}, "--override", bad)
            self.assertNotEqual(code, 0, bad)
            self.assertIn("KEY=reason", out)
        code, out = self.pick_with(job, {first: 1}, "--override", "f99s999-1=why")
        self.assertNotEqual(code, 0)
        self.assertIn("not in the choices", out)

    def test_pick_of_an_ungated_legacy_job_is_unchanged(self):
        scenes, first, job = self.candidates_ready()                 # no gate.json, no recorded intent
        self.assertEqual(self.pick(job, {first: 1})[0], 0)
        meta = self.picks()[-1]["meta"]
        self.assertNotIn("overrides", meta)
        self.assertNotIn("advisories", meta)

    def test_a_gated_job_whose_candidate_has_no_gate_result_is_advisory_needs_review(self):
        first, job = self.gated_ready({1: self.PASS})                # c2 was never gated (gate ran out of time)
        code, out = self.pick(job, {first: 2})
        self.assertEqual(code, 0, out)
        self.assertIn("intended", out)
        self.calibrate()
        code, out = self.pick(job, {first: 2})
        self.assertNotEqual(code, 0, out)

    def test_gate_intent_comes_from_the_manifest_not_from_files_on_disk(self):
        # gate.json files exist but the job's recorded model has no gate: not gated, nothing is read as blocking
        first, job = self.gated_ready({1: self.PASS, 2: self.FAIL}, intended=False)
        self.calibrate()
        self.assertNotEqual(self.pick(job, {first: 2})[0], 0)        # a file that says fail still blocks

    def test_a_gated_job_with_no_gate_files_at_all_is_not_treated_as_legacy(self):
        first, job = self.gated_ready({})                            # intent recorded, gate produced nothing
        code, out = self.pick(job, {first: 1})
        self.assertEqual(code, 0, out)                               # advisory before calibration...
        self.assertIn("WARNING", out)
        self.calibrate()
        self.assertNotEqual(self.pick(job, {first: 1})[0], 0)        # ...blocking after it

    def test_film_refuses_a_certain_fail_still_unless_a_reason_is_recorded(self):
        scenes, first, job = self.candidates_ready()
        base = [j for j in cli._jobs(Record.load(self.root)) if j["kind"] == "stills"][0]["job_id"]
        gate = self.root / "stills" / base / f"{first}.gate.json"
        gate.write_text(json.dumps(self.FAIL))
        code, out = self.film_run()
        self.assertNotEqual(code, 0, out)
        self.assertIn("certain gate fail", out)
        self.assertIn(first, out)
        (self.root / "picks").mkdir(exist_ok=True)
        (self.root / "picks" / "gate-overrides.json").write_text(json.dumps({first: "owner accepted it"}))
        code, out = self.film_run()
        self.assertEqual(code, 0, out)
        (self.root / "picks" / "gate-overrides.json").unlink()
        gate.write_text(json.dumps(self.REVIEW))                     # needs_review never blocks the film
        self.assertEqual(self.film_run()[0], 0)

    def test_pick_refuses_bad_jobs_keys_and_numbers(self):
        scenes, first, job = self.candidates_ready()
        base = [j for j in cli._jobs(Record.load(self.root)) if j["kind"] == "stills"][0]["job_id"]
        narr = [j for j in cli._jobs(Record.load(self.root)) if j["kind"] == "narration"][0]["job_id"]
        for bad_job, choices, words in ((base, {first: 1}, "no candidate"),
                                        (narr, {first: 1}, "not an imported stills job"),
                                        ("stills-nope", {first: 1}, "not an imported stills job"),
                                        (job, {"f99s999-1": 1}, "f99s999-1"),
                                        (job, {first: 4}, "4"), (job, {first: 0}, "0"),
                                        (job, {first: "2"}, "'2'"), (job, {first: True}, "True"),
                                        (job, {}, "no choices"), (job, [first], "object")):
            with self.subTest(job=bad_job, choices=choices):
                code, out = self.pick(bad_job, choices)
                self.assertNotEqual(code, 0, out)
                self.assertIn("STOP", out)
                self.assertIn(words, out)
        rec = Record.load(self.root)
        self.assertFalse([a for a in rec.data["artifacts"] if a["kind"] == "stills_pick"])
        self.assertFalse((self.root / "picks").exists() and any((self.root / "picks").iterdir()))

    def test_film_uses_only_the_picked_candidate_renamed_to_its_key(self):
        scenes, first, job = self.candidates_ready()
        base = [j for j in cli._jobs(Record.load(self.root)) if j["kind"] == "stills"][0]["job_id"]
        self.assertEqual(self.pick(job, {first: 1})[0], 0)
        self.assertEqual(self.pick(job, {first: 2})[0], 0)  # re-running replaces the selection
        code, out = self.film_run()
        self.assertEqual(code, 0, out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"], {"base": base, "patches": [job]})
        merged = self.root / "film" / "film-01" / "stills"
        names = sorted(p.name for p in merged.iterdir())
        self.assertEqual(names, sorted(f"{sc['scene_id']}-1.png" for sc in scenes))
        self.assertFalse([n for n in names if "--c" in n])
        self.assertEqual((merged / f"{first}.png").read_bytes(),
                         (self.root / "stills" / job / f"{first}--c2.png").read_bytes())

    def test_film_ignores_an_unpicked_candidates_job(self):
        scenes, first, job = self.candidates_ready()
        base = [j for j in cli._jobs(Record.load(self.root)) if j["kind"] == "stills"][0]["job_id"]
        code, out = self.film_run()
        self.assertEqual(code, 0, out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"], {"base": base, "patches": [], "unpicked": [job]})
        merged = self.root / "film" / "film-01" / "stills"
        self.assertFalse([p for p in merged.iterdir() if "--c" in p.name])
        self.assertEqual((merged / f"{first}.png").read_bytes(),
                         (self.root / "stills" / base / f"{first}.png").read_bytes())

    # --- hold: unapproved shots show the scene's nearest approved still ---------------------
    def hold_ready(self):
        """film_ready plus a base stills job with four shots (distinct colours) per scene."""
        self.film_ready()
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        sid = scenes[0]["scene_id"]

        def shots(rec, job_id, job_dir, out):
            for sc in scenes:
                for n in range(1, 5):
                    Image.new("RGB", (64, 36), (40 * n, 7 * n, 3)).save(out / f"{sc['scene_id']}-{n}.png")
        job = self.fake_job("stills", "film-01", shots)
        return sid, job

    def hold(self, *args):
        return run("hold", "--root", self.root, "--film", "1", *args)

    def merged(self):
        rec = Record.load(self.root)
        out = self.d / "merged-out"
        out.mkdir(exist_ok=True)
        folder, meta = cli._film_stills(rec, "film-01", out)
        return {p.stem: p.read_bytes() for p in folder.iterdir()}, meta

    def shot(self, job, sid, n):
        return (self.root / "stills" / job / f"{sid}-{n}.png").read_bytes()

    def test_hold_substitutes_the_previous_approved_shot_else_the_next(self):
        sid, job = self.hold_ready()
        code, out = self.hold("--keys", f"{sid}-2,{sid}-3,{sid}-1")
        self.assertEqual(code, 0, out)
        files, meta = self.merged()
        self.assertEqual(files[f"{sid}-1"], self.shot(job, sid, 4))  # nothing before: the next approved
        self.assertEqual(files[f"{sid}-2"], self.shot(job, sid, 4))
        self.assertEqual(files[f"{sid}-3"], self.shot(job, sid, 4))
        code, out = self.hold("--keys", f"{sid}-3")
        self.assertEqual(code, 0, out)
        files, meta = self.merged()
        self.assertEqual(files[f"{sid}-3"], self.shot(job, sid, 2))  # previous wins over next
        self.assertEqual(files[f"{sid}-4"], self.shot(job, sid, 4))
        self.assertEqual(meta["held"], [f"{sid}-3"])
        self.assertEqual(meta["substitutes"], {f"{sid}-3": {"use": f"{sid}-2", "cross_scene": False}})

    def test_a_held_key_never_uses_its_own_file(self):
        sid, job = self.hold_ready()
        self.assertEqual(self.hold("--keys", f"{sid}-2")[0], 0)
        files, meta = self.merged()
        self.assertNotEqual(files[f"{sid}-2"], self.shot(job, sid, 2))
        self.assertEqual(files[f"{sid}-2"], self.shot(job, sid, 1))
        self.assertEqual(meta["substitutes"], {f"{sid}-2": {"use": f"{sid}-1", "cross_scene": False}})

    def test_an_all_held_scene_falls_back_to_the_previous_scenes_last_approved_still(self):
        sid, job = self.hold_ready()
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        if len(scenes) < 2:
            self.skipTest("needs two scenes")
        s2 = scenes[1]["scene_id"]
        self.assertEqual(self.hold("--keys", ",".join(f"{s2}-{n}" for n in range(1, 5)) + f",{sid}-4")[0], 0)
        files, meta = self.merged()
        self.assertEqual(files[f"{s2}-2"], self.shot(job, sid, 3))
        self.assertEqual(meta["substitutes"][f"{s2}-1"], {"use": f"{sid}-3", "cross_scene": True})
        self.assertEqual(meta["substitutes"][f"{sid}-4"], {"use": f"{sid}-3", "cross_scene": False})

    def test_an_all_held_first_scene_falls_back_to_the_next_scenes_first_approved_still(self):
        sid, job = self.hold_ready()
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        if len(scenes) < 2:
            self.skipTest("needs two scenes")
        s2 = scenes[1]["scene_id"]
        self.assertEqual(self.hold("--keys", ",".join(f"{sid}-{n}" for n in range(1, 5)))[0], 0)
        files, meta = self.merged()
        self.assertEqual(files[f"{sid}-3"], self.shot(job, s2, 1))
        self.assertEqual(meta["substitutes"][f"{sid}-3"], {"use": f"{s2}-1", "cross_scene": True})

    def test_a_film_with_every_shot_held_stops(self):
        sid, job = self.hold_ready()
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        keys = [f"{sc['scene_id']}-{n}" for sc in scenes for n in range(1, 5)]
        self.assertEqual(self.hold("--keys", ",".join(keys))[0], 0)
        with self.assertRaises(cli.Stop) as cm:
            self.merged()
        self.assertIn("every shot of the film is held", str(cm.exception))

    def test_the_latest_hold_wins_and_clear_removes_it(self):
        sid, job = self.hold_ready()
        self.assertEqual(self.hold("--keys", f"{sid}-2")[0], 0)
        self.assertEqual(self.hold("--keys", f"{sid}-3")[0], 0)
        files, meta = self.merged()
        self.assertEqual(meta["held"], [f"{sid}-3"])
        self.assertEqual(files[f"{sid}-2"], self.shot(job, sid, 2))
        code, out = self.hold("--clear")
        self.assertEqual(code, 0, out)
        files, meta = self.merged()
        self.assertNotIn("held", meta)
        self.assertEqual(files[f"{sid}-3"], self.shot(job, sid, 3))
        arts = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "stills_hold"]
        self.assertEqual([a["meta"]["keys"] for a in arts], [[f"{sid}-2"], [f"{sid}-3"], []])
        self.assertNotEqual(self.hold()[0], 0)  # neither --keys nor --clear

    def test_a_candidates_job_never_becomes_the_base(self):
        """Every key of the base is covered by the candidates job, yet the base stays."""
        self.film_ready()
        scenes = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]
        base = [j for j in cli._jobs(Record.load(self.root)) if j["kind"] == "stills"][0]["job_id"]

        def cands(rec, job_id, job_dir, out):
            for sc in scenes:
                for c in (1, 2):
                    Image.new("RGB", (320, 180), (0, 0, 40 * c)).save(
                        out / f"{sc['scene_id']}-1--c{c}.png")
        job = self.fake_job("stills", "film-01", cands)
        self.assertEqual(self.pick(job, {f"{scenes[0]['scene_id']}-1": 2})[0], 0)
        code, out = self.film_run()
        self.assertEqual(code, 0, out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills"], {"base": base, "patches": [job]})

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
        # plus the gate's seconds (set-up 300 s + 6 s x 3 stills), added after the margin
        self.assertAlmostEqual(entry["units"], ((4 * 10.0 * 3 + 10 + 10) * 1.15 + 300 + 6 * 3) / 3600 * 5.0)

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

    def imported(self):
        job_id, job_dir = self.build_narration()
        folder, units = self.fake_colab_outputs(job_id, job_dir)
        code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 1.5)
        self.assertEqual(code, 0, out)
        return job_id, folder, units

    def reviewed(self):
        """Narration imported, film 1 assembled (faked) and a passing qc after it (R26)."""
        got = self.imported()
        rec = Record.load(self.root)
        (self.root / "film" / "film-01").mkdir(parents=True, exist_ok=True)
        (self.root / "film" / "film-01" / "film-01.mp4").write_bytes(b"x")
        rec.add_artifact("film", self.root / "film" / "film-01" / "film-01.mp4", {"target": "film-01"})
        rec.event("film", "assembled", {"target": "film-01"})
        rec.event("qc", "pass", {"failed": []})
        return got

    def test_bundle_audio_needs_a_passing_qc_of_the_film(self):
        self.imported()
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertNotEqual(code, 0)
        self.assertIn("qc", out)
        self.assertFalse((self.d / "b").exists())
        rec = Record.load(self.root)
        (self.root / "film" / "film-01").mkdir(parents=True)
        (self.root / "film" / "film-01" / "film-01.mp4").write_bytes(b"x")
        rec.add_artifact("film", self.root / "film" / "film-01" / "film-01.mp4", {"target": "film-01"})
        rec.event("film", "assembled", {"target": "film-01"})
        rec.event("qc", "fail", {"failed": ["film-01:loudness"]})
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertNotEqual(code, 0)
        rec.event("qc", "pass", {"failed": []})
        rec.event("film", "assembled", {"target": "film-01"})  # re-assembled after that qc
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertNotEqual(code, 0)
        rec.event("qc", "pass", {"failed": []})
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertEqual(code, 0, out)


    # --- Task 10: the audiobook profile (default): own master, chapters, sentence timing ---------------
    def frame_dir(self):
        d = self.d / "frame"
        d.mkdir()
        for name, freq in (("title", 300), ("author", 330), ("closing", 260)):
            self.wav(d / f"{name}.wav", 0.8, freq)
        return d

    def audiobook(self, *flags, source=None):
        if source:
            self.src.write_text(json.dumps(source), encoding="utf-8")
        self.reviewed()
        bundle = self.d / "bundle"
        # a few seconds of fixture speech have no loudness range: the 4-8 LU gate is tested in test_mix
        with mock.patch.object(mix, "LRA_LU", (0.0, 20.0)):
            code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--frame-dir",
                            self.frame_dir(), *flags)
        return code, out, bundle

    def chaptered_source(self):
        src = json.loads(json.dumps(SOURCE))
        src["units"][0]["paragraphs"][0] = {"anchor_id": "a1", "kind": "heading", "text": "প্রথম পরিচ্ছেদ"}
        return src

    def test_bundle_has_chapters_and_sentence_timing(self):
        code, out, bundle = self.audiobook("--dry", source=self.chaptered_source())
        self.assertEqual(code, 0, out)
        timing = json.loads((bundle / "timing.json").read_text())
        rows = {r["unit_id"]: r for r in timing["units"]}
        self.assertEqual(set(rows["u-1"]), {"unit_id", "mp3", "segments", "chapters", "sentences"})
        segs = {s["anchor_id"]: s for r in timing["units"] for s in r["segments"]}
        # chapter markers: the পরিচ্ছেদ heading at its measured start; a unit with none gets its title at 0
        self.assertEqual(rows["u-1"]["chapters"], [{"title": "প্রথম পরিচ্ছেদ", "start_ms": segs["a1"]["start_ms"]}])
        self.assertEqual(rows["u-2"]["chapters"], [{"title": "Two", "start_ms": 0}])
        self.assertGreater(segs["a1"]["start_ms"], 0)  # the title and author are spoken first
        by_anchor = {}
        for r in timing["units"]:
            for s in r["sentences"]:
                self.assertEqual(set(s), {"anchor_id", "sentence_index", "start_ms", "end_ms"})
                by_anchor.setdefault(s["anchor_id"], []).append(s)
        self.assertEqual(sorted(by_anchor), ["a1", "a2", "a3"])
        for a, got in by_anchor.items():  # every paragraph is covered by its sentences, in order
            self.assertEqual([s["sentence_index"] for s in got], list(range({"a1": 1, "a2": 2, "a3": 2}[a])))
            self.assertEqual(got[0]["start_ms"], segs[a]["start_ms"])
            self.assertEqual(got[-1]["end_ms"], segs[a]["end_ms"])
            for s, nxt in zip(got, got[1:]):
                self.assertLess(s["start_ms"], s["end_ms"])
                self.assertLessEqual(s["end_ms"], nxt["start_ms"])
        # a2 = two sentences (0.7 s and 0.8 s) with a measured 400 ms pause between them
        a2 = by_anchor["a2"]
        self.assertAlmostEqual((a2[1]["start_ms"] - a2[0]["end_ms"]) / 1000, 0.4, delta=0.06)
        self.assertAlmostEqual((a2[0]["end_ms"] - a2[0]["start_ms"]) / 1000, 0.7, delta=0.06)
        prov = timing["provenance"]
        self.assertEqual(prov["profile"], "audiobook")
        self.assertEqual(prov["units"]["u-1"]["mastered_with"], "eav.mix.master_audiobook")
        self.assertEqual(prov["units"]["u-1"]["encoder"], "ffmpeg libmp3lame 64 kbps CBR mono 48 kHz")
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=channels,bit_rate",
                                           "-of", "json", str(bundle / "unit-001.mp3")], check=True,
                                          capture_output=True, text=True).stdout)["streams"][0]
        self.assertEqual((probe["channels"], probe["bit_rate"]), (1, "64000"))
        self.assertAlmostEqual(mix.measure(bundle / "unit-001.mp3")["lufs"], -18.0, delta=1.0)
        self.assertLessEqual(mix.measure(bundle / "unit-001.mp3")["true_peak"], -2.0)
        for k in ("title", "author", "closing"):
            self.assertIn(k, prov["frame_units_sha256"])
        self.assertEqual(sorted(p.name for p in bundle.iterdir()), ["timing.json", "unit-001.mp3", "unit-002.mp3"])

    def test_audiobook_is_the_default_profile_and_needs_the_frame_units(self):
        self.reviewed()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertNotEqual(code, 0)
        self.assertIn("--frame-dir", out)
        self.assertIn("title.wav", out)
        self.assertFalse(bundle.exists())
        (self.d / "empty").mkdir()
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry", "--frame-dir", self.d / "empty")
        self.assertNotEqual(code, 0)
        self.assertIn("author.wav", out)

    def test_audiobook_with_score_dir_beds_only_at_part_changes_and_ends(self):
        code, out, bundle = self.audiobook("--score-dir", self.scores(), "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        prov = json.loads((bundle / "timing.json").read_text())["provenance"]
        for unit_id, row in prov["units"].items():
            self.assertEqual(row["mastered_with"], "eav.mix.master_audiobook")
            self.assertGreaterEqual(row["bed_under_voice_lu"], 24.0)
            self.assertEqual(row["score_sha256"], hashlib.sha256(
                (self.d / "scores" / f"{unit_id}.wav").read_bytes()).hexdigest())

    def test_beds_only_at_book_intro_outro_and_flagged_parts(self):
        args = mock.Mock(frame_dir=self.d / "f")
        bed = self.d / "bed.wav"
        chapter = {"unit_id": "u", "title": "প্রথম পরিচ্ছেদ", "paragraphs": []}
        self.assertEqual(sorted(cli._audiobook_cues(args, bed, 1, 3, chapter)), ["intro", "opening"])
        self.assertEqual(cli._audiobook_cues(args, bed, 2, 3, chapter), {})  # a chapter: no bed
        self.assertEqual(sorted(cli._audiobook_cues(args, bed, 3, 3, chapter)), ["closing", "outro"])
        flagged = {**chapter, "part": True}
        self.assertEqual(sorted(cli._audiobook_cues(args, bed, 2, 3, flagged)), ["part"])
        titled = {**chapter, "title": "দ্বিতীয় খণ্ড"}
        self.assertEqual(sorted(cli._audiobook_cues(args, bed, 2, 3, titled)), ["part"])
        self.assertEqual(sorted(cli._audiobook_cues(args, bed, 2, 3, {**chapter, "title": "তৃতীয় ভাগ"})), ["part"])

    def test_sentence_mapping_is_recorded_per_paragraph(self):
        code, out, bundle = self.audiobook("--dry")
        self.assertEqual(code, 0, out)
        prov = json.loads((bundle / "timing.json").read_text())["provenance"]["units"]
        self.assertEqual(prov["u-1"]["sentence_mapping"], {"a1": "single", "a2": "longest"})
        self.assertEqual(prov["u-2"]["sentence_mapping"], {"a3": "longest"})

    def test_next_action_says_staging_needs_the_film_profile(self):
        import inspect
        self.assertIn("--profile film", cli.STAGING_NOTE)
        self.assertIn("interface-notes/2026-11-27-audio-bundle-sentences-chapters.md", cli.STAGING_NOTE)
        self.assertEqual(inspect.getsource(cli.next_action).count("STAGING_NOTE"), 2)  # both bundle steps

    def test_film_profile_is_still_selectable_and_unchanged(self):
        self.reviewed()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", bundle, "--dry")
        self.assertEqual(code, 0, out)
        row = json.loads((bundle / "timing.json").read_text())["units"][0]
        self.assertEqual(set(row), {"unit_id", "mp3", "segments"})
        self.assertNotIn("profile", json.loads((bundle / "timing.json").read_text())["provenance"])

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

    def test_qc_runs_the_cinematic_gates_on_a_shots_film(self):
        self.init_and_plan()
        fd = self.root / "film" / "film-01"
        for sub in ("shots", "stills", "voice", "audio"):
            (fd / sub).mkdir(parents=True)
        video = fd / "film-01.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:d=4:r=24",
                        "-f", "lavfi", "-i", "sine=f=220:d=4:r=48000", "-shortest", "-pix_fmt", "yuv420p",
                        str(video)], check=True)
        (fd / "shots" / "s1.json").write_text(json.dumps({"scene_id": "s1", "seconds": 4.0, "shots": [
            {"n": 1, "motion": "glide", "start": 0.0, "end": 4.0, "sound": {"sfx": []}}]}))
        Record.load(self.root).add_artifact("film", video, {"target": "film-01", "mode": "shots", "scenes": ["s1"]})
        code, _ = run("qc", "--root", self.root)
        report = json.loads((self.root / "qc" / "report.json").read_text())
        item = report["items"]["film-01"]
        for gate in ("new_info", "holds", "black_bars", "hitches", "flashes"):
            self.assertIn(gate, item["checks"])
        self.assertIn("margin", item["not_run"])                       # no scene mix or voice on disk
        self.assertNotIn("margin", item["checks"])
        self.assertEqual(report["result"], "fail")                      # a gate that cannot run never passes
        self.assertEqual(code, 5)
        for gate in ("margin", "captions", "peak_silence"):
            self.assertIn(f"film-01:not_run:{gate}", report["failed"])
        self.assertFalse(cli._qc_passed(Record.load(self.root)))

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
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", bundle)
        self.assertNotEqual(code, 0)
        self.assertIn("score", out)
        self.assertIn("--dry", out)
        self.assertFalse(bundle.exists())
        self.assertFalse((self.root / "maison").exists())

    def test_bundle_audio_refuses_missing_chapter_score(self):
        self.reviewed()
        scores = self.scores()
        (scores / "u-2.wav").unlink()
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "bundle",
                        "--score-dir", scores, "--score-route", "vcsl")
        self.assertNotEqual(code, 0)
        self.assertIn("u-2", out)
        self.assertFalse((self.d / "bundle").exists())

    def test_bundle_audio_records_score_route_and_licence(self):
        """R24: the evidence draft names the score route and its licence for the clearance record."""
        self.reviewed()
        scores = self.scores()
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b0", "--score-dir", scores)
        self.assertNotEqual(code, 0)
        self.assertIn("--score-route", out)
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b1", "--score-dir", scores,
                        "--score-route", "ace-step:music-none")
        self.assertNotEqual(code, 0)
        self.assertFalse((self.d / "b1").exists())
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b2", "--score-dir", scores,
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
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b", "--score-dir",
                        self.scores(), "--score-route", f"ace-step:{music}")
        self.assertEqual(code, 0, out)
        ev = json.loads((self.root / "maison" / "audiovisual-clearance-evidence.draft.json").read_text())
        self.assertEqual((ev["music"]["route"], ev["music"]["licence"], ev["music"]["music_job_id"]),
                         (f"ace-step:{music}", "Apache-2.0", music))
        self.assertIn("ACE-Step", ev["music"]["source_and_licence"])

    def test_bundle_audio_dry_is_recorded(self):
        self.reviewed()
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "bundle", "--dry")
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
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", bundle, "--dry")
        self.assertNotEqual(code, 0)
        self.assertIn("qc", out)  # R26: no passing qc of an assembled film yet
        rec = Record.load(self.root)  # even with one faked, the narration must be imported
        (self.root / "film" / "film-01").mkdir(parents=True)
        (self.root / "film" / "film-01" / "film-01.mp4").write_bytes(b"x")
        rec.add_artifact("film", self.root / "film" / "film-01" / "film-01.mp4", {"target": "film-01"})
        rec.event("qc", "pass", {"failed": []})
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", bundle, "--dry")
        self.assertNotEqual(code, 0)
        self.assertIn("narration not imported", out)
        self.assertFalse(bundle.exists())
        self.assertFalse((self.root / "maison").exists())

    def test_bundle_audio_writes_measured_timing_with_provenance(self):
        job_id, folder, units = self.reviewed()
        scores = self.scores()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", bundle, "--score-dir", scores, "--score-route", "vcsl")
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


class StorytellerCliTests(unittest.TestCase):
    """Owner 2026-11-24: expressive storytelling, candidate presets and the audition job."""
    setUp = CliTests.setUp
    fake_job, noise = RoundTwo.fake_job, RoundTwo.noise
    init_and_plan = CliTests.init_and_plan
    fake_colab_outputs = CliTests.fake_colab_outputs

    def job(self, *flags):
        return run("job", "narration", "--root", self.root, "--rates", self.rates, *flags)

    def job_json(self, job_dir):
        with zipfile.ZipFile(job_dir / "inputs.zip") as z:
            return json.loads(z.read("job.json"))

    def only_job(self):
        return next((self.root / "jobs").iterdir())

    def test_expressive_job_records_its_style(self):
        self.init_and_plan()
        code, out = self.job("--expressive")
        self.assertEqual(code, 0, out)
        job = self.job_json(self.only_job())
        self.assertEqual(job["voice_style"], {"group": True, "pauses": True, "direct": True})
        texts = [u["text"] for u in job["units"]]
        self.assertIn("Every afternoon the children played in the garden. It was large and lovely.", texts)
        self.assertTrue(all("speaks in a" in u["description"] for u in job["units"]))
        ev = [e for e in Record.load(self.root).data["events"] if e["result"] == "job_target"][-1]
        self.assertEqual(ev["detail"]["voice_style"], job["voice_style"])

    def test_directions_need_expressive_and_known_units(self):
        self.init_and_plan()
        d = self.d / "directions.json"
        d.write_text(json.dumps({"s001-002": {"emotion": "Sad"}}))
        code, out = self.job("--directions", d)
        self.assertNotEqual(code, 0)
        self.assertIn("--expressive", out)
        d.write_text(json.dumps({"nope-001": {"emotion": "Sad"}}))
        code, out = self.job("--expressive", "--directions", d)
        self.assertNotEqual(code, 0)
        self.assertIn("unknown unit", out)
        self.assertFalse((self.root / "jobs").exists())

    def test_list_units_prints_keys_and_builds_nothing(self):
        self.init_and_plan()
        code, out = self.job("--expressive", "--list-units")
        self.assertEqual(code, 0, out)
        self.assertIn("-001", out)
        self.assertIn("It was large and lovely.", out)
        self.assertFalse((self.root / "jobs").exists())

    def test_candidate_storyteller_preset_is_refused_for_production(self):
        self.init_and_plan()
        code, out = self.job("--voice", "mary::storyteller")
        self.assertNotEqual(code, 0)
        self.assertIn("audition", out)
        code, out = self.job("--voice", "arjun::storyteller")
        self.assertNotEqual(code, 0)
        self.assertIn("language", out)
        self.assertFalse((self.root / "jobs").exists())

    def test_owner_selected_storyteller_preset_is_used(self):
        self.init_and_plan()
        roster = json.loads(cli.STORYTELLER_ROSTER.read_text(encoding="utf-8"))
        mary = next(p for p in roster["presets"]["en"] if p["preset_key"] == "mary::storyteller")
        mary["status"] = "OWNER_SELECTED"
        path = self.d / "storyteller.json"
        path.write_text(json.dumps(roster), encoding="utf-8")
        with mock.patch.object(cli, "STORYTELLER_ROSTER", path):
            code, out = self.job("--voice", "mary::storyteller", "--expressive")
        self.assertEqual(code, 0, out)
        job = self.job_json(self.only_job())
        self.assertTrue(all(u["description"].startswith(mary["description"] + " Mary speaks in a")
                            for u in job["units"]))
        ev = [e for e in Record.load(self.root).data["events"] if e["result"] == "job_target"][-1]
        self.assertEqual(ev["detail"]["voice"], "mary::storyteller")

    def test_storyteller_roster_candidates(self):
        roster = json.loads(cli.STORYTELLER_ROSTER.read_text(encoding="utf-8"))
        keys = {lang: [p["preset_key"] for p in roster["presets"][lang]] for lang in ("bn", "en")}
        self.assertEqual(keys, {"bn": ["arjun::storyteller", "aditi::storyteller", "arnav::storyteller"],
                                "en": ["thoma::storyteller", "mary::storyteller", "tisha::storyteller"]})
        for lang, presets in roster["presets"].items():
            for p in presets:
                self.assertEqual(p["status"], "CANDIDATE \u2014 owner audition required")
                low = p["description"].lower()
                for phrase in ("highly expressive", "very clear audio", "no background noise",
                               "storyteller"):
                    self.assertIn(phrase, low, p["preset_key"])
                self.assertNotIn("even manner", low)
                self.assertTrue(p["description"].startswith(p["speaker"] + " "))
                self.assertEqual(p["temperature"], 0.91)
        self.assertEqual(roster["model"]["revision"], "7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca")

    def audition_file(self):
        path = self.d / "audition.json"
        path.write_text(json.dumps({"passages": {
            "narration": "The giant came home. He was tired.",
            "dialogue": "\u201cWho are you?\u201d he asked. \u201cA child.\u201d",
            "emotional": "She wept. The garden was gone forever."},
            "directions": {"emotional-001": {"emotion": "Sad", "clause": "Slower, close to tears."}}}))
        return path

    def test_audition_job_builds_imports_and_never_narrates_a_film(self):
        self.init_and_plan()
        code, out = self.job("--audition", self.audition_file())
        self.assertEqual(code, 0, out)
        self.assertIn("audition", out)
        job_dir = self.only_job()
        job = self.job_json(job_dir)
        variants = job["audition"]["variants"]
        self.assertEqual(variants, {"control": "en_tisha::story",
                                    "thoma-storyteller": "thoma::storyteller",
                                    "mary-storyteller": "mary::storyteller",
                                    "tisha-storyteller": "tisha::storyteller"})
        self.assertIs(job["audition"]["film_narration"], False)
        keys = {u["unit_key"] for u in job["units"]}
        for v in variants:
            for passage in ("narration", "dialogue", "emotional"):
                self.assertIn(f"{v}__{passage}-001", keys)
        ev = [e for e in Record.load(self.root).data["events"] if e["result"] == "job_target"][-1]
        self.assertEqual(ev["detail"]["target"], "audition")
        folder, _ = self.fake_colab_outputs(job_dir.name, job_dir)
        code, out = run("import", job_dir.name, "--root", self.root, "--from", folder, "--units", 0.5)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "narration" / job_dir.name / "mary-storyteller__dialogue-001.wav").is_file())
        code, out = run("status", "--root", self.root)
        self.assertIn("job narration", out.split("Next:")[-1])  # film narration still to build
        code, out = run("film", "--root", self.root, "--logo", self.d / "l.png", "--end-card",
                        self.d / "e.png", "--score", self.d / "s.wav", "--score-route", "vcsl")
        self.assertNotEqual(code, 0)
        self.assertIn("needs imported narration", out)

    def test_audition_refuses_film_or_reel_flags_and_unknown_candidates(self):
        self.init_and_plan()
        code, out = self.job("--audition", self.audition_file(), "--expressive")
        self.assertNotEqual(code, 0)
        bad = json.loads(self.audition_file().read_text())
        bad["candidates"] = ["arjun::storyteller"]
        path = self.d / "bad.json"
        path.write_text(json.dumps(bad))
        code, out = self.job("--audition", path)
        self.assertNotEqual(code, 0)
        self.assertIn("language", out)
        self.assertFalse((self.root / "jobs").exists())

    def test_expressive_narration_assembles_film_and_bundles_audio(self):
        self.init_and_plan()
        code, out = self.job("--expressive")
        self.assertEqual(code, 0, out)
        job_dir = self.only_job()
        folder, units = self.fake_colab_outputs(job_dir.name, job_dir)
        code, out = run("import", job_dir.name, "--root", self.root, "--from", folder, "--units", 1)
        self.assertEqual(code, 0, out)
        plan = json.loads((self.root / "plan.json").read_text())
        scenes = plan["plan"]["films"][0]["scenes"]

        def stills(rec, job_id, jd, out):
            for i, sc in enumerate(scenes):
                Image.new("RGB", (320, 180), (60 * i, 90, 120)).save(out / f"{sc['scene_id']}-1.png")
        self.fake_job("stills", "film-01", stills)
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(self.d / "logo.png")
        Image.new("RGB", (320, 180), (0, 0, 0)).save(self.d / "end.png")
        bed = self.d / "bed.wav"
        self.noise(bed, 30)
        code, out = run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                        self.d / "end.png", "--score", bed, "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        timing = json.loads((self.root / "film" / "film-01" / "timing.json").read_text())
        self.assertEqual([t["unit_key"] for t in timing["units"]], [u["unit_key"] for u in units])
        rec = Record.load(self.root)
        rec.event("qc", "pass", {"failed": []})
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertEqual(code, 0, out)


class ImportTakeCliTests(unittest.TestCase):
    """Owner 2026-11-24: ElevenLabs Eleven v3 narration, one take per scene, sliced and filed."""
    setUp = CliTests.setUp
    fake_job, noise, wav = RoundTwo.fake_job, RoundTwo.noise, RoundTwo.wav
    init_and_plan = CliTests.init_and_plan
    VOICE = ("--engine", "elevenlabs", "--model", "eleven_v3", "--voice-id", "XdbTvfQSkW1sgZYKdZdF",
             "--voice-name", "Sakshi \u2013 Warm Bedtime Storyteller")

    def scenes(self):
        return json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"]

    def write_take(self, key, units, seconds=0.9, gap_s=0.35, tags=True):
        """<key>.txt tagged script and <key>.mp3: one tone per unit, separated by silences."""
        from tests.test_take import gap, tone, write_wav
        import numpy as np
        self.scripts.mkdir(exist_ok=True)
        self.audio.mkdir(exist_ok=True)
        text = " ".join(u["text"] for u in units)
        script = " [pause] ".join(u["text"] for u in units) if tags else text
        (self.scripts / f"{key}.txt").write_text("[softly] " + script + "\n", encoding="utf-8")
        parts = []
        for i, u in enumerate(units):
            parts += [tone(seconds, 200 + 30 * i)] + ([gap(gap_s)] if i < len(units) - 1 else [])
        wav = self.d / f"{key}-src.wav"
        write_wav(wav, np.concatenate([gap(0.05)] + parts + [gap(0.05)]))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a",
                        "128k", str(self.audio / f"{key}.mp3")], check=True)

    def film_takes(self):
        from eav.voice import voice_units
        self.scripts, self.audio = self.d / "scripts", self.d / "takes"
        for sc in self.scenes():
            self.write_take(sc["scene_id"], voice_units(sc, {"description": ""}, None, "en"))

    def import_take(self, target="film-01", *extra):
        return run("import-take", target, "--root", self.root, "--scripts", self.scripts,
                   "--audio", self.audio, *self.VOICE, "--credits", 812, *extra)

    def test_film_take_imports_and_assembles_with_scene_end_pauses_only(self):
        self.init_and_plan()
        self.film_takes()
        code, out = self.import_take()
        self.assertEqual(code, 0, out)
        rec = Record.load(self.root)
        job = [e for e in rec.data["events"] if e["result"] == "job_target"][-1]["detail"]
        self.assertEqual(job["target"], "film-01")
        self.assertEqual(job["engine"], "elevenlabs")
        self.assertEqual(job["model"], "eleven_v3")
        self.assertEqual(job["voice_id"], "XdbTvfQSkW1sgZYKdZdF")
        self.assertEqual(job["credits"], 812)
        self.assertEqual(job["voice_style"], {"continuous": True})
        self.assertEqual(job["estimated_boundaries"], [])
        job_id = job["job_id"]
        accepted = [e for e in rec.data["events"] if e["result"] == "accepted"][-1]["detail"]
        self.assertEqual((accepted["job_id"], accepted["actual_units"]), (job_id, 0))
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual([(e["job_id"], e["units"], e["state"]) for e in ledger], [(job_id, 0, "settled")])
        from eav.voice import voice_units
        units = [u for sc in self.scenes() for u in voice_units(sc, {"description": ""}, None, "en")]
        wav_dir = self.root / "narration" / job_id
        self.assertEqual(sorted(p.stem for p in wav_dir.glob("*.wav")), sorted(u["unit_key"] for u in units))
        manifest = json.loads((self.root / "jobs" / job_id / "take-manifest.json").read_text())
        for name, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256((self.root / name).read_bytes()).hexdigest(), digest, name)
        for sc in manifest["scenes"]:
            self.assertEqual(sc["audio_sha256"],
                             hashlib.sha256((self.audio / f"{sc['key']}.mp3").read_bytes()).hexdigest())
            self.assertEqual(sc["script_sha256"],
                             hashlib.sha256((self.scripts / f"{sc['key']}.txt").read_bytes()).hexdigest())
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{job_id} narration film-01: imported", out)

        scenes = self.scenes()

        def stills(rec, jid, jd, o):
            for i, sc in enumerate(scenes):
                Image.new("RGB", (320, 180), (60 * i, 90, 120)).save(o / f"{sc['scene_id']}-1.png")
        self.fake_job("stills", "film-01", stills)
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(self.d / "logo.png")
        Image.new("RGB", (320, 180), (0, 0, 0)).save(self.d / "end.png")
        bed = self.d / "bed.wav"
        self.noise(bed, 30)
        code, out = run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                        self.d / "end.png", "--score", bed, "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        timing = json.loads((self.root / "film" / "film-01" / "timing.json").read_text())["units"]
        self.assertEqual([t["unit_key"] for t in timing], [u["unit_key"] for u in units])
        durs = {u["unit_key"]: cli.film._duration(wav_dir / f"{u['unit_key']}.wav") for u in units}
        last_of_first = [u["unit_key"] for u in units if u["unit_key"].startswith(scenes[0]["scene_id"])][-1]
        for a, b in zip(timing, timing[1:]):
            gap_s = b["start"] - a["end"]
            self.assertAlmostEqual(gap_s, 1.2 if a["unit_key"] == last_of_first else 0.0, delta=0.002)
        self.assertAlmostEqual(timing[-1]["end"], sum(durs.values()) + 1.2, delta=0.01)
        srt = (self.root / "film" / "film-01" / "film-01.srt").read_text()
        self.assertEqual(srt.count(" --> "), len(units))
        Record.load(self.root).event("qc", "pass", {"failed": []})
        code, out = run("bundle-audio", "--profile", "film", "--root", self.root, "--out", self.d / "b", "--dry")
        self.assertEqual(code, 0, out)
        draft = json.loads((self.root / "maison" / cli.EVIDENCE_DRAFT).read_text())
        self.assertEqual(draft["generators"], [{
            "model": "elevenlabs/eleven_v3", "engine": "elevenlabs", "job_ids": [job_id],
            "licence": "ElevenLabs paid-plan commercial licence (owner decision 2026-11-24)",
            "voice": "Sakshi \u2013 Warm Bedtime Storyteller", "voice_id": "XdbTvfQSkW1sgZYKdZdF",
            "credits": 812}])

    def test_refusals_leave_nothing_behind(self):
        self.init_and_plan()
        self.film_takes()
        first = self.scenes()[0]["scene_id"]
        cases = []
        (self.audio / f"{first}.mp3").rename(self.d / "held.mp3")
        cases.append(("missing audio", "film-01"))
        cases.append(("unknown target", "film-09"))
        for what, target in cases:
            code, out = self.import_take(target)
            self.assertNotEqual(code, 0, what)
            self.assertIn("STOP", out, what)
        (self.d / "held.mp3").rename(self.audio / f"{first}.mp3")
        good = (self.scripts / f"{first}.txt").read_text(encoding="utf-8")
        (self.scripts / f"{first}.txt").write_text(good.replace("garden", "yard"), encoding="utf-8")
        code, out = self.import_take()
        self.assertNotEqual(code, 0)
        self.assertIn("differs from the book text", out)
        (self.scripts / f"{first}.txt").unlink()
        code, out = self.import_take()
        self.assertNotEqual(code, 0)
        self.assertIn("script", out)
        (self.scripts / f"{first}.txt").write_text(good, encoding="utf-8")
        code, out = run("import-take", "film-01", "--root", self.root, "--scripts", self.scripts,
                        "--audio", self.audio, *self.VOICE, "--credits", -3)
        self.assertNotEqual(code, 0)
        self.assertFalse((self.root / "narration").exists())
        self.assertFalse(self.ledger.exists() and json.loads(self.ledger.read_text()))
        self.assertFalse([e for e in Record.load(self.root).data["events"] if e["result"] == "job_target"])

    def test_refused_while_a_colab_narration_job_waits(self):
        self.init_and_plan()
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)
        self.film_takes()
        code, out = self.import_take()
        self.assertNotEqual(code, 0)
        self.assertIn("supersede", out)
        self.assertFalse((self.root / "narration").exists())
        job_id = next((self.root / "jobs").iterdir()).name
        self.assertEqual(run("supersede", job_id, "--root", self.root, "--reason", "ElevenLabs")[0], 0)
        code, out = self.import_take()
        self.assertEqual(code, 0, out)

    def test_reel_take_is_one_continuous_take(self):
        self.init_and_plan()
        path = self.d / "reel.json"
        path.write_text(json.dumps(REEL))
        self.assertEqual(run("reel", 1, "--root", self.root, "--script", path)[0], 0)
        from eav.voice import voice_units
        units = voice_units(cli._reel_scene(REEL, 1), {"description": ""}, None, "en")
        self.scripts, self.audio = self.d / "scripts", self.d / "takes"
        self.write_take("reel-1", units, seconds=4.3, gap_s=0.35)  # 13 x 4.3 + 12 x 0.35 + 0.1
        code, out = self.import_take("reel-1")
        self.assertEqual(code, 0, out)
        code, out = run("reel", 1, "--root", self.root, "--plan-shots")
        self.assertEqual(code, 0, out)
        narr = self.root / "reels" / "reel-1" / "narration.wav"
        take = cli.film._duration(self.d / "reel-1-src.wav")  # the decoded take, without mp3 padding
        self.assertAlmostEqual(cli.film._duration(narr), take, delta=0.03)  # nothing added

    def test_reel_take_refused_once_shots_are_planned(self):
        self.test_reel_take_is_one_continuous_take()
        code, out = self.import_take("reel-1")
        self.assertNotEqual(code, 0)
        self.assertIn("planned", out)


class SentenceSanity(unittest.TestCase):
    def test_fixture_a2_has_two_sentences(self):
        self.assertEqual(len(sentences(PARAS[1][2])), 2)


if __name__ == "__main__":
    unittest.main()


class ImportPassagesCliTests(unittest.TestCase):
    """Eleven v4 narration (owner 26 Nov): one take per passage, retimed, checked and joined per scene.
    The v4 model id is read from <root>/voice.json; "eleven_v4_test" below is a test value only."""
    V4 = "eleven_v4_test"
    VOICE4 = ("--engine", "elevenlabs", "--model", V4, "--voice-id", "XdbTvfQSkW1sgZYKdZdF",
              "--voice-name", "Sakshi – Warm Bedtime Storyteller")
    PASSAGES = {"f01s001": ["The Garden Every afternoon the children played in the garden.",
                            "It was large and lovely."],
                "f01s002": ["The giant came back. He had been away for seven years."]}
    setUp0 = CliTests.setUp
    fake_job, noise, wav = RoundTwo.fake_job, RoundTwo.noise, RoundTwo.wav
    init_and_plan = CliTests.init_and_plan
    film_ready, shots_end_to_end = RoundTwo.film_ready, CliTests.shots_end_to_end
    VOICE = ImportTakeCliTests.VOICE
    scenes, write_take = ImportTakeCliTests.scenes, ImportTakeCliTests.write_take
    film_takes, import_take = ImportTakeCliTests.film_takes, ImportTakeCliTests.import_take

    def setUp(self):
        self.setUp0()
        self.init_and_plan()
        self.scripts, self.audio = self.d / "scripts", self.d / "takes"
        (self.root / "voice.json").write_text(json.dumps({"model_id": self.V4}), encoding="utf-8")
        for key, texts in self.PASSAGES.items():
            for n, text in enumerate(texts, 1):
                self.write_passage(f"{key}-p{n:02d}", text)

    def write_passage(self, stem, text, tagged=None, pace=0.025):
        """Takes last `pace` s per character (two tones and a gap), so a run's passages share one rate."""
        from tests.test_take import gap, tone, write_wav
        import numpy as np
        self.scripts.mkdir(exist_ok=True)
        self.audio.mkdir(exist_ok=True)
        (self.scripts / f"{stem}.txt").write_text(tagged or text, encoding="utf-8")
        wav = self.d / f"{stem}-src.wav"
        half = max(0.3, len(text) * pace / 2 - 0.2)
        write_wav(wav, np.concatenate([gap(0.05), tone(half, 210), gap(0.4), tone(half, 190), gap(0.05)]))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "128k",
                        str(self.audio / f"{stem}.mp3")], check=True)

    def import_passages(self, *extra, voice=None):
        return run("import-take", "film-01", "--root", self.root, "--scripts", self.scripts, "--audio", self.audio,
                   *(voice or self.VOICE4), "--credits", 420, "--cps", 5, *extra)

    @staticmethod
    def passing(take, expected_s, prof, prev_tail=None):
        return {"pass": True, "failures": [], "metrics": {"duration_s": expected_s}}

    def test_import_take_accepts_v4_per_passage_takes(self):
        seen = []

        def check(take, expected_s, prof, prev_tail=None):
            seen.append((take.name, prev_tail.name if prev_tail else None))
            return self.passing(take, expected_s, prof, prev_tail)
        with mock.patch.object(cli.voicecheck, "check", side_effect=check):
            code, out = self.import_passages()
        self.assertEqual(code, 0, out)
        voice = self.root / "film" / "film-01" / "voice"
        from tests._media import samples
        for key in self.PASSAGES:
            self.assertGreater(len(samples(voice / f"{key}.wav")), 48000, key)
        # each passage was retimed then checked; the join check looks at the passage before it in the scene
        self.assertEqual(seen, [("f01s001-p01.wav", None), ("f01s001-p02.wav", "f01s001-p01.wav"),
                                ("f01s002-p01.wav", None)])
        work = voice / "passages"
        # the expected duration is characters / the run's own median measured rate (not the --cps guess)
        import statistics
        from eav import retime
        ids = ("f01s001-p01", "f01s001-p02", "f01s002-p01")
        chars = [len(t) for ts in self.PASSAGES.values() for t in ts]
        durs = [len(retime.read(work / f"{n}.wav")) / retime.SR for n in ids]
        rate = statistics.median(c / d for c, d in zip(chars, durs))
        for n, c in zip(ids, chars):
            got = json.loads((work / f"{n}.voicecheck.json").read_text())["expected_s"]
            self.assertAlmostEqual(got, c / rate, places=2)
        self.assertTrue((work / "voicecheck-profile.json").is_file())
        self.assertTrue((work / "f01s001-p01.voicecheck.json").is_file())
        manifest = json.loads((voice / "f01s001.passages.json").read_text())
        self.assertEqual((manifest["model"], manifest["voice_id"], manifest["credits"]),
                         (self.V4, "XdbTvfQSkW1sgZYKdZdF", 420))
        self.assertEqual(manifest["voice_json_sha256"],
                         hashlib.sha256((self.root / "voice.json").read_bytes()).hexdigest())
        self.assertEqual(len(manifest["join"]["seams"]), 1)
        self.assertEqual([p["id"] for p in manifest["passages"]], ["f01s001-p01", "f01s001-p02"])
        self.assertEqual(manifest["join"]["crossfade_ms"], 10)
        for p in manifest["passages"]:
            self.assertEqual(p["take_sha256"], hashlib.sha256((self.audio / f"{p['id']}.mp3").read_bytes()).hexdigest())
        rec = Record.load(self.root)
        ev = [e for e in rec.data["events"] if e["result"] == "passages_joined"][-1]["detail"]
        self.assertEqual((ev["target"], ev["model"], ev["scenes"]), ("film-01", self.V4, ["f01s001", "f01s002"]))
        self.assertEqual(sorted(a["path"] for a in rec.data["artifacts"] if a["kind"] == "scene_voice"),
                         ["film/film-01/voice/f01s001.wav", "film/film-01/voice/f01s002.wav"])

    def test_failed_passage_blocks_only_its_own_scene_and_credits_are_recorded_every_run(self):
        def check(take, expected_s, prof, prev_tail=None):
            bad = take.stem == "f01s001-p02"
            return {"pass": not bad, "failures": ["pitch_spread"] if bad else [], "metrics": {}}
        with mock.patch.object(cli.voicecheck, "check", side_effect=check):
            code, out = self.import_passages()
        self.assertNotEqual(code, 0)
        self.assertIn("f01s001-p02", out)
        self.assertIn("pitch_spread", out)
        voice = self.root / "film" / "film-01" / "voice"
        self.assertTrue((voice / "f01s002.wav").is_file())       # the other scene still joins
        self.assertFalse((voice / "f01s001.wav").exists())       # the failed scene never does
        events = Record.load(self.root).data["events"]
        checked = [e["detail"] for e in events if e["result"] == "passages_checked"]
        self.assertEqual([(c["credits"], c["joined"], list(c["failed"])) for c in checked],
                         [(420, ["f01s002"], ["f01s001"])])       # the failed run's credits are on record
        # redo only the failure: the same call (credits of that regeneration) joins, reusing the saved profile
        self.write_passage("f01s001-p02", self.PASSAGES["f01s001"][1])
        with mock.patch.object(cli.voicecheck, "check", side_effect=self.passing), \
                mock.patch.object(cli.voicecheck, "profile", side_effect=AssertionError("profile re-measured")):
            code, out = run("import-take", "film-01", "--root", self.root, "--scripts", self.scripts,
                            "--audio", self.audio, *self.VOICE4, "--credits", 35, "--cps", 5)
        self.assertEqual(code, 0, out)
        self.assertTrue((voice / "f01s001.wav").is_file())
        checked = [e["detail"]["credits"] for e in Record.load(self.root).data["events"]
                   if e["result"] == "passages_checked"]
        self.assertEqual(checked, [420, 35])

    def test_whisper_words_route_on_passages(self):
        """--transcripts keyed by passage id: a dropped sentence fails only that passage; a passage with no
        transcript (or one made for another file) is recorded as not run, never as checked."""
        from eav import voicecheck
        plain = {"f01s001-p01": "The Garden Every afternoon the children played in the garden.",
                 "f01s001-p02": "It was large and lovely.", "f01s002-p01": "The giant came back. He had been away for seven years."}
        sha = lambda pid: hashlib.sha256((self.audio / f"{pid}.mp3").read_bytes()).hexdigest()
        tr = self.d / "transcripts.json"
        tr.write_text(json.dumps({"schema": voicecheck.TRANSCRIPT_SCHEMA, "model": {"repo": "openai/whisper-small"}, "takes": {
            "f01s001-p01": {"sha256": sha("f01s001-p01"), "text": "The Garden Every afternoon"},   # dropped words
            "f01s001-p02": {"sha256": sha("f01s001-p02"), "text": plain["f01s001-p02"]},
            "f01s002-p01": {"sha256": "0" * 64, "text": plain["f01s002-p01"]}}}), encoding="utf-8")
        real = voicecheck.check

        def words_only(*a, **k):   # the synthetic tones fail the pitch gates; keep only what this test is about
            r = real(*a, **k)
            r["failures"] = [c for c in r["failures"] if c == "words"]
            r["pass"] = False if r["failures"] else (None if r.get("not_run") else True)
            return r
        with mock.patch.object(cli.voicecheck, "check", side_effect=words_only):
            code, out = self.import_passages("--transcripts", tr)
        work = self.root / "film" / "film-01" / "voice" / "passages"
        res = {n: json.loads((work / f"{n}.voicecheck.json").read_text()) for n in plain}
        self.assertNotIn("words", res["f01s001-p02"]["failures"])
        self.assertEqual(res["f01s001-p02"]["metrics"]["words"]["cer"], 0.0)
        self.assertEqual(res["f01s002-p01"]["not_run"], ["words"])
        self.assertIn("Word check NOT RUN", out)
        prof = json.loads((work / "voicecheck-profile.json").read_text())   # accepted takes only
        self.assertEqual(prof["words_cer_n"], 1)
        self.assertEqual(list(prof["words_cers"]), ["f01s001-p02"])
        self.assertEqual(res["f01s001-p01"]["warnings"], ["words"])   # provisional ceiling: warning, not a redo
        self.assertEqual(res["f01s001-p01"]["failures"], [])
        code, out = self.import_passages("--transcripts", self.d / "nope.json")
        self.assertNotEqual(code, 0)
        self.assertIn("not a transcripts.json", out)

    def test_duration_is_checked_by_the_real_gate_against_the_runs_own_pace(self):
        """Unmocked voicecheck: passages at one pace meet their expected duration; an out-of-pace take misses."""
        self.write_passage("f01s001-p02", self.PASSAGES["f01s001"][1], pace=0.07)  # 2.8x slower than the run
        code, out = self.import_passages()
        self.assertNotEqual(code, 0)  # the synthetic tones fail other gates (pitch); only `duration` is asked
        work = self.root / "film" / "film-01" / "voice" / "passages"
        codes = {n: json.loads((work / f"{n}.voicecheck.json").read_text())["failures"]
                 for n in ("f01s001-p01", "f01s001-p02", "f01s002-p01")}
        self.assertNotIn("duration", codes["f01s001-p01"])
        self.assertNotIn("duration", codes["f01s002-p01"])
        self.assertIn("duration", codes["f01s001-p02"])

    def test_fewer_than_three_passages_make_duration_a_warning(self):
        code, out = self.import_passages("--scene", "f01s002")
        self.assertNotEqual(code, 0)  # tones fail the pitch gates, not duration
        res = json.loads((self.root / "film" / "film-01" / "voice" / "passages" / "f01s002-p01.voicecheck.json").read_text())
        self.assertNotIn("duration", res["failures"])
        self.assertIn("fewer than 3 passages", out)

    def test_scene_option_and_scenes_without_passage_scripts(self):
        with mock.patch.object(cli.voicecheck, "check", side_effect=self.passing):
            code, out = self.import_passages("--scene", "f01s002")
        self.assertEqual(code, 0, out)
        voice = self.root / "film" / "film-01" / "voice"
        self.assertEqual([p.name for p in voice.glob("*.wav")], ["f01s002.wav"])
        code, out = self.import_passages("--scene", "nope")
        self.assertNotEqual(code, 0)
        (self.scripts / "f01s001-p01.txt").unlink()
        (self.scripts / "f01s001-p02.txt").unlink()
        (voice / "f01s002.wav").unlink()
        (voice / "f01s002.passages.json").unlink()
        with mock.patch.object(cli.voicecheck, "check", side_effect=self.passing):
            code, out = self.import_passages()   # no --scene: only scenes whose p01 is present
        self.assertEqual(code, 0, out)
        self.assertEqual([p.name for p in voice.glob("*.wav")], ["f01s002.wav"])

    def test_model_must_be_listed_in_the_title_voice_settings(self):
        (self.root / "voice.json").unlink()
        code, out = self.import_passages()
        self.assertNotEqual(code, 0)
        self.assertIn("voice.json", out)
        (self.root / "voice.json").write_text(json.dumps({"model_id": "eleven_other"}), encoding="utf-8")
        code, out = self.import_passages()
        self.assertNotEqual(code, 0)
        self.assertIn("not the approved narration engine", out)
        # eleven_v3 may not be the "v4" id: it would send the one-take route down the passage path
        (self.root / "voice.json").write_text(json.dumps({"model_id": "eleven_v3"}), encoding="utf-8")
        code, out = self.import_passages()
        self.assertNotEqual(code, 0)
        self.assertIn("eleven_v3", out)
        self.assertFalse((self.root / "film" / "film-01" / "voice").exists())

    def test_v3_one_take_per_scene_import_is_unchanged(self):
        (self.root / "voice.json").write_text("{ not json", encoding="utf-8")  # never blocks the v3 route
        self.film_takes()
        code, out = self.import_take()
        self.assertEqual(code, 0, out)
        self.assertFalse((self.root / "film" / "film-01" / "voice").exists())
        # v3 still wants <scene>.txt, not passage files
        for p in self.scripts.glob("f01s001.txt"):
            p.unlink()
        code, out = self.import_take("film-01")
        self.assertNotEqual(code, 0)

    def test_script_rules_stop_the_import(self):
        self.write_passage("f01s001-p01", self.PASSAGES["f01s001"][0],
                           "[softly] The Garden Every afternoon the children played in the garden.")
        with mock.patch.object(cli.voicecheck, "check", side_effect=self.passing):
            code, out = self.import_passages()
        self.assertNotEqual(code, 0)
        self.assertIn("bare [softly]", out)
        self.write_passage("f01s001-p01", self.PASSAGES["f01s001"][0], "[warmly] The Garden Every afternoon the children played in the garden.")
        with mock.patch.object(cli.voicecheck, "check", side_effect=self.passing):
            code, out = self.import_passages()
        self.assertNotEqual(code, 0)
        self.assertIn("carry", out)  # the next passage dropped [warmly]

    def test_missing_passage_take_and_a_gap_in_numbering_stop(self):
        (self.audio / "f01s001-p02.mp3").unlink()
        code, out = self.import_passages()
        self.assertNotEqual(code, 0)
        self.assertIn("f01s001-p02", out)

    def test_a_hand_placed_scene_wav_blocks_only_its_own_scene(self):
        voice = self.root / "film" / "film-01" / "voice"
        voice.mkdir(parents=True)
        (voice / "f01s002.wav").write_bytes(b"RIFF hand placed")
        with mock.patch.object(cli.voicecheck, "check", side_effect=self.passing):
            code, out = self.import_passages()
            self.assertEqual(code, 0, out)
            self.assertIn("f01s002", out)
            self.assertTrue((voice / "f01s001.wav").is_file())
            code, out = self.import_passages("--scene", "f01s002")
        self.assertNotEqual(code, 0)
        self.assertIn("f01s002.wav", out)
        self.assertEqual((voice / "f01s002.wav").read_bytes(), b"RIFF hand placed")

    def test_passages_serve_films_not_reels(self):
        code, out = run("import-take", "reel-1", "--root", self.root, "--scripts", self.scripts,
                        "--audio", self.audio, *self.VOICE4, "--credits", 1)
        self.assertNotEqual(code, 0)

    def test_split_passages_writes_the_untagged_passage_scripts_keeping_blocks(self):
        out_dir = self.d / "split"
        code, out = run("split-passages", "film-01", "--root", self.root, "--out", out_dir, "--cps", 5)
        self.assertEqual(code, 0, out)
        names = sorted(p.name for p in out_dir.glob("*.txt"))
        self.assertEqual(names, ["f01s001-p01.txt", "f01s002-p01.txt"])
        # the heading stays its own block (not joined to the sentence by a space)
        self.assertEqual((out_dir / "f01s001-p01.txt").read_text(encoding="utf-8").strip(),
                         "The Garden\n\nEvery afternoon the children played in the garden. It was large and lovely.")
        code, out = run("split-passages", "film-01", "--root", self.root, "--out", out_dir, "--cps", 5)
        self.assertNotEqual(code, 0)  # never overwrites a tagged script

    def test_film_shots_needs_no_narration_job_on_the_v4_route(self):
        with mock.patch.object(cli.voicecheck, "check", side_effect=self.passing):
            self.assertEqual(self.import_passages()[0], 0)
        rec = Record.load(self.root)
        self.assertFalse([a for a in rec.data["artifacts"] if a["kind"] == "narration"])
        self.assertFalse([e for e in rec.data["events"] if e["result"] == "job_target"])
        self.shots_end_to_end(narration=False, init=False)
