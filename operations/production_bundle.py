"""Verify an immutable local production handoff. No network or provider work."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import uuid

SCHEMA = 'earnalism.production_bundle.v1'
FINAL_VOICES = frozenset(('en_mary', 'en_raghav', 'en_tisha', 'bn_arnav', 'bn_riya'))
ROLES = frozenset(('audio', 'native_audio', 'video', 'captions', 'timing_map',
                   'qa_report', 'rights_document', 'thumbnail', 'source_text', 'reader_source'))
PLATFORMS = frozenset(('youtube', 'instagram', 'facebook', 'x'))
HEX = re.compile(r'[a-f0-9]{64}\Z')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')


class BundleError(ValueError):
    pass


def canonical_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise BundleError('BUNDLE_JSON_REQUIRED') from exc


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or set(value) - set(required) - set(optional):
        raise BundleError('BUNDLE_FIELDS_INVALID')


def _uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise BundleError('UUID4_REQUIRED') from exc
    if parsed.version != 4 or str(parsed) != value:
        raise BundleError('UUID4_REQUIRED')


def _hash(value):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise BundleError('SHA256_REQUIRED')


def _relative(relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or '\x00' in relative:
        raise BundleError('LOCAL_ASSET_PATH_REQUIRED')
    parts = PurePosixPath(relative)
    if parts.is_absolute() or any(p in ('', '.', '..') for p in relative.split('/')):
        raise BundleError('CONTAINED_ASSET_PATH_REQUIRED')
    return parts


def asset_path(asset_root, relative):
    root = Path(asset_root).resolve(strict=True)
    if not root.is_dir(): raise BundleError('LOCAL_ASSET_PATH_REQUIRED')
    parts = _relative(relative)
    path = root
    for part in parts.parts:
        path = path / part
        if path.is_symlink():
            raise BundleError('ASSET_SYMLINK_NOT_ALLOWED')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise BundleError('EXACT_LOCAL_ASSET_REQUIRED')
    return path


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load_bundle(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise BundleError('BOUNDED_BUNDLE_FILE_REQUIRED')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BundleError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result

    try:
        return json.loads(path.read_bytes(), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(BundleError('FINITE_JSON_REQUIRED')))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise BundleError('BUNDLE_JSON_REQUIRED') from exc


def validate_manifest(manifest):
    """Fingerprint valid metadata ONLY; this does not verify any asset's bytes."""
    return _validate(manifest, None)


def verify_bundle(manifest, asset_root):
    """Fingerprint metadata and verify every local asset, never authorizing use."""
    if asset_root is None: raise BundleError('LOCAL_ASSET_ROOT_REQUIRED')
    return _validate(manifest, asset_root)


