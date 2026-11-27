"""Source-bound Colab output -> existing Maison private drafts. Never publishes.

The HTTP client stages private assets and calls the private attachment endpoint.
Existing verify_media_asset prepares actual provider evidence; nothing publishes.
"""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from urllib import error, request
from urllib.parse import urlsplit

MAX_STAGED_R2_BYTES = 64 * 1024 * 1024

class HandoffError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _version(etag):
    match = re.fullmatch(r'"v([1-9][0-9]*)"', etag or "")
    if not match:
        raise HandoffError("STRONG_REVISION_ETAG_REQUIRED")
    return int(match[1])


def prepare_handoff(manifest, asset_root):
    from operations.production_bundle import verify_bundle
    digest = verify_bundle(manifest, asset_root)
    return _handoff_plan(manifest, digest)


def _handoff_plan(manifest, digest):
    content = manifest["content"]
    if manifest["private"] is not True or not all(k in content for k in ("edition_id", "revision_id", "expected_etag")):
        raise HandoffError("PRIVATE_EXISTING_DRAFT_IDENTITY_REQUIRED")
    _version(content["expected_etag"])
    uploads, retained = [], []
    limits = {"audio": 268435456, "video": 10737418240, "timing_map": 1048576, "rights_document": 4194304, "reader_source": 4194304}
    for item in manifest["assets"]:
        role, mime = item["role"], item["content_type"]
        if role in {"native_audio", "thumbnail"}:
            retained.append(item["id"])
            continue
        kind = {"audio": "audio", "video": "video", "timing_map": "timing_map", "rights_document": "rights_document"}.get(role, "reader_source")
        suffix = ".json" if mime == "application/json" else ".txt"
        if role in {"audio", "video"}:
            if mime != ("audio/mpeg" if role == "audio" else "video/mp4") or not item.get("unit_id") or type(item.get("duration_ms")) is not int:
                raise HandoffError("MEDIA_UNIT_AND_MEASURED_DURATION_REQUIRED")
            suffix = ".mp3" if role == "audio" else ".mp4"
        elif role == "rights_document":
            if mime not in {"application/pdf", "text/plain"}:
                raise HandoffError("UNSUPPORTED_PRIVATE_RIGHTS_MIME")
            suffix = ".pdf" if mime == "application/pdf" else ".txt"
        elif role == "captions" and mime in {"text/vtt", "application/x-subrip", "text/plain"}:
            # Exact original caption bytes are retained as staff-only text evidence.
            mime, suffix = "text/plain", ".txt"
        elif role in {"source_text", "reader_source"} and mime == "text/plain":
            suffix = ".txt"
        elif mime != "application/json":
            raise HandoffError("JSON_EVIDENCE_REQUIRED")
        if item["bytes"] > limits[kind]:
            raise HandoffError("SPLIT_ASSET_TO_EXISTING_MAISON_LIMIT")
        body = {"edition_revision_id": content["revision_id"], "kind": kind,
                "content_type": mime, "bytes": item["bytes"], "sha256": item["sha256"],
                "file_name": item["id"] + suffix}
        for key in ("unit_id", "duration_ms"):
            if key in item:
                body[key] = item[key]
        uploads.append({"id": item["id"], "path": item["path"], "body": body})
    if len(uploads) > 100 or len(canonical(manifest)) > 196608:
        raise HandoffError("SPLIT_BOUNDED_PLATFORM_HANDOFF_BUNDLE")
    if sum(x["body"]["bytes"] for x in uploads if x["body"]["kind"] != "video") > MAX_STAGED_R2_BYTES:
        raise HandoffError("SPLIT_PLATFORM_HANDOFF_TO_64_MIB_STAGED_R2_BYTES")
    return {"schema": "earnalism.maison_handoff_plan.v1", "bundle_sha256": digest,
            "content": content, "uploads": uploads, "retained_only_assets": retained,
            "execution_enabled": False, "publication": False,
            "limits": "Existing drafts only; new-book HTTP import remains EN-071 only. Video uses managed private Stream TUS; WAV/thumbnail remain retained provenance."}


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise HandoffError("REDIRECT_REFUSED")


