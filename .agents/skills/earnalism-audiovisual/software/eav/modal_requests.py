"""Modal runs through GitHub Actions: request files and the private R2 transfer of the outputs.

A session that cannot reach Modal writes a request file (`eav modal-request`); the workflow
`.github/workflows/modal-jobs.yml` runs it with `modal-run --request`, uploads the job folder to
the private R2 bucket (`eav r2-upload`) and records the file list with sha256 in the request;
`eav modal-fetch` downloads and verifies it. `eav import` is unchanged and still does the import.

R2 is reached through the Cloudflare v4 REST API (api.cloudflare.com), not the S3 endpoint:
  PUT  /client/v4/accounts/{account}/r2/buckets/{bucket}/objects/{key}   body = the object bytes
  GET  /client/v4/accounts/{account}/r2/buckets/{bucket}/objects/{key}   returns the object bytes
  GET  /client/v4/accounts/{account}/r2/buckets/{bucket}/objects?prefix=<p>[&cursor=<c>]
       returns the usual envelope {"success", "errors", "result": [{"key", "size", "etag", ...}],
       "result_info": {"cursor", "is_truncated", ...}}
The key is one path segment (percent-encoded, slashes included). The listing parser is tolerant:
`result` may also be {"objects": [...]} and the cursor/is_truncated pair may sit in `result_info`
or in `result`. No code here reads a token from disk or prints one: in GitHub Actions the bearer
token comes from the CLOUDFLARE_R2_TOKEN secret through the environment; in the Claude session the
egress proxy injects it, so the caller passes no token.
"""
import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMA = "earnalism.modal-request.v1"
BRANCH = "claude/wonderful-bardeen-s9k90x"
R2_ACCOUNT = "9a524b17e84b2df55933527db876b69a"
R2_BUCKET = "reo-earnalism-maison-private"
API = "https://api.cloudflare.com/client/v4"
TOKEN_ENV = "CLOUDFLARE_R2_TOKEN"
OPEN = ("requested", "running")
FINISHED = ("done", "failed", "hard_stopped")
STATUSES = OPEN + FINISHED
RUN_TO_REQUEST = {"ok": "done", "failed": "failed", "hard_stopped": "hard_stopped"}
TIMEOUT_S = 120
MAX_PAGES = 1000


class R2Error(Exception):
    """A transfer to or from R2 failed or did not verify."""


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


def r2_prefix(slug, job_id) -> str:
    return f"gpu-jobs/{slug}/{job_id}/"


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


# ---------------------------------------------------------------- R2 over the Cloudflare API
def _object_url(key, account=R2_ACCOUNT, bucket=R2_BUCKET) -> str:
    return f"{API}/accounts/{account}/r2/buckets/{bucket}/objects/{urllib.parse.quote(key, safe='')}"


def _list_url(prefix, cursor=None, account=R2_ACCOUNT, bucket=R2_BUCKET) -> str:
    query = {"prefix": prefix}
    if cursor:
        query["cursor"] = cursor
    return f"{API}/accounts/{account}/r2/buckets/{bucket}/objects?{urllib.parse.urlencode(query)}"


def _call(opener, method, url, body=None, token=None) -> bytes:
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
        raise R2Error(f"{method} {url.split('?')[0]}: HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise R2Error(f"{method} {url.split('?')[0]}: {type(e).__name__}: {e}") from None


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
    """Every object key under prefix, following the cursor while the listing is truncated."""
    keys, cursor = [], None
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
        if not (isinstance(info, dict) and info.get("is_truncated") and cursor):
            return keys
    raise R2Error(f"list: more than {MAX_PAGES} pages under {prefix}")


def get_object(key, opener, token=None) -> bytes:
    return _call(opener, "GET", _object_url(key), token=token)


def put_object(key, body: bytes, opener, token=None) -> None:
    raw = _call(opener, "PUT", _object_url(key), body=body, token=token)
    if raw.strip():
        _envelope(raw, f"PUT {key}")


def upload_folder(folder, prefix, opener, token=None) -> list:
    """PUT every file of folder under prefix + its relative path, then GET each one back and
    compare sha256. Returns [{"path", "sha256", "bytes"}] in path order."""
    folder = Path(folder)
    if not folder.is_dir():
        raise R2Error(f"no job folder at {folder}")
    files = []
    for p in sorted(x for x in folder.rglob("*") if x.is_file()):
        rel = p.relative_to(folder).as_posix()
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