def _validate(manifest, asset_root):
    _keys(manifest, ('schema', 'project_id', 'private', 'content', 'assets', 'evidence'), ('social',))
    if manifest['schema'] != SCHEMA or not isinstance(manifest['project_id'], str) or not NAME.fullmatch(manifest['project_id']):
        raise BundleError('BUNDLE_IDENTITY_INVALID')
    if type(manifest['private']) is not bool:
        raise BundleError('EXPLICIT_PRIVATE_FLAG_REQUIRED')
    content = manifest['content']
    _keys(content, ('text_sha256', 'language', 'voice_profile'),
          ('edition_id', 'revision_id', 'expected_etag', 'source_text_asset_id', 'source_text_sha256'))
    _hash(content['text_sha256'])
    if content['language'] not in ('en', 'bn') or content['voice_profile'] not in FINAL_VOICES:
        raise BundleError('OWNER_FINAL_VOICE_REQUIRED')
    if not content['voice_profile'].startswith(content['language'] + '_'):
        raise BundleError('VOICE_LANGUAGE_MISMATCH')
    draft = ('edition_id', 'revision_id', 'expected_etag')
    if any(k in content for k in draft):
        if not all(k in content for k in draft):
            raise BundleError('COMPLETE_DRAFT_IDENTITY_REQUIRED')
        _uuid(content['edition_id']); _uuid(content['revision_id'])
        if not isinstance(content['expected_etag'], str) or not re.fullmatch(r'"v[0-9]+"', content['expected_etag']):
            raise BundleError('STRONG_EDITION_ETAG_REQUIRED')
    assets = manifest['assets']
    if not isinstance(assets, list) or not 1 <= len(assets) <= 1000:
        raise BundleError('BOUNDED_ASSET_LIST_REQUIRED')
    by_id = {}; paths = set()
    for row in assets:
        _keys(row, ('id', 'path', 'bytes', 'sha256', 'content_type', 'role'),
              ('unit_id', 'duration_ms', 'native_wav'))
        ident = row['id']
        if not isinstance(ident, str) or not NAME.fullmatch(ident) or ident in by_id or not isinstance(row['path'], str) or row['path'] in paths:
            raise BundleError('UNIQUE_ASSET_ID_AND_PATH_REQUIRED')
        if type(row['bytes']) is not int or row['bytes'] < 1:
            raise BundleError('POSITIVE_ASSET_BYTES_REQUIRED')
        _hash(row['sha256'])
        if not isinstance(row['role'], str) or row['role'] not in ROLES or not isinstance(row['content_type'], str) or not re.fullmatch(r'[a-z0-9.+-]+/[a-z0-9.+-]+', row['content_type']):
            raise BundleError('ASSET_TYPE_INVALID')
        if 'unit_id' in row: _uuid(row['unit_id'])
        if 'duration_ms' in row and (type(row['duration_ms']) is not int or row['duration_ms'] < 1):
            raise BundleError('POSITIVE_DURATION_REQUIRED')
        _relative(row['path'])
        if asset_root is not None:
            path = asset_path(asset_root, row['path'])
            if path.stat().st_size != row['bytes'] or digest_file(path) != row['sha256']:
                raise BundleError('ASSET_BYTES_CHANGED')
        by_id[ident] = row; paths.add(row['path'])
    for row in assets:
        if 'native_wav' in row:
            native = by_id.get(row['native_wav']) if isinstance(row['native_wav'], str) else None
            if not native or native['role'] != 'native_audio' or native['content_type'] not in ('audio/wav', 'audio/x-wav'):
                raise BundleError('NATIVE_AUDIO_PROVENANCE_INVALID')
    evidence = manifest['evidence']
    _keys(evidence, ('qa', 'rights'), ('measured_maps', 'captions'))
    for field, role in (('qa', 'qa_report'), ('rights', 'rights_document')):
        ids = evidence[field]
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)) or any(i not in by_id or by_id[i]['role'] != role for i in ids):
            raise BundleError('EVIDENCE_REFERENCE_INVALID')
    for field, role in (('measured_maps', 'timing_map'), ('captions', 'captions')):
        if field in evidence and (not isinstance(evidence[field], str) or evidence[field] not in by_id or by_id[evidence[field]]['role'] != role):
            raise BundleError('EVIDENCE_REFERENCE_INVALID')
    if 'source_text_asset_id' in content or 'source_text_sha256' in content:
        row = by_id.get(content.get('source_text_asset_id')) if isinstance(content.get('source_text_asset_id'), str) else None
        if not row or row['role'] != 'source_text' or row['sha256'] != content.get('source_text_sha256'):
            raise BundleError('SOURCE_TEXT_BINDING_INVALID')
    targets = manifest.get('social', [])
    if not isinstance(targets, list) or len(targets) > 20:
        raise BundleError('BOUNDED_SOCIAL_TARGETS_REQUIRED')
    identities = set()
    for target in targets:
        _keys(target, ('platform', 'account_id', 'video_asset_id', 'title', 'description'),
              ('caption_asset_id', 'thumbnail_asset_id', 'made_for_kids', 'cover_timestamp_ms'))
        if not isinstance(target['platform'], str) or target['platform'] not in PLATFORMS or not isinstance(target['account_id'], str) or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,256}', target['account_id']):
            raise BundleError('SOCIAL_DESTINATION_INVALID')
        identity = (target['platform'], target['account_id'])
        if identity in identities:
            raise BundleError('DUPLICATE_SOCIAL_DESTINATION')
        identities.add(identity)
        if not isinstance(target['video_asset_id'], str) or target['video_asset_id'] not in by_id or by_id[target['video_asset_id']]['role'] != 'video':
            raise BundleError('SOCIAL_VIDEO_REFERENCE_INVALID')
        for field, role in (('caption_asset_id', 'captions'), ('thumbnail_asset_id', 'thumbnail')):
            if field in target and (not isinstance(target[field], str) or target[field] not in by_id or by_id[target[field]]['role'] != role):
                raise BundleError('SOCIAL_COMPANION_REFERENCE_INVALID')
        for field, maximum in (('title', 300), ('description', 10000)):
            value = target[field]
            if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
                raise BundleError('SOCIAL_COPY_INVALID')
        if 'made_for_kids' in target and type(target['made_for_kids']) is not bool:
            raise BundleError('EXPLICIT_AUDIENCE_BOOLEAN_REQUIRED')
        if 'cover_timestamp_ms' in target and (type(target['cover_timestamp_ms']) is not int or target['cover_timestamp_ms'] < 0):
            raise BundleError('MEASURED_COVER_TIMESTAMP_REQUIRED')
    return hashlib.sha256(canonical_bytes(manifest)).hexdigest()
