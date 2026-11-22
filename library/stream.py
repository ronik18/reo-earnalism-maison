"""Private Stream VOD adapter. No uploads, key creation or provider activation.

Official contracts checked 19 Nov 2026:
https://developers.cloudflare.com/stream/viewing-videos/securing-your-stream/
https://developers.cloudflare.com/api/resources/stream/methods/get/

Trusted staff preparation verifies metadata before marking an asset ready.
Playback signs locally, after the ordinary account/device/rights/entitlement
checks. No media bytes or provider secrets pass through a public DTO.
"""
import base64
from datetime import datetime, timedelta, timezone as dt_timezone
from functools import lru_cache
import http.client
import json
import math
import re
import ssl
import time
import uuid
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.utils import timezone

from core.api import DomainError

API_HOST = 'api.cloudflare.com'
MAX_METADATA_BYTES = 262144
GRANT_SECONDS = 120
UID = re.compile(r'[a-f0-9]{32}\Z')
HOST = re.compile(r'customer-[a-z0-9]{1,100}\.cloudflarestream\.com\Z')


def _not_configured():
    return DomainError('provider_not_configured', 'Private video delivery is not configured.', 503)


def customer_host():
    host = getattr(settings, 'STREAM_CUSTOMER_HOST', '')
    if not isinstance(host, str) or not HOST.fullmatch(host):
        raise _not_configured()
    return host


def _account_config():
    account = getattr(settings, 'STREAM_ACCOUNT_ID', '')
    token = getattr(settings, 'STREAM_API_TOKEN', '')
    if not isinstance(account, str) or not UID.fullmatch(account) or not isinstance(token, str) or not 1 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise _not_configured()
    return account, token, customer_host()


@lru_cache(maxsize=1)
def _private_key(encoded, key_id):
    try:
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 32768:
            raise ValueError
        raw = encoded.encode('ascii')
        if not encoded.startswith(('-----BEGIN', '{')):
            raw = base64.b64decode(raw, validate=True)
        if raw.lstrip().startswith(b'{'):
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('kty') != 'RSA' or data.get('alg', 'RS256') != 'RS256' or data.get('kid', key_id) != key_id or 'd' not in data:
                raise ValueError
            key = jwt.algorithms.RSAAlgorithm.from_jwk(data)
        else:
            key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError
        return key
    except Exception as exc:
        # Never include decoder/key/provider exception text in a public response.
        raise _not_configured() from exc


def validate_configuration():
    """Startup-safe configuration validation, without a network call."""
    account, _, host = _account_config()
    key_id = getattr(settings, 'STREAM_SIGNING_KEY_ID', '')
    if not isinstance(key_id, str) or not UID.fullmatch(key_id):
        raise _not_configured()
    _private_key(getattr(settings, 'STREAM_SIGNING_PRIVATE_KEY', ''), key_id)
    return {'account_id': account, 'customer_host': host, 'key_id': key_id}


def _asset_uid(asset, *, require_ready=False):
    uid = getattr(asset, 'storage_key', '')
    if (getattr(asset, 'provider', None) != 'stream' or getattr(asset, 'kind', None) != 'video'
            or not isinstance(uid, str) or not UID.fullmatch(uid)
            or (require_ready and getattr(asset, 'state', None) != 'ready')):
        raise DomainError('asset_not_deliverable', 'A prepared private Stream video is required.', 403)
    return uid


def _bound_duration(asset):
    unit = getattr(asset, 'unit', None) if getattr(asset, 'unit_id', None) else None
    duration = getattr(asset, 'duration_ms', None)
    if (unit is None or getattr(unit, 'revision_id', None) != getattr(asset, 'revision_id', None)
            or type(duration) is not int or duration < 1
            or type(getattr(unit, 'duration_ms', None)) is not int or unit.duration_ms != duration):
        raise DomainError('asset_not_deliverable', 'Video requires its bound unit and matching measured duration.', 403)
    return duration


