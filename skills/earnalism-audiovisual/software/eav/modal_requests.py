"""Modal runs through GitHub Actions: request files and the private R2 transfer of the outputs.

A session that cannot reach Modal writes a request file (`eav modal-request`); the workflow
`.github/workflows/modal-jobs.yml` runs it with `modal-run --request`, uploads the job folder to
the private R2 bucket (`eav r2-upload`) and records the file list with sha256 in the request;
`eav modal-fetch` downloads and verifies it. `eav import` is unchanged and still does the import.

R2 is reached through the Cloudflare v4 REST API (api.cloudflare.com), not the S3 endpoint.
Shapes verified live by root against reo-earnalism-maison-private (27 Nov 2026):
  PUT    .../accounts/{account}/r2/buckets/{bucket}/objects/{key}   body = the object bytes;
         returns {"success": true, "result": {"key", "size", "etag"}}
  GET    .../objects/{key}                                          returns the raw object bytes
  DELETE .../objects/{key}
  GET    .../objects?prefix=<p>&per_page=1000[&cursor=<c>]
         returns {"success": true, "result": [{"key", "size", "etag", ...}], "result_info"?: {...}}
The key keeps its slashes literally; each path segment is percent-encoded on its own. Listing
follows a non-empty `result_info.cursor` until there is none (`result` as {"objects": [...]} is also
accepted). No code here reads a token from disk or prints one: in GitHub Actions the bearer token
comes from the CLOUDFLARE_R2_TOKEN secret through the environment; in the Claude session the
egress proxy injects it, so the caller passes no token.

Each request has its own prefix, `gpu-jobs/<slug>/<job_id>/run-<n>/` (n from its pending run_id),
recorded in the request as `r2_prefix`; probe, upload and fetch use the request's prefix, so a
re-request never meets the objects of an earlier run. (Requests written before per-run prefixes
carry `gpu-jobs/<slug>/<job_id>/` and keep it.) Two reserved names under a prefix:
`_request-result.json` (a copy of the finished request, so `modal-fetch` works even when the
workflow could not push it to the branch) and `_probe/` (the workflow's pre-run probe object,
deleted again).

This module, like budget, needs only the standard library, so the workflow can refuse a request
even when installing the dependencies failed:
  python3 -m eav.modal_requests check <request.json> --workspace <checkout>
  python3 -m eav.modal_requests refuse-unstarted <request.json> --workspace <checkout> --reason <text>
  python3 -m eav.modal_requests replay <job_id> --root <title root> --saved <dir>
The workflow runs these with `python3 -S` (no site-packages, so no code an install added runs in
the steps that hold the push token).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import budget

SCHEMA = "earnalism.modal-request.v1"
BRANCH = "claude/wonderful-bardeen-s9k90x"
R2_ACCOUNT = "9a524b17e84b2df55933527db876b69a"
R2_BUCKET = "reo-earnalism-maison-private"
API = "https://api.cloudflare.com/client/v4"
TOKEN_ENV = "CLOUDFLARE_R2_TOKEN"
OPEN = ("requested", "running")
FINISHED = ("done", "failed", "hard_stopped")
REFUSED = "refused"  # refused before Modal was contacted: its pending row was released
STATUSES = OPEN + FINISHED + (REFUSED,)
RESULT_NAME = "_request-result.json"
PROBE_DIR = "_probe/"
FALLBACK_BRANCH = "modal-results/{job_id}"  # or modal-results/<job_id>-run-<GitHub run id> if taken
JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
TITLE_ROOT_RE = re.compile(r"^production/audiovisual/[a-z0-9][a-z0-9-]*$")
PER_PAGE = 1000
RUN_TO_REQUEST = {"ok": "done", "failed": "failed", "hard_stopped": "hard_stopped"}
TIMEOUT_S = 120
MAX_PAGES = 1000


class R2Error(Exception):
    """A transfer to or from R2 failed or did not verify."""
    transient = False  # set on HTTP 429/5xx and network errors, which _call retries
    http_status = None  # the HTTP status of a refused call (404: no such object)


# ---------------------------------------------------------------- request files
def requests_dir(root) -> Path:
    """production/audiovisual/<slug> -> production/audiovisual/modal-requests."""
    return Path(root).resolve().parent / "modal-requests"


def request_path(root, job_id) -> Path:
    return requests_dir(root) / f"{job_id}.json"


def repo_root(start) -> Path:
    """The git checkout holding start (the nearest ancestor with a .git entry)."""
    p = Path(start).resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d
    raise ValueError(f"{start} is not inside a git checkout; the request must name the title root "
                     "relative to the repository the workflow checks out")


def r2_prefix(slug, job_id, run_id=None) -> str:
    """gpu-jobs/<slug>/<job_id>/run-<n>/ for the request whose pending row is run_id."""
    base = f"gpu-jobs/{slug}/{job_id}/"
    return base if run_id is None else f"{base}run-{budget.Ledger.run_number(run_id)}/"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_job_id(job_id) -> bool:
    return isinstance(job_id, str) and bool(JOB_ID_RE.fullmatch(job_id)) and ".." not in job_id


def read_request(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{path}: not a {SCHEMA} request (schema {data.get('schema')!r})")
    if data.get("status") not in STATUSES:
        raise ValueError(f"{path}: unknown request status {data.get('status')!r}")
    return data


def write_request(path, data) -> Path:
    """Atomic write (sorted keys, trailing newline), so a killed process never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".req-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def validate(data, path) -> list:
    """What makes a request file unusable by the workflow (empty list: none): the schema, a known
    status, job_id matching ^[a-z0-9][a-z0-9.-]*$ and the file name, title_root under
    production/audiovisual/, a pending_run_id of this job, colab_units >= 0 and an r2_prefix."""
    if not isinstance(data, dict):
        return ["the request is not a JSON object"]
    errors = []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema {data.get('schema')!r} is not {SCHEMA}")
    if data.get("status") not in STATUSES:
        errors.append(f"unknown status {data.get('status')!r}")
    job_id = data.get("job_id")
    if not valid_job_id(job_id):
        errors.append(f"job_id {job_id!r} does not match {JOB_ID_RE.pattern}")
    elif Path(path).name != f"{job_id}.json":
        errors.append(f"job_id {job_id!r} differs from the file name {Path(path).name!r}")
    root = data.get("title_root")
    if not isinstance(root, str) or not TITLE_ROOT_RE.fullmatch(root):
        errors.append(f"title_root {root!r} is not a title under production/audiovisual/")
    run_id = data.get("pending_run_id")
    if not isinstance(run_id, str) or not isinstance(job_id, str) \
            or run_id.rpartition("#")[0] != job_id or budget.Ledger.run_number(run_id) < 1:
        errors.append(f"pending_run_id {run_id!r} is not a run of {job_id!r}")
    try:
        budget._check_units(data.get("colab_units"))
    except ValueError as e:
        errors.append(f"colab_units: {e}")
    prefix = data.get("r2_prefix")
    if not isinstance(prefix, str) or not prefix.startswith("gpu-jobs/") or not prefix.endswith("/") \
            or ".." in prefix.split("/"):
        errors.append(f"r2_prefix {prefix!r} is not under gpu-jobs/")
    return errors


