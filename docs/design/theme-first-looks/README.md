# Maison theme first looks: Ivory Atelier and Burgundy Salon

Status: **proposal for owner review. Not approved and not implemented.**
The approved Maison visual design is still the Peacock Crest theme kit (`docs/design/peacock-crest/`, `static/maison/peacock/`). These two directions answer the owner brief: a premium, luxurious, user-friendly theme in Ivory, Dark Burgundy and Metallic Gold. Changing the shipped theme is a design-behaviour deviation, so it needs explicit owner approval (AGENTS.md, 17 Nov 2026 instruction) before any code under `static/`, `templates/` or `client/` changes.

| File | What it is |
| --- | --- |
| `theme-a.html` / `theme-a.png` | A · Ivory Atelier, light-first. One scrollable board with a 1060 px desktop frame and a 390 px mobile frame for each screen, followed by tokens and contrast results. |
| `theme-b.html` / `theme-b.png` | B · Burgundy Salon, dark-first. Same five screens, a different layout language. |
| `README.md` | This summary: tokens, fonts, contrast results and open questions. |

Method: the `superdesign` skill was invoked first. Its CLI ran (v0.14.0) but was not authenticated, and its login needs a browser, which this session does not have. Following the skill's fallback (`design-with-your-model`), both mockups are hand-authored static HTML/CSS. Each is self-contained: inline CSS and Google Fonts only, with no scripts. PNGs were rendered with Playwright (Chromium, deviceScaleFactor 1, full page, 1560 px wide).

The official logo is used unmodified, by relative path (`../../../static/maison/logo.png`). It always sits on ivory, because its dark wordmark needs a light background. Theme B therefore keeps an ivory header band for it. Covers, people and numbers are typographic placeholders and layout samples. No real data, customer records or licensed artwork are used.

---

## The two directions

### A · Ivory Atelier (light-first)
1. Ivory paper is the room, dark burgundy is the voice, and metallic gold is foil: hairlines, frames, progress bars and one flourish per screen.
2. The layout uses a classic top navigation, with a burgundy "salon card" hero that holds Continue (book, audiobook and video together).
3. The Reader is a warm two-page spread with a drop cap, a page-curl corner, dashed tap-zone overlays and a keyboard legend. The page carries no ornament or ads.
4. Audio and video get the only dark surfaces (a burgundy stage and ink-dark video chrome), so media feels immersive while the rest of the app stays calm.
5. Best for long reading, daytime study and the widest accessibility margins (ink on ivory is 16.8:1).

### B · Burgundy Salon (dark-first)
1. An evening salon: noir-burgundy velvet surfaces, ivory text and gold as jewellery, with squarer couture radii and an uppercase letter-spaced UI.
2. The app shell has a slim left icon rail, an ivory logo band that doubles as the search bar, and a featured-title hero with a large cover.
3. The Reader shows a 3D page turn in progress, a swipe arc, edge tap zones, a bookmark page strip and Paper/Sepia/Night page themes. The mobile frame shows a Bengali storybook on the sepia page.
4. The audio player is built around a gold "disc" whose arc shows chapter progress, with a live narrated line and a speed dial. The video player uses a 21:9 theatre layout with optional stacked dual-language (EN + বাংলা) subtitles.
5. Best for listening, watching and evening use. The cinematic feel makes the visual brand stronger.

Shared rules in both directions: the interface is English only. Book language is a **content filter** (All / English / বাংলা) and never a user segment. Reading and display fonts switch per book `lang`. Ads are labelled "Sponsored", frequency-capped, include "Why this ad?", and never appear in the Reader, a playing lesson or children's titles. The admin view makes the 47-region publication rule visible before anything can be scheduled.

---

## Fonts

| Role | A · Ivory Atelier | B · Burgundy Salon | Why |
| --- | --- | --- | --- |
| Display | **Cormorant Garamond** 500/600, italic | **Bodoni Moda** 400–600, italic (optical sizes) | A: an old-style Garamond echoes the serif in the logo; refined and literary. B: a high-contrast Didone reads as couture and editorial luxury, especially on dark. |
| UI | **DM Sans** 400–600 | **Jost** 400–600 | A: neutral, highly legible at 12–14 px, with tabular-friendly figures. B: a geometric, Futura-like face that suits Art-Deco salon caps and letter-spaced eyebrows. |
| Long reading | **Source Serif 4** (optical sizes) | **Literata** (optical sizes) | Both are designed for long on-screen reading. Literata was made for e-book reading. |
| Bengali reading/display | **Noto Serif Bengali** | **Tiro Bangla** | Correct conjuncts, metrics that sit well beside the Latin serif, and OFL licence. Tiro Bangla adds more calligraphic character for storybooks. |
| Bengali UI | **Noto Sans Bengali** | **Hind Siliguri** | Clean sans at small sizes for chips, titles in tables and subtitles. |

