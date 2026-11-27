// WCAG 2.2 AA gate: no serious or critical axe violations on the public pages.
// Runs with the production regression suite (`npm run e2e:production`) against
// MAISON_E2E_BASE_URL; outside India production pages are skipped like the journey suite.
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const BASE = (process.env.MAISON_E2E_BASE_URL || 'https://maison.theearnalism.com').replace(/\/$/, '');
const PAGES = ['/en/', '/en/explore/', '/en/sign-in/', '/en/sign-up/', '/en/privacy/', '/en/terms/', '/en/contact/', '/en/learn/'];

for (const path of PAGES) {
  test(`no serious accessibility violations on ${path}`, async ({ page }) => {
    const response = await page.goto(`${BASE}${path}`);
    test.skip(response.status() === 403, 'Production serves India only: run this suite from an Indian network.');
    expect(response.status()).toBe(200);
    const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
    const blocking = violations.filter((v) => ['serious', 'critical'].includes(v.impact))
      .map((v) => `${v.id}: ${v.help} (${v.nodes.length}) e.g. ${v.nodes[0]?.target?.join(' ')}`);
    expect(blocking, blocking.join('\n')).toEqual([]);
  });
}

// Reader and player (Read/Listen plan, Task 13). The reader runs signed out on the first published Reader
// edition's preview, once per reading theme (set the way the reader itself stores a signed-out choice).
// The player needs the dedicated test account (MAISON_E2E_EMAIL/PASSWORD, see journey.spec.mjs) and a
// published audio edition. Skipped, never passed, while the live catalog has none. The local equivalent with
// fixtures runs in integration_tests/test_read_listen.py.
const THEMES = ['light', 'sepia', 'dark', 'true_black'];
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'];

async function firstEdition(request, format) {
  const catalog = await request.get(`${BASE}/api/v1/catalog?format=${format}&limit=20`);
  if (catalog.status() === 403) return { blocked: true };
  expect(catalog.status(), 'catalog API').toBe(200);
  return { edition: (await catalog.json()).items.find((card) => card.formats.includes(format)) };
}

async function blockingViolations(page) {
  const { violations } = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  return violations.filter((v) => ['serious', 'critical'].includes(v.impact))
    .map((v) => `${v.id}: ${v.help} (${v.nodes.length}) e.g. ${v.nodes[0]?.target?.join(' ')}`);
}

for (const theme of THEMES) {
  test(`no serious accessibility violations on the reader (${theme})`, async ({ browser, request }) => {
    const { blocked, edition } = await firstEdition(request, 'reader');
    test.skip(!!blocked, 'Production serves India only: run this suite from an Indian network.');
    test.skip(!edition, 'The live catalog has no published Reader edition yet.');
    const context = await browser.newContext();
    await context.addInitScript((value) => {
      localStorage.setItem('maison.reader.preferences', JSON.stringify({ reader_theme: value }));
    }, theme);
    const page = await context.newPage();
    const response = await page.goto(`${BASE}/en/read/${edition.edition_id}/`);
    expect(response.status()).toBe(200);
    await expect(page.locator('[data-anchor]').first()).toBeVisible({ timeout: 20_000 });
    await expect(page.locator('body')).toHaveClass(new RegExp(`reader-theme-${theme}`));
    const blocking = await blockingViolations(page);
    expect(blocking, blocking.join('\n')).toEqual([]);
    await context.close();
  });
}

test('no serious accessibility violations on the player', async ({ browser, request }) => {
  const { blocked, edition } = await firstEdition(request, 'audio');
  test.skip(!!blocked, 'Production serves India only: run this suite from an Indian network.');
  test.skip(!edition, 'The live catalog has no published audio edition yet.');
  test.skip(!process.env.MAISON_E2E_EMAIL || !process.env.MAISON_E2E_PASSWORD, 'Set MAISON_E2E_EMAIL and MAISON_E2E_PASSWORD for the dedicated test account.');
  const page = await browser.newPage();
  await page.goto(`${BASE}/en/sign-in/`);
  await page.fill('#auth-email', process.env.MAISON_E2E_EMAIL);
  await page.fill('#auth-password', process.env.MAISON_E2E_PASSWORD);
  const consent = page.locator('input[name="password_purpose_consent"]');
  if (await consent.count()) await consent.check();
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.includes('/sign-in/'), { timeout: 15_000 });
  const response = await page.goto(`${BASE}/en/listen/${edition.edition_id}/`);
  expect(response.status()).toBe(200);
  await expect(page.locator('.player-panel audio')).toBeAttached({ timeout: 20_000 });
  const blocking = await blockingViolations(page);
  expect(blocking, blocking.join('\n')).toEqual([]);
});
