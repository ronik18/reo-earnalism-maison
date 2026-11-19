"""Controlled pipeline tests; actual archive/age/PG restore remains qualification."""
import hashlib
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from operations.qualification.restore_scheduled_archive import RestoreError, restore_archive, validate_reference

REFERENCE = {'format':'postgres-jsonb-C-SHA256-lengthprefixed-v1','schema':'public',
             'tables':{'fixture':{'rows':1,'sha256':'a'*64,'columns_sha256':'b'*64}}}


class FakeProcess:
    def __init__(self,code=0):
        self.stdout=io.BytesIO(b'fixture-stream');self.returncode=code
    def poll(self):return self.returncode


class RestoreQualificationTests(TestCase):
    def files(self,directory):
        root=Path(directory);cipher=root/'backup.dump.age';manifest=root/'manifest.json';identity=root/'owner.identity'
        cipher.write_bytes(b'ciphertext-fixture')
        manifest.write_text(json.dumps({'ciphertext_bytes':cipher.stat().st_size,'ciphertext_sha256':hashlib.sha256(cipher.read_bytes()).hexdigest(),'table_reference':REFERENCE}))
        identity.write_text('synthetic-unused-test-placeholder');identity.chmod(0o600)
        return cipher,manifest,identity

    def test_reference_required_and_cannot_silently_ignore_volatile_tables(self):
        for manifest in [{},{'table_reference':{'format':'unknown'}},{'table_reference':{**REFERENCE,'tables':{}}}]:
            with self.assertRaises(RestoreError):validate_reference(manifest)
        self.assertEqual(validate_reference({'table_reference':REFERENCE}),REFERENCE)

    def test_checksum_failure_precedes_private_identity_or_database_use(self):
        with tempfile.TemporaryDirectory() as directory:
            cipher,manifest,identity=self.files(directory);cipher.write_bytes(b'corrupted')
            with patch('psycopg.connect') as connect,patch('subprocess.Popen') as popen,self.assertRaises(RestoreError):
                restore_archive(cipher,manifest,identity,'postgresql://maison:local-pass@127.0.0.1/maison?sslmode=disable')
            connect.assert_not_called();popen.assert_not_called()

    def test_remote_target_and_world_readable_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            files=self.files(directory)
            with patch('psycopg.connect') as connect,self.assertRaises(RestoreError):
                restore_archive(*files,'postgresql://maison:pass@remote.example.test/maison?sslmode=verify-full')
            connect.assert_not_called()
            files[2].chmod(0o644)
            with self.assertRaises(RestoreError):
                restore_archive(*files,'postgresql://maison:pass@127.0.0.1/maison?sslmode=disable')

    def pipeline(self,files,*,restore_code=0,actual=None):
        connection=MagicMock();connection.__enter__.return_value=connection
        connection.execute.return_value.fetchone.return_value=(180007,)
        def run(argv,**kwargs):return SimpleNamespace(stdout='pg_restore (PostgreSQL) 18.7\n',returncode=0)
        with patch('psycopg.connect',return_value=connection),patch('subprocess.run',side_effect=run) as commands,patch('subprocess.Popen',side_effect=[FakeProcess(),FakeProcess(restore_code)]) as pipes,patch('operations.qualification.restore_scheduled_archive.database_reference',return_value=actual or REFERENCE):
            if restore_code:
                with self.assertRaises(RestoreError):
                    restore_archive(*files,'postgresql://maison:local-pass@127.0.0.1/maison?sslmode=disable')
                result=None
            else:
                result=restore_archive(*files,'postgresql://maison:local-pass@127.0.0.1/maison?sslmode=disable')
        return result,commands,pipes

    def test_stream_pipeline_isolates_identity_and_removes_only_generated_target(self):
        with tempfile.TemporaryDirectory() as directory:
            files=self.files(directory);result,commands,pipes=self.pipeline(files)
            self.assertTrue(result['row_counts_content_and_column_hashes_match'])
            self.assertFalse(result['plaintext_dump_written']);self.assertEqual(result['tables_compared'],1)
            self.assertNotIn('PGPASSWORD',pipes.call_args_list[0].kwargs['env'])
            self.assertNotIn('DATABASE_URL',pipes.call_args_list[0].kwargs['env'])
            self.assertIn('--single-transaction',pipes.call_args_list[1].args[0])
            create=next(c.args[0] for c in commands.call_args_list if c.args[0][0]=='createdb')
            drop=next(c.args[0] for c in commands.call_args_list if c.args[0][0]=='dropdb')
            self.assertRegex(create[-1],r'^maison_restore_archive_[a-f0-9]{12}$')
            self.assertEqual(create[-1],drop[-1]);self.assertNotEqual(drop[-1],'maison')
            self.assertEqual(len(list(Path(directory).iterdir())),3)

    def test_failed_restore_still_cleans_only_its_created_target(self):
        with tempfile.TemporaryDirectory() as directory:
            _,commands,_=self.pipeline(self.files(directory),restore_code=1)
            self.assertTrue(any(c.args[0][0]=='dropdb' for c in commands.call_args_list))
