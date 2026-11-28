"""job narration --redo-units: voice only a few suspect_truncated units of an imported narration
job again; on import a take that passes the truncation check supplies the unit downstream (film,
bundle-audio, preview) in place of the old take, which stays on disk and on record."""
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from eav import cli
from eav.record import Record
from tests import test_cli
from tests.test_cli import RATES, SOURCE, run


# helpers borrowed from test_cli.CliTests (never imported by name: pytest would collect it again)
class RedoUnitsTests(unittest.TestCase):
    build_narration = test_cli.CliTests.build_narration
    fake_colab_outputs = test_cli.CliTests.fake_colab_outputs
    imported = test_cli.CliTests.imported
    init_and_plan = test_cli.CliTests.init_and_plan
    cut_off = staticmethod(test_cli.CliTests.cut_off)
    fake_job = test_cli.CliTests.fake_job
    wav = test_cli.CliTests.wav
    noise = test_cli.CliTests.noise

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        # a checkout layout, so modal-request accepts the title root
        (self.d / ".git").mkdir()
        self.root = self.d / "production" / "audiovisual" / "selfish-giant"
        self.ledger = self.root.parent / "allowance-ledger.json"
        self.src = self.d / "selfish-giant.json"
        self.src.write_text(json.dumps(SOURCE), encoding="utf-8")
        self.rates = self.d / "rates.json"
        self.rates.write_text(json.dumps(RATES), encoding="utf-8")

    # ---------------------------------------------------------------- helpers
    def cut_source(self):
        """An imported film-01 narration job with one unit cut off (0.5 s for 50 characters)."""
        job_id, _, units = self.imported(self.cut_off)
        key = next(u["unit_key"] for u in units if self.cut_off(u))
        return job_id, key, units

    def redo(self, spec):
        return run("job", "narration", "--root", self.root, "--rates", self.rates, "--redo-units", spec)

    def job_json(self, job_id):
        with zipfile.ZipFile(self.root / "jobs" / job_id / "inputs.zip") as z:
            return json.loads(z.read("job.json"))

    def import_redo(self, redo_id, seconds=None):
        folder, _ = self.fake_colab_outputs(redo_id, self.root / "jobs" / redo_id, seconds)
        return run("import", redo_id, "--root", self.root, "--from", folder, "--units", 0.2)

    def events(self, result):
        return [e["detail"] for e in Record.load(self.root).data["events"]
                if e["stage"] == "narration" and e["result"] == result]

    def ledger_rows(self):
        return json.loads(self.ledger.read_text()) if self.ledger.exists() else []

    def stills_and_cards(self):
        plan = json.loads((self.root / "plan.json").read_text())
        scenes = plan["plan"]["films"][0]["scenes"]

        def stills(rec, job_id, job_dir, out):
            for i, sc in enumerate(scenes):
                Image.new("RGB", (320, 180), (60 * i, 90, 120)).save(out / f"{sc['scene_id']}-1.png")
        self.fake_job("stills", "film-01", stills)
        Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(self.d / "logo.png")
        Image.new("RGB", (320, 180), (0, 0, 0)).save(self.d / "end.png")
        self.bed = self.d / "bed.wav"
        self.noise(self.bed, 30)

    def film(self, *extra):
        return run("film", "--root", self.root, "--logo", self.d / "logo.png", "--end-card",
                   self.d / "end.png", "--score", self.bed, "--score-route", "vcsl", *extra)

    # ---------------------------------------------------------------- tests
    def test_redo_job_holds_only_those_units_with_the_source_settings(self):
        job_id, key, _ = self.cut_source()
        before = len(self.ledger_rows())
        code, out = self.redo(f"{job_id}:{key}")
        self.assertEqual(code, 0, out)
        redo_id = f"{job_id}-u1"
        self.assertIn(f"Built narration redo job {redo_id}", out)
        src, new = self.job_json(job_id), self.job_json(redo_id)
        self.assertEqual(new["units"], [u for u in src["units"] if u["unit_key"] == key])
        for k in ("generation", "batch", "model", "kind", "title", "schema"):
            self.assertEqual(new[k], src[k], k)
        self.assertEqual(new["redo"], {"source_job_id": job_id, "unit_keys": [key]})
        self.assertNotIn("chunk", new)
        src_b = json.loads((self.root / "jobs" / job_id / "build-manifest.json").read_text())
        new_b = json.loads((self.root / "jobs" / redo_id / "build-manifest.json").read_text())
        self.assertEqual(new_b["model"], src_b["model"])
        self.assertEqual(new_b["generation"], src_b["generation"])
        self.assertEqual(new_b["inputs_sha256"],
                         hashlib.sha256((self.root / "jobs" / redo_id / "inputs.zip").read_bytes()).hexdigest())
        rows = self.ledger_rows()
        self.assertEqual(len(rows), before + 1)
        row = next(r for r in rows if r["job_id"] == redo_id)
        self.assertEqual(row["state"], "reserved")
        self.assertGreater(row["units"], 0)
        # one unit costs less than the whole job
        self.assertLess(row["units"], next(r for r in rows if r["job_id"] == job_id)["units"])
        # the redo is the next action; the source stays the current narration
        self.assertIn(f"import {redo_id}", cli.next_action(self.root))
        rec = Record.load(self.root)
        self.assertEqual(cli._latest_job(rec, "narration", "film-01")["job_id"], job_id)
        # a second redo of the same unit while this one is live is refused
        code, out = self.redo(f"{job_id}:{key}")
        self.assertNotEqual(code, 0)
        self.assertIn("already have a live redo job", out)
        # it runs on Modal through the same request flow as any job (no Modal contact here)
        code, out = run("modal-request", redo_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual(code, 0, out)
        req = json.loads((self.root.parent / "modal-requests" / f"{redo_id}.json").read_text())
        self.assertEqual((req["job_id"], req["status"]), (redo_id, "requested"))

    def test_unknown_unit_and_wrong_sources_are_refused_before_any_reservation(self):
        job_id, key, _ = self.cut_source()
        rows = self.ledger_rows()
        for spec, why in ((f"{job_id}:f99s999-001", "not in narration job"),
                          (f"{job_id}:{key},f99s999-001", "not in narration job"),
                          ("narration-nope:f01s001-001", "unknown narration job"),
                          (f"{job_id}:", "is not <job_id>:<unit_key>"),
                          (f"{job_id}:{key},{key}", "names a unit twice")):
            code, out = self.redo(spec)
            self.assertEqual(code, 2, (spec, out))
            self.assertIn(why, out, spec)
        self.assertEqual(self.ledger_rows(), rows)
        self.assertEqual(sorted(p.name for p in (self.root / "jobs").iterdir()), [job_id])
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--redo-units", f"{job_id}:{key}", "--spec", self.rates)
        self.assertNotEqual(code, 0)
        self.assertIn("do not apply", out)
        # a job that is not imported yet has no takes to redo
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates, "--job-id", "narr-two")
        self.assertEqual(code, 0, out)
        code, out = self.redo(f"narr-two:{key}")
        self.assertNotEqual(code, 0)
        self.assertIn("not imported", out)

    def test_import_replaces_the_suspect_take_downstream_and_retire_reverts_it(self):
        job_id, key, _ = self.cut_source()
        self.stills_and_cards()
        code, out = self.film()
        self.assertEqual(code, 5, out)
        self.assertIn(f"--redo-units {job_id}:{key}", out)  # the gate offers the redo
        self.assertEqual(self.redo(f"{job_id}:{key}")[0], 0)
        redo_id = f"{job_id}-u1"
        original = self.root / "narration" / job_id / f"{key}.wav"
        original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
        code, out = self.import_redo(redo_id)  # the default fake take: 20 chars/s, not suspect
        self.assertEqual(code, 0, out)
        self.assertIn("passed the truncation check", out)
        take = self.root / "narration" / redo_id / f"{key}.wav"
        [ev] = self.events("unit_replaced")
        self.assertEqual((ev["job_id"], ev["source_job_id"], ev["unit_key"]), (redo_id, job_id, key))
        self.assertEqual(ev["path"], f"narration/{redo_id}/{key}.wav")
        self.assertEqual(ev["sha256"], hashlib.sha256(take.read_bytes()).hexdigest())
        self.assertEqual((ev["original_path"], ev["original_sha256"]),
                         (f"narration/{job_id}/{key}.wav", original_sha))
        self.assertTrue(original.is_file())  # the old take is kept
        self.assertEqual(self.events("unit_redo_suspect"), [])
        rec = Record.load(self.root)
        self.assertEqual(cli._latest_job(rec, "narration", "film-01")["job_id"], job_id)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{redo_id} narration film-01 redo of {job_id} unit(s) {key}: imported", out)
        self.assertIn(f"{key}: uses narration/{redo_id}/{key}.wav", out)
        # film: the unit is no longer suspect, so no --accept-qc is needed, and the new take is used
        code, out = self.film()
        self.assertEqual(code, 0, out)
        self.assertNotIn("suspect_truncated", out)
        art = [a for a in Record.load(self.root).data["artifacts"] if a["kind"] == "film"][-1]
        self.assertEqual(art["meta"]["suspect_truncated"], [])
        self.assertEqual(art["meta"]["narration_job_id"], job_id)
        self.assertEqual(art["meta"]["narration_replaced_units"], {key: ev["sha256"]})
        prov = json.loads((self.root / "film" / "film-01" / "timing.json").read_text())["provenance"]
        self.assertEqual(prov["wav_sha256"][key], ev["sha256"])
        self.assertEqual(prov["replaced_units"][key]["job_id"], redo_id)
        # qc lists no suspect for the film any more
        run("qc", "--root", self.root)
        item = json.loads((self.root / "qc" / "report.json").read_text())["items"]["film-01"]
        self.assertEqual(item["suspect_truncated"], [])
        rec = Record.load(self.root)
        rec.event("qc", "pass", {"failed": []})  # the owner's review of the package (faked)
        # bundle-audio voices the unit with the new take and names the redo job
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle, "--dry")
        self.assertEqual(code, 0, out)
        units = json.loads((bundle / "timing.json").read_text())["provenance"]["units"]
        chapter = next(u for u in units.values() if key in u["wav_sha256"])
        self.assertEqual(chapter["wav_sha256"][key], ev["sha256"])
        self.assertEqual(chapter["replaced_units"][key]["replaces_sha256"], original_sha)
        draft = json.loads((self.root / "maison" / cli.EVIDENCE_DRAFT).read_text())
        self.assertIn(redo_id, draft["generators"][0]["job_ids"])
        ev_b = [e for e in Record.load(self.root).data["events"] if e["stage"] == "bundle_audio"][-1]
        self.assertEqual(ev_b["detail"]["suspect_truncated"], [])
        # preview takes that bundle as current (this tiny chapter has no pause after 10 s to end
        # a clip on, which preview reports with exit 5 after the currency check)
        code, out = run("preview", "--root", self.root, "--bundle", bundle, "--out", self.d / "p")
        self.assertIn(code, (0, 5), out)
        self.assertNotIn("redone narration take", out)
        self.assertNotIn("Traceback", out)
        # reversible: retiring the redo job puts the original take back; the film and the bundle
        # built with the redone take are no longer current
        code, out = run("retire", redo_id, "--root", self.root, "--reason", "owner prefers the original")
        self.assertEqual(code, 0, out)
        rec = Record.load(self.root)
        self.assertEqual(cli._replacements(rec, cli._find(rec, job_id)), {})
        self.assertEqual(cli._current_films(rec, "film-01"), [])
        self.assertIn("film", cli.next_action(self.root))
        code, out = run("preview", "--root", self.root, "--bundle", bundle, "--out", self.d / "p2")
        self.assertNotEqual(code, 0)
        self.assertIn("redone narration take", out)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{key}: redo {redo_id} retired", out)
        code, out = self.film()
        self.assertEqual(code, 5, out)  # the original take is suspect again
        self.assertIn(key, out)

    def test_a_redo_take_that_is_still_suspect_stays_flagged(self):
        job_id, key, _ = self.cut_source()
        self.stills_and_cards()
        self.assertEqual(self.redo(f"{job_id}:{key}")[0], 0)
        redo_id = f"{job_id}-u1"
        code, out = self.import_redo(redo_id, seconds=lambda u: 0.4)  # cut off again
        self.assertEqual(code, 0, out)  # the paid outputs are imported all the same
        self.assertIn("the redone take is itself suspect", out)
        self.assertTrue((self.root / "narration" / redo_id / f"{key}.wav").is_file())
        self.assertEqual(self.events("unit_replaced"), [])
        [ev] = self.events("unit_redo_suspect")
        self.assertEqual((ev["job_id"], ev["unit_key"]), (redo_id, key))
        self.assertTrue(ev["suspect"]["reasons"])
        rec = Record.load(self.root)
        self.assertEqual(cli._replacements(rec, cli._find(rec, job_id)), {})
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{key}: redone take narration/{redo_id}/{key}.wav", out)
        self.assertIn("still suspect_truncated", out)
        code, out = self.film()
        self.assertEqual(code, 5, out)
        self.assertIn(f"suspect_truncated narration unit(s) {key}", out)
        # a second redo of the unit is numbered -u2 and can still replace it
        code, out = self.redo(f"{job_id}:{key}")
        self.assertEqual(code, 0, out)
        code, out = self.import_redo(f"{job_id}-u2")
        self.assertEqual(code, 0, out)
        [ev2] = self.events("unit_replaced")
        self.assertEqual(ev2["job_id"], f"{job_id}-u2")
        self.assertEqual(self.film()[0], 0)

    def test_import_needs_the_source_takes_for_the_check(self):
        job_id, key, _ = self.cut_source()
        self.assertEqual(self.redo(f"{job_id}:{key}")[0], 0)
        redo_id = f"{job_id}-u1"
        for p in (self.root / "narration" / job_id).iterdir():
            if p.name != f"{key}.wav":
                p.unlink()
        code, out = self.import_redo(redo_id)
        self.assertEqual(code, 4, out)
        self.assertIn("truncation check", out)
        self.assertFalse((self.root / "narration" / redo_id).exists())
        self.assertEqual(next(r for r in self.ledger_rows() if r["job_id"] == redo_id)["state"],
                         "reserved")

    def test_a_unit_of_a_chunk_is_redone_and_supplies_the_group(self):
        self.init_and_plan()
        self.rates.write_text(json.dumps({"narration": {**RATES["narration"], "s_per_step": 3000.0,
                                                        "units_per_hour": 0.2}}), encoding="utf-8")
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)
        chunks = sorted((p.name for p in (self.root / "jobs").iterdir()),
                        key=lambda n: int(n.rsplit("-c", 1)[1].split("of")[0]))
        self.assertGreaterEqual(len(chunks), 2)
        group = chunks[0].rsplit("-c", 1)[0]
        cut = self.job_json(chunks[1])["units"][0]["unit_key"]
        for c in chunks:
            folder, _ = self.fake_colab_outputs(
                c, self.root / "jobs" / c, lambda u: 0.05 if u["unit_key"] == cut else None)
            code, out = run("import", c, "--root", self.root, "--from", folder, "--units", 0.2)
            self.assertEqual(code, 0, out)
        self.stills_and_cards()
        code, out = self.film()
        self.assertEqual(code, 5, out)
        self.assertIn(f"--redo-units {chunks[1]}:{cut}", out)  # names the chunk holding the unit
        code, out = self.redo(f"{group}:{cut}")
        self.assertNotEqual(code, 0)
        self.assertIn("names the chunk", out)
        code, out = self.redo(f"{chunks[0]}:{cut}")  # the unit is in another chunk
        self.assertNotEqual(code, 0)
        self.assertIn("not in narration job", out)
        code, out = self.redo(f"{chunks[1]}:{cut}")
        self.assertEqual(code, 0, out)
        redo_id = f"{chunks[1]}-u1"
        self.assertEqual(self.job_json(redo_id)["units"],
                         [u for u in self.job_json(chunks[1])["units"] if u["unit_key"] == cut])
        code, out = self.import_redo(redo_id)
        self.assertEqual(code, 0, out)
        code, out = self.film()
        self.assertEqual(code, 0, out)
        prov = json.loads((self.root / "film" / "film-01" / "timing.json").read_text())["provenance"]
        self.assertEqual(prov["narration_chunk_job_ids"], chunks)  # the group, unchanged
        self.assertEqual(prov["replaced_units"][cut]["job_id"], redo_id)
        code, out = run("status", "--root", self.root)
        self.assertIn(f"narration {group} film-01: per-unit redo takes", out)
        self.assertIn(f"{cut}: uses narration/{redo_id}/{cut}.wav", out)

    def test_redo_rows_keep_each_units_own_voice_and_extra_fields(self):
        """No job-wide voice is assumed: each unit row (its own description, and any later field
        such as voiced segments) is copied verbatim, so a multi-voice cast can be redone."""
        from eav import colab_jobs
        rows = [{"unit_key": "f01s001-001", "text": "Narrated line.", "description": "narrator voice",
                 "pause_after_ms": 400},
                {"unit_key": "f01s001-002", "text": "“Hello,” she said.",
                 "description": "a woman's voice", "pause_after_ms": 400,
                 "segments": [{"text": "“Hello,”", "role": "character", "speaker": "bimala"},
                              {"text": " she said.", "role": "narrator", "speaker": "narrator"}]}]
        old = {"schema": "earnalism.audiovisual-job.v1", "kind": "narration", "job_id": "narration-x",
               "title": "t", "model": colab_jobs.NARRATION_REPO, "units": rows,
               "generation": {"temperature": 0.91}, "batch": 8}
        build = {"model": {"repo": colab_jobs.NARRATION_REPO, "revision": "abc"},
                 "generation": {"temperature": 0.91}}
        plan = colab_jobs._redo_plan(old, build, ["f01s001-002"], RATES)
        self.assertEqual(plan["payload"]["units"], [rows[1]])
        self.assertEqual(plan["payload"]["generation"], {"temperature": 0.91})
        self.assertEqual(plan["revision"], "abc")

    def test_reel_narration_is_refused(self):
        job_id, key, _ = self.cut_source()
        rec = Record.load(self.root)
        # the source must be film narration: a reel narration's redo is refused
        for e in rec.data["events"]:
            if e["stage"] == "cli" and e["result"] == "job_target" and e["detail"]["job_id"] == job_id:
                e["detail"]["target"] = "reel-1"
        rec._save()
        code, out = self.redo(f"{job_id}:{key}")
        self.assertNotEqual(code, 0)
        self.assertIn("re-voiced as a whole", out)


if __name__ == "__main__":
    unittest.main()