def locate(data, workspace):
    """(title root, ledger) of a request in the workflow checkout, or ValueError."""
    workspace = Path(workspace).resolve()
    root_rel = data.get("title_root") if isinstance(data, dict) else None
    if not isinstance(root_rel, str) or not TITLE_ROOT_RE.fullmatch(root_rel):
        raise ValueError(f"title_root {root_rel!r} is not a title under production/audiovisual/")
    root = workspace / root_rel
    record = json.loads((root / "record.json").read_text(encoding="utf-8"))
    pinned = record.get("ledger") if isinstance(record, dict) else None
    if not isinstance(pinned, str) or PurePosixPath(pinned).is_absolute() or Path(pinned).is_absolute():
        raise ValueError(f"{root}/record.json pins no relative ledger")
    ledger = (root / pinned).resolve()
    if workspace not in ledger.parents:
        raise ValueError(f"the ledger {ledger} is outside the checkout")
    return root, ledger


def refuse(path, ledger, reason) -> dict:
    """Refuse a request before Modal was contacted: release its pending row, restore the job's CU
    reservation if it never reached Modal (budget.Ledger.undo_move_to_modal), mark it refused. If
    the restored reservation leaves a CU cap exceeded, the request's error says so (hold the job)."""
    req = read_request(path)
    if req.get("pending_run_id"):
        try:
            ledger.release_pending_modal(req["pending_run_id"])
        except (KeyError, ValueError):
            pass  # already released, or no longer pending: it then stays as it is
    if ledger.undo_move_to_modal(req["job_id"]):
        over = ledger.cap_overrun(req["job_id"])
        if over:
            reason = f"{reason}; {over}"
    req.update(status=REFUSED, error=reason, finished_at=now())
    write_request(path, req)
    return req


