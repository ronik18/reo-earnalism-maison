import contextlib
import io
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from operations.production_delivery import main, execute_private
from operations.production_bundle import BundleError
from operations.test_production_bundle import fixture
from operations.social_delivery.test_bridge import FakeHTTP, reply


class PrivateEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.bundle = fixture(self.root)
        self.path = self.root / 'bundle.json'; self.path.write_text(json.dumps(self.bundle))

    def test_default_preparation_has_zero_provider_or_model_requests(self):
        output = io.StringIO()
        with patch('socket.create_connection', side_effect=AssertionError('network')), contextlib.redirect_stdout(output):
            self.assertEqual(main(['prepare', '--bundle', str(self.path), '--assets', str(self.root)]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['provider_requests'], 0)
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse(result['publication'])

    def test_stage_without_execute_needs_no_auth_or_journal(self):
        with patch.dict('os.environ', {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['maison-stage', '--bundle', str(self.path), '--assets', str(self.root)]), 0)

    def test_no_publication_cli_exists(self):
        for args in (['publish'], ['social-stage', '--bundle', str(self.path), '--assets', str(self.root), '--action', 'publish']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): main(args)

    def test_nonprivate_candidate_cannot_execute(self):
        self.bundle['private'] = False
        with self.assertRaisesRegex(BundleError, 'PRIVATE_CANDIDATE'):
            execute_private(self.bundle, self.root, destination='maison', journal_dir=self.root / 'journal')

    def test_held_errors_do_not_expose_capabilities(self):
        output = io.StringIO()
        with patch('operations.production_delivery.load_bundle', side_effect=RuntimeError('https://private.example/?sig=secret')), contextlib.redirect_stdout(output):
            self.assertEqual(main(['prepare', '--bundle', str(self.path), '--assets', str(self.root)]), 1)
        self.assertNotIn('secret', output.getvalue()); self.assertNotIn('private.example', output.getvalue())

    def test_unknown_opaque_credential_exception_is_not_an_error_code(self):
        output = io.StringIO()
        with patch('operations.production_delivery.load_bundle', side_effect=RuntimeError('OpaqueCredential123')), contextlib.redirect_stdout(output):
            self.assertEqual(main(['prepare', '--bundle', str(self.path), '--assets', str(self.root)]), 1)
        self.assertNotIn('OpaqueCredential123', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['error_code'], 'RuntimeError')

    def test_output_never_overwrites_an_asset(self):
        before = (self.root / 'source.txt').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['prepare', '--bundle', str(self.path), '--assets', str(self.root),
                                   '--output', str(self.root / 'source.txt')]), 1)
        self.assertEqual((self.root / 'source.txt').read_bytes(), before)

    def test_actual_delivery_private_upload_then_restarted_status_does_not_upload_again(self):
        raw = b'source-bound local protocol fixture, not released media'
        (self.root / 'film.mp4').write_bytes(raw)
        self.bundle['assets'].append(dict(id='film', path='film.mp4', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
            content_type='video/mp4', role='video'))
        self.bundle['social'] = [dict(platform='youtube', account_id='channel1', video_asset_id='film',
            title='Exact candidate', description='Exact source-bound description', made_for_kids=False)]
        def status(processing):
            return reply({'items': [{'id': 'video1', 'snippet': {'channelId': 'channel1',
                'title': 'Exact candidate', 'description': 'Exact source-bound description'},
                'processingDetails': {'processingStatus': processing}, 'status': {'privacyStatus': 'private'}}]})
        first = FakeHTTP(reply({'items': [{'id': 'channel1'}]}),
            reply(location='https://www.googleapis.com/upload/youtube/v3/videos?capability=DO_NOT_RETAIN'),
            reply({'id': 'video1'}, 201), status('processing'))
        kwargs = dict(destination='social', platform='youtube', account='channel1',
            journal_dir=self.root / 'social-journal', environ={'EARNALISM_YOUTUBE_ACCESS_TOKEN': 'in-memory-fixture-only'})
        probe = dict(width=1920, height=1080, duration_seconds=30, codec='h264')
        with patch('operations.social_delivery.bridge._probe', return_value=probe), \
                patch('operations.social_delivery.bridge.HTTPSClient', return_value=first):
            result = execute_private(self.bundle, self.root, **kwargs)
        self.assertFalse(result['processing_ready']); self.assertFalse(result['publication'])
        self.assertEqual([c[0] for c in first.calls], ['GET', 'POST', 'PUT', 'GET'])
        self.assertEqual(first.calls[1][2]['json_body']['status']['privacyStatus'], 'private')
        self.assertIn('capability=DO_NOT_RETAIN', first.calls[2][1])
        for action in ('status', 'private-upload'):
            restarted = FakeHTTP(reply({'items': [{'id': 'channel1'}]}), status('succeeded'))
            with patch('operations.social_delivery.bridge._probe', return_value=probe), \
                    patch('operations.social_delivery.bridge.HTTPSClient', return_value=restarted):
                result = execute_private(self.bundle, self.root, action=action, **kwargs)
            self.assertEqual([c[0] for c in restarted.calls], ['GET', 'GET'])
            self.assertTrue(result.get('ready', result.get('processing_ready')))
        retained = ''.join(p.read_text() for p in (self.root / 'social-journal').glob('*.json'))
        self.assertNotIn('DO_NOT_RETAIN', retained); self.assertNotIn('in-memory-fixture-only', retained)
        self.assertEqual((self.root / 'film.mp4').read_bytes(), raw)

    def test_actual_facebook_delivery_uses_explicit_version_and_private_draft(self):
        raw = b'source-bound local portrait fixture'
        (self.root / 'portrait.mp4').write_bytes(raw)
        self.bundle['assets'].append(dict(id='portrait', path='portrait.mp4', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
            content_type='video/mp4', role='video'))
        self.bundle['social'] = [dict(platform='facebook', account_id='page1', video_asset_id='portrait',
            title='Exact candidate', description='Exact description')]
        fake = FakeHTTP(reply({'id': 'page1'}), reply({'video_id': 'video1',
            'upload_url': 'https://rupload.facebook.com/video-upload/v27.0/video1'}), reply({'success': True}),
            reply({'status': {'video_status': 'ready'}}), reply({'success': True}))
        with patch('operations.social_delivery.bridge._probe', return_value=dict(width=1080, height=1920, duration_seconds=30, codec='h264')), \
                patch('operations.social_delivery.bridge.HTTPSClient', return_value=fake):
            result = execute_private(self.bundle, self.root, destination='social', platform='facebook', account='page1',
                journal_dir=self.root / 'facebook-journal', environ={'EARNALISM_FACEBOOK_ACCESS_TOKEN': 'in-memory-only',
                                                                   'EARNALISM_META_GRAPH_VERSION': 'v27.0'})
        self.assertFalse(result['publication']); self.assertEqual(fake.calls[-1][2]['json_body']['video_state'], 'DRAFT')
        self.assertTrue(all('PUBLISHED' not in str(c[2].get('json_body', {})) for c in fake.calls))


if __name__ == '__main__': unittest.main()
