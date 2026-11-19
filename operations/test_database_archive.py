import hashlib
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from .database_archive import Archive, ArchiveConfig, ArchiveError, ROOT
from .scheduled_export import main


class Missing(Exception):
    response = {'Error': {'Code': '404'}}


class Precondition(Exception):
    response = {'Error': {'Code': '412'}}


class FakeR2:
    """Transport-only fixture; never a real R2/cryptographic acceptance claim."""
    def __init__(self):
        self.objects = {}; self.metadata = {}; self.modified = {}; self.deleted = []; self.truncated = False; self.corrupt = False

    def put_object(self, Bucket, Key, Body, Metadata, **kwargs):
        if Key in self.objects:
            raise Precondition()
        self.objects[Key] = Body.read() if hasattr(Body, 'read') else Body
        self.metadata[Key] = Metadata
        self.modified[Key] = datetime.now(timezone.utc)

    def get_object(self, Bucket, Key):
        data = self.objects[Key]
        if self.corrupt and Key.endswith('.dump.age'):
            data = data[:-1] + b'!'
        return {'Body': io.BytesIO(data), 'ContentLength': len(data)}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {'Contents': [{'Key': key, 'LastModified': self.modified.get(key)} for key in keys[:MaxKeys]], 'IsTruncated': self.truncated or len(keys) > MaxKeys}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise Missing()
        return {'Metadata': self.metadata.get(Key, {}), 'ContentLength': len(self.objects[Key]), 'LastModified': self.modified.get(Key)}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key); self.objects.pop(Key, None)


