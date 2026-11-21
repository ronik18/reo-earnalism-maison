"""Private Stream TUS byte transfer; no creation, publication or credential discovery.

The trusted Maison backend creates the direct-user TUS Location with
`requiresignedurls` in its FIRST Upload-Metadata request and retains the UID
from stream-media-id. Later upload metadata cannot make a public upload private.
This client receives that existing capability in memory only. Transfer completion
does not prove processing, signed playback, rights, listening or publication QA.

Official protocols checked 2026-11-21:
https://developers.cloudflare.com/stream/uploading-videos/direct-creator-uploads/
https://developers.cloudflare.com/stream/uploading-videos/resumable-uploads/
https://tus.io/protocols/resumable-upload.html
"""
import base64
import hashlib
import http.client
import json
from pathlib import Path
import re
import ssl
from urllib.parse import urlsplit

from operations.social_delivery.http import FileSlice, Response, _LimitedFile

CHUNK = 50 * 1024 * 1024
UID = re.compile(r'[a-f0-9]{32}\Z')
HEX = re.compile(r'[a-f0-9]{64}\Z')


class StreamDeliveryError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _target(url):
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in url):
        raise StreamDeliveryError('TRUSTED_STREAM_TUS_CAPABILITY_REQUIRED')
    target = urlsplit(url)
    if (target.scheme != 'https' or target.netloc != 'upload.videodelivery.net'
            or target.username or target.password or target.fragment or not target.path or target.path == '/'):
        raise StreamDeliveryError('EXACT_STREAM_DIRECT_UPLOAD_ORIGIN_REQUIRED')
    return target


def _headers(required_headers):
    if not isinstance(required_headers, dict):
        raise StreamDeliveryError('EXACT_TUS_HEADERS_REQUIRED')
    result = {}
    for key, value in required_headers.items():
        if not isinstance(key, str) or not isinstance(value, str) or any(c in key + value for c in '\r\n'):
            raise StreamDeliveryError('EXACT_TUS_HEADERS_REQUIRED')
        key = key.lower()
        if key in result or key not in {'tus-resumable', 'content-type'}:
            raise StreamDeliveryError('NO_API_CREDENTIALS_OR_HEADER_OVERRIDES_ALLOWED')
        result[key] = value
    if result.get('tus-resumable') != '1.0.0' or result.get('content-type', 'application/offset+octet-stream') != 'application/offset+octet-stream':
        raise StreamDeliveryError('TUS_1_0_0_OFFSET_STREAM_REQUIRED')
    return {'Tus-Resumable': '1.0.0'}


