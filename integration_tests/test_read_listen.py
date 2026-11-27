"""Browser acceptance for the Read/Listen plan (Task 13): one real journey plus the checks earlier tasks carried here.

Journey: title page -> Read (signed-out preview) -> preview ending -> sign in -> back at the boundary anchor ->
Listen at the same place -> Back 15 / Forward 30 -> sleep timer "End of part" -> Follow in text highlight.
Carried checks: the <mark> fallback with CSS.highlights removed (across an annotation, cleared on stop), CR/CRLF
paragraph text against sentence offsets, the four reader themes (header seam), the 360 px toolbar, the Reading
comfort sheet at 375/1280 px with keyboard only, and axe on the reader (all four themes) and the player.

Fixtures are original, synthetic and local-only: an English two-part edition written for this test, never
published or used for launch content. The narration is a sine tone generated with ffmpeg at test time
(64 kbps mono MP3, the exact measured duration the timing map claims); the sentence-precision TimingMap is built
from ``library.sentences.split_sentences`` (the shared rule) at 3 s per sentence, the shape
``library.test_media_providers.ServingRenditionsTests.sentence_map`` uses. Nothing calls a paid service.

Run: ``npm run build && MAISON_ENV=test MAISON_REQUIRE_BROWSER=1 MAISON_TEST_DB_NAME=maison_test_rl13
python manage.py test integration_tests.test_read_listen``. Screenshots (deviceScaleFactor 1) go to
``MAISON_SCREENSHOT_DIR`` when it is set, never into the repository.
With ``MAISON_REQUIRE_BROWSER=1`` a missing playwright, client bundle, axe-core or ffmpeg fails instead of skipping.
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import SkipTest
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone

from integration_tests.test_film_playback import browser_prerequisites
from library import storage
from library.models import Asset, Edition, Paragraph, Revision, Rights, TimingMap, Unit, Work
from library.sentences import split_sentences
from library.services import asset_path, digest, paragraph_dto, revision_hash, write_reader_package

PASSWORD = 'Synthetic-ReadListen-Passphrase-47'
SENTENCE_MS = 3000
AXE = Path(settings.BASE_DIR) / 'node_modules/axe-core/axe.min.js'
SHOTS = os.getenv('MAISON_SCREENSHOT_DIR', '')
FEATURES = {**settings.FEATURES, 'audio': True}
TITLE = 'The River Bend'
# Original text written for this test. Part one paragraph 3 holds a CRLF and paragraph 4 a lone CR (carried item 2).
PART_ONE = [
    ('heading', 'The first bend'),
    ('paragraph', 'The river bends twice before the mill. Herons wait in the reeds. A boat drifts past the old stone bridge.'),
    ('paragraph', 'Morning fog lifts slowly.\r\nThe miller opens the gate. Water rushes under the wheel.'),
    ('paragraph', 'Children race along the bank.\rTheir shouts carry far. Nobody minds the noise.'),
    ('heading', 'Noon'),
    ('paragraph', 'By noon the light turns gold. The heron finally takes flight. The day settles into quiet.'),
    ('paragraph', 'Evening brings the lamps. A fisherman counts his catch. The river keeps its own time.'),
]
PART_TWO = [
    ('paragraph', 'Night falls over the water. Owls call from the alders. The mill wheel rests.'),
    ('paragraph', 'Dawn returns the fog. The herons come back. The river bends again.'),
]
THEMES = [('light', 'Light'), ('sepia', 'Sepia'), ('dark', 'Dark'), ('true_black', 'True Black')]
AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

FOLLOW = """() => {
  const read = (el) => el ? {anchor: el.closest('[data-anchor]') && el.closest('[data-anchor]').dataset.anchor} : {};
  const reg = window.CSS && CSS.highlights;
  for (const name of ['follow-sentence', 'follow-paragraph']) {
    const h = reg && reg.get(name);
    if (h && h.size) { const r = [...h][0];
      const el = r.startContainer.nodeType === 3 ? r.startContainer.parentElement : r.startContainer;
      return {kind: name, via: 'highlight', text: r.toString(), ...read(el)}; }
    const marks = [...document.querySelectorAll('mark.' + name)];
    if (marks.length) return {kind: name, via: 'mark', marks: marks.length, text: marks.map(m => m.textContent).join(''), ...read(marks[0])};
  }
  return null; }"""
RECT = """(sel) => { const el = document.querySelector(sel); if (!el) return null; const r = el.getBoundingClientRect();
  return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height}; }"""
FOLLOW_RECT = """() => { const reg = window.CSS && CSS.highlights; const h = reg && (reg.get('follow-sentence') || reg.get('follow-paragraph'));
  let r = h && h.size ? [...h][0].getBoundingClientRect() : null;
  if (!r) { const m = document.querySelector('mark.follow-sentence, mark.follow-paragraph'); r = m && m.getBoundingClientRect(); }
  const player = document.querySelector('#persistent-media [data-persistent-player]');
  const bar = document.querySelector('.reader-toolbar');
  return r ? {top: Math.round(r.top), bottom: Math.round(r.bottom), vh: innerHeight, playerTop: player ? Math.round(player.getBoundingClientRect().top) : null,
              toolbarBottom: bar && !bar.classList.contains('is-hidden') ? Math.round(bar.getBoundingClientRect().bottom) : 0} : null; }"""


def tool_prerequisites():
    """axe-core (npm ci) and ffmpeg (CI installs it) are needed as well; same skip/fail rule as playwright."""
    required = os.getenv('MAISON_REQUIRE_BROWSER') == '1'
    for ok, reason in ((AXE.exists(), 'axe-core is required for the accessibility pass: npm ci'),
                       (bool(shutil.which('ffmpeg')), 'ffmpeg is required to generate the synthetic narration')):
        if not ok:
            if required:
                raise AssertionError(f'MAISON_REQUIRE_BROWSER=1: {reason}')
            raise SkipTest(reason)


def tone(path, seconds):
    """A bitexact 64 kbps mono MP3 sine of exactly `seconds` (synthetic narration, never real speech)."""
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                    f'sine=frequency=330:sample_rate=22050:duration={seconds}', '-ac', '1', '-c:a', 'libmp3lame',
                    '-b:a', '64k', '-map_metadata', '-1', '-fflags', '+bitexact', '-flags:a', '+bitexact', str(path)],
                   check=True)
    return path.read_bytes()


def contrast(a, b):
    """WCAG contrast ratio of two computed 'rgb(r, g, b)' colours."""
    def luminance(value):
        channels = [int(x) / 255 for x in value[value.index('(') + 1:value.index(')')].split(',')[:3]]
        r, g, bl = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return round((high + 0.05) / (low + 0.05), 2)


def dom_text(text):
    """What an HTML parser leaves in the text node: CRLF and lone CR become LF."""
    return text.replace('\r\n', '\n').replace('\r', '\n')


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=True, FREE_ACCESS_ENABLED=False, FEATURES=FEATURES,
                   FEATURE_FLAGS=FEATURES, MEDIA_STORAGE_BACKEND='local')
class ReadListenBrowserTests(StaticLiveServerTestCase):
    host = '127.0.0.1'

    @classmethod
    def setUpClass(cls):
        sync_playwright = browser_prerequisites()
        tool_prerequisites()
        super().setUpClass()  # Django registers the live server thread's termination as a class cleanup
        cls.async_unsafe = os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE')
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
        # Each acquisition registers its own release, so a failure later in setUpClass (ffmpeg, browser launch)
        # still stops the live server, removes the audio directory and restores the environment.
        cls.addClassCleanup(cls.restore_async_unsafe)
        cls.audio_dir = TemporaryDirectory(prefix='maison-read-listen-audio-')
        cls.addClassCleanup(cls.audio_dir.cleanup)
        cls.tones = {}
        for count in (sum(len(split_sentences(text)) for _, text in PART_ONE), sum(len(split_sentences(text)) for _, text in PART_TWO)):
            cls.tones[count] = tone(Path(cls.audio_dir.name) / f'tone-{count}.mp3', count * SENTENCE_MS / 1000)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception:
            cls.browser = cls.playwright.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()  # the browser, audio files and environment are class cleanups (they run even when setUpClass fails)

    @classmethod
    def restore_async_unsafe(cls):
        if cls.async_unsafe is None:
            os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)
        else:
            os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = cls.async_unsafe

    # ---------------------------------------------------------------- fixture
    def setUp(self):
        directory = TemporaryDirectory(prefix='maison-read-listen-')
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=Path(directory.name) / 'media', PUBLIC_BASE_URL=self.live_server_url)
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('read-listen@example.test', PASSWORD, is_verified=True)
        key = uuid.uuid4().hex[:10]
        work = Work.objects.create(slug='read-listen-acceptance-' + key, title=TITLE, creators=['Maison acceptance fixture'])
        self.edition = Edition.objects.create(work=work, slug=work.slug, locale='en')
        self.revision = Revision.objects.create(edition=self.edition, title=TITLE, description='An original two-part test edition about a river.',
                                                access_policy={'reader': 'free', 'audio': 'free', 'video': 'deny'},
                                                download_policy={'reader': False, 'audio': False, 'video': False})
        self.parts, self.segments = [], {}
        evidence = {}
        for ordinal, rows in enumerate((PART_ONE, PART_TWO), 1):
            unit = Unit.objects.create(revision=self.revision, ordinal=ordinal, title=f'Part {"One" if ordinal == 1 else "Two"}')
            paragraphs = [Paragraph.objects.create(unit=unit, ordinal=i, kind=kind, text=text) for i, (kind, text) in enumerate(rows, 1)]
            segments, at = [], 0
            for p in paragraphs:
                for index, (start, end) in enumerate(split_sentences(p.text)):
                    segments.append({'anchor_id': str(p.anchor_id), 'sentence_index': index, 'start_offset_chars': start,
                                     'end_offset_chars': end, 'start_ms': at, 'end_ms': at + SENTENCE_MS})
                    at += SENTENCE_MS
            unit.duration_ms = at
            unit.save()
            raw = self.tones[len(segments)]
            asset = Asset.objects.create(revision=self.revision, unit=unit, kind='audio_chapter', state='ready', provider='r2',
                                         storage_key=f'revisions/{self.revision.id}/{uuid.uuid4()}.mp3', sha256=hashlib.sha256(raw).hexdigest(),
                                         bytes=len(raw), content_type='audio/mpeg', duration_ms=at)
            storage.put_private(asset.storage_key, raw, 'audio/mpeg')
            evidence[str(asset.id)] = {'sha256': asset.sha256, 'unit_id': str(unit.id), 'duration_ms': at, 'quality_kbps': 64,
                                       'prepared': True, 'measurement_evidence': 'synthetic sine tone for browser acceptance only'}
            self.parts.append({'unit': unit, 'paragraphs': paragraphs, 'asset': asset})
            self.segments[str(unit.id)] = segments
            write_reader_package(unit)
        self.revision.preview = [paragraph_dto(p) for p in self.parts[0]['paragraphs'][:2]]
        cover = (Path(settings.BASE_DIR) / 'static/maison/logo.png').read_bytes()  # any ready image; served unaltered
        cover_key = f'revisions/{self.revision.id}/{uuid.uuid4()}.png'
        path = asset_path(cover_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(cover)
        Asset.objects.create(revision=self.revision, kind='cover', state='ready', storage_key=cover_key, sha256=digest(cover),
                             bytes=len(cover), content_type='image/png')
        now = timezone.now()
        for fmt, actions in (('reader', ('read', 'preview')), ('audio', ('read',))):
            for action in actions:
                Rights.objects.create(revision=self.revision, format=fmt, action=action, territories=['IN'], starts_at=now - timedelta(days=1),
                                      ends_at=now + timedelta(days=30), approved=True, test_only=True, evidence='synthetic browser acceptance')
        self.revision.content_sha256 = revision_hash(self.revision)
        self.revision.validation_evidence = {'media_assets': evidence}
        self.revision.save()
        for part in self.parts:
            TimingMap.objects.create(revision=self.revision, asset=part['asset'], text_sha256=self.revision.content_sha256,
                                     asset_sha256=part['asset'].sha256, measured=True, precision='sentence',
                                     segments=self.segments[str(part['unit'].id)],
                                     chapters=[{'title': 'The first bend', 'start_ms': 0}, {'title': 'Noon', 'start_ms': 30000}] if part is self.parts[0] else [])
        self.revision.state = 'live'
        self.revision.published_at = now
        self.revision.save()
        self.edition.live_revision = self.revision
        self.edition.save()
        self.unit1 = self.parts[0]['unit']
        self.p = self.parts[0]['paragraphs']

    # ---------------------------------------------------------------- helpers
    def context(self, width=1280, height=900, init=None, **extra):
        context = self.browser.new_context(base_url=self.live_server_url, viewport={'width': width, 'height': height},
                                           device_scale_factor=1, **extra)
        self.addCleanup(context.close)
        if init:
            context.add_init_script(init)
        blocked = []
        context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).hostname == '127.0.0.1'
                      else (blocked.append(route.request.url), route.abort()))
        self.addCleanup(lambda: self.assertEqual(blocked, [], 'the browser must only reach the loopback server'))
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda message: page.errors.append(message.text) if message.type == 'error' else None)
        return page

    def sign_in(self, page):
        page.goto('/en/')
        status = page.evaluate("""async ([email, password]) => {
            const s = await (await fetch('/api/v1/session', {cache: 'no-store'})).json();
            const r = await fetch('/api/v1/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': s.csrf_token},
              body: JSON.stringify({email, password, password_purpose_consent: true, password_purpose_version: 'password-account-v1'})});
            return r.status; }""", [self.user.email, PASSWORD])
        self.assertEqual(status, 200)

    def api(self, page, method, path, body=None):
        return page.evaluate("""async ([method, path, body]) => {
            const s = await (await fetch('/api/v1/session', {cache: 'no-store'})).json();
            const headers = {'X-CSRFToken': s.csrf_token, 'Idempotency-Key': crypto.randomUUID()};
            if (body) headers['Content-Type'] = 'application/json';
            const r = await fetch('/api/v1' + path, {method, headers, body: body ? JSON.stringify(body) : undefined});
            return {status: r.status, json: await r.json().catch(() => null)}; }""", [method, path, body])

    def wait(self, page, predicate, timeout=15, message='', arg=None):
        deadline = time.monotonic() + timeout
        value = None
        while time.monotonic() < deadline:
            value = page.evaluate(predicate, arg) if arg is not None else page.evaluate(predicate)
            if value:
                return value
            page.wait_for_timeout(100)
        self.fail(f'{message} (last: {value!r}; errors: {page.errors})')

    def shot(self, page, name, full_page=False):
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(SHOTS) / f'{name}.png'), full_page=full_page)

    def axe(self, page, label):
        """Every axe violation (all impacts), printed and returned; rules axe could not decide are printed as incomplete."""
        if not page.evaluate('() => !!window.axe'):
            page.evaluate(AXE.read_text() + '\n;void 0')  # evaluated by the driver: the page's CSP forbids injected script tags
        found = page.evaluate("""async (tags) => { const r = await axe.run(document, {runOnly: {type: 'tag', values: tags}});
            return {violations: r.violations.map(v => ({id: v.id, impact: v.impact, count: v.nodes.length, target: v.nodes[0] && v.nodes[0].target.join(' '),
                                                       summary: v.nodes[0] && (v.nodes[0].failureSummary || '').split('\\n').slice(0, 2).join(' ')})),
                    incomplete: r.incomplete.map(v => `${v.id}(${v.nodes.length})`)}; }""", AXE_TAGS)
        result = found['violations']
        print(f'\nAXE {label}: ' + (json.dumps(result, ensure_ascii=False) if result else 'no violations')
              + f'; incomplete: {", ".join(found["incomplete"]) or "none"}')
        return result

    def expected_sentence(self, unit, ms):
        segment = next(s for s in self.segments[str(unit.id)] if s['start_ms'] <= ms < s['end_ms'])
        paragraph = Paragraph.objects.get(anchor_id=segment['anchor_id'])
        return segment, dom_text(paragraph.text[segment['start_offset_chars']:segment['end_offset_chars']])

    def player_audio_at(self, page, seconds):
        page.evaluate("(t) => { const a = document.querySelector('#persistent-media audio, audio'); a.muted = true; a.currentTime = t; }", seconds)

    def open_player(self, page, position_ms=0, unit=None):
        unit = unit or self.unit1
        page.goto(f'/en/listen/{self.edition.pk}/?unit_id={unit.pk}&position_ms={position_ms}')
        self.wait(page, "() => { const a = document.querySelector('audio'); return a && a.readyState >= 1 && a.src; }", message='player must load its granted audio')

    def open_reader_following(self, page, seconds):
        """Player at `seconds`, then its Follow in text link (the player persists across the client navigation)."""
        self.open_player(page)
        self.player_audio_at(page, seconds)
        link = page.get_by_role('link', name='Follow in text')
        link.wait_for(timeout=10000)
        link.click()
        page.wait_for_url(f'**/read/{self.edition.pk}/{self.unit1.pk}/**')
        self.wait(page, "() => !!document.querySelector('#reading-text') && !!document.querySelector('#persistent-media audio')",
                  message='the reader must open with the player still mounted')
        self.player_audio_at(page, seconds)

    # ---------------------------------------------------------------- the journey
    def test_title_read_preview_sign_in_listen_skip_sleep_follow(self):
        page = self.context()
        title_url = f'/en/titles/{self.edition.pk}/'
        page.goto(title_url)
        # Carried 6: format row "Read · Listen · Film" with separators and Coming soon; Read first among the actions.
        row = page.evaluate("""() => { const row = document.querySelector('.format-row');
            return {text: row.innerText.replace(/\\s+/g, ' ').trim(), seps: [...row.querySelectorAll('.format-sep')].map(s => [s.textContent, s.getAttribute('aria-hidden')]),
                    soon: [...row.querySelectorAll('.format-row-soon')].map(s => [s.textContent.trim(), !!s.closest('a')]),
                    links: [...row.querySelectorAll('a')].map(a => a.textContent.trim())}; }""")
        self.assertEqual(row['seps'], [['·', 'true'], ['·', 'true']], row)
        self.assertRegex(row['text'], r'^Read · Listen · Film Coming soon$', row)
        self.assertEqual(row['soon'], [['Film Coming soon', False]], row)
        actions = page.evaluate("() => [...document.querySelectorAll('.actions')[0].querySelectorAll('a.button, button')].map(e => e.textContent.trim())")
        self.assertTrue(actions[0].startswith('Read'), f'Read (the preview) must be the first action in DOM order: {actions}')
        self.shot(page, 'journey-01-title-1280')

        # Read -> the signed-out preview, then its ending.
        page.locator('.actions a.button').first.click()
        page.wait_for_url(f'**/read/{self.edition.pk}/{self.unit1.pk}/**')
        ending = page.locator('.preview-boundary .preview-ending-copy, .preview-boundary p:has-text("your place is kept")').first
        ending.wait_for(timeout=10000)
        ending.scroll_into_view_if_needed()
        copy = page.evaluate("""() => { const p = [...document.querySelectorAll('.preview-boundary p')].find(e => e.textContent.includes('your place is kept'));
            const span = p && p.querySelector('span[lang]'); return p && {text: p.textContent, lang: span && span.lang, title: span && span.textContent}; }""")
        self.assertEqual(copy['text'], f'Sign in free to finish {TITLE} — your place is kept', copy)
        self.assertEqual((copy['lang'], copy['title']), ('en', TITLE), copy)
        self.assertNotIn(self.p[2].text[:20], page.content(), 'the preview must stop at its boundary')
        visible_sign_in = page.evaluate("""() => [...document.querySelectorAll('a')].filter(a => a.textContent.trim() === 'Sign in free' && a.offsetParent !== null)
            .map(a => a.getAttribute('href'))""")
        self.shot(page, 'journey-02-preview-end-1280')
        page.wait_for_timeout(1000)
        self.shot(page, 'journey-02b-preview-end-settled-1280')
        buttons = page.evaluate("""() => { const paper = getComputedStyle(document.getElementById('reader')).backgroundColor;
            return [...document.querySelectorAll('.preview-boundary a.button')].filter(a => a.offsetParent).map(a => { const c = getComputedStyle(a);
              return {text: a.textContent, color: c.color, background: c.backgroundColor === 'rgba(0, 0, 0, 0)' ? paper : c.backgroundColor}; }); }""")
        print('\nPREVIEW BUTTONS ' + json.dumps(buttons))
        for button in buttons:
            with self.subTest('BUG frontend static CSS: preview-ending button text contrast on the reader paper', button=button['text']):
                # axe reports this as "incomplete" (textured paper background), so it is measured against the paper colour.
                self.assertGreaterEqual(contrast(button['color'], button['background']), 4.5, button)
        preview_axe = self.axe(page, 'reader preview ending (signed out) 1280px')
        with self.subTest('BUG frontend: serious/critical axe violations at the preview ending'):
            self.assertEqual([v['id'] for v in preview_axe if v['impact'] in ('serious', 'critical')], [], preview_axe)
        minutes = page.evaluate("() => [...document.querySelectorAll('.preview-boundary p')].map(p => p.textContent).find(t => t.includes('left to read'))")
        self.assertIsNotNone(minutes, 'Task 10: the preview ending shows the minutes left')
        self.assertRegex(minutes, r'^1 ', f'the fixture leaves about one minute to read: {minutes!r}')
        with self.subTest('BUG frontend web/i18n.py + media-sheets.tsx: "1 minutes left to read" (English singular rule)'):
            self.assertNotIn('1 minutes', minutes, f'one minute must not be pluralised: {minutes!r}')
        self.assertEqual(len(visible_sign_in), 1, f'exactly one visible "Sign in free" path at the preview end: {visible_sign_in}')
        boundary = self.p[1]
        return_to = parse_qs(urlsplit(visible_sign_in[0]).query)['return_to'][0]
        self.assertEqual(return_to, f'/en/read/{self.edition.pk}/{self.unit1.pk}/?anchor={boundary.anchor_id}&offset={len(boundary.text)}')

        # Sign in through the real form; it returns to the boundary anchor with the whole text.
        page.locator('.preview-boundary a', has_text='Sign in free').first.click()
        page.wait_for_url('**/sign-in/**')
        page.fill('#auth-email', self.user.email)
        page.fill('#auth-password', PASSWORD)
        for box in page.locator('form:has(#auth-password) input[type=checkbox]').all():
            box.check()
        page.locator('form:has(#auth-password) button[type=submit], form:has(#auth-password) button:not([type])').first.click()
        page.wait_for_url(f'**/read/{self.edition.pk}/{self.unit1.pk}/?anchor={boundary.anchor_id}&offset={len(boundary.text)}')
        self.wait(page, "() => document.body.textContent.includes('Water rushes under the wheel')", message='the signed-in reader shows the whole part')
        landed = self.wait(page, """(anchor) => { const el = document.getElementById('anchor-' + anchor); const r = el.getBoundingClientRect();
            return r.bottom > 0 && r.top < innerHeight && {top: Math.round(r.top), bottom: Math.round(r.bottom), scrollY: Math.round(scrollY)}; }""",
                           arg=str(boundary.anchor_id), message='sign-in must return to the boundary anchor in view')
        self.shot(page, 'journey-03-returned-to-anchor-1280')

        # Listen at the same place: the toolbar switch carries the reader position through /content/switch-position.
        expected = next(s for s in reversed(self.segments[str(self.unit1.pk)]) if s['anchor_id'] == str(boundary.anchor_id))
        switch_bodies = []
        page.on('request', lambda r: switch_bodies.append(r.post_data) if r.url.endswith('/content/switch-position') else None)
        page.locator('[data-format-switch="listen"]').click()
        page.wait_for_url(f'**/listen/{self.edition.pk}/**')
        query = parse_qs(urlsplit(page.url).query)
        self.assertEqual(query.get('unit_id'), [str(self.unit1.pk)], page.url)
        opened_ms = int(query['position_ms'][0])
        paragraph_start = next(s for s in self.segments[str(self.unit1.pk)] if s['anchor_id'] == str(boundary.anchor_id))['start_ms']
        self.assertIn(opened_ms, (paragraph_start, expected['start_ms']), f'Listen must open inside the boundary paragraph: {page.url}')
        with self.subTest('BUG frontend client/reader.tsx: restored offset lost before the Listen switch'):
            # The sign-in return lands on ?anchor=<boundary>&offset=<end>. jump() sets that exact position, but the
            # IntersectionObserver created just before it (reader.tsx ~:455-466) reports its first entries afterwards
            # and resets position.current to {anchor, offset_chars: 0}; the switch then starts the paragraph again.
            self.assertEqual(opened_ms, expected['start_ms'],
                             f'Listen must open at the boundary sentence ({expected["start_ms"]} ms), not the paragraph start '
                             f'({paragraph_start} ms): {page.url}; anchor in view {landed}; switch request {switch_bodies}')
        start = self.wait(page, "() => { const a = document.querySelector('audio'); return a && a.readyState >= 1 && a.currentTime > 0 && a.currentTime; }",
                          message='the player must start at the switched position')
        self.assertAlmostEqual(start, opened_ms / 1000, delta=0.25)

        # Back 15 subtracts 15 s and Forward 30 adds 30 s (paused, so time does not drift); Back 15 clamps at 0.
        def seek(t):
            page.evaluate("(t) => { const a = document.querySelector('audio'); a.pause(); a.currentTime = t; }", t)
            self.wait(page, f"() => Math.abs(document.querySelector('audio').currentTime - {t}) < 0.05", message=f'seek to {t} s')
        def skip(button, expected):
            page.get_by_role('button', name=button).click()
            got = self.wait(page, f"() => {{ const t = document.querySelector('audio').currentTime; return Math.abs(t - {expected}) < 0.3 && {{t}}; }}",
                            message=f'{button} must land at {expected} s')
            self.assertAlmostEqual(got['t'], expected, delta=0.3)
        seek(40.0)
        skip('Back 15 seconds', 25.0)
        seek(10.0)
        skip('Forward 30 seconds', 40.0)
        seek(9.0)
        skip('Back 15 seconds', 0.0)
        self.shot(page, 'journey-04-player-1280', full_page=True)

        # Sleep timer "End of part": part one ends and playback stops instead of moving to part two.
        page.get_by_label('Sleep timer').select_option(label='End of part')
        duration = self.unit1.duration_ms / 1000
        page.evaluate("(t) => { const a = document.querySelector('audio'); a.muted = true; a.currentTime = t; return a.play(); }", duration - 1.5)
        self.wait(page, "() => document.body.innerText.includes('The sleep timer paused playback.')", timeout=20,
                  message='End of part must stop at the end of part one')
        state = page.evaluate("() => { const a = document.querySelector('audio'); return {paused: a.paused, current: document.querySelector('.parts-list > li > button[aria-current]').textContent}; }")
        self.assertTrue(state['paused'], state)
        self.assertEqual(state['current'], 'Part One', state)

        # Follow in text: the reader highlights the sentence being narrated.
        self.player_audio_at(page, 31.0)
        page.get_by_role('link', name='Follow in text').click()
        page.wait_for_url(f'**/read/{self.edition.pk}/{self.unit1.pk}/**')
        self.player_audio_at(page, 31.0)
        segment, sentence = self.expected_sentence(self.unit1, 31000)
        follow = self.wait(page, FOLLOW, message='the reader must highlight the narrated sentence')
        self.assertEqual((follow['kind'], follow['anchor'], follow['text']), ('follow-sentence', segment['anchor_id'], sentence), follow)
        self.shot(page, 'journey-05-follow-along-1280')
        self.assertEqual([e for e in page.errors if 'favicon' not in e], [], 'no page errors on the journey')

    # ---------------------------------------------------------------- carried 1 and 2
    def follow_checks(self, page, via):
        # Paragraph 3 holds a CRLF, paragraph 4 a lone CR: each second sentence must be highlighted exactly.
        results = {}
        for name, paragraph in (('crlf', self.p[2]), ('cr', self.p[3])):
            segment = next(s for s in self.segments[str(self.unit1.pk)] if s['anchor_id'] == str(paragraph.anchor_id) and s['sentence_index'] == 1)
            self.player_audio_at(page, segment['start_ms'] / 1000 + 0.5)
            expected = dom_text(paragraph.text[segment['start_offset_chars']:segment['end_offset_chars']])
            got = self.wait(page, f"() => {{ const f = ({FOLLOW})(); return f && f.anchor === '{segment['anchor_id']}' && f; }}",
                            message=f'{name}: the follow highlight must reach paragraph {paragraph.ordinal}')
            self.assertEqual(got['via'], via, got)
            results[name] = (got['text'], expected)
            self.shot(page, f'follow-{via}-{name}-1280')
        return results

    def assert_follow_results(self, results):
        got, expected = results['cr']
        self.assertEqual(got, expected, 'lone CR: highlighted text must be the narrated sentence')
        got, expected = results['crlf']
        with self.subTest('BUG frontend client/sentences.ts highlightSpan / follow-dom.ts: CRLF shifts sentence offsets'):
            # Server offsets count CR and LF (library/sentences.py on the stored text); the HTML parser turns CRLF
            # into one LF, so every sentence after a CRLF is drawn one character late ('he miller ... W').
            self.assertEqual(got, expected, 'CRLF: highlighted text must be the narrated sentence')

    def test_follow_along_highlight_api_and_cr_crlf_offsets(self):
        page = self.context()
        self.sign_in(page)
        self.open_reader_following(page, 1.0)
        results = self.follow_checks(page, 'highlight')
        self.assert_follow_results(results)

    def test_follow_along_mark_fallback_across_annotation_cleared_on_stop(self):
        page = self.context(init='try { delete CSS.highlights; Object.defineProperty(CSS, "highlights", {value: undefined}); } catch (e) {}')
        self.sign_in(page)
        # An annotation across the boundary of the first and second sentence of paragraph 6.
        p6 = self.p[5]
        first, second = split_sentences(p6.text)[:2]
        note = {'annotation_id': str(uuid.uuid4()), 'edition_revision_id': str(self.revision.pk), 'kind': 'note',
                'range': {'unit_id': str(self.unit1.pk), 'start_anchor_id': str(p6.anchor_id), 'start_offset_chars': first[1] - 6,
                          'end_anchor_id': str(p6.anchor_id), 'end_offset_chars': second[0] + 8, 'offset_unit': 'unicode_code_point'}, 'color': 'gold',
                'note_text': 'Synthetic acceptance note'}
        created = self.api(page, 'POST', '/me/annotations', note)
        self.assertEqual(created['status'], 201, created)
        self.open_reader_following(page, 1.0)
        self.assertIsNone(page.evaluate('() => window.CSS && CSS.highlights'), 'the init script must remove CSS.highlights')
        before = page.evaluate("(a) => document.getElementById('anchor-' + a).textContent", str(p6.anchor_id))
        self.assertEqual(before, p6.text)
        annotation_text = p6.text[first[1] - 6:second[0] + 8]
        self.wait(page, "(a) => [...document.getElementById('anchor-' + a).querySelectorAll('mark')].some(m => !m.className.includes('follow'))",
                  arg=str(p6.anchor_id), message='the annotation mark must render')
        segment = next(s for s in self.segments[str(self.unit1.pk)] if s['anchor_id'] == str(p6.anchor_id) and s['sentence_index'] == 1)
        self.player_audio_at(page, segment['start_ms'] / 1000 + 0.5)
        got = self.wait(page, f"() => {{ const f = ({FOLLOW})(); return f && f.anchor === '{p6.anchor_id}' && f; }}",
                        message='the <mark> fallback must highlight paragraph 6')
        self.shot(page, 'follow-mark-across-annotation-1280')
        self.assertEqual(got['via'], 'mark', got)
        self.assertEqual(got['text'], p6.text[segment['start_offset_chars']:segment['end_offset_chars']], got)
        self.assertGreaterEqual(got['marks'], 2, f'the sentence starts inside the annotation, so it needs two pieces: {got}')
        during = page.evaluate("""(a) => { const p = document.getElementById('anchor-' + a);
            return {text: p.textContent, notes: [...p.querySelectorAll('mark:not(.follow-sentence):not(.follow-paragraph)')].map(m => m.textContent).join('')}; }""",
                               str(p6.anchor_id))
        self.assertEqual(during, {'text': p6.text, 'notes': annotation_text}, 'the fallback must not change the text or the annotation')
        # Mark fallback on the CR/CRLF paragraphs too.
        results = self.follow_checks(page, 'mark')
        # Stop: closing the player clears every follow mark and leaves the text as it was.
        page.get_by_role('button', name='Close player').click()
        self.wait(page, "() => !document.querySelector('mark.follow-sentence, mark.follow-paragraph')", message='stopping must clear the highlight')
        after = page.evaluate("""(a) => { const p = document.getElementById('anchor-' + a);
            return {text: p.textContent, notes: [...p.querySelectorAll('mark')].map(m => m.textContent).join('')}; }""", str(p6.anchor_id))
        self.assertEqual(after, {'text': p6.text, 'notes': annotation_text})
        self.assert_follow_results(results)

    # ---------------------------------------------------------------- carried 3 and the reader axe pass
    def choose_theme(self, page, label):
        page.locator('#reader-settings-trigger').click()
        sheet = page.locator('dialog.media-sheet[open]')
        sheet.wait_for()
        sheet.get_by_role('radio', name=label).click()
        sheet.get_by_role('button', name='Close').click()
        page.wait_for_timeout(250)

    def test_reader_themes_header_seam_and_axe(self):
        violations, seams = {}, {}
        for width, height in ((1280, 900), (360, 780)):
            page = self.context(width, height)
            self.sign_in(page)
            page.goto(f'/en/read/{self.edition.pk}/{self.unit1.pk}/')
            page.wait_for_selector('#reader-settings-trigger')
            self.wait(page, "() => !document.querySelector('#reader-controls p[role=status]') || !document.querySelector('#reader-controls p[role=status]').textContent.includes('Loading')",
                      message='reader must hydrate')
            for theme, label in THEMES:
                self.choose_theme(page, label)
                self.wait(page, f"() => document.body.classList.contains('reader-theme-{theme}')", message=f'{theme} must reach the body')
                seams[(theme, width)] = page.evaluate("""() => { const bg = (el) => el && getComputedStyle(el).backgroundColor;
                    const header = document.querySelector('.reader-toolbar') || document.querySelector('header');
                    return {header: bg(header), body: bg(document.body), reader: bg(document.getElementById('reader')),
                            main: bg(document.querySelector('main')), border: header && getComputedStyle(header).borderBottomColor}; }""")
                self.shot(page, f'reader-{theme}-{width}')
                if width == 1280:
                    violations[theme] = self.axe(page, f'reader {theme} {width}px')
        print('\nTHEME COLOURS ' + json.dumps({f'{k[0]}@{k[1]}': v for k, v in seams.items()}))
        blocking = {theme: [v['id'] for v in found if v['impact'] in ('serious', 'critical')] for theme, found in violations.items()}
        self.assertEqual({t: v for t, v in blocking.items() if v}, {}, f'serious/critical axe violations on the reader: {violations}')

    def test_player_axe(self):
        page = self.context()
        self.sign_in(page)
        self.open_player(page, 9000)
        page.wait_for_timeout(300)
        self.shot(page, 'player-1280', full_page=True)
        found = self.axe(page, 'player 1280px')
        page.set_viewport_size({'width': 375, 'height': 800})
        self.shot(page, 'player-375', full_page=True)
        blocking = [v['id'] for v in found if v['impact'] in ('serious', 'critical')]
        self.assertEqual(blocking, [], f'serious/critical axe violations on the player: {found}')

    # ---------------------------------------------------------------- carried 4
    def test_mobile_toolbar_two_rows_hides_on_scroll_and_keyboard_pins(self):
        page = self.context(360, 640, has_touch=False)
        self.sign_in(page)
        page.goto(f'/en/read/{self.edition.pk}/{self.unit1.pk}/')
        page.wait_for_selector('.reader-toolbar .reader-tools')
        page.wait_for_timeout(400)
        layout = page.evaluate("""() => { const bar = document.querySelector('.reader-toolbar'); const tools = bar.querySelector('.reader-tools');
            const title = bar.querySelector('.room-evening-title, h1, [class*=title]'); const t = title && title.getBoundingClientRect(); const r = tools.getBoundingClientRect();
            return {scrollWidth: document.documentElement.scrollWidth, innerWidth: innerWidth, toolsTop: r.top, toolsLeft: r.left, toolsRight: r.right,
                    titleBottom: t && t.bottom, titleTop: t && t.top, barHeight: bar.getBoundingClientRect().height,
                    overflow: [...bar.querySelectorAll('a, button, [role=progressbar], .reader-minutes, .logo-plate')].filter(e => { const b = e.getBoundingClientRect(); return b.width && (b.right > innerWidth + 0.5 || b.left < -0.5); }).map(e => { const b = e.getBoundingClientRect(); return `${e.tagName}.${e.className} [${Math.round(b.left)},${Math.round(b.right)}] ${e.getAttribute('src') || ''}`; }),
                    toolsHeight: r.height,
                    // visual rows of the whole toolbar: visible controls grouped by vertical overlap
                    rows: [...bar.querySelectorAll('a, button, .reader-minutes, .logo-plate, .room-evening-title')]
                      .map(e => e.getBoundingClientRect()).filter(b => b.width && b.height).sort((a, b) => a.top - b.top)
                      .reduce((rows, b) => { const last = rows[rows.length - 1]; if (last && b.top < last.bottom - 4) { last.bottom = Math.max(last.bottom, b.bottom); } else rows.push({top: b.top, bottom: b.bottom}); return rows; }, []).length}; }""")
        self.shot(page, 'toolbar-360-top')
        print('\nTOOLBAR 360 ' + json.dumps(layout))
        self.assertLessEqual(layout['scrollWidth'], 360, f'no horizontal scroll at 360 px: {layout}')
        self.assertEqual(layout['overflow'], [], layout)
        self.assertGreaterEqual(layout['toolsTop'], layout['titleBottom'] - 1, f'tools must sit on a second row: {layout}')
        with self.subTest('BUG frontend static CSS: the 360 px toolbar wraps to three rows'):
            # Task 8 ruling "mobile two rows": row 1 Back/title/logo, row 2 the reader tools. With Task 11's
            # Read/Listen switch in the tools, flex-wrap pushes "Reading comfort" to a third row.
            self.assertEqual(layout['rows'], 2, f'the 360 px toolbar must be exactly two rows: {layout}')
        hidden = "() => document.querySelector('.reader-toolbar').classList.contains('is-hidden')"
        page.mouse.move(180, 400)
        for _ in range(4):
            page.mouse.wheel(0, 250)
            page.wait_for_timeout(120)
        self.wait(page, hidden, message='a hand scroll down must hide the toolbar')
        page.wait_for_timeout(350)
        box = page.evaluate(RECT, '.reader-toolbar')
        self.shot(page, 'toolbar-360-hidden')
        self.assertLessEqual(box['bottom'], 1, f'the hidden toolbar must be off screen: {box}')
        page.mouse.wheel(0, -200)
        self.wait(page, f"() => !({hidden})()", message='a scroll up must show the toolbar')
        self.shot(page, 'toolbar-360-shown-after-up')
        # Keyboard only: Tab into the toolbar pins it; a scroll down then leaves it shown.
        page.mouse.wheel(0, 300)
        self.wait(page, hidden, message='hidden again before the keyboard check')
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        for _ in range(30):
            page.keyboard.press('Tab')
            inside = page.evaluate("() => !!document.activeElement.closest('.reader-toolbar') && document.activeElement.matches(':focus-visible') && (document.activeElement.id || document.activeElement.textContent.trim())")
            if inside:
                break
        self.assertTrue(inside, 'Tab must reach a toolbar control')
        self.wait(page, f"() => !({hidden})()", message='keyboard focus inside the toolbar must show it')
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(400)
        self.assertFalse(page.evaluate(hidden), f'the toolbar stays pinned while keyboard focus ({inside}) is inside it')
        self.shot(page, 'toolbar-360-keyboard-pinned')

    # ---------------------------------------------------------------- carried 5
    def comfort_keyboard(self, page):
        trigger = page.locator('#reader-settings-trigger')
        trigger.focus()
        page.keyboard.press('Enter')
        page.locator('dialog.media-sheet[open]').wait_for()
        stops = []
        for _ in range(40):
            page.keyboard.press('Tab')
            where = page.evaluate("""() => { const a = document.activeElement; const g = a.closest('[role=radiogroup]');
                return {group: g ? g.getAttribute('aria-labelledby') : null, role: a.getAttribute('role'), label: (a.getAttribute('aria-label') || a.textContent).trim().slice(0, 40),
                        inDialog: !!a.closest('dialog[open]')}; }""")
            if not where['inDialog'] or (stops and where == stops[0]):
                break  # past the last control a native modal dialog hands focus to the browser, never to the page behind
            stops.append(where)
        groups = [s['group'] for s in stops if s['group']]
        self.assertEqual(len(groups), len(set(groups)), f'each radio group takes exactly one Tab stop: {stops}')
        self.assertEqual(set(groups), {'comfort-theme', 'comfort-width', 'comfort-align', 'comfort-face', 'comfort-layout'}, stops)
        # Arrow keys move the choice inside the width group.
        page.locator('[aria-labelledby=comfort-width] [aria-checked=true]').focus()
        before = page.evaluate("() => document.activeElement.textContent")
        page.keyboard.press('ArrowRight')
        moved = page.evaluate("() => ({focus: document.activeElement.textContent, checked: document.querySelector('[aria-labelledby=comfort-width] [aria-checked=true]').textContent})")
        self.assertNotEqual(moved['checked'], before, moved)
        self.assertEqual(moved['focus'], moved['checked'], moved)
        page.keyboard.press('Escape')
        self.wait(page, "() => !document.querySelector('dialog.media-sheet[open]')", message='Escape must close the sheet')
        self.assertEqual(page.evaluate("() => document.activeElement.id"), 'reader-settings-trigger', 'focus returns to the trigger')

    def test_reading_comfort_sheet_layout_keyboard_and_follow_recentres(self):
        geometry = {}
        for width, height, name in ((375, 812, 'bottom'), (1280, 900, 'centred')):
            page = self.context(width, height)
            self.sign_in(page)
            page.goto(f'/en/read/{self.edition.pk}/{self.unit1.pk}/')
            page.wait_for_selector('#reader-settings-trigger')
            page.wait_for_timeout(400)
            page.locator('#reader-settings-trigger').click()
            page.locator('dialog.media-sheet[open]').wait_for()
            page.wait_for_timeout(300)
            box = page.evaluate(RECT, 'dialog.media-sheet[open]')
            geometry[width] = box
            self.shot(page, f'comfort-sheet-{width}')
            page.keyboard.press('Escape')
            if name == 'bottom':
                self.assertAlmostEqual(box['bottom'], height, delta=2, msg=f'375 px: the sheet sits on the bottom edge: {box}')
                self.assertGreaterEqual(box['width'], width - 2, f'375 px: full-width bottom sheet: {box}')
            else:
                self.assertAlmostEqual(box['left'], width - box['right'], delta=2, msg=f'1280 px: horizontally centred: {box}')
                self.assertLess(box['width'], width * 0.8, box)
            self.comfort_keyboard(page)
        print('\nCOMFORT SHEET ' + json.dumps(geometry))

        # The follow-along highlight stays visible and re-centres while size, width and line spacing change.
        page = self.context(1280, 900)
        self.sign_in(page)
        self.open_reader_following(page, 40.0)  # paragraph 6, near the end of the part
        page.evaluate("() => document.querySelector('#persistent-media audio').play()")
        self.wait(page, FOLLOW, message='follow-along must be drawn before the sheet changes')
        page.locator('#reader-settings-trigger').click()
        sheet = page.locator('dialog.media-sheet[open]')
        sheet.wait_for()
        rects = []
        for control in ('Larger text', 'Larger text', 'More line spacing'):
            sheet.get_by_role('button', name=control).click()
            page.wait_for_timeout(700)
            rects.append((control, page.evaluate(FOLLOW_RECT)))
        sheet.get_by_role('radio', name='Narrow').click()
        page.wait_for_timeout(700)
        rects.append(('Narrow', page.evaluate(FOLLOW_RECT)))
        self.shot(page, 'comfort-follow-after-changes-1280')
        page.evaluate("() => document.querySelector('#persistent-media audio').pause()")
        print('\nFOLLOW RECTS ' + json.dumps(rects))
        for control, rect in rects:
            with self.subTest(control=control):
                self.assertIsNotNone(rect, f'the highlight must survive {control}')
                self.assertTrue(rect['top'] >= 0 and rect['bottom'] <= rect['vh'], f'after {control} the highlight must stay in the viewport: {rect}')
        final = rects[-1][1]
        with self.subTest('BUG frontend client/reader.tsx: follow-along centring ignores the docked player'):
            # spec §10: the follow-along highlight must stay visible. reader.tsx (~:839) only scrolls when the sentence leaves [0, innerHeight], so the docked
            # player (or the toolbar) can cover it. Checked once, after all the setting changes.
            self.assertTrue(final['top'] >= final['toolbarBottom'] and (final['playerTop'] is None or final['bottom'] <= final['playerTop']),
                            f'spec §10: the follow-along highlight must stay visible: after all the comfort changes it must not sit under the toolbar or the docked player: {final}')

    def test_follow_along_sentence_is_not_left_under_the_docked_player(self):
        page = self.context(1280, 900)
        self.sign_in(page)
        p6 = self.p[5]
        segments = [s for s in self.segments[str(self.unit1.pk)] if s['anchor_id'] == str(p6.anchor_id)]
        self.open_reader_following(page, segments[0]['start_ms'] / 1000 + 0.2)
        self.wait(page, FOLLOW, message='follow-along must be drawn')
        # The reader scrolls by hand so paragraph 6 sits low on the screen, where the docked player is; then waits
        # out the 5 s hands-off window and lets the narration reach the paragraph's next sentence.
        player_top = page.evaluate("() => Math.round(document.querySelector('#persistent-media [data-persistent-player]').getBoundingClientRect().top)")
        page.evaluate("([a, y]) => { const el = document.getElementById('anchor-' + a); scrollBy(0, el.getBoundingClientRect().top - y); }",
                      [str(p6.anchor_id), player_top + 40])
        page.wait_for_timeout(5400)
        page.evaluate("(t) => { const a = document.querySelector('#persistent-media audio'); a.muted = true; a.currentTime = t; return a.play(); }",
                      segments[1]['start_ms'] / 1000 + 0.1)
        self.wait(page, f"() => {{ const f = ({FOLLOW})(); return f && f.text.startsWith('A fisherman'); }}", message='the next sentence must be highlighted')
        page.wait_for_timeout(500)
        rect = page.evaluate(FOLLOW_RECT)
        page.evaluate("() => document.querySelector('#persistent-media audio').pause()")
        self.shot(page, 'follow-under-docked-player-1280')
        print('\nFOLLOW UNDER PLAYER ' + json.dumps(rect))
        with self.subTest('BUG frontend client/reader.tsx: follow-along centring ignores the docked player'):
            self.assertTrue(rect['bottom'] <= rect['playerTop'],
                            f'spec §10: the follow-along highlight must stay visible; the narrated sentence must be scrolled clear of the docked player, not left under it: {rect}')
