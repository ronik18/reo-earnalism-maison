"""A3: long narration/stills jobs are cut into chunks of <= 3600 forecast seconds; consumers use a
chunk group only once every chunk is imported, and then all chunks' outputs in order."""
import hashlib
import json
import re
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from eav import budget, cli, colab_jobs
from eav.record import Record
from eav.voice import voice_units
from tests.test_cli import SOURCE, run, speech_seconds

NARR = {"s_per_step": 2.0, "units_per_hour": 5.0, "steps": 1, "decode_s": 10, "export_s": 10}
# 30 stills at 4 steps: (4 x 62.7 x 30 + 300) x 1.15 = 9000 s (2.5 h); 11 stills fit 3600 s.
STILLS = {"s_per_step": 62.7, "units_per_hour": 5.0, "steps": 4, "decode_s": 240, "export_s": 60}


def _job_json(job_dir: Path) -> dict:
    with zipfile.ZipFile(job_dir / "inputs.zip") as z:
        return json.loads(z.read("job.json"))


class ChunkSizeTests(unittest.TestCase):
    def test_short_job_is_one_chunk(self):
        compute = {"kind": "stills", "steps": 4, "items": 11, "takes": 1, "decode_s": 240, "export_s": 60}
        self.assertLessEqual(budget.forecast_seconds(compute, {"stills": STILLS}), 3600)
        self.assertEqual(colab_jobs.chunk_sizes(compute, {"stills": STILLS}), [11])

    def test_two_and_a_half_hours_split_into_three(self):
        rates = {"stills": STILLS}
        compute = {"kind": "stills", "steps": 4, "items": 30, "takes": 1, "decode_s": 240, "export_s": 60}
        self.assertAlmostEqual(budget.forecast_seconds(compute, rates), 9000, delta=10)
        sizes = colab_jobs.chunk_sizes(compute, rates)
        self.assertEqual(sizes, [10, 10, 10])
        for k in sizes:
            self.assertLessEqual(budget.forecast_seconds({**compute, "items": k}, rates),
                                 colab_jobs.MAX_CHUNK_SECONDS)

    def test_music_and_reel_clips_are_never_chunked(self):
        rates = {"music": {"s_per_step": 100.0, "units_per_hour": 5.0, "decode_s": 0, "export_s": 0}}
        compute = {"kind": "music", "steps": 60, "items": 3, "takes": 1, "decode_s": 0, "export_s": 0}
        self.assertGreater(budget.forecast_seconds(compute, rates), 3600)
        self.assertEqual(colab_jobs.chunk_sizes(compute, rates), [3])

    def test_one_item_over_the_limit_is_refused(self):
        compute = {"kind": "stills", "steps": 4, "items": 2, "takes": 1, "decode_s": 0, "export_s": 0}
        with self.assertRaises(ValueError):
            colab_jobs.chunk_sizes(compute, {"stills": {**STILLS, "s_per_step": 1000.0}})


class ChunkCliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / "selfish-giant"
        self.ledger = self.d / "titles" / "allowance-ledger.json"
        self.src = self.d / "selfish-giant.json"
        self.src.write_text(json.dumps(SOURCE), encoding="utf-8")
        self.rates = self.d / "rates.json"
        self.set_rates(NARR, STILLS)
        self.assertEqual(run("init", self.src, "--root", self.root)[0], 0)
        self.assertEqual(run("plan", "--root", self.root)[0], 0)
        self.plan = json.loads((self.root / "plan.json").read_text())
        self.scenes = self.plan["plan"]["films"][0]["scenes"]
        self.units = [u for sc in self.scenes for u in voice_units(sc, {"description": ""}, None, "en")]

    def set_rates(self, narration, stills):
        self.rates.write_text(json.dumps({"narration": narration, "stills": stills}), encoding="utf-8")

    def jobs(self):
        """Job folders in build order: a group's chunks by their numeric index (A3 M5: as strings,
        -c10of12 would sort before -c2of12)."""
        def order(p):
            m = re.search(r"-c(\d+)of(\d+)", p.name)
            return (p.name[:m.start()], int(m.group(1)), p.name) if m else (p.name, 0, p.name)
        return sorted((p for p in (self.root / "jobs").iterdir()), key=order) \
            if (self.root / "jobs").is_dir() else []

    def stills_spec(self, n=30):
        keys = [f"{self.scenes[i % len(self.scenes)]['scene_id']}-{i // len(self.scenes) + 1:02d}"
                for i in range(n)]
        spec = self.d / "stills.json"
        spec.write_text(json.dumps({"items": [{"key": k, "prompt": f"still {k}", "seed": i}
                                              for i, k in enumerate(keys)]}), encoding="utf-8")
        return spec, keys

    def ledger_rows(self):
        return json.loads(self.ledger.read_text()) if self.ledger.exists() else []

    # --- requirement 2: unchanged at or under 3600 s ------------------------------------------
    def test_short_job_is_built_exactly_as_before(self):
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)
        [job_dir] = self.jobs()
        self.assertNotIn("-c1of", job_dir.name)
        job = _job_json(job_dir)
        rec = Record.load(self.root)
        preset = {k: v for k, v in self.plan["voice"].items() if k in colab_jobs.GENERATION_KEYS}
        self.assertEqual(job, {"schema": colab_jobs.JOB_SCHEMA, "kind": "narration",
                               "job_id": job_dir.name, "title": "selfish-giant",
                               "model": colab_jobs.NARRATION_REPO,
                               "units": [u for sc in self.scenes for u in voice_units(
                                   sc, {"description": self.plan["voice"]["description"], **preset},
                                   None, "en")],
                               "generation": preset, "batch": colab_jobs.DEFAULT_BATCH})
        self.assertNotIn("chunk", json.loads((job_dir / "build-manifest.json").read_text()))
        art = next(a for a in rec.data["artifacts"] if a["kind"] == "colab_job")
        self.assertNotIn("chunk", art["meta"])
        self.assertEqual(len(self.ledger_rows()), 1)

    def test_short_job_json_is_byte_identical_to_the_build_before_chunks(self):
        """A3 M4: compared with output produced by the code before chunking existed (commit
        f48d4a1, tests/fixtures/narration-job-at-f48d4a1.json), not with a dict built here."""
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--job-id", "narration-golden")
        self.assertEqual(code, 0, out)
        with zipfile.ZipFile(self.root / "jobs" / "narration-golden" / "inputs.zip") as z:
            built = z.read("job.json")
        self.assertEqual(built, (Path(__file__).parent / "fixtures" /
                                 "narration-job-at-f48d4a1.json").read_bytes())

    def test_a_job_id_already_used_as_a_job_or_group_id_is_refused(self):
        """A3 M3: one id names one thing: a --job-id that is a job id or a chunk group id here is
        refused before anything is reserved or written."""
        spec, _ = self.stills_spec()
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec, "--job-id", "stills-g")[0], 0)
        ids = [d.name for d in self.jobs()]
        self.assertEqual(ids[0], "stills-g-c1of3")
        before = (self.ledger.read_bytes(), (self.root / "record.json").read_bytes())
        for taken in ("stills-g", "stills-g-c2of3"):
            code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                            "--job-id", taken)
            self.assertEqual(code, 2, out)
            self.assertIn(f"--job-id {taken} is already a job or chunk group id", out)
        self.assertEqual((self.ledger.read_bytes(), (self.root / "record.json").read_bytes()), before)

    # --- requirements 2-4: ~2.5 h splits into 3 chunks -----------------------------------------
    def test_stills_job_of_two_and_a_half_hours_is_three_chunks(self):
        spec, keys = self.stills_spec()
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec", spec)
        self.assertEqual(code, 0, out)
        dirs = self.jobs()
        self.assertEqual(len(dirs), 3)
        group = dirs[0].name.rsplit("-c", 1)[0]
        self.assertEqual([d.name for d in dirs], [f"{group}-c{i}of3" for i in (1, 2, 3)])
        got, total = [], 0.0
        rates = json.loads(self.rates.read_text())
        for i, d in enumerate(dirs, 1):
            job = _job_json(d)
            self.assertEqual(job["chunk"], {"index": i, "of": 3, "group": group})
            self.assertEqual(json.loads((d / "build-manifest.json").read_text())["chunk"], job["chunk"])
            got += [x["key"] for x in job["items"]]
            secs = budget.forecast_seconds({"kind": "stills", "steps": 4, "items": len(job["items"]),
                                            "takes": 1, "decode_s": 240, "export_s": 60}, rates)
            self.assertLessEqual(secs, 3600)
            self.assertEqual(json.loads((d / "build-manifest.json").read_text())["deadline_seconds"],
                             int(secs))
            total += budget.forecast({"kind": "stills", "steps": 4, "items": len(job["items"]),
                                      "takes": 1, "decode_s": 240, "export_s": 60}, rates)
        self.assertEqual(got, keys)  # every item once, in order
        rows = self.ledger_rows()
        self.assertEqual(sorted(r["job_id"] for r in rows), [d.name for d in dirs])
        self.assertTrue(all(r["state"] == "reserved" for r in rows))
        self.assertAlmostEqual(sum(r["units"] for r in rows), total, places=9)
        self.assertIn("3 chunks", out)
        # status lists each chunk with index/of and the group
        code, out = run("status", "--root", self.root)
        for i in (1, 2, 3):
            self.assertIn(f"{group}-c{i}of3 stills film-01 chunk {i}/3 of {group}: waiting for Colab", out)
        self.assertIn(f"group {group} stills film-01: 0 of 3 chunks imported (incomplete)", out)
        self.assertIn(f"chunk 1 of 3 of group {group}", out)  # Next: run the first chunk
        self.assertIn(f"import {group}-c1of3", out)

    # --- requirement 3: the caps see the total ---------------------------------------------------
    def test_total_over_cap_refuses_every_chunk(self):
        self.set_rates(NARR, {**STILLS, "units_per_hour": 25.0})  # ~22 CU a chunk, ~67 CU in all
        spec, _ = self.stills_spec()
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec", spec)
        self.assertEqual(code, 3, out)
        self.assertIn("Budget exceeded", out)
        self.assertIn("for all 3 chunks", out)
        self.assertEqual(self.jobs(), [])
        self.assertFalse(self.ledger.exists())
        self.assertFalse(any(a["kind"] == "colab_job" for a in Record.load(self.root).data["artifacts"]))

    def test_a_failing_chunk_build_removes_every_chunk(self):
        spec, _ = self.stills_spec()
        real = colab_jobs._write_notebook_bundle
        calls = []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 3:
                raise OSError("disk full")
            return real(*a, **kw)

        before = json.loads((self.root / "record.json").read_text())
        from unittest import mock
        with mock.patch.object(colab_jobs, "_write_notebook_bundle", flaky):
            code, out = run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec", spec)
        self.assertNotEqual(code, 0, out)
        self.assertEqual(self.jobs(), [])
        self.assertTrue(all(r["state"] == "settled" and r["units"] == 0 for r in self.ledger_rows()))
        self.assertEqual(json.loads((self.root / "record.json").read_text()), before)

    # --- requirement 6: supersede ----------------------------------------------------------------
    def test_one_chunk_is_superseded_only_with_its_group(self):
        spec, _ = self.stills_spec()
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec)[0], 0)
        ids = [d.name for d in self.jobs()]
        code, out = run("supersede", ids[1], "--root", self.root, "--reason", "replaced")
        self.assertNotEqual(code, 0)
        self.assertIn("--group", out)
        self.assertTrue(all(r["state"] == "reserved" for r in self.ledger_rows()))
        code, out = run("supersede", ids[1], "--root", self.root, "--reason", "replaced", "--group")
        self.assertEqual(code, 0, out)
        self.assertTrue(all(r["state"] == "settled" and r["units"] == 0 for r in self.ledger_rows()))
        self.assertNotIn(ids[0].rsplit("-c", 1)[0], cli.next_action(self.root))  # nothing left to run
        code, out = run("supersede", ids[0], "--root", self.root, "--reason", "again", "--group")
        self.assertNotEqual(code, 0)

    def test_a_group_with_a_chunk_that_ran_on_modal_is_never_superseded(self):
        spec, _ = self.stills_spec()
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec)[0], 0)
        ids = [d.name for d in self.jobs()]
        budget.Ledger(self.ledger).record_modal_spend("2026-11", ids[2], 0.2, 5.0, "failed", "t")
        before_ledger = self.ledger.read_bytes()
        before_record = (self.root / "record.json").read_bytes()
        code, out = run("supersede", ids[0], "--root", self.root, "--reason", "replaced", "--group")
        self.assertEqual(code, 2, out)
        self.assertIn(f"{ids[2]} of group", out)
        self.assertIn("ran on Modal", out)
        self.assertEqual(self.ledger.read_bytes(), before_ledger)  # no chunk was superseded
        self.assertEqual((self.root / "record.json").read_bytes(), before_record)

    # --- fix round 1 (I1): a closed chunk is rebuilt alone ---------------------------------------
    def closed_stills_chunk_2(self):
        spec, keys = self.stills_spec()
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec)[0], 0)
        ids = [d.name for d in self.jobs()]
        code, out = run("close", ids[1], "--root", self.root, "--units", 1.0, "--reason", "hard stop")
        self.assertEqual(code, 0, out)
        return ids, keys

    def test_a_closed_chunk_is_replaced_with_only_its_items(self):
        ids, keys = self.closed_stills_chunk_2()
        group = ids[0].rsplit("-c", 1)[0]
        nxt = cli.next_action(self.root)
        self.assertIn(f"--replace-chunk {ids[1]}", nxt)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"group {group} stills film-01: 0 of 3 chunks imported (incomplete: chunk 2 "
                      "closed; rebuild it with job --replace-chunk)", out)
        rows = len(self.ledger_rows())
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates,
                        "--replace-chunk", ids[1])
        self.assertEqual(code, 0, out)
        new = self.root / "jobs" / f"{ids[1]}-r1"
        old_job, new_job = _job_json(self.root / "jobs" / ids[1]), _job_json(new)
        self.assertEqual(new_job["items"], old_job["items"])  # the same slice, in order
        self.assertEqual(new_job["chunk"], {"index": 2, "of": 3, "group": group})
        self.assertEqual({k: v for k, v in new_job.items() if k != "job_id"},
                         {k: v for k, v in old_job.items() if k != "job_id"})
        self.assertEqual(json.loads((new / "build-manifest.json").read_text())["chunk"], new_job["chunk"])
        ledger = self.ledger_rows()
        self.assertEqual(len(ledger), rows + 1)
        entry = next(r for r in ledger if r["job_id"] == new.name)
        self.assertEqual(entry["state"], "reserved")
        self.assertAlmostEqual(entry["units"], budget.forecast(
            {"kind": "stills", "steps": 4, "items": 10, "takes": 1, "decode_s": 240, "export_s": 60},
            {"stills": STILLS}), places=9)
        self.assertIn(f"import {ids[0]}", cli.next_action(self.root))  # chunks 1 and 3 kept
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{new.name} stills film-01 chunk 2/3 of {group}: waiting for Colab", out)
        self.assertIn(f"group {group} stills film-01: 0 of 3 chunks imported (incomplete)", out)
        # a second replacement while r1 is live is refused; so is replacing a live chunk
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates,
                        "--replace-chunk", ids[1])
        self.assertNotEqual(code, 0)
        self.assertIn(f"already has {new.name}", out)

    def test_a_live_chunk_is_never_replaced(self):
        spec, _ = self.stills_spec()
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec)[0], 0)
        ids = [d.name for d in self.jobs()]
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates,
                        "--replace-chunk", ids[1])
        self.assertNotEqual(code, 0)
        self.assertIn("still live", out)
        self.assertEqual(len(self.jobs()), 3)
        self.assertEqual(len(self.ledger_rows()), 3)

    def test_a_replacement_over_the_cap_exits_3(self):
        ids, _ = self.closed_stills_chunk_2()
        before = self.ledger_rows()
        self.set_rates(NARR, {**STILLS, "units_per_hour": 300.0})
        code, out = run("job", "stills", "--root", self.root, "--rates", self.rates,
                        "--replace-chunk", ids[1])
        self.assertEqual(code, 3, out)
        self.assertIn("Budget exceeded", out)
        self.assertEqual(self.ledger_rows(), before)
        self.assertEqual(len(self.jobs()), 3)

    def test_replaced_chunk_completes_the_group_for_film_and_bundle(self):
        self.set_rates({**NARR, "s_per_step": 3000.0, "units_per_hour": 0.2}, STILLS)
        self.assertEqual(run("job", "narration", "--root", self.root, "--rates", self.rates)[0], 0)
        narr = self.jobs()
        self.assertGreaterEqual(len(narr), 3)
        spec, _ = self.stills_spec(5)  # one short stills job
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec)[0], 0)
        [stills] = [d for d in self.jobs() if d not in narr]
        self.import_chunk(stills, "stills")
        code, out = run("close", narr[1].name, "--root", self.root, "--units", 0.2, "--reason", "crash")
        self.assertEqual(code, 0, out)
        for d in [narr[0]] + narr[2:]:
            self.import_chunk(d, "narration")
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--replace-chunk", narr[1].name)
        self.assertEqual(code, 0, out)
        r1 = self.root / "jobs" / f"{narr[1].name}-r1"
        self.import_chunk(r1, "narration")
        used = [narr[0].name, r1.name] + [d.name for d in narr[2:]]
        group = narr[0].name.rsplit("-c", 1)[0]
        code, out = run("status", "--root", self.root)
        self.assertIn(f"group {group} narration film-01: {len(narr)} of {len(narr)} chunks imported "
                      "(complete)", out)
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(self.d / "logo.png")
        Image.new("RGB", (320, 180), (0, 0, 0)).save(self.d / "end.png")
        bed = self.d / "bed.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "anoisesrc=d=30:c=pink:r=48000:a=0.2", "-ac", "2", str(bed)], check=True)
        code, out = run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                        self.d / "end.png", "--score", bed, "--score-route", "vcsl")
        self.assertEqual(code, 0, out)
        timing = json.loads((self.root / "film" / "film-01" / "timing.json").read_text())
        self.assertEqual([t["unit_key"] for t in timing["units"]], [u["unit_key"] for u in self.units])
        self.assertEqual(timing["provenance"]["narration_chunk_job_ids"], used)
        for u in _job_json(r1)["units"]:
            self.assertEqual(timing["provenance"]["wav_sha256"][u["unit_key"]], hashlib.sha256(
                (self.root / "narration" / r1.name / f"{u['unit_key']}.wav").read_bytes()).hexdigest())
        Record.load(self.root).event("qc", "pass", {"failed": []})
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertEqual(code, 0, out)
        prov = json.loads((bundle / "timing.json").read_text())["provenance"]
        for unit in prov["units"].values():
            self.assertEqual(unit["narration_chunk_job_ids"], used)
        draft = json.loads((self.root / "maison" / cli.EVIDENCE_DRAFT).read_text())
        self.assertEqual(draft["generators"][0]["job_ids"], used)  # chunk order (A3 M5)
        self.assertNotIn(narr[1].name, draft["generators"][0]["job_ids"])
        code, out = run("preview", "--root", self.root, "--bundle", bundle, "--out", self.d / "preview")
        self.assertIn(code, (0, 5), out)
        self.assertNotIn("Traceback", out)

    # --- requirement 5: consumers ----------------------------------------------------------------
    def fake_outputs(self, job_dir, kind):
        job = _job_json(job_dir)
        folder = self.d / "download" / job_dir.name
        folder.mkdir(parents=True)
        outputs = {}
        rows = job["units"] if kind == "narration" else job["items"]
        for i, r in enumerate(rows):
            if kind == "narration":
                f = folder / f"{r['unit_key']}.wav"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                                f"sine=f={200 + 20 * i}:d={speech_seconds(r['text'])}:r=24000", "-ac", "1", str(f)], check=True)
            else:
                f = folder / f"{r['key']}.png"
                Image.new("RGB", (320, 180), (8 * i, 90, 120)).save(f)
            outputs[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": job_dir.name, "title": "selfish-giant",
            "kind": kind, "input_zip_sha256": hashlib.sha256((job_dir / "inputs.zip").read_bytes()).hexdigest(),
            "model": {"repo": "x", "revision": "y"}, "status": "COMPLETE", "packages": {"torch": "2"},
            "outputs": outputs}), encoding="utf-8")
        return folder

    def import_chunk(self, job_dir, kind):
        code, out = run("import", job_dir.name, "--root", self.root, "--from",
                        self.fake_outputs(job_dir, kind), "--units", 0.5)
        self.assertEqual(code, 0, out)

    def test_film_bundle_preview_status_use_a_complete_group_in_order(self):
        # narration: every unit forecast ~58 min -> one unit per chunk
        self.set_rates({**NARR, "s_per_step": 3000.0, "units_per_hour": 0.2}, STILLS)
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)
        narr = self.jobs()
        self.assertEqual(len(narr), len(self.units))
        self.assertGreater(len(narr), 1)
        spec, _ = self.stills_spec()
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec)[0], 0)
        stills = [d for d in self.jobs() if d not in narr]
        self.assertEqual(len(stills), 3)
        for d in narr[:-1]:
            self.import_chunk(d, "narration")
        for d in stills:
            self.import_chunk(d, "stills")
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(self.d / "logo.png")
        Image.new("RGB", (320, 180), (0, 0, 0)).save(self.d / "end.png")
        bed = self.d / "bed.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "anoisesrc=d=30:c=pink:r=48000:a=0.2", "-ac", "2", str(bed)], check=True)
        film = ("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                self.d / "end.png", "--score", bed, "--score-route", "vcsl")
        group = narr[0].name.rsplit("-c", 1)[0]
        code, out = run(*film)  # one chunk still out: incomplete, never a partial film
        self.assertNotEqual(code, 0)
        self.assertIn(f"{group}: {len(narr) - 1} of {len(narr)} chunks imported; incomplete", out)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"group {group} narration film-01: {len(narr) - 1} of {len(narr)} chunks "
                      "imported (incomplete)", out)
        self.assertIn(f"import {narr[-1].name}", out)
        self.import_chunk(narr[-1], "narration")
        code, out = run("status", "--root", self.root)
        self.assertIn(f"group {group} narration film-01: {len(narr)} of {len(narr)} chunks imported "
                      "(complete)", out)
        self.assertIn("python3 -m eav.cli film", out)
        code, out = run(*film)
        self.assertEqual(code, 0, out)
        timing = json.loads((self.root / "film" / "film-01" / "timing.json").read_text())
        self.assertEqual([t["unit_key"] for t in timing["units"]], [u["unit_key"] for u in self.units])
        self.assertEqual(timing["provenance"]["narration_job_id"], group)
        self.assertEqual(timing["provenance"]["narration_chunk_job_ids"], [d.name for d in narr])
        for d in narr:  # each unit measured from the chunk that made it
            for u in _job_json(d)["units"]:
                self.assertEqual(timing["provenance"]["wav_sha256"][u["unit_key"]],
                                 hashlib.sha256((self.root / "narration" / d.name /
                                                 f"{u['unit_key']}.wav").read_bytes()).hexdigest())
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["clips"], 30)  # every still of all three chunks
        # bundle-audio and preview from the group
        rec = Record.load(self.root)
        rec.event("qc", "pass", {"failed": []})
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertEqual(code, 0, out)
        prov = json.loads((bundle / "timing.json").read_text())["provenance"]
        self.assertEqual(prov["narration_job_id"], group)
        for unit in prov["units"].values():
            self.assertEqual(unit["narration_job_id"], group)
            self.assertEqual(unit["narration_chunk_job_ids"], [d.name for d in narr])
        draft = json.loads((self.root / "maison" / cli.EVIDENCE_DRAFT).read_text())
        self.assertEqual(draft["generators"][0]["job_ids"], [d.name for d in narr])  # chunk order
        code, out = run("preview", "--root", self.root, "--bundle", bundle, "--out", self.d / "preview")
        self.assertIn(code, (0, 5), out)  # the fixture's short pauses may not qualify; never a crash
        self.assertNotIn("Traceback", out)


    # --- M1: retire a group a newer build replaced ------------------------------------------------
    def film_args(self):
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(self.d / "logo.png")
        Image.new("RGB", (320, 180), (0, 0, 0)).save(self.d / "end.png")
        bed = self.d / "bed.wav"
        if not bed.exists():
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "anoisesrc=d=30:c=pink:r=48000:a=0.2", "-ac", "2", str(bed)], check=True)
        return ("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                self.d / "end.png", "--score", bed, "--score-route", "vcsl")

    def test_a_retired_group_is_never_current_and_film_uses_the_newest_complete_job(self):
        """The live case: a narration group (chunk 1 imported, chunk 2 closed) was rebuilt as one
        job and imported; the group kept driving Next ("rebuild only that chunk"). Retired, it is
        kept on record and never used; film, bundle-audio and preview say which job they used."""
        self.set_rates({**NARR, "s_per_step": 3000.0, "units_per_hour": 0.2}, STILLS)
        self.assertEqual(run("job", "narration", "--root", self.root, "--rates", self.rates,
                             "--job-id", "narration-r3")[0], 0)
        chunks = self.jobs()
        self.assertGreaterEqual(len(chunks), 2)
        self.import_chunk(chunks[0], "narration")
        for d in chunks[1:]:
            code, out = run("close", d.name, "--root", self.root, "--units", 0.1, "--reason", "cut off")
            self.assertEqual(code, 0, out)
        self.set_rates(NARR, STILLS)
        self.assertEqual(run("job", "narration", "--root", self.root, "--rates", self.rates,
                             "--job-id", "narration-r4")[0], 0)
        self.import_chunk(self.root / "jobs" / "narration-r4", "narration")
        spec, _ = self.stills_spec(5)
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec, "--job-id", "stills-one")[0], 0)
        self.import_chunk(self.root / "jobs" / "stills-one", "stills")
        self.assertIn("--replace-chunk", cli.next_action(self.root))  # the bug: the old group leads
        code, out = run("retire", chunks[0].name, "--root", self.root, "--reason", "rebuilt as r4")
        self.assertEqual(code, 2, out)
        self.assertIn("a group is retired as a whole", out)
        self.assertIn("retire narration-r3", out)
        events = len(Record.load(self.root).data["events"])
        ledger = self.ledger.read_bytes()
        code, out = run("retire", "narration-r3", "--root", self.root, "--reason", "rebuilt as narration-r4")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ledger.read_bytes(), ledger)  # kept on record: nothing settled again
        ev = Record.load(self.root).data["events"][events]
        self.assertEqual((ev["stage"], ev["result"], ev["detail"]["job_id"], ev["detail"]["jobs"]),
                         ("job", "retired", "narration-r3", [d.name for d in chunks]))
        nxt = cli.next_action(self.root)
        self.assertNotIn("--replace-chunk", nxt)
        self.assertIn("film", nxt)
        code, out = run("status", "--root", self.root)
        self.assertIn("group narration-r3 narration film-01", out)
        self.assertIn("(retired: kept on record, never used as current)", out)
        self.assertIn(f"{chunks[0].name} narration film-01 chunk 1/{len(chunks)} of narration-r3: "
                      "retired, never used as current (imported)", out)
        code, out = run("retire", "narration-r3", "--root", self.root, "--reason", "again")
        self.assertEqual(code, 2, out)
        self.assertIn("already retired", out)
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--replace-chunk", chunks[1].name)
        self.assertEqual(code, 2, out)
        self.assertIn("is retired", out)
        code, out = run(*self.film_args())
        self.assertEqual(code, 0, out)
        self.assertIn("from narration job narration-r4 and stills job stills-one", out)
        timing = json.loads((self.root / "film" / "film-01" / "timing.json").read_text())
        self.assertEqual(timing["provenance"]["narration_job_id"], "narration-r4")
        Record.load(self.root).event("qc", "pass", {"failed": []})
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertEqual(code, 0, out)
        self.assertIn("from narration job(s) narration-r4.", out)
        # a bundle built from the retired group is refused by preview
        stale = self.d / "stale-bundle"
        stale.mkdir()
        (stale / "unit-001.mp3").write_bytes((bundle / "unit-001.mp3").read_bytes())
        prov = json.loads((bundle / "timing.json").read_text())
        for unit in prov["provenance"]["units"].values():
            unit["narration_job_id"] = "narration-r3"
        (stale / "timing.json").write_text(json.dumps(prov))
        code, out = run("preview", "--root", self.root, "--bundle", stale, "--out", self.d / "pv-stale")
        self.assertEqual(code, 2, out)
        self.assertIn("built from narration job narration-r3, which is not the current narration "
                      "(narration-r4", out)
        self.assertFalse((self.d / "pv-stale").exists())
        code, out = run("preview", "--root", self.root, "--bundle", bundle, "--out", self.d / "pv")
        self.assertIn(code, (0, 5), out)
        if code == 0:
            self.assertIn("from narration job narration-r4", out)

    def test_retire_refuses_live_jobs_pending_rows_and_open_requests(self):
        self.assertEqual(run("job", "narration", "--root", self.root, "--rates", self.rates,
                             "--job-id", "narration-live")[0], 0)
        before = ((self.root / "record.json").read_bytes(), self.ledger.read_bytes())
        code, out = run("retire", "narration-live", "--root", self.root, "--reason", "x")
        self.assertEqual(code, 2, out)
        self.assertIn("still live", out)
        code, out = run("retire", "nope", "--root", self.root, "--reason", "x")
        self.assertEqual(code, 2, out)
        self.assertIn("unknown job or chunk group", out)
        led = budget.Ledger(self.ledger)
        led.move_to_modal("narration-live", "t", 0.0)
        run_id = led.record_modal_spend("2026-11", "narration-live", 1.0, 0.0, "pending", "t")
        code, out = run("retire", "narration-live", "--root", self.root, "--reason", "x")
        self.assertEqual(code, 2, out)
        self.assertIn(f"pending Modal row ({run_id})", out)
        led.finish_modal_spend(run_id, 0.3, 100.0, "failed")
        req = cli.modal_requests.request_path(self.root, "narration-live")
        req.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema": cli.modal_requests.SCHEMA, "job_id": "narration-live", "status": "running"}
        req.write_text(json.dumps(data))
        code, out = run("retire", "narration-live", "--root", self.root, "--reason", "x")
        self.assertEqual(code, 2, out)
        self.assertIn("open Modal request", out)
        self.assertEqual((self.root / "record.json").read_bytes(), before[0])
        # failed on Modal (its request finished failed): closed first, settling the spend, then retired
        req.write_text(json.dumps({**data, "status": "failed"}))
        code, out = run("retire", "narration-live", "--root", self.root, "--reason", "rebuilt")
        self.assertEqual(code, 0, out)
        self.assertIn("Closed first (failed on Modal, spend settled): narration-live", out)
        entry = next(e for e in json.loads(self.ledger.read_text()) if e.get("job_id") == "narration-live")
        self.assertEqual((entry["state"], entry["usd"]), ("settled", 0.3))
        results = [e["result"] for e in Record.load(self.root).data["events"]
                   if e["detail"].get("job_id") == "narration-live" and e["stage"] == "job"]
        self.assertEqual(results, ["built", "closing", "closed", "retired"])
        code, out = run("import", "narration-live", "--root", self.root, "--from", self.d)
        self.assertEqual(code, 2, out)
        self.assertIn("retired", out)

    # --- S1: per-key replacement of stills ------------------------------------------------------
    def keyed_spec(self, name, keys, seed0):
        spec = self.d / name
        spec.write_text(json.dumps({"items": [{"key": k, "prompt": f"{name} {k}", "seed": seed0 + i}
                                              for i, k in enumerate(keys)]}), encoding="utf-8")
        return spec

    def test_film_uses_per_key_the_most_recently_imported_still(self):
        """Chunk 2 of a stills group ran but was closed; a new job with new prompts holds its keys,
        and a small replacement job regenerates two keys of chunk 1. Per key the film uses the
        still of the most recently imported, non-retired job; status says which job supplies each
        key; retiring the replacement brings the earlier stills back."""
        self.assertEqual(run("job", "narration", "--root", self.root, "--rates", self.rates,
                             "--job-id", "narr")[0], 0)
        self.import_chunk(self.root / "jobs" / "narr", "narration")
        spec, keys = self.stills_spec()
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates,
                             "--spec", spec, "--job-id", "st")[0], 0)
        chunks = [d for d in self.jobs() if d.name.startswith("st-c")]
        self.assertEqual(len(chunks), 3)
        ckeys = [[it["key"] for it in _job_json(d)["items"]] for d in chunks]
        self.import_chunk(chunks[0], "stills")
        self.import_chunk(chunks[2], "stills")
        code, out = run("close", chunks[1].name, "--root", self.root, "--units", 0.5, "--reason", "OOM")
        self.assertEqual(code, 0, out)
        nxt = cli.next_action(self.root)
        self.assertIn(f"--replace-chunk {chunks[1].name}", nxt)
        self.assertIn("the film uses, per key, the most recently imported still", nxt)
        code, out = run(*self.film_args())  # chunk 2's keys have no still: never a partial film
        self.assertEqual(code, 2, out)
        self.assertIn("no imported still for key(s) " + ", ".join(ckeys[1]), out)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"stills film-01: {len(ckeys[0]) + len(ckeys[2])} key(s) supplied", out)
        self.assertIn("no imported still yet for " + ", ".join(ckeys[1]), out)
        # a new job (new prompts, new seeds) for chunk 2's keys: Next no longer offers --replace-chunk
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec",
                             self.keyed_spec("c2.json", ckeys[1], 500), "--job-id", "st-c2-new")[0], 0)
        nxt = cli.next_action(self.root)
        self.assertNotIn("--replace-chunk", nxt)
        self.assertIn("st-c2-new", nxt)
        self.import_chunk(self.root / "jobs" / "st-c2-new", "stills")
        fix = [ckeys[0][1], ckeys[2][0]]
        self.assertEqual(run("job", "stills", "--root", self.root, "--rates", self.rates, "--spec",
                             self.keyed_spec("fix.json", fix, 900), "--job-id", "st-fix")[0], 0)
        self.import_chunk(self.root / "jobs" / "st-fix", "stills")
        rec = Record.load(self.root)
        have = cli._stills_by_key(rec, "film-01")
        self.assertEqual(set(have), set(keys))
        want = {k: ("st-fix" if k in fix else "st-c2-new" if k in ckeys[1]
                    else chunks[0].name if k in ckeys[0] else chunks[2].name) for k in keys}
        self.assertEqual({k: v["job_id"] for k, v in have.items()}, want)
        self.assertEqual(have[fix[0]]["path"], self.root / "stills" / "st-fix" / f"{fix[0]}.png")
        code, out = run("status", "--root", self.root)
        self.assertIn(f"stills film-01: {len(keys)} key(s) supplied", out)
        self.assertIn(f"    st-fix: {', '.join(fix)}", out)
        self.assertIn(f"    st-c2-new: {', '.join(ckeys[1])}", out)
        self.assertNotIn("no imported still yet", out)
        self.assertIn("python3 -m eav.cli film", cli.next_action(self.root))
        code, out = run(*self.film_args())
        self.assertEqual(code, 0, out)
        self.assertIn("stills jobs", out)
        self.assertIn("st-fix (2 keys)", out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["stills_by_key"], want)
        self.assertEqual(art["meta"]["clips"], len(keys))
        # retiring the replacement job: its keys come from chunk 1 and 3 again
        code, out = run("retire", "st-fix", "--root", self.root, "--reason", "owner preferred the originals")
        self.assertEqual(code, 0, out)
        have = cli._stills_by_key(Record.load(self.root), "film-01")
        self.assertEqual(have[fix[0]]["job_id"], chunks[0].name)
        self.assertEqual(have[fix[1]]["job_id"], chunks[2].name)

    def test_reel_clips_art_dir_may_map_image_names_to_files(self):
        a, b = self.d / "a", self.d / "b"
        a.mkdir(), b.mkdir()
        for d in (a, b):
            Image.new("RGB", (8, 8)).save(d / "shot-01.png")
        spec = {"shots": [{"id": "shot-01", "image": "shot-01.png"}]}
        with self.assertRaisesRegex(ValueError, "in 2 of the art_dir"):
            colab_jobs.art_images({**spec, "art_dir": [str(a), str(b)]})
        got = colab_jobs.art_images({**spec, "art_dir": {"shot-01.png": str(b / "shot-01.png")}})
        self.assertEqual(got, {"shot-01.png": b / "shot-01.png"})
        with self.assertRaisesRegex(ValueError, "maps no existing file"):
            colab_jobs.art_images({**spec, "art_dir": {"shot-01.png": str(a / "missing.png")}})


if __name__ == "__main__":
    unittest.main()