class DatabaseArchiveTests(TestCase):
    def setUp(self):
        self.config = ArchiveConfig('https://' + 'a' * 32 + '.r2.cloudflarestorage.com', 'maison-backups', 'fake-key', 'fake-secret')
        self.client = FakeR2(); self.archive = Archive(self.config, self.client)
        self.now = datetime(2026, 11, 19, 3, tzinfo=timezone.utc)

    def bundle(self, root, completed=None, suffix='a' * 12):
        completed = completed or self.now
        name = 'maison-' + completed.strftime('%Y%m%dT%H%M%SZ') + '-' + suffix + '.dump.age'
        data = b'age-encryption.org/v1\n->' + b'ciphertext-only-fixture'
        Path(root, name).write_bytes(data)
        return {'ciphertext_file': name, 'ciphertext_sha256': hashlib.sha256(data).hexdigest(),
                'ciphertext_bytes': len(data), 'completed_at': completed.isoformat(), 'restore_verified': False}

    def upload(self, completed=None, suffix='a' * 12):
        with tempfile.TemporaryDirectory() as directory:
            report = self.bundle(directory, completed, suffix)
            return self.archive.upload(report, directory)

    def test_upload_verifies_both_pairs_and_month_is_immutable(self):
        receipts = self.upload()
        self.assertEqual([r['class'] for r in receipts], ['daily', 'monthly'])
        monthly = {k: v for k, v in self.client.objects.items() if '/monthly/' in k}
        next_receipts = self.upload(self.now + timedelta(days=1), 'b' * 12)
        self.assertEqual(len(next_receipts), 1)
        self.assertEqual(monthly, {k: v for k, v in self.client.objects.items() if '/monthly/' in k})
        manifest = self.archive.manifest(receipts[0]['manifest_key'])
        self.assertTrue(manifest['provider_uploaded']); self.assertFalse(manifest['restore_verified'])

    def test_corrupt_readback_never_commits_manifest(self):
        self.client.corrupt = True
        with self.assertRaises(ArchiveError):
            self.upload()
        self.assertFalse(any(k.endswith('.json') for k in self.client.objects))

    def test_lost_response_retry_verifies_immutable_existing_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.bundle(directory)
            first = self.archive.upload(report, directory)
            before = dict(self.client.objects)
            retry = self.archive.upload(report, directory)
            self.assertEqual(before, self.client.objects)
            self.assertEqual(retry[0], first[0])

    def test_daily_30days_latest12_months_preview_apply_and_unrelated_preserved(self):
        for month in range(1, 13):
            self.upload(datetime(2025, month, 1, tzinfo=timezone.utc), f'{month:012x}')
        self.upload(datetime(2026, 1, 1, tzinfo=timezone.utc), 'd' * 12)
        protected = ['revisions/book/manuscript.json', 'static/release/logo.png', 'exports/user.json', ROOT + 'daily/unknown-file.txt']
        for key in protected:
            self.client.objects[key] = b'preserve'
        preview = self.archive.retention(now=self.now)
        self.assertEqual(preview['eligible_pairs'], 14)  #13daily + oldestmonthly.
        self.assertEqual(self.client.deleted, [])
        applied = self.archive.retention(now=self.now, apply=True)
        self.assertEqual(applied['removed_pairs'], 14)
        self.assertEqual(sum(k.endswith('/manifest.json') and '/monthly/' in k for k in self.client.objects), 12)
        self.assertTrue(all(key in self.client.objects for key in protected))
        self.assertEqual(self.archive.retention(now=self.now, apply=True)['removed_pairs'], 0)

    def test_exact_daily_boundary_and_holds_never_auto_expire(self):
        completed = self.now - timedelta(days=30)
        receipts = self.upload(completed)
        daily = receipts[0]['manifest_key']
        self.assertEqual(self.archive.retention(now=self.now - timedelta(seconds=1))['eligible_pairs'], 0)
        value = self.archive.manifest(daily)
        self.client.metadata[value['ciphertext_key']]['retention-hold'] = 'true'
        result = self.archive.retention(now=self.now + timedelta(days=100), apply=True)
        self.assertEqual(result['held_pairs'], 1); self.assertEqual(result['removed_pairs'], 0)
        self.assertIn(daily, self.client.objects)

    def test_prefix_hold_and_scan_bounds_fail_closed(self):
        receipts = self.upload(self.now - timedelta(days=40))
        prefix = receipts[0]['manifest_key'].rsplit('/', 1)[0] + '/'
        config = ArchiveConfig(**{**self.config.__dict__, 'held_prefixes': (prefix,)})
        self.assertEqual(Archive(config, self.client).retention(now=self.now)['held_pairs'], 1)
        self.client.truncated = True
        with self.assertRaises(ArchiveError):
            self.archive.retention(now=self.now, apply=True)
        self.assertEqual(self.client.deleted, [])

    def test_malformed_manifest_cannot_target_manuscript(self):
        receipts = self.upload(self.now - timedelta(days=40))
        key = receipts[0]['manifest_key']; value = json.loads(self.client.objects[key])
        value['ciphertext_key'] = 'revisions/private/manuscript'
        self.client.objects[key] = json.dumps(value).encode()
        self.client.metadata[key]['sha256'] = hashlib.sha256(self.client.objects[key]).hexdigest()
        with self.assertRaises(ArchiveError):
            self.archive.retention(now=self.now, apply=True)
        self.assertEqual(self.client.deleted, [])

    def test_manifest_stamp_or_class_mismatch_fails_without_deletion(self):
        receipts = self.upload(self.now - timedelta(days=40))
        key = receipts[0]['manifest_key']; original = self.client.objects[key]
        for patch_value in [{'completed_at': self.now.isoformat()}, {'retention_class': 'monthly'}]:
            value = {**json.loads(original), **patch_value}
            self.client.objects[key] = json.dumps(value).encode()
            self.client.metadata[key]['sha256'] = hashlib.sha256(self.client.objects[key]).hexdigest()
            with self.assertRaises(ArchiveError):
                self.archive.retention(now=self.now, apply=True)
            self.assertEqual(self.client.deleted, [])
        self.client.objects[key] = original
        self.client.metadata[key]['sha256'] = hashlib.sha256(original).hexdigest()
        bad_month = ROOT + 'monthly/2026-99/manifest.json'
        self.client.objects[bad_month] = self.client.objects[receipts[1]['manifest_key']]
        self.client.metadata[bad_month] = dict(self.client.metadata[receipts[1]['manifest_key']])
        with self.assertRaises(ArchiveError):
            self.archive.retention(now=self.now, apply=True)

    def test_missing_retained_month_cannot_trigger_prune_of_valid_older_snapshot(self):
        for month in range(1, 13):
            self.upload(datetime(2025, month, 1, tzinfo=timezone.utc), f'{month:012x}')
        self.upload(datetime(2026, 1, 1, tzinfo=timezone.utc), 'd' * 12)
        newest = ROOT + 'monthly/2026-01/manifest.json'
        value = self.archive.manifest(newest)
        self.client.objects.pop(value['ciphertext_key'])
        with self.assertRaises(ArchiveError):
            self.archive.retention(now=self.now, apply=True)
        self.assertEqual(self.client.deleted, [])

    def test_partial_delete_retries_generated_pair_idempotently(self):
        receipts = self.upload(self.now - timedelta(days=40))
        key = receipts[0]['manifest_key']; value = self.archive.manifest(key)
        # Simulates ciphertext deletion succeeding before a process interruption.
        self.client.objects.pop(value['ciphertext_key'])
        self.assertEqual(self.archive.retention(now=self.now, apply=True)['removed_pairs'], 1)
        self.assertNotIn(key, self.client.objects)

    def test_invalid_config_and_missing_environment_fail_without_export(self):
        for values in [{'endpoint': 'http://unsafe.test'}, {'held_prefixes': ('revisions/',)}, {'max_objects': 0}]:
            with self.assertRaises(ArchiveError):
                ArchiveConfig(**{**self.config.__dict__, **values}).validate()
        with patch.dict('os.environ', {}, clear=True), patch('operations.scheduled_export.export_database') as export, patch('builtins.print'):
            self.assertEqual(main([]), 1)
        export.assert_not_called()

    def test_scheduled_entrypoint_uses_separate_credentials_and_previews_retention(self):
        env = {'BACKUP_R2_ENDPOINT': self.config.endpoint, 'BACKUP_R2_BUCKET': self.config.bucket,
               'BACKUP_R2_KEY_ID': 'fixture-key', 'BACKUP_R2_SECRET': 'fixture-secret',
               'MAISON_BACKUP_DATABASE_URL': 'postgresql://backup-only@example.test/db?sslmode=verify-full',
               'BACKUP_AGE_RECIPIENT': 'age1' + 'q' * 58}
        def export(url, recipient, directory, **options):
            self.assertEqual(url, env['MAISON_BACKUP_DATABASE_URL'])
            self.assertEqual(recipient, env['BACKUP_AGE_RECIPIENT'])
            self.assertFalse(options['with_reference'])
            return self.bundle(directory, datetime.now(timezone.utc) - timedelta(seconds=1))
        with patch.dict('os.environ', env, clear=True), patch('operations.database_archive.archive_client', return_value=self.client), patch('operations.scheduled_export.export_database', side_effect=export), patch('builtins.print') as output:
            self.assertEqual(main([]), 0)
        result = json.loads(output.call_args.args[0])
        self.assertTrue(result['retention']['dry_run'])
        self.assertFalse(result['restore_verified'])
        self.assertEqual(self.client.deleted, [])

    def test_provider_errors_never_echo_credentials_or_signed_requests(self):
        env = {'BACKUP_R2_ENDPOINT': self.config.endpoint, 'BACKUP_R2_BUCKET': self.config.bucket,
               'BACKUP_R2_KEY_ID': 'fixture-key', 'BACKUP_R2_SECRET': 'do-not-output-secret'}
        with patch.dict('os.environ', env, clear=True), patch('operations.scheduled_export.export_database', side_effect=OSError('do-not-output-secret')), patch('builtins.print') as output:
            self.assertEqual(main([]), 1)
        self.assertNotIn('do-not-output-secret', output.call_args.args[0])

    def test_old_generated_orphan_cleanup_preserves_recent_unknown_and_held(self):
        prefix = ROOT + 'monthly/2025-01/'
        keys = [prefix + f'maison-20250101T000000Z-{n:012x}.dump.age' for n in range(4)]
        for key in keys:
            self.client.objects[key] = b'fixture-cipher'
            self.client.metadata[key] = {'maison-backup': 'v1', 'sha256': 'a' * 64}
            self.client.modified[key] = self.now - timedelta(days=31)
        self.client.modified[keys[1]] = self.now - timedelta(days=29)
        self.client.metadata[keys[2]]['retention-hold'] = 'true'
        self.client.metadata[keys[3]] = {'unknown': 'preserve'}
        unknown = prefix + 'manual-private-file.dump.age'
        self.client.objects[unknown] = b'private'; self.client.modified[unknown] = self.now - timedelta(days=100)
        preview = self.archive.retention(now=self.now)
        self.assertEqual(preview['orphan_targets'], [keys[0]])
        self.assertEqual(self.client.deleted, [])
        result = self.archive.retention(now=self.now, apply=True)
        self.assertEqual(result['removed_orphans'], 1)
        self.assertEqual(result['held_orphans'], 1)
        self.assertTrue(all(key in self.client.objects for key in keys[1:] + [unknown]))
