"""R2 exchange for Colab jobs (owner-approved option B, 2026-11-23; references/colab-exchange.md).

The owner's only step per job is: open the notebook in Colab, set RUN = True, Run all. Inputs
arrive and outputs leave through two short-lived, single-object signed URLs:

  GET  exports/colab-exchange/<title>/<job_id>/inputs.zip    (uploaded here by exchange-stage)
  PUT  exports/colab-exchange/<title>/<job_id>/outputs.tar   (uploaded by the notebook)

Maison signs them (`manage.py presign_colab_exchange`), this module checks them and writes
exchange.json into the job dir. The URLs are capabilities: they live only in exchange.json (job
dir, gitignored, and the Drive job folder), never in record.json, never in a commit.

Production transport is the Cloudflare REST API object endpoint with a bearer token taken from
$CLOUDFLARE_API_TOKEN (the egress proxy may inject the real token; the value may be a placeholder).
Tests patch cloudflare_upload / cloudflare_download; nothing here runs at import time.
"""
import json
import re
import shutil
import tarfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

SCHEMA = "earnalism.colab-exchange.v1"
PREFIX = "exports/colab-exchange"
INPUTS, OUTPUTS = "inputs.zip", "outputs.tar"
INPUT_TYPE, OUTPUT_TYPE = "application/zip", "application/x-tar"
FILENAME = "exchange.json"
MIN_VALIDITY_S = 2 * 3600
MAX_OUTPUT_BYTES = 8 * 1024 ** 3
KINDS = ("narration", "stills", "music", "retouch", "edit", "film_clips")  # reel_clips use the Wan batch builder's own route
API = "https://api.cloudflare.com/client/v4/accounts/{account}/r2/buckets/{bucket}/objects/{key}"
_SAFE = re.compile(r"[a-z0-9][a-z0-9-]*")
_ACCOUNT = re.compile(r"[0-9a-f]{32}")
_BUCKET = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")
_MEMBER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class ExchangeError(ValueError):
    """The exchange request or archive is refused; nothing was written or imported."""


def key(title: str, job_id: str, name: str) -> str:
    if not _SAFE.fullmatch(title or "") or not _SAFE.fullmatch(job_id or "") or name not in (INPUTS, OUTPUTS):
        raise ExchangeError("exchange keys need a lowercase title slug and job id")
    return f"{PREFIX}/{title}/{job_id}/{name}"


def presign_requests(title: str, job_id: str) -> list:
    return [{"key": key(title, job_id, INPUTS), "method": "GET"},
            {"key": key(title, job_id, OUTPUTS), "method": "PUT", "content_type": OUTPUT_TYPE}]


def presign_command(request: dict) -> str:
    cmd = f"python manage.py presign_colab_exchange --key {request['key']} --method {request['method']}"
    if request.get("content_type"):
        cmd += f" --content-type {request['content_type']}"
    return cmd


def endpoint(account: str, bucket: str) -> tuple:
    if not _ACCOUNT.fullmatch(account or ""):
        raise ExchangeError("the Cloudflare account id must be 32 lowercase hex characters "
                            "(--account or $EAV_R2_ACCOUNT)")
    if not _BUCKET.fullmatch(bucket or ""):
        raise ExchangeError("the private R2 bucket name is missing or invalid (--bucket or $EAV_R2_BUCKET)")
    return account, bucket


def parse_signed(text: str) -> list:
    """The presign command's output: JSON lines (one object per line) or one JSON array."""
    text = text.strip()
    try:
        rows = json.loads(text) if text.startswith("[") else [json.loads(l) for l in text.splitlines()
                                                              if l.strip()]
    except ValueError:
        raise ExchangeError("--signed must hold the two JSON lines presign_colab_exchange printed") from None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ExchangeError("--signed must hold JSON objects")
    return rows


def _when(value, what) -> datetime:
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ExchangeError(f"{what} expires_at is not an ISO 8601 time") from None
    if when.tzinfo is None:
        raise ExchangeError(f"{what} expires_at has no time zone")
    return when