A reuses the fonts already self-hosted under `static/maison/fonts/` (all OFL), so it needs no new font licensing or hosting. B's fonts are also OFL on Google Fonts, but they would have to be self-hosted before release.

Type scale (px / line-height):

| Token | A | B |
| --- | --- | --- |
| display | 56 / 1.05 | 60 / 1.02 |
| h1 | 40 / 1.10 | 42 / 1.08 |
| h2 | 30 / 1.15 | 30 / 1.15 |
| h3 | 22 / 1.25 | 22 / 1.25 |
| body | 16 / 1.6 | 16 / 1.6 |
| small | 14 / 1.5 | 14 / 1.5 |
| micro / eyebrow | 12 / 1.4 (eyebrow 11–13, +0.14 em) | 12 / 1.4 (eyebrow 11, +0.24 em caps) |
| reading | 20 / 1.7 (user-adjustable) | 19 / 1.72 (user-adjustable) |
| Bengali text | line-height +0.2 to 0.25 over Latin, no letter-spacing, no uppercase | same |

---

## Colour tokens

### A · Ivory Atelier

| Token | Hex | Role |
| --- | --- | --- |
| ivory-50 | `#FCF8F0` | canvas |
| ivory-100 | `#F6EFE1` | surface, cards |
| ivory-200 | `#EEE3CD` | raised, wells |
| ivory-300 | `#DFCFAE` | hairlines (decorative) |
| burgundy-950 | `#2A0F16` | ink (text) |
| burgundy-900 | `#3F1420` | admin nav |
| burgundy-800 | `#561A2A` | hero and audio stage |
| burgundy-700 | `#6E2034` | primary button, links, selected, focus ring |
| burgundy-600 | `#8A2C43` | hover |
| burgundy-100 | `#F1DCDD` | selected tint |
| ink-muted | `#5C4448` | secondary text |
| gold-800 | `#6E5119` | gold *text* on ivory |
| gold-600 | `#A8833A` | strokes and icons (non-text) |
| gold-400 | `#CFAE62` | foil mid |
| gold-200 | `#EED9A2` | gold text on burgundy |
| reader page | `#FFFCF5`, ink `#2B1A1C`, highlight `#F3E1A6` | Reader |
| status | success `#2F5D3A`, warning `#7A4A06`, danger `#9B1C2E`, info `#2D4A6B` (on tinted pills) | |

Metallic gold gradients:
- `--gold-foil` (decorative only): `linear-gradient(115deg,#7D5C22 0%,#B8924A 22%,#F1DDA1 46%,#C9A256 62%,#8E6B2A 82%,#C8A35A 100%)`
- `--gold-foil-fill` (surfaces carrying ink text or icons): `#B8924A → #F1DDA1 → #C9A256 → #B8924A`
- `--gold-foil-text-dark` (large text on burgundy): `#B8924A → #F1DDA1 → #C9A256`
- `--gold-foil-text-light` (large text on ivory): `#6E5119 → #8E6B2A → #6E5119`

### B · Burgundy Salon

| Token | Hex | Role |
| --- | --- | --- |
| noir | `#1A070D` | canvas |
| surface | `#2A0D16` | cards, panels, rail |
| raised | `#3A1320` | menus, wells, hover |
| line | `#5C2433` | hairlines (decorative) |
| velvet | `#7A1F35` | selected, secondary button |
| velvet-hi | `#94304A` | hover |
| ivory | `#F5ECDA` | primary text, logo band |
| ivory-muted | `#CBB8A6` | secondary text |
| ink | `#22090F` | text on ivory and foil |
| gold | `#D8B76A` | gold text on dark |
| gold-300 | `#E8CF8E` | focus ring, badges, gold on velvet |
| gold-600 | `#A8833A` | strokes |
| reader Paper / Sepia / Night | `#F7EFE0`/`#22090F` · `#EAD9B8`/`#3A2418` · `#201014`/`#E9DCC4` | page themes |
| status (dark-tuned) | ok `#8FD1A0`, warn `#F0C674`, bad `#F2A0AC`, info `#A9C6EA` | |

Metallic gold gradients:
- `--foil` (decorative: hairlines, disc, progress): `linear-gradient(120deg,#8A6A2E 0%,#C9A24F 24%,#F4E3AE 48%,#D2AC5C 66%,#96722F 86%,#C9A24F 100%)`
- `--foil-fill` (CTA, play button; Noir text only): `#C9A24F → #F4E3AE → #D2AC5C → #C9A24F`
- `--foil-text` (display text on dark): `#C9A24F → #F4E3AE → #D2AC5C → #C9A24F`

