// Behaviour check for the landing carousel in the design prototype.
// Run: node docs/design/final/carousel.check.mjs
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const page_url = 'file://' + path.join(path.dirname(fileURLToPath(import.meta.url)), 'index.html') + '#home';
const HEADLINES = [
  'Five spare minutes? Read a page, not a feed.',
  'Your language, your shelf.',
  'Your place follows you.',
  'Learn one idea at a time.',
];
let failed = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + detail}`); if (!ok) failed++; };

const browser = await chromium.launch();
async function open({ width = 1440, reduced = false } = {}) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: reduced ? 'reduce' : 'no-preference' });
  await page.clock.install();
  await page.goto(page_url);
  return page;
}
const active = (page) => page.evaluate(() => [...document.querySelectorAll('#turner .turn-card.is-active')].map(c => c.dataset.card));

try {
  let page = await open();
  check('carousel exists', await page.locator('#turner').count() === 1, 'no #turner');
  if (await page.locator('#turner').count()) {
    check('headline', (await page.locator('#turner h2').first().textContent()).trim() === 'Swap one scroll for one story.');
    const heads = await page.locator('#turner .turn-card h3').allTextContents();
    check('four card headlines', JSON.stringify(heads.map(s => s.trim())) === JSON.stringify(HEADLINES), JSON.stringify(heads));
    const ctas = await page.locator('#turner .turn-card a', { hasText: 'Start Chapter 1 free' }).count();
    check('every card has the CTA', ctas === 4, `found ${ctas}`);
    check('card 1 shows the real opening', (await page.locator('[data-card="c1"]').textContent()).includes('Every afternoon, as they were coming from school'));
    check('card 4 is marked coming soon', (await page.locator('[data-card="c4"]').textContent()).includes('Coming soon'));
    check('starts on card 1', JSON.stringify(await active(page)) === '["c1"]');

    await page.clock.runFor(7000);
    check('auto-advances after 7s', JSON.stringify(await active(page)) === '["c2"]', JSON.stringify(await active(page)));

    await page.locator('#turner .turn-stage').hover();
    await page.clock.runFor(15000);
    check('hover pauses', JSON.stringify(await active(page)) === '["c2"]', JSON.stringify(await active(page)));
    await page.mouse.move(5, 5);

    await page.locator('#turn-pause').click();
    check('pause button pressed', await page.locator('#turn-pause').getAttribute('aria-pressed') === 'true');
    await page.mouse.move(5, 5);
    await page.clock.runFor(15000);
    check('paused stays', JSON.stringify(await active(page)) === '["c2"]', JSON.stringify(await active(page)));
    await page.locator('#turn-pause').click();
    check('play resumes state', await page.locator('#turn-pause').getAttribute('aria-pressed') === 'false');

    for (let i = 0; i < 6; i++) await page.locator('#turn-next').click();
    const a = await active(page);
    check('one active after rapid clicks', a.length === 1, JSON.stringify(a));
    await page.locator('.turn-dot[data-i="3"]').click();
    await page.locator('#turn-next').click();
    check('next wraps 4 to 1', JSON.stringify(await active(page)) === '["c1"]', JSON.stringify(await active(page)));
    await page.locator('#turn-prev').click();
    check('prev wraps 1 to 4', JSON.stringify(await active(page)) === '["c4"]', JSON.stringify(await active(page)));

    await page.locator('#turn-next').focus();
    const before = await active(page);
    await page.clock.runFor(21000);
    check('focus inside stops advance', JSON.stringify(await active(page)) === JSON.stringify(before), JSON.stringify(await active(page)));

    const ev = await page.evaluate(() => (window.maisonEvents || []).map(e => e.event));
    check('card view events recorded', ev.includes('carousel_card_viewed'));
    await page.evaluate(() => document.querySelector('#turner .turn-card.is-active a.turn-cta').addEventListener('click', e => e.preventDefault(), { once: true }));
    await page.locator('#turner .turn-card.is-active a.turn-cta').click();
    const ev2 = await page.evaluate(() => (window.maisonEvents || []).filter(e => e.event === 'carousel_cta_clicked'));
    check('cta click recorded with opaque card id only', ev2.length === 1 && Object.keys(ev2[0]).sort().join() === 'card,event', JSON.stringify(ev2));
    check('no sideways scroll 1440', !(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)));
    await page.close();

    page = await open({ reduced: true });
    await page.clock.runFor(30000);
    check('reduced motion never auto-advances', JSON.stringify(await active(page)) === '["c1"]', JSON.stringify(await active(page)));
    await page.close();

    page = await open({ width: 360 });
    check('no sideways scroll 360', !(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)));
    const fits = await page.evaluate(() => { const c = document.querySelector('#turner .turn-card.is-active'); const b = c.querySelector('.turn-cta').getBoundingClientRect(); const r = c.getBoundingClientRect(); return b.right <= r.right + 1 && b.height >= 44; });
    check('CTA fits inside card on phone and is 44px tall', fits);
    await page.close();
  }
} finally {
  await browser.close();
}
console.log(failed ? `${failed} failed` : 'all passed');
process.exit(failed ? 1 : 0);
