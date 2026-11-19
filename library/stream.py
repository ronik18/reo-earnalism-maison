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
    from .services import authorize_revision, authorized_until, iso, validate_device
    revision = authorize_revision(user, asset.revision, 'video', territory=territory)
    validate_device(user, device_id)
    config = validate_configuration()
    now = timezone.now()
    expiry = min(now+timedelta(seconds=GRANT_SECONDS), authorized_until(user,revision,'video',territory=territory))
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
