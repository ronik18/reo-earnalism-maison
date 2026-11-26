"""B5: Modal runs through the GitHub Actions workflow; outputs through the private R2 bucket.

modal-request (caps, one pending row, duplicates, schema), modal-run --request (reuses that row),
r2-upload and modal-fetch against a fake Cloudflare API opener (no network), and the workflow file."""
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

from eav import budget, cli, modal_requests, modal_run
from tests.test_modal_run import ModalRunCliTests, fake_runner, fakes, run

REPO = next(p for p in Path(__file__).resolve().parents if (p / "AGENTS.md").is_file())
WORKFLOW = REPO / ".github" / "workflows" / "modal-jobs.yml"
SECRETS = {"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "CLOUDFLARE_R2_TOKEN"}
OBJECTS = (f"{modal_requests.API}/accounts/{modal_requests.R2_ACCOUNT}/r2/buckets/"
           f"{modal_requests.R2_BUCKET}/objects")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeR2:
    """The Cloudflare R2 object API, in memory: PUT/GET objects/<key>, GET objects?prefix= with
    cursor pagination (page_size keys per page). Records every request's method, URL and headers."""

    def __init__(self, page_size=2):
        self.store, self.page_size, self.calls = {}, page_size, []

    def open(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        self.calls.append((method, url, dict(req.header_items())))
        assert url.startswith(OBJECTS), url
        rest = url[len(OBJECTS):]
        if rest.startswith("?"):
            q = urllib.parse.parse_qs(rest[1:])
            keys = sorted(k for k in self.store if k.startswith(q["prefix"][0]))
            start = int(q.get("cursor", ["0"])[0])
            page = keys[start:start + self.page_size]
            more = start + self.page_size < len(keys)
            return _Resp(json.dumps({
                "success": True, "errors": [], "messages": [],
                "result": [{"key": k, "size": len(self.store[k]), "etag": "x"} for k in page],
                "result_info": {"cursor": str(start + self.page_size) if more else "",
                                "is_truncated": more, "per_page": self.page_size}}).encode())
        key = urllib.parse.unquote(rest[1:])
        if method == "PUT":
            self.store[key] = req.data
            return _Resp(json.dumps({"success": True, "errors": [], "result": {"key": key}}).encode())
        if key not in self.store:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _Resp(self.store[key])


class ModalRequestTests(unittest.TestCase):
    MONTH = "2026-11"
    modal_patch = ModalRunCliTests.modal_patch
    ledger_bytes = ModalRunCliTests.ledger_bytes

    def setUp(self):
        ModalRunCliTests.setUp(self)
        (self.d / ".git").mkdir()  # the title root sits in a checkout: titles/selfish-giant
        self.ledger = budget.Ledger(self.d / "titles" / "allowance-ledger.json")
        p = mock.patch.object(cli, "_MONTH", self.MONTH)
        p.start()
        self.addCleanup(p.stop)
        self.slug = cli.Record.load(self.root).data["title_slug"]
        self.req_path = self.d / "titles" / "modal-requests" / f"{self.job_id}.json"
        self.r2 = FakeR2()
        p = mock.patch.object(modal_requests, "default_opener", lambda: self.r2)
        p.start()
        self.addCleanup(p.stop)
        self.timeout_s = modal_run.plan(self.root / "jobs" / self.job_id / "narration.ipynb",
                                        self.root / "jobs" / self.job_id / "inputs.zip")["timeout_seconds"]

    def request(self, *extra):
        if "--colab-units" not in extra:
            extra = (*extra, "--colab-units", 0)
        return run("modal-request", self.job_id, "--root", self.root, *extra)

    def req(self):
        return json.loads(self.req_path.read_text())

    def set_status(self, status):
        data = self.req()
        data["status"] = status
        self.req_path.write_text(json.dumps(data))

    def rows(self):
        return [(r["status"], round(r["usd"], 6)) for r in self.ledger.modal_rows(job_id=self.job_id)]

    # ------------------------------------------------------------ modal-request
    def test_request_file_schema_and_one_pending_row(self):
        code, out = self.request("--colab-units", 1.5)
        self.assertEqual(code, 0, out)
        req = self.req()
        self.assertLessEqual({"schema", "job_id", "title_root", "requested_at", "status"}, set(req))
        self.assertEqual((req["schema"], req["job_id"], req["title_root"], req["status"]),
                         ("earnalism.modal-request.v1", self.job_id, "titles/selfish-giant", "requested"))
        self.assertRegex(req["requested_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual(req["colab_units"], 1.5)
        self.assertEqual(req["r2_prefix"], f"gpu-jobs/{self.slug}/{self.job_id}/")
        worst = self.timeout_s * modal_run.L4_USD_PER_S
        self.assertEqual(self.rows(), [("pending", round(worst, 6))])
        self.assertEqual(req["pending_run_id"], self.ledger.modal_rows(job_id=self.job_id)[0]["run_id"])
        (entry,) = [e for e in json.loads(self.ledger_bytes()) if e.get("job_id") == self.job_id]
        self.assertEqual((entry["runner"], entry["colab_units"]), ("modal", 1.5))
        self.assertIn("modal-fetch", out)
        self.assertIn(modal_requests.BRANCH, out)

    def test_duplicate_request_refused_while_requested_or_running(self):
        self.assertEqual(self.request()[0], 0)
        before = (self.req_path.read_bytes(), self.ledger_bytes())
        for status in ("requested", "running"):
            self.set_status(status)
            before = (self.req_path.read_bytes(), self.ledger_bytes())
            code, out = self.request()
            self.assertEqual(code, 2, out)
            self.assertIn(f"already has a {status} request", out)
            self.assertEqual((self.req_path.read_bytes(), self.ledger_bytes()), before)
        self.assertEqual(len(self.rows()), 1)

    def test_cap_refusal_writes_nothing(self):
        self.ledger.record_modal_spend(self.MONTH, "other-job", 29.5, 1.0, "ok", "t")
        before = self.ledger_bytes()
        with mock.patch.object(modal_run, "L4_USD_PER_S", 0.60 / self.timeout_s):
            code, out = self.request()
        self.assertEqual(code, 3, out)
        self.assertIn("Modal month cap", out)
        self.assertFalse(self.req_path.exists())
        self.assertEqual(self.ledger_bytes(), before)

    def test_title_cap_counts_the_pending_row_of_a_request(self):
        with mock.patch.object(modal_run, "L4_USD_PER_S", 5.0 / self.timeout_s):
            self.assertEqual(self.request()[0], 0)
            self.set_status("done")  # finished but its row was never replaced: still counts
            code, out = self.request()
        self.assertEqual(code, 3, out)
        self.assertIn("title cap", out)

    def test_colab_units_required_and_validated(self):
        code, out = run("modal-request", self.job_id, "--root", self.root)
        self.assertEqual(code, 2, out)
        self.assertIn("--colab-units is required", out)
        code, out = self.request("--colab-units", -1)
        self.assertEqual(code, 2, out)
        self.assertFalse(self.req_path.exists())
        self.assertEqual(self.rows(), [])

    def test_request_refuses_what_modal_run_refuses(self):
        zip_path = self.root / "jobs" / self.job_id / "inputs.zip"
        zip_path.write_bytes(zip_path.read_bytes() + b"x")
        code, out = self.request()
        self.assertEqual(code, 2, out)
        self.assertIn("does not match", out)
        self.assertFalse(self.req_path.exists())

    def test_local_modal_run_refused_while_a_request_is_open(self):
        self.assertEqual(self.request()[0], 0)
        calls = []
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.1, calls=calls)):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual((code, calls), (2, []), out)
        self.assertIn("open Modal request", out)
        self.assertEqual(len(self.rows()), 1)

    # ------------------------------------------------------------ modal-run --request
    def test_run_request_reuses_the_pending_row(self):
        self.assertEqual(self.request("--colab-units", 0.5)[0], 0)
        self.set_status("running")
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.37, seconds=5.0)):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual(code, 0, out)
        rows = self.ledger.modal_rows(job_id=self.job_id)
        self.assertEqual([(r["status"], r["usd"], r["seconds"]) for r in rows], [("ok", 0.37, 5.0)])
        req = self.req()
        self.assertEqual((req["status"], req["run"]["status"], req["run"]["usd"], req["run"]["run_id"]),
                         ("running", "ok", 0.37, rows[0]["run_id"]))
        self.assertEqual(self.ledger.colab_units_before_modal(self.job_id), 0.5)

    def test_run_request_failure_still_replaces_the_row(self):
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.22, "failed")):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual(code, 2, out)
        self.assertEqual(self.rows(), [("failed", 0.22)])
        self.assertEqual(self.req()["run"]["status"], "failed")

    def test_run_request_refusals(self):
        code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual(code, 2, out)
        self.assertIn("no request file", out)
        self.assertEqual(self.request("--colab-units", 1)[0], 0)
        calls = []
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.1, calls=calls)):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request",
                            "--colab-units", 0)
            self.assertEqual(code, 2, out)
            self.assertIn("differs from the request", out)
            self.ledger.settle_pending_modal(self.job_id, 0.2)  # the row is no longer pending
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
            self.assertEqual(code, 2, out)
            self.assertIn("not pending", out)
            self.set_status("done")
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
            self.assertEqual(code, 2, out)
        self.assertEqual(calls, [])

    # ------------------------------------------------------------ r2-upload and modal-fetch
    def run_and_upload(self, runner=None):
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        dl = self.d / "runner-temp"
        with mock.patch.object(modal_run, "run_modal", runner or fake_runner(0.3, seconds=9.0)):
            run("modal-run", self.job_id, "--root", self.root, "--request", "--download", dl)
        folder = dl / "job"
        (folder / "sub").mkdir(parents=True, exist_ok=True)
        for name, body in (("manifest.json", b"{}"), ("u1.wav", b"one"), ("sub/u2.wav", b"two")):
            (folder / name).write_bytes(body)
        with mock.patch.dict(os.environ, {"CLOUDFLARE_R2_TOKEN": "test-token-value"}):
            code, out = run("r2-upload", self.job_id, "--root", self.root, "--from", folder)
        return code, out

    def test_upload_finishes_the_request_with_verified_files(self):
        code, out = self.run_and_upload()
        self.assertEqual(code, 0, out)
        self.assertNotIn("test-token-value", out)
        req = self.req()
        prefix = f"gpu-jobs/{self.slug}/{self.job_id}/"
        self.assertEqual((req["status"], req["seconds"], req["usd"], req["r2_prefix"]),
                         ("done", 9.0, 0.3, prefix))
        self.assertEqual(req["files"], [
            {"path": p, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
            for p, b in (("manifest.json", b"{}"), ("sub/u2.wav", b"two"), ("u1.wav", b"one"))])
        self.assertEqual(sorted(self.r2.store), sorted(prefix + f["path"] for f in req["files"]))
        puts = [c for c in self.r2.calls if c[0] == "PUT"]
        self.assertEqual(len(puts), 3)
        self.assertTrue(all(c[2].get("Authorization") == "Bearer test-token-value" for c in puts))
        self.assertIn(f"objects/gpu-jobs%2F{self.slug}%2F{self.job_id}%2Fsub%2Fu2.wav",
                      " ".join(c[1] for c in puts))
        # every upload was read back
        self.assertEqual(len([c for c in self.r2.calls if c[0] == "GET"]), 3)

    def test_upload_maps_hard_stop_and_records_a_failed_upload(self):
        code, out = self.run_and_upload(fake_runner(0.3, "hard_stopped"))
        self.assertEqual((code, self.req()["status"]), (0, "hard_stopped"), out)
        req_path, other = self.req_path, self.d / "empty"
        other.mkdir()
        self.set_status("running")
        code, out = run("r2-upload", self.job_id, "--root", self.root, "--from", other)
        self.assertEqual(code, 2, out)
        req = json.loads(req_path.read_text())
        self.assertEqual((req["status"], req["files"]), ("failed", []))
        self.assertIn("upload:", req["error"])

    def fetch(self, *extra):
        return run("modal-fetch", self.job_id, "--root", self.root, *extra)

    def test_fetch_downloads_paginated_and_verified_and_never_imports(self):
        self.assertEqual(self.run_and_upload()[0], 0)
        self.r2.calls.clear()
        with mock.patch.object(cli.importer, "import_job", side_effect=AssertionError("imported")):
            code, out = self.fetch()
        self.assertEqual(code, 0, out)
        dest = self.root / ".downloads" / self.job_id
        self.assertEqual((dest / "sub" / "u2.wav").read_bytes(), b"two")
        self.assertEqual((dest / "u1.wav").read_bytes(), b"one")
        self.assertEqual((self.root / ".downloads" / ".gitignore").read_text(), "*\n")
        lists = [c for c in self.r2.calls if "?" in c[1]]
        self.assertEqual(len(lists), 2)  # 3 objects, 2 per page
        self.assertIn("cursor=2", lists[1][1])
        self.assertTrue(all("Authorization" not in c[2] for c in self.r2.calls))
        self.assertIn(f"eav.cli import {self.job_id} --root {self.root} --from {dest}", out)

    def test_fetch_into_and_refusals_leave_nothing(self):
        self.assertEqual(self.run_and_upload()[0], 0)
        key = f"gpu-jobs/{self.slug}/{self.job_id}/u1.wav"
        good = self.r2.store[key]
        self.r2.store[key] = b"tampered"
        code, out = self.fetch("--into", self.d / "into")
        self.assertEqual(code, 2, out)
        self.assertIn("sha256 differs", out)
        self.assertFalse((self.d / "into").exists())
        self.assertEqual([p.name for p in self.d.iterdir() if p.name.startswith(".into")], [])
        del self.r2.store[key]
        code, out = self.fetch("--into", self.d / "into")
        self.assertEqual(code, 2, out)
        self.assertIn("missing in R2: u1.wav", out)
        self.assertFalse((self.d / "into").exists())
        self.r2.store[key] = good
        self.r2.store[key + ".extra"] = b"x"
        code, out = self.fetch("--into", self.d / "into")
        self.assertEqual(code, 2, out)
        self.assertIn("not in the request", out)
        del self.r2.store[key + ".extra"]
        code, out = self.fetch("--into", self.d / "into")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.d / "into" / "u1.wav").read_bytes(), b"one")

    def test_fetch_refuses_an_unfinished_or_missing_request(self):
        code, out = self.fetch()
        self.assertEqual(code, 2, out)
        self.assertIn("no request file", out)
        self.assertEqual(self.request()[0], 0)
        for status in ("requested", "running"):
            self.set_status(status)
            code, out = self.fetch()
            self.assertEqual(code, 2, out)
            self.assertIn("has not finished", out)
        self.assertEqual(self.r2.calls, [])

    def test_list_parser_tolerates_other_shapes(self):
        class Opener:
            def __init__(self, pages):
                self.pages = pages

            def open(self, req, timeout=None):
                return _Resp(json.dumps(self.pages.pop(0)).encode())

        pages = [{"success": True, "result": {"objects": [{"key": "p/a"}], "cursor": "c1",
                                              "is_truncated": True}},
                 {"result": [{"key": "p/b"}], "result_info": {"is_truncated": False}}]
        self.assertEqual(modal_requests.list_keys("p/", Opener(pages)), ["p/a", "p/b"])
        with self.assertRaises(modal_requests.R2Error):
            modal_requests.list_keys("p/", Opener([{"success": False, "errors": [{"code": 10006}]}]))

    def test_end_to_end_request_run_upload_fetch_import(self):
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        fm, patched = self.modal_patch()
        dl = self.d / "runner-temp"
        with fakes(), patched:
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request", "--download", dl)
        self.assertEqual(code, 0, out)
        self.assertEqual(run("r2-upload", self.job_id, "--root", self.root, "--from", dl / self.job_id)[0], 0)
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        dest = self.root / ".downloads" / self.job_id
        code, out = run("import", self.job_id, "--root", self.root, "--from", dest)
        self.assertEqual(code, 0, out)
        self.assertIn("settled from its Modal rows", out)
        self.assertEqual([r["status"] for r in self.ledger.modal_rows(job_id=self.job_id)], ["ok"])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_secrets_are_only_the_three_names_and_never_echoed(self):
        self.assertEqual(set(re.findall(r"secrets\.([A-Za-z0-9_]+)", self.text)), SECRETS)
        for name in SECRETS:
            self.assertNotRegex(self.text, r"echo[^\n]*\$\{?" + name)
            self.assertNotIn(f"set -x", self.text)
        self.assertNotRegex(self.text, r"echo[^\n]*secrets\.")

    def test_trigger_paths_exclude_the_readme(self):
        readme = REPO / "production" / "audiovisual" / "modal-requests" / "README.md"
        self.assertTrue(readme.is_file())
        self.assertIn("paths: ['production/audiovisual/modal-requests/*.json']", self.text)
        self.assertIn("set -euo pipefail", self.text)
        self.assertIn("modal-run \"$job_id\" --root \"$root\" --request", self.text)
        self.assertIn("r2-upload", self.text)

    @unittest.skipUnless(__import__("importlib").util.find_spec("yaml"), "PyYAML not installed")
    def test_workflow_parses(self):
        import yaml
        wf = yaml.safe_load(self.text)
        on = wf.get("on", wf.get(True))  # YAML 1.1 reads a bare `on` as True
        self.assertEqual(on["push"]["branches"], [modal_requests.BRANCH])
        self.assertEqual(on["push"]["paths"], ["production/audiovisual/modal-requests/*.json"])
        self.assertEqual(wf["permissions"], {"contents": "write"})
        self.assertEqual(wf["concurrency"], {"group": "modal-jobs", "cancel-in-progress": False})
        (job,) = wf["jobs"].values()
        self.assertEqual((job["runs-on"], job["timeout-minutes"]), ("ubuntu-latest", 300))
        steps = job["steps"]
        self.assertTrue(any(s.get("with", {}).get("python-version") == "3.12" for s in steps))
        self.assertTrue(any(s.get("run") == "pip install modal" for s in steps))
        env = {k: v for s in steps for k, v in (s.get("env") or {}).items()}
        self.assertEqual(env, {n: "${{ secrets.%s }}" % n for n in SECRETS})


if __name__ == "__main__":
    unittest.main()
