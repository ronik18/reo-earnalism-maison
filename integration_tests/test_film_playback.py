"""Browser acceptance: a member plays a private Maison film with synced captions and survives grant expiry.

Real path, local storage backend: the film and its WebVTT are stored with ``library.storage`` as ready
assets of a published synthetic revision; the built client (``npm run build``) requests a real film grant,
plays the ``local_signed`` URL (byte ranges, 206) and loads captions from the authorized captions route.

Fixture provenance (``library/fixtures/film/``, original, synthetic, local-only, never published):
``synthetic-film.mp4`` is 8 s of 320x180 H.264 Constrained Baseline + mono AAC, faststart, made with
``ffmpeg -f lavfi -i testsrc=size=320x180:rate=15:duration=8 -f lavfi -i sine=frequency=440:sample_rate=22050:duration=8
-c:v libx264 -profile:v baseline -level 3.0 -pix_fmt yuv420p -b:v 160k -maxrate 180k -bufsize 180k -g 15
-c:a aac -b:a 32k -ac 1 -map_metadata -1 -fflags +bitexact -flags:v +bitexact -flags:a +bitexact
-movflags +faststart synthetic-film.mp4``; ``synthetic-film.vtt`` holds two original cues covering 0-8 s.

Grant expiry is forced by patching ``library.services.GRANT_SECONDS`` (which also bounds the signed token's
max_age) for the live server. A browser holds a whole 155 KiB film in memory after one request, so a test
network gate caps each forwarded byte range and withholds the film's second half until the grant has
expired: the seek past the watermark then genuinely reaches the server with an expired token (403) and the
client must renew the grant to resume. Every byte still comes from the real signed route.

Run: ``MAISON_TEST_DB_NAME=maison_test_t9 python3 manage.py test integration_tests.test_film_playback``.
Evidence: ``docs/evidence/film-delivery-20261124/browser.json`` (paths only; queries and tokens redacted), written only
with ``MAISON_WRITE_EVIDENCE=1``. With ``MAISON_REQUIRE_BROWSER=1`` (CI) a missing playwright or client bundle fails.
"""
import hashlib
import json
import os
import re
import time
import uuid
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import SkipTest
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from billing.models import Entitlement
from library import storage
from library.models import Asset, Edition, Revision, Rights, Unit, Work
from reader.models import Progress

FIXTURE = Path(settings.BASE_DIR) / 'library/fixtures/film'
EVIDENCE = Path(settings.BASE_DIR) / 'docs/evidence/film-delivery-20261124/browser.json'
PASSWORD = 'Synthetic-Film-Passphrase-47'
EXPIRY_SECONDS = 4
CHUNK = 16384
FEATURES = {**settings.FEATURES, 'video': True, 'offline_text_audio': True}
STATE = """() => { const v = document.querySelector('video'); const s = document.querySelector('[role=status]');
    return v ? {time: v.currentTime, paused: v.paused, ready: v.readyState, error: v.error && v.error.code,
                status: s && s.textContent} : {status: s && s.textContent, video: false}; }"""


def browser_prerequisites(manifest=None):
    """Skip locally when playwright or the built bundle is absent; with MAISON_REQUIRE_BROWSER=1 (CI) fail instead."""
    required = os.getenv('MAISON_REQUIRE_BROWSER') == '1'
    manifest = manifest or Path(settings.BASE_DIR) / 'static/maison/dist/manifest.json'

    def missing(reason):
        if required:
            raise AssertionError(f'MAISON_REQUIRE_BROWSER=1: {reason}')
        raise SkipTest(reason)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        missing('Python playwright is required for browser acceptance (pip install playwright==1.63.0)')
    if not manifest.exists():
        missing('Build the client first: npm run build')
    return sync_playwright


def write_evidence_enabled():
    """Evidence is rewritten only on request (MAISON_WRITE_EVIDENCE=1), never as a side effect of a test run."""
    return os.getenv('MAISON_WRITE_EVIDENCE', '0') == '1'


def redact(url):
    return urlsplit(url).path + ('?<redacted>' if urlsplit(url).query else '')


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=False, FREE_ACCESS_ENABLED=False, FEATURES=FEATURES,
                   FEATURE_FLAGS=FEATURES, VIDEO_PROVIDER='r2', MEDIA_STORAGE_BACKEND='local')
