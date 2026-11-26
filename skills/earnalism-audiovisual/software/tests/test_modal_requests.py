"""B5: Modal runs through the GitHub Actions workflow; outputs through the private R2 bucket.

modal-request (caps, one pending row, duplicates, schema), modal-run --request (reuses that row),
r2-upload and modal-fetch against a fake Cloudflare API opener (no network), and the workflow file."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
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
SECRETS = {"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "CLOUDFLARE_R2_TOKEN", "HF_TOKEN"}
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
        self.store, self.page_size, self.calls, self.deny = {}, page_size, [], set()

    def open(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        self.calls.append((method, url, dict(req.header_items())))
        assert url.startswith(OBJECTS), url
        if method in self.deny:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        rest = url[len(OBJECTS):]
        if rest.startswith("?"):  # the verified shape: result is a plain list; a cursor only if more
            q = urllib.parse.parse_qs(rest[1:])
            assert q["per_page"] == ["1000"], q
            keys = sorted(k for k in self.store if k.startswith(q["prefix"][0]))
            start = int(q.get("cursor", ["0"])[0])
            page = keys[start:start + self.page_size]
            body = {"success": True, "errors": [], "messages": [],
                    "result": [{"key": k, "size": len(self.store[k]), "etag": "x"} for k in page]}
            if start + self.page_size < len(keys):
                body["result_info"] = {"cursor": str(start + self.page_size)}
            return _Resp(json.dumps(body).encode())
        assert "%2F" not in rest, rest  # slashes stay literal; each segment is encoded on its own
        key = "/".join(urllib.parse.unquote(seg) for seg in rest[1:].split("/"))
        if method == "PUT":
            self.store[key] = req.data
            return _Resp(json.dumps({"success": True, "errors": [], "result": {
                "key": key, "size": str(len(req.data)), "etag": "x"}}).encode())
        if key not in self.store:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if method == "DELETE":
            del self.store[key]
            return _Resp(json.dumps({"success": True, "errors": [], "result": {}}).encode())
        return _Resp(self.store[key])


class ModalRequestTests(unittest.TestCase):
    MONTH = "2026-11"
    TITLES = ("production", "audiovisual")  # the workflow runs title roots under production/audiovisual
    modal_patch = ModalRunCliTests.modal_patch
    ledger_bytes = ModalRunCliTests.ledger_bytes

    def setUp(self):
        ModalRunCliTests.setUp(self)
        (self.d / ".git").mkdir()  # the title root sits in a checkout: production/audiovisual/selfish-giant
        self.ledger = budget.Ledger(self.titles / "allowance-ledger.json")
        p = mock.patch.object(cli, "_MONTH", self.MONTH)
        p.start()
        self.addCleanup(p.stop)
        self.slug = cli.Record.load(self.root).data["title_slug"]
        self.req_path = self.titles / "modal-requests" / f"{self.job_id}.json"
        self.r2 = FakeR2()
        p = mock.patch.object(modal_requests, "default_opener", lambda: self.r2)
        p.start()
        self.addCleanup(p.stop)
        self.timeout_s = modal_run.plan(self.root / "jobs" / self.job_id / "narration.ipynb",
                                        self.root / "jobs" / self.job_id / "inputs.zip")["timeout_seconds"]

    def rate(self, usd):
        """Make the request's worst case (deadline + margin x the overhead factor) equal usd."""
        return mock.patch.object(modal_run, "L4_USD_PER_S",
                                 usd / (self.timeout_s * modal_run.MODAL_OVERHEAD_FACTOR))

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
        code, out = self.request("--colab-units", 0.75)
        self.assertEqual(code, 0, out)
        req = self.req()
        self.assertLessEqual({"schema", "job_id", "title_root", "requested_at", "status"}, set(req))
        self.assertEqual((req["schema"], req["job_id"], req["title_root"], req["status"]),
                         ("earnalism.modal-request.v1", self.job_id, "production/audiovisual/selfish-giant",
                          "requested"))
        self.assertRegex(req["requested_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual(req["colab_units"], 0.75)
        self.assertEqual(req["r2_prefix"], f"gpu-jobs/{self.slug}/{self.job_id}/run-1/")
        worst = modal_run.modal_cost(self.timeout_s)
        self.assertEqual(self.rows(), [("pending", round(worst, 6))])
        self.assertEqual(req["pending_run_id"], self.ledger.modal_rows(job_id=self.job_id)[0]["run_id"])
        (entry,) = [e for e in json.loads(self.ledger_bytes()) if e.get("job_id") == self.job_id]
        self.assertEqual((entry["runner"], entry["colab_units"]), ("modal", 0.75))
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
        with self.rate(0.60):
            code, out = self.request()
        self.assertEqual(code, 3, out)
        self.assertIn("Modal month cap", out)
        self.assertFalse(self.req_path.exists())
        self.assertEqual(self.ledger_bytes(), before)

    def test_title_cap_counts_the_pending_row_of_a_request(self):
        with self.rate(5.0):
            self.assertEqual(self.request()[0], 0)
            self.set_status("failed")  # finished but its row was never replaced: still counts
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
        self.assertEqual(self.request("--colab-units", 0.25)[0], 0)
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
        prefix = f"gpu-jobs/{self.slug}/{self.job_id}/run-1/"
        self.assertEqual((req["status"], req["seconds"], req["usd"], req["r2_prefix"]),
                         ("done", 9.0, 0.3, prefix))
        self.assertEqual(req["files"], [
            {"path": p, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
            for p, b in (("manifest.json", b"{}"), ("sub/u2.wav", b"two"), ("u1.wav", b"one"))])
        result_key = prefix + "_request-result.json"
        self.assertEqual(sorted(self.r2.store),
                         sorted([result_key] + [prefix + f["path"] for f in req["files"]]))
        self.assertEqual(json.loads(self.r2.store[result_key]), req)  # the R2 copy of the request
        puts = [c for c in self.r2.calls if c[0] == "PUT"]
        self.assertEqual(len(puts), 4)
        self.assertTrue(all(c[2].get("Authorization") == "Bearer test-token-value" for c in puts))
        self.assertIn(f"objects/gpu-jobs/{self.slug}/{self.job_id}/run-1/sub/u2.wav",
                      " ".join(c[1] for c in puts))
        # every upload was read back
        self.assertEqual(len([c for c in self.r2.calls if c[0] == "GET"]), 3)

    def test_object_urls_keep_slashes_and_encode_each_segment(self):
        url = modal_requests._object_url("gpu-jobs/a b/c?d/e.wav")
        self.assertEqual(url, OBJECTS + "/gpu-jobs/a%20b/c%3Fd/e.wav")
        self.assertIn("per_page=1000", modal_requests._list_url("gpu-jobs/x/"))

    def test_list_follows_a_cursor_without_is_truncated(self):
        self.r2.page_size = 1
        for i in range(3):
            self.r2.store[f"p/{i}"] = b"x"
        self.assertEqual(modal_requests.list_keys("p/", self.r2), ["p/0", "p/1", "p/2"])
        self.assertEqual(len(self.r2.calls), 3)

    # ------------------------------------------------------------ run-time cap re-check (I2)
    def test_request_run_in_a_later_month_counts_there(self):
        with self.rate(1.0):
            self.assertEqual(self.request()[0], 0)  # 1.00 USD pending in 2026-11
        self.set_status("running")
        with mock.patch.object(cli, "_MONTH", "2026-12"), \
                mock.patch.object(modal_run, "run_modal", fake_runner(0.4)):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ledger.modal_rows(month="2026-11"), [])
        self.assertEqual([(r["status"], r["usd"]) for r in self.ledger.modal_rows(month="2026-12")],
                         [("ok", 0.4)])

    def test_gated_model_without_hf_token_refuses_the_request_before_modal(self):
        self.assertEqual(self.request("--colab-units", 0.5)[0], 0)
        self.set_status("running")
        calls = []
        env = {k: v for k, v in os.environ.items() if k != "HF_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(modal_run, "run_modal", fake_runner(0.1, calls=calls)):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual((code, calls), (3, []), out)
        self.assertEqual(self.rows(), [])  # the pending row was released
        req = self.req()
        self.assertEqual(req["status"], "refused")
        self.assertIn("HF_TOKEN", req["error"])
        self.assertNotIn("modal_contacted_at", req)
        (entry,) = [e for e in json.loads(self.ledger_bytes()) if e.get("job_id") == self.job_id]
        self.assertNotEqual(entry.get("runner"), "modal")  # the CU reservation was restored

    def test_request_refused_when_the_run_month_is_full(self):
        with self.rate(1.0):
            self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        self.ledger.record_modal_spend("2026-12", "other-job", 29.5, 1.0, "ok", "t")
        calls = []
        with mock.patch.object(cli, "_MONTH", "2026-12"), \
                mock.patch.object(modal_run, "run_modal", fake_runner(0.1, calls=calls)):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual((code, calls), (3, []), out)
        self.assertIn("Modal month cap", out)
        self.assertEqual(self.rows(), [])  # the pending row was released
        req = self.req()
        self.assertEqual(req["status"], "refused")
        self.assertIn("Budget exceeded", req["error"])
        with mock.patch.object(cli, "_MONTH", "2026-12"), \
                self.rate(1.0):
            self.assertEqual(self.request()[0], 3)  # December is still full for a new request

    def test_request_refused_when_the_title_cap_filled_meanwhile(self):
        with self.rate(1.0):
            self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        (entry,) = [e for e in json.loads(self.ledger_bytes()) if e.get("job_id") == self.job_id]
        # another job of the same title spent 5.50 USD since the request was written
        self.ledger.reserve(entry.get("title"), self.MONTH, 0.0, "sibling-job", entry.get("edition_id"))
        self.ledger.record_modal_spend(self.MONTH, "sibling-job", 5.5, 1.0, "ok", "t")
        calls = []
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.1, calls=calls)):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual((code, calls), (3, []), out)
        self.assertIn("title cap", out)
        self.assertEqual((self.req()["status"], self.rows()), ("refused", []))

    # ------------------------------------------------------------ R2 probe before the paid run (I3)
    def test_probe_puts_lists_reads_and_deletes(self):
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        with mock.patch.dict(os.environ, {"CLOUDFLARE_R2_TOKEN": "test-token-value"}):
            code, out = run("r2-probe", self.job_id, "--root", self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual([c[0] for c in self.r2.calls], ["PUT", "GET", "GET", "DELETE"])
        self.assertIn(f"/gpu-jobs/{self.slug}/{self.job_id}/run-1/_probe/probe.txt", self.r2.calls[0][1])
        self.assertEqual(self.r2.store, {})
        self.assertEqual((self.req()["status"], len(self.rows())), ("running", 1))

    def test_probe_failure_refuses_and_releases_before_modal(self):
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        self.r2.deny = {"DELETE"}
        code, out = run("r2-probe", self.job_id, "--root", self.root)
        self.assertEqual(code, 2, out)
        self.assertIn("R2 probe failed", out)
        self.assertEqual((self.req()["status"], self.rows()), ("refused", []))
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.1, calls=[])) as _:
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual(code, 2, out)  # a refused request never runs
        self.assertEqual(self.request()[0], 0)  # a new request may follow

    # ------------------------------------------------------------ replay after a rebase conflict (I1)
    def test_replay_reapplies_only_this_jobs_rows_onto_a_newer_ledger(self):
        code, out = self.run_and_upload()
        self.assertEqual(code, 0, out)
        saved = self.d / "saved"
        saved.mkdir()
        (saved / "request.json").write_bytes(self.req_path.read_bytes())
        (saved / "ledger.json").write_bytes(self.ledger_bytes())
        mine = self.ledger.modal_rows(job_id=self.job_id)
        # the branch moved on: the ledger as it was before the run, plus root's new request row
        newer = json.loads(self.ledger_bytes())
        for rec in newer:
            for row in rec.get("rows", ()):
                if row["job_id"] == self.job_id:
                    row.update(status="pending", usd=9.9, seconds=0.0)
        newer.append({"modal_spend": "2026-11", "rows": []})
        newer = [r for r in newer if r.get("rows", [1])]
        for rec in newer:
            if rec.get("modal_spend") == self.MONTH:
                rec["rows"].append({"run_id": "next-job#9", "job_id": "next-job", "usd": 1.2,
                                    "seconds": 0.0, "at": "t", "status": "pending"})
        self.ledger._write(newer)
        self.set_status("running")
        code, out = run("modal-replay", self.job_id, "--root", self.root, "--saved", saved)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ledger.modal_rows(job_id=self.job_id), mine)
        self.assertEqual([r["usd"] for r in self.ledger.modal_rows(job_id="next-job")], [1.2])
        self.assertEqual(self.req()["status"], "done")
        code, out = run("modal-replay", "other", "--root", self.root, "--saved", saved)
        self.assertEqual(code, 2, out)

    def test_replay_of_a_refused_request_never_resurrects_its_released_row(self):
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        head = json.loads(self.ledger_bytes())  # the branch: our pending row, before the refusal
        self.r2.deny = {"PUT"}
        code, out = run("r2-probe", self.job_id, "--root", self.root)
        self.assertEqual((code, self.req()["status"], self.rows()), (2, "refused", []), out)
        saved = self.d / "saved"
        saved.mkdir()
        (saved / "request.json").write_bytes(self.req_path.read_bytes())
        (saved / "ledger.json").write_bytes(self.ledger_bytes())
        # meanwhile root pushed another job's request row into the same month (the conflict)
        for rec in head:
            if rec.get("modal_spend") == self.MONTH:
                rec["rows"].append({"run_id": "next-job#9", "job_id": "next-job", "usd": 1.2,
                                    "seconds": 0.0, "at": "t", "status": "pending"})
        self.ledger._write(head)
        self.set_status("running")
        self.assertEqual(len(self.rows()), 1)  # the released row is back on the fresh head
        code, out = run("modal-replay", self.job_id, "--root", self.root, "--saved", saved)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.rows(), [])  # no pending row for the refused request
        self.assertEqual([(r["run_id"], r["usd"], r["status"])
                          for r in self.ledger.modal_rows(job_id="next-job")],
                         [("next-job#9", 1.2, "pending")])
        self.assertEqual(self.req()["status"], "refused")
        self.assertAlmostEqual(self.ledger.modal_month_usd(self.MONTH), 1.2)

    def test_fetch_reads_the_r2_copy_when_the_branch_request_is_stale(self):
        self.assertEqual(self.run_and_upload()[0], 0)
        self.set_status("running")  # the push-back never reached the branch
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertIn("stale", out)
        self.assertIn(f"modal-results/{self.job_id}", out)
        self.assertEqual((self.root / ".downloads" / self.job_id / "u1.wav").read_bytes(), b"one")

    def test_upload_refuses_a_reserved_name(self):
        folder = self.d / "f"
        folder.mkdir()
        (folder / "_request-result.json").write_text("{}")
        with self.assertRaises(modal_requests.R2Error):
            modal_requests.upload_folder(folder, "p/", self.r2)

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
        key = f"gpu-jobs/{self.slug}/{self.job_id}/run-1/u1.wav"
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
        # only the R2 copy of the request was looked for (absent), nothing downloaded
        self.assertTrue(self.r2.calls)
        self.assertTrue(all(c[0] == "GET" and c[1].endswith("/_request-result.json")
                            for c in self.r2.calls))

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

    # ------------------------------------------------------------ F1: refused before Modal (I2, I4)
    def entry(self):
        return next(e for e in json.loads(self.ledger_bytes()) if e.get("job_id") == self.job_id)

    def test_run_request_records_modal_contacted_at(self):
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        seen = []

        def runner(notebook, inputs_zip, download_dir, gpu="L4", on_contact=None, expected_sha256=None):
            self.assertNotIn("modal_contacted_at", self.req())
            on_contact()
            seen.append(self.req()["modal_contacted_at"])
            return fake_runner(0.2)(notebook, inputs_zip, download_dir)

        with mock.patch.object(modal_run, "run_modal", runner):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual(code, 0, out)
        self.assertRegex(seen[0], r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(self.req()["modal_contacted_at"], seen[0])

    def test_refused_request_restores_the_cu_reservation(self):
        """I4: a run-time refusal undoes the move: Colab caps and supersede behave as before."""
        reserved = self.entry()["units"]
        self.assertEqual(self.request("--colab-units", 0.25)[0], 0)
        self.assertEqual((self.entry()["runner"], self.entry()["units"]), ("modal", 0.25))
        self.set_status("running")
        self.r2.deny = {"PUT"}
        code, out = run("r2-probe", self.job_id, "--root", self.root)
        self.assertEqual(code, 2, out)
        self.assertIn("CU reservation restored", out)
        e = self.entry()
        self.assertEqual((e["units"], e["state"]), (reserved, "reserved"))
        for key in ("runner", "colab_units", "reserved_units", "moved_to_modal_at"):
            self.assertNotIn(key, e)
        self.assertFalse(self.ledger.is_modal_job(self.job_id))
        code, out = run("supersede", self.job_id, "--root", self.root, "--reason", "never ran")
        self.assertEqual(code, 0, out)  # never ran: supersede works again

    def test_colab_units_above_the_reservation_are_refused(self):
        reserved = self.entry()["units"]
        before = self.ledger_bytes()
        code, out = self.request("--colab-units", reserved + 0.01)
        self.assertEqual(code, 2, out)
        self.assertIn("cannot exceed the reservation", out)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertFalse(self.req_path.exists())

    def refuse_unstarted(self, reason="stopped"):
        return modal_requests.refuse_unstarted(self.req_path, self.d, reason)

    def test_workflow_refuses_a_request_whose_run_never_contacted_modal(self):
        """I2: install/mark/probe crash or modal-run dying before contact: refused, row released."""
        reserved = self.entry()["units"]
        self.assertEqual(self.request()[0], 0)
        for status in ("requested", "running"):  # install failed / a later step crashed
            self.set_status(status)
            before = self.ledger_bytes()
            out = self.refuse_unstarted("install=failure")
            self.assertTrue(out["refused"], out)
            self.assertEqual((out["root"], out["ledger"]), (str(self.root), str(self.ledger.path)))
            req = self.req()
            self.assertEqual(req["status"], "refused")
            self.assertIn("install=failure", req["error"])
            self.assertEqual(self.rows(), [])
            self.assertEqual(self.entry()["units"], reserved)
            self.ledger._write(json.loads(before))  # again from the same state, for the next status
        self.set_status("running")
        data = self.req()
        data["modal_contacted_at"] = "2026-11-26T12:00:00+00:00"
        self.req_path.write_text(json.dumps(data))
        before = (self.req_path.read_bytes(), self.ledger_bytes())
        out = self.refuse_unstarted()
        self.assertFalse(out["refused"])
        self.assertIn("contacted", out["why"])
        self.assertEqual((self.req_path.read_bytes(), self.ledger_bytes()), before)
        self.set_status("done")
        self.assertFalse(self.refuse_unstarted()["refused"])

    def test_workflow_entry_point_is_stdlib_only(self):
        """The refusal must work when the dependency install failed (numpy, PIL, modal missing)."""
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        sw = Path(modal_requests.__file__).resolve().parents[1]
        code = ("import builtins, runpy, sys\n"
                "real = builtins.__import__\n"
                "def guard(name, *a, **k):\n"
                "    if name.split('.')[0] in ('numpy', 'PIL', 'modal'):\n"
                "        raise ImportError('blocked ' + name)\n"
                "    return real(name, *a, **k)\n"
                "builtins.__import__ = guard\n"
                "sys.argv = ['x'] + sys.argv[1:]\n"
                "runpy.run_module('eav.modal_requests', run_name='__main__')\n")
        proc = subprocess.run([os.sys.executable, "-c", code, "refuse-unstarted", str(self.req_path),
                               "--workspace", str(self.d), "--reason", "install=failure"],
                              cwd=sw, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["refused"])
        self.assertEqual((self.req()["status"], self.rows()), ("refused", []))
        proc = subprocess.run([os.sys.executable, "-m", "eav.modal_requests", "check", str(self.req_path),
                               "--workspace", str(self.d)], cwd=sw, capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(json.loads(proc.stdout)["status"], "refused")

    def test_an_invalid_request_is_refused_instead_of_blocking_the_queue(self):
        self.assertEqual(self.request()[0], 0)
        good = self.req()
        self.assertEqual(modal_requests.validate(good, self.req_path), [])
        checked = modal_requests.check(self.req_path, self.d)
        self.assertEqual((checked["status"], checked["errors"], checked["root"]),
                         ("requested", [], str(self.root)))
        bad_cases = {
            "job_id": ("../x", "does not match"),
            "title_root": ("titles/selfish-giant", "production/audiovisual"),
            "schema": ("other.v1", "schema"),
            "pending_run_id": ("other#1", "pending_run_id"),
            "colab_units": (-1, "colab_units"),
        }
        for field, (value, words) in bad_cases.items():
            data = dict(good, **{field: value})
            self.assertTrue(any(words in e for e in modal_requests.validate(data, self.req_path)), field)
        other = self.req_path.with_name("Not-A-Job.json")
        self.assertTrue(any("file name" in e for e in modal_requests.validate(good, other)))
        # title_root outside production/audiovisual: refused, the ledger cannot be located (untouched)
        self.req_path.write_text(json.dumps(dict(good, title_root="titles/x")))
        before = self.ledger_bytes()
        out = self.refuse_unstarted()
        self.assertTrue(out["refused"])
        self.assertIsNone(out["ledger"])
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(self.req()["status"], "refused")
        self.assertIn("invalid request", self.req()["error"])
        self.assertIn("modal-settle", self.req()["error"])
        # schema wrong but the ledger located: refused, its row released
        self.req_path.write_text(json.dumps(dict(good, schema="other.v1")))
        out = self.refuse_unstarted()
        self.assertTrue(out["refused"])
        self.assertEqual(self.rows(), [])

    def test_abandon_a_running_request_that_never_reached_modal(self):
        reserved = self.entry()["units"]
        self.assertEqual(self.request()[0], 0)
        code, out = run("modal-request", self.job_id, "--root", self.root, "--abandon", "--reason", "x")
        self.assertEqual(code, 2, out)  # requested, not running
        self.assertIn("only a running request", out)
        self.set_status("running")
        code, out = run("modal-request", self.job_id, "--root", self.root, "--abandon")
        self.assertEqual(code, 2, out)
        self.assertIn("--abandon needs --reason", out)
        code, out = run("modal-request", self.job_id, "--root", self.root, "--reason", "x",
                        "--colab-units", 0)
        self.assertEqual(code, 2, out)
        data = self.req()
        data["modal_contacted_at"] = "2026-11-26T12:00:00+00:00"
        self.req_path.write_text(json.dumps(data))
        before = (self.req_path.read_bytes(), self.ledger_bytes())
        code, out = run("modal-request", self.job_id, "--root", self.root, "--abandon", "--reason", "x")
        self.assertEqual(code, 2, out)
        self.assertIn("contacted Modal", out)
        self.assertEqual((self.req_path.read_bytes(), self.ledger_bytes()), before)
        del data["modal_contacted_at"]
        self.req_path.write_text(json.dumps(data))
        code, out = run("modal-request", self.job_id, "--root", self.root, "--abandon", "--reason",
                        "runner cancelled before the Modal step")
        self.assertEqual(code, 0, out)
        req = self.req()
        self.assertEqual(req["status"], "refused")
        self.assertIn("abandoned: runner cancelled", req["error"])
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.entry()["units"], reserved)
        code, out = self.request()
        self.assertEqual(code, 0, out)  # a new request may follow, with a fresh run_id
        self.assertEqual(self.req()["pending_run_id"], f"{self.job_id}#2")

    # ------------------------------------------------------------ F1: per-run R2 prefix (B5 M4, M1)
    def test_each_request_has_its_own_r2_prefix_and_fetch_ignores_a_stale_copy(self):
        code, out = self.run_and_upload(fake_runner(0.3, "failed"))
        self.assertEqual(self.req()["r2_prefix"], f"gpu-jobs/{self.slug}/{self.job_id}/run-1/")
        old_copy = f"gpu-jobs/{self.slug}/{self.job_id}/run-1/_request-result.json"
        self.assertIn(old_copy, self.r2.store)
        self.assertEqual(self.request()[0], 0)  # request again after the failure
        req = self.req()
        self.assertEqual((req["pending_run_id"], req["r2_prefix"]),
                         (f"{self.job_id}#2", f"gpu-jobs/{self.slug}/{self.job_id}/run-2/"))
        # a stale copy of run 1 placed under run 2's prefix (or found there) is not this request
        self.r2.store[req["r2_prefix"] + "_request-result.json"] = self.r2.store[old_copy]
        code, out = self.fetch()
        self.assertEqual(code, 2, out)
        self.assertIn("has not finished", out)
        del self.r2.store[req["r2_prefix"] + "_request-result.json"]
        self.set_status("running")
        dl = self.d / "runner-temp-2"
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.2)):
            self.assertEqual(run("modal-run", self.job_id, "--root", self.root, "--request",
                                 "--download", dl)[0], 0)
        folder = dl / "job"
        (folder / "only.wav").write_bytes(b"new")
        self.assertEqual(run("r2-upload", self.job_id, "--root", self.root, "--from", folder)[0], 0)
        code, out = self.fetch()  # run 1's other files under run-1/ never get in the way
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / ".downloads" / self.job_id).iterdir()),
                         ["only.wav"])

    # ------------------------------------------------------------ M1: deferred minors and live findings
    def test_a_failed_upload_after_a_finished_run_is_recovered_by_requesting_again(self):
        """M1 item 4 (live, 26 Nov: R2 HTTP 502): the Modal run finished, the upload failed after
        its retries; a re-request resumes from the volume, generates nothing new and uploads under
        a new run prefix; fetch and import then succeed."""
        from tests._narration_fakes import FakeModel

        class R2Down(FakeR2):
            down = True

            def open(self, req, timeout=None):
                if self.down and req.get_method() == "PUT":
                    raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)
                return super().open(req, timeout)
        self.r2 = R2Down()
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        fm, patched = self.modal_patch()
        FakeModel.calls = []
        with fakes(), patched:
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request",
                            "--download", self.d / "dl1")
        self.assertEqual(code, 0, out)
        generated = sum(len(c["input_ids"]) for c in FakeModel.calls)
        self.assertGreater(generated, 0)
        with mock.patch.object(modal_requests, "RETRY_DELAYS_S", (0, 0)):
            code, out = run("r2-upload", self.job_id, "--root", self.root, "--from",
                            self.d / "dl1" / self.job_id)
        self.assertEqual(code, 2, out)
        req = self.req()
        self.assertEqual(req["status"], "failed")
        self.assertIn("HTTP 502", req["error"])
        self.assertEqual(self.rows()[0][0], "ok")  # the Modal run itself finished
        self.assertEqual(self.r2.store, {})
        self.r2.down = False
        code, out = self.request()  # a failed request is requested again (never refused as done)
        self.assertEqual(code, 0, out)
        req = self.req()
        self.assertEqual((req["pending_run_id"], req["r2_prefix"]),
                         (f"{self.job_id}#2", f"gpu-jobs/{self.slug}/{self.job_id}/run-2/"))
        self.set_status("running")
        FakeModel.calls = []
        fm, patched = self.modal_patch()  # the same volume folder: the first run's outputs are there
        with fakes(), patched:
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request",
                            "--download", self.d / "dl2")
        self.assertEqual(code, 0, out)
        self.assertEqual(FakeModel.calls, [])  # resumed: every unit was already done
        manifest = json.loads((self.d / "dl2" / self.job_id / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "COMPLETE")
        code, out = run("r2-upload", self.job_id, "--root", self.root, "--from",
                        self.d / "dl2" / self.job_id)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.r2.store)
        self.assertTrue(all(k.startswith(req["r2_prefix"]) for k in self.r2.store))
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        code, out = run("import", self.job_id, "--root", self.root, "--from",
                        self.root / ".downloads" / self.job_id)
        self.assertEqual(code, 0, out)
        self.assertEqual([s_ for s_, _ in self.rows()], ["ok", "ok"])

    def test_a_done_request_is_fetched_and_imported_never_requested_again(self):
        """Final review M3: a finished run is not paid for twice."""
        self.assertEqual(self.run_and_upload()[0], 0)
        self.assertEqual(self.req()["status"], "done")
        before = (self.req_path.read_bytes(), self.ledger_bytes())
        code, out = self.request()
        self.assertEqual(code, 2, out)
        self.assertIn("already finished on Modal", out)
        self.assertIn(f"modal-fetch {self.job_id}", out)
        with mock.patch.object(modal_run, "run_modal", side_effect=AssertionError("contacted")):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual(code, 2, out)
        self.assertEqual((self.req_path.read_bytes(), self.ledger_bytes()), before)

    def test_fetch_of_a_finished_request_with_no_uploaded_files(self):
        """M1 item 3 / H1 Minor 1: the "no uploaded files" guard, with its own fixture: a failed
        request that lists no files is never fetched; it says to close or request again."""
        self.assertEqual(self.request()[0], 0)
        data = self.req()
        data.update(status="failed", files=[], error="RuntimeError: boom; upload: no job folder")
        self.req_path.write_text(json.dumps(data))
        self.r2.store[data["r2_prefix"] + "stray.wav"] = b"x"  # never reached: the guard comes first
        calls = len(self.r2.calls)
        code, out = self.fetch()
        self.assertEqual(code, 2, out)
        self.assertIn(f"request {self.job_id} is failed with no uploaded files (RuntimeError: boom", out)
        self.assertIn(f"close {self.job_id}", out)
        self.assertIn("or request it again", out)
        self.assertEqual(len(self.r2.calls), calls)
        self.assertFalse((self.root / ".downloads" / self.job_id).exists())

    def test_abandon_says_what_is_known_and_a_billed_run_can_be_recorded_after_all(self):
        """M1 item 2: the message never claims Modal was never contacted for the job; it names the
        released row and the earlier rows kept. If the abandoned run shows up billed, modal-settle
        --run writes its row again."""
        self.assertEqual(self.run_and_upload(fake_runner(0.3, "failed"))[0], 0)  # run #1: settled
        self.assertEqual(run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.25)[0], 0)
        self.assertEqual(self.request()[0], 0)  # request #2
        self.set_status("running")
        code, out = run("modal-request", self.job_id, "--root", self.root, "--abandon", "--reason",
                        "runner cancelled before the Modal step")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Modal was never contacted", out)
        self.assertIn("this request's run recorded no Modal contact", out)
        self.assertIn(f"its pending row {self.job_id}#2 was released", out)
        self.assertIn("the job stays moved to Modal (it has earlier Modal runs)", out)
        self.assertIn(f"{self.job_id}#1 failed billed 0.2500 USD", out)
        self.assertIn("check the Modal dashboard", out)
        self.assertEqual(self.rows(), [("failed", 0.25)])
        code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.12,
                        "--run", f"{self.job_id}#2")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.rows(), [("failed", 0.25), ("settled", 0.12)])

    def test_a_local_run_of_a_requested_job_names_the_request_before_the_token(self):
        """H1 Minor 3: the open request is the reason, not a missing HF_TOKEN."""
        self.assertEqual(self.request()[0], 0)
        env = {k: v for k, v in os.environ.items() if k != "HF_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual(code, 2, out)
        self.assertIn("has an open Modal request", out)
        self.assertNotIn("HF_TOKEN", out)

    def test_a_request_file_that_cannot_be_written_leaves_no_pending_row(self):
        """B5 M6: the row is released and the move undone when the request file write fails."""
        reserved = self.entry()["units"]
        with mock.patch.object(modal_requests, "write_request", side_effect=OSError("disk full")):
            code, out = self.request()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.entry()["units"], reserved)
        self.assertNotIn("runner", self.entry())
        self.assertFalse(self.req_path.exists())

    def test_a_run_that_fails_before_contacting_modal_releases_its_row(self):
        """modal-run fails after its pending row but before Modal is contacted: nothing was spent,
        the request is refused (row released) at once, not left for the refusal step or settle."""
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")

        def broken(*a, on_contact=None, **k):
            raise ValueError("inputs.zip does not match its build manifest (sha256)")
        with mock.patch.object(modal_run, "run_modal", broken):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        self.assertEqual(code, 2, out)
        self.assertIn("Modal was not contacted: the pending row", out)
        self.assertEqual((self.req()["status"], self.rows()), ("refused", []))
        self.assertNotIn("runner", self.entry())

    def test_a_run_that_may_end_next_month_is_checked_against_both_months(self):
        """B2 M3: started 30 Nov 23:30 UTC, a run may still be going in December: December's cap
        is checked too, and a run that ended there is recorded there."""
        from datetime import datetime, timezone
        late = datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc)
        with mock.patch.object(cli, "_MONTH", None), mock.patch.object(cli, "_NOW", late):
            self.ledger.record_modal_spend("2026-12", "other-job", 29.9, 1.0, "ok", "t")
            with self.rate(0.6):
                code, out = self.request()
            self.assertEqual(code, 3, out)
            self.assertIn("2026-12", out)
            self.assertFalse(self.req_path.exists())
            self.ledger.bill_modal_run("other-job", 1.0, "other-job#1")
            with self.rate(0.6):
                self.assertEqual(self.request()[0], 0)
            self.set_status("running")

            def ends_in_december(notebook, inputs_zip, download_dir, **kw):
                kw["on_contact"]()
                cli._NOW = datetime(2026, 12, 1, 0, 20, tzinfo=timezone.utc)
                return fake_runner(0.2)(notebook, inputs_zip, download_dir)
            with self.rate(0.6), mock.patch.object(modal_run, "run_modal", ends_in_december):
                code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
            self.assertEqual(code, 0, out)
        self.assertEqual([r["status"] for r in self.ledger.modal_rows(month="2026-12",
                                                                     job_id=self.job_id)], ["ok"])
        self.assertEqual(self.ledger.modal_rows(month="2026-11", job_id=self.job_id), [])

    def test_a_refusal_that_restores_a_reservation_over_a_cu_cap_says_hold(self):
        """F1 concern 3: the restored CU were taken meanwhile; the request's error says so."""
        self.assertEqual(self.request()[0], 0)
        month_total = self.ledger.spent(None, self.MONTH)
        need = budget.MONTH_CAP - month_total  # other titles take the released CU (60 each at most)
        self.ledger.reserve("another-title", self.MONTH, min(need, 60.0), "other-job")
        if need > 60.0:
            self.ledger.reserve("third-title", self.MONTH, need - 60.0, "third-job")
        self.set_status("running")
        self.r2.deny = {"PUT"}
        code, out = run("r2-probe", self.job_id, "--root", self.root)
        self.assertEqual(code, 2, out)
        err = self.req()["error"]
        self.assertIn(f"month cap", err)
        self.assertIn("hold this job for the owner; do not run it in Colab", err)

    def test_fetch_reports_an_r2_error_instead_of_saying_not_finished(self):
        """B5 re-review: only a 404 means there is no R2 copy; an auth error is reported."""
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        code, out = self.fetch()
        self.assertEqual(code, 2, out)
        self.assertIn("has not finished", out)  # 404: no copy yet
        self.r2.deny = {"GET"}
        code, out = self.fetch()
        self.assertEqual(code, 2, out)
        self.assertIn("is unreadable", out)
        self.assertIn("HTTP 403", out)

    def test_an_invalid_file_named_for_another_job_never_touches_this_jobs_ledger(self):
        """F1 re-review: a request file whose name differs from its job_id is refused without
        releasing that job_id's row or undoing its move."""
        self.assertEqual(self.request()[0], 0)
        other = self.req_path.with_name("narration-other.json")
        other.write_text(self.req_path.read_text())
        before = self.ledger_bytes()
        out = modal_requests.refuse_unstarted(other, self.d, "stopped")
        self.assertTrue(out["refused"])
        self.assertIn("differs from the file name", out["why"])
        self.assertIn("the ledger was not touched", out["why"])
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(json.loads(other.read_text())["status"], "refused")
        self.assertEqual(self.req()["status"], "requested")

    def test_the_push_back_replay_is_stdlib_only(self):
        """F1 concern 4: the publish script's conflict replay works when the install failed."""
        self.assertEqual(self.run_and_upload()[0], 0)
        saved = self.d / "saved"
        saved.mkdir()
        (saved / "request.json").write_bytes(self.req_path.read_bytes())
        (saved / "ledger.json").write_bytes(self.ledger_bytes())
        done = self.req_path.read_bytes()
        self.set_status("running")  # the fresh head still has the request running
        sw = Path(modal_requests.__file__).resolve().parents[1]
        code = ("import builtins, runpy, sys\n"
                "real = builtins.__import__\n"
                "def guard(name, *a, **k):\n"
                "    if name.split('.')[0] in ('numpy', 'PIL', 'modal'):\n"
                "        raise ImportError('blocked ' + name)\n"
                "    return real(name, *a, **k)\n"
                "builtins.__import__ = guard\n"
                "sys.argv = ['x'] + sys.argv[1:]\n"
                "runpy.run_module('eav.modal_requests', run_name='__main__')\n")
        proc = subprocess.run([os.sys.executable, "-S", "-c", code, "replay", self.job_id, "--root",
                               str(self.root), "--saved", str(saved)],
                              cwd=sw, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Replayed request", proc.stdout)
        self.assertEqual(self.req_path.read_bytes(), done)

    def test_next_for_a_job_on_modal_says_request_again_not_modal_run(self):
        """Final review M2: this session cannot run modal-run; resume means modal-request."""
        self.assertEqual(self.run_and_upload(fake_runner(0.3, "hard_stopped"))[0], 0)
        nxt = cli.next_action(self.root)
        self.assertIn(f"modal-request {self.job_id}", nxt)
        self.assertIn(f"modal-fetch {self.job_id}", nxt)
        self.assertNotIn(f"rerun python3 -m eav.cli modal-run", nxt.lower())
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.1, "failed")):
            self.assertEqual(self.request()[0], 0)
            self.set_status("running")
            code, out = run("modal-run", self.job_id, "--root", self.root, "--request")
        line = json.loads(next(l for l in out.splitlines() if l.startswith("{")))
        self.assertIn(f"modal-request {self.job_id}", line["next"])

    # ------------------------------------------------------------ F1: the real ledger and requests
    def test_the_existing_production_ledger_and_requests_load(self):
        """A copy of a frozen snapshot of production/audiovisual (tests/fixtures/modal-state-20261126:
        ledger, request files, the title's record.json), read only: c1of2 #1 refused by hand (row
        settled at 0), #2 failed (no payment method); the live files change with every real run."""
        src = Path(__file__).resolve().parent / "fixtures" / "modal-state-20261126"
        work = self.d / "copy"
        (work / ".git").mkdir(parents=True)
        dst = work / "production" / "audiovisual"
        shutil.copytree(src / "modal-requests", dst / "modal-requests")
        shutil.copy2(src / "allowance-ledger.json", dst / "allowance-ledger.json")
        ledger = budget.Ledger(dst / "allowance-ledger.json")
        for path in sorted((dst / "modal-requests").glob("*.json")):
            req = modal_requests.read_request(path)
            self.assertEqual(modal_requests.validate(req, path), [], path.name)
            slug = req["title_root"].rsplit("/", 1)[1]
            (dst / slug).mkdir(exist_ok=True)
            shutil.copy2(src / slug / "record.json", dst / slug / "record.json")
            root, ledger_path = modal_requests.locate(req, work)
            self.assertEqual(ledger_path, ledger.path.resolve())
            job = req["job_id"]
            rows = ledger.modal_rows(job_id=job)
            ids = {r["run_id"] for r in rows}
            self.assertIn(req["pending_run_id"], ids)
            if req["status"] not in modal_requests.OPEN:  # finished or refused: the workflow leaves it
                self.assertFalse(modal_requests.refuse_unstarted(path, work, "x")["refused"])
            # I3: the next run_id is past every one issued, released or not
            nxt = max(budget.Ledger.run_number(i) for i in ids) + 1
            self.assertEqual(modal_requests.r2_prefix(slug, job, f"{job}#{nxt}"),
                             f"gpu-jobs/{slug}/{job}/run-{nxt}/")
            if any(r["status"] != "pending" for r in rows):
                self.assertFalse(ledger.undo_move_to_modal(job))  # it reached Modal: stays moved
            self.assertEqual(ledger.record_modal_spend("2026-11", job, 0.0, 0.0, "pending", "t"),
                             f"{job}#{nxt}")
        # the known state: c1of2 #1 settled 0 (refused by hand), #2 and #3 failed with the wall-clock
        # estimate (the next run is #4); c2of2 #1 settled 0.0117, its request failed
        c2 = "narration-film-01-r3-c2of2"
        row2 = ledger.modal_rows(job_id=c2)[0]  # [1] is the probe row the loop above added
        self.assertEqual((row2["status"], row2["usd"]), ("settled", 0.0117))
        self.assertEqual(modal_requests.read_request(dst / "modal-requests" / f"{c2}.json")["status"], "failed")
        job = "narration-film-01-r3-c1of2"
        rows = {r["run_id"]: r for r in ledger.modal_rows(job_id=job)}
        self.assertEqual(rows[f"{job}#1"]["status"], "settled")
        self.assertEqual(rows[f"{job}#2"]["status"], "failed")
        self.assertEqual([r["run_id"] for r in ledger.unbilled_modal_runs(job)], [f"{job}#2", f"{job}#3"])
        ledger.release_pending_modal(f"{job}#4")  # the probe row above
        root = dst / "bicharak"
        code, out = run("modal-settle", job, "--root", root, "--usd", 0, "--run", f"{job}#2")
        self.assertEqual(code, 0, out)  # reconcile #2 from the bill (Modal refused before any GPU)
        row = next(r for r in ledger.modal_rows(job_id=job) if r["run_id"] == f"{job}#2")
        self.assertEqual((row["usd"], row["billed"], row["status"]), (0, True, "failed"))
        self.assertAlmostEqual(row["estimated_usd"], 0.02270221720785)
        code, out = run("modal-fetch", job, "--root", root)
        self.assertEqual(code, 2, out)  # failed, its files are not in the (fake, empty) R2: nothing written
        self.assertIn("missing in R2", out)
        code, out = run("modal-request", job, "--root", root, "--abandon", "--reason", "x")
        self.assertEqual(code, 2, out)  # failed, not running
        self.assertEqual(budget.Ledger(src / "allowance-ledger.json").modal_rows(job_id=job)[1]["status"],
                         "failed")  # the real ledger was only read

    # ------------------------------------------------------------ M1 review, task quality minors
    def take_released_cu(self):
        """Other titles reserve the CU this job released when it moved to Modal."""
        need = budget.MONTH_CAP - self.ledger.spent(None, self.MONTH)
        self.ledger.reserve("another-title", self.MONTH, min(need, 60.0), "other-job")
        if need > 60.0:
            self.ledger.reserve("third-title", self.MONTH, need - 60.0, "third-job")

    def test_a_local_run_failing_before_modal_says_hold_when_the_restore_is_over_a_cap(self):
        """Minor 1: _not_started restores the reservation; the hold guidance is printed."""
        def broken(*a, on_contact=None, **k):
            self.take_released_cu()
            raise ValueError("no Modal client")
        with mock.patch.object(modal_run, "run_modal", broken):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual(code, 2, out)
        self.assertIn("Modal was not contacted: the pending row", out)
        self.assertIn("month cap", out)
        self.assertIn("hold this job for the owner; do not run it in Colab", out)
        self.assertEqual(self.rows(), [])
        self.assertNotIn("runner", self.entry())

    def test_a_failed_request_write_says_hold_when_the_restore_is_over_a_cap(self):
        """Minor 1: the failed request-file write restores the reservation; hold is printed."""
        def full(*a, **k):
            self.take_released_cu()
            raise OSError("disk full")
        with mock.patch.object(modal_requests, "write_request", side_effect=full):
            code, out = self.request()
        self.assertEqual(code, 2, out)
        self.assertIn("The request file was not written", out)
        self.assertIn("hold this job for the owner; do not run it in Colab", out)
        self.assertEqual(self.rows(), [])
        self.assertFalse(self.req_path.exists())

    def test_a_released_row_billed_after_all_counts_in_the_month_of_its_request(self):
        """Minor 2: settled in December, the abandoned November run counts in its own month."""
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        code, out = run("modal-request", self.job_id, "--root", self.root, "--abandon", "--reason",
                        "runner cancelled before the Modal step")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ledger.released_month(self.job_id, f"{self.job_id}#1"), self.MONTH)
        with mock.patch.object(cli, "_MONTH", "2026-12"):
            code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.12,
                            "--run", f"{self.job_id}#1")
        self.assertEqual(code, 0, out)
        self.assertIn(f"in {self.MONTH}", out)
        self.assertEqual(self.ledger.modal_month_usd(self.MONTH), 0.12)
        self.assertEqual(self.ledger.modal_rows(month="2026-12"), [])

    def test_a_released_row_without_a_recorded_month_uses_the_requested_at_month(self):
        """Minor 2: an older ledger has no released_runs; the request's requested_at decides."""
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        self.assertEqual(run("modal-request", self.job_id, "--root", self.root, "--abandon",
                             "--reason", "x")[0], 0)
        raw = json.loads(self.ledger_bytes())
        for e in raw:
            e.pop("released_runs", None)
        self.ledger._write(raw)
        data = self.req()
        data["requested_at"] = "2026-10-31T23:50:00+00:00"
        self.req_path.write_text(json.dumps(data))
        with mock.patch.object(cli, "_MONTH", "2026-12"):
            code, out = run("modal-settle", self.job_id, "--root", self.root, "--usd", 0.2,
                            "--run", f"{self.job_id}#1")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ledger.modal_month_usd("2026-10"), 0.2)
        self.assertEqual(self.ledger.modal_rows(month="2026-12"), [])

    def test_retire_refuses_a_finished_run_unless_the_owner_discards_it(self):
        """Minor 3: the Modal run finished (ok row), only the upload failed: retire says to
        re-request or import; --discard-finished retires it and states the loss."""
        self.assertEqual(self.request()[0], 0)
        self.set_status("running")
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.3)):
            self.assertEqual(run("modal-run", self.job_id, "--root", self.root, "--request",
                                 "--download", self.d / "dl")[0], 0)
        self.set_status("failed")  # the upload failed
        before = ((self.root / "record.json").read_bytes(), self.ledger_bytes())
        code, out = run("retire", self.job_id, "--root", self.root, "--reason", "rebuilt")
        self.assertEqual(code, 2, out)
        self.assertIn("finished on Modal (its newest Modal row is ok)", out)
        self.assertIn(f"modal-request {self.job_id}", out)
        self.assertIn(f"import {self.job_id}", out)
        self.assertIn("--discard-finished", out)
        self.assertEqual(((self.root / "record.json").read_bytes(), self.ledger_bytes()), before)
        code, out = run("retire", self.job_id, "--root", self.root, "--reason", "rebuilt",
                        "--discard-finished")
        self.assertEqual(code, 0, out)
        self.assertIn(f"Discarded finished Modal run(s) (--discard-finished): {self.job_id} "
                      "(0.3000 USD paid)", out)
        self.assertIn("given up, never imported", out)
        self.assertNotIn("Closed first (failed on Modal", out)
        self.assertEqual((self.entry()["state"], self.entry()["usd"]), ("settled", 0.3))
        (ev,) = [e for e in cli.Record.load(self.root).data["events"] if e["result"] == "retired"]
        self.assertEqual(ev["detail"]["discarded_finished"], [self.job_id])

    def test_a_finished_local_run_is_never_requested_again_after_a_failed_request(self):
        """Minor 4: request #1 failed; a local modal-run #2 finished ok; the failed request file
        no longer hides it, so a third run is never paid for."""
        self.run_and_upload(fake_runner(0.3, "failed"))
        self.assertEqual(self.req()["status"], "failed")
        with mock.patch.object(modal_run, "run_modal", fake_runner(0.2)):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0,
                            "--download", self.d / "local")
        self.assertEqual(code, 0, out)
        rows = self.ledger.modal_rows(job_id=self.job_id)
        self.assertEqual([(r["status"], bool(r.get("local"))) for r in rows],
                         [("failed", False), ("ok", True)])
        before = (self.req_path.read_bytes(), self.ledger_bytes())
        code, out = self.request()
        self.assertEqual(code, 2, out)
        self.assertIn("already finished on Modal", out)
        self.assertIn(f"import {self.job_id} --root {self.root} --from <the downloaded folder>", out)
        with mock.patch.object(modal_run, "run_modal", side_effect=AssertionError("contacted")):
            code, out = run("modal-run", self.job_id, "--root", self.root, "--colab-units", 0)
        self.assertEqual(code, 2, out)
        self.assertEqual((self.req_path.read_bytes(), self.ledger_bytes()), before)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_secrets_are_only_the_four_names_and_never_echoed(self):
        self.assertEqual(set(re.findall(r"secrets\.([A-Za-z0-9_]+)", self.text)), SECRETS)
        for name in SECRETS:
            self.assertNotRegex(self.text, r"echo[^\n]*\$\{?" + name)
            self.assertNotIn(f"set -x", self.text)
        self.assertNotRegex(self.text, r"echo[^\n]*secrets\.")

    def test_trigger_paths_exclude_the_readme(self):
        readme = REPO / "production" / "audiovisual" / "modal-requests" / "README.md"
        self.assertTrue(readme.is_file())
        self.assertIn("paths: ['production/audiovisual/modal-requests/*.json', '.github/workflows/modal-jobs.yml']", self.text)
        self.assertIn("set -euo pipefail", self.text)
        self.assertIn('modal-run "$JOB_ID" --root "$ROOT" --request', self.text)
        self.assertIn("r2-probe", self.text)
        self.assertIn("r2-upload", self.text)

    def test_actions_pinned_to_commits_and_modal_pinned(self):
        uses = re.findall(r"uses:\s*(\S+)", self.text)
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r"^[\w-]+/[\w-]+@[0-9a-f]{40}$")
        self.assertIn("pip install modal==1.6.4", self.text)

    def test_publish_script_aborts_a_conflicting_rebase_and_falls_back(self):
        script = (REPO / ".github" / "scripts" / "modal-publish.sh").read_text(encoding="utf-8")
        self.assertIn("git rebase --abort", script)
        self.assertIn("modal-replay", script)
        self.assertIn("modal-results/$job_id", script)
        self.assertIn("set -euo pipefail", script)
        self.assertNotIn("--force", script)
        self.assertIn("GIT_CONFIG_VALUE_0", script)  # the token reaches git through its env only
        self.assertNotIn("echo \"$GH_TOKEN", script)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_publish_script_pushes_or_falls_back_under_set_e(self):
        """B5: a failing replay under `set -e` still reaches the fallback push, and the fallback
        branch gets a run suffix when it already exists. A local bare repository stands in for
        GitHub; nothing leaves the machine."""
        script = REPO / ".github" / "scripts" / "modal-publish.sh"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_CONFIG_NOSYSTEM="1", BRANCH="b", RUNNER_TEMP=str(d / "tmp"),
                   MODAL_PUBLISH_BACKOFF_S="0", GITHUB_RUN_ID="777")
        env.pop("GH_TOKEN", None)
        (d / "tmp").mkdir()

        def git(*args, cwd=None):
            return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                                  text=True).stdout.strip()

        git("init", "-q", "--bare", "-b", "b", str(d / "origin.git"))
        git("clone", "-q", str(d / "origin.git"), str(d / "seed"))
        git("checkout", "-q", "-b", "b", cwd=d / "seed")
        (d / "seed" / "req.json").write_text('{"status": "requested"}\n')
        (d / "seed" / "ledger.json").write_text("[]\n")
        git("add", ".", cwd=d / "seed")
        git("commit", "-q", "-m", "seed", cwd=d / "seed")
        git("push", "-q", "origin", "b", cwd=d / "seed")

        def publish(ws, status, ledger="ledger.json"):
            (ws / "req.json").write_text('{"status": "%s"}\n' % status)
            return subprocess.run(["bash", str(script), f"m {status}", "job-1", str(ws),
                                   str(ws / ledger) if ledger else "", "req.json"],
                                  cwd=ws, env=dict(env, GITHUB_WORKSPACE=str(ws)),
                                  capture_output=True, text=True, timeout=120)

        ws = d / "ws"
        git("clone", "-q", "-b", "b", str(d / "origin.git"), str(ws))
        proc = publish(ws, "running")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("running", git("show", "b:req.json", cwd=d / "origin.git"))
        proc = publish(ws, "refused", ledger="")  # an invalid request: the request file alone
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("refused", git("show", "b:req.json", cwd=d / "origin.git"))
        # the branch moves on with a conflicting change; the replay cannot run here (no eav in
        # this workspace), so every attempt fails and the fallback branch gets this run's commit
        git("pull", "-q", "origin", "b", cwd=d / "seed")
        (d / "seed" / "req.json").write_text('{"status": "other"}\n')
        git("commit", "-q", "-am", "conflict", cwd=d / "seed")
        git("push", "-q", "origin", "b", cwd=d / "seed")
        proc = publish(ws, "done")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("the result is on modal-results/job-1", proc.stdout)
        self.assertIn("done", git("show", "modal-results/job-1:req.json", cwd=d / "origin.git"))
        self.assertIn("other", git("show", "b:req.json", cwd=d / "origin.git"))  # never forced
        ws2 = d / "ws2"  # a second run, cloned before the branch moves on again
        git("clone", "-q", "-b", "b", str(d / "origin.git"), str(ws2))
        (d / "seed" / "req.json").write_text('{"status": "other again"}\n')
        git("commit", "-q", "-am", "conflict again", cwd=d / "seed")
        git("push", "-q", "origin", "b", cwd=d / "seed")
        proc = publish(ws2, "failed")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("the result is on modal-results/job-1-run-777", proc.stdout)
        self.assertIn("failed", git("show", "modal-results/job-1-run-777:req.json", cwd=d / "origin.git"))

    def test_hf_token_only_in_the_run_on_modal_step(self):
        self.assertEqual(self.text.count("secrets.HF_TOKEN"), 1)
        start = self.text.index("      - name: Run on Modal\n")
        end = self.text.index("      - name: Refuse the request if Modal was never contacted")
        self.assertIn("HF_TOKEN: ${{ secrets.HF_TOKEN }}", self.text[start:end])
        self.assertEqual(self.text.count("HF_TOKEN: "), 1)  # no other step sets it

    def test_checkouts_keep_no_token_and_only_push_steps_get_it(self):
        self.assertEqual(self.text.count("persist-credentials: false"), 2)
        self.assertEqual(self.text.count("actions/checkout@"), 2)
        self.assertEqual(self.text.count("GH_TOKEN: ${{ github.token }}"), 3)
        self.assertRegex(self.text, r"spend limit[^\n]*\n#[^\n]*30 USD a month or less")
        self.assertIn("refuse-unstarted", self.text)
        self.assertIn("timeout-minutes: 300  # per matrix job, i.e. per request", self.text)

    @unittest.skipUnless(__import__("importlib").util.find_spec("yaml"), "PyYAML not installed")
    def test_workflow_parses_and_each_step_holds_only_its_secrets(self):
        import yaml
        wf = yaml.safe_load(self.text)
        on = wf.get("on", wf.get(True))  # YAML 1.1 reads a bare `on` as True
        self.assertEqual(on["push"]["branches"], [modal_requests.BRANCH])
        self.assertEqual(on["push"]["paths"], ["production/audiovisual/modal-requests/*.json",
                                               ".github/workflows/modal-jobs.yml"])
        self.assertEqual(wf["permissions"], {"contents": "read"})  # only the run job writes
        self.assertEqual(wf["jobs"]["run"]["permissions"], {"contents": "write"})
        self.assertNotIn("permissions", wf["jobs"]["list"])
        self.assertEqual(wf["concurrency"], {"group": "modal-jobs", "cancel-in-progress": False})
        job = wf["jobs"]["run"]
        self.assertEqual((job["runs-on"], job["timeout-minutes"]), ("ubuntu-latest", 300))
        self.assertEqual(job["strategy"]["max-parallel"], 1)
        self.assertNotIn("secrets.", json.dumps(wf["jobs"]["list"]))
        self.assertNotIn("secrets.", json.dumps(job.get("env", {})))
        steps = job["steps"]
        self.assertTrue(any(s.get("with", {}).get("python-version") == "3.12" for s in steps))
        secrets_by_step = {s.get("name", s.get("uses", "")): {
            k for k, v in (s.get("env") or {}).items() if "secrets." in str(v)} for s in steps}
        self.assertEqual(secrets_by_step["Install the Modal client (no secrets in this step)"], set())
        self.assertEqual(secrets_by_step["Probe R2 before the paid run"], {"CLOUDFLARE_R2_TOKEN"})
        self.assertEqual(secrets_by_step["Run on Modal"], {"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "HF_TOKEN"})
        self.assertEqual(secrets_by_step["Upload the outputs to R2"], {"CLOUDFLARE_R2_TOKEN"})
        self.assertEqual(secrets_by_step["Push the result back (only the push token)"], set())
        self.assertEqual(sum(len(v) for v in secrets_by_step.values()), 5)
        token_steps = {s.get("name") for s in steps if "GH_TOKEN" in (s.get("env") or {})}
        self.assertEqual(token_steps, {"Mark the request running (only the push token)",
                                       "Refuse the request if Modal was never contacted (only the push token)",
                                       "Push the result back (only the push token)"})
        for s in steps:  # where the push token is, python runs without site-packages (-S)
            if s.get("name") in token_steps:
                calls = re.findall(r"python3(?: -[A-Za-z])* ", s["run"])
                self.assertTrue(calls, s["name"])
                self.assertTrue(all(c.startswith("python3 -S") for c in calls), (s["name"], calls))
        for s in steps:
            if "uses" in s and s["uses"].startswith("actions/checkout@"):
                self.assertIs(s["with"]["persist-credentials"], False)
        self.assertIs(wf["jobs"]["list"]["steps"][0]["with"]["persist-credentials"], False)
        by_name = {s.get("name"): s for s in steps}
        refuse = by_name["Refuse the request if Modal was never contacted (only the push token)"]
        self.assertIn("always()", refuse["if"])
        self.assertIn("refuse-unstarted", refuse["run"])
        upload = by_name["Upload the outputs to R2"]
        self.assertIn("steps.unstarted.outputs.refused != 'true'", upload["if"])
        for s in steps:
            for k, v in (s.get("env") or {}).items():
                if "secrets." in str(v):
                    self.assertEqual(v, "${{ secrets.%s }}" % k)
        names = [s.get("name") for s in steps]
        self.assertLess(names.index("Probe R2 before the paid run"), names.index("Run on Modal"))
        self.assertLess(names.index("Run on Modal"), names.index(refuse["name"]))
        self.assertLess(names.index(refuse["name"]), names.index("Upload the outputs to R2"))


if __name__ == "__main__":
    unittest.main()


class R2RetryTests(unittest.TestCase):
    def _opener(self, codes):
        import urllib.error
        calls = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"ok"

        class Opener:
            def open(self, req, timeout=None):
                calls.append(req.get_method())
                code = codes.pop(0) if codes else None
                if code:
                    raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
                return Resp()
        return Opener(), calls

    def test_transient_502_is_retried_then_succeeds(self):
        from eav import modal_requests as mr
        opener, calls = self._opener([502, 503])
        slept = []
        self.assertEqual(mr._call(opener, "PUT", "https://x/objects/k", b"b", _sleep=slept.append), b"ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(slept, [2, 5])

    def test_permanent_403_is_not_retried(self):
        from eav import modal_requests as mr
        opener, calls = self._opener([403])
        with self.assertRaises(mr.R2Error):
            mr._call(opener, "PUT", "https://x/objects/k", b"b", _sleep=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_the_last_retry(self):
        from eav import modal_requests as mr
        opener, calls = self._opener([502] * 9)
        with self.assertRaises(mr.R2Error):
            mr._call(opener, "GET", "https://x/objects/k", _sleep=lambda s: None)
        self.assertEqual(len(calls), len(mr.RETRY_DELAYS_S) + 1)
