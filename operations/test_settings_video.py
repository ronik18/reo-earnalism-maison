import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
PROBE = ("import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); "
         "django.setup(); from django.conf import settings; print(settings.VIDEO_PROVIDER)")
R2_DUMMY = {'MEDIA_STORAGE_BACKEND': 'r2', 'R2_ACCOUNT_ID': 'a' * 32, 'R2_PRIVATE_BUCKET': 'test-private',
            'R2_APPLICATION_KEY_ID': 'x', 'R2_APPLICATION_SECRET': 'x', 'R2_UPLOAD_KEY_ID': 'x', 'R2_UPLOAD_SECRET': 'x'}
STREAM_VARS = ['STREAM_ACCOUNT_ID', 'STREAM_API_TOKEN', 'STREAM_SIGNING_KEY_ID',
               'STREAM_SIGNING_PRIVATE_KEY', 'STREAM_CUSTOMER_HOST']


def load_settings(**overrides):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('MAISON_VIDEO', 'STREAM_')) and k not in {'MAISON_ENV_FILE'}}
    env['MAISON_ENV'] = 'local'
    env['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run([sys.executable, '-c', PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


class VideoProviderSettingsTests(SimpleTestCase):
    def test_default_provider_is_r2(self):
        r = load_settings()
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertEqual(r.stdout.strip().splitlines()[-1], 'r2')

    def test_video_r2_without_stream_vars_ok(self):
        r = load_settings(MAISON_VIDEO='true', **R2_DUMMY)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertEqual(r.stdout.strip().splitlines()[-1], 'r2')

    def test_video_stream_still_requires_stream_profile(self):
        r = load_settings(MAISON_VIDEO='true', MAISON_VIDEO_PROVIDER='stream')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('ImproperlyConfigured', r.stderr)
        self.assertIn('Stream', r.stderr)

    def test_stream_provider_with_video_off_needs_no_stream_vars(self):
        r = load_settings(MAISON_VIDEO_PROVIDER='stream')
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertEqual(r.stdout.strip().splitlines()[-1], 'stream')

    def test_unknown_video_provider_refused_even_with_video_off(self):
        for video in (None, 'true'):
            r = load_settings(MAISON_VIDEO=video, MAISON_VIDEO_PROVIDER='vimeo')
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('ImproperlyConfigured', r.stderr)
            self.assertIn('MAISON_VIDEO_PROVIDER', r.stderr)

    def test_video_r2_with_local_backend_in_production_refused(self):
        from config.settings import video_configuration_error as err
        self.assertIsNotNone(err(True, 'r2', 'local', False, False))
        self.assertIsNone(err(True, 'r2', 'r2', False, False))
        self.assertIsNone(err(True, 'r2', 'local', True, False))
        self.assertIsNone(err(False, 'r2', 'local', False, False))

    def test_pure_rule_matrix(self):
        from config.settings import video_configuration_error as err
        self.assertIsNotNone(err(True, 'stream', 'r2', False, False))
        self.assertIsNone(err(True, 'stream', 'r2', False, True))
        self.assertIsNone(err(False, 'stream', 'r2', False, False))
        self.assertIsNotNone(err(False, 'bogus', 'r2', True, True))