### Spacing, radius, shadow, motion

| Token | A · Ivory Atelier | B · Burgundy Salon |
| --- | --- | --- |
| Space (4 pt) | 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 | same |
| Radius | 4 · 8 · 14 (cards) · 22 (hero) · pill (buttons, chips) | 2 · 4 (buttons) · 8 (cards) · 12 (panels) · pill (chips only) |
| Shadow | sh-1 `0 1px 2px rgba(42,15,22,.06), 0 2px 6px rgba(42,15,22,.05)`; sh-2 `0 6px 18px rgba(42,15,22,.10)…`; sh-3 `0 24px 60px rgba(42,15,22,.18)…`; page gutter shadow inset | sh-1/2 = inner gold top highlight `rgba(244,227,174,.06–.08)` + black depth; sh-3 `0 30px 80px rgba(0,0,0,.6)` + gold 1 px ring; glow-gold for the logo band and active knob |
| Durations | 120 ms feedback · 220 ms UI · 520 ms page curl | 140 ms · 260 ms · 600 ms 3D page turn · 2.4 s one-off CTA shimmer |
| Easing | out `cubic-bezier(.2,.7,.2,1)`; page `cubic-bezier(.45,.05,.2,1)` | out `cubic-bezier(.16,1,.3,1)`; page `cubic-bezier(.6,.05,.25,1)` |
| Reduced motion (`prefers-reduced-motion` and the existing in-app `reduced_motion` setting) | page curl becomes an instant swap with a 1 px edge highlight; no parallax; no waveform animation | no shimmer; no disc spin; page turn becomes a 120 ms cross-fade; mini-player slides become fades |
| Focus | 2 px burgundy-700 ring, 3 px offset (brass on ivory is only 1.68:1, as already noted in the Peacock kit) | 2 px gold-300 ring + 2 px noir gap |

---

## WCAG 2.2 AA contrast results

Ratios are computed with the WCAG relative-luminance formula. Thresholds: 4.5:1 for body text, 3:1 for large text and non-text UI. The two "Fails" rows are intentional. They document why the full foil gradient may never sit behind text, and the token rules forbid that use.

### A · Ivory Atelier

| Pair | Ratio | Needs | Result |
| --- | --- | --- | --- |
| Ink `#2A0F16` on Ivory 50 `#FCF8F0` | 16.82:1 | 4.5 | Pass |
| Ink on Ivory 100 `#F6EFE1` | 15.57:1 | 4.5 | Pass |
| Ink-muted `#5C4448` on Ivory 50 | 8.35:1 | 4.5 | Pass |
| Ink-muted on Ivory 100 | 7.73:1 | 4.5 | Pass |
| Ink-muted on Ivory 200 `#EEE3CD` | 6.95:1 | 4.5 | Pass |
| Burgundy 700 `#6E2034` text/links on Ivory 50 | 10.33:1 | 4.5 | Pass |
| Burgundy 700 on Burgundy 100 `#F1DCDD` (selected) | 8.35:1 | 4.5 | Pass |
| Ivory 50 on Burgundy 700 (primary button) | 10.33:1 | 4.5 | Pass |
| Ivory 50 on Burgundy 800 `#561A2A` (hero, stage) | 12.57:1 | 4.5 | Pass |
| `#EBDDD6` body on Burgundy 800 | 10.05:1 | 4.5 | Pass |
| `#E0CFC6` meta on Burgundy 950 | 11.80:1 | 4.5 | Pass |
| Gold 200 `#EED9A2` on Burgundy 800 | 9.56:1 | 4.5 | Pass |
| Gold 200 on Burgundy 900 `#3F1420` (admin nav) | 11.32:1 | 4.5 | Pass |
| Gold 800 `#6E5119` on Ivory 50 (eyebrows) | 6.95:1 | 4.5 | Pass |
| Gold 800 on Ivory 100 | 6.43:1 | 4.5 | Pass |
| Reading ink `#2B1A1C` on page `#FFFCF5` | 16.17:1 | 4.5 | Pass |
| Reading ink on highlight `#F3E1A6` | 12.73:1 | 4.5 | Pass |
| Ink on foil-fill worst stop `#B8924A` (play button, ad mark) | 6.15:1 | 4.5 | Pass |
| Foil-text-dark worst stop `#B8924A`, large text on Burgundy 800 | 4.60:1 | 3.0 | Pass |
| Foil-text-light worst stop `#8E6B2A`, large text on Ivory 50 | 4.62:1 | 3.0 | Pass |
| Full foil `#7D5C22` stop behind ink text | 2.91:1 | 4.5 | Fails: forbidden by rule |
| Focus ring Burgundy 700 vs Ivory 50 | 10.33:1 | 3.0 | Pass |
| Gold 600 `#A8833A` stroke on Ivory 50 | 3.32:1 | 3.0 | Pass |
| Ivory 300 line on Ivory 50 | 1.45:1 | none | Decorative, exempt |
| White caption on `rgba(18,7,9,.78)` over light footage (about `#3E3337`) | 12.11:1 | 4.5 | Pass |
| Success `#2F5D3A` on `#E3EEE4` | 6.41:1 | 4.5 | Pass |
| Warning `#7A4A06` on `#F6E8CC` | 6.17:1 | 4.5 | Pass |
| Danger `#9B1C2E` on `#F6DADD` | 6.15:1 | 4.5 | Pass |
| Info `#2D4A6B` on `#DFE7F0` | 7.30:1 | 4.5 | Pass |

