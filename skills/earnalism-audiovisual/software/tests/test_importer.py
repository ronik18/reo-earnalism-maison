import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eav import colab_jobs, importer
from eav.budget import Ledger
from eav.importer import ImportHeld
from eav.record import Record

RATES = {k: {"s_per_step": 1.0, "units_per_hour": 10.0, "decode_s": 30, "export_s": 20}
         for k in ("narration", "stills", "music")}
COMPUTE = {"steps": 1, "items": 2, "takes": 1, "decode_s": 30, "export_s": 20}
PRESET = {"description": "A calm warm female voice, very clear, close to the microphone."}
SCENE = {"scene_id": "s01", "text": "The morning was quiet. Rain fell on the roof."}
MODEL_INFO = {"repo": "black-forest-labs/FLUX.1-schnell", "revision": "a" * 40}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class ImporterTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.record = Record.create(self.root / "rec", "garden-book", {"x": 1})
        self.ledger = Ledger(self.root / "ledger.json")
        out = self.root / "rec" / "jobs"
        out.mkdir()
        self.job = colab_jobs.build_job(
            "stills", self.record, {"items": [{"key": "a", "prompt": "a lamp", "seed": 1}]}, self.ledger, RATES, out, month="2026-11")
        self.zip_sha = sha(Path(self.job["inputs_zip"]).read_bytes())
        self.dl = self.root / "download"
        self.dl.mkdir()

    def download(self, files=None, **manifest_over):
        files = files or {"a.png": b"png-a", "b.png": b"png-b"}
        for name, data in files.items():
            (self.dl / name).write_bytes(data)
        manifest = {"schema": "earnalism.audiovisual-outputs.v1",
                    "job_id": self.job["job_id"], "kind": "stills",
                    "input_zip_sha256": self.zip_sha, "model": MODEL_INFO, "status": "COMPLETE",
                    "packages": {"diffusers": "0.31.0"},
                    "outputs": {n: sha(d) for n, d in files.items()}}
        manifest.update(manifest_over)
        (self.dl / "manifest.json").write_text(json.dumps(manifest))

    def run_import(self, units=1.5):
        return importer.import_job(self.record, self.job, self.dl, self.ledger, units)

    def assert_nothing_changed(self):
        self.assertEqual(self.record.data["artifacts"][1:], [])
        self.assertEqual([e["stage"] for e in self.record.data["events"]], ["job"])
        self.assertFalse((self.record.root / "stills").exists())
        self.assertEqual(self.ledger._load()[0]["state"], "reserved")
        self.assertEqual([p.name for p in self.record.root.iterdir() if p.name.startswith(".") and p.name != ".record.lock"], [])

    def test_clean_import_adds_artifacts_and_settles(self):
        self.download()
        arts = self.run_import()
        jid = self.job["job_id"]
        self.assertEqual(sorted(a["path"] for a in arts),
                         [f"stills/{jid}/a.png", f"stills/{jid}/b.png"])
        self.assertEqual((self.record.root / "stills" / jid / "a.png").read_bytes(), b"png-a")
        self.assertEqual(arts[0]["kind"], "stills")
        self.assertEqual(arts[0]["meta"]["model"], MODEL_INFO)
        entry = self.ledger._load()[0]
        self.assertEqual((entry["state"], entry["units"]), ("settled", 1.5))
        ev = self.record.data["events"][-1]
        self.assertEqual((ev["stage"], ev["result"]), ("import", "accepted"))
        self.assertEqual(ev["detail"]["model"], MODEL_INFO)
        self.assertEqual(Record.load(self.record.root).data["events"][-1], ev)

    def test_missing_file_holds_and_changes_nothing(self):
        self.download()
        (self.dl / "b.png").unlink()
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_extra_file_holds(self):
        self.download()
        (self.dl / "stray.txt").write_text("x")
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_hash_mismatch_holds(self):
        self.download()
        (self.dl / "a.png").write_bytes(b"tampered")
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_input_zip_sha_mismatch_holds(self):
        self.download(input_zip_sha256="0" * 64)
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_wrong_job_id_or_kind_holds(self):
        self.download(job_id="other-job")
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.download(kind="music")
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_missing_manifest_and_unsafe_names_hold(self):
        self.download()
        (self.dl / "manifest.json").unlink()
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.download(outputs={"../evil.png": sha(b"x")})
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_inputs_zip_copy_allowed_only_if_identical(self):
        self.download()
        (self.dl / "inputs.zip").write_bytes(Path(self.job["inputs_zip"]).read_bytes())
        self.assertEqual(len(self.run_import()), 2)

    def test_exchange_json_in_a_drive_download_is_never_an_output(self):
        """A manually downloaded Drive folder carries exchange.json (capability URLs): it is
        skipped, never imported, and can never be listed as an output."""
        self.download()
        (self.dl / "exchange.json").write_text('{"inputs": {"url": "https://x"}}')
        arts = self.run_import()
        self.assertNotIn("exchange.json", [Path(a["path"]).name for a in arts])
        self.assertFalse((self.record.root / "stills" / self.job["job_id"] / "exchange.json").exists())

    def test_exchange_json_listed_as_output_holds(self):
        self.download(files={"a.png": b"png-a", "exchange.json": b"{}"})
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_inputs_zip_copy_changed_holds(self):
        self.download()
        (self.dl / "inputs.zip").write_bytes(b"different")
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_missing_model_holds(self):
        self.download()
        m = json.loads((self.dl / "manifest.json").read_text())
        del m["model"]
        (self.dl / "manifest.json").write_text(json.dumps(m))
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assert_nothing_changed()

    def test_record_failure_is_all_or_nothing(self):
        self.download()
        real = self.record.add_artifact
        n = []

        def flaky(*a, **k):
            n.append(1)
            if len(n) == 2:
                raise OSError("disk full")
            return real(*a, **k)
        with patch.object(self.record, "add_artifact", flaky):
            with self.assertRaises(OSError):
                self.run_import()
        self.assert_nothing_changed()
        self.assertEqual(len(Record.load(self.record.root).data["artifacts"]), 1)
        self.assertEqual(len(self.run_import()), 2)

    def test_incomplete_or_unmarked_manifest_holds(self):
        """R25: a hard-stopped run writes an INCOMPLETE manifest; import refuses it."""
        for status in ("INCOMPLETE", None, "complete"):
            with self.subTest(status):
                self.download(status=status)
                with self.assertRaisesRegex(ImportHeld, "COMPLETE"):
                    self.run_import()
                self.assert_nothing_changed()

    def test_manifest_without_package_versions_holds(self):
        """R26: every output manifest records the resolved package versions that ran."""
        for packages in (None, {}, {"diffusers": None}):
            with self.subTest(packages):
                self.download(packages=packages)
                with self.assertRaisesRegex(ImportHeld, "package"):
                    self.run_import()
                self.assert_nothing_changed()

    def test_manifest_missing_a_job_item_holds(self):
        self.download(files={"b.png": b"png-b"})  # the job asked for key "a"
        with self.assertRaisesRegex(ImportHeld, "a"):
            self.run_import()
        self.assert_nothing_changed()

    def test_invalid_units_and_double_import_hold(self):
        self.download()
        with self.assertRaises(ImportHeld):
            self.run_import(units=-1)
        self.assert_nothing_changed()
        self.run_import()
        with self.assertRaises(ImportHeld):
            self.run_import()
        self.assertEqual(len(self.record.data["artifacts"]), 3)


class ReelImportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.record = Record.create(self.root / "rec", "garden-book", {})
        self.ledger = Ledger(self.root / "ledger.json")
        self.ledger.reserve("garden-book", "2026-11", 5, "reel-clips-1")
        d = self.root / "rec" / "jobs" / "reel-clips-1"
        d.mkdir(parents=True)
        (d / "job.json").write_text(json.dumps({"scenes": [{"id": "s1"}, {"id": "s2"}]}))
        (d / "wan22-batch-inputs.zip").write_bytes(b"zip")
        (d / "build-manifest.json").write_text(json.dumps(
            {"schema": "earnalism.wan22-batch-build.v1"}))
        self.job = {"job_id": "reel-clips-1", "notebook": d / "x.ipynb",
                    "inputs_zip": d / "wan22-batch-inputs.zip",
                    "manifest": d / "build-manifest.json", "forecast_units": 5}
        self.archive = self.root / "export.zip"
        self.archive.write_bytes(b"archive")
        self.calls = []

    def fake_batch(self, clips=None, error=None, rejected=()):
        calls = self.calls

        class Batch:
            @staticmethod
            def import_export(archive, destination, expected_sha, job_path):
                calls.append((Path(archive), Path(destination), expected_sha, Path(job_path)))
                Path(destination).mkdir(parents=True)
                if error:
                    raise error
                out = Path(destination) / "outputs"
                out.mkdir()
                rows = []
                for sid in clips if clips is not None else ["s1", "s2"]:
                    (out / f"{sid}.mp4").write_bytes(b"mp4-" + sid.encode())
                    rows.append({"scene": sid, "file": str(out / f"{sid}.mp4"),
                                 "sha256": sha(b"mp4-" + sid.encode()),
                                 "source_image_sha256": "i" * 64,
                                 "technical_verified": True, "motion_accepted": False})
                (Path(destination) / "import-receipt.json").write_text(
                    json.dumps({"clips": rows, "rejected": list(rejected)}))
                return rows
        return patch.object(importer, "_load_wan_batch", return_value=Batch)

    def run_import(self, **kw):
        return importer.import_job(self.record, self.job, self.root / "unused", self.ledger,
                                   2.0, archive=self.archive,
                                   archive_sha256=kw.get("sha", "abc"))

    def test_reel_delegates_and_records_clips(self):
        with self.fake_batch(clips=["s1", "s2"]):
            arts = self.run_import()
        archive, dest, sha_arg, job_path = self.calls[0]
        self.assertEqual((archive, sha_arg), (self.archive, "abc"))
        self.assertEqual(dest, self.record.root / "reel_clips" / "reel-clips-1")
        self.assertEqual(job_path.name, "job.json")
        clips = [a for a in arts if a["kind"] == "reel_clip"]
        self.assertEqual([a["path"] for a in clips],
                         ["reel_clips/reel-clips-1/outputs/s1.mp4",
                          "reel_clips/reel-clips-1/outputs/s2.mp4"])
        self.assertFalse(clips[0]["meta"]["motion_accepted"])
        self.assertEqual(self.ledger._load()[0]["state"], "settled")
        self.assertEqual(self.record.data["events"][-1]["result"], "accepted")

    def test_reel_requires_archive_and_sha(self):
        with self.assertRaises(ImportHeld):
            importer.import_job(self.record, self.job, self.root, self.ledger, 2.0)
        self.assertEqual(self.ledger._load()[0]["state"], "reserved")

    def test_reel_export_failure_holds_and_cleans_up(self):
        with self.fake_batch(error=ValueError("Export archive hash mismatch")):
            with self.assertRaises(ImportHeld):
                self.run_import()
        self.assertFalse((self.record.root / "reel_clips" / "reel-clips-1").exists())
        self.assertEqual(self.record.data["artifacts"], [])
        self.assertEqual(self.ledger._load()[0]["state"], "reserved")

    def assert_reel_unchanged(self):
        self.assertFalse((self.record.root / "reel_clips" / "reel-clips-1").exists())
        self.assertEqual(self.record.data["artifacts"], [])
        self.assertEqual(self.record.data["events"], [])
        self.assertEqual(self.ledger._load()[0]["state"], "reserved")

    def test_reel_missing_scene_holds(self):
        with self.fake_batch(clips=["s1"]):
            with self.assertRaises(ImportHeld):
                self.run_import()
        self.assert_reel_unchanged()

    def test_reel_rejected_clip_holds(self):
        with self.fake_batch(rejected=[{"scene": "s3", "reason": "bad"}]):
            with self.assertRaises(ImportHeld):
                self.run_import()
        self.assert_reel_unchanged()

    def test_reel_preexisting_destination_is_preserved(self):
        dest = self.record.root / "reel_clips" / "reel-clips-1"
        dest.mkdir(parents=True)
        (dest / "keep.txt").write_text("x")
        with self.fake_batch():
            with self.assertRaises(ImportHeld):
                self.run_import()
        self.assertTrue((dest / "keep.txt").exists())

    def test_reel_unexpected_error_cleans_up_and_propagates(self):
        with self.fake_batch(error=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_import()
        self.assert_reel_unchanged()

    def test_reel_record_failure_is_all_or_nothing(self):
        real = self.record.add_artifact
        n = []

        def flaky(*a, **k):
            n.append(1)
            if len(n) == 2:
                raise OSError("disk full")
            return real(*a, **k)
        with self.fake_batch(), patch.object(self.record, "add_artifact", flaky):
            with self.assertRaises(Exception):
                self.run_import()
        self.assert_reel_unchanged()
        self.assertEqual(Record.load(self.record.root).data["artifacts"], [])
        with self.fake_batch():
            self.assertEqual(len(self.run_import()), 3)

    def test_reel_real_import_export_wrong_sha_holds(self):
        with patch.object(importer, "_load_wan_batch", colab_jobs._load_wan_batch):
            with self.assertRaises(ImportHeld):
                self.run_import(sha="0" * 64)
        self.assert_reel_unchanged()

    def test_reel_with_no_accepted_clips_holds(self):
        with self.fake_batch(clips=[]):
            with self.assertRaises(ImportHeld):
                self.run_import()
        self.assertEqual(self.record.data["artifacts"], [])
        self.assertEqual(self.ledger._load()[0]["state"], "reserved")


if __name__ == "__main__":
    unittest.main()