class MaisonHTTP:
    """In-memory existing session credentials; direct PUT never forwards them to R2."""
    def __init__(self, origin, session_cookie, csrf_token, *, opener=None, timeout=30):
        parsed = urlsplit(origin)
        local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (parsed.scheme != "https" and not local) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise HandoffError("HTTPS_MAISON_OR_LOOPBACK_ORIGIN_REQUIRED")
        if any("\n" in x or "\r" in x for x in (session_cookie, csrf_token)):
            raise HandoffError("INVALID_SESSION_HEADERS")
        self.origin, self.cookie, self.csrf = origin.rstrip("/"), session_cookie, csrf_token
        self.opener, self.timeout = opener or request.build_opener(_NoRedirect()), timeout

    def request(self, method, path, *, payload=None, headers=None):
        routes = {"GET": r"/api/v1/staff/(?:editions/[a-f0-9-]+/(?:review|production-handoffs)|drafts/[a-f0-9-]+/document|assets/[a-f0-9-]+)",
                  "POST": r"/api/v1/staff/(?:books/imports|assets/(?:uploads|[a-f0-9-]+/complete)|editions/[a-f0-9-]+/(?:production-handoffs|source-imports))"}
        if not re.fullmatch(routes.get(method, r"(?!)"), path):
            raise HandoffError("STAFF_ROUTE_REQUIRED")
        h = {"Accept": "application/json", "Cookie": self.cookie, "X-CSRFToken": self.csrf,
             "Origin": self.origin, "Referer": self.origin + "/", **(headers or {})}
        data = None if payload is None else canonical(payload)
        if data is not None:
            h["Content-Type"] = "application/json"
        req = request.Request(self.origin + path, data=data, method=method, headers=h)
        try:
            response = self.opener.open(req, timeout=self.timeout)
        except error.HTTPError as exc:
            response = exc
        except Exception:
            raise HandoffError("HTTP_TRANSPORT_OUTCOME_UNKNOWN") from None
        with response:
            limit = 4194304 if path.endswith("/document") else 262144
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise HandoffError("BOUNDED_JSON_RESPONSE_REQUIRED")
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                raise HandoffError("JSON_RESPONSE_REQUIRED") from None
            if not isinstance(body, dict):
                raise HandoffError("JSON_OBJECT_RESPONSE_REQUIRED")
            return response.code, body, dict(response.headers)

    def put_upload(self, url, required_headers, path):
        parsed = urlsplit(url)
        same = (parsed.scheme, parsed.netloc) == (urlsplit(self.origin).scheme, urlsplit(self.origin).netloc)
        r2 = parsed.scheme == "https" and parsed.hostname and parsed.hostname.endswith(".r2.cloudflarestorage.com")
        if not (same or r2) or parsed.username or parsed.password or parsed.fragment:
            raise HandoffError("UNSUPPORTED_UPLOAD_ORIGIN")
        h = dict(required_headers)
        if set(h) - {"Content-Type", "If-None-Match"}:
            raise HandoffError("UNEXPECTED_UPLOAD_HEADERS")
        if not same and h.get("If-None-Match") != "*":
            raise HandoffError("CREATE_ONCE_R2_GRANT_REQUIRED")
        if same:
            if not parsed.path.startswith("/api/v1/staff/assets/") or not parsed.path.endswith("/local-upload"):
                raise HandoffError("LOCAL_UPLOAD_ROUTE_REQUIRED")
            h.update({"Cookie": self.cookie, "X-CSRFToken": self.csrf, "Origin": self.origin, "Referer": self.origin + "/"})
        path = Path(path); h["Content-Length"] = str(path.stat().st_size)
        try:
            with path.open("rb") as source:
                with self.opener.open(request.Request(url, data=source, headers=h, method="PUT"), timeout=self.timeout) as response:
                    return response.code
        except Exception:
            raise HandoffError("UPLOAD_OUTCOME_UNKNOWN_NO_REPLAY") from None

    def upload_tus(self, grant, path, expected_sha256, *, journal, key, reconcile=False):
        from operations.stream_delivery import upload_private_video
        return upload_private_video(grant["upload_url"], grant["required_headers"], path,
            grant["max_bytes"], expected_sha256, journal=journal, key=key,
            execute=True, reconcile=reconcile, provider_uid=grant["provider_uid"])


