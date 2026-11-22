// Production regression suite. See journey.spec.mjs for prerequisites.
import { defineConfig } from '@playwright/test';

// Honour an egress proxy when one is configured (Playwright does not read HTTPS_PROXY itself).
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;

export default defineConfig({
  testDir: '.',
  timeout: 60_000,
  retries: 0, // A production regression must not be hidden by retries.
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: '../../.local/e2e-report', open: 'never' }]],
  use: {
    browserName: 'chromium',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    userAgent: 'Maison-Regression-Suite',
    ...(proxy ? { proxy: { server: proxy } } : {}),
  },
});
