"""Prepare finite private provider acceptance from retained bytes; never executes.

No credentials, environment, HTTP client or provider transport is read here.
Local source verification and ffprobe are evidence of bytes/containers only.
"""
from datetime import datetime
import json
import math
from pathlib import Path
import re
import subprocess

from .production_bundle import asset_path, verify_bundle

PROVIDERS = frozenset(('maison', 'r2', 'stream', 'youtube', 'instagram', 'facebook', 'x'))
CHECKS = frozenset(('account_identity', 'existing_access', 'existing_quota',
                    'deployed_bridge', 'private_state', 'retained_source_association'))


class AcceptanceError(ValueError):
    pass


def _observations(value, digest):
    if value is None:
        return []
    if (not isinstance(value, dict) or set(value) != {'schema', 'candidate_sha256', 'checks'}
            or value['schema'] != 'earnalism.private_provider_observations.v1'
            or value['candidate_sha256'] != digest or not isinstance(value['checks'], list)
            or len(value['checks']) > 42):
        raise AcceptanceError('SOURCE_BOUND_PROVIDER_OBSERVATIONS_REQUIRED')
    result, seen = [], set()
    for row in value['checks']:
        if (not isinstance(row, dict) or set(row) != {'provider', 'check', 'result', 'observed_at', 'evidence_sha256'}
                or not isinstance(row['provider'], str) or row['provider'] not in PROVIDERS
                or not isinstance(row['check'], str) or row['check'] not in CHECKS
                or row['result'] not in ('OBSERVED', 'MISSING', 'UNKNOWN')
                or not isinstance(row['evidence_sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', row['evidence_sha256'])
                or not isinstance(row['observed_at'], str)
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', row['observed_at'])):
            raise AcceptanceError('SAFE_HASH_BOUND_READ_ONLY_OBSERVATION_REQUIRED')
        try:
            datetime.fromisoformat(row['observed_at'].replace('Z', '+00:00'))
        except ValueError:
            raise AcceptanceError('UTC_OBSERVATION_TIME_REQUIRED') from None
        key = (row['provider'], row['check'])
        if key in seen:
            raise AcceptanceError('UNIQUE_PROVIDER_OBSERVATION_REQUIRED')
        seen.add(key)
        result.append(dict(row))
    return result


def _measure(path):
    try:
        response = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
            '-show_entries', 'format=duration,format_name:stream=codec_type,codec_name,width,height,bit_rate,sample_rate,channels',
            '-of', 'json', str(path)], check=True, capture_output=True, timeout=20)
        if len(response.stdout) > 65536:
            raise ValueError
        value = json.loads(response.stdout)
        seconds = float(value['format']['duration'])
        if not math.isfinite(seconds) or seconds <= 0 or not isinstance(value['streams'], list):
            raise ValueError
        streams = []
        for item in value['streams']:
            if item.get('codec_type') not in {'video', 'audio'}:
                raise ValueError
            row = {key: item[key] for key in ('codec_type', 'codec_name', 'width', 'height', 'bit_rate', 'sample_rate', 'channels') if key in item}
            if row['codec_type'] == 'video' and (type(row.get('width')) is not int or type(row.get('height')) is not int or row['width'] <= 0 or row['height'] <= 0):
                raise ValueError
            streams.append(row)
        return {'duration_seconds': seconds, 'duration_ms': math.floor(seconds * 1000 + .5),
                'container': value['format']['format_name'], 'streams': streams}
    except Exception:
        raise AcceptanceError('RETAINED_MEDIA_CONTAINER_MEASUREMENT_REQUIRED') from None


def _identity(manifest, provider):
    accounts = [x['account_id'] for x in manifest.get('social', []) if x['platform'] == provider]
    if len(accounts) > 1:
        raise AcceptanceError('ONE_ACCOUNT_PER_PROVIDER_ACCEPTANCE_PASS')
    return accounts[0] if accounts else None


