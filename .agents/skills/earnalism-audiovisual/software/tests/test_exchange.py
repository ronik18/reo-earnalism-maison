"""R2 exchange for Colab jobs: stage inputs, accept signed URLs, collect outputs safely.

No network: the Cloudflare uploader/downloader are patched; URLs here are fixtures."""
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from eav import exchange
from eav.record import Record
from tests.test_cli import RATES, SOURCE, run

ACCOUNT = "0123456789abcdef0123456789abcdef"
BUCKET = "maison-private"
SIGNATURE = "X-Amz-Signature=deadbeefcafe"


def signed_line(key, method, hours=6, url_key=None, headers=None):
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    url = (f"https://{ACCOUNT}.r2.cloudflarestorage.com/{BUCKET}/{url_key or key}"
           f"?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires={int(hours * 3600)}"
           f"&X-Amz-Date={(expires - timedelta(hours=hours)).strftime('%Y%m%dT%H%M%SZ')}"
           f"&{SIGNATURE}")
    if headers is None:
        headers = {"Content-Type": "application/x-tar"} if method == "PUT" else {}
    return {"key": key, "method": method, "url": url, "headers": headers,
            "expires_at": expires.isoformat()}


def tar_of(entries, path):
    """entries: list of (TarInfo, bytes|None)."""
    with tarfile.open(path, "w") as tar:
        for info, data in entries:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