class FilmPlaybackBrowserTests(StaticLiveServerTestCase):
    host = '127.0.0.1'

    @classmethod
    def setUpClass(cls):
        sync_playwright = browser_prerequisites()
        super().setUpClass()
        # Playwright's sync API keeps an event loop on this thread; Django's documented opt-out for browser tests.
        cls.async_unsafe = os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE')
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception:
            cls.browser = cls.playwright.chromium.launch(executable_path='/opt/pw-browsers/chromium')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        if cls.async_unsafe is None:
            os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)
        else:
            os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = cls.async_unsafe

    def setUp(self):
        directory = TemporaryDirectory(prefix='maison-film-browser-')
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=Path(directory.name) / 'media')
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('film-browser@example.test', PASSWORD, is_verified=True)
        key = uuid.uuid4().hex[:12]
        work = Work.objects.create(slug='synthetic-film-browser-' + key, title='Synthetic film acceptance')
        self.edition = Edition.objects.create(work=work, slug=work.slug, locale='en')
        self.revision = Revision.objects.create(edition=self.edition, title=work.title, access_policy={'video': 'paid'})
        film = (FIXTURE / 'synthetic-film.mp4').read_bytes()
        captions = (FIXTURE / 'synthetic-film.vtt').read_bytes()
        self.unit = Unit.objects.create(revision=self.revision, ordinal=1, title='Synthetic film', duration_ms=8000)
        self.film = self.store('video', 'mp4', film, 'video/mp4', duration_ms=8000)
        self.captions = self.store('video_captions', 'vtt', captions, 'text/vtt')
        self.film_bytes = len(film)
        now = timezone.now()
        Rights.objects.create(revision=self.revision, format='video', action='read', territories=['IN'],
                              starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
                              approved=True, test_only=False)
        self.revision.state = 'live'
        self.revision.published_at = now
        self.revision.save()
        self.edition.live_revision = self.revision
        self.edition.save()
        Entitlement.objects.create(grant_key='synthetic-film-browser-' + key, user=self.user, edition=self.edition,
                                   formats=['video'], source='one_time_order', scope='edition',
                                   valid_from=now - timedelta(seconds=1), valid_until=now + timedelta(hours=1))

    def store(self, kind, suffix, raw, content_type, **fields):
        key = f'revisions/{self.revision.pk}/film/{uuid.uuid4().hex}.{suffix}'
        storage.put_private(key, raw, content_type)
        return Asset.objects.create(revision=self.revision, unit=self.unit, kind=kind, provider='r2', state='ready',
                                    storage_key=key, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                                    content_type=content_type, **fields)

    def wait(self, page, predicate, timeout=20, message=''):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = page.evaluate(predicate)
            if value:
                return value
            page.wait_for_timeout(100)
        self.fail(f'{message}: {page.evaluate(STATE)}')

    def test_film_plays_with_captions_and_survives_grant_expiry(self):
        context = self.browser.new_context(base_url=self.live_server_url)
        self.addCleanup(context.close)
        page = context.new_page()
        log, errors, gate = [], [], {'open': False, 'held': []}
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def record(response):
            path = urlsplit(response.url).path
            if path.startswith(('/api/v1/content/local-assets/', '/api/v1/content/video-captions/', '/api/v1/media/grants', '/api/v1/me/progress/')):
                log.append({'method': response.request.method, 'path': redact(response.url), 'status': response.status,
                            'range': response.request.headers.get('range'),
                            'content_range': response.headers.get('content-range'),
                            'cache_control': response.headers.get('cache-control'),
                            'from_service_worker': response.from_service_worker, 'at': round(time.monotonic(), 3)})
        page.on('response', record)

        def forward(route):
            """Cap each film range at CHUNK and hold ranges past the watermark until the gate opens."""
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', route.request.headers.get('range', 'bytes=0-'))
            start = int(match[1])
            if start >= self.film_bytes // 2 and not gate['open']:
                gate['held'].append(route)
                return
            end = min(int(match[2]) if match[2] else self.film_bytes - 1, start + CHUNK - 1)
            try:
                route.fulfill(response=route.fetch(headers={**route.request.headers, 'range': f'bytes={start}-{end}'}))
            except Exception:  # The element abandoned this range (seek or source swap).
                pass
        page.route(re.compile(r'.*/api/v1/content/local-assets/.*'), forward)

        # Sign in as the verified, entitled member through the real API.
        page.goto('/en/')
        login = page.evaluate("""async ([email, password]) => {
            const s = await (await fetch('/api/v1/session', {cache: 'no-store'})).json();
            const r = await fetch('/api/v1/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': s.csrf_token},
              body: JSON.stringify({email, password, password_purpose_consent: true, password_purpose_version: 'password-account-v1'})});
            return r.status; }""", [self.user.email, PASSWORD])
        self.assertEqual(login, 200)
        # The offline worker is enabled; reload until it controls the page so film requests pass through it.
        page.goto(f'/en/watch/{self.edition.pk}/')
        page.evaluate("() => navigator.serviceWorker.ready.then(() => true)")
        page.reload()
        self.assertTrue(page.evaluate("() => !!navigator.serviceWorker.controller"), 'service worker must control the page')

        with patch('library.services.GRANT_SECONDS', EXPIRY_SECONDS):
            page.get_by_role('button', name='Watch').click()
            page.wait_for_selector('video.stream-frame')
            page.evaluate("() => { const v = document.querySelector('video'); v.muted = true; return v.play(); }")
            first = self.wait(page, "() => { const v = document.querySelector('video'); return v.currentTime > 0.5 && v.currentTime; }",
                              message='film must play')
            later = self.wait(page, f"() => {{ const v = document.querySelector('video'); return v.currentTime > {first} + 0.3 && v.currentTime; }}",
                              message='currentTime must advance')
            cue = self.wait(page, """() => { const t = document.querySelector('video').textTracks[0];
                return t && t.mode === 'showing' && t.activeCues && t.activeCues.length > 0 && t.activeCues[0].text; }""",
                            message='captions must show an active cue')
            grants_before = sum(1 for e in log if e['path'] == '/api/v1/media/grants' and e['status'] == 200)
            # Let the grant (and its signed token) expire, then seek past the withheld watermark.
            page.wait_for_timeout((EXPIRY_SECONDS + 1.5) * 1000)
            gate['open'] = True
            for route in gate['held']:  # Still-wanted ranges now reach the server with the expired token.
                forward(route)
            target = 6.0
            page.evaluate(f"() => {{ document.querySelector('video').currentTime = {target}; }}")
            resumed = self.wait(page, f"""() => {{ const v = document.querySelector('video');
                return !v.paused && v.currentTime >= {target} && v.currentTime < {target} + 1.5 && v.readyState >= 3 && v.currentTime; }}""",
                                timeout=25, message='playback must resume at the sought time after renewal')
            advanced = self.wait(page, f"() => {{ const v = document.querySelector('video'); return v.currentTime > {resumed} + 0.2 && v.currentTime; }}",
                                 message='playback must advance after renewal')
            # Pausing saves the resumed position: the client's restoration completed and its handlers are live.
            paused_at = page.evaluate("() => { const v = document.querySelector('video'); v.pause(); return v.currentTime; }")
            deadline = time.monotonic() + 10
            saved = None
            while time.monotonic() < deadline and not (saved and abs(saved.get('position_ms', 0) / 1000 - paused_at) <= 0.5):
                page.wait_for_timeout(200)
                saved = Progress.objects.filter(user=self.user, edition=self.edition, format='video').values_list('location', flat=True).first()
            self.assertIsNotNone(saved, f'pausing must save video progress: {page.evaluate(STATE)} {log}')
            self.assertEqual(saved['unit_id'], str(self.unit.pk))
            self.assertAlmostEqual(saved['position_ms'] / 1000, paused_at, delta=0.5)

        expired = [e for e in log if e['path'].startswith('/api/v1/content/local-assets/') and e['status'] == 403]
        grants = [e for e in log if e['path'] == '/api/v1/media/grants' and e['status'] == 200]
        films = [e for e in log if e['path'].startswith('/api/v1/content/local-assets/')]
        captions = [e for e in log if e['path'].startswith('/api/v1/content/video-captions/')]
        self.assertTrue(expired, f'the seek must reach the server with the expired grant: {log}')
        self.assertGreater(len(grants), grants_before, f'the client must renew the expired grant: {log}')
        self.assertTrue(any(e['status'] == 206 for e in films), log)
        self.assertTrue(captions and all(e['status'] == 200 for e in captions), log)
        self.assertTrue(all(e['from_service_worker'] is False for e in log), log)
        self.assertTrue(all('no-store' in (e['cache_control'] or '') for e in films + captions if e['status'] in (200, 206)), log)
        cached = page.evaluate("""async () => { const out = [];
            for (const name of await caches.keys()) for (const r of await (await caches.open(name)).keys()) out.push(new URL(r.url).pathname);
            return out; }""")
        leaked = [p for p in cached if re.search(r'local-assets|video-captions|media/grants', p)]
        self.assertEqual(leaked, [], 'the service worker cache must never hold film, captions or grant responses')

        result = {
            'schema': 'maison-film-browser-acceptance-v1', 'date': '2026-11-24', 'status': 'pass',
            'scope': 'Synthetic local fixture film; covers no staged title, so it carries no staged content sha256.',
            'test': 'integration_tests.test_film_playback.FilmPlaybackBrowserTests.test_film_plays_with_captions_and_survives_grant_expiry',
            'browser': self.browser.browser_type.name + ' ' + self.browser.version,
            'storage_backend': 'local', 'transport': 'local_signed', 'provider': 'r2',
            'fixture': {'film': 'library/fixtures/film/synthetic-film.mp4', 'film_bytes': self.film_bytes,
                        'film_sha256': self.film.sha256, 'captions': 'library/fixtures/film/synthetic-film.vtt',
                        'captions_sha256': self.captions.sha256, 'synthetic': True},
            'forced_grant_seconds': EXPIRY_SECONDS, 'range_cap_bytes': CHUNK,
            'observations': {'first_time_s': round(first, 3), 'advanced_time_s': round(later, 3), 'active_cue': cue,
                             'seek_target_s': target, 'resumed_time_s': round(resumed, 3), 'after_resume_s': round(advanced, 3),
                             'paused_at_s': round(paused_at, 3), 'saved_position_ms': saved['position_ms'],
                             'grants_issued': len(grants), 'expired_film_requests_403': len(expired),
                             'service_worker_controlled': True, 'service_worker_cache_entries_checked': len(cached)},
            'checks': {'video_playback': True, 'captions_active_cue': True, 'grant_expiry_renewed_and_resumed': True,
                       'film_range_206': True, 'no_store_responses': True, 'not_from_service_worker': True,
                       'not_in_service_worker_cache': True, 'progress_saved_on_pause': True},
            'network': [{k: v for k, v in e.items() if k != 'at'} for e in log],
            'console_errors': [re.sub(r'token=[^\s&"]+', 'token=<redacted>', e) for e in errors],
            'scope_note': 'Local fixture success does not certify R2/CDN, real devices, rights or production release.',
        }
        text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
        self.assertNotIn('token=', text)
        if write_evidence_enabled():
            EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
            EVIDENCE.write_text(text)


