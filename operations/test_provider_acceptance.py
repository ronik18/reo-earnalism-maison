"""Offline finite preparation tests. Fixture bytes and probe results are synthetic."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from operations.production_bundle import BundleError, verify_bundle
from operations.provider_acceptance import AcceptanceError, prepare_acceptance


VIDEO = {'duration_seconds': 5.041667, 'duration_ms': 5042,
    'container': 'mov,mp4,m4a,3gp,3g2,mj2',
    'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1280, 'height': 704}]}


class ProviderAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        assets = []
        for name, role, mime, raw in [('video', 'video', 'video/mp4', b'SYNTHETIC_VIDEO_TEST_BYTES'),
                ('source', 'source_text', 'text/plain', b'Synthetic source, not a release candidate'),
                ('qa', 'qa_report', 'application/json', b'{"synthetic":true}')]:
            (self.root / name).write_bytes(raw)
            assets.append(dict(id=name, path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), role=role, content_type=mime))
        assets[0]['duration_ms'] = 5042
        self.manifest = dict(schema='earnalism.production_bundle.v1', project_id='synthetic-acceptance-only', private=True,
            content=dict(text_sha256=assets[1]['sha256'], language='en', voice_profile='en_tisha',
                source_text_asset_id='source', source_text_sha256=assets[1]['sha256']),
            assets=assets, evidence=dict(qa=['qa'], rights=[]), social=[])

    def prepare(self, observations=None):
        with patch('operations.provider_acceptance._measure', return_value=deepcopy(VIDEO)):
            return prepare_acceptance(self.manifest, self.root, observations=observations)

    def test_actual_bytes_bind_finite_private_scope_without_invented_identities(self):
        result = self.prepare()
        self.assertEqual(result['candidate_sha256'], verify_bundle(self.manifest, self.root))
        self.assertFalse(result['execution_enabled']); self.assertFalse(result['publication'])
        self.assertEqual(result['provider_requests'], 0); self.assertEqual(result['credential_reads'], 0)
        scope = {x['provider']: x for x in result['proposed_provider_scope']}
        self.assertEqual(set(scope), {'stream', 'youtube', 'x', 'facebook', 'instagram'})
        for name in ('stream', 'youtube', 'x'):
            self.assertIsNone(scope[name]['account_id'])
            self.assertEqual(scope[name]['maximum_new_media_objects'], 1)
            self.assertEqual(scope[name]['maximum_source_upload_bytes'], self.manifest['assets'][0]['bytes'])
            self.assertFalse(scope[name]['execution_enabled'])
        self.assertEqual(result['maison_draft_identity'], {})
        self.assertIn('MAISON_DRAFT_AND_UNIT_IDENTITIES_UNBOUND', scope['stream']['gates'])
        self.assertTrue(result['content_quality_and_rights']['video_only_cannot_qualify_soundtrack_or_full_film_playback'])
        self.assertFalse(result['content_quality_and_rights']['release_ready'])

    def test_landscape_facebook_and_unbound_instagram_are_held_without_transformation(self):
        result = self.prepare(); scope = {x['provider']: x for x in result['proposed_provider_scope']}
        self.assertTrue(scope['facebook']['local_candidate_state'].startswith('HELD_'))
        self.assertTrue(scope['instagram']['local_candidate_state'].startswith('HELD_'))
        self.assertEqual(scope['facebook']['maximum_new_media_objects'], 0)
        self.assertEqual(scope['instagram']['proposed_steps'], [])
        self.assertFalse(result['new_generation']); self.assertFalse(result['new_encoding'])

    def test_supplied_real_destination_ids_are_preserved_and_never_synthesized(self):
        self.manifest['social'] = [dict(platform='youtube', account_id='SYNTHETIC_EXPLICIT_ACCOUNT',
            video_asset_id='video', title='Synthetic local test', description='No real account request', made_for_kids=False)]
        result = self.prepare(); scope = {x['provider']: x for x in result['proposed_provider_scope']}
        self.assertEqual(scope['youtube']['account_id'], 'SYNTHETIC_EXPLICIT_ACCOUNT')
        self.assertIsNone(scope['x']['account_id'])

    def test_bound_draft_still_requires_actual_video_unit(self):
        self.manifest['content'].update(edition_id=str(uuid.uuid4()), revision_id=str(uuid.uuid4()), expected_etag='"v1"')
        scope = {x['provider']: x for x in self.prepare()['proposed_provider_scope']}
        self.assertIn('MAISON_DRAFT_AND_UNIT_IDENTITIES_UNBOUND', scope['stream']['gates'])
        self.manifest['assets'][0]['unit_id'] = str(uuid.uuid4())
        scope = {x['provider']: x for x in self.prepare()['proposed_provider_scope']}
        self.assertNotIn('MAISON_DRAFT_AND_UNIT_IDENTITIES_UNBOUND', scope['stream']['gates'])
        self.assertIn('ACTUAL_PRIVATE_UPLOAD_PROCESSING_AND_READBACK_UNPERFORMED', scope['stream']['gates'])

    def test_source_and_QA_resource_budget_does_not_create_rights_or_quality(self):
        result = self.prepare(); source = result['r2_source_transfer']
        self.assertEqual(source['maximum_new_objects'], 2)
        self.assertEqual(source['maximum_source_upload_bytes'], sum(x['bytes'] for x in self.manifest['assets'][1:]))
        self.assertEqual(result['content_quality_and_rights']['supplied_rights_assets'], [])
        self.assertEqual(result['content_quality_and_rights']['actual_listening'], 'UNASSESSED')

    def test_changed_source_nonprivate_and_duration_mismatch_are_not_prepared(self):
        original = (self.root / 'video').read_bytes()
        (self.root / 'video').write_bytes(b'changed')
        with self.assertRaises(BundleError): self.prepare()
        (self.root / 'video').write_bytes(original)
        self.manifest['private'] = False
        with self.assertRaisesRegex(AcceptanceError, 'PRIVATE_TRANSPORT'): self.prepare()
        self.manifest['private'] = True; self.manifest['assets'][0]['duration_ms'] = 5041
        with self.assertRaisesRegex(AcceptanceError, 'DURATION_CHANGED'): self.prepare()

    def test_no_environment_HTTP_or_account_call_is_needed(self):
        with (patch('os.getenv', side_effect=AssertionError('credential lookup')),
                patch('socket.create_connection', side_effect=AssertionError('provider HTTP')),
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('provider HTTP'))):
            result = self.prepare()
        self.assertEqual(result['model_calls'], 0)
        with self.assertRaises(TypeError):
            prepare_acceptance(self.manifest, self.root, execute=True)

    def observation(self):
        return dict(schema='earnalism.private_provider_observations.v1',
            candidate_sha256=verify_bundle(self.manifest, self.root), checks=[dict(provider='youtube',
                check='account_identity', result='OBSERVED', observed_at='2026-11-21T00:00:00Z', evidence_sha256='a' * 64)])

    def test_read_only_observation_is_hash_bound_but_never_grants_execution_or_acceptance(self):
        observations = self.observation(); result = self.prepare(observations)
        self.assertEqual(result['observations'], observations['checks'])
        self.assertTrue(result['observations_are_operator_supplied_not_independently_verified'])
        self.assertFalse(result['execution_enabled']); self.assertFalse(result['content_quality_and_rights']['release_ready'])
        observations['candidate_sha256'] = 'b' * 64
        with self.assertRaises(AcceptanceError): self.prepare(observations)

    def test_unsafe_observation_fields_and_invalid_times_are_rejected(self):
        for changes in ({'access_token': 'DO_NOT_STORE'}, {'observed_at': '2026-99-21T00:00:00Z'}, {'evidence_sha256': 'https://private.example/capability'}, {'result': 'PASS'}):
            observations = self.observation(); observations['checks'][0].update(changes)
            with self.subTest(changes=tuple(changes)), self.assertRaises(AcceptanceError): self.prepare(observations)

    def test_multiple_videos_exceed_finite_preparation_scope(self):
        original = self.manifest['assets'][0]; row = deepcopy(original); row.update(id='other', path='other')
        (self.root / 'other').write_bytes((self.root / 'video').read_bytes()); self.manifest['assets'].append(row)
        with self.assertRaisesRegex(AcceptanceError, 'ONE_RETAINED_VIDEO'): self.prepare()

    def test_nonconforming_retained_MP3_is_held_without_encoding(self):
        original = self.manifest['assets'][0]; original.update(role='audio', content_type='audio/mpeg', duration_ms=82686)
        mp3 = dict(duration_seconds=82.686259, duration_ms=82686, container='mp3',
            streams=[dict(codec_type='audio', codec_name='mp3', bit_rate='101576', sample_rate='44100', channels=1)])
        before = hashlib.sha256((self.root / 'video').read_bytes()).hexdigest()
        with patch('operations.provider_acceptance._measure', return_value=mp3):
            result = prepare_acceptance(self.manifest, self.root)
        self.assertEqual(result['proposed_provider_scope'], [])
        self.assertFalse(result['retained_media'][0]['existing_maison_audio_profile_supported'])
        self.assertEqual(result['retained_media'][0]['profile_result'], 'HELD_NO_ENCODING_AUTHORIZED')
        self.assertEqual(hashlib.sha256((self.root / 'video').read_bytes()).hexdigest(), before)


if __name__ == '__main__': unittest.main()
