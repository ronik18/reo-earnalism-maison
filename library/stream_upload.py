"""Draft-only private Stream TUS intent; no provider I/O inside DB transactions.

Existing staff/MFA views call this helper. A blocked outbox row records one
creation attempt before HTTP; an unknown result cannot allocate another video.
The short-lived Location is AES-GCM encrypted with a purpose-derived existing
SECRET_KEY. General receipts, audit events and job payloads contain no capability.
Official protocol: https://developers.cloudflare.com/stream/uploading-videos/direct-creator-uploads/
and https://developers.cloudflare.com/stream/uploading-videos/resumable-uploads/.
"""
import base64
from datetime import timedelta
import http.client
import json
import os
from pathlib import PurePath
import re
import ssl
import time
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.api import DomainError, public_uuid
from core.models import OutboxJob
from core.services import apply_operation, audit, locked_actor, payload_hash
from operations.stream_delivery import _target
from .models import Asset, Revision, Unit
from .services import iso
from . import stream

KIND = 'stream_upload_intent'
PURPOSE = b'maison.private-stream-tus-grant.v1'


def _error(code='stream_upload_reconciliation_required', status=409):
    return DomainError(code, 'The private Stream upload requires its retained intent and reconciliation; no new allocation was attempted.', status)


def _publisher(actor):
    if not actor.is_active or not actor.is_staff or not actor.is_verified or not actor.has_perm('library.publish_revision'):
        raise DomainError('permission_denied', 'Verified content publisher permission is required.', 403)


def _matches(asset, data):
    return (str(asset.revision_id) == data['edition_revision_id'] and str(asset.unit_id) == data['unit_id']
        and asset.kind == 'video' and asset.content_type == 'video/mp4'
        and asset.sha256 == data['sha256'] and asset.bytes == data['bytes'] and asset.duration_ms == data['duration_ms']
        and Unit.objects.filter(pk=asset.unit_id, revision_id=asset.revision_id, duration_ms=asset.duration_ms).exists())


def _input(data):
    fields = {'edition_revision_id', 'kind', 'file_name', 'content_type', 'bytes', 'sha256', 'unit_id', 'duration_ms'}
    if not isinstance(data, dict) or set(data) != fields:
        raise DomainError('validation_error', 'Video requires its complete draft, unit, source and measured duration.', 422)
    result = dict(data)
    for field in ('edition_revision_id', 'unit_id'): result[field] = str(public_uuid(result[field], field))
    name = result['file_name']
    if (result['kind'] != 'video' or result['content_type'] != 'video/mp4'
            or type(result['bytes']) is not int or not 0 < result['bytes'] <= 10 * 1024**3
            or type(result['duration_ms']) is not int or not 0 < result['duration_ms'] <= 9223372036854775807
            or not isinstance(result['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', result['sha256'])
            or not isinstance(name, str) or not 1 <= len(name) <= 255 or any(c in name for c in '/\\')
            or any(ord(c) < 32 for c in name) or PurePath(name).suffix.lower() != '.mp4'):
        raise DomainError('validation_error', 'Use a bound MP4 source up to ten GiB with positive measured duration.', 422)
    return result


def _aad(job, kind):
    return json.dumps({'purpose': PURPOSE.decode(), 'kind': kind, 'actor': str(job.actor_id),
        'asset': job.payload['asset_id'], 'request': job.payload['request_sha256'],
        'expires_at': job.result['expires_at']}, sort_keys=True, separators=(',', ':')).encode()


def _cipher():
    secret = settings.SECRET_KEY
    if not isinstance(secret, str) or len(secret) < 40:
        raise _error('stream_upload_encryption_unavailable', 503)
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=PURPOSE).derive(secret.encode())
    return AESGCM(derived)


def _seal(job, value, kind):
    nonce = os.urandom(12)
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return {'nonce': base64.b64encode(nonce).decode(),
            'ciphertext': base64.b64encode(_cipher().encrypt(nonce, raw, _aad(job, kind))).decode(),
            'encrypted_payload_kind': kind}