def reg(name, data=b"x"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


class SafeExtractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.dest = self.d / "out"

    def refused(self, entries, needle):
        tar = tar_of(entries, self.d / "o.tar")
        with self.assertRaises(exchange.ExchangeError) as ctx:
            exchange.safe_extract(tar, self.dest)
        self.assertIn(needle, str(ctx.exception))
        self.assertFalse(self.dest.exists(), "a refused archive leaves nothing behind")

    def test_clean_flat_archive_extracts(self):
        tar = tar_of([reg("manifest.json", b"{}"), reg("a.wav", b"RIFF")], self.d / "o.tar")
        names = exchange.safe_extract(tar, self.dest)
        self.assertEqual(sorted(names), ["a.wav", "manifest.json"])
        self.assertEqual((self.dest / "a.wav").read_bytes(), b"RIFF")

    def test_traversal_and_absolute_paths_refused(self):
        self.refused([reg("manifest.json"), reg("../evil.wav")], "unsafe member name")
        self.refused([reg("manifest.json"), reg("/etc/evil.wav")], "unsafe member name")
        self.refused([reg("sub/a.wav")], "unsafe member name")

    def test_links_and_non_regular_members_refused(self):
        link = tarfile.TarInfo("a.wav")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        self.refused([reg("manifest.json"), (link, None)], "not a regular file")
        hard = tarfile.TarInfo("b.wav")
        hard.type, hard.linkname = tarfile.LNKTYPE, "manifest.json"
        self.refused([reg("manifest.json"), (hard, None)], "not a regular file")
        folder = tarfile.TarInfo("dir")
        folder.type = tarfile.DIRTYPE
        self.refused([(folder, None)], "not a regular file")

    def test_duplicate_members_refused(self):
        self.refused([reg("a.wav", b"1"), reg("a.wav", b"2")], "duplicate member")

    def test_compressed_or_garbage_archive_refused(self):
        (self.d / "o.tar").write_bytes(b"not a tar at all" * 100)
        with self.assertRaises(exchange.ExchangeError):
            exchange.safe_extract(self.d / "o.tar", self.dest)
        self.assertFalse(self.dest.exists())


class ExchangeCliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / "selfish-giant"
        self.src = self.d / "selfish-giant.json"
        self.src.write_text(json.dumps(SOURCE), encoding="utf-8")
        self.rates = self.d / "rates.json"
        self.rates.write_text(json.dumps(RATES), encoding="utf-8")
        self.assertEqual(run("init", self.src, "--root", self.root)[0], 0)
        self.assertEqual(run("plan", "--root", self.root)[0], 0)
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates,
                        "--job-id", "narration-x1")
        self.assertEqual(code, 0, out)
        self.job_id, self.job_dir = "narration-x1", self.root / "jobs" / "narration-x1"
        self.prefix = f"exports/colab-exchange/selfish-giant/{self.job_id}"
        self.uploads = []
        env = mock.patch.dict("os.environ", {"CLOUDFLARE_API_TOKEN": "placeholder"})
        env.start()
        self.addCleanup(env.stop)

    # ------------------------------------------------------------ stage
    def fake_upload(self, account, bucket, key, path, content_type, token):
        self.uploads.append((account, bucket, key, Path(path).read_bytes(), content_type, token))

    def upload(self):
        with mock.patch.object(exchange, "cloudflare_upload", self.fake_upload):
            return run("exchange-stage", self.job_id, "--root", self.root,
                       "--account", ACCOUNT, "--bucket", BUCKET)

    def sign(self, lines):
        path = self.d / "signed.jsonl"
        path.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
        return run("exchange-stage", self.job_id, "--root", self.root, "--signed", path)

    def good(self, **kw):
        return [signed_line(f"{self.prefix}/inputs.zip", "GET", **kw),
                signed_line(f"{self.prefix}/outputs.tar", "PUT", **kw)]

    def test_stage_uploads_inputs_and_prints_presign_requests(self):
        code, out = self.upload()
        self.assertEqual(code, 0, out)
        [(account, bucket, key, body, ctype, token)] = self.uploads
        self.assertEqual((account, bucket, key, ctype, token),
                         (ACCOUNT, BUCKET, f"{self.prefix}/inputs.zip", "application/zip", "placeholder"))
        self.assertEqual(body, (self.job_dir / "inputs.zip").read_bytes())
        self.assertIn(f"presign_colab_exchange --key {self.prefix}/inputs.zip --method GET", out)
        self.assertIn(f"presign_colab_exchange --key {self.prefix}/outputs.tar --method PUT "
                      "--content-type application/x-tar", out)
        self.assertFalse((self.job_dir / "exchange.json").exists())
        events = [e for e in Record.load(self.root).data["events"] if e["stage"] == "job"]
        self.assertEqual(events[-1]["result"], "exchange_uploaded")

    def test_stage_needs_account_bucket_and_token(self):
        with mock.patch.object(exchange, "cloudflare_upload", self.fake_upload), \
                mock.patch.dict("os.environ", {"EAV_R2_ACCOUNT": "", "EAV_R2_BUCKET": ""}):
            code, out = run("exchange-stage", self.job_id, "--root", self.root)
        self.assertEqual(code, 2, out)
        with mock.patch.object(exchange, "cloudflare_upload", self.fake_upload), \
                mock.patch.dict("os.environ", {"EAV_R2_ACCOUNT": ACCOUNT, "EAV_R2_BUCKET": BUCKET,
                                               "CLOUDFLARE_API_TOKEN": ""}):
            code, out = run("exchange-stage", self.job_id, "--root", self.root)
        self.assertEqual(code, 2, out)
        self.assertEqual(self.uploads, [])

    def test_signed_requests_write_exchange_json(self):
        self.assertEqual(self.upload()[0], 0)
        lines = self.good()
        code, out = self.sign(lines)
        self.assertEqual(code, 0, out)
        data = json.loads((self.job_dir / "exchange.json").read_text())
        raw = (self.job_dir / "inputs.zip").read_bytes()
        self.assertEqual(data["schema"], "earnalism.colab-exchange.v1")
        self.assertEqual((data["job_id"], data["title"]), (self.job_id, "selfish-giant"))
        self.assertEqual(data["inputs"], {"url": lines[0]["url"], "bytes": len(raw),
                                          "sha256": hashlib.sha256(raw).hexdigest()})
        self.assertEqual(data["outputs"], {"url": lines[1]["url"], "method": "PUT",
                                           "headers": {"Content-Type": "application/x-tar"}})
        self.assertGreater(datetime.fromisoformat(data["expires_at"]),
                           datetime.now(timezone.utc) + timedelta(hours=5))
        record_text = (self.root / "record.json").read_text()
        self.assertNotIn("https://", record_text)  # capabilities never reach the record
        self.assertNotIn(SIGNATURE, record_text)
        staged = [e for e in Record.load(self.root).data["events"]
                  if e["result"] == "exchange_staged"]
        self.assertEqual(staged[-1]["detail"]["inputs_key"], f"{self.prefix}/inputs.zip")
        self.assertEqual(staged[-1]["detail"]["outputs_key"], f"{self.prefix}/outputs.tar")
        self.assertIn("expires_at", staged[-1]["detail"])
        code, out = run("status", "--root", self.root)
        self.assertIn("exchange.json", out)
        self.assertIn(f"exchange-collect {self.job_id}", out)

    def assert_refused(self, lines, needle):
        code, out = self.sign(lines)
        self.assertEqual(code, 2, out)
        self.assertIn(needle, out)
        self.assertFalse((self.job_dir / "exchange.json").exists())
        self.assertNotIn("exchange_staged", (self.root / "record.json").read_text())

    def test_short_expiry_refused(self):
        self.assertEqual(self.upload()[0], 0)
        self.assert_refused(self.good(hours=1), "expire")

    def test_expiry_shorter_in_url_than_claimed_is_refused(self):
        self.assertEqual(self.upload()[0], 0)
        lines = self.good()
        lines[0]["url"] = lines[0]["url"].replace("X-Amz-Expires=21600", "X-Amz-Expires=600")
        self.assert_refused(lines, "expire")

    def test_wrong_key_refused(self):
        self.assertEqual(self.upload()[0], 0)
        lines = self.good()
        other = "exports/colab-exchange/selfish-giant/narration-other/inputs.zip"
        lines[0] = signed_line(other, "GET")
        self.assert_refused(lines, "key")
        lines = self.good()
        lines[0]["url"] = lines[0]["url"].replace(self.job_id, "narration-other")
        self.assert_refused(lines, "URL")

    def test_wrong_method_refused(self):
        self.assertEqual(self.upload()[0], 0)
        lines = self.good()
        lines[0]["method"] = "PUT"
        self.assert_refused(lines, "method")
        lines = self.good()
        lines[1] = signed_line(f"{self.prefix}/outputs.tar", "PUT",
                               headers={"Content-Type": "application/zip"})
        self.assert_refused(lines, "Content-Type")

    def test_signed_before_upload_refused(self):
        self.assert_refused(self.good(), "exchange-stage")

    def test_ended_or_imported_job_refused(self):
        self.assertEqual(self.upload()[0], 0)
        self.assertEqual(run("supersede", self.job_id, "--root", self.root,
                             "--reason", "never ran")[0], 0)
        self.assert_refused(self.good(), "superseded")
        with mock.patch.object(exchange, "cloudflare_upload", self.fake_upload):
            code, out = run("exchange-stage", self.job_id, "--root", self.root,
                            "--account", ACCOUNT, "--bucket", BUCKET)
        self.assertEqual(code, 2, out)

    # ------------------------------------------------------------ collect
    def outputs_folder(self, status="COMPLETE"):
        folder = self.d / "colab-out"
        folder.mkdir()
        with zipfile.ZipFile(self.job_dir / "inputs.zip") as z:
            units = json.loads(z.read("job.json"))["units"]
        outputs = {}
        for u in units:
            p = folder / f"{u['unit_key']}.wav"
            p.write_bytes(b"RIFF" + u["unit_key"].encode())
            outputs[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": self.job_id,
            "title": "selfish-giant", "kind": "narration",
            "input_zip_sha256": hashlib.sha256((self.job_dir / "inputs.zip").read_bytes()).hexdigest(),
            "model": {"repo": "ai4bharat/indic-parler-tts", "revision": "x"}, "status": status,
            "packages": {"parler_tts": "0.2.2"}, "outputs": outputs}), encoding="utf-8")
        return folder

    def staged(self):
        self.assertEqual(self.upload()[0], 0)
        self.assertEqual(self.sign(self.good())[0], 0)

    def collect(self, tar_path, *extra):
        calls = []

        def fake_download(account, bucket, key, dest, token, max_bytes):
            calls.append((account, bucket, key))
            shutil.copyfile(tar_path, dest)
        with mock.patch.object(exchange, "cloudflare_download", fake_download):
            code, out = run("exchange-collect", self.job_id, "--root", self.root, "--units", 1.25,
                            "--account", ACCOUNT, "--bucket", BUCKET, *extra)
        return code, out, calls

    def tar_folder(self, folder):
        path = self.d / "outputs.tar"
        with tarfile.open(path, "w") as tar:
            for p in sorted(folder.iterdir()):
                tar.add(p, arcname=p.name)
        return path

    def leftovers(self):
        return [p.name for p in self.root.iterdir() if p.name.startswith(".") and p.name != ".record.lock"]

    def test_collect_imports_through_the_importer_and_cleans_up(self):
        self.staged()
        code, out, calls = self.collect(self.tar_folder(self.outputs_folder()))
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, [(ACCOUNT, BUCKET, f"{self.prefix}/outputs.tar")])
        rec = Record.load(self.root)
        self.assertTrue(any(e["result"] == "accepted" and e["detail"]["job_id"] == self.job_id
                            for e in rec.data["events"]))
        self.assertEqual(rec.data["events"][-1]["result"], "exchange_collected")
        self.assertTrue(list((self.root / "narration" / self.job_id).glob("*.wav")))
        self.assertEqual(self.leftovers(), [])

    def test_collect_incomplete_manifest_is_held_and_cleaned(self):
        self.staged()
        code, out, _ = self.collect(self.tar_folder(self.outputs_folder(status="INCOMPLETE")))
        self.assertEqual(code, 4, out)
        self.assertIn("INCOMPLETE", out)
        self.assertFalse((self.root / "narration" / self.job_id).exists())
        self.assertEqual(self.leftovers(), [])
        self.assertNotIn("exchange_collected", (self.root / "record.json").read_text())

    def test_collect_tampered_output_is_held(self):
        self.staged()
        folder = self.outputs_folder()
        next(folder.glob("*.wav")).write_bytes(b"tampered")
        code, out, _ = self.collect(self.tar_folder(folder))
        self.assertEqual(code, 4, out)
        self.assertEqual(self.leftovers(), [])

    def test_collect_unsafe_archive_is_held_and_cleaned(self):
        self.staged()
        folder = self.outputs_folder()
        path = self.d / "evil.tar"
        with tarfile.open(path, "w") as tar:
            for p in sorted(folder.iterdir()):
                tar.add(p, arcname=p.name)
            info, data = reg("../escape.wav", b"x")
            tar.addfile(info, io.BytesIO(data))
        code, out, _ = self.collect(path)
        self.assertEqual(code, 4, out)
        self.assertFalse((self.root.parent / "escape.wav").exists())
        self.assertEqual(self.leftovers(), [])
        self.assertFalse((self.root / "narration" / self.job_id).exists())

    def test_collect_needs_a_staged_exchange(self):
        code, out, calls = self.collect(self.tar_folder(self.outputs_folder()))
        self.assertEqual(code, 2, out)
        self.assertIn("exchange-stage", out)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
