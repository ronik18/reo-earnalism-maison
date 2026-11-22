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