def _get(transport, path):
    status, data, headers = transport.request("GET", path)
    if status != 200:
        raise HandoffError("STAFF_READ_FAILED_" + str(status))
    return data, headers


def _call(transport, journal, key, path, body, *, etag=None, reconcile=False, same_operation=None):
    digest = fingerprint({"path": path, "body": body, "etag": etag, "same_operation": same_operation})
    old = journal.read(key)
    if old and old["fingerprint"] != digest:
        raise HandoffError("JOURNALED_REQUEST_CHANGED")
    if old and old["state"] == "acknowledged":
        if not 200 <= old["result"]["status"] < 300:
            raise HandoffError("STAFF_WRITE_REJECTED_" + old["result"]["data"]["code"])
        return old["result"]
    if not old:
        journal.begin(key, digest)
    elif not reconcile:
        raise HandoffError("EXPLICIT_UNKNOWN_OPERATION_RECONCILIATION_REQUIRED")
    headers = {"Idempotency-Key": str(uuid.UUID(hex=hashlib.sha256((same_operation or key).encode()).hexdigest()[:32], version=4))}
    if etag:
        headers["If-Match"] = etag
    try:
        status, data, response_headers = transport.request("POST", path, payload=body, headers=headers)
    except Exception:
        journal.unknown(key, "STAFF_WRITE_OUTCOME_UNKNOWN")
        raise HandoffError("STAFF_WRITE_OUTCOME_UNKNOWN_RECONCILE_SAME_OPERATION") from None
    if 400 <= status < 500:
        code = data.get("code", "request_rejected")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", code):
            code = "request_rejected"
        journal.acknowledge(key, {"status": status, "data": {"code": code}})
        raise HandoffError("STAFF_WRITE_REJECTED_" + code)
    if not 200 <= status < 300:
        journal.unknown(key, "STAFF_WRITE_OUTCOME_UNKNOWN")
        raise HandoffError("STAFF_WRITE_OUTCOME_UNKNOWN_RECONCILE_SAME_OPERATION")
    # Presigned URL/headers are intentionally never persisted in the journal.
    safe = {k: v for k, v in data.items() if k not in {"upload_url", "required_headers"}}
    journal.acknowledge(key, {"status": status, "data": safe, "etag": response_headers.get("ETag")})
    return {"status": status, "data": data, "etag": response_headers.get("ETag")}


def _finish_private(manifest, staged, transport, journal, prefix, reconcile):
    key = prefix + "attach"
    old = journal.read(key)
    if reconcile and old and old["state"] == "acknowledged":
        # Skip immutable historical observations locally. One explicit invocation
        # performs at most one HTTP replay of the SAME attachment operation.
        index = 1
        while True:
            candidate = prefix + "attach-reconcile:" + str(index)
            observed = journal.read(candidate)
            if observed is None or observed["state"] != "acknowledged":
                key = candidate; break
            index += 1
    result = _call(transport, journal, key,
        "/api/v1/staff/editions/" + staged["edition_id"] + "/production-handoffs",
        {"manifest": manifest, "staging_receipt": staged}, etag=staged["expected_etag"], reconcile=reconcile,
        same_operation=prefix + "attach")["data"]
    verified = set(result.get("verified_asset_ids", []))
    uncertain = []
    for ident in staged["uncertain_uploads_require_provider_verification"]:
        if staged["assets"][ident]["asset_id"] in verified:
            journal.acknowledge(prefix + ident + ":put", {"accepted": True, "reconciled_by_server_ready_asset": True})
        else:
            uncertain.append(ident)
    return {**staged, "state": result["state"], "attachment": result,
        "expected_etag": result.get("current_etag", staged["expected_etag"]),
        "uncertain_uploads_require_provider_verification": uncertain}


