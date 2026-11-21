"""Provider protocol steps used by the common production CLI/outbox, never a controller.

Authority is a scoped request, not evidence that owner/staff consent occurred.
The integrating caller must independently authorize it. No credentials enter plans
or journal records; provider upload capabilities remain in this object only.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode, urlsplit

from .http import FileSlice, HTTPSClient

PLATFORMS = {'youtube', 'instagram', 'facebook', 'x'}
CHUNK = 4 * 1024 * 1024


class DeliveryError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                      ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,codec_name:format=duration', '-of', 'json', str(path)],
        check=True, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    stream = data['streams'][0]
    return {'width': int(stream['width']), 'height': int(stream['height']),
            'codec': stream['codec_name'], 'duration_seconds': float(data['format']['duration'])}


def prepare(manifest, asset_root, *, verify=None, probe=None):
    """Validate actual bundle/files and video geometry; performs no provider requests."""
    if verify is None:
        from operations.production_bundle import verify_bundle
        verify = verify_bundle
    digest = verify(manifest, asset_root)
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise DeliveryError('verified_bundle_hash_required')
    root = Path(asset_root).resolve(strict=True)
    assets = {item['id']: item for item in manifest['assets']}
    destinations = []
    seen = set()
    for item in manifest.get('social', []):
        platform, account = item['platform'], item['account_id']
        if platform not in PLATFORMS or not isinstance(account, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', account):
            raise DeliveryError('explicit_supported_destination_account_required')
        key = platform + ':' + account
        if key in seen:
            raise DeliveryError('duplicate_destination')
        seen.add(key)
        video = assets[item['video_asset_id']]
        if video['role'] != 'video' or video['content_type'] != 'video/mp4' or type(video['bytes']) is not int or video['bytes'] <= 0:
            raise DeliveryError('bound_mp4_video_required')
        path = root / video['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise DeliveryError('contained_video_required')
        geometry = (probe or _probe)(path)
        if (type(geometry.get('width')) is not int or type(geometry.get('height')) is not int
                or geometry['width'] <= 0 or geometry['height'] <= 0
                or not isinstance(geometry.get('duration_seconds'), (int, float))
                or not math.isfinite(geometry['duration_seconds']) or geometry['duration_seconds'] <= 0):
            raise DeliveryError('actual_video_geometry_required')
        if platform == 'facebook' and (geometry['width'] * 16 != geometry['height'] * 9
                or geometry['width'] < 540 or geometry['height'] < 960
                or not 3 <= geometry['duration_seconds'] <= 90):
            raise DeliveryError('facebook_reels_portrait_3_to_90_seconds_required')
        if 'cover_timestamp_ms' in item and (platform != 'instagram'
                or type(item['cover_timestamp_ms']) is not int
                or not 0 <= item['cover_timestamp_ms'] < geometry['duration_seconds'] * 1000):
            raise DeliveryError('instagram_cover_frame_within_actual_video_required')
        caption = assets.get(item.get('caption_asset_id'))
        if caption is not None and caption['role'] != 'captions':
            raise DeliveryError('caption_asset_role_required')
        title, description = item['title'], item['description']
        if not isinstance(title, str) or not title.strip() or not isinstance(description, str):
            raise DeliveryError('explicit_destination_copy_required')
        if platform == 'youtube' and (len(title) > 100 or len(description) > 5000):
            raise DeliveryError('youtube_copy_limit_exceeded')
        destinations.append({**item, 'key': key, 'video': video, 'captions': caption,
            'geometry': geometry, 'aspect': 'portrait' if geometry['height'] > geometry['width'] else 'landscape',
            'caption_delivery': 'native_track' if caption and platform == 'youtube' else 'burned_into_master_required',
            'caption_burn_in_verified': False,
            'thumbnail_delivery': 'native_upload_available' if platform == 'youtube' else 'unsupported_separate_cover_handoff',
            'separate_caption_upload_implemented': platform == 'youtube',
            'constraints': {'private_feed_post_supported': platform == 'youtube',
                'nonpublic_media_staging_only': platform in {'instagram', 'x'},
                'facebook_page_publish_is_public': platform == 'facebook',
                'current_account_permissions_limits_and_processing_require_readback': True}})
    return {'schema': 'earnalism.social_delivery_plan.v1', 'candidate_sha256': digest,
        'manifest': json.loads(json.dumps(manifest)), 'asset_root': str(root), 'destinations': destinations,
        'state': 'PREPARED_NO_PROVIDER_REQUESTS', 'private': manifest['private'],
        'provider_requests': 0, 'rights_QA_listening_acceptance_supplied_by_bridge': False}


@dataclass(frozen=True)
class Authority:
    candidate_sha256: str
    destination_key: str
    account_id: str
    actions: frozenset
    reference: str


class Delivery:
    """Explicit individual protocol operations, with injected root-owned journal.

    run(..., execute=False) is inert. No automatic retries, processing polls,
    credential discovery, OAuth flow or purchase exists here.
    """
    def __init__(self, plan, journal, token_for, authorize, *, http=None,
                 graph_version=None, meta_login='facebook_business', verify=None):
        has_meta = any(d.get('platform') in {'instagram', 'facebook'} for d in plan['destinations'])
        if has_meta and (not isinstance(graph_version, str) or not re.fullmatch(r'v[0-9]{1,3}\.0', graph_version)):
            raise DeliveryError('explicit_meta_api_version_required')
        self.plan, self.journal = json.loads(json.dumps(plan)), journal
        self.token_for, self.authorize = token_for, authorize
        self.http = http or HTTPSClient()
        self.version, self.meta_login, self.verify = graph_version, meta_login, verify
        self.state, self.capabilities, self.identities = {}, {}, set()

    def _token(self, d):
        value = self.token_for(d['platform'], d['account_id'])
        if not isinstance(value, str) or not value or any(c in value for c in '\r\n'):
            raise DeliveryError('in_memory_provider_token_required')
        return value

    def _request(self, d, method, url, *, oauth=False, headers=None, **kwargs):
        if any(k.lower() in {'authorization', 'host', 'cookie', 'proxy-authorization',
                'content-length', 'transfer-encoding', 'connection'} for k in (headers or {})):
            raise DeliveryError('provider_request_issuer_owns_sensitive_headers')
        auth = ('OAuth ' if oauth else 'Bearer ') + self._token(d)
        return self.http.request(method, url, headers={'Authorization': auth, **(headers or {})}, **kwargs)

    def _write(self, d, action, intent, invoke, interpret):
        key = 'social:' + self.plan['candidate_sha256'] + ':' + d['key'] + ':' + action
        binding = fingerprint({'candidate': self.plan['candidate_sha256'], 'destination': d['key'],
                               'action': action, 'intent': intent})
        cached = self.journal.begin(key, binding)
        if cached is not None:
            return cached
        try:
            response = invoke()
            if not 200 <= response.status < 300:
                raise DeliveryError('provider_http_' + str(response.status))
            result = interpret(response)
            self.journal.acknowledge(key, result)
            return result
        except Exception as exc:
            code = exc.code if isinstance(exc, DeliveryError) else 'provider_outcome_unknown'
            self.journal.unknown(key, code)
            raise DeliveryError(code) from None

    def _completed_upload_binding(self, d):
        return fingerprint({'candidate': self.plan['candidate_sha256'], 'destination': d['key'],
            'source_sha256': d['video']['sha256'], 'source_bytes': d['video']['bytes']})

    def _remember_completed_upload(self, d, result):
        # One stable receipt also covers dynamic resume_upload:<offset> steps.
        # Persist only acknowledged identity, never capability or readiness.
        completed = {'video_id': self._id(result.get('video_id')), 'upload_completed': True}
        key = 'social:' + self.plan['candidate_sha256'] + ':' + d['key'] + ':completed-upload'
        old = self.journal.begin(key, self._completed_upload_binding(d))
        if old is None:
            self.journal.acknowledge(key, completed)
        elif old != completed:
            raise DeliveryError('completed_upload_identity_conflict')
        return {**result, 'upload_completed': True}

    def _graph(self, identifier, edge='', **query):
        return ('https://graph.facebook.com/' + self.version + '/' + identifier
                + ('/' + edge if edge else '') + ('?' + urlencode(query) if query else ''))

    def _identity(self, d):
        token_hash = hashlib.sha256(self._token(d).encode()).hexdigest()
        key = d['key'], token_hash
        if key in self.identities:
            return
        platform = d['platform']
        if platform == 'youtube':
            url = 'https://www.googleapis.com/youtube/v3/channels?part=id&mine=true'
        elif platform == 'x':
            url = 'https://api.x.com/2/users/me'
        elif platform == 'instagram':
            url = self._graph('me', fields='id,instagram_business_account')
        else:
            url = self._graph('me', fields='id')
        response = self._request(d, 'GET', url)
        if response.status != 200:
            raise DeliveryError('provider_account_verification_failed')
        data = response.data
        if platform == 'youtube':
            ids = [x.get('id') for x in data.get('items', [])]
        elif platform == 'instagram':
            ids = [data.get('instagram_business_account', {}).get('id')]
        else:
            ids = [data.get('data', data).get('id')]
        if d['account_id'] not in ids:
            raise DeliveryError('provider_account_mismatch')
        self.identities.add(key)

    def _file(self, d, name='video'):
        item = d[name]
        if item is None:
            raise DeliveryError('required_bound_asset_missing')
        path = Path(self.plan['asset_root']) / item['path']
        return item, path

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
            raise DeliveryError('provider_resource_id_missing')
        return value

    @staticmethod
    def _success(response):
        if response.data.get('success') is not True:
            raise DeliveryError('provider_success_not_acknowledged')
        return {'state': 'MEDIA_TRANSFER_ACKNOWLEDGED_NOT_PUBLISHED'}

    def run(self, destination_key, action, *, execute=False, authority=None):
        d = next((x for x in self.plan['destinations'] if x['key'] == destination_key), None)
        if d is None:
            raise DeliveryError('destination_not_in_bound_candidate')
        if not execute:
            return {'state': 'PREPARED_NO_PROVIDER_REQUESTS', 'destination': d['key'], 'action': action,
                    'provider_requests': 0, 'constraints': d['constraints']}
        if action == 'publish' and self.plan['private']:
            raise DeliveryError('private_candidate_cannot_be_published')
        if (not isinstance(authority, Authority) or authority.candidate_sha256 != self.plan['candidate_sha256']
                or authority.destination_key != d['key'] or authority.account_id != d['account_id']
                or action not in authority.actions or not authority.reference or not callable(self.authorize)):
            raise DeliveryError('separate_candidate_destination_account_authority_required')
        if self.authorize(authority, self.plan, d, action) is not True:
            raise DeliveryError('integrating_caller_authorization_required')
        if self.verify is None:
            from operations.production_bundle import verify_bundle
            verify = verify_bundle
        else:
            verify = self.verify
        if verify(self.plan['manifest'], self.plan['asset_root']) != self.plan['candidate_sha256']:
            raise DeliveryError('candidate_changed_after_preparation')
        source = next((x for x in self.plan['manifest'].get('social', [])
            if x['platform'] + ':' + x['account_id'] == d['key']), None)
        assets = {x['id']: x for x in self.plan['manifest']['assets']}
        if (source is None or any(d.get(k) != v for k, v in source.items())
                or d['video'] != assets.get(source['video_asset_id'])
                or d['captions'] != assets.get(source.get('caption_asset_id'))):
            raise DeliveryError('destination_changed_after_preparation')
        if action == 'publish' and source.get('thumbnail_asset_id') and d['platform'] != 'youtube':
            raise DeliveryError('separate_thumbnail_requires_supported_delivery_handoff')
        if action == 'publish' and d['captions'] is not None and d['platform'] != 'youtube':
            raise DeliveryError('caption_delivery_requires_verified_burn_in_handoff')
        self._identity(d)
        if d['key'] not in self.state:
            # Restore only acknowledged provider IDs/companion acknowledgements.
            # Capabilities and processing readiness are never reconstructed.
            restored = {}
            prefix = 'social:' + self.plan['candidate_sha256'] + ':' + d['key'] + ':'
            for prior in ('start', 'upload:0', 'upload', 'finalize', 'captions', 'thumbnail', 'stage_draft', 'completed-upload'):
                record = self.journal.read(prefix + prior)
                if record and record['state'] == 'acknowledged':
                    if prior == 'completed-upload' and (record['fingerprint'] != self._completed_upload_binding(d)
                            or record['result'].get('upload_completed') is not True):
                        raise DeliveryError('completed_upload_source_binding_mismatch')
                    for field in ('video_id', 'container_id', 'media_id', 'caption_id', 'thumbnail_acknowledged', 'upload_completed'):
                        if field in record['result']:
                            restored[field] = record['result'][field]
            self.state[d['key']] = restored
        state = self.state[d['key']]
        result = getattr(self, '_' + d['platform'])(d, state, action)
        if action == 'status' and self.plan['private']:
            visibility = result.get('provider_status', {}).get('privacyStatus')
            if (result.get('public_post_observed') is True
                    or d['platform'] == 'youtube' and visibility != 'private'
                    or d['platform'] == 'instagram' and result.get('status_code') == 'PUBLISHED'
                    or d['platform'] == 'facebook' and str(result.get('publish_status', '')).lower() in {'published', 'public'}):
                raise DeliveryError('private_scope_conflicts_with_observed_provider_visibility')
        state.update(result)
        return result

    def _youtube(self, d, state, action):
        video, path = self._file(d)
        if action == 'start':
            if type(d.get('made_for_kids')) is not bool:
                raise DeliveryError('explicit_youtube_audience_choice_required')
            metadata = {'snippet': {'title': d['title'], 'description': d['description'],
                'defaultLanguage': self.plan['manifest']['content']['language']},
                'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': d['made_for_kids'],
                           'containsSyntheticMedia': True}}
            def interpret(r):
                url = r.headers.get('location', '')
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or parsed.netloc != 'www.googleapis.com' or not parsed.path.startswith('/upload/youtube/'):
                    raise DeliveryError('youtube_resumable_location_missing')
                self.capabilities[d['key']] = url  # Never persisted in a journal.
                return {'state': 'PRIVATE_UPLOAD_SESSION_STARTED', 'upload_capability_persisted': False}
            return self._write(d, action, metadata,
                lambda: self._request(d, 'POST', 'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
                    json_body=metadata, headers={'X-Upload-Content-Length': str(video['bytes']), 'X-Upload-Content-Type': 'video/mp4'}), interpret)
        if action in {'upload', 'resume_upload'}:
            if d['key'] not in self.capabilities:
                raise DeliveryError('lost_upload_capability_requires_reconciliation_no_new_session')
            offset = state.get('resume_offset', 0) if action == 'resume_upload' else 0
            if action == 'resume_upload' and 'resume_offset' not in state:
                raise DeliveryError('resumable_status_evidence_required')
            def send():
                for start in range(offset, video['bytes'], CHUNK):
                    size = min(CHUNK, video['bytes'] - start)
                    response = self._request(d, 'PUT', self.capabilities[d['key']],
                        body=FileSlice(path, start, size), headers={'Content-Type': 'video/mp4',
                            'Content-Range': f'bytes {start}-{start + size - 1}/{video["bytes"]}'})
                    if response.status == 308:
                        if response.headers.get('range') != f'bytes=0-{start + size - 1}':
                            raise DeliveryError('youtube_committed_range_requires_reconciliation')
                        continue
                    if response.status in (200, 201) and start + size == video['bytes']:
                        return response
                    raise DeliveryError('youtube_upload_outcome_requires_reconciliation')
                raise DeliveryError('youtube_final_upload_response_missing')
            result = self._write(d, action + ':' + str(offset), {'video_sha256': video['sha256'], 'offset': offset}, send,
                lambda r: self._remember_completed_upload(d,
                    {'state': 'PRIVATE_VIDEO_UPLOAD_ACKNOWLEDGED', 'video_id': self._id(r.data.get('id'))}))
            return self._remember_completed_upload(d, result)
        if action == 'reconcile_upload':
            if d['key'] not in self.capabilities:
                raise DeliveryError('lost_upload_capability_requires_manual_reconciliation')
            response = self._request(d, 'PUT', self.capabilities[d['key']], body=b'',
                headers={'Content-Range': 'bytes */' + str(video['bytes'])})
            if response.status == 308:
                match = re.fullmatch(r'bytes=0-([0-9]+)', response.headers.get('range', ''))
                offset = int(match[1]) + 1 if match else 0
                if not 0 <= offset < video['bytes']:
                    raise DeliveryError('youtube_invalid_resume_offset')
                return {'state': 'INCOMPLETE_UPLOAD_STATUS_OBSERVED_NO_RETRY', 'resume_offset': offset}
            if response.status in (200, 201):
                return self._remember_completed_upload(d,
                    {'state': 'COMPLETED_UPLOAD_STATUS_OBSERVED', 'video_id': self._id(response.data.get('id'))})
            raise DeliveryError('youtube_upload_status_unresolved')
        if action == 'captions':
            caption, caption_path = self._file(d, 'captions')
            vid = self._id(state.get('video_id'))
            def send():
                metadata = {'snippet': {'videoId': vid, 'language': self.plan['manifest']['content']['language'],
                    'name': 'Earnalism ' + self.plan['candidate_sha256'][:12], 'isDraft': False}}
                response = self._request(d, 'POST', 'https://www.googleapis.com/upload/youtube/v3/captions?uploadType=resumable&part=snippet',
                    json_body=metadata, headers={'X-Upload-Content-Type': caption['content_type'],
                                                'X-Upload-Content-Length': str(caption['bytes'])})
                location = response.headers.get('location', '')
                parsed = urlsplit(location)
                if response.status != 200 or parsed.scheme != 'https' or parsed.netloc != 'www.googleapis.com' or not parsed.path.startswith('/upload/youtube/'):
                    raise DeliveryError('caption_upload_session_unresolved')
                return self._request(d, 'PUT', location, body=FileSlice(caption_path, 0, caption['bytes']),
                    headers={'Content-Type': caption['content_type']})
            return self._write(d, action, {'video_id': vid, 'caption_sha256': caption['sha256']}, send,
                lambda r: {'state': 'CAPTION_UPLOAD_ACKNOWLEDGED', 'caption_id': self._id(r.data.get('id')),
                           'caption_ready': r.data.get('snippet', {}).get('status') == 'serving'})
        if action == 'thumbnail':
            item = next((x for x in self.plan['manifest']['assets'] if x['id'] == d.get('thumbnail_asset_id')), None)
            if item is None or item['role'] != 'thumbnail' or item['content_type'] not in {'image/jpeg', 'image/png'} or item['bytes'] > 50_000_000:
                raise DeliveryError('bound_youtube_thumbnail_under_50_mb_required')
            if not state.get('ready'):
                raise DeliveryError('processed_video_readback_before_thumbnail_required')
            vid = self._id(state.get('video_id'))
            def interpret(r):
                if not r.data.get('items') or not isinstance(r.data['items'][0], dict) or not r.data['items'][0].get('default'):
                    raise DeliveryError('youtube_thumbnail_acknowledgement_missing')
                return {'state': 'THUMBNAIL_UPLOAD_ACKNOWLEDGED', 'video_id': vid, 'thumbnail_acknowledged': True}
            return self._write(d, action, {'video_id': vid, 'thumbnail_sha256': item['sha256']},
                lambda: self._request(d, 'POST', 'https://www.googleapis.com/upload/youtube/v3/thumbnails/set?' + urlencode({'uploadType': 'media', 'videoId': vid}),
                    body=FileSlice(Path(self.plan['asset_root']) / item['path'], 0, item['bytes']), headers={'Content-Type': item['content_type']}), interpret)
        if action == 'status':
            vid = self._id(state.get('video_id'))
            response = self._request(d, 'GET', 'https://www.googleapis.com/youtube/v3/videos?' + urlencode({'part': 'status,processingDetails,snippet', 'id': vid}))
            items = response.data.get('items', [])
            if response.status != 200 or len(items) != 1 or items[0].get('id') != vid:
                raise DeliveryError('youtube_video_status_unresolved')
            item = items[0]
            if item.get('snippet', {}).get('channelId') != d['account_id']:
                raise DeliveryError('youtube_video_account_mismatch')
            caption_ready = d['captions'] is None
            if d['captions'] is not None:
                cr = self._request(d, 'GET', 'https://www.googleapis.com/youtube/v3/captions?' + urlencode({'part': 'snippet', 'videoId': vid}))
                caption_ready = cr.status == 200 and any(x.get('id') == state.get('caption_id') and x.get('snippet', {}).get('status') == 'serving' for x in cr.data.get('items', []))
            return {'state': 'PROVIDER_STATUS_OBSERVED', 'video_id': vid,
                'ready': item.get('processingDetails', {}).get('processingStatus') == 'succeeded',
                'copy_matches': item.get('snippet', {}).get('title') == d['title'] and item.get('snippet', {}).get('description') == d['description'],
                'caption_ready': caption_ready, 'provider_status': item.get('status', {}),
                'public_post_observed': item.get('status', {}).get('privacyStatus') == 'public'}
        if action == 'publish':
            if not state.get('ready') or not state.get('copy_matches') or not state.get('caption_ready'):
                raise DeliveryError('processed_video_copy_and_caption_readback_required')
            if d.get('thumbnail_asset_id') and not state.get('thumbnail_acknowledged'):
                raise DeliveryError('bound_thumbnail_acknowledgement_required')
            allowed = {'privacyStatus', 'embeddable', 'license', 'publicStatsViewable', 'selfDeclaredMadeForKids', 'containsSyntheticMedia'}
            status = {k: v for k, v in state['provider_status'].items() if k in allowed}
            status['privacyStatus'] = 'public'
            vid = self._id(state.get('video_id'))
            def interpret(r):
                if r.data.get('id') != vid or r.data.get('status', {}).get('privacyStatus') != 'public':
                    raise DeliveryError('youtube_publication_acknowledgement_unresolved')
                return {'state': 'PUBLICATION_ACKNOWLEDGED_REQUIRES_READBACK', 'video_id': vid}
            return self._write(d, action, {'video_id': vid, 'status': status},
                lambda: self._request(d, 'PUT', 'https://www.googleapis.com/youtube/v3/videos?part=status', json_body={'id': vid, 'status': status}),
                interpret)
        raise DeliveryError('unsupported_youtube_operation')

    def _instagram(self, d, state, action):
        video, path = self._file(d)
        if self.meta_login != 'facebook_business':
            raise DeliveryError('instagram_binary_resumable_requires_facebook_business_login')
        if action == 'start':
            body = {'media_type': 'REELS', 'upload_type': 'resumable', 'caption': d['description'], 'is_ai_generated': True}
            if 'cover_timestamp_ms' in d:
                body['thumb_offset'] = d['cover_timestamp_ms']
            return self._write(d, action, body, lambda: self._request(d, 'POST', self._graph(d['account_id'], 'media'), json_body=body),
                lambda r: {'state': 'NONPUBLIC_CONTAINER_CREATED', 'container_id': self._id(r.data.get('id'))})
        cid = self._id(state.get('container_id'))
        if action == 'upload':
            return self._write(d, action, {'container_id': cid, 'video_sha256': video['sha256']},
                lambda: self._request(d, 'POST', 'https://rupload.facebook.com/ig-api-upload/' + self.version + '/' + cid,
                    oauth=True, body=FileSlice(path, 0, video['bytes']), headers={'offset': '0', 'file_size': str(video['bytes']), 'Content-Type': 'application/octet-stream'}), self._success)
        if action == 'status':
            r = self._request(d, 'GET', self._graph(cid, fields='status_code'))
            code = r.data.get('status_code')
            if r.status != 200 or code not in {'IN_PROGRESS', 'FINISHED', 'PUBLISHED', 'ERROR', 'EXPIRED'}:
                raise DeliveryError('instagram_container_status_unresolved')
            return {'state': 'CONTAINER_STATUS_OBSERVED', 'status_code': code, 'ready': code == 'FINISHED',
                    'public_post_observed': code == 'PUBLISHED'}
        if action == 'publish':
            if not state.get('ready'):
                raise DeliveryError('finished_container_readback_required')
            return self._write(d, action, {'container_id': cid},
                lambda: self._request(d, 'POST', self._graph(d['account_id'], 'media_publish'), json_body={'creation_id': cid}),
                lambda r: {'state': 'PUBLICATION_ACKNOWLEDGED_REQUIRES_READBACK', 'media_id': self._id(r.data.get('id'))})
        raise DeliveryError('unsupported_instagram_operation_use_caption_delivery_handoff')

    def _facebook(self, d, state, action):
        video, path = self._file(d)
        if action == 'start':
            def interpret(r):
                vid = self._id(r.data.get('video_id'))
                url = r.data.get('upload_url', '')
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or parsed.netloc != 'rupload.facebook.com' or not parsed.path.startswith('/video-upload/') or not parsed.path.endswith('/' + vid):
                    raise DeliveryError('facebook_upload_location_missing')
                self.capabilities[d['key']] = url
                return {'state': 'NONPUBLIC_VIDEO_UPLOAD_STARTED', 'video_id': vid, 'upload_capability_persisted': False}
            return self._write(d, action, {'page_id': d['account_id']},
                lambda: self._request(d, 'POST', self._graph(d['account_id'], 'video_reels'), json_body={'upload_phase': 'start'}), interpret)
        vid = self._id(state.get('video_id'))
        if action == 'upload':
            if d['key'] not in self.capabilities:
                raise DeliveryError('lost_upload_capability_requires_reconciliation_no_new_session')
            return self._write(d, action, {'video_id': vid, 'video_sha256': video['sha256']},
                lambda: self._request(d, 'POST', self.capabilities[d['key']], oauth=True,
                    body=FileSlice(path, 0, video['bytes']), headers={'offset': '0', 'file_size': str(video['bytes']), 'Content-Type': 'application/octet-stream'}), self._success)
        if action == 'status':
            r = self._request(d, 'GET', self._graph(vid, fields='status,permalink_url'))
            if r.status != 200 or not isinstance(r.data.get('status'), dict):
                raise DeliveryError('facebook_processing_status_unresolved')
            info = r.data['status']
            return {'state': 'PAGE_VIDEO_STATUS_OBSERVED', 'video_id': vid,
                'ready': info.get('video_status') == 'ready',
                'bytes_transferred': info.get('uploading_phase', {}).get('bytes_transfered'),
                'publish_status': info.get('publishing_phase', {}).get('publish_status')}
        if action in {'stage_draft', 'publish'}:
            if not state.get('ready'):
                raise DeliveryError('facebook_ready_processing_readback_required')
            body = {'upload_phase': 'finish', 'video_id': vid, 'video_state': 'DRAFT' if action == 'stage_draft' else 'PUBLISHED',
                    'title': d['title'], 'description': d['description'], 'is_ai_generated': True}
            return self._write(d, action, body,
                lambda: self._request(d, 'POST', self._graph(d['account_id'], 'video_reels'), json_body=body),
                lambda r: {**self._success(r), 'state': 'DRAFT_FINISH_ACKNOWLEDGED' if action == 'stage_draft' else 'PUBLICATION_ACKNOWLEDGED_REQUIRES_READBACK', 'video_id': vid})
        raise DeliveryError('unsupported_facebook_reel_operation')

    def _x(self, d, state, action):
        video, path = self._file(d)
        if action == 'start':
            body = {'media_type': 'video/mp4', 'total_bytes': video['bytes'], 'media_category': 'tweet_video'}
            return self._write(d, action, body,
                lambda: self._request(d, 'POST', 'https://api.x.com/2/media/upload/initialize', json_body=body),
                lambda r: {'state': 'NONPUBLIC_MEDIA_INITIALIZED', 'media_id': self._id(r.data.get('data', {}).get('id'))})
        mid = self._id(state.get('media_id'))
        if action == 'upload':
            def send():
                with path.open('rb') as source:
                    for index, offset in enumerate(range(0, video['bytes'], CHUNK)):
                        chunk = source.read(min(CHUNK, video['bytes'] - offset))
                        boundary = 'earnalism-' + self.plan['candidate_sha256'] + '-' + str(index)
                        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="segment_index"\r\n\r\n{index}\r\n'
                            f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="chunk.mp4"\r\n'
                            'Content-Type: application/octet-stream\r\n\r\n').encode() + chunk + ('\r\n--' + boundary + '--\r\n').encode()
                        r = self._request(d, 'POST', 'https://api.x.com/2/media/upload/' + mid + '/append', body=body,
                            headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
                        if not 200 <= r.status < 300:
                            raise DeliveryError('x_append_outcome_requires_reconciliation')
                return r
            return self._write(d, action, {'media_id': mid, 'video_sha256': video['sha256']}, send,
                lambda r: {'state': 'MEDIA_SEGMENTS_ACKNOWLEDGED', 'media_id': mid})
        if action == 'finalize':
            def interpret(r):
                data = r.data.get('data', {})
                if data.get('id') != mid:
                    raise DeliveryError('x_media_finalize_acknowledgement_missing')
                return {'state': 'MEDIA_FINALIZE_ACKNOWLEDGED', 'media_id': mid,
                        'ready': data.get('processing_info') is None or data.get('processing_info', {}).get('state') == 'succeeded'}
            return self._write(d, action, {'media_id': mid},
                lambda: self._request(d, 'POST', 'https://api.x.com/2/media/upload/' + mid + '/finalize'),
                interpret)
        if action == 'status':
            r = self._request(d, 'GET', 'https://api.x.com/2/media/upload?' + urlencode({'command': 'STATUS', 'media_id': mid}))
            if r.status != 200 or r.data.get('data', {}).get('id') != mid:
                raise DeliveryError('x_media_status_unresolved')
            info = r.data['data'].get('processing_info')
            return {'state': 'MEDIA_PROCESSING_STATUS_OBSERVED', 'media_id': mid,
                    'ready': info is None or info.get('state') == 'succeeded'}
        if action == 'publish':
            if not state.get('ready'):
                raise DeliveryError('x_processed_media_readback_required')
            body = {'text': d['description'], 'media': {'media_ids': [mid]}, 'made_with_ai': True}
            return self._write(d, action, body,
                lambda: self._request(d, 'POST', 'https://api.x.com/2/tweets', json_body=body),
                lambda r: {'state': 'PUBLICATION_ACKNOWLEDGED_REQUIRES_READBACK', 'post_id': self._id(r.data.get('data', {}).get('id'))})
        raise DeliveryError('unsupported_x_operation_use_caption_delivery_handoff')