### B · Burgundy Salon

| Pair | Ratio | Needs | Result |
| --- | --- | --- | --- |
| Ivory `#F5ECDA` on Noir `#1A070D` | 16.57:1 | 4.5 | Pass |
| Ivory on Surface `#2A0D16` | 15.32:1 | 4.5 | Pass |
| Ivory on Raised `#3A1320` | 13.83:1 | 4.5 | Pass |
| Muted `#CBB8A6` on Noir | 10.13:1 | 4.5 | Pass |
| Muted on Surface | 9.37:1 | 4.5 | Pass |
| Muted on Raised | 8.46:1 | 4.5 | Pass |
| Gold `#D8B76A` on Noir | 10.09:1 | 4.5 | Pass |
| Gold on Surface | 9.34:1 | 4.5 | Pass |
| Gold on Raised | 8.43:1 | 4.5 | Pass |
| Ivory on Velvet `#7A1F35` | 8.62:1 | 4.5 | Pass |
| Gold 300 `#E8CF8E` on Velvet | 6.63:1 | 4.5 | Pass |
| Noir on foil-fill worst stop `#C9A24F` (CTA, play) | 8.11:1 | 4.5 | Pass |
| Full foil `#8A6A2E` stop behind Noir text | 3.87:1 | 4.5 | Fails: forbidden by rule |
| Header ink `#22090F` on Ivory band | 16.06:1 | 4.5 | Pass |
| Velvet nav text on Ivory band | 8.62:1 | 4.5 | Pass |
| Night reader `#E9DCC4` on `#201014` | 13.53:1 | 4.5 | Pass |
| Sepia reader `#3A2418` on `#EAD9B8` | 10.46:1 | 4.5 | Pass |
| Paper reader `#22090F` on `#F7EFE0` | 16.50:1 | 4.5 | Pass |
| Velvet tap-zone label on Sepia | 7.28:1 | 4.5 | Pass |
| Gold 300 Bengali subtitle on caption box `#120609` | 13.02:1 | 4.5 | Pass |
| Noir on Gold 300 (Sponsored label, badges) | 12.73:1 | 4.5 | Pass |
| Focus ring Gold 300 on Noir | 12.73:1 | 3.0 | Pass |
| Line `#5C2433` on Noir | 1.63:1 | none | Decorative, exempt |
| ok `#8FD1A0` / warn `#F0C674` / bad `#F2A0AC` / info `#A9C6EA` on Raised | 9.12 / 10.07 / 8.04 / 9.24 | 4.5 | Pass |

Other AA 2.2 points designed in: 44 px minimum targets (chips at 32 px need 44 px hit areas in build); focus is never hidden by sticky bars (2.4.11); swipe gestures always have tap and keyboard alternatives (2.5.1 / 2.5.7); captions have size and backing controls; status is never shown by colour alone (dot + word).

---

## Feature and screen inventory: open questions for the owner

Confirm or strike each item before every screen is designed. Items marked ★ already have routes in `web/urls.py` (home, explore, search, title, reader, player, video, learn, track, lesson, practice, question, series, collection, vault, downloads, settings, pass, guardian, clips, gifts, sign-in/up and system states).

**0. Direction**
1. A (light-first), B (dark-first), or a hybrid: A's light theme as default with B as the dark mode? Should either replace Peacock Crest, or sit beside it as a selectable theme?
2. Display face: Cormorant Garamond (already self-hosted) or Bodoni Moda (new self-hosting)? Same question for Literata vs Source Serif 4, and Tiro Bangla vs Noto Serif Bengali.
3. Should gold foil animate (one-off shimmer on the primary CTA), or stay static everywhere?