def stage_private(manifest, asset_root, transport, journal, *, execute=False, reconcile=False):
    plan = prepare_handoff(manifest, asset_root)
    if not execute:
        return plan
    digest, content = plan["bundle_sha256"], plan["content"]
    prefix = "maison:" + digest + ":"
    scope_key = prefix + "scope"
    scope = journal.read(scope_key)
    if scope is None:
        journal.begin(scope_key, digest); scope = journal.read(scope_key)
    if scope["fingerprint"] != digest or scope["state"] == "unknown":
        raise HandoffError("PRIVATE_HANDOFF_SCOPE_RECONCILIATION_REQUIRED")
    first = scope.get("result")
    if first is None:
        # No HTTP write can precede this local-only scope acknowledgement.
        first = {"started_epoch": scope["started_epoch"]}; journal.acknowledge(scope_key, first)
    if time.time() - first["started_epoch"] > 30 * 86400:
        raise HandoffError("JOURNAL_EXCEEDS_SERVER_RECEIPT_RECONCILIATION_WINDOW")
    saved = journal.read(prefix + "staged")
    if saved and saved["state"] == "acknowledged":
        return _finish_private(manifest, saved["result"], transport, journal, prefix, reconcile)
    if saved and saved["state"] == "unknown":
        raise HandoffError("STAGING_RECEIPT_RECONCILIATION_REQUIRED")

    def draft(*, exact=True):
        review, headers = _get(transport, "/api/v1/staff/editions/" + content["edition_id"] + "/production-handoffs")
        state = review["state"]
        if any(state.get(k) != v for k, v in {"edition_id": content["edition_id"], "edition_revision_id": content["revision_id"], "sha256": content["text_sha256"], "state": "draft"}.items()):
            raise HandoffError("EXACT_DRAFT_REVISION_REQUIRED")
        known = pending = 0
        for item in plan["uploads"]:
            for phase in ("intent", "complete"):
                row = journal.read(prefix + item["id"] + ":" + phase)
                if row:
                    if row["state"] == "acknowledged" and 200 <= row["result"]["status"] < 300:
                        mutation_count = row["result"]["data"]["version"] if phase == "intent" else 1
                        if type(mutation_count) is not int or not 1 <= mutation_count <= 2:
                            raise HandoffError("KNOWN_ASSET_INTENT_MUTATION_COUNT_REQUIRED")
                        known += mutation_count
                    elif row["state"] != "acknowledged":
                        pending += 2 if phase == "intent" and item["body"]["kind"] == "video" else 1
        expected, actual = _version(content["expected_etag"]) + known, _version(headers.get("ETag"))
        if not expected <= actual <= expected + (0 if exact else pending):
            raise HandoffError("REVISION_ETAG_CHANGED_OUTSIDE_JOURNALED_ASSET_MUTATIONS")
        return headers["ETag"]

    draft(exact=False)
    document, _ = _get(transport, "/api/v1/staff/drafts/" + content["revision_id"] + "/document")
    if document.get("edition_revision_id") != content["revision_id"] or document.get("state") != "draft" or document.get("sha256") != content["text_sha256"]:
        raise HandoffError("DRAFT_DOCUMENT_CHANGED")
    units = {u["unit_id"] for u in document["units"]}
    if any(x["body"].get("unit_id") not in units for x in plan["uploads"] if "unit_id" in x["body"]):
        raise HandoffError("UNIT_OUTSIDE_FROZEN_DRAFT")
    assets, uncertain = {}, []
    for item in plan["uploads"]:
        key = prefix + item["id"]
        intent = _call(transport, journal, key + ":intent", "/api/v1/staff/assets/uploads", item["body"], reconcile=reconcile)["data"]
        asset_id = intent["asset_id"]
        current, asset_headers = _get(transport, "/api/v1/staff/assets/" + asset_id)
        if any(current.get(k) != v for k, v in {"edition_revision_id": content["revision_id"], "sha256": item["body"]["sha256"], "bytes": item["body"]["bytes"]}.items()):
            raise HandoffError("ASSET_INTENT_BINDING_MISMATCH")
        put = journal.read(key + ":put")
        if current["state"] == "uploading":
            tus = intent.get("protocol") == "stream_tus"
            if (item["body"]["kind"] == "video") != tus:
                raise HandoffError("VIDEO_REQUIRES_PRIVATE_STREAM_TUS_AUDIO_REQUIRES_R2")
            needs_tus = tus and (not put or put["state"] != "acknowledged")
            if needs_tus and put and not reconcile:
                raise HandoffError("UNKNOWN_TUS_REQUIRES_EXPLICIT_OFFSET_RECONCILIATION")
            if needs_tus or (not tus and not put):
                if "upload_url" not in intent:
                    headers = {"Idempotency-Key": str(uuid.UUID(hex=hashlib.sha256((key + ":intent").encode()).hexdigest()[:32], version=4))}
                    status, intent, _ = transport.request("POST", "/api/v1/staff/assets/uploads", payload=item["body"], headers=headers)
                    if status != 201 or intent.get("asset_id") != asset_id:
                        raise HandoffError("EXISTING_UPLOAD_GRANT_NOT_RECOVERED")
            if needs_tus:
                if intent.get("max_bytes") != item["body"]["bytes"] or not re.fullmatch(r"[a-f0-9]{32}", intent.get("provider_uid", "")):
                    raise HandoffError("EXACT_PRIVATE_TUS_GRANT_REQUIRED")
                if put is None:
                    journal.begin(key + ":put", fingerprint(item["body"]))
                try:
                    proof = transport.upload_tus(intent, Path(asset_root) / item["path"], item["body"]["sha256"],
                        journal=journal, key="maison-tus:" + fingerprint({"bundle": digest, "asset": item["id"]}), reconcile=bool(put))
                    if proof.get("upload_offset") != item["body"]["bytes"] or proof.get("provider_uid") != intent["provider_uid"]:
                        raise HandoffError("TUS_TRANSFER_NOT_COMPLETE")
                except Exception:
                    journal.unknown(key + ":put", "TUS_OFFSET_RECONCILIATION_REQUIRED")
                    raise HandoffError("TUS_OFFSET_RECONCILIATION_REQUIRED") from None
                journal.acknowledge(key + ":put", {"accepted": True, "provider_uid": intent["provider_uid"], "upload_offset": proof["upload_offset"]})
            elif put and put["state"] != "acknowledged":
                if not reconcile:
                    raise HandoffError("UNKNOWN_UPLOAD_REQUIRES_EXPLICIT_RECONCILIATION_NO_REPLAY")
                uncertain.append(item["id"])
            elif not put:
                if intent.get("method") != "PUT" or intent.get("protocol") not in {"r2_put", "local_put"} or intent.get("max_bytes") != item["body"]["bytes"]:
                    raise HandoffError("UNSUPPORTED_BOUNDED_UPLOAD_GRANT")
                journal.begin(key + ":put", fingerprint(item["body"]))
                try:
                    status = transport.put_upload(intent["upload_url"], intent["required_headers"], Path(asset_root) / item["path"])
                    if not 200 <= status < 300:
                        raise HandoffError("UPLOAD_NOT_ACKNOWLEDGED")
                except Exception:
                    journal.unknown(key + ":put", "UPLOAD_OUTCOME_UNKNOWN_NO_REPLAY")
                    raise HandoffError("UPLOAD_OUTCOME_UNKNOWN_NO_REPLAY") from None
                journal.acknowledge(key + ":put", {"accepted": True})
            body = {"bytes": item["body"]["bytes"], "sha256": item["body"]["sha256"]}
            _call(transport, journal, key + ":complete", "/api/v1/staff/assets/" + asset_id + "/complete", body, etag='"v' + str(intent["version"]) + '"', reconcile=reconcile)
            current, asset_headers = _get(transport, "/api/v1/staff/assets/" + asset_id)
        elif current["state"] not in {"ready", "processing"}:
            raise HandoffError("UNEXPECTED_PRIVATE_ASSET_STATE")
        else:
            completion = journal.read(key + ":complete")
            if completion and completion["state"] != "acknowledged":
                _call(transport, journal, key + ":complete", "/api/v1/staff/assets/" + asset_id + "/complete",
                      {"bytes": item["body"]["bytes"], "sha256": item["body"]["sha256"]},
                      etag='"v' + str(intent["version"]) + '"', reconcile=reconcile)
            if put and put["state"] != "acknowledged" and current["state"] == "ready":
                journal.acknowledge(key + ":put", {"accepted": True, "reconciled_by_server_ready_asset": True})
            elif put and put["state"] != "acknowledged":
                uncertain.append(item["id"])
        assets[item["id"]] = current
        draft(exact=False)
    etag = draft()
    staged = {"schema": "earnalism.maison_private_handoff.v1", "state": "DRAFT_ASSETS_STAGED_ATTACHMENT_AND_MEDIA_VERIFICATION_PENDING",
            "bundle_sha256": digest, "edition_id": content["edition_id"], "revision_id": content["revision_id"],
            "text_sha256": content["text_sha256"], "expected_etag": etag, "assets": assets,
            "uncertain_uploads_require_provider_verification": uncertain, "retained_only_assets": plan["retained_only_assets"],
            "publication": False, "ready": False, "rights_approval_created": False}
    old_staged = journal.read(prefix + "staged")
    if old_staged is None:
        journal.begin(prefix + "staged", fingerprint(staged))
    elif old_staged["fingerprint"] != fingerprint(staged):
        raise HandoffError("STAGING_RECEIPT_CHANGED")
    journal.acknowledge(prefix + "staged", staged)
    return _finish_private(manifest, staged, transport, journal, prefix, reconcile)