def _metadata_request(uid, max_seconds):
    account, token, _ = _account_config()
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= 8:
        raise DomainError('invalid_budget', 'Video verification permits at most eight seconds.', 422)
    deadline = time.monotonic() + max_seconds
    connection = http.client.HTTPSConnection(API_HOST, timeout=min(3, max_seconds), context=ssl.create_default_context())
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise DomainError('stream_unavailable', 'Video verification exceeded its budget.', 503)
        if connection.sock is not None:
            connection.sock.settimeout(value)
        return value
    try:
        connection.connect(); remaining()
        connection.request('GET', f'/client/v4/accounts/{account}/stream/{uid}', headers={
            'Authorization': 'Bearer '+token, 'Accept': 'application/json',
        })
        remaining(); response = connection.getresponse()
        if response.status != 200:
            raise DomainError('stream_unavailable', 'Video metadata is temporarily unavailable.', 503)
        length = response.getheader('Content-Length')
        if length is not None and (not re.fullmatch('[0-9]{1,10}', length) or int(length) > MAX_METADATA_BYTES):
            raise ValueError('Oversized metadata')
        mime = response.getheader('Content-Type', '').split(';')[0].strip().lower()
        if mime != 'application/json':
            raise ValueError('Unexpected metadata type')
        chunks=[]; total=0
        while True:
            remaining()
            block=response.read(min(65536, MAX_METADATA_BYTES-total+1))
            if not block:
                break
            total += len(block)
            if total > MAX_METADATA_BYTES:
                raise ValueError('Oversized metadata')
            chunks.append(block)
        remaining()
        document=json.loads(b''.join(chunks), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
        if not isinstance(document,dict) or document.get('success') is not True or not isinstance(document.get('result'),dict):
            raise ValueError('Unsuccessful metadata')
        return document['result']
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError('stream_unavailable', 'Video metadata is temporarily unavailable.', 503) from exc
    finally:
        connection.close()


def verify_video_metadata(asset, *, max_seconds=8):
    """Read-only provider check for trusted preparation/publication, not playback.

    Asset and bound unit durations must be known and match the rounded provider
    duration exactly. This verifies provider identity/privacy/
    readiness, not SHA256 of provider-generated adaptive video renditions.
    """
    uid = _asset_uid(asset)
    expected_duration = _bound_duration(asset)
    data = _metadata_request(uid, max_seconds)
    duration = data.get('duration')
    if (data.get('uid') != uid or data.get('readyToStream') is not True or data.get('requireSignedURLs') is not True
            or not isinstance(data.get('status'),dict) or data['status'].get('state') != 'ready'
            or type(duration) not in (int,float) or not math.isfinite(duration) or not 0 < duration < (2**63-1)/1000):
        raise DomainError('stream_not_ready', 'The exact video is not ready for private playback.', 409)
    duration_ms = math.floor(duration*1000+0.5)
    if duration_ms < 1 or expected_duration != duration_ms:
        raise DomainError('asset_integrity_failed', 'Video duration differs from the prepared asset.', 422)
    playback = data.get('playback')
    if not isinstance(playback,dict) or not isinstance(playback.get('hls'),str):
        raise DomainError('stream_not_ready', 'Private video playback metadata is incomplete.', 409)
    url=urlsplit(playback['hls'])
    if (url.scheme != 'https' or url.netloc != customer_host() or url.username or url.password
            or url.path != f'/{uid}/manifest/video.m3u8' or url.query or url.fragment):
        raise DomainError('asset_integrity_failed', 'Video playback origin does not match its configured provider.', 422)
    return {'uid':uid, 'duration_ms':duration_ms, 'require_signed_urls':True, 'ready_to_stream':True}


def grant(user, asset, device_id, territory='IN'):
    """Issue an online-only <=120s iframe token, capped by current authority."""
    if getattr(settings,'FEATURES',{}).get('video') is not True:
        raise DomainError('feature_disabled', 'Video is unavailable.', 503)
    uid = _asset_uid(asset, require_ready=True)
    duration_ms = _bound_duration(asset)
    from .services import access_ends, authorize_revision, iso, validate_device
    revision = authorize_revision(user, asset.revision, 'video', territory=territory)
    validate_device(user, device_id)
    config = validate_configuration()
    now = timezone.now()
    expiry = min(now+timedelta(seconds=GRANT_SECONDS), access_ends(user,revision,'video',territory=territory))
    epoch = math.floor(expiry.timestamp())
    if epoch <= math.floor(now.timestamp()):
        raise DomainError('rights_unavailable', 'Video authorization is expiring.', 403)
    expires_at = datetime.fromtimestamp(epoch,dt_timezone.utc)
    payload = {'sub':uid, 'kid':config['key_id'], 'nbf':math.floor(now.timestamp()), 'exp':epoch,
               'downloadable':False, 'accessRules':[{'type':'ip.geoip.country','action':'allow','country':[territory.upper()]},
                                                  {'type':'any','action':'block'}]}
    token = jwt.encode(payload, _private_key(getattr(settings,'STREAM_SIGNING_PRIVATE_KEY',''),config['key_id']),
                       algorithm='RS256', headers={'kid':config['key_id']})
    return {'grant_id':str(uuid.uuid4()), 'asset_id':str(asset.id), 'edition_revision_id':str(revision.id),
            'transport':'stream_signed', 'url':f"https://{config['customer_host']}/{token}/iframe",
            'content_type':'application/vnd.apple.mpegurl', 'sha256':None, 'issued_at':iso(now),
            'expires_at':iso(expires_at), 'range_supported':False, 'quality_kbps':None, 'duration_ms':duration_ms}


def prepare_stream_asset(actor, manifest, source_file, *, max_seconds=300):
    """Register one already-uploaded private UID on a draft, without uploading.

    Operator-only preparation: verify the retained source bytes locally and the
    provider's identity/privacy/duration metadata, then atomically bind the exact
    draft/unit/proof. The source SHA is NOT a hash of adaptive Stream renditions;
    the operator's private evidence reference retains the upload association.
    No rights, access policy, publication pointer or provider settings change.
    """
    import hashlib
    from pathlib import Path
    from django.contrib.auth import get_user_model
    from core.api import public_uuid
    from core.models import OperationReceipt
    from core.services import apply_operation, audit, payload_hash
    from .models import Asset, Revision, Unit

    if (not actor.is_active or not actor.is_staff or not actor.is_verified
            or not actor.has_perm('library.publish_revision')):
        raise DomainError('permission_denied', 'Verified content publisher permission is required.', 403)
    fields={'operation_id','edition_revision_id','expected_revision_version','unit_id','video_uid',
            'duration_ms','source_sha256','source_bytes','source_evidence_ref'}
    if not isinstance(manifest,dict) or set(manifest)!=fields:
        raise DomainError('validation_error', 'Use the complete private Stream intake manifest.', 422)
    payload=dict(manifest)
    for field in ['operation_id','edition_revision_id','unit_id']:
        payload[field]=str(public_uuid(payload[field],field))
    if (type(payload['expected_revision_version']) is not int or payload['expected_revision_version']<1
            or type(payload['duration_ms']) is not int or not 1<=payload['duration_ms']<=9223372036854775807
            or type(payload['source_bytes']) is not int or not 1<=payload['source_bytes']<=10*1024**3
            or not isinstance(payload['video_uid'],str) or not UID.fullmatch(payload['video_uid'])
            or not isinstance(payload['source_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',payload['source_sha256'])
            or not isinstance(payload['source_evidence_ref'],str) or not 1<=len(payload['source_evidence_ref'].strip())<=500
            or type(max_seconds) not in (int,float) or not 0<max_seconds<=900):
        raise DomainError('validation_error', 'Stream source identity, size, duration or verification budget is invalid.', 422)
    operation=uuid.UUID(payload['operation_id']);request_hash=payload_hash('asset.stream_prepare',payload)
    proof=None

    def persist():
        # This callback performs DB work only. Provider/source I/O precedes locks.
        current_actor=get_user_model().objects.get(pk=actor.pk)
        if not current_actor.is_active or not current_actor.is_staff or not current_actor.is_verified or not current_actor.has_perm('library.publish_revision'):
            raise DomainError('permission_denied','Publisher authority changed during preparation.',403)
        revision=Revision.objects.select_for_update().filter(pk=payload['edition_revision_id']).first()
        if not revision:
            raise DomainError('not_found','Draft revision not found.',404)
        old=Asset.objects.filter(pk=operation).first()
        previous=revision.validation_evidence.get('media_assets',{}).get(str(operation),{})
        if old:
            if (old.provider!='stream' or old.revision_id!=revision.id or old.unit_id!=uuid.UUID(payload['unit_id'])
                    or old.storage_key!=payload['video_uid'] or previous.get('intake_actor_id')!=str(actor.pk)
                    or previous.get('intake_request_sha256')!=request_hash
                    or not isinstance(previous.get('intake_result'),dict)):
                raise DomainError('idempotency_key_reused','Stream intake operation already has different input.',409)
            return 201,previous['intake_result'],previous['intake_result']['version']
        if proof is None:
            raise DomainError('operation_reconciliation_required','Retry this same verified intake operation.',409)
        if revision.state!='draft':
            raise DomainError('revision_frozen','Prepare video only on a draft revision.',409)
        if revision.version!=payload['expected_revision_version']:
            raise DomainError('version_conflict','Draft changed during source verification.',412,{'current_version':revision.version})
        unit=Unit.objects.select_for_update().filter(pk=payload['unit_id'],revision=revision).first()
        if not unit or unit.duration_ms!=payload['duration_ms']:
            raise DomainError('unit_revision_mismatch','The bound draft unit and measured duration must match.',409)
        if Asset.objects.filter(storage_key=payload['video_uid']).exists():
            raise DomainError('stream_identity_conflict','This provider video already belongs to another asset.',409)
        asset=Asset.objects.create(id=operation,revision=revision,unit=unit,kind='video',provider='stream',state='ready',
            storage_key=payload['video_uid'],sha256=payload['source_sha256'],bytes=payload['source_bytes'],
            duration_ms=payload['duration_ms'],content_type='application/vnd.apple.mpegurl')
        result={'asset_id':str(asset.id),'edition_revision_id':str(revision.id),'unit_id':str(unit.id),
                'state':'ready','revision_state':'draft','version':asset.version,'provider':'stream'}
        evidence=dict(revision.validation_evidence);media=dict(evidence.get('media_assets',{}))
        media[str(asset.id)]={**proof,'provider':'stream','source_sha256':asset.sha256,'source_bytes':asset.bytes,
            'source_evidence_ref':payload['source_evidence_ref'],'unit_id':str(unit.id),'prepared':True,
            'verified_at':timezone.now().isoformat().replace('+00:00','Z'),
            'intake_actor_id':str(actor.pk),'intake_request_sha256':request_hash,'intake_result':result}
        evidence['media_assets']=media;revision.validation_evidence=evidence;revision.save()
        audit(actor,'asset.stream_prepared',asset,{'source_sha256':asset.sha256,'unit_id':str(unit.id)})
        return 201,result,asset.version

    # Receipts and the durable asset linkage replay without source/provider reads,
    # including after personal-operation receipt retention has elapsed.
    if (OperationReceipt.objects.filter(actor=actor,operation_id=operation).exists()
            or Asset.objects.filter(pk=operation).exists()):
        return apply_operation(actor,operation,'asset.stream_prepare',payload,persist)
    revision=Revision.objects.filter(pk=payload['edition_revision_id'],state='draft').first()
    unit=Unit.objects.filter(pk=payload['unit_id'],revision=revision).first() if revision else None
    if not revision or not unit or unit.duration_ms!=payload['duration_ms']:
        raise DomainError('unit_revision_mismatch','Select the exact draft unit and measured duration.',409)
    if revision.version!=payload['expected_revision_version']:
        raise DomainError('version_conflict','Draft changed before source verification.',412,{'current_version':revision.version})
    deadline=time.monotonic()+max_seconds
    try:
        path=Path(source_file)
        if not path.is_file() or path.stat().st_size!=payload['source_bytes']:
            raise ValueError
        digest=hashlib.sha256();total=0
        with path.open('rb') as source:
            while True:
                if time.monotonic()>=deadline:
                    raise DomainError('asset_verification_timeout','Source verification exceeded its budget.',503)
                block=source.read(min(1024**2,payload['source_bytes']-total+1))
                if not block:break
                total+=len(block)
                if total>payload['source_bytes']:raise ValueError
                digest.update(block)
        if total!=payload['source_bytes'] or digest.hexdigest()!=payload['source_sha256']:
            raise ValueError
    except DomainError:
        raise
    except (OSError,TypeError,ValueError) as exc:
        raise DomainError('asset_integrity_failed','Retained source bytes do not match this intake.',422) from exc
    candidate=Asset(id=operation,revision=revision,unit=unit,kind='video',provider='stream',state='processing',
        storage_key=payload['video_uid'],sha256=payload['source_sha256'],bytes=payload['source_bytes'],duration_ms=payload['duration_ms'])
    remaining=deadline-time.monotonic()
    if remaining<=0:
        raise DomainError('asset_verification_timeout','Source verification exceeded its budget.',503)
    proof=verify_video_metadata(candidate,max_seconds=min(8,remaining))
    return apply_operation(actor,operation,'asset.stream_prepare',payload,persist)
