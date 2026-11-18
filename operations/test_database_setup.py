import io
from unittest.mock import MagicMock, patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class DatabaseTimeoutSetupTests(SimpleTestCase):
    @override_settings(DATABASE_CONNECTION_ROLE='pooled')
    def test_admin_setup_rejects_pooled_configuration(self):
        with self.assertRaises(CommandError):
            call_command('configure_database_timeouts', stdout=io.StringIO())

    @override_settings(DATABASE_CONNECTION_ROLE='direct')
    def test_admin_setup_rejects_pooler_host_even_when_mislabeled(self):
        with patch('operations.management.commands.configure_database_timeouts.connection') as db:
            db.settings_dict = {'HOST': 'ep-example-pooler.region.neon.tech'}
            with self.assertRaises(CommandError):
                call_command('configure_database_timeouts', stdout=io.StringIO())
            db.cursor.assert_not_called()

    @override_settings(DATABASE_CONNECTION_ROLE='direct')
    def test_defaults_are_scoped_to_resolved_role_and_database(self):
        db = MagicMock()
        db.settings_dict = {'HOST': 'ep-example.region.neon.tech'}
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ('current-role', 'current-db')
        with patch('operations.management.commands.configure_database_timeouts.connection', db):
            call_command('configure_database_timeouts', stdout=io.StringIO())
        queries = [args.args[0].as_string() for args in cursor.execute.call_args_list[1:]]
        self.assertEqual(len(queries), 3)
        for query in queries:
            self.assertTrue(query.startswith('ALTER ROLE "current-role" IN DATABASE "current-db" SET '))
        self.assertIn('"statement_timeout" TO \'5s\'', queries[0])
        self.assertIn('"lock_timeout" TO \'2s\'', queries[1])
        self.assertIn('"idle_in_transaction_session_timeout" TO \'10s\'', queries[2])

class DatabaseConfigurationTests(SimpleTestCase):
    def settings_process(self, **updates):
        import os, subprocess, sys
        from pathlib import Path
        env = dict(os.environ)
        env.update(MAISON_ENV='local', MAISON_ENV_FILE='', MAISON_DATABASE_ROLE='pooled',
                   DATABASE_URL='postgresql://review:unused@ep-test-pooler.region.neon.tech/maison?sslmode=disable',
                   DATABASE_DIRECT_URL='', DATABASE_URL_UNPOOLED='')
        env.update(updates)
        return subprocess.run([sys.executable, '-c',
            "import config.settings as s; print(s.DATABASES['default']['OPTIONS']['sslmode']); "
            "print('options' in s.DATABASES['default']['OPTIONS']); "
            "print(s.DATABASES.get('maintenance',{}).get('OPTIONS',{}).get('sslmode')); "
            "print(s.PRIVACY_EXPORT_DB_ALIAS)"], env=env,
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)

    def test_neon_pool_omits_startup_options_and_direct_export_verifies_tls(self):
        result = self.settings_process(DATABASE_URL_UNPOOLED='postgresql://review:unused@ep-test.region.neon.tech/maison?sslmode=disable')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['verify-full', 'False', 'verify-full', 'maintenance'])

    def test_direct_export_cannot_target_another_database_or_endpoint(self):
        for url in ['postgresql://review:unused@ep-other.region.neon.tech/maison',
                    'postgresql://review:unused@ep-test.region.neon.tech/another']:
            with self.subTest(url=url):
                result = self.settings_process(DATABASE_URL_UNPOOLED=url)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('same database endpoint', result.stderr)

    def test_production_requires_direct_export_configuration(self):
        result = self.settings_process(MAISON_ENV='production', DJANGO_SECRET_KEY='x'*64,
            ALLOWED_HOSTS='maison.example')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Production requires a direct database URL', result.stderr)


    def test_public_asset_host_is_one_exact_https_hostname(self):
        self.assertEqual(self.settings_process(R2_PUBLIC_ASSET_HOST='https://assets.maison.example').returncode,0)
        for host in ['https://assets.example;script-src *','https://assets.example:443','https://assets.example/path','https://test.r2.dev','https://bad_host.example','https://assets.example?x=1']:
            with self.subTest(host=host):
                result=self.settings_process(R2_PUBLIC_ASSET_HOST=host)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('dedicated HTTPS CDN hostname',result.stderr)
