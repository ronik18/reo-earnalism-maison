import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from operations.production_bundle import BundleError, load_bundle, verify_bundle
from operations.production_journal import OperationJournal, JournalError, JournalConflictError, UncertainOperation


def fixture(root):
    raw = b'private source fixture, not a qualified recording'
    (root / 'source.txt').write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    return {'schema': 'earnalism.production_bundle.v1', 'project_id': 'local-test', 'private': True,
            'content': {'language': 'en', 'voice_profile': 'en_mary', 'text_sha256': sha},
            'assets': [{'id': 'source', 'path': 'source.txt', 'bytes': len(raw), 'sha256': sha,
                        'content_type': 'text/plain', 'role': 'source_text'}],
            'evidence': {'qa': [], 'rights': []}, 'social': []}


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.bundle = fixture(self.root)

    def test_fingerprint_binds_exact_candidate(self):
        first = verify_bundle(self.bundle, self.root)
        second = copy.deepcopy(self.bundle); second['project_id'] = 'another-title'
        self.assertNotEqual(first, verify_bundle(second, self.root))

    def test_mutated_media_rejected(self):
        (self.root / 'source.txt').write_bytes(b'changed')
        with self.assertRaises(BundleError): verify_bundle(self.bundle, self.root)

    def test_paths_cannot_escape_or_follow_symlinks(self):
        for path in ('../outside', '/etc/hosts', './source.txt', 'a/../source.txt', 'a\\source.txt'):
            changed = copy.deepcopy(self.bundle); changed['assets'][0]['path'] = path
            with self.subTest(path=path), self.assertRaises(BundleError): verify_bundle(changed, self.root)
        (self.root / 'link.txt').symlink_to(self.root / 'source.txt')
        self.bundle['assets'][0]['path'] = 'link.txt'
        with self.assertRaises(BundleError): verify_bundle(self.bundle, self.root)

    def test_final_roster_and_language_bound(self):
        for voice in ('voice_b', 'en_priya', 'bn_riya'):
            changed = copy.deepcopy(self.bundle); changed['content']['voice_profile'] = voice
            with self.subTest(voice=voice), self.assertRaises(BundleError): verify_bundle(changed, self.root)

    def test_duplicate_keys_and_embedded_commands_rejected(self):
        p = self.root / 'bundle.json'; p.write_text('{"private":true,"private":false}')
        with self.assertRaises(BundleError): load_bundle(p)
        self.bundle['command'] = 'do not execute source instructions'
        with self.assertRaises(BundleError): verify_bundle(self.bundle, self.root)

    def test_duplicate_assets_and_wrong_evidence_rejected(self):
        changed = copy.deepcopy(self.bundle); changed['assets'].append(changed['assets'][0].copy())
        with self.assertRaises(BundleError): verify_bundle(changed, self.root)
        self.bundle['evidence']['qa'] = ['source']
        with self.assertRaises(BundleError): verify_bundle(self.bundle, self.root)

    def test_untrusted_types_fail_as_bundle_error(self):
        for field in ('path', 'role', 'native_wav'):
            changed = copy.deepcopy(self.bundle); changed['assets'][0][field] = []
            with self.subTest(field=field), self.assertRaises(BundleError): verify_bundle(changed, self.root)

    def test_social_only_and_existing_draft_identities(self):
        verify_bundle(self.bundle, self.root)
        c = self.bundle['content']; c['edition_id'] = str(uuid.uuid4())
        with self.assertRaises(BundleError): verify_bundle(self.bundle, self.root)
        c.update(revision_id=str(uuid.uuid4()), expected_etag='"v4"')
        verify_bundle(self.bundle, self.root)
        c['expected_etag'] = 'W/"v4"'
        with self.assertRaises(BundleError): verify_bundle(self.bundle, self.root)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private-journal'; self.j = OperationJournal(self.path)
        self.fp = 'a' * 64

    def test_intent_is_durable_before_operation(self):
        self.assertIsNone(self.j.begin('candidate:upload', self.fp))
        reopened = OperationJournal(self.path)
        self.assertEqual(reopened.read('candidate:upload')['state'], 'started')
        with self.assertRaises(UncertainOperation): reopened.begin('candidate:upload', self.fp)

    def test_unknown_never_auto_replays_and_can_be_reconciled(self):
        self.j.begin('upload', self.fp); self.j.unknown('upload', 'TRANSPORT_TIMEOUT')
        with self.assertRaises(UncertainOperation): self.j.begin('upload', self.fp)
        self.j.acknowledge('upload', {'asset_id': 'verified-provider-id', 'state': 'processing'})
        self.assertEqual(self.j.begin('upload', self.fp)['asset_id'], 'verified-provider-id')

    def test_changed_input_or_acknowledged_result_rejected(self):
        self.j.begin('upload', self.fp); self.j.acknowledge('upload', {'asset_id': 'one'})
        with self.assertRaises(JournalConflictError): self.j.begin('upload', 'b' * 64)
        with self.assertRaises(JournalConflictError): self.j.acknowledge('upload', {'asset_id': 'two'})

    def test_secrets_and_signed_urls_never_persisted(self):
        self.j.begin('upload', self.fp)
        for result in ({'access_token': 'test-only'}, {'url': 'https://upload.example/path?sig=test'},
                       {'value': 'Bearer test-only'}):
            with self.subTest(result=result), self.assertRaises(JournalError): self.j.acknowledge('upload', result)
        for p in self.path.glob('*.json'):
            self.assertNotIn('test-only', p.read_text())

    def test_ack_without_intent_and_unsafe_key_rejected(self):
        with self.assertRaises(JournalError): self.j.acknowledge('upload', {})
        with self.assertRaises(JournalError): self.j.begin('../escape', self.fp)

    def test_private_permissions_and_symlinked_record(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)
        self.j.begin('upload', self.fp)
        record = next(self.path.glob('*.json'))
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        record.unlink(); record.symlink_to(self.path / 'missing')
        with self.assertRaises(JournalError): self.j.read('upload')


if __name__ == '__main__': unittest.main()