**1. Reader ★**
4. Page model: paginated spread (desktop) plus single page (mobile), scroll mode, or both as a user option?
5. Turn animation default: curl, slide or none? Should users be able to change it?
6. Page themes: Paper / Sepia / Night (plus True Black from today's settings)? Font size, line spacing, margins and justification controls?
7. Storybooks: fixed-layout illustrated pages with pinch-zoom and two-page art spreads? Do picture books for children need a simplified "kid mode" chrome?
8. Dictionary or definition on long-press, for English and Bengali? Translation of a selection (would this be a paid API)?
9. Text-to-speech for books without a narrated edition, or narrated audio only?

**2. Audio ★**
10. Speed range: 0.5 to 3× in 0.05 steps, or fixed presets? Should speed be remembered per book or globally?
11. Sleep timer options: end of chapter/tale, 5–60 minutes, shake to extend? Fade length?
12. Read-along word highlighting needs synced timings per edition. Is that in scope for launch content?
13. Background play, lock-screen controls, car or Bluetooth controls, and a persistent mini-player on every screen except the Reader?

**3. Video tutorials ★**
14. Speed presets 0.5 to 2×. Subtitles in EN, BN, or both stacked (as B shows)? Subtitle size, colour and backing controls?
15. Transcript with click-to-seek and search, chapters, picture-in-picture, quality selector, and resume position?
16. Notes timestamped to the video? Should a lesson count as "complete" at a watch threshold or only after its quiz?

**4. Series, courses, quizzes ★**
17. Series types: knowledge series, story series, course tracks. Ordered or free order? Should there be locked prerequisites?
18. Quizzes: single and multi-choice, true/false, short answer? Retries, explanations, scoring, certificates?
19. Should progress streaks, goals or badges exist, or is that against the calm premium tone?

**5. Discovery, search and language filter ★**
20. Confirm that book language (All / English / বাংলা, extensible) is a content filter only, and that the interface stays English for everyone. Should the default be "All languages" for every reader?
21. Search across title, author, narrator, series, transcript text and in-book text? Facets: format, language, age band, duration, topic?
22. Editorial collections, "Because you read…" recommendations, trending? Any personalisation constraints?

**6. Library management ★ (Vault)**
23. Shelves: Continue, Saved, Finished, Downloads, personal lists ★? Should lists be shareable?
24. Bookmarks, highlights (how many colours?) and notes: private only, or export or share? Should they sync across devices?
25. Downloads and offline ★: storage cap, device limit, licence expiry, Wi-Fi-only option?

**7. Profiles and settings ★**
26. Multiple profiles per account (family or children), guardian controls ★, age bands?
27. Settings: theme, reduced motion, text size, autoplay, data saver, notifications, privacy, account deletion?
28. Free access now. Should the Pass ★ and checkout screens be hidden, or shown as "coming later"?

**8. Ads and sponsorship**
29. Allowed placements: Home banner, Explore rail, end-of-lesson card, between series episodes? Confirm exclusions: Reader, active playback, children's titles, checkout.
30. Formats: static card only, or also short video pre-roll on tutorials? Are house promotions and sponsored placements styled the same?
31. Frequency cap, "Why this ad?", hide or report, and consent per region. Which ad source: direct-sold campaigns in our own admin, or a third-party network (cost, privacy and region policy implications)?

**9. Admin**
32. Content pipeline: draft → rights check → QA → scheduled → published → held. Who approves each step (roles)?
33. Rights and territories: a 47-region matrix per edition, format and action, with publication blocked until it is complete. Is the visual matrix view required at launch?
34. Media QA: caption coverage per language, audio-sync check, cover and metadata completeness?
35. Campaigns: create, target (region, surface, audience), schedule, cap, pacing, pause, report. Is a review or approval step needed?
36. Users and devices: search, roles, device list and revoke, offline licences, guardian links, data export and delete requests.
37. Moderation: reports on notes, quiz disputes, ad complaints. What are the SLAs and escalation paths?
38. Analytics: which KPIs (reads, completions, listening minutes, lesson completion, ad impressions/CTR)? Any privacy limits on per-user analytics?
39. Support: in-app contact ★, FAQ, ticket queue, status page ★?
40. Is an audit log of every admin and provider mutation required (it is recommended)?

**10. Platform**
41. Is mobile web (PWA) enough at launch, or do native iOS and Android shells need their own gesture specs?
42. Is tablet landscape a first-class layout (two-page spread on tablets)?
43. Which accessibility conformance target should be published: WCAG 2.2 AA (assumed)?
