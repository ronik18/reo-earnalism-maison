import hashlib
import json
import os
import tempfile
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import AuditEvent
from operations.management.commands import post_approved
from operations.models import ReviewItem
from operations.social_delivery import Authority, prepare
from operations.social_delivery.http import Response

TOKEN = 'in-memory-fixture-credential'


class FakeHTTP:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError('unexpected provider request')
        return self.responses.pop(0)


def reply(data=None, status=200, **headers):
    return Response(status, headers, data or {})


def upload_replies(video_id='video1'):
    return [reply({'items': [{'id': 'account1'}]}),
            reply(location='https://www.googleapis.com/upload/youtube/v3/videos?session=transient'),
            reply({'id': video_id}, 201)]


class PostApprovedTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        override = override_settings(BASE_DIR=self.root, MAISON_SOCIAL_JOURNAL_DIR=str(self.root / 'journal'))
        override.enable()
        self.addCleanup(override.disable)
        env = patch.dict(os.environ, {post_approved.TOKEN_ENV: TOKEN})
        env.start()
        self.addCleanup(env.stop)
        probe = lambda _: dict(width=1080, height=1920, duration_seconds=30, codec='h264')
        real = post_approved.prepare
        patcher = patch.object(post_approved, 'prepare', lambda m, r: real(m, r, probe=probe))
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.root / 'assets').mkdir()
        raw = b'bound-video-payload'
        (self.root / 'assets' / 'film').write_bytes(raw)
        self.asset = dict(id='film', path='film', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                          role='video', content_type='video/mp4')
        (self.root / 'bundle').mkdir()

    def manifest(self, name='one', account='account1'):
        data = dict(schema='earnalism.production_bundle.v1', project_id=name, private=True,
            content=dict(text_sha256='a' * 64, language='en', voice_profile='en_tisha'),
            assets=[deepcopy(self.asset)], evidence=dict(qa=[], rights=[]),
            social=[dict(platform='youtube', account_id=account, video_asset_id='film', title='Exact title',
                         description='Exact description', made_for_kids=False)])
        (self.root / 'bundle' / (name + '.json')).write_text(json.dumps(data))
        return 'bundle/' + name + '.json'

    def post(self, name='one', status='approved', **overrides):
        summary = dict(edition_slug='ed', bundle_manifest=self.manifest(name), asset_root='assets',
                       destination_key='youtube:account1', account_id='account1', post_id=name)
        summary.update(overrides)
        return ReviewItem.objects.create(kind='post', ref=f'social/ed/{name}', sha256=hashlib.sha256(name.encode()).hexdigest(),
                                         summary={k: v for k, v in summary.items() if v is not None}, status=status)

    def run_cmd(self, *args):
        out, err = StringIO(), StringIO()
        try:
            call_command('post_approved', *args, stdout=out, stderr=err)
        except CommandError as exc:
            raise CommandError(str(exc) + ' | ' + err.getvalue()) from None
        finally:
            self.out, self.err = out.getvalue(), err.getvalue()

    def test_dry_run_changes_nothing(self):
        item = self.post()
        http = FakeHTTP()
        with patch.object(post_approved, 'make_http', lambda: http):
            self.run_cmd('--provider', 'youtube')
        self.assertIn('social/ed/one', self.out)
        self.assertEqual(http.calls, [])
        item.refresh_from_db()
        self.assertNotIn('receipt', item.summary)
        self.assertEqual(AuditEvent.objects.filter(action='social.upload_private').count(), 0)

    def test_execute_uploads_only_approved_posts_once(self):
        item, pending = self.post('one'), self.post('two', status='pending')
        http = FakeHTTP(*upload_replies())
        with patch.object(post_approved, 'make_http', lambda: http):
            self.run_cmd('--provider', 'youtube', '--execute')
            self.run_cmd('--provider', 'youtube', '--execute')  # second run: receipt present, nothing happens
        item.refresh_from_db(); pending.refresh_from_db()
        self.assertEqual(item.summary['receipt'], {'video_id': 'video1', 'upload_completed': True})
        self.assertIn('posted_at', item.summary)
        self.assertNotIn('receipt', pending.summary)
        self.assertEqual(len(http.calls), 3)
        meta = http.calls[1][2]['json_body']
        self.assertEqual(meta['status']['privacyStatus'], 'private')
        self.assertFalse(any('publish' in c[1] or c[0] == 'PUT' and 'videos?part=status' in c[1] for c in http.calls))
        self.assertEqual(AuditEvent.objects.filter(action='social.upload_private').count(), 1)
        saved = ''.join(p.read_text() for p in (self.root / 'journal').glob('*.json'))
        self.assertNotIn(TOKEN, saved + self.out + self.err + json.dumps(item.summary))

    def test_unknown_provider_is_refused(self):
        self.post()
        with self.assertRaisesRegex(CommandError, 'not authorized'):
            self.run_cmd('--provider', 'instagram', '--execute')

    def test_missing_token_is_refused_without_partial_upload(self):
        item = self.post()
        http = FakeHTTP()
        with patch.dict(os.environ, {}, clear=False), patch.object(post_approved, 'make_http', lambda: http):
            os.environ.pop(post_approved.TOKEN_ENV)
            with self.assertRaisesRegex(CommandError, post_approved.TOKEN_ENV):
                self.run_cmd('--provider', 'youtube', '--execute')
        self.assertEqual(http.calls, [])
        item.refresh_from_db()
        self.assertNotIn('receipt', item.summary)

    def test_invalid_items_are_refused_individually_and_left_untouched(self):
        self.post('nofield', post_id=None)
        self.post('escape', bundle_manifest='../outside.json')
        self.post('absolute', asset_root='/etc')
        self.post('mismatch', destination_key='youtube:other')
        good = self.post('good')
        http = FakeHTTP(*upload_replies())
        with patch.object(post_approved, 'make_http', lambda: http):
            with self.assertRaisesRegex(CommandError, '4 item'):
                self.run_cmd('--provider', 'youtube', '--execute')
        self.assertIn('social/ed/nofield: REFUSED - missing summary fields: post_id', self.err)
        for name in ('escape', 'absolute', 'mismatch'):
            self.assertIn(f'social/ed/{name}: REFUSED', self.err)
        good.refresh_from_db()
        self.assertEqual(good.summary['receipt']['video_id'], 'video1')
        for item in ReviewItem.objects.exclude(pk=good.pk):
            self.assertNotIn('receipt', item.summary)

    def test_grant_covers_only_start_and_upload(self):
        seen = []
        real = post_approved.Delivery.run

        def spy(self_, key, action, *, execute=False, authority=None):
            seen.append((action, authority.actions))
            return real(self_, key, action, execute=execute, authority=authority)

        self.post()
        http = FakeHTTP(*upload_replies())
        with patch.object(post_approved, 'make_http', lambda: http), patch.object(post_approved.Delivery, 'run', spy):
            self.run_cmd('--provider', 'youtube', '--execute')
        self.assertEqual(seen, [('start', frozenset(['start'])), ('upload', frozenset(['upload']))])

    def test_item_rejected_after_listing_is_not_uploaded(self):
        item = self.post()
        http = FakeHTTP()
        real = post_approved.Command._upload

        def reject_then_upload(self_, it, fields, token):
            ReviewItem.objects.filter(pk=it.pk).update(status='rejected')
            return real(self_, it, fields, token)

        with patch.object(post_approved, 'make_http', lambda: http), patch.object(post_approved.Command, '_upload', reject_then_upload):
            self.run_cmd('--provider', 'youtube', '--execute')
        self.assertEqual(http.calls, [])
        self.assertIn('SKIPPED', self.out)
        item.refresh_from_db()
        self.assertNotIn('receipt', item.summary)

    def test_receipt_write_failure_recovers_without_provider_request(self):
        item = self.post()
        http = FakeHTTP(*upload_replies())
        with patch.object(post_approved, 'make_http', lambda: http), patch.object(post_approved, 'audit', side_effect=RuntimeError('db')):
            with self.assertRaises(CommandError):
                self.run_cmd('--provider', 'youtube', '--execute')
        item.refresh_from_db()
        self.assertNotIn('receipt', item.summary)
        again = FakeHTTP()
        with patch.object(post_approved, 'make_http', lambda: again):
            self.run_cmd('--provider', 'youtube', '--execute')
        self.assertEqual(again.calls, [])
        item.refresh_from_db()
        self.assertEqual(item.summary['receipt'], {'video_id': 'video1', 'upload_completed': True})
        self.assertEqual(AuditEvent.objects.filter(action='social.upload_private').count(), 1)

    def test_uncertain_upload_prints_reconcile_next_step(self):
        self.post()
        http = FakeHTTP(reply({'items': [{'id': 'account1'}]}),
                        reply(location='https://www.googleapis.com/upload/youtube/v3/videos?session=transient'),
                        TimeoutError('x'))
        with patch.object(post_approved, 'make_http', lambda: http):
            with self.assertRaises(CommandError):
                self.run_cmd('--provider', 'youtube', '--execute')
            self.assertIn('provider_outcome_unknown', self.err)
            http.responses.append(reply({'items': [{'id': 'account1'}]}))  # identity check on the re-run
            with self.assertRaises(CommandError):
                self.run_cmd('--provider', 'youtube', '--execute')
        self.assertIn('reconcile_upload', self.err)
        self.assertIn('not retried automatically', self.err)

    def test_authorize_grants_only_one_private_upload_action(self):
        plan = {'candidate_sha256': 'a' * 64}
        dest = {'key': 'youtube:account1', 'account_id': 'account1'}

        def grant(actions, action, sha='a' * 64, key='youtube:account1', account='account1'):
            return post_approved.authorize_private_upload(Authority(sha, key, account, frozenset(actions), 'r'), plan, dest, action)

        self.assertTrue(grant(['start'], 'start'))
        self.assertTrue(grant(['upload'], 'upload'))
        for action in ('publish', 'status', 'captions', 'thumbnail', 'resume_upload'):
            self.assertFalse(grant([action], action))
        self.assertFalse(grant(['start', 'upload'], 'start'))
        self.assertFalse(grant(['start'], 'start', sha='b' * 64))
        self.assertFalse(grant(['start'], 'start', key='youtube:other'))
        self.assertFalse(grant(['start'], 'start', account='other'))