def _hash(path, offset=0, length=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        stream.seek(offset)
        while length is None or length:
            block = stream.read(4 * 1024 * 1024 if length is None else min(length, 4 * 1024 * 1024))
            if not block:
                if length: raise StreamDeliveryError('SOURCE_SHORTER_THAN_BOUND_BYTES')
                break
            digest.update(block)
            if length is not None: length -= len(block)
    return digest.hexdigest()


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class TUSHTTPSClient:
    """Exact Stream upload origin, streaming bodies, bounded replies, no redirects/retries."""
    def request(self, method, url, *, headers, body=None):
        target = _target(url)
        if method not in {'OPTIONS', 'HEAD', 'PATCH'}:
            raise StreamDeliveryError('TUS_CLIENT_NEVER_CREATES_OR_PUBLISHES')
        if any(not re.fullmatch(r'[A-Za-z0-9-]+', k) or not isinstance(v, str)
               or any(c in k + v for c in '\r\n') for k, v in headers.items()):
            raise StreamDeliveryError('SAFE_TUS_HEADERS_REQUIRED')
        if any(k.lower() in {'authorization', 'cookie', 'host', 'proxy-authorization',
                'transfer-encoding', 'content-length'} for k in headers):
            raise StreamDeliveryError('NO_API_CREDENTIALS_OR_HEADER_OVERRIDES_ALLOWED')
        headers = dict(headers)
        source = None
        if body is not None:
            if not isinstance(body, FileSlice) or body.offset < 0 or body.length < 1:
                raise StreamDeliveryError('BOUND_STREAMING_FILE_SLICE_REQUIRED')
            headers['Content-Length'] = str(body.length)
            source = _LimitedFile(body)
        connection = http.client.HTTPSConnection(target.hostname, timeout=180, context=ssl.create_default_context())
        try:
            connection.request(method, target.path + ('?' + target.query if target.query else ''), headers=headers, body=source)
            response = connection.getresponse()
            if len(response.read(65537)) > 65536:
                raise StreamDeliveryError('TUS_REPLY_TOO_LARGE')
            return Response(response.status, {k.lower(): v for k, v in response.getheaders()}, {})
        finally:
            if source is not None: source.close()
            connection.close()


def upload_private_video(url, required_headers, path, expected_bytes, expected_sha256,
                         *, http=None, journal=None, key=None, execute=False,
                         reconcile=False, provider_uid=None):
    """Upload an existing trusted private TUS intent, inert unless execute=True.

    Only trusted staff orchestration may supply the intent/execute flag. This is
    not an owner-approval endpoint. No API token is accepted. Reconcile explicitly
    authorizes HEAD-based resolution of an uncertain prefix before another PATCH;
    no transport retry or new upload creation occurs. A missing/lost capability
    is a hold, never permission to request a fresh duplicate upload.
    """
    _target(url)
    headers = _headers(required_headers)
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or type(expected_bytes) is not int or not 0 < expected_bytes <= 10 * 1024**3
            or not isinstance(expected_sha256, str) or not HEX.fullmatch(expected_sha256)
            or path.stat().st_size != expected_bytes or _hash(path) != expected_sha256):
        raise StreamDeliveryError('EXACT_LOCAL_SOURCE_BYTES_REQUIRED')
    if provider_uid is not None and (not isinstance(provider_uid, str) or not UID.fullmatch(provider_uid)):
        raise StreamDeliveryError('EXACT_STREAM_UID_REQUIRED')
    if not execute:
        return {'state': 'PREPARED_NO_PROVIDER_REQUESTS', 'bytes': expected_bytes,
                'sha256': expected_sha256, 'provider_uid': provider_uid, 'provider_requests': 0}
    if journal is None or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,180}', key):
        raise StreamDeliveryError('DURABLE_BOUND_UPLOAD_JOURNAL_REQUIRED')
    client = http or TUSHTTPSClient()
    binding = {'bytes': expected_bytes, 'sha256': expected_sha256, 'provider_uid': provider_uid,
               'endpoint_fingerprint': hashlib.sha256(url.encode()).hexdigest()}
    source_key = key + ':source'
    if journal.begin(source_key, _fingerprint(binding)) is None:
        journal.acknowledge(source_key, {'state': 'LOCAL_STREAM_SOURCE_BOUND', 'bytes': expected_bytes,
                                      'sha256': expected_sha256, 'provider_uid': provider_uid})
    count = 0
    def request(method, *, extra=None, body=None):
        nonlocal count
        count += 1
        try:
            return client.request(method, url, headers={**headers, **(extra or {})}, body=body)
        except Exception:
            raise StreamDeliveryError('STREAM_REQUEST_OUTCOME_UNKNOWN') from None
    def numeric(value):
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,12}', value):
            raise StreamDeliveryError('EXACT_TUS_OFFSET_AND_LENGTH_REQUIRED')
        return int(value)
    # Checksum is an optional TUS extension, not an assumed Cloudflare guarantee.
    options = request('OPTIONS')
    if options.status not in (200, 204):
        raise StreamDeliveryError('TUS_CAPABILITIES_UNRESOLVED_NO_PATCH')
    extensions = {x.strip() for x in options.headers.get('tus-extension', '').split(',')}
    algorithms = {x.strip() for x in options.headers.get('tus-checksum-algorithm', '').split(',')}
    checksum = 'checksum' in extensions and 'sha256' in algorithms
    head = request('HEAD')
    if head.status not in (200, 204) or head.headers.get('tus-resumable') != '1.0.0':
        raise StreamDeliveryError('TUS_HEAD_STATUS_UNRESOLVED_NO_PATCH')
    offset = numeric(head.headers.get('upload-offset'))
    if numeric(head.headers.get('upload-length')) != expected_bytes or not 0 <= offset <= expected_bytes:
        raise StreamDeliveryError('TUS_REMOTE_LENGTH_OR_OFFSET_MISMATCH')
    observed_uid = head.headers.get('stream-media-id')
    if observed_uid is not None and (not UID.fullmatch(observed_uid) or provider_uid not in (None, observed_uid)):
        raise StreamDeliveryError('TUS_PROVIDER_UID_MISMATCH')
    uid = provider_uid or observed_uid
    if uid is None:
        raise StreamDeliveryError('TRUSTED_OR_HEADER_STREAM_UID_REQUIRED')

    def entry(start, attempt):
        operation = key + ':patch:' + str(start) + ':' + str(attempt)
        length = min(CHUNK, expected_bytes - start)
        intent = {**binding, 'from_offset': start, 'length': length, 'chunk_sha256': _hash(path, start, length)}
        return operation, length, _fingerprint(intent)

    # Walk only retained intents/acknowledgements: an unexplained remote prefix
    # must never be adopted merely because its length looks plausible.
    cursor = 0
    while cursor < offset:
        attempt = 0
        while True:
            operation, length, digest = entry(cursor, attempt)
            record = journal.read(operation)
            if record is None or record['fingerprint'] != digest:
                raise StreamDeliveryError('UNATTRIBUTED_REMOTE_PREFIX_REQUIRES_RECONCILIATION')
            if record['state'] == 'acknowledged':
                following = record['result'].get('next_offset')
                if type(following) is not int or not cursor <= following <= cursor + length or following > offset:
                    raise StreamDeliveryError('REMOTE_PREFIX_CONFLICTS_WITH_RETAINED_ACK')
                if following == cursor:
                    attempt += 1
                    continue
                cursor = following
                break
            if not reconcile:
                raise StreamDeliveryError('UNCERTAIN_PATCH_REQUIRES_EXPLICIT_RECONCILIATION')
            following = min(offset, cursor + length)
            journal.acknowledge(operation, {'state': 'TUS_PATCH_RECONCILED_FROM_HEAD', 'from_offset': cursor,
                'next_offset': following, 'provider_uid': uid, 'provider_digest_verified': False})
            cursor = following
            break
    while cursor < expected_bytes:
        attempt = 0
        while True:
            operation, length, digest = entry(cursor, attempt)
            record = journal.read(operation)
            if record is None:
                break
            if record['fingerprint'] != digest:
                raise StreamDeliveryError('TUS_PATCH_SOURCE_BINDING_CHANGED')
            if record['state'] != 'acknowledged':
                if not reconcile:
                    raise StreamDeliveryError('UNCERTAIN_PATCH_REQUIRES_EXPLICIT_RECONCILIATION')
                # HEAD proves no bytes from this intent were committed. Preserve
                # that result, then use a distinct, explicit recovery intent.
                journal.acknowledge(operation, {'state': 'TUS_PATCH_NO_BYTES_COMMITTED_HEAD_OBSERVED',
                    'from_offset': cursor, 'next_offset': cursor, 'provider_uid': uid})
            if record['state'] == 'acknowledged' and record['result'].get('next_offset') != cursor:
                raise StreamDeliveryError('REMOTE_OFFSET_REGRESSED_BEHIND_RETAINED_ACK')
            attempt += 1
        if journal.begin(operation, digest) is not None:
            raise StreamDeliveryError('CONCURRENT_PATCH_CHANGED_OFFSET_RECONCILE_BEFORE_DISPATCH')
        patch_headers = {'Content-Type': 'application/offset+octet-stream', 'Upload-Offset': str(cursor)}
        if checksum:
            patch_headers['Upload-Checksum'] = 'sha256 ' + base64.b64encode(bytes.fromhex(_hash(path, cursor, length))).decode()
        try:
            response = request('PATCH', extra=patch_headers, body=FileSlice(path, cursor, length))
            if (response.status != 204 or response.headers.get('tus-resumable') != '1.0.0'
                    or numeric(response.headers.get('upload-offset')) != cursor + length):
                raise StreamDeliveryError('TUS_PATCH_ACKNOWLEDGEMENT_UNRESOLVED')
            journal.acknowledge(operation, {'state': 'TUS_PATCH_ACKNOWLEDGED', 'from_offset': cursor,
                'next_offset': cursor + length, 'provider_uid': uid, 'provider_digest_verified': checksum})
        except Exception as exc:
            code = exc.code if isinstance(exc, StreamDeliveryError) else 'STREAM_PATCH_OUTCOME_UNKNOWN'
            journal.unknown(operation, code)
            raise StreamDeliveryError(code) from None
        cursor += length
    if path.stat().st_size != expected_bytes or _hash(path) != expected_sha256:
        raise StreamDeliveryError('SOURCE_CHANGED_DURING_STREAM_TRANSFER')
    return {'state': 'TUS_BYTES_TRANSFERRED_PROCESSING_UNASSESSED', 'provider_uid': uid,
        'bytes': expected_bytes, 'sha256': expected_sha256, 'upload_offset': cursor,
        'provider_requests': count, 'privacy_verified_by_client': False,
        'provider_rendition_sha256_verified': False, 'publication_performed': False}
