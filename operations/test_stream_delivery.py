"""Source-bound TUS fake HTTP and real local-byte tests, with no provider calls."""
import base64
import hashlib
import http.client
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from operations.production_journal import OperationJournal, JournalConflictError
from operations.social_delivery.http import FileSlice, Response, _LimitedFile
from operations.stream_delivery import CHUNK, StreamDeliveryError, TUSHTTPSClient, upload_private_video

URL = 'https://upload.videodelivery.net/tus/opaque?capability=DO_NOT_RETAIN'
UID = 'a' * 32
HEADERS = {'Tus-Resumable': '1.0.0'}


def options(checksum=False):
    return Response(204, {'tus-extension': 'checksum', 'tus-checksum-algorithm': 'sha1,sha256'} if checksum else {}, {})


def head(offset, length=19, uid=UID):
    return Response(200, {'tus-resumable': '1.0.0', 'upload-length': str(length),
                         'upload-offset': str(offset), 'stream-media-id': uid}, {})


def ack(offset):
    return Response(204, {'tus-resumable': '1.0.0', 'upload-offset': str(offset)}, {})


class FakeHTTP:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, *, headers, body=None):
        self.calls.append((method, url, headers, body))
        if not self.responses: raise AssertionError('unexpected provider request')
        value = self.responses.pop(0)
        if isinstance(value, Exception): raise value
        return value


class StreamDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'retained.mp4'; self.raw = b'0123456789abcdefghi'; self.path.write_bytes(self.raw)
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.journal = OperationJournal(self.root / 'journal')

    def upload(self, http, **kw):
        return upload_private_video(URL, HEADERS, self.path, len(self.raw), self.sha,
            http=http, journal=self.journal, key='candidate:asset', provider_uid=UID, **kw)

    def test_prepare_is_inert_and_exact_source_is_required(self):
        http = FakeHTTP()
        self.assertEqual(self.upload(http)['provider_requests'], 0)
        self.assertEqual(http.calls, [])
        self.assertEqual(list(self.journal.directory.glob('*.json')), [])
        self.path.write_bytes(b'changed')
        with self.assertRaisesRegex(StreamDeliveryError, 'EXACT_LOCAL_SOURCE_BYTES_REQUIRED'):
            self.upload(http, execute=True)
        self.assertEqual(http.calls, [])

    def test_fixed_chunk_size_meets_cloudflare_constraints(self):
        self.assertEqual(CHUNK, 52_428_800)
        self.assertGreaterEqual(CHUNK, 5_242_880)
        self.assertEqual(CHUNK % (256 * 1024), 0)

    def test_complete_transfer_streams_chunks_and_replays_without_writes(self):
        http = FakeHTTP(options(), head(0), ack(8), ack(16), ack(19))
        with patch('operations.stream_delivery.CHUNK', 8): result = self.upload(http, execute=True)
        self.assertEqual(result['upload_offset'], 19)
        self.assertFalse(result['privacy_verified_by_client']); self.assertFalse(result['publication_performed'])
        patches = [c for c in http.calls if c[0] == 'PATCH']
        self.assertEqual([c[3].offset for c in patches], [0, 8, 16])
        self.assertEqual([c[3].length for c in patches], [8, 8, 3])
        self.assertTrue(all(isinstance(c[3], FileSlice) for c in patches))
        self.assertTrue(all(c[2]['Content-Type'] == 'application/offset+octet-stream' for c in patches))
        second = FakeHTTP(options(), head(19))
        with patch('operations.stream_delivery.CHUNK', 8): repeated = self.upload(second, execute=True)
        self.assertEqual(repeated['upload_offset'], 19)
        self.assertEqual([c[0] for c in second.calls], ['OPTIONS', 'HEAD'])
        records = ''.join(p.read_text() for p in self.journal.directory.glob('*.json'))
        self.assertNotIn('DO_NOT_RETAIN', records); self.assertNotIn('https://', records)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_unknown_patch_is_held_until_explicit_head_reconciliation(self):
        first = FakeHTTP(options(), head(0), TimeoutError('provider URL token must not leak'))
        with patch('operations.stream_delivery.CHUNK', 8):
            with self.assertRaisesRegex(StreamDeliveryError, 'STREAM_REQUEST_OUTCOME_UNKNOWN'): self.upload(first, execute=True)
            held = FakeHTTP(options(), head(8))
            with self.assertRaisesRegex(StreamDeliveryError, 'UNCERTAIN_PATCH_REQUIRES_EXPLICIT_RECONCILIATION'):
                self.upload(held, execute=True)
            self.assertEqual([c[0] for c in held.calls], ['OPTIONS', 'HEAD'])
            resumed = FakeHTTP(options(), head(8), ack(16), ack(19))
            result = self.upload(resumed, execute=True, reconcile=True)
        self.assertEqual(result['upload_offset'], 19)
        self.assertEqual([c[3].offset for c in resumed.calls if c[0] == 'PATCH'], [8, 16])
        self.assertNotIn('token must', ''.join(p.read_text() for p in self.journal.directory.glob('*.json')))

    def test_partial_unknown_patch_keeps_accepted_prefix_and_never_replays_it(self):
        with patch('operations.stream_delivery.CHUNK', 8):
            with self.assertRaises(StreamDeliveryError):
                self.upload(FakeHTTP(options(), head(0), TimeoutError()), execute=True)
            resumed = FakeHTTP(options(), head(5), ack(13), ack(19))
            self.upload(resumed, execute=True, reconcile=True)
        self.assertEqual([c[3].offset for c in resumed.calls if c[0] == 'PATCH'], [5, 13])
        self.assertEqual([c[3].length for c in resumed.calls if c[0] == 'PATCH'], [8, 6])

    def test_no_committed_bytes_need_distinct_explicit_recovery_intent(self):
        with patch('operations.stream_delivery.CHUNK', 8):
            with self.assertRaises(StreamDeliveryError): self.upload(FakeHTTP(options(), head(0), TimeoutError()), execute=True)
            resumed = FakeHTTP(options(), head(0), ack(8), ack(16), ack(19))
            self.upload(resumed, execute=True, reconcile=True)
        prior = self.journal.read('candidate:asset:patch:0:0')
        retry = self.journal.read('candidate:asset:patch:0:1')
        self.assertEqual(prior['result']['next_offset'], 0)
        self.assertEqual(prior['result']['state'], 'TUS_PATCH_NO_BYTES_COMMITTED_HEAD_OBSERVED')
        self.assertEqual(retry['result']['next_offset'], 8)

    def test_unattributed_remote_prefix_and_changed_capability_are_held(self):
        with patch('operations.stream_delivery.CHUNK', 8):
            with self.assertRaisesRegex(StreamDeliveryError, 'UNATTRIBUTED_REMOTE_PREFIX'):
                self.upload(FakeHTTP(options(), head(8)), execute=True, reconcile=True)
        with self.assertRaises(JournalConflictError):
            upload_private_video(URL + 'CHANGED', HEADERS, self.path, 19, self.sha, http=FakeHTTP(),
                journal=self.journal, key='candidate:asset', execute=True, provider_uid=UID)

    def test_uid_length_and_patch_offset_mismatch_never_become_complete(self):
        for response, code in [(head(0, 18), 'REMOTE_LENGTH'), (head(0, uid='b' * 32), 'PROVIDER_UID_MISMATCH')]:
            with self.assertRaisesRegex(StreamDeliveryError, code): self.upload(FakeHTTP(options(), response), execute=True)
        bad = FakeHTTP(options(), head(0), ack(7))
        with patch('operations.stream_delivery.CHUNK', 8):
            with self.assertRaisesRegex(StreamDeliveryError, 'PATCH_ACKNOWLEDGEMENT_UNRESOLVED'): self.upload(bad, execute=True)
        self.assertEqual(self.journal.read('candidate:asset:patch:0:0')['state'], 'unknown')

    def test_checksums_are_only_sent_when_explicitly_advertised(self):
        http = FakeHTTP(options(True), head(0), ack(19))
        self.upload(http, execute=True)
        self.assertEqual(http.calls[-1][2]['Upload-Checksum'], 'sha256 ' + base64.b64encode(bytes.fromhex(self.sha)).decode())
        # No extension advertisement on another retained source -> no checksum claim.
        journal = OperationJournal(self.root / 'other-journal')
        plain = FakeHTTP(options(), head(0), ack(19))
        upload_private_video(URL, HEADERS, self.path, 19, self.sha, http=plain, journal=journal,
            key='other', execute=True, provider_uid=UID)
        self.assertNotIn('Upload-Checksum', plain.calls[-1][2])

    def test_lost_or_foreign_capability_and_api_headers_are_rejected_before_dispatch(self):
        for value in (None, '', 'http://upload.videodelivery.net/tus/x', 'https://attacker.example/tus/x',
                      'https://upload.videodelivery.net@attacker.example/tus/x'):
            with self.assertRaises(StreamDeliveryError):
                upload_private_video(value, HEADERS, self.path, 19, self.sha, http=FakeHTTP(), execute=True)
        with self.assertRaisesRegex(StreamDeliveryError, 'NO_API_CREDENTIALS'):
            upload_private_video(URL, {**HEADERS, 'Authorization': 'Bearer forbidden'}, self.path, 19, self.sha)