def measure_mp3(path, *, timeout_seconds=20):
    """Bounded local container measurement, never a speech/listening assessment."""
    import math
    import subprocess
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
            "format=duration:stream=codec_name,codec_type,bit_rate,channels", "-of", "json", str(Path(path).resolve())],
            capture_output=True, check=True, timeout=max(.1, min(20, timeout_seconds)))
        if len(result.stdout) > 65536:
            raise ValueError
        measured = json.loads(result.stdout)
        streams = measured["streams"]
        if len(streams) != 1 or streams[0].get("codec_name") != "mp3" or streams[0].get("codec_type") != "audio":
            raise ValueError
        duration = float(measured["format"]["duration"])
        bitrate = int(streams[0]["bit_rate"])
        # 48 and 96 kbps as before; 64 kbps is the audiobook rendition and must be mono.
        if (not math.isfinite(duration) or duration <= 0
                or not (bitrate in {48000, 96000} or (bitrate == 64000 and streams[0].get("channels") == 1))):
            raise ValueError
    except Exception:
        raise HandoffError("EXACT_MEASURED_48_96_OR_64_MONO_KBPS_MP3_REQUIRED") from None
    return {"duration_ms": round(duration * 1000), "quality_kbps": bitrate // 1000,
            "measurement_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "method": "ffprobe exact retained MP3; container metadata only, not listening QA"}


def attach_private(manifest, asset_root, staged, actor, expected_etag, operation_id, *, execute=False, measure=measure_mp3):
    """Server-side attachment using existing models/receipts, always draft.

Provider verification remains the existing verify_media_asset command. Source
alignment evidence is retained and geometrically checked, never inferred here.
"""
    plan = prepare_handoff(manifest, asset_root)
    if not execute:
        return {**plan, "state": "PREPARED_ATTACHMENT_EXECUTION_DISABLED"}
    return _attach_verified(manifest, asset_root, staged, actor, expected_etag, operation_id,
        plan=plan, measure=measure, source_scope="ALL_LOCAL_BUNDLE_ASSETS_HASH_VERIFIED")


def _attach_verified(manifest, asset_root, staged, actor, expected_etag, operation_id, *, plan, measure, source_scope):
    from core.api import DomainError
    from core.services import apply_operation, audit
    from .models import Asset, Edition, Revision, TimingMap
    from .services import prepared_audio
    from .timing import validated_segments
    from .audio_chapters import validate_chapters
    from .intake_api import staff_permission
    staff_permission(actor)
    if not actor.is_verified:
        raise DomainError("email_verification_required", "A verified publisher is required.", 403)
    content, digest = manifest["content"], plan["bundle_sha256"]
    if (staged.get("schema") != "earnalism.maison_private_handoff.v1"
        or staged.get("bundle_sha256") != digest or staged.get("revision_id") != content["revision_id"]
        or staged.get("edition_id") != content["edition_id"] or staged.get("text_sha256") != content["text_sha256"]):
        raise HandoffError("STAGING_RECEIPT_DOES_NOT_BIND_BUNDLE")
    if set(staged.get("assets", {})) != {x["id"] for x in plan["uploads"]}:
        raise HandoffError("EXACT_STAGED_ASSET_SET_REQUIRED")
    version = _version(expected_etag)
    by_id = {x["id"]: x for x in manifest["assets"]}
    measurements = {}
    for item in manifest["assets"]:
        if item["role"] == "audio":
            native = by_id.get(item.get("native_wav"))
            if not native or native["role"] != "native_audio" or native["content_type"] not in {"audio/wav", "audio/x-wav"}:
                raise HandoffError("RETAINED_NATIVE_WAV_PROVENANCE_REQUIRED")
            proof = measure(Path(asset_root) / item["path"])
            if proof["duration_ms"] != item.get("duration_ms"):
                raise HandoffError("MEASURED_MP3_DURATION_DIFFERS_FROM_BUNDLE")
            native_proof = {k: native[k] for k in ("id", "path", "bytes", "sha256")}
            native_proof["byte_verification"] = "LOCAL_BUNDLE_HASH_VERIFIED" if source_scope == "ALL_LOCAL_BUNDLE_ASSETS_HASH_VERIFIED" else "SOURCE_PROVENANCE_REFERENCE_ONLY_NOT_SERVER_VERIFIED"
            measurements[item["id"]] = {**proof, "native_wav": native_proof}
    map_id = manifest["evidence"].get("measured_maps")
    maps = []
    if map_id:
        item = by_id[map_id]
        if item["role"] != "timing_map":
            raise HandoffError("MEASURED_MAP_ROLE_REQUIRED")
        mapping = json.loads((Path(asset_root) / item["path"]).read_bytes())
        if (mapping.get("schema") != "earnalism.measured_audio_maps.v1"
            or mapping.get("edition_revision_id") != content["revision_id"]
            or mapping.get("text_sha256") != content["text_sha256"] or not isinstance(mapping.get("maps"), list)):
            raise HandoffError("MEASURED_MAP_SOURCE_BINDING_REQUIRED")
        maps = mapping["maps"]
    if measurements and (len(maps) != len(measurements) or {row.get("audio_asset_id") for row in maps} != set(measurements)):
        raise HandoffError("ONE_COMPLETE_MEASURED_MAP_PER_AUDIO_REQUIRED")

    def attach():
        edition = Edition.objects.select_for_update().get(pk=content["edition_id"])
        revision = Revision.objects.select_for_update().get(pk=content["revision_id"], edition=edition)
        if revision.state != "draft" or revision.version != version or revision.content_sha256 != content["text_sha256"]:
            raise DomainError("version_conflict", "Exact draft revision/ETag/hash required.", 412)
        evidence = dict(revision.validation_evidence)
        history = dict(evidence.get("production_handoffs", {}))
        if digest in history:
            raise DomainError("already_attached", "Preserve the existing attachment; reconcile its operation receipt.", 409)
        stored = {}
        for item in plan["uploads"]:
            receipt = staged.get("assets", {}).get(item["id"], {})
            asset = Asset.objects.select_for_update(of=("self",)).select_related("unit").filter(pk=receipt.get("asset_id"), revision=revision).first()
            body = item["body"]
            if (not asset or asset.sha256 != body["sha256"] or asset.bytes != body["bytes"]
                or receipt.get("sha256") != body["sha256"] or receipt.get("bytes") != body["bytes"]
                or receipt.get("edition_revision_id") != content["revision_id"]
                or asset.content_type != body["content_type"]
                or asset.provider != ("stream" if body["kind"] == "video" else "r2")
                or asset.kind != ("audio_chapter" if body["kind"] == "audio" else body["kind"])
                or str(asset.unit_id) != str(body.get("unit_id"))
                or asset.state not in ({"processing", "ready"} if body["kind"] in {"audio", "video"} else {"ready"})):
                raise DomainError("asset_integrity_failed", "Exact completed private asset binding required.", 409)
            stored[item["id"]] = asset
        media = dict(evidence.get("media_assets", {}))
        for item_id, proof in measurements.items():
            asset = stored[item_id]; item = by_id[item_id]
            if asset.provider != "r2" or not asset.unit_id or asset.duration_ms != proof["duration_ms"]:
                raise DomainError("media_not_ready", "Exact R2 MP3 unit/duration required.", 409)
            if asset.unit.duration_ms not in (None, proof["duration_ms"]):
                raise DomainError("unit_revision_mismatch", "Unit already binds a different duration.", 409)
            if asset.unit.duration_ms is None:
                asset.unit.duration_ms = proof["duration_ms"]; asset.unit.save()
            value = {"sha256": asset.sha256, "unit_id": str(asset.unit_id), "duration_ms": proof["duration_ms"],
                "quality_kbps": proof["quality_kbps"], "prepared": True,
                "measurement_evidence": "production_bundle:" + digest + "/ffprobe:" + proof["measurement_sha256"],
                "native_wav": proof["native_wav"], "actual_listening": False}
            if str(asset.id) in media and media[str(asset.id)] != value:
                raise DomainError("evidence_conflict", "Preserve existing media evidence; do not replace it.", 409)
            media[str(asset.id)] = value
        evidence["media_assets"] = media
        revision.validation_evidence = evidence
        map_ids = []
        for row in maps:
            if row.get("measured") is not True or not isinstance(row.get("measurement_evidence_ref"), str) or not row["measurement_evidence_ref"].strip():
                raise HandoffError("ACTUAL_ALIGNMENT_EVIDENCE_REFERENCE_REQUIRED")
            asset = stored.get(row["audio_asset_id"])
            if asset is None or row.get("precision") not in {"paragraph", "sentence"}:
                raise HandoffError("MEASURED_MAP_AUDIO_AND_PRECISION_REQUIRED")
            asset.revision = revision
            asset.state = "ready"  # In-memory geometry validation only; never saved as ready.
            chapters = row.get("chapters", [])
            if not isinstance(chapters, list) or (chapters and validate_chapters(chapters, measurements[row["audio_asset_id"]]["duration_ms"])):
                raise HandoffError("MEASURED_MAP_CHAPTERS_INVALID")
            mapping = TimingMap(revision=revision, asset=asset, text_sha256=revision.content_sha256,
                asset_sha256=asset.sha256, precision=row["precision"], measured=True, segments=row["segments"], chapters=chapters)
            mapping.full_clean(); prepared_audio(asset); validated_segments(mapping)
            mapping.save(); map_ids.append(str(mapping.id))
        history[digest] = {"schema": "earnalism.attached_production_bundle.v1", "assets": staged["assets"],
            "source_byte_verification_scope": source_scope,
            "source_assets": manifest["assets"], "evidence_references": manifest["evidence"],
            "uncertain_uploads_require_provider_verification": staged.get("uncertain_uploads_require_provider_verification", []),
            "timing_map_ids": map_ids, "actual_listening": False, "rights_approval_created": False,
            "publication": False, "source_alignment_is_supplied_evidence_not_independent_listening": True}
        evidence["production_handoffs"] = history
        revision.validation_evidence = evidence; revision.save(); revision.refresh_from_db()
        audit(actor, "content.production_handoff", revision, {"bundle_sha256": digest, "timing_map_ids": map_ids})
        return 200, {"state": "DRAFT_ATTACHED_MEDIA_VERIFICATION_PENDING", "bundle_sha256": digest,
            "edition_id": str(edition.id), "revision_id": str(revision.id), "expected_etag": '"v' + str(revision.version) + '"',
            "timing_map_ids": map_ids, "verify_media_asset_ids": [str(stored[x["id"]].id) for x in manifest["assets"] if x["role"] in {"audio", "video"}],
            "rights_approval_created": False, "publication": False, "ready": False}, revision.version

    payload = {"bundle_sha256": digest, "staging_receipt_sha256": fingerprint(staged), "expected_etag": expected_etag}
    # Existing actor fencing, operation receipt and local CAS; no provider IO under locks.
    _, result = apply_operation(actor, operation_id, "content.production_handoff", payload, attach)
    return result
