# Landing 3D carousel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved taste-first 3D page-turner carousel under the hero of the final Maison design prototype.

**Architecture:** One `<section class="turner">` in `docs/design/final/index.html` (design prototype, not app templates), styled with CSS 3D transforms on handmade-paper cards and driven by a small inline script. A Playwright check script beside the prototype proves the behaviour.

**Tech Stack:** HTML/CSS/vanilla JS; Playwright (pre-installed) via a Node script.

**Spec:** `docs/superpowers/specs/2026-11-22-landing-carousel-design.md`

## Global Constraints

- Placement directly under the hero; hero illustration unchanged.
- Headline exactly: "Swap one scroll for one story."
- Four cards, headlines exactly: "Five spare minutes? Read a page, not a feed." / "Your language, your shelf." / "Your place follows you." / "Learn one idea at a time."
- Every card's primary button text exactly "Start Chapter 1 free"; quiet link "Explore the library".
- Card 4 is labelled "Coming soon"; no prices, counts, ratings or testimonials.
- Auto-advance every 7000 ms; pause on hover, focus, touch and hidden tab; visible Pause/Play; reduced motion → no auto-advance and cross-fade.
- Events: `carousel_card_viewed`, `carousel_cta_clicked` with opaque `card` id only.
- 44px minimum targets; no horizontal scroll 360–1920px.

## Review Focus

- Rapid repeated clicks on next/previous: index must wrap 4→1 and 1→4, never show two cards active.
- Keyboard user tabbing into the carousel: auto-advance stops and does not resume until focus leaves.
- Reduced-motion visitor: no timer ever starts, even after pressing Play.
- Phone width 360px: card text and button stay inside the card, no sideways scroll.
- Hidden tab returns: carousel does not jump several cards at once.

---

### Task 1: Carousel markup, 3D styling and behaviour

**Files:**
- Modify: `docs/design/final/index.html` (new section after `.hero`, CSS before `</style>`, script before `</script>`)
- Create: `docs/design/final/carousel.check.mjs`

**Interfaces:**
- Produces: `window.maisonEvents: Array<{event: string, card: string}>`; DOM `#turner` with `.turn-card[data-card="c1".."c4"]`, active card has `aria-hidden="false"` and class `is-active`; controls `#turn-prev`, `#turn-next`, `#turn-pause` (aria-pressed true when paused), `.turn-dot[data-i]`.

- [ ] **Step 1: Write the failing check** — `carousel.check.mjs` opens the prototype with Playwright and asserts: 4 cards with the exact headlines; each has a link with text "Start Chapter 1 free"; card c1 contains "Every afternoon, as they were coming from school"; card c4 contains "Coming soon"; with `page.clock` advanced 7000 ms the active card becomes c2; hovering stops advance; `#turn-pause` toggles `aria-pressed`; next from c4 wraps to c1 and prev from c1 to c4; only one `.is-active` at a time after 6 rapid clicks; focus inside stops advance; emulated reduced motion → no advance after 30 s; `maisonEvents` records `carousel_card_viewed` on change and `carousel_cta_clicked` on CTA; no horizontal scroll at 360 and 1440.
- [ ] **Step 2: Run it** — `node docs/design/final/carousel.check.mjs` — Expected: FAIL ("#turner not found").
- [ ] **Step 3: Implement** the section, CSS (stacked cards with `transform-origin:left` page-turn, peek offsets, handmade-paper surface, capsule controls) and the script `initTurner()` (timer 7000 ms, pause reasons set, `visibilitychange`, reduced-motion media query).
- [ ] **Step 4: Run it** — same command — Expected: `PASS` lines for every assertion and exit 0.
- [ ] **Step 5: Commit** `git add docs/design/final/index.html docs/design/final/carousel.check.mjs && git commit`.

### Task 2: Captures and canvas

**Files:** Modify: `docs/design/final/home-desktop.png`, `docs/design/final/phone-screens.png`

- [ ] **Step 1:** Re-run the screen capture and update the Superdesign draft `70a96403-ec4f-4e91-98f7-36ddb202dd48`.
- [ ] **Step 2:** Run `node docs/design/final/carousel.check.mjs` — Expected: exit 0. Commit and push.
