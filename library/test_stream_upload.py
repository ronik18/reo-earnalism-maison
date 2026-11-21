"""PostgreSQL transactions and fake provider I/O; never a live upload or publication."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import io
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.core.management import call_command
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.api import DomainError
from core.models import OperationReceipt, OutboxJob
from .models import Asset, Edition, Revision, Unit, Work
from . import stream_upload as upload

UID = 'a' * 32
ACCOUNT = 'b' * 32
CAPABILITY = 'https://upload.videodelivery.net/tus/opaque?capability=SYNTHETIC_PRIVATE_CAPABILITY'
SETTINGS = dict(SECRET_KEY='synthetic-private-stream-test-key-' * 3, STREAM_ACCOUNT_ID=ACCOUNT,
    STREAM_API_TOKEN='synthetic-backend-only-token', STREAM_CUSTOMER_HOST='customer-synthetic.cloudflarestream.com')


@override_settings(**SETTINGS)
class PrivateStreamUploadTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser('stream-intent@example.test', 'Synthetic-only-password-47')
        work = Work.objects.create(slug='private-stream-intent', title='Synthetic private source')
        edition = Edition.objects.create(work=work, slug=work.slug, locale='en')
        self.revision = Revision.objects.create(edition=edition, title=work.title)
        self.unit = Unit.objects.create(revision=self.revision, ordinal=1, title='Exact unit', duration_ms=30456)
        self.operation = uuid.uuid4()
        self.data = dict(edition_revision_id=str(self.revision.id), unit_id=str(self.unit.id),
            kind='video', file_name='private.mp4', content_type='video/mp4', bytes=12345,
            sha256='d' * 64, duration_ms=30456)
        self.provider = patch('library.stream_upload._create_provider_upload', side_effect=self.provider_ack).start()
        self.metadata = patch('library.stream._metadata_request', side_effect=self.metadata_ack).start()
        self.addCleanup(patch.stopall)

    def provider_ack(self, asset, expiry):
        self.assertFalse(connection.in_atomic_block)
        job = OutboxJob.objects.get(kind=upload.KIND)
        self.assertEqual(job.payload['phase'], 'submitting'); self.assertEqual(job.status, 'blocked')
        self.assertEqual(job.attempts, 1); self.assertTrue(OperationReceipt.objects.filter(operation_id=self.operation).exists())
        self.assertEqual(asset.provider, 'r2'); self.assertIn('/pending-stream', asset.storage_key)
        self.assertLessEqual((expiry - timezone.now()).total_seconds(), 120)
        return {'provider_uid': UID, 'upload_url': CAPABILITY}

    def metadata_ack(self, uid, budget):
        self.assertFalse(connection.in_atomic_block); self.assertEqual(uid, UID); self.assertEqual(budget, 8)
        self.assertEqual(Asset.objects.get(storage_key=UID).provider, 'stream')
        return {'uid': UID, 'requireSignedURLs': True, 'readyToStream': False, 'status': {'state': 'uploading'}}

    def create(self, **changes):
        return upload.create_private_upload(self.actor, {**self.data, **changes}, self.operation)

    def test_private_intent_is_durable_before_post_encrypted_and_exactly_replayable(self):
        status, grant = self.create()
        self.assertEqual(status, 201); self.assertEqual(grant['method'], 'PATCH')
        self.assertEqual(grant['protocol'], 'stream_tus'); self.assertEqual(grant['provider_uid'], UID)
        self.assertEqual(grant['upload_url'], CAPABILITY); self.assertEqual(grant['version'], 2)
        self.assertEqual(grant['required_headers'], {'Tus-Resumable': '1.0.0'})
        job = OutboxJob.objects.get(kind=upload.KIND)
        self.assertEqual(job.payload['phase'], 'grant_ready'); self.assertTrue(job.result['private_metadata_verified'])
        saved = json.dumps(job.payload) + json.dumps(job.result) + json.dumps(OperationReceipt.objects.get(operation_id=self.operation).response)
        self.assertNotIn(CAPABILITY, saved); self.assertNotIn('SYNTHETIC_PRIVATE_CAPABILITY', saved)
        self.assertNotIn(SETTINGS['STREAM_API_TOKEN'], saved)
        self.assertIn('ciphertext', job.result)
        self.assertEqual(self.create(), (status, grant))
        self.provider.assert_called_once(); self.metadata.assert_called_once()
        OperationReceipt.objects.filter(operation_id=self.operation).delete()
        self.assertEqual(self.create(), (status, grant))
        self.assertEqual(Asset.objects.count(), 1); self.provider.assert_called_once()
        self.revision.refresh_from_db(); self.assertEqual(self.revision.state, 'draft')
        self.assertIsNone(self.revision.edition.live_revision_id); self.assertEqual(self.revision.rights.count(), 0)

    def test_unknown_post_and_consumed_attempt_never_allocate_again(self):
        self.provider.side_effect = TimeoutError('token/raw provider capability must be redacted')
        with self.assertRaises(DomainError) as error: self.create()
        self.assertEqual(error.exception.code, 'stream_upload_outcome_unknown')
        job = OutboxJob.objects.get(kind=upload.KIND)
        self.assertEqual(job.payload['phase'], 'unknown'); self.assertEqual(job.attempts, 1)
        self.assertEqual(Asset.objects.get().provider, 'r2'); self.metadata.assert_not_called()
        with self.assertRaises(DomainError) as held: self.create()
        self.assertEqual(held.exception.code, 'stream_upload_reconciliation_required')
        self.provider.assert_called_once()
        self.assertNotIn('raw provider', json.dumps(job.result)); self.assertNotIn('token/raw', error.exception.message)

    def test_exact_private_metadata_is_required_before_capability_return(self):
        self.metadata.side_effect = lambda *args: {'uid': UID, 'requireSignedURLs': False}
        with self.assertRaises(DomainError) as error: self.create()
        self.assertEqual(error.exception.code, 'stream_upload_private_metadata_unverified')
        job = OutboxJob.objects.get(); self.assertEqual(job.payload['phase'], 'privacy_failed')
        self.assertEqual(Asset.objects.get().storage_key, UID)
        with self.assertRaises(DomainError): self.create()
        self.provider.assert_called_once(); self.metadata.assert_called_once()

    def test_original_grant_expiry_and_ciphertext_tampering_hold_without_post(self):
        _, grant = self.create()
        expires = parse_datetime(grant['expires_at'])
        with patch('library.stream_upload.timezone.now', return_value=expires + timedelta(seconds=1)):
            with self.assertRaises(DomainError) as expired: self.create()
        self.assertEqual(expired.exception.code, 'stream_upload_grant_expired')
        self.assertEqual(OutboxJob.objects.get().payload['phase'], 'expired')
        self.provider.assert_called_once()

    def test_encrypted_capability_is_bound_to_actor_asset_and_request(self):
        self.create(); job = OutboxJob.objects.get()
        job.result['ciphertext'] = base64.b64encode(b'tampered').decode(); job.save(update_fields=['result'])
        with self.assertRaises(DomainError) as error: self.create()
        self.assertEqual(error.exception.code, 'stream_upload_grant_unavailable')
        self.provider.assert_called_once()

    def test_changed_request_invalid_source_and_nonpublisher_never_allocate(self):
        for change in ({'duration_ms': 30457}, {'bytes': False}, {'file_name': '../escape.mp4'}, {'content_type': 'audio/mpeg'}):
            with self.assertRaises(DomainError): self.create(**change)
        self.provider.assert_not_called(); self.assertEqual(Asset.objects.count(), 0)
        self.create()
        with self.assertRaises(DomainError) as conflict: self.create(sha256='e' * 64)
        self.assertEqual(conflict.exception.code, 'idempotency_key_reused')
        self.actor.is_verified = False; self.actor.save(update_fields=['is_verified'])
        with self.assertRaises(DomainError) as denied: self.create()
        self.assertEqual(denied.exception.status, 403); self.provider.assert_called_once()

    def test_concurrent_replay_holds_submitting_without_second_post(self):
        entered, release = Event(), Event()
        def blocked_provider(asset, expiry):
            self.provider_ack(asset, expiry); entered.set()
            if not release.wait(5): raise TimeoutError('fixture release timeout')
            return {'provider_uid': UID, 'upload_url': CAPABILITY}
        self.provider.side_effect = blocked_provider
        def execute():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                return upload.create_private_upload(actor, self.data, self.operation)
            finally: connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(DomainError) as held: self.create()
                self.assertEqual(held.exception.code, 'stream_upload_reconciliation_required')
            finally: release.set()
            self.assertEqual(future.result(timeout=10)[0], 201)
        self.provider.assert_called_once(); self.assertEqual(OutboxJob.objects.get().attempts, 1)

    def test_changed_unit_after_provider_ack_retains_private_identity_but_returns_no_grant(self):
        def changed_unit(asset, expiry):
            result = self.provider_ack(asset, expiry)
            Unit.objects.filter(pk=self.unit.id).update(duration_ms=30457)
            return result
        self.provider.side_effect = changed_unit
        with self.assertRaises(DomainError) as error: self.create()
        self.assertEqual(error.exception.code, 'stream_upload_draft_changed')
        job = OutboxJob.objects.get()
        self.assertEqual(job.payload['phase'], 'orphaned_private_provider_ack')
        self.assertEqual(job.result['provider_uid'], UID)
        self.assertNotIn(CAPABILITY, json.dumps(job.result)); self.metadata.assert_not_called()
        self.provider.assert_called_once()

    def test_completion_association_requires_exact_actor_uid_source_and_current_unit(self):
        _, grant = self.create(); asset = Asset.objects.get(pk=grant['asset_id'])
        self.assertTrue(upload.verify_private_upload_association(self.actor, asset)['source_upload_association_verified'])
        self.provider.reset_mock(); self.metadata.reset_mock()
        other = get_user_model().objects.create_superuser('other-stream-intent@example.test', 'Synthetic-other-password47')
        with self.assertRaises(DomainError): upload.verify_private_upload_association(other, asset)
        with self.assertRaises(DomainError): upload.verify_private_upload_association(self.actor, asset, source_bytes=asset.bytes + 1)
        asset.storage_key = 'f' * 32
        with self.assertRaises(DomainError): upload.verify_private_upload_association(self.actor, asset)
        asset.refresh_from_db()
        Unit.objects.filter(pk=self.unit.id).update(duration_ms=30457)
        with self.assertRaises(DomainError): upload.verify_private_upload_association(self.actor, asset)
        self.provider.assert_not_called(); self.metadata.assert_not_called()

    def api_client(self, actor=None, password='Synthetic-only-password-47'):
        actor = actor or self.actor
        client = Client(enforce_csrf_checks=True)
        csrf = client.get('/api/v1/session').json()['csrf_token']
        login = client.post('/api/v1/auth/login', json.dumps({'email': actor.email, 'password': password,
            'password_purpose_consent': True, 'password_purpose_version': 'password-account-v1'}),
            content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(login.status_code, 200, login.content)
        return client, client.get('/api/v1/session').json()['csrf_token']

    def test_authenticated_csrf_video_upload_completion_and_private_processing_journey(self):
        self.data['bytes'] = 300000  # Video takes its Stream branch before the local R2 limit.
        client, csrf = self.api_client()
        denied = client.post('/api/v1/staff/assets/uploads', json.dumps(self.data), content_type='application/json',
            HTTP_IDEMPOTENCY_KEY=str(self.operation))
        self.assertEqual(denied.status_code, 403); self.provider.assert_not_called()
        intent = client.post('/api/v1/staff/assets/uploads', json.dumps(self.data), content_type='application/json',
            HTTP_IDEMPOTENCY_KEY=str(self.operation), HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(intent.status_code, 201, intent.content)
        grant = intent.json(); ident = grant['asset_id']
        complete = client.post(f'/api/v1/staff/assets/{ident}/complete', json.dumps({'bytes': self.data['bytes'], 'sha256': self.data['sha256']}),
            content_type='application/json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()), HTTP_IF_MATCH=intent['ETag'], HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(complete.status_code, 200, complete.content); self.assertEqual(complete.json()['state'], 'processing')
        self.metadata.side_effect = None
        self.metadata.return_value = {'uid': UID, 'requireSignedURLs': True, 'readyToStream': True,
            'status': {'state': 'ready'}, 'duration': 30.456,
            'playback': {'hls': f'https://customer-synthetic.cloudflarestream.com/{UID}/manifest/video.m3u8'}}
        output = io.StringIO()
        call_command('verify_media_asset', ident, stdout=output)
        asset = Asset.objects.get(pk=ident); self.assertEqual(asset.state, 'ready')
        self.revision.refresh_from_db(); self.assertEqual(self.revision.state, 'draft')
        self.assertIsNone(self.revision.edition.live_revision_id); self.assertEqual(self.revision.rights.count(), 0)
        self.assertNotIn('live', output.getvalue().lower())

    def test_api_completion_rejects_fabricated_uid_cross_actor_and_changed_body(self):
        client, csrf = self.api_client()
        intent = client.post('/api/v1/staff/assets/uploads', json.dumps(self.data), content_type='application/json',
            HTTP_IDEMPOTENCY_KEY=str(self.operation), HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(intent.status_code, 201, intent.content); ident = intent.json()['asset_id']
        def complete(target_client=client, token=csrf, body=None, etag=None):
            return target_client.post(f'/api/v1/staff/assets/{ident}/complete', json.dumps(body or {'bytes': self.data['bytes'], 'sha256': self.data['sha256']}),
                content_type='application/json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()), HTTP_IF_MATCH=etag or intent['ETag'], HTTP_X_CSRFTOKEN=token)
        self.assertEqual(complete(body={'bytes': self.data['bytes'] + 1, 'sha256': self.data['sha256']}).status_code, 422)
        other = get_user_model().objects.create_superuser('other-api-stream@example.test', 'Synthetic-other-api-password47')
        other_client, other_csrf = self.api_client(other, 'Synthetic-other-api-password47')
        self.assertEqual(complete(other_client, other_csrf).status_code, 409)
        asset = Asset.objects.get(pk=ident); asset.storage_key = 'f' * 32; asset.save()
        current_etag = client.get(f'/api/v1/staff/assets/{ident}')['ETag']
        self.assertEqual(complete(etag=current_etag).status_code, 409)
        asset.refresh_from_db(); self.assertEqual(asset.state, 'uploading')
        asset.storage_key = UID; asset.save()
        Unit.objects.filter(pk=self.unit.id).update(duration_ms=30457)
        current_etag = client.get(f'/api/v1/staff/assets/{ident}')['ETag']
        self.assertEqual(complete(etag=current_etag).status_code, 409)


@override_settings(**SETTINGS)
class StreamCreationProtocolTests(SimpleTestCase):
    def test_official_create_has_private_first_metadata_and_no_public_fallback(self):
        expiry = timezone.now() + timedelta(seconds=120)
        asset = SimpleNamespace(id=uuid.uuid4(), bytes=12345, duration_ms=30456)
        with patch('library.stream_upload.http.client.HTTPSConnection') as client:
            client.return_value.sock = None
            response = client.return_value.getresponse.return_value
            response.status = 201; response.read.return_value = b''
            response.getheader.side_effect = lambda k: {'Location': CAPABILITY, 'stream-media-id': UID}.get(k)
            result = upload._create_provider_upload(asset, expiry)
            self.assertEqual(result, {'upload_url': CAPABILITY, 'provider_uid': UID})
            call = client.return_value.request.call_args
            self.assertEqual(call.args[:2], ('POST', f'/client/v4/accounts/{ACCOUNT}/stream?direct_user=true'))
            headers = call.kwargs['headers']
            self.assertEqual(headers['Upload-Length'], '12345'); self.assertEqual(headers['Tus-Resumable'], '1.0.0')
            metadata = headers['Upload-Metadata'].split(',')
            self.assertIn('requiresignedurls', metadata)
            decoded = {k: base64.b64decode(v).decode() for k, v in (x.split(' ', 1) for x in metadata if ' ' in x)}
            self.assertEqual(decoded['maxDurationSeconds'], '31'); self.assertEqual(decoded['name'], str(asset.id))
            self.assertEqual(parse_datetime(decoded['expiry']), expiry)
            response.status = 302
            with self.assertRaises(DomainError) as error: upload._create_provider_upload(asset, expiry)
            self.assertEqual(error.exception.code, 'stream_upload_outcome_unknown')