class BrowserGateTests(SimpleTestCase):
    """CI sets MAISON_REQUIRE_BROWSER=1: a missing playwright or client bundle must fail, never skip."""

    def missing_playwright(self):
        import builtins
        real = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name.startswith('playwright'):
                raise ImportError('synthetic: playwright absent')
            return real(name, *args, **kwargs)
        return patch('builtins.__import__', side_effect=refuse)

    def test_missing_playwright_skips_by_default(self):
        with patch.dict(os.environ, {}, clear=False), self.missing_playwright():
            os.environ.pop('MAISON_REQUIRE_BROWSER', None)
            with self.assertRaises(SkipTest):
                browser_prerequisites()

    def test_missing_playwright_fails_when_browser_required(self):
        with patch.dict(os.environ, {'MAISON_REQUIRE_BROWSER': '1'}), self.missing_playwright():
            with self.assertRaises(AssertionError) as failed:
                browser_prerequisites()
        self.assertNotIsInstance(failed.exception, SkipTest)
        self.assertIn('playwright', str(failed.exception))

    def test_missing_bundle_fails_when_browser_required(self):
        with TemporaryDirectory() as empty, patch.dict(os.environ, {'MAISON_REQUIRE_BROWSER': '1'}):
            with self.assertRaises(AssertionError) as failed:
                browser_prerequisites(Path(empty) / 'manifest.json')
        self.assertIn('npm run build', str(failed.exception))
        with TemporaryDirectory() as empty, patch.dict(os.environ, {'MAISON_REQUIRE_BROWSER': '0'}):
            with self.assertRaises(SkipTest):
                browser_prerequisites(Path(empty) / 'manifest.json')

    def test_evidence_write_defaults_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MAISON_WRITE_EVIDENCE', None)
            self.assertIs(write_evidence_enabled(), False)
        with patch.dict(os.environ, {'MAISON_WRITE_EVIDENCE': '1'}):
            self.assertIs(write_evidence_enabled(), True)