def refuse_unstarted(path, workspace, reason) -> dict:
    """The workflow, after every step before the upload: a request still open whose run never
    recorded modal_contacted_at is refused (row released, reservation restored). An invalid request
    is refused too; its ledger is touched only when it can be located. Returns
    {"refused": bool, "why", "root", "ledger"} (root/ledger None when not located)."""
    path = Path(path)
    out = {"refused": False, "why": "", "root": None, "ledger": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        out["why"] = f"unreadable request: {e}"
        return out
    if not isinstance(data, dict) or data.get("status") not in OPEN:
        out["why"] = f"not open ({data.get('status') if isinstance(data, dict) else 'not an object'})"
        return out
    if data.get("modal_contacted_at"):
        out["why"] = f"Modal was contacted at {data['modal_contacted_at']}"
        return out
    errors = validate(data, path)
    try:
        root, ledger_path = locate(data, workspace)
    except (OSError, ValueError) as e:
        root = ledger_path = None
        errors.append(f"cannot locate the ledger: {e}")
    if not errors:
        refuse(path, budget.Ledger(ledger_path), reason)
    else:
        reason = f"{reason}; invalid request: {'; '.join(errors)}"
        # the ledger is touched only for the job this file is named after (a file whose job_id
        # differs from its name never releases another job's row or reservation)
        if ledger_path is not None and valid_job_id(data.get("job_id")) \
                and path.name == f"{data['job_id']}.json":
            ledger = budget.Ledger(ledger_path)
            run_id = data.get("pending_run_id")
            if isinstance(run_id, str) and run_id.rpartition("#")[0] == data["job_id"]:
                try:
                    ledger.release_pending_modal(run_id)
                except (KeyError, ValueError):
                    pass
            if ledger.undo_move_to_modal(data["job_id"]):
                over = ledger.cap_overrun(data["job_id"])
                if over:
                    reason = f"{reason}; {over}"
        else:
            ledger_path = None
            reason += " (the ledger was not touched: settle any pending row with modal-settle)"
        data.update(status=REFUSED, error=reason, finished_at=now())
        write_request(path, data)
    out.update(refused=True, why=reason, root=str(root) if root else None,
               ledger=str(ledger_path) if ledger_path else None)
    return out


def pinned_ledger(root) -> Path:
    """The ledger record.json pins (relative to the title root), as `eav` itself resolves it."""
    root = Path(root)
    record = json.loads((root / "record.json").read_text(encoding="utf-8"))
    pinned = record.get("ledger") if isinstance(record, dict) else None
    if not isinstance(pinned, str) or not pinned or PurePosixPath(pinned).is_absolute() \
            or Path(pinned).is_absolute():
        raise ValueError(f"{root}/record.json pins no relative ledger")
    return (root / pinned).resolve()


def replay(job_id, root, saved) -> dict:
    """The publish script, when a push-back rebase conflicts: on the freshly fetched branch,
    re-apply this run's saved request file and this job's own ledger entry and rows
    (budget.Ledger.replay_job); every other job's entry and rows stay. Stdlib only, so it works
    even when installing the dependencies failed."""
    saved = Path(saved)
    req = read_request(saved / "request.json")
    if req["job_id"] != job_id:
        raise ValueError(f"the saved request is for {req['job_id']}, not {job_id}")
    ledger = budget.Ledger(pinned_ledger(root))
    ledger.replay_job(job_id, json.loads((saved / "ledger.json").read_text(encoding="utf-8")))
    write_request(request_path(root, job_id), req)
    return req


def check(path, workspace) -> dict:
    """The workflow's mark-running step: {"status", "errors", "root", "ledger"} of a request."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"status": None, "errors": [f"unreadable request: {e}"], "root": None, "ledger": None}
    errors = validate(data, path)
    root = ledger = None
    try:
        root, ledger = locate(data, workspace)
    except (OSError, ValueError) as e:
        errors.append(f"cannot locate the ledger: {e}")
    return {"status": data.get("status") if isinstance(data, dict) else None, "errors": errors,
            "root": str(root) if root else None, "ledger": str(ledger) if ledger else None}


# ---------------------------------------------------------------- R2 over the Cloudflare API
def _object_url(key, account=R2_ACCOUNT, bucket=R2_BUCKET) -> str:
    path = "/".join(urllib.parse.quote(seg, safe="") for seg in key.split("/"))
    return f"{API}/accounts/{account}/r2/buckets/{bucket}/objects/{path}"


def _list_url(prefix, cursor=None, account=R2_ACCOUNT, bucket=R2_BUCKET) -> str:
    query = {"prefix": prefix, "per_page": PER_PAGE}
    if cursor:
        query["cursor"] = cursor
    return f"{API}/accounts/{account}/r2/buckets/{bucket}/objects?{urllib.parse.urlencode(query)}"


RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_DELAYS_S = (2, 5, 15, 30)  # transient Cloudflare errors: retry the same idempotent call


def _call(opener, method, url, body=None, token=None, _sleep=None) -> bytes:
    """One R2 API call; transient HTTP 429/5xx and network errors are retried with backoff.

    PUT, GET, DELETE and list are idempotent here (same key, same bytes), so a retry is safe."""
    import time
    sleep = _sleep or time.sleep
    for delay in RETRY_DELAYS_S + (None,):
        try:
            return _call_once(opener, method, url, body, token)
        except R2Error as e:
            if delay is None or not e.transient:
                raise
            sleep(delay)


def _call_once(opener, method, url, body=None, token=None) -> bytes:
    headers = {"Accept": "*/*"}
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with opener.open(req, timeout=TIMEOUT_S) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        err = R2Error(f"{method} {url.split('?')[0]}: HTTP {e.code}")
        err.transient = e.code in RETRY_STATUSES
        err.http_status = e.code
        raise err from None
    except (urllib.error.URLError, OSError) as e:
        err = R2Error(f"{method} {url.split('?')[0]}: {type(e).__name__}: {e}")
        err.transient = True
        raise err from None


def _envelope(raw: bytes, what: str) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise R2Error(f"{what}: the response is not JSON") from None
    if not isinstance(data, dict) or data.get("success") is False:
        errors = data.get("errors") if isinstance(data, dict) else None
        raise R2Error(f"{what}: the API reported failure {errors!r}")
    return data


def default_opener():
    """urllib with the environment's proxy settings (the session proxy adds the credential)."""
    return urllib.request.build_opener()


def list_keys(prefix, opener, token=None) -> list:
    """Every object key under prefix, following result_info.cursor while it is non-empty."""
    keys, cursor, seen = [], None, set()
    for _ in range(MAX_PAGES):
        data = _envelope(_call(opener, "GET", _list_url(prefix, cursor), token=token), "list")
        result = data.get("result")
        objects = result.get("objects", []) if isinstance(result, dict) else (result or [])
        if not isinstance(objects, list):
            raise R2Error("list: `result` holds no object list")
        for obj in objects:
            if not isinstance(obj, dict) or not isinstance(obj.get("key"), str):
                raise R2Error(f"list: an entry has no key: {obj!r}")
            keys.append(obj["key"])
        info = data.get("result_info") or (result if isinstance(result, dict) else {}) or {}
        cursor = info.get("cursor") if isinstance(info, dict) else None
        if not cursor:
            return keys
        if cursor in seen:
            raise R2Error(f"list: the cursor repeats under {prefix}")
        seen.add(cursor)
    raise R2Error(f"list: more than {MAX_PAGES} pages under {prefix}")


def get_object(key, opener, token=None) -> bytes:
    return _call(opener, "GET", _object_url(key), token=token)


def put_object(key, body: bytes, opener, token=None) -> None:
    raw = _call(opener, "PUT", _object_url(key), body=body, token=token)
    if raw.strip():
        _envelope(raw, f"PUT {key}")


def delete_object(key, opener, token=None) -> None:
    raw = _call(opener, "DELETE", _object_url(key), token=token)
    if raw.strip():
        _envelope(raw, f"DELETE {key}")


def _reserved(rel: str) -> bool:
    return rel == RESULT_NAME or rel.startswith(PROBE_DIR)


def probe(prefix, opener, token=None, body=b"eav r2 probe\n") -> str:
    """PUT, list, GET and DELETE a tiny object under prefix + _probe/, so a wrong token or API shape
    is found before any paid run. Returns the probe key; R2Error on any failure."""
    key = prefix + PROBE_DIR + "probe.txt"
    put_object(key, body, opener, token)
    if key not in list_keys(prefix + PROBE_DIR, opener, token):
        raise R2Error(f"probe: {key} was put but is not listed")
    if get_object(key, opener, token) != body:
        raise R2Error(f"probe: {key} does not read back")
    delete_object(key, opener, token)
    return key


def put_result(prefix, request: dict, opener, token=None) -> None:
    """The finished request as prefix + _request-result.json (the copy modal-fetch can read)."""
    put_object(prefix + RESULT_NAME, (json.dumps(request, indent=2, sort_keys=True) + "\n").encode(),
               opener, token)


def get_result(prefix, opener, token=None):
    """The R2 copy of the finished request, or None if there is none (HTTP 404). Any other failure
    (auth, network, a 5xx after the retries) is raised: it says nothing about whether a copy exists."""
    try:
        raw = get_object(prefix + RESULT_NAME, opener, token)
    except R2Error as e:
        if e.http_status == 404:
            return None
        raise
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise R2Error(f"{RESULT_NAME} under {prefix} is not JSON") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("status") not in STATUSES:
        raise R2Error(f"{RESULT_NAME} under {prefix} is not a {SCHEMA} request")
    return data


def upload_folder(folder, prefix, opener, token=None) -> list:
    """PUT every file of folder under prefix + its relative path, then GET each one back and
    compare sha256. Returns [{"path", "sha256", "bytes"}] in path order."""
    folder = Path(folder)
    if not folder.is_dir():
        raise R2Error(f"no job folder at {folder}")
    files = []
    for p in sorted(x for x in folder.rglob("*") if x.is_file()):
        rel = p.relative_to(folder).as_posix()
        if _reserved(rel):
            raise R2Error(f"{rel}: a reserved name under the job prefix")
        body = p.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        put_object(prefix + rel, body, opener, token)
        back = get_object(prefix + rel, opener, token)
        if hashlib.sha256(back).hexdigest() != digest:
            raise R2Error(f"{rel}: the uploaded object does not read back with the same sha256")
        files.append({"path": rel, "sha256": digest, "bytes": len(body)})
    if not files:
        raise R2Error(f"the job folder {folder} is empty")
    return files


def fetch_folder(prefix, files, dest, opener, token=None) -> Path:
    """Download every object under prefix into dest and verify it against files (the request's
    list). Refused, with nothing left at dest, when an object is missing, extra or has another
    sha256. The files land in a sibling temp folder first and are moved into place at the end."""
    dest = Path(dest)
    want = {f["path"]: f["sha256"] for f in files}
    if not want:
        raise R2Error("the request lists no files")
    keys = list_keys(prefix, opener, token)
    have = {}
    for key in keys:
        if not key.startswith(prefix) or key == prefix:
            raise R2Error(f"list returned {key!r} outside {prefix}")
        if not _reserved(key[len(prefix):]):
            have[key[len(prefix):]] = key
    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    if missing:
        raise R2Error("missing in R2: " + ", ".join(missing))
    if extra:
        raise R2Error("in R2 but not in the request: " + ", ".join(extra))
    if dest.exists():
        raise R2Error(f"{dest} already exists; move it away or pass another --into")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=f".{dest.name}-"))
    try:
        for rel in sorted(want):
            if rel.startswith("/") or ".." in Path(rel).parts:
                raise R2Error(f"unsafe path in the request: {rel}")
            body = get_object(have[rel], opener, token)
            if hashlib.sha256(body).hexdigest() != want[rel]:
                raise R2Error(f"{rel}: sha256 differs from the request")
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return dest


# ---------------------------------------------------------------- workflow entry point (stdlib only)
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m eav.modal_requests")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("check", "refuse-unstarted"):
        s = sub.add_parser(name)
        s.add_argument("request")
        s.add_argument("--workspace", required=True)
        if name == "refuse-unstarted":
            s.add_argument("--reason", required=True)
    s = sub.add_parser("replay")
    s.add_argument("job_id")
    s.add_argument("--root", required=True)
    s.add_argument("--saved", required=True, help="folder with this run's request.json and ledger.json")
    args = p.parse_args(argv)
    if args.command == "replay":
        try:
            req = replay(args.job_id, args.root, args.saved)
        except (OSError, ValueError, KeyError) as e:
            print(f"STOP: replay failed: {type(e).__name__}: {e}")
            return 2
        print(f"Replayed request {args.job_id} ({req['status']}) and its ledger rows onto the "
              "current tree.")
        return 0
    if args.command == "check":
        result = check(args.request, args.workspace)
    else:
        result = refuse_unstarted(args.request, args.workspace, args.reason)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