def prepare_acceptance(manifest, asset_root, *, observations=None):
    """Return a source-bound proposal with execution disabled, even with observations.

    This is transport acceptance only. A supplied rights/QA file or operator
    observation is not independently verified clearance, quality or authority.
    Account/draft identifiers are never invented when absent.
    """
    digest = verify_bundle(manifest, asset_root)
    if manifest['private'] is not True:
        raise AcceptanceError('PRIVATE_TRANSPORT_CANDIDATE_REQUIRED')
    recorded = _observations(observations, digest)
    media, videos, audio = [], [], []
    for row in manifest['assets']:
        if row['role'] not in {'video', 'audio'}:
            continue
        measured = _measure(asset_path(asset_root, row['path']))
        if 'duration_ms' in row and measured['duration_ms'] != row['duration_ms']:
            raise AcceptanceError('MEASURED_CANDIDATE_DURATION_CHANGED')
        item = {key: row[key] for key in ('id', 'path', 'bytes', 'sha256', 'content_type', 'role')}
        item['measurement'] = measured
        if 'unit_id' in row:
            item['unit_id'] = row['unit_id']
        if row['role'] == 'video':
            visual = [x for x in measured['streams'] if x['codec_type'] == 'video']
            if row['content_type'] != 'video/mp4' or len(visual) != 1 or 'mp4' not in measured['container'].split(','):
                raise AcceptanceError('ONE_RETAINED_MP4_VIDEO_STREAM_REQUIRED')
            item['video_only'] = not any(x['codec_type'] == 'audio' for x in measured['streams'])
            videos.append(item)
        else:
            streams = measured['streams']
            supported = (row['content_type'] == 'audio/mpeg' and len(streams) == 1
                and streams[0]['codec_type'] == 'audio' and streams[0].get('codec_name') == 'mp3'
                and str(streams[0].get('bit_rate')) in {'48000', '96000'})
            item['existing_maison_audio_profile_supported'] = supported
            item['retained_native_audio_reference_supplied'] = 'native_wav' in row
            item['profile_result'] = 'CONTAINER_PROFILE_ONLY_NOT_VOICE_ACCEPTANCE' if supported else 'HELD_NO_ENCODING_AUTHORIZED'
            audio.append(item)
        media.append(item)
    if len(videos) > 1:
        raise AcceptanceError('ONE_RETAINED_VIDEO_PER_FINITE_ACCEPTANCE_PASS')
    content = manifest['content']
    draft_bound = all(k in content for k in ('edition_id', 'revision_id', 'expected_etag'))
    source_assets = [{key: row[key] for key in ('id', 'path', 'bytes', 'sha256', 'content_type', 'role')}
        for row in manifest['assets'] if row['role'] in {'source_text', 'reader_source', 'qa_report', 'rights_document', 'timing_map', 'captions'}]
    r2_bytes = sum(x['bytes'] for x in source_assets)
    r2_bounded = (len(source_assets) <= 100 and r2_bytes <= 64 * 1024 * 1024
        and all(x['bytes'] <= (1024 * 1024 if x['role'] == 'timing_map' else 4 * 1024 * 1024) for x in source_assets))
    proposed = []
    if videos:
        video = videos[0]
        visual = next(s for s in video['measurement']['streams'] if s['codec_type'] == 'video')
        for provider in ('stream', 'youtube', 'x', 'facebook', 'instagram'):
            account = _identity(manifest, provider)
            gates = ['FRESH_EXISTING_ACCOUNT_ACCESS_AND_QUOTA_READBACK', 'EXACT_PRIVATE_DESTINATION_AUTHORITY', 'ACTUAL_PRIVATE_UPLOAD_PROCESSING_AND_READBACK_UNPERFORMED']
            local = 'RETAINED_CONTAINER_VERIFIED_TRANSPORT_ONLY'
            if provider == 'stream' and (not draft_bound or 'unit_id' not in video):
                gates.append('MAISON_DRAFT_AND_UNIT_IDENTITIES_UNBOUND')
            elif provider != 'stream' and account is None:
                gates.append('ACCOUNT_IDENTITY_UNBOUND')
            if provider == 'facebook' and (visual['width'] * 16 != visual['height'] * 9 or visual['width'] < 540
                    or visual['height'] < 960 or not 3 <= video['measurement']['duration_seconds'] <= 90):
                local = 'HELD_CURRENT_ADAPTER_REQUIRES_PORTRAIT_3_TO_90_SECONDS'
            if provider == 'instagram':
                # Do not invent an account merely to make adapter preflight pass.
                local = 'HELD_UNTIL_EXACT_ACCOUNT_CURRENT_ADAPTER_PREFLIGHT'
                gates.append('CURRENT_ADAPTER_ACCOUNT_GEOMETRY_DURATION_PREFLIGHT_REQUIRED')
            if provider == 'youtube':
                target = next((x for x in manifest.get('social', []) if x['platform'] == provider), None)
                if target is None or type(target.get('made_for_kids')) is not bool:
                    gates.append('EXACT_PROVIDER_COPY_AND_EXPLICIT_AUDIENCE_REQUIRED')
            modes = {'stream': 'PRIVATE_SIGNED_STREAM', 'youtube': 'PRIVATE_VIDEO', 'x': 'MEDIA_ONLY_NO_POST',
                     'facebook': 'DRAFT_REEL_ONLY', 'instagram': 'NONPUBLIC_CONTAINER_ONLY'}
            steps = {'stream': ['existing_private_draft_and_unit', 'one_private_tus_intent', 'HEAD_offset', 'PATCH_exact_source', 'complete', 'private_metadata_processing', 'signed_unsigned_expired_playback_checks'],
                     'youtube': ['account_identity', 'one_private_resumable_session', 'exact_source_upload', 'one_processing_status', 'private_saved_state_and_playback'],
                     'x': ['account_identity', 'one_media_initialize', 'exact_source_append', 'finalize', 'one_media_status'],
                     'facebook': [], 'instagram': []}
            proposed.append({'provider': provider, 'account_id': account, 'asset_id': video['id'],
                'source_bytes': video['bytes'], 'source_sha256': video['sha256'], 'private_mode': modes[provider],
                'local_candidate_state': local, 'gates': gates, 'proposed_steps': steps[provider],
                'maximum_new_media_objects': 1 if provider in {'stream', 'youtube', 'x'} else 0,
                'maximum_source_upload_bytes': video['bytes'] if provider in {'stream', 'youtube', 'x'} else 0,
                'maximum_upload_chunks': (video['bytes'] - 1) // ((50 if provider == 'stream' else 4) * 1024 * 1024) + 1 if provider in {'stream', 'youtube', 'x'} else 0,
                'automatic_retries': 0, 'automatic_processing_polls': 0, 'execution_enabled': False})
    return {'schema': 'earnalism.private_provider_acceptance_plan.v1',
        'state': 'PREPARED_PRIVATE_TRANSPORT_ONLY_NOT_EXECUTED', 'candidate_sha256': digest,
        'project_id': manifest['project_id'], 'private': True, 'voice_profile': content['voice_profile'],
        'voice_profile_is_routing_metadata_not_performance_acceptance': True,
        'retained_media': media, 'proposed_provider_scope': proposed,
        'r2_source_transfer': {'state': ('PREPARED_SOURCE_BYTES_ONLY' if r2_bounded else 'HELD_SPLIT_TO_EXISTING_R2_LIMITS') if source_assets else 'HELD_NO_RETAINED_SOURCE_OR_QA_BYTES',
            'assets': source_assets, 'maximum_new_objects': len(source_assets) if r2_bounded else 0,
            'maximum_source_upload_bytes': r2_bytes if r2_bounded else 0,
            'retained_source_bytes': r2_bytes, 'source_transfer_does_not_certify_general_import_schema': True,
            'gates': ['EXACT_PRIVATE_DRAFT_SOURCE_OR_QA_UPLOAD_INTENT', 'EXISTING_PRIVATE_BUCKET_ACCESS_AND_QUOTA', 'ACTUAL_PUT_COMPLETE_AND_HASH_READBACK_UNPERFORMED'],
            'execution_enabled': False},
        'maison_draft_identity': {key: content[key] for key in ('edition_id', 'revision_id', 'expected_etag') if key in content},
        'observations': recorded, 'observations_are_operator_supplied_not_independently_verified': True,
        'content_quality_and_rights': {'status': 'NOT_ACCEPTED_BY_TRANSPORT_PREPARATION',
            'supplied_qa_assets': list(manifest['evidence']['qa']), 'supplied_rights_assets': list(manifest['evidence']['rights']),
            'actual_listening': 'UNASSESSED', 'release_ready': False,
            'video_only_cannot_qualify_soundtrack_or_full_film_playback': any(x.get('video_only') for x in videos)},
        'execution_enabled': False, 'provider_requests': 0, 'credential_reads': 0, 'model_calls': 0,
        'new_generation': False, 'new_encoding': False, 'purchases': False, 'publication': False,
        'originals_modified': False, 'Open_Window_soundtrack_and_style_preserved': True,
        'future_execution_requires_fresh_bounded_authority': True,
        'stop_rule': 'Retain one terminal result per candidate/provider. Unknown writes hold; never create another object or regenerate media to hide an outcome.'}
