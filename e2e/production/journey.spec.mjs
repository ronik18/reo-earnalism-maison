// Production member-journey regression suite (browser automation).
//
// Covers the post-deploy checks for the member journey: home and title page,
// cover revalidation (ETag/304), Reader chapter open and chapter turn, progress
// reaching Vault "Continue", save/unsave, and a learning track.
//
// Production is India-first: the edge returns 403 `service_region_unavailable`
// outside India, so run this from an Indian network. Outside India only the
// liveness check runs; every other test is skipped with that reason, never
// reported as passed.
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
let edition; // first available catalog card from Home

test.beforeAll(async ({ request }) => {
  const home = await request.get(`${BASE}/api/v1/home?locale=${LOCALE}&territory=IN`);
  if (home.status() === 403 && (await home.json()).code === 'service_region_unavailable') {
    regionBlocked = true;
    return;
  }
  expect(home.status(), 'home API').toBe(200);
  const body = await home.json();
  edition = body.shelves.flatMap((shelf) => shelf.items).find((card) => card.formats.includes('reader'));
});

const needsIndia = () => test.skip(regionBlocked, 'Production serves India only: run this suite from an Indian network.');
const needsMember = () => {
  needsIndia();
  test.skip(!EMAIL || !PASSWORD, 'Set MAISON_E2E_EMAIL and MAISON_E2E_PASSWORD for the dedicated test account.');
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

async function signIn(page) {
  await page.goto(`${BASE}/${LOCALE}/sign-in/`);
  await page.fill('#auth-email', EMAIL);
  await page.fill('#auth-password', PASSWORD);
  const consent = page.locator('input[name="password_purpose_consent"]');
  if (await consent.count()) await consent.check(); // Members agree to password processing at sign-in.
  await page.locator('form button[type="submit"]').click();
  await expect.poll(async () => (await api(page, 'GET', '/session')).json?.authenticated,
    { message: 'test account signs in', timeout: 15_000 }).toBeTruthy();
}

test('liveness endpoint answers', async ({ request }) => {
  const response = await request.get(`${BASE}/api/v1/health/live`);
  expect(response.status()).toBe(200);
  expect((await response.json()).status).toBe('ok');
});

test('home and a title page render a published edition', async ({ page }) => {
  needsIndia();
  expect(edition, 'Home lists at least one Reader edition').toBeTruthy();
  await page.goto(`${BASE}/${LOCALE}/`);
  await expect(page.locator('body')).toContainText(edition.title);
  const title = await page.goto(`${BASE}/${LOCALE}/titles/${edition.edition_id}/`);
  expect(title.status()).toBe(200);
  await expect(page.locator('h1')).toContainText(edition.title);
});

test('cover revalidation returns 304 with a strong content ETag', async ({ request }) => {
  needsIndia();
  test.skip(!edition?.cover, 'The first edition has no cover.');
  const first = await request.get(edition.cover.url);
  expect(first.status()).toBe(200);
  test.skip(first.headers()['cache-control'].includes('private'),
    'Covers are only edge-cacheable behind the HTTPS public origin (production); nothing to revalidate here.');
  const etag = first.headers()['etag'];
  expect(etag, 'strong SHA-256 ETag').toMatch(/^"[0-9a-f]{64}"$/);
  const again = await request.get(edition.cover.url, { headers: { 'If-None-Match': etag } });
  expect(again.status()).toBe(304);
});

test('member opens a chapter, turns the page and resumes from Vault', async ({ page }) => {
  needsMember();
  await signIn(page);
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

test('member saves and unsaves a published edition', async ({ page }) => {
  needsMember();
  await signIn(page);
  const put = await api(page, 'PUT', `/me/saved-items/${edition.edition_id}`, { key: crypto.randomUUID() });
  expect(put.status, JSON.stringify(put.json)).toBe(200);
  expect(put.json.available).toBe(true);
  const listed = await api(page, 'GET', '/me/saved-items?limit=100');
  expect(listed.json.items.find((item) => item.edition_id === edition.edition_id)?.available).toBe(true);
  const removed = await api(page, 'DELETE', `/me/saved-items/${edition.edition_id}`, { key: crypto.randomUUID() });
  expect(removed.status).toBe(204);
});

test('member opens a learning track', async ({ page }) => {
  needsMember();
  await signIn(page);
  const tracks = (await api(page, 'GET', `/learning/tracks?locale=${LOCALE}`)).json;
  test.skip(!tracks.items.length, 'No published learning track in this territory.');
  const track = tracks.items[0];
  expect(['free', 'included', 'locked']).toContain(track.access);
  const response = await page.goto(`${BASE}/${LOCALE}/tracks/${track.track_id}/`);
  expect(response.status()).toBe(200);
  await expect(page.locator('h1')).toContainText(track.title);
});
