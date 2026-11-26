"""A3: long narration/stills jobs are cut into chunks of <= 3600 forecast seconds; consumers use a
chunk group only once every chunk is imported, and then all chunks' outputs in order."""
import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from eav import budget, cli, colab_jobs
from eav.record import Record
from eav.voice import voice_units
from tests.test_cli import SOURCE, run

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
        return sorted(p for p in (self.root / "jobs").iterdir()) if (self.root / "jobs").is_dir() else []

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
        self.assertEqual(draft["generators"][0]["job_ids"], sorted(used))
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
                                f"sine=f={200 + 20 * i}:d=0.7:r=24000", "-ac", "1", str(f)], check=True)
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
        self.assertEqual(draft["generators"][0]["job_ids"], sorted(d.name for d in narr))
        code, out = run("preview", "--root", self.root, "--bundle", bundle, "--out", self.d / "preview")
        self.assertIn(code, (0, 5), out)  # the fixture's short pauses may not qualify; never a crash
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()
