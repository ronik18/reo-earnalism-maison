// Production member-journey regression suite (browser automation).
//
// Covers the post-deploy checks for the member journey: home and title page,
// cover revalidation (ETag/304), Reader chapter open and chapter turn, progress
// reaching Vault "Continue", save/unsave, and a learning track.
//
// Production serves the launch countries (IN, US, GB, BR, SG, MY, ID, PH, TH):
// elsewhere the edge returns 403 `service_region_unavailable`. From any other
// country only the liveness check runs; every other test is skipped with that
// reason, never reported as passed.
//
// Member tests need a dedicated, verified TEST account (never a customer
// account). It must not hold paid access. The suite never buys anything and
// cleans up its saved item.
//   MAISON_E2E_EMAIL, MAISON_E2E_PASSWORD
// Optional: MAISON_E2E_BASE_URL (default https://maison.theearnalism.com).
import { test, expect } from '@playwright/test';

const BASE = (process.env.MAISON_E2E_BASE_URL || 'https://maison.theearnalism.com').replace(/\/$/, '');
const EMAIL = process.env.MAISON_E2E_EMAIL;
const PASSWORD = process.env.MAISON_E2E_PASSWORD;
const LOCALE = 'en';

let regionBlocked = false;
let edition; // first published Reader edition in any content language

test.beforeAll(async ({ request }) => {
  // No locale filter: the published book may be Bengali while the interface is English.
  // No territory parameter: the server uses the visitor's trusted edge territory.
  const catalog = await request.get(`${BASE}/api/v1/catalog?format=reader&limit=20`);
  if (catalog.status() === 403 && (await catalog.json()).code === 'service_region_unavailable') {
    regionBlocked = true;
    return;
  }
  expect(catalog.status(), 'catalog API').toBe(200);
  edition = (await catalog.json()).items.find((card) => card.formats.includes('reader'));
});

const needsIndia = () => test.skip(regionBlocked, 'Production is not available from this network\'s country: run the suite from a launch country.');
const needsMember = () => {
  needsIndia();
  test.skip(!EMAIL || !PASSWORD, 'Set MAISON_E2E_EMAIL and MAISON_E2E_PASSWORD for the dedicated test account.');
};
// Until a book is published the live catalog is empty by design. Once one is, set
// MAISON_E2E_REQUIRE_BOOK=1 so an empty catalog fails as a regression instead of skipping.
const needsBook = () => {
  needsIndia();
  if (process.env.MAISON_E2E_REQUIRE_BOOK === '1') {
    expect(edition, 'the live catalog lists a published Reader edition in India').toBeTruthy();
  }
  test.skip(!edition, 'The live catalog has no published Reader edition in India yet.');
};

// Calls the API from inside the signed-in page, the way the Maison client does.
async function api(page, method, path, { body, key, version } = {}) {
  return page.evaluate(async ({ method, path, body, key, version }) => {
    const session = await (await fetch('/api/v1/session', { credentials: 'same-origin' })).json();
    const headers = { 'X-CSRFToken': session.csrf_token };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (key) headers['Idempotency-Key'] = key;
    if (version !== undefined) headers['If-Match'] = `"v${version}"`;
    const response = await fetch(`/api/v1${path}`, { method, headers, credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body) });
    const text = await response.text();
    return { status: response.status, json: text ? JSON.parse(text) : null };
  }, { method, path, body, key, version });
}

// Sign in ONCE per run and reuse the session: the server allows 5 sign-in attempts
// per email per 15 minutes, so signing in for every test locks the account out.
let memberState;
async function memberPage(browser) {
  if (!memberState) {
    const context = await browser.newContext();
    await signIn(await context.newPage());
    memberState = await context.storageState();
    await context.close();
  }
  const page = await (await browser.newContext({ storageState: memberState })).newPage();
  await page.goto(`${BASE}/${LOCALE}/`); // api() calls are same-origin from this page
  return page;
}

async function signIn(page) {
  await page.goto(`${BASE}/${LOCALE}/sign-in/`);
  await page.fill('#auth-email', EMAIL);
  await page.fill('#auth-password', PASSWORD);
  const consent = page.locator('input[name="password_purpose_consent"]');
  if (await consent.count()) await consent.check(); // Members agree to password processing at sign-in.
  await page.locator('form button[type="submit"]').click();
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    if ((await api(page, 'GET', '/session')).json?.authenticated) return;
    await page.waitForTimeout(500);
  }
  // Report what the member would see instead of a bare timeout.
  const shown = (await page.locator('[role="alert"], .error-notice, #auth-form-status').allInnerTexts())
    .map((text) => text.trim()).filter(Boolean).join(' | ');
  throw new Error(`Test account did not sign in. Page: ${new URL(page.url()).pathname}. Message: ${shown || '(none shown)'}`);
}

test('liveness endpoint answers', async ({ request }) => {
  const response = await request.get(`${BASE}/api/v1/health/live`);
  expect(response.status()).toBe(200);
  expect((await response.json()).status).toBe('ok');
});