def _open(job, kind):
    try:
        if job.result.get('encrypted_payload_kind') != kind: raise ValueError
        raw = _cipher().decrypt(base64.b64decode(job.result['nonce'], validate=True),
            base64.b64decode(job.result['ciphertext'], validate=True), _aad(job, kind))
        value = json.loads(raw)
        if not isinstance(value, dict): raise ValueError
        return value
    except Exception:
        raise _error('stream_upload_grant_unavailable') from None


def _create_provider_upload(asset, expiry):
    """One authenticated creation POST; only this backend sees the API token."""
    if connection.in_atomic_block: raise _error('stream_upload_transaction_scope', 500)
    account, token, _ = stream._account_config()
    metadata = [('name', str(asset.id)), ('maxDurationSeconds', str((asset.duration_ms + 999) // 1000)), ('expiry', iso(expiry))]
    encoded = ','.join(k + ' ' + base64.b64encode(v.encode()).decode() for k, v in metadata) + ',requiresignedurls'
    deadline = time.monotonic() + 8
    client = http.client.HTTPSConnection(stream.API_HOST, timeout=3, context=ssl.create_default_context())
    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0: raise TimeoutError
        if client.sock is not None: client.sock.settimeout(seconds)
    try:
        client.connect(); remaining()
        client.request('POST', f'/client/v4/accounts/{account}/stream?direct_user=true', body=b'',
            headers={'Authorization': 'Bearer ' + token, 'Tus-Resumable': '1.0.0',
                     'Upload-Length': str(asset.bytes), 'Upload-Metadata': encoded})
        remaining(); response = client.getresponse()
        location, uid = response.getheader('Location'), response.getheader('stream-media-id')
        remaining()
        if response.status != 201 or not isinstance(uid, str) or not stream.UID.fullmatch(uid): raise ValueError
        _target(location)
        if len(response.read(65537)) > 65536: raise ValueError
        remaining()
        return {'upload_url': location, 'provider_uid': uid}
    except Exception:
        raise _error('stream_upload_outcome_unknown', 503) from None
    finally:
        client.close()


def _phase(job_id, phase, *, code='', update=None):
    with transaction.atomic():
        job = OutboxJob.objects.select_for_update().get(pk=job_id)
        job.payload = {**job.payload, 'phase': phase}; job.error_code = code
        if update: job.result = {**job.result, **update}
        job.save(update_fields=['payload', 'error_code', 'result'])
    return job


def verify_private_upload_association(actor, asset, *, source_bytes=None, source_sha256=None):
    """Pure DB/source association for completion; never a provider SHA or QA verdict.

    The existing completion transaction fences actor/asset mutation. A grant may
    expire after its private upload finished; its retained verified association
    remains usable without minting another capability or requiring a live URL.
    """
    _publisher(get_user_model().objects.get(pk=actor.pk))
    if ((source_bytes is not None and source_bytes != asset.bytes)
            or (source_sha256 is not None and source_sha256 != asset.sha256)):
        raise DomainError('upload_integrity_failed', 'Completion source differs from the retained upload intent.', 422)
    data = {'edition_revision_id': str(asset.revision_id), 'unit_id': str(asset.unit_id),
            'sha256': asset.sha256, 'bytes': asset.bytes, 'duration_ms': asset.duration_ms}
    if (asset.provider != 'stream' or not stream.UID.fullmatch(asset.storage_key)
            or asset.revision.state != 'draft' or not _matches(asset, data)):
        raise _error('stream_upload_source_association_unverified')
    job = OutboxJob.objects.filter(kind=KIND, actor_id=actor.pk, payload__asset_id=str(asset.id)).first()
    if (job is None or job.result.get('private_metadata_verified') is not True
            or job.result.get('provider_uid') != asset.storage_key
            or job.result.get('source_sha256') != asset.sha256 or job.result.get('source_bytes') != asset.bytes
            or job.payload.get('source_sha256') != asset.sha256 or job.payload.get('source_bytes') != asset.bytes):
        raise _error('stream_upload_source_association_unverified')
    return {'stream_upload_intent_id': str(job.id), 'provider_uid': asset.storage_key,
        'source_sha256': asset.sha256, 'source_bytes': asset.bytes, 'unit_id': str(asset.unit_id),
        'duration_ms': asset.duration_ms, 'private_metadata_verified': True,
        'source_upload_association_verified': True, 'provider_rendition_sha256_verified': False}


def create_private_upload(actor, data, operation):
    """Return (201, same short-lived private TUS grant), or a named safe hold.

    Reservation receipt and blocked outbox intent are committed before HTTP.
    Replays reuse encrypted capability until its original expiry and never
    repeat a creation POST. Metadata verification accepts an uploading private
    UID; normal completion separately verifies processing and measured duration.
    """
    if connection.in_atomic_block: raise _error('stream_upload_transaction_scope', 500)
    _publisher(get_user_model().objects.get(pk=actor.pk))
    data = _input(data); operation = public_uuid(operation, 'operation_id')
    request_hash = payload_hash('asset.upload', data)
    dedupe = f'stream-upload:{actor.pk}:{operation}'
    # Validate existing configuration/encryption locally before reserving an intent.
    stream._account_config(); _cipher()
    def reserve():
        _publisher(get_user_model().objects.get(pk=actor.pk))
        old = OutboxJob.objects.select_for_update().filter(dedupe_key=dedupe).first()
        if old:
            if old.actor_id != actor.pk or old.payload.get('request_sha256') != request_hash:
                raise DomainError('idempotency_key_reused', 'Upload identity already has different input.', 409)
            return 201, {'asset_id': old.payload['asset_id'], 'state': 'reserved'}, 1
        revision = Revision.objects.select_for_update().filter(pk=data['edition_revision_id']).first()
        if revision is None: raise DomainError('not_found', 'Draft revision not found.', 404)
        if revision.state != 'draft': raise DomainError('revision_frozen', 'Upload only into a draft revision.', 409)
        unit = Unit.objects.filter(pk=data['unit_id'], revision=revision, duration_ms=data['duration_ms']).first()
        if unit is None: raise DomainError('unit_revision_mismatch', 'The exact draft unit and measured video duration must match.', 409)
        ident = uuid.uuid4()
        asset = Asset.objects.create(id=ident, revision=revision, unit=unit, kind='video', provider='r2',
            storage_key=f'revisions/{revision.id}/{ident}/pending-stream', sha256=data['sha256'],
            bytes=data['bytes'], duration_ms=data['duration_ms'], content_type='video/mp4')
        OutboxJob.objects.create(kind=KIND, dedupe_key=dedupe, actor=actor, status='blocked', not_before=timezone.now(),
            payload={'asset_id': str(ident), 'operation_id': str(operation), 'request_sha256': request_hash,
                     'phase': 'reserved', 'source_sha256': data['sha256'], 'source_bytes': data['bytes']})
        audit(actor, 'asset.stream_upload_reserved', asset, {'source_sha256': asset.sha256, 'source_bytes': asset.bytes})
        return 201, {'asset_id': str(ident), 'state': 'reserved'}, asset.version
    _, reserved = apply_operation(actor, operation, 'asset.upload', data, reserve)
    with transaction.atomic():
        _publisher(locked_actor(actor))
        job = OutboxJob.objects.select_for_update().get(dedupe_key=dedupe)
        if job.payload.get('request_sha256') != request_hash or job.payload['asset_id'] != reserved['asset_id']:
            raise DomainError('idempotency_key_reused', 'Upload identity already has different input.', 409)
        asset = Asset.objects.select_for_update().select_related('revision').get(pk=reserved['asset_id'])
        revision = Revision.objects.select_for_update().get(pk=asset.revision_id)
        if revision.state != 'draft' or asset.state != 'uploading' or not _matches(asset, data):
            raise _error('stream_upload_draft_changed')
        phase = job.payload['phase']
        if phase == 'reserved':
            expiry = timezone.now() + timedelta(seconds=120)
            job.payload = {**job.payload, 'phase': 'submitting'}
            job.result = {'expires_at': iso(expiry)}; job.attempts = 1
            job.save(update_fields=['payload', 'result', 'attempts'])
        else:
            expiry = parse_datetime(job.result.get('expires_at', ''))
    if phase in {'submitting', 'unknown', 'expired', 'privacy_failed', 'orphaned_private_provider_ack'}:
        raise _error('stream_upload_grant_expired' if phase == 'expired' else 'stream_upload_reconciliation_required')
    if expiry is None or expiry <= timezone.now():
        _phase(job.id, 'expired', code='stream_upload_grant_expired')
        raise _error('stream_upload_grant_expired')
    if phase == 'reserved':
        try:
            capability = _create_provider_upload(asset, expiry)
            # Durable provider acknowledgement precedes metadata/asset mutation.
            job.result = {**job.result, 'provider_uid': capability['provider_uid']}
            sealed = _seal(job, capability, 'capability')
            job = _phase(job.id, 'provider_ack', update={'provider_uid': capability['provider_uid'], **sealed})
            phase = 'provider_ack'
        except Exception:
            _phase(job.id, 'unknown', code='stream_upload_outcome_unknown')
            raise _error('stream_upload_outcome_unknown', 503) from None
    if phase == 'provider_ack':
        capability = _open(job, 'capability')
        with transaction.atomic():
            _publisher(locked_actor(actor))
            current = OutboxJob.objects.select_for_update().get(pk=job.id)
            asset = Asset.objects.select_for_update().select_related('revision').get(pk=asset.id)
            revision = Revision.objects.select_for_update().get(pk=asset.revision_id)
            if current.payload.get('phase') in {'privacy_pending', 'grant_ready'}:
                job = current; phase = current.payload['phase']
            elif current.payload.get('phase') != 'provider_ack':
                raise _error()
            elif revision.state != 'draft' or asset.state != 'uploading' or not _matches(asset, data):
                current.payload = {**current.payload, 'phase': 'orphaned_private_provider_ack'}
                current.error_code = 'stream_upload_draft_changed'; current.save(update_fields=['payload', 'error_code'])
                phase = 'orphaned_private_provider_ack'
            else:
                asset.provider = 'stream'; asset.storage_key = capability['provider_uid']; asset.version += 1; asset.save()
                grant = {'asset_id': str(asset.id), 'version': asset.version, 'protocol': 'stream_tus', 'method': 'PATCH',
                    'upload_url': capability['upload_url'], 'required_headers': {'Tus-Resumable': '1.0.0'},
                    'expires_at': current.result['expires_at'], 'max_bytes': asset.bytes, 'provider_uid': asset.storage_key}
                current.result = {**current.result, **_seal(current, grant, 'grant'),
                    'source_sha256': asset.sha256, 'source_bytes': asset.bytes}
                current.payload = {**current.payload, 'phase': 'privacy_pending'}
                current.save(update_fields=['payload', 'result']); job = current; phase = 'privacy_pending'
        if phase == 'orphaned_private_provider_ack': raise _error('stream_upload_draft_changed')
    if phase == 'privacy_pending':
        try:
            metadata = stream._metadata_request(job.result['provider_uid'], 8)
            if metadata.get('uid') != job.result['provider_uid'] or metadata.get('requireSignedURLs') is not True:
                raise ValueError
        except Exception:
            _phase(job.id, 'privacy_failed', code='stream_upload_private_metadata_unverified')
            raise _error('stream_upload_private_metadata_unverified', 503) from None
        job = _phase(job.id, 'grant_ready', update={'private_metadata_verified': True})
        phase = 'grant_ready'
    if phase != 'grant_ready' or job.result.get('private_metadata_verified') is not True:
        raise _error()
    with transaction.atomic():
        _publisher(locked_actor(actor))
        asset = Asset.objects.select_for_update().select_related('revision').get(pk=asset.id)
        if asset.revision.state != 'draft' or asset.state != 'uploading' or not _matches(asset, data):
            raise _error('stream_upload_draft_changed')
        if expiry <= timezone.now(): raise _error('stream_upload_grant_expired')
        grant = _open(job, 'grant')
        if grant.get('asset_id') != str(asset.id) or grant.get('provider_uid') != asset.storage_key or grant.get('max_bytes') != asset.bytes:
            raise _error('stream_upload_grant_unavailable')
    return 201, grant