def _url_expiry(url: str, what: str):
    """The expiry the SigV4 query itself carries (X-Amz-Date + X-Amz-Expires), when present."""
    q = parse_qs(urlsplit(url).query)
    if "X-Amz-Date" not in q and "X-Amz-Expires" not in q:
        return None
    try:
        signed = datetime.strptime(q["X-Amz-Date"][0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return signed + timedelta(seconds=int(q["X-Amz-Expires"][0]))
    except (KeyError, ValueError):
        raise ExchangeError(f"{what} URL carries an unreadable signature expiry") from None


def check_signed(rows: list, title: str, job_id: str, now: datetime = None) -> dict:
    """Exactly the job's GET inputs.zip and PUT outputs.tar, each valid for >= 2 h from now."""
    now = now or datetime.now(timezone.utc)
    want = {key(title, job_id, INPUTS): "GET", key(title, job_id, OUTPUTS): "PUT"}
    if len(rows) != 2:
        raise ExchangeError(f"expected exactly 2 signed requests (GET {INPUTS}, PUT {OUTPUTS}), got {len(rows)}")
    found = {}
    for row in rows:
        k, method = row.get("key"), row.get("method")
        if k not in want:
            raise ExchangeError(f"signed key {k!r} is not one of this job's exchange keys {sorted(want)}")
        if k in found:
            raise ExchangeError(f"signed key {k!r} appears twice")
        if method != want[k]:
            raise ExchangeError(f"signed method {method!r} for {k} must be {want[k]}")
        url = row.get("url")
        parts = urlsplit(url if isinstance(url, str) else "")
        if (parts.scheme != "https" or not (parts.hostname or "").endswith(".r2.cloudflarestorage.com")
                or parts.username or parts.password or parts.fragment
                or not unquote(parts.path).endswith("/" + k)):
            raise ExchangeError(f"signed URL for {k} is not an HTTPS R2 URL for that exact object")
        headers = row.get("headers") or {}
        if not isinstance(headers, dict):
            raise ExchangeError(f"signed headers for {k} must be an object")
        if method == "PUT" and headers != {"Content-Type": OUTPUT_TYPE}:
            raise ExchangeError(f"the PUT for {k} must sign exactly Content-Type {OUTPUT_TYPE}, got {headers!r}")
        if method == "GET" and headers:
            raise ExchangeError(f"the GET for {k} must not need headers, got {sorted(headers)}")
        expires = _when(row.get("expires_at"), k)
        in_url = _url_expiry(url, k)
        if in_url is not None:
            expires = min(expires, in_url)
        if expires < now + timedelta(seconds=MIN_VALIDITY_S):
            raise ExchangeError(f"the signed URL for {k} expires at {expires.isoformat()}, less than "
                                f"{MIN_VALIDITY_S // 3600} h from now: re-sign with a longer --ttl-seconds")
        found[k] = {"url": url, "headers": headers, "expires_at": expires}
    inputs, outputs = found[key(title, job_id, INPUTS)], found[key(title, job_id, OUTPUTS)]
    return {"inputs_key": key(title, job_id, INPUTS), "outputs_key": key(title, job_id, OUTPUTS),
            "inputs_url": inputs["url"], "outputs_url": outputs["url"],
            "outputs_headers": outputs["headers"],
            "expires_at": min(inputs["expires_at"], outputs["expires_at"])}


def exchange_document(title, job_id, checked, inputs_sha256, inputs_bytes) -> dict:
    return {"schema": SCHEMA, "job_id": job_id, "title": title,
            "inputs": {"url": checked["inputs_url"], "sha256": inputs_sha256, "bytes": inputs_bytes},
            "outputs": {"url": checked["outputs_url"], "method": "PUT",
                        "headers": dict(checked["outputs_headers"])},
            "expires_at": checked["expires_at"].astimezone(timezone.utc).isoformat()}


def safe_extract(tar_path, dest) -> list:
    """Extract a flat, uncompressed tar of regular files into dest (which must not exist).

    Refuses absolute paths, `..`, sub-directories, links, devices and duplicate names before
    writing anything; on any failure dest is removed, so nothing is left behind."""
    dest = Path(dest)
    try:
        tar = tarfile.open(tar_path, mode="r:")
    except (tarfile.TarError, OSError) as e:
        raise ExchangeError(f"outputs.tar is not an uncompressed tar archive: {e}") from None
    with tar:
        try:
            members = tar.getmembers()
        except (tarfile.TarError, OSError) as e:
            raise ExchangeError(f"outputs.tar is unreadable: {e}") from None
        seen, total = set(), 0
        for m in members:
            if not _MEMBER.fullmatch(m.name) or m.name in (".", ".."):
                raise ExchangeError(f"unsafe member name in outputs.tar: {m.name!r} (flat file names only)")
            if not m.isreg():
                raise ExchangeError(f"outputs.tar member {m.name!r} is not a regular file")
            if m.name in seen:
                raise ExchangeError(f"duplicate member in outputs.tar: {m.name!r}")
            seen.add(m.name)
            total += m.size
            if total > MAX_OUTPUT_BYTES:
                raise ExchangeError("outputs.tar expands past the exchange size limit")
        if not members:
            raise ExchangeError("outputs.tar is empty")
        dest.mkdir(parents=True)
        try:
            for m in members:
                src = tar.extractfile(m)
                with src, open(dest / m.name, "xb") as out:
                    shutil.copyfileobj(src, out)
                if (dest / m.name).stat().st_size != m.size:
                    raise ExchangeError(f"outputs.tar member {m.name!r} is truncated")
        except BaseException as e:
            shutil.rmtree(dest, ignore_errors=True)
            if isinstance(e, (tarfile.TarError, OSError)):
                raise ExchangeError(f"outputs.tar could not be extracted: {e}") from None
            raise
    return [m.name for m in members]


# ---------------------------------------------------------------- production transport
def _api_url(account, bucket, object_key) -> str:
    endpoint(account, bucket)
    return API.format(account=account, bucket=bucket, key=quote(object_key, safe="/"))


def cloudflare_upload(account, bucket, object_key, path, content_type, token):
    """PUT one object to the private bucket through the Cloudflare REST API."""
    data = Path(path).read_bytes()
    req = urllib.request.Request(_api_url(account, bucket, object_key), data=data, method="PUT",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": content_type,
                                          "Content-Length": str(len(data))})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            status, body = r.status, r.read(65536)
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read(65536)
    if not 200 <= status < 300:
        raise ExchangeError(f"R2 upload of {object_key} failed: HTTP {status}")
    try:
        if json.loads(body or b"{}").get("success") is False:
            raise ExchangeError(f"R2 upload of {object_key} was refused by the API")
    except ValueError:
        pass


def cloudflare_download(account, bucket, object_key, dest, token, max_bytes):
    """GET one object from the private bucket into dest, at most max_bytes."""
    req = urllib.request.Request(_api_url(account, bucket, object_key), method="GET",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        r = urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        raise ExchangeError(f"R2 download of {object_key} failed: HTTP {e.code}"
                            + (" (the notebook has not uploaded it yet?)" if e.code == 404 else "")) from None
    with r, open(dest, "xb") as out:
        if not 200 <= r.status < 300:
            raise ExchangeError(f"R2 download of {object_key} failed: HTTP {r.status}")
        total = 0
        while block := r.read(1 << 20):
            total += len(block)
            if total > max_bytes:
                raise ExchangeError(f"{object_key} is larger than {max_bytes} bytes")
            out.write(block)
