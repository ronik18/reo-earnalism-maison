"""Local byte bindings and mocked official protocols; no account/network calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from operations.production_bundle import BundleError, verify_bundle
from operations.production_journal import OperationJournal, UncertainOperation
from operations.social_delivery import Authority, Delivery, DeliveryError, prepare
from operations.social_delivery.http import FileSlice, HTTPSClient, Response, _LimitedFile


class FakeHTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError('unexpected provider request')
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def reply(data=None, status=200, **headers):
    return Response(status, headers, data or {})


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.assets = []
        for ident, raw, role, mime in [('film', b'bound-video-payload', 'video', 'video/mp4'),
                ('captions', b'1\n00:00:00,000 --> 00:00:01,000\nExact source\n', 'captions', 'application/x-subrip'),
                ('cover', b'bound-cover-payload', 'thumbnail', 'image/jpeg')]:
            (self.root / ident).write_bytes(raw)
            self.assets.append(dict(id=ident, path=ident, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), role=role, content_type=mime))

    def bundle(self, platform='youtube', private=True, captions=False, cover=False, **extra):
        target = dict(platform=platform, account_id='account1', video_asset_id='film', title='Exact title', description='Exact description')
        if platform == 'youtube': target['made_for_kids'] = False
        if captions: target['caption_asset_id'] = 'captions'
        if cover: target['thumbnail_asset_id'] = 'cover'
        target.update(extra)
        return dict(schema='earnalism.production_bundle.v1', project_id='private-local-protocol-fixture', private=private,
            content=dict(text_sha256='a' * 64, language='en', voice_profile='en_tisha'),
            assets=deepcopy(self.assets), evidence=dict(qa=[], rights=[]), social=[target])

    def plan(self, platform='youtube', **options):
        return prepare(self.bundle(platform, **options), self.root,
            probe=lambda _: dict(width=1080, height=1920, duration_seconds=30, codec='h264'))

    def client(self, plan, http, authorize=lambda *args: True):
        journal = OperationJournal(self.root / ('journal-' + str(len(list(self.root.glob('journal-*'))))))
        version = 'v27.0' if any(d['platform'] in {'instagram', 'facebook'} for d in plan['destinations']) else None
        client = Delivery(plan, journal, lambda *args: 'in-memory-fixture-credential', authorize, http=http, graph_version=version)
        return client

    def step(self, client, action):
        d = client.plan['destinations'][0]
        authority = Authority(client.plan['candidate_sha256'], d['key'], d['account_id'], frozenset([action]), 'explicit-test-only')
        return client.run(d['key'], action, execute=True, authority=authority)

    def test_default_is_inert_and_source_mutation_is_rejected(self):
        plan = self.plan()
        http = FakeHTTP()
        client = self.client(plan, http)
        self.assertEqual(client.run('youtube:account1', 'start')['provider_requests'], 0)
        self.assertEqual(http.calls, [])
        (self.root / 'film').write_bytes(b'changed')
        with self.assertRaises(BundleError): self.step(client, 'start')
        self.assertEqual(http.calls, [])

    def test_authority_and_integrating_authorization_are_both_required(self):
        plan = self.plan()
        http = FakeHTTP()
        client = self.client(plan, http, authorize=lambda *args: False)
        with self.assertRaisesRegex(DeliveryError, 'integrating_caller_authorization_required'): self.step(client, 'start')
        bad = Authority('f' * 64, 'youtube:account1', 'account1', frozenset(['start']), 'not-consent')
        with self.assertRaisesRegex(DeliveryError, 'separate_candidate'): client.run('youtube:account1', 'start', execute=True, authority=bad)
        self.assertEqual(http.calls, [])

    def test_private_publication_is_impossible_for_every_platform(self):
        for platform in ('youtube', 'instagram', 'facebook', 'x'):
            client = self.client(self.plan(platform), FakeHTTP())
            with self.assertRaisesRegex(DeliveryError, 'private_candidate_cannot_be_published'):
                self.step(client, 'publish')
            self.assertEqual(client.http.calls, [])

    def test_destination_or_identity_mismatch_cannot_dispatch(self):
        client = self.client(self.plan(), FakeHTTP(reply({'items': [{'id': 'other'}]})))
        with self.assertRaisesRegex(DeliveryError, 'provider_account_mismatch'): self.step(client, 'start')
        self.assertEqual(len(client.http.calls), 1)
        client = self.client(self.plan(), FakeHTTP())
        client.plan['destinations'][0]['description'] = 'changed copy'
        with self.assertRaisesRegex(DeliveryError, 'destination_changed'): self.step(client, 'start')
        self.assertEqual(client.http.calls, [])

    def test_youtube_private_upload_caption_thumbnail_and_readback(self):
        http = FakeHTTP(reply({'items': [{'id': 'account1'}]}),
            reply(location='https://www.googleapis.com/upload/youtube/v3/videos?session=transient'),
            reply({'id': 'video1'}, 201),
            reply(location='https://www.googleapis.com/upload/youtube/v3/captions?session=transient'),
            reply({'id': 'caption1', 'snippet': {'status': 'serving'}}),
            reply({'items': [{'id': 'video1', 'snippet': {'channelId': 'account1', 'title': 'Exact title', 'description': 'Exact description'},
                'processingDetails': {'processingStatus': 'succeeded'}, 'status': {'privacyStatus': 'private'}}]}),
            reply({'items': [{'id': 'caption1', 'snippet': {'status': 'serving'}}]}),
            reply({'items': [{'default': {'url': 'https://provider-image.example/derived.jpg'}}]}))
        client = self.client(self.plan(captions=True, cover=True), http)
        self.step(client, 'start'); self.step(client, 'upload'); self.step(client, 'captions')
        self.assertTrue(self.step(client, 'status')['ready'])
        self.assertTrue(self.step(client, 'thumbnail')['thumbnail_acknowledged'])
        meta = http.calls[1][2]['json_body']
        self.assertEqual(meta['status']['privacyStatus'], 'private')
        self.assertIs(meta['status']['selfDeclaredMadeForKids'], False)
        self.assertIsInstance(http.calls[2][2]['body'], FileSlice)
        self.assertIn('/thumbnails/set?', http.calls[-1][1])
        self.assertEqual(http.calls[-1][2]['headers']['Content-Type'], 'image/jpeg')
        before = len(http.calls)
        self.step(client, 'thumbnail')
        self.assertEqual(len(http.calls), before)
        saved = ''.join(x.read_text() for x in client.journal.directory.glob('*.json'))
        self.assertNotIn('transient', saved); self.assertNotIn('in-memory-fixture-credential', saved)
        self.assertNotIn('https://', saved)

    def test_youtube_uncertain_upload_requires_status_and_explicit_resume(self):
        http = FakeHTTP(reply({'items': [{'id': 'account1'}]}),
            reply(location='https://www.googleapis.com/upload/youtube/v3/videos?capability=transient'),
            TimeoutError('raw secret URL must not enter receipt'), reply(status=308, range='bytes=0-7'), reply({'id': 'video1'}, 201))
        client = self.client(self.plan(), http)
        self.step(client, 'start')
        with self.assertRaisesRegex(DeliveryError, 'provider_outcome_unknown'): self.step(client, 'upload')
        count = len(http.calls)
        with self.assertRaises(UncertainOperation): self.step(client, 'upload')
        self.assertEqual(len(http.calls), count)
        self.assertEqual(self.step(client, 'reconcile_upload')['resume_offset'], 8)
        self.assertEqual(self.step(client, 'resume_upload')['video_id'], 'video1')
        self.assertEqual(http.calls[-1][2]['body'].offset, 8)
        self.assertEqual(http.calls[-1][2]['headers']['Content-Range'], 'bytes 8-18/19')
        restarted = Delivery(client.plan, client.journal, client.token_for, client.authorize,
                             http=FakeHTTP(reply({'items': [{'id': 'account1'}]})))
        self.step(restarted, 'start')  # Existing acknowledgement, not a second session.
        with self.assertRaisesRegex(DeliveryError, 'lost_upload_capability'): self.step(restarted, 'upload')
        self.assertEqual(len(restarted.http.calls), 1)
        self.assertNotIn('raw secret', ''.join(x.read_text() for x in client.journal.directory.glob('*.json')))

    def test_youtube_chunks_check_exact_committed_ranges(self):
        http = FakeHTTP(reply({'items': [{'id': 'account1'}]}),
            reply(location='https://www.googleapis.com/upload/youtube/v3/videos?session=transient'),
            reply(status=308, range='bytes=0-7'), reply(status=308, range='bytes=0-15'), reply({'id': 'v1'}, 201))
        client = self.client(self.plan(), http)
        self.step(client, 'start')
        with patch('operations.social_delivery.bridge.CHUNK', 8): self.step(client, 'upload')
        self.assertEqual([x[2]['body'].offset for x in http.calls[2:]], [0, 8, 16])

    def test_resumed_or_reconciled_completion_restores_id_for_fresh_get_only_runs(self):
        from operations.production_delivery import execute_private
        def observed_status():
            return reply({'items': [{'id': 'video1', 'snippet': {'channelId': 'account1',
                'title': 'Exact title', 'description': 'Exact description'},
                'processingDetails': {'processingStatus': 'succeeded'}, 'status': {'privacyStatus': 'private'}}]})
        for mode in ('resume', 'completed-reconciliation'):
            responses = [reply({'items': [{'id': 'account1'}]}),
                reply(location='https://www.googleapis.com/upload/youtube/v3/videos?session=TRANSIENT_ONLY'), TimeoutError()]
            responses += [reply(status=308, range='bytes=0-7'), reply({'id': 'video1'}, 201)] if mode == 'resume' else [reply({'id': 'video1'})]
            original = self.client(self.plan(), FakeHTTP(*responses))
            self.step(original, 'start')
            with self.assertRaises(DeliveryError): self.step(original, 'upload')
            self.step(original, 'reconcile_upload')
            if mode == 'resume': self.step(original, 'resume_upload')
            prefix = 'social:' + original.plan['candidate_sha256'] + ':youtube:account1:'
            completed = original.journal.read(prefix + 'completed-upload')
            self.assertEqual(completed['state'], 'acknowledged')
            self.assertEqual(completed['result'], {'video_id': 'video1', 'upload_completed': True})
            # The original uncertain request remains recorded; canonical completion
            # is evidence from a later real protocol acknowledgement, not replay.
            self.assertEqual(original.journal.read(prefix + 'upload:0')['state'], 'unknown')
            fresh_http = FakeHTTP(reply({'items': [{'id': 'account1'}]}), observed_status())
            fresh = Delivery(original.plan, original.journal, original.token_for, original.authorize, http=fresh_http)
            self.assertEqual(fresh.capabilities, {}); self.assertEqual(fresh.state, {})
            self.assertTrue(self.step(fresh, 'status')['ready'])
            self.assertTrue(fresh.state['youtube:account1']['upload_completed'])
            self.assertEqual([x[0] for x in fresh_http.calls], ['GET', 'GET'])
            cli_http = FakeHTTP(reply({'items': [{'id': 'account1'}]}), observed_status())
            with patch('operations.social_delivery.bridge._probe', return_value=dict(width=1080, height=1920, duration_seconds=30, codec='h264')), \
                    patch('operations.social_delivery.bridge.HTTPSClient', return_value=cli_http):
                result = execute_private(original.plan['manifest'], self.root, destination='social',
                    journal_dir=original.journal.directory, platform='youtube', account='account1',
                    environ={'EARNALISM_YOUTUBE_ACCESS_TOKEN': 'in-memory-test-only'})
            self.assertTrue(result['processing_ready']); self.assertFalse(result['publication'])
            self.assertEqual([x[0] for x in cli_http.calls], ['GET', 'GET'])

    def test_unknown_start_cannot_be_replayed_and_malformed_ack_is_not_success(self):
        http = FakeHTTP(reply({'items': [{'id': 'account1'}]}), TimeoutError('provider token=secret'))
        client = self.client(self.plan(), http)
        with self.assertRaises(DeliveryError): self.step(client, 'start')
        with self.assertRaises(UncertainOperation): self.step(client, 'start')
        self.assertEqual(len(http.calls), 2)
        other = self.client(self.plan('instagram'), FakeHTTP(reply({'id': 'page1', 'instagram_business_account': {'id': 'account1'}}), reply({})))
        with self.assertRaisesRegex(DeliveryError, 'provider_resource_id_missing'): self.step(other, 'start')
        self.assertNotIn('provider token', ''.join(x.read_text() for x in client.journal.directory.glob('*.json')))

    def test_instagram_binary_container_never_publishes_privately(self):
        http = FakeHTTP(reply({'id': 'page1', 'instagram_business_account': {'id': 'account1'}}), reply({'id': 'container1'}), reply({'success': True}), reply({'status_code': 'FINISHED'}))
        client = self.client(self.plan('instagram'), http)
        self.step(client, 'start'); self.step(client, 'upload')
        self.assertTrue(self.step(client, 'status')['ready'])
        self.assertEqual(http.calls[1][2]['json_body']['upload_type'], 'resumable')
        self.assertIn('/ig-api-upload/v27.0/container1', http.calls[2][1])
        self.assertTrue(http.calls[2][2]['headers']['Authorization'].startswith('OAuth '))
        self.assertNotIn('media_publish', ''.join(x[1] for x in http.calls))

    def test_instagram_cover_frame_is_explicit_bounded_and_not_a_separate_image(self):
        http = FakeHTTP(reply({'id': 'page1', 'instagram_business_account': {'id': 'account1'}}), reply({'id': 'container1'}))
        client = self.client(self.plan('instagram', cover_timestamp_ms=1234), http)
        self.step(client, 'start')
        self.assertEqual(http.calls[-1][2]['json_body']['thumb_offset'], 1234)
        self.assertNotIn('cover_url', http.calls[-1][2]['json_body'])
        with self.assertRaisesRegex(DeliveryError, 'cover_frame_within_actual_video'):
            self.plan('instagram', cover_timestamp_ms=30_000)
        client = self.client(self.plan('instagram', private=False, cover=True, cover_timestamp_ms=1000), FakeHTTP())
        with self.assertRaisesRegex(DeliveryError, 'separate_thumbnail_requires_supported_delivery_handoff'):
            self.step(client, 'publish')
        self.assertEqual(client.http.calls, [])

    def test_facebook_page_reel_finishes_draft_only(self):
        http = FakeHTTP(reply({'id': 'account1'}), reply({'video_id': 'video1', 'upload_url': 'https://rupload.facebook.com/video-upload/v27.0/video1'}),
            reply({'success': True}), reply({'status': {'video_status': 'ready', 'uploading_phase': {'bytes_transfered': 19}}}), reply({'success': True}))
        client = self.client(self.plan('facebook'), http)
        self.step(client, 'start'); self.step(client, 'upload'); self.step(client, 'status')
        self.assertEqual(self.step(client, 'stage_draft')['state'], 'DRAFT_FINISH_ACKNOWLEDGED')
        self.assertEqual(http.calls[-1][2]['json_body']['video_state'], 'DRAFT')
        self.assertEqual(http.calls[-1][2]['json_body']['upload_phase'], 'finish')
        with self.assertRaisesRegex(DeliveryError, 'portrait_3_to_90'):
            prepare(self.bundle('facebook'), self.root, probe=lambda _: dict(width=1920, height=1080, duration_seconds=30))

    def test_x_current_dedicated_protocol_and_processing_evidence(self):
        http = FakeHTTP(reply({'data': {'id': 'account1'}}), reply({'data': {'id': 'media1'}}), reply(status=204),
            reply({'data': {'id': 'media1', 'processing_info': {'state': 'pending'}}}),
            reply({'data': {'id': 'media1', 'processing_info': {'state': 'succeeded'}}}))
        client = self.client(self.plan('x'), http)
        self.step(client, 'start'); self.step(client, 'upload')
        self.assertFalse(self.step(client, 'finalize')['ready'])
        self.assertTrue(self.step(client, 'status')['ready'])
        urls = [x[1] for x in http.calls]
        self.assertTrue(urls[1].endswith('/initialize'))
        self.assertTrue(urls[2].endswith('/media1/append'))
        self.assertTrue(urls[3].endswith('/media1/finalize'))
        self.assertIn('command=STATUS', urls[4])
        self.assertNotIn('command=INIT', ''.join(urls))
        self.assertIn(b'name="segment_index"', http.calls[2][2]['body'])
        self.assertNotIn('/2/tweets', ''.join(urls))

    def test_x_empty_finalize_response_remains_unknown(self):
        client = self.client(self.plan('x'), FakeHTTP(reply({'data': {'id': 'account1'}}), reply({'data': {'id': 'media1'}}), reply({})))
        self.step(client, 'start')
        with self.assertRaisesRegex(DeliveryError, 'finalize_acknowledgement_missing'): self.step(client, 'finalize')
        with self.assertRaises(UncertainOperation): self.step(client, 'finalize')

    def test_future_nonprivate_publish_needs_processing_and_real_ack(self):
        client = self.client(self.plan(private=False), FakeHTTP(reply({'items': [{'id': 'account1'}]})))
        with self.assertRaisesRegex(DeliveryError, 'processed_video'): self.step(client, 'publish')
        client.state['youtube:account1'] = dict(ready=True, copy_matches=True, caption_ready=True,
            video_id='video1', provider_status=dict(privacyStatus='private', embeddable=False))
        client.http.responses.append(reply({'id': 'video1', 'status': {'privacyStatus': 'public'}}))
        result = self.step(client, 'publish')
        self.assertEqual(result['state'], 'PUBLICATION_ACKNOWLEDGED_REQUIRES_READBACK')
        self.assertIs(client.http.calls[-1][2]['json_body']['status']['embeddable'], False)

    def test_local_probe_restricts_network_protocols(self):
        with patch('operations.social_delivery.bridge.subprocess.run') as call:
            call.return_value.stdout = json.dumps(dict(streams=[dict(width=1080, height=1920, codec_name='h264')], format=dict(duration='30')))
            prepare(self.bundle(), self.root)
        command = call.call_args.args[0]
        self.assertEqual(command[command.index('-protocol_whitelist') + 1], 'file,pipe')

    def test_meta_version_is_explicit_and_page_token_is_account_bound(self):
        for platform in ('instagram', 'facebook'):
            with self.assertRaisesRegex(DeliveryError, 'explicit_meta_api_version_required'):
                Delivery(self.plan(platform), None, None, None, http=FakeHTTP())
        for platform in ('youtube', 'x'):
            Delivery(self.plan(platform), None, None, None, http=FakeHTTP())
        http = FakeHTTP(reply({'id': 'page1', 'instagram_business_account': {'id': 'another-account'}}))
        client = self.client(self.plan('instagram'), http)
        with self.assertRaisesRegex(DeliveryError, 'provider_account_mismatch'): self.step(client, 'start')
        self.assertIn('/me?fields=id%2Cinstagram_business_account', http.calls[0][1])
        self.assertEqual(len(http.calls), 1)
        http = FakeHTTP(reply({'id': 'another-page'}))
        client = self.client(self.plan('facebook'), http)
        with self.assertRaisesRegex(DeliveryError, 'provider_account_mismatch'): self.step(client, 'start')
        self.assertIn('/me?fields=id', http.calls[0][1])

    def test_request_issuer_rejects_sensitive_header_overrides(self):
        client = self.client(self.plan(), FakeHTTP())
        for key in ('Authorization', 'Host', 'Cookie', 'Content-Length', 'Transfer-Encoding'):
            with self.assertRaisesRegex(DeliveryError, 'request_issuer_owns_sensitive_headers'):
                client._request(client.plan['destinations'][0], 'GET', 'https://www.googleapis.com/youtube/v3/channels', headers={key: 'untrusted'})
        self.assertEqual(client.http.calls, [])

    def test_observed_nonprivate_visibility_holds_without_privacy_changes(self):
        for visibility in ('public', 'unlisted', None):
            status = {} if visibility is None else {'privacyStatus': visibility}
            fake = FakeHTTP(reply({'items': [{'id': 'account1'}]}), reply({'items': [{'id': 'video1',
                'snippet': {'channelId': 'account1', 'title': 'Exact title', 'description': 'Exact description'},
                'processingDetails': {'processingStatus': 'succeeded'}, 'status': status}]}))
            client = self.client(self.plan(), fake)
            client.state['youtube:account1'] = {'video_id': 'video1'}
            with self.assertRaisesRegex(DeliveryError, 'private_scope_conflicts_with_observed_provider_visibility'):
                self.step(client, 'status')
            self.assertNotIn('ready', client.state['youtube:account1'])
            self.assertEqual([x[0] for x in fake.calls], ['GET', 'GET'])
        for platform, identity, provider_status, ids in (
                ('instagram', {'id': 'page1', 'instagram_business_account': {'id': 'account1'}}, {'status_code': 'PUBLISHED'}, {'container_id': 'container1'}),
                ('facebook', {'id': 'account1'}, {'status': {'video_status': 'ready', 'publishing_phase': {'publish_status': 'published'}}}, {'video_id': 'video1'})):
            fake = FakeHTTP(reply(identity), reply(provider_status))
            client = self.client(self.plan(platform), fake); client.state[platform + ':account1'] = ids
            with self.assertRaisesRegex(DeliveryError, 'private_scope_conflicts_with_observed_provider_visibility'):
                self.step(client, 'status')
            self.assertNotIn('ready', client.state[platform + ':account1'])
            self.assertEqual([x[0] for x in fake.calls], ['GET', 'GET'])


class TransportTests(unittest.TestCase):
    def test_foreign_origin_and_header_injection_never_open_connection(self):
        with patch('operations.social_delivery.http.http.client.HTTPSConnection') as connection:
            for url in ('http://api.x.com/2/users/me', 'https://attacker.example/', 'https://api.x.com@attacker.example/', 'https://api.x.com:444/'):
                with self.assertRaises(ValueError): HTTPSClient().request('GET', url, headers={})
            with self.assertRaises(ValueError): HTTPSClient().request('GET', 'https://api.x.com/2/users/me', headers={'Authorization': 'Bearer x\nInjected: yes'})
            with self.assertRaises(ValueError): HTTPSClient().request('GET', 'https://api.x.com/2/users/me', headers={'X-Bad\nInjected': 'value'})
            connection.assert_not_called()

    def test_file_body_is_bounded_and_response_redirect_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'file'; path.write_bytes(b'0123456789')
            stream = _LimitedFile(FileSlice(path, 3, 4))
            try:
                self.assertEqual(stream.read(2), b'34'); self.assertEqual(stream.read(99), b'56'); self.assertEqual(stream.read(), b'')
            finally: stream.close()
            with patch('operations.social_delivery.http.http.client.HTTPSConnection') as connection:
                response = connection.return_value.getresponse.return_value
                response.status = 307; response.read.return_value = b'{}'
                response.getheaders.return_value = [('Location', 'https://attacker.example/')]
                value = HTTPSClient().request('PUT', 'https://www.googleapis.com/upload/youtube/test', headers={}, body=FileSlice(path, 3, 4))
                self.assertEqual(value.status, 307)
                self.assertEqual(connection.call_count, 1)
                kwargs = connection.return_value.request.call_args.kwargs
                self.assertIsInstance(kwargs['body'], _LimitedFile)
                self.assertEqual(kwargs['headers']['Content-Length'], '4')


if __name__ == '__main__':
    unittest.main()
