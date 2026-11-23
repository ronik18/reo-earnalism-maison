"""Orchestrator CLI: every command prints the next owner action; gates exit non-zero."""
import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from eav import cli
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


class CliTests(unittest.TestCase):
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

    def test_bundle_audio_before_narration_import_stops_and_writes_nothing(self):
        self.build_narration()
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle)
        self.assertNotEqual(code, 0)
        self.assertIn("narration not imported", out)
        self.assertFalse(bundle.exists())
        self.assertFalse((self.root / "maison").exists())

    def test_bundle_audio_writes_measured_timing_with_provenance(self):
        job_id, job_dir = self.build_narration()
        folder, units = self.fake_colab_outputs(job_id, job_dir)
        code, out = run("import", job_id, "--root", self.root, "--from", folder, "--units", 1.5)
        self.assertEqual(code, 0, out)
        bundle = self.d / "bundle"
        code, out = run("bundle-audio", "--root", self.root, "--out", bundle)
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


class SentenceSanity(unittest.TestCase):
    def test_fixture_a2_has_two_sentences(self):
        self.assertEqual(len(sentences(PARAS[1][2])), 2)


if __name__ == "__main__":
    unittest.main()
