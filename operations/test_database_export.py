import json,os,tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from django.core.management.base import CommandError
from operations.management.commands.export_database import Command
from operations.database_export import ExportError,database_environment,export_database

RECIPIENT='age1'+'q'*58
FACTS={'server_version_num':180007,'migration_count':43,'migration_sha256':'synthetic-test-only'}

class DatabaseExportTests(TestCase):
    def test_command_requires_encryption_manifest_and_separate_backup_url(self):
        options=dict(encrypted=True,manifest=True,output_dir=None,max_seconds=900,max_bytes=1000)
        for flag in ['encrypted','manifest']:
            with self.assertRaises(CommandError):Command().handle(**{**options,flag:False})
        with patch.dict(os.environ,{},clear=True),self.assertRaises(CommandError):Command().handle(**options)

    def test_direct_verified_database_and_separate_environment(self):
        with patch.dict(os.environ,{'UNRELATED_PROVIDER_SECRET':'must-not-inherit','PGPASSWORD':'stale'}):
            env=database_environment('postgresql://backup:private-pass@direct.example.test/maison?sslmode=verify-full')
        self.assertEqual(env['PGPASSWORD'],'private-pass')
        self.assertNotIn('UNRELATED_PROVIDER_SECRET',env)
        self.assertEqual(env['PGSSLMODE'],'verify-full')
        for url in ['postgresql://backup:pass@ep-test-pooler.example.test/maison?sslmode=verify-full',
                    'postgresql://backup:pass@direct.example.test/maison?sslmode=disable',
                    'postgresql://backup:pass@direct.example.test/maison?sslmode=verify-full&sslmode=disable','']:
            with self.assertRaises(ExportError):database_environment(url)

    def _program(self,path,text):
        path.write_text('#!/usr/bin/env python3\n'+text);path.chmod(0o700);return str(path)

    def _pipeline(self,directory,*,dump='import sys;sys.stdout.buffer.write(b"private-database-bytes")',encrypt=None):
        root=Path(directory)
        dump_program=self._program(root/'pg_dump','import sys\nif "--version" in sys.argv:\n print("pg_dump (PostgreSQL) 18.7");sys.exit(0)\n'+dump+'\n')
        # Deliberately fake encryption tests pipeline control only, not crypto correctness.
        encrypt=encrypt or 'import sys;sys.stdout.buffer.write(b"age-encryption.org/v1\\n->"+sys.stdin.buffer.read())'
        age_program=self._program(root/'age',encrypt+'\n')
        return dict(pg_dump=dump_program,age=age_program)

    def test_success_writes_only_private_ciphertext_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory,patch('operations.database_export.database_facts',return_value=FACTS):
            output=Path(directory)/'out'
            report=export_database('postgresql://backup:pass@127.0.0.1/maison?sslmode=disable',RECIPIENT,output,local=True,**self._pipeline(directory))
            files=list(output.iterdir());self.assertEqual(len(files),2)
            self.assertTrue(all(p.stat().st_mode&0o777==0o600 for p in files))
            self.assertFalse(any(p.suffix=='.dump' or p.name.startswith('.export-') for p in files))
            manifest=next(p for p in files if p.suffix=='.json')
            self.assertEqual(json.loads(manifest.read_text()),report)
            self.assertFalse(report['provider_uploaded']);self.assertFalse(report['restore_verified'])
            self.assertNotIn('private-pass',manifest.read_text())

    def test_failed_encryption_leaves_no_success_artifact(self):
        with tempfile.TemporaryDirectory() as directory,patch('operations.database_export.database_facts',return_value=FACTS):
            output=Path(directory)/'out'
            with self.assertRaises(ExportError):
                export_database('postgresql://backup:pass@127.0.0.1/maison?sslmode=disable',RECIPIENT,output,local=True,**self._pipeline(directory,encrypt='import sys;sys.exit(2)'))
            self.assertEqual(list(output.iterdir()),[])

    def test_timeout_and_size_failure_leave_no_success_artifact(self):
        for mode in ['timeout','size']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory,patch('operations.database_export.database_facts',return_value=FACTS):
                output=Path(directory)/'out'
                programs=self._pipeline(directory,dump='import time;time.sleep(10)' if mode=='timeout' else 'import sys;sys.stdout.buffer.write(b"x"*10000)')
                with self.assertRaises(ExportError):
                    export_database('postgresql://backup:pass@127.0.0.1/maison?sslmode=disable',RECIPIENT,output,local=True,max_seconds=.1 if mode=='timeout' else 10,max_bytes=100,**programs)
                self.assertEqual(list(output.iterdir()),[])