test('home page renders', async ({ page }) => {
  needsIndia();
  const home = await page.goto(`${BASE}/${LOCALE}/`);
  expect(home.status()).toBe(200);
  await expect(page.locator('main')).toBeVisible();
});

test('title page renders a published edition', async ({ page }) => {
  needsBook();
  const title = await page.goto(`${BASE}/${LOCALE}/titles/${edition.edition_id}/`);
  expect(title.status()).toBe(200);
  await expect(page.locator('h1')).toContainText(edition.title);
});

test('cover revalidation returns 304 with a strong content ETag', async ({ request }) => {
  needsBook();
  test.skip(!edition.cover, 'The first edition has no cover.');
  const first = await request.get(edition.cover.url);
  expect(first.status()).toBe(200);
  test.skip(first.headers()['cache-control'].includes('private'),
    'Covers are only edge-cacheable behind the HTTPS public origin (production); nothing to revalidate here.');
  const etag = first.headers()['etag'];
  expect(etag, 'strong SHA-256 ETag').toMatch(/^"[0-9a-f]{64}"$/);
  const again = await request.get(edition.cover.url, { headers: { 'If-None-Match': etag } });
  expect(again.status()).toBe(304);
});

test('test account signs in', async ({ browser }) => {
  needsMember();
  const page = await memberPage(browser);
  const session = (await api(page, 'GET', '/session')).json;
  expect(session.member.email_verified, 'test account email is verified').toBe(true);
});

test('member opens a chapter, turns the page and resumes from Vault', async ({ browser }) => {
  needsBook();
  needsMember();
  const page = await memberPage(browser);
  const boot = async () => JSON.parse(await page.locator('#reader-bootstrap').textContent());
  const opened = await page.goto(`${BASE}/${LOCALE}/read/${edition.edition_id}/`);
  expect(opened.status()).toBe(200);
  await expect(page.locator('[data-anchor]').first(), 'chapter text renders').toBeVisible({ timeout: 20_000 });
  let reader = await boot();
  if (reader.next_unit_url) {
    const turned = await page.goto(`${BASE}${reader.next_unit_url}`);
    expect(turned.status(), 'next chapter opens').toBe(200);
    await expect(page.locator('[data-anchor]').first()).toBeVisible({ timeout: 20_000 });
    reader = await boot();
  }

  const anchor = await page.locator('[data-anchor]').first().getAttribute('data-anchor');
  const current = (await api(page, 'GET', `/me/progress/${edition.edition_id}/reader`)).json;
  const saved = await api(page, 'PUT', `/me/progress/${edition.edition_id}/reader`, {
    version: current.version,
    body: { operation_id: crypto.randomUUID(), edition_revision_id: reader.edition_revision_id,
      occurred_at: new Date().toISOString(),
      location: { format: 'reader', unit_id: reader.unit_id, anchor_id: anchor, offset_chars: 0 } },
  });
  expect(saved.status, JSON.stringify(saved.json)).toBe(200);
  expect(saved.json.fraction_complete).toBeGreaterThanOrEqual(0);
  expect(saved.json.fraction_complete).toBeLessThanOrEqual(1);

  const vault = await api(page, 'GET', '/me/vault');
  expect(vault.status).toBe(200);
  const resume = vault.json.continue.find((entry) => entry.card.edition_id === edition.edition_id);
  expect(resume, 'edition appears in Continue').toBeTruthy();
  expect(resume.progress.location.unit_id).toBe(reader.unit_id);
  expect((await page.goto(`${BASE}/${LOCALE}/vault/`)).status()).toBe(200);
});

test('member saves and unsaves a published edition', async ({ browser }) => {
  needsBook();
  needsMember();
  const page = await memberPage(browser);
  const put = await api(page, 'PUT', `/me/saved-items/${edition.edition_id}`, { key: crypto.randomUUID() });
  expect(put.status, JSON.stringify(put.json)).toBe(200);
  expect(put.json.available).toBe(true);
  const listed = await api(page, 'GET', '/me/saved-items?limit=100');
  expect(listed.json.items.find((item) => item.edition_id === edition.edition_id)?.available).toBe(true);
  const removed = await api(page, 'DELETE', `/me/saved-items/${edition.edition_id}`, { key: crypto.randomUUID() });
  expect(removed.status).toBe(204);
});

test('member opens a learning track', async ({ browser }) => {
  needsMember();
  const page = await memberPage(browser);
  const tracks = (await api(page, 'GET', `/learning/tracks`)).json;
  test.skip(!tracks.items.length, 'No published learning track in this territory.');
  const track = tracks.items[0];
  expect(['free', 'included', 'locked']).toContain(track.access);
  const response = await page.goto(`${BASE}/${LOCALE}/tracks/${track.track_id}/`);
  expect(response.status()).toBe(200);
  await expect(page.locator('h1')).toContainText(track.title);
});
