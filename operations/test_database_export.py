import json,os,tempfile,time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch,MagicMock
from django.core.management.base import CommandError
from operations.management.commands.export_database import Command
from operations.database_export import ExportError,database_environment,export_database,export_reference_snapshot,database_reference

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

    def test_snapshot_reference_is_opt_in_and_passed_to_dump_without_reporting_id(self):
        from contextlib import contextmanager
        reference={'format':'fixture-reference','tables':{'fixture':{'rows':1,'sha256':'a'*64}}}
        @contextmanager
        def snapshot(env,deadline,enabled):
            self.assertTrue(enabled)
            yield '00000001-00000002-1',reference
        with tempfile.TemporaryDirectory() as directory,patch('operations.database_export.database_facts',return_value=FACTS),patch('operations.database_export.export_reference_snapshot',side_effect=snapshot):
            programs=self._pipeline(directory,dump='import sys;assert "--snapshot=00000001-00000002-1" in sys.argv;sys.stdout.buffer.write(b"snapshot-bytes")')
            report=export_database('postgresql://backup:pass@127.0.0.1/maison?sslmode=disable',RECIPIENT,Path(directory)/'out',local=True,with_reference=True,**programs)
            self.assertEqual(report['table_reference'],reference)
            self.assertNotIn('00000001-00000002-1',json.dumps(report))

    def test_snapshot_connection_rolls_back_and_closes_on_failure(self):
        env=database_environment('postgresql://backup:pass@127.0.0.1/maison?sslmode=disable',local=True)
        connection=MagicMock();connection.execute.return_value.fetchone.return_value=('00000001-00000002-1',)
        with patch('psycopg.connect',return_value=connection) as connect,patch('operations.database_export.database_reference',return_value={'tables':{}}):
            with self.assertRaises(ExportError):
                with export_reference_snapshot(env,time.monotonic()+10,True):
                    raise ExportError('pipeline failed')
        self.assertTrue(connect.call_args.kwargs['autocommit'])
        connection.execute.assert_any_call('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        connection.rollback.assert_called_once();connection.close.assert_called_once()

    def test_expired_snapshot_deadline_never_connects(self):
        with patch('psycopg.connect') as connect,self.assertRaises(ExportError):
            with export_reference_snapshot({},time.monotonic()-1,True):pass
        connect.assert_not_called()

    def test_manifest_bound_checks_exact_indented_bytes_not_compact_estimate(self):
        from contextlib import contextmanager
        # Many compact small keys cause indentation to dominate the stored size.
        reference={'format':'fixture-reference','tables':{f'table_{i}':{'rows':0,'sha256':'a'*64,'columns_sha256':'b'*64} for i in range(310)}}
        self.assertLess(len(json.dumps(reference,separators=(',',':')).encode())+1024,65536)
        self.assertGreater(len((json.dumps(reference,indent=2)+'\n').encode()),65536)
        @contextmanager
        def snapshot(*args):yield '00000001-00000002-1',reference
        with tempfile.TemporaryDirectory() as directory,patch('operations.database_export.database_facts',return_value=FACTS),patch('operations.database_export.export_reference_snapshot',side_effect=snapshot):
            output=Path(directory)/'out'
            with self.assertRaisesRegex(ExportError,'manifest exceeds'):
                export_database('postgresql://backup:pass@127.0.0.1/maison?sslmode=disable',RECIPIENT,output,local=True,with_reference=True,**self._pipeline(directory))
            self.assertEqual(list(output.iterdir()),[])


from django.test import TransactionTestCase
from django.db import connection
from unittest import skipUnless


@skipUnless(connection.vendor=='postgresql','PostgreSQL snapshot qualification')
class ConsistentReferenceTests(TransactionTestCase):
    def test_reference_snapshot_survives_concurrent_volatile_row_insert(self):
        import psycopg
        from psycopg import sql
        from core.models import OutboxJob
        from django.utils import timezone
        # Other TransactionTestCases can close the wrapper; exercise that cold
        # start explicitly instead of depending on test execution order.
        connection.close()
        connection.ensure_connection()
        config=connection.settings_dict
        env={'PGHOST':config.get('HOST') or '127.0.0.1','PGPORT':str(config.get('PORT') or 5432),'PGUSER':config['USER'],
             'PGPASSWORD':config['PASSWORD'],'PGDATABASE':connection.connection.info.dbname,'PGSSLMODE':'disable'}
        deadline=time.monotonic()+30
        with export_reference_snapshot(env,deadline,True) as (snapshot,reference):
            OutboxJob.objects.create(kind='fixture_reference',dedupe_key='snapshot-fixture',status='done',not_before=timezone.now())
            params=connection.get_connection_params();params['autocommit']=True
            with psycopg.connect(**params) as imported:
                imported.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                imported.execute(sql.SQL('SET TRANSACTION SNAPSHOT {}').format(sql.Literal(snapshot)))
                self.assertEqual(database_reference(imported,deadline),reference)
                imported.rollback()
        with psycopg.connect(**params) as current:
            current.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            actual=database_reference(current,deadline);current.rollback()
        self.assertEqual(actual['tables']['maison_outbox']['rows'],reference['tables']['maison_outbox']['rows']+1)
        self.assertNotEqual(actual['tables']['maison_outbox']['sha256'],reference['tables']['maison_outbox']['sha256'])