class StreamTransportTests(unittest.TestCase):
    def test_redirect_is_not_followed_and_large_file_body_streams(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'asset'; path.write_bytes(b'0123456789')
            with patch('operations.stream_delivery.http.client.HTTPSConnection') as connection:
                response = connection.return_value.getresponse.return_value
                response.status = 307; response.read.return_value = b''
                response.getheaders.return_value = [('Location', 'https://attacker.example/')]
                result = TUSHTTPSClient().request('PATCH', URL, headers=HEADERS, body=FileSlice(path, 2, 5))
                self.assertEqual(result.status, 307); self.assertEqual(connection.call_count, 1)
                kwargs = connection.return_value.request.call_args.kwargs
                self.assertIsInstance(kwargs['body'], _LimitedFile)
                self.assertEqual(kwargs['headers']['Content-Length'], '5')

    def test_client_cannot_create_publish_or_send_api_tokens(self):
        with patch('operations.stream_delivery.http.client.HTTPSConnection') as connection:
            for method in ('POST', 'PUT', 'DELETE'):
                with self.assertRaises(StreamDeliveryError): TUSHTTPSClient().request(method, URL, headers=HEADERS)
            with self.assertRaises(StreamDeliveryError): TUSHTTPSClient().request('HEAD', URL, headers={'Authorization': 'secret'})
            connection.assert_not_called()


if __name__ == '__main__':
    unittest.main()
