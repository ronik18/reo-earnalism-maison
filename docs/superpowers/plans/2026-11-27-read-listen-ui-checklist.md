# Read/Listen UI conventions checklist

Task 0 inventory for the Read/Listen experience plan. Every later frontend task is reviewed against this file.
Evidence is `file:line`. CSS files are minified into very long lines, so a line number points at the rule's line and
the selector is quoted. Re-grep the selector if a line has moved.

Reference: the shipped Read and Listen pages (`templates/web/reader.html`, `templates/web/player.html`, `client/reader.tsx`,
`client/player.tsx`, `client/media-sheets.tsx`), checked against the title page and the other client islands
(`client/video.tsx`, `client/downloads.tsx`, `client/home.tsx`).
Decision basis: the reference is the one other pages import (`MediaSheet` and its two wrappers are used by both
`reader.tsx` and `player.tsx`).

## 0. Read this first: two CSS layers are live at once

`templates/web/base.html:7-9` loads, in order, `fonts/typography.css`, `app.css`, then `room/room.css`.
`<body>` carries `room maison theme-<light|dark|true_black>` plus `room-focused` on reader, player and video
(`base.html:11`). The reader and player views pass `focused=True` (`web/views.py:261, 745, 765`).

- `app.css` is the older shell layer (69 lines, every rule on a very long line). It defines `.maison-dialog`, `.reader`, `.player-panel`, `.focus-toolbar`, `.actions`, `.button`.
- `room/room.css` is the owner-approved "reading room" layer (22 Nov) and wins where both match. It restyles buttons, cards, dialogs and the reader, and it neutralises the app.css shell globals (`room.css:272` comment).
- A new rule that targets a Read/Listen element must be checked against both files, or it will silently lose.
- `fonts/typography.css` also defines `.bottom-sheet` and `.sheet-content` selectors (`typography.css:12, 33, 44, 71-72`). No template or client file uses those classes. They are dead hooks, not a pattern (see section 5).

## 1. Colour tokens

Each new colour is written through a variable. Do not paste hex values into new rules.

| Layer | Variables | Evidence |
|---|---|---|
| Shell defaults (dark base) | `--canvas --surface --raised --ink --muted --gold --line --accent --ui --display` | `app.css:1` |
| Light theme | same names, light values | `app.css:3` `.theme-light`, `room.css:267` `body.room{...}` |
| Dark and true black | same names | `room.css:269-270`, `app.css:3` `.theme-true_black` |
| Room palette | `--ivory --parchment --parchment-deep --line --burgundy --burgundy-deep --wine --ink --ink-soft --gold --gold-deep --gold-text --gold-on-dark --night --night-ink --night-soft` | `room.css:3-12` |
| Paper and shadow | `--paper` (`handmade-paper.webp`), `--card-shadow` | `room.css:12-13` |
| Focused (Read, Listen, Watch) override | `--surface:#2A1820 --raised:#352831 --ink:#F6EEDF --muted:#CDBDB4 --gold:#E6C987 --line:#4A3038` | `room.css:339` `body.room-focused` |

Conventions:

- [ ] Text, borders and fills use `--ink`, `--muted`, `--line`, `--surface`, `--raised`, `--accent`, `--gold`. These re-point per theme and per `room-focused`, so they work on the light header and the dark reading surface. The room palette names (`--burgundy`, `--wine`, `--ivory`) are for fixed brand surfaces only (header plate, `.room-btn`).
- [ ] Primary action: `--accent` fill, ivory text, 4 px radius (`room.css:297` `.room-page .button`). Inside `room-focused` it flips to gold fill with `--burgundy-deep` text (`room.css:340-342`).
- [ ] Secondary action: transparent, `--accent` outline (`room.css:299`); gold outline in dark themes and in `room-focused` (`room.css:301, 342`).
- [ ] Reader surface themes are classes `reader-light|paper|sepia|dark|ink|true_black` set by `client/reader.tsx:493-494`. Their backgrounds are literal values in `app.css:10` and `room.css:344-345`, not tokens. A new reader control must inherit with `color:inherit` / `currentColor` (as `.reader button` does, `app.css:10`), never a fixed colour.
- [ ] Highlight colours `gold|mint|rose|lavender` are literal `mark.<name>` rules (`app.css:10`). Reuse those class names for any new highlight UI.
- [ ] Gap: no contrast figures are recorded for `--muted` on `room-focused` surfaces or for the wine focus ring on dark surfaces. `DESIGN.md` quotes ratios for its own `--binding`/`--paper` tokens, which are a different token set from the shipped CSS variables. Measure only if a task asks.

## 2. Spacing, radius, type scale

- [ ] No spacing variable exists. Spacing is literal px in rules. Values in use on Read/Listen: gaps 8, 10, 12, 16, 20, 24; section margins 20-40; reader padding `36px 45px`, mobile `26px 22px` (`app.css:10, 14`); dialog padding 25, mobile `20px 18px` (`app.css:11, 14`); `.room-page` padding `48px 32px 96px`, mobile `32px 16px 72px` (`room.css:282, 283`); `.room-wrap` side gutter 32, mobile 16 (`room.css:27-28`).
- [ ] `DESIGN.md` states an 8 px scale (4, 8, 12, 16, 24, 32, 48, 72, 112). The code only partly follows it (10, 18, 25, 36, 45 appear). New rules should use the DESIGN.md scale values.
- [ ] Radius: buttons 4 px inside `.room-page` (`room.css:296-297`); dialogs 10 px (`app.css:11`); cards 8 px (`room.css:312`); reader 6 px (`room.css:344`); icon buttons and chips 999 px (`room.css:172, 64`). app.css base buttons are 22 px pills (`app.css:4`) but room.css overrides them inside `.room-page`.
- [ ] Type families: `--display` (Cormorant Garamond then Noto Serif Bengali), `--ui` (DM Sans then Noto Sans Bengali), `--read` (Source Serif 4 then Noto Serif Bengali) (`room.css:9-10`, `typography.css:13-15`).
- [ ] Type sizes are literal. UI body 16 px; reader 20 px default with options 16/20/23/26/30 (`client/reader.tsx:914`, `typography.css:21`); `.eyebrow` 12 px upper-case, `.fine` 14 px; dialog h2 30 px (mobile 27); dialog title in `.player-mini` 22 px. Small status text is 14 px (`app.css:4` `.fine`, `.save-status`).
- [ ] Breakpoints in use: 640, 767, 900, 1100 px. Read/Listen mobile rules sit at `max-width:767px` (`app.css:14, 36`); `room.css` uses 640 for the page frame and 767 for the last block (`room.css:371`). Use 767 for a new Read/Listen mobile rule.

## 3. Buttons and icon buttons

- [ ] Global touch target: `button,select,summary,.button{min-height:44px}` (`app.css:4`). Inline text links get 44 px through per-rule `min-height:44px` (`app.css:9, 35` `.unit-list a`, `.text-link`).
- [ ] Primary and form-submit buttons: 48 px minimum, 24 px side padding (`room.css:47` `.room-btn`, `297` `.room-page .button`, `368` form submit). Inputs and selects: `min-height:48px` (`app.css:5`) or 50 px inside `.room-page` (`room.css:305`).
- [ ] Plain `<button>` is a surface-filled, `--line`-bordered control with gold-deep border on hover (`room.css:302-303`). `reader-actions` buttons are transparent with `currentColor` border (`app.css:10`).
- [ ] Disabled: `opacity:.6`, `cursor:not-allowed` (`app.css:4, 36`). The base rule is `cursor:wait`, overridden later in app.css. Disabled state is set through the `disabled` attribute, driven by a `busy` flag (`player.tsx` `disabled={busy}`, `reader.tsx` `disabled={busy}`).
- [ ] Toggle state: native `aria-pressed` for on/off (`player.tsx:496` complete toggle) and `aria-expanded` for disclosure (`player.tsx:416` mini/expand). Do not invent `data-active` styling.
- [ ] Icon-only buttons are 44 x 44 px, round, `grid;place-items:center`, no padding: `.turn-btn` and `.turn-dot` (`room.css:172, 176`). Header icon links are `min-width:44px` (`room.css:72`). Icon buttons carry `aria-label`, and the glyph is `<svg aria-hidden="true"><use href="#i-..."/></svg>` (`base.html:12-26`).
- [ ] Icon set is the inline sprite in `base.html:12-26`: `i-book i-head i-play i-globe i-search i-user i-arrow i-back i-next i-moon i-speed i-check i-pause i-tri`. Icons are 20 px (`room.css:23` `.room svg{width:20px;height:20px}`), stroke 1.6-1.9, `currentColor`. A later task that needs another glyph adds a `<symbol>` here with the same attributes.
- [ ] Gap: `client/*.tsx` has no icon button at all. Every Read/Listen control is a text button (`t("close")`, `t("back")`, `t("continue")`). `<use>` is not used from React anywhere. A React icon button is a new piece with no instance (see section 10 for the question).
- [ ] Gap: no 44 px rule is written for icon-only controls in React, only for `.turn-btn`. The 44 px minimum is therefore a project convention carried by the global `button` rule, not a stated requirement. Do not cite a standard for it.

## 4. Player layout

- [ ] `player.html` is a one-line shell: back link plus `<div id="player-island">` (`player.html:1`). The island moves its host into `#persistent-media` (fixed dock, bottom right, `z-index:90`) and adds `has-persistent-player` to body (`player.tsx:573-580`, `app.css:25`, `room.css:281`).
- [ ] Component structure: `<section className="player-panel [player-mini]" aria-label={t("audio")}>`, then `<header>` with eyebrow, `<h1 lang>`, chapter `<p lang>`, a toggle button; then close button, native `<audio controls aria-label>`, status `<p role="status" aria-live="polite">`, `.player-options` grid (3 columns, 2 on mobile), chapter list `<ol class="unit-list">` with `aria-current="true"` on the playing item (`player.tsx:405-548`, `app.css:36`).
- [ ] Panel look comes from the shared paper-card rule (`room.css:312` list includes `.player-panel`), and `.player-mini` shrinks the header (`app.css:36`). Native `<audio controls>` is the only transport control. Anything custom must sit beside it, not replace it, unless a task says so.
- [ ] Select-style options use `<label>text<select>` with the label as the visible name (`player.tsx:497-530`).
- [ ] Status messages: `<p role="status" aria-live="polite">` for transient text, `.notice` box for blocking or conflict states, `.error-notice` for errors (`room.css:310` colours). A `role="alert"` notice gets a gold left border (`app.css:35`).
- [ ] Mobile dock: `#persistent-media` sits at `left:12px;right:12px;bottom:76px;max-height:70dvh` under 760 px (`app.css:25`). It is laid out to clear the old bottom `side-nav`, which `room.css` no longer renders. Check the 76 px offset when changing dock height.

## 5. Dialog and sheet pattern

There is one pattern, and it is a centred modal, not a bottom sheet.

- [ ] Wrapper: `MediaSheet` in `client/media-sheets.tsx:5-33` renders a native `<dialog className="maison-dialog media-sheet" aria-labelledby>` opened with `showModal()` and closed with `.close()`.
- [ ] Heading row: `<div className="dialog-heading"><h2 id={titleId}>…</h2><button type="button">{t("close")}</button></div>` (`media-sheets.tsx:31`). A text Close button, not an icon, and no backdrop-click dismissal is coded.
- [ ] Focus: stores `document.activeElement` before `showModal()` and restores it on close and on unmount (`media-sheets.tsx:9-27`). Native `<dialog>` supplies the focus trap, Esc handling and inert background. No manual trap is written.
- [ ] Navigation: closes on the `maison:before-navigate` window event (`media-sheets.tsx:26-29`, fired from `client/navigation.ts:77`).
- [ ] Body order: explanatory `<p>`, state (`<p className="notice">` offline, `<p role="status">` loading), primary control, then `<div className="actions">` with the secondary buttons (`media-sheets.tsx:54-61, 76-82`). `.media-sheet .actions` makes children `flex:1; min-width:150px`; they stack in a column under 767 px (`app.css:28`).
- [ ] Look: `.maison-dialog` is light ivory even on dark themes, width `min(650px, 100vw - 32px)`, `max-height:calc(100dvh - 48px)`, 10 px radius, own local variables `--ink --muted --surface --line --gold --accent` (`app.css:11`); `room.css:330` adds paper texture. `.media-sheet` caps width at 620 px (`app.css:28`).
- [ ] Reader's two other dialogs (`#reading-settings`, annotation note) hand-write the same markup and use `ref.showModal()` instead of `MediaSheet` (`reader.tsx:456, 740, 891-899, 1013-1019`). `MediaSheet` is used only by `PreviewBoundary` and `FormatSwitch`. Count: 3 files mention it (`media-sheets.tsx`, `player.tsx`, `reader.tsx`); 2 files own a raw `<dialog>` (`media-sheets.tsx`, `reader.tsx`).
- [ ] Rule for later tasks: a new Read/Listen dialog is a `MediaSheet`. Do not hand-write another `<dialog>`.
- [ ] Gap: there is no bottom-anchored sheet, drag handle or slide-in animation. `.bottom-sheet`/`.sheet-content` appear only in `typography.css` and nothing renders them. If the plan needs a bottom sheet on mobile, that is a deviation from the one existing pattern and needs a decision, not a quiet new component.
- [ ] Gap: `MediaSheet` itself has no tests (`client/*.test.*` do not import it). Behaviour above is from reading the code.

## 6. Focus styles

- [ ] Global: `a, button, input, select, textarea, summary, [tabindex]` `:focus-visible` = 3 px solid `--gold`, offset 4 px (`app.css:4`).
- [ ] Room layer: `.room :focus-visible` = 3 px solid `--wine`, offset 3 px, radius 3 px (`room.css:20`). On the dark header, footer and nav it is `--gold-on-dark` (`room.css:21`). On the carousel controls it is gold, offset -3 px (`room.css:179`).
- [ ] Form fields add a border and a soft ring on `:focus` (`room.css:306`: accent border, `outline:3px solid rgba(107,35,53,.25)`).
- [ ] Skip link: `.skip-link` jumps to `#main` (`base.html:28`, `room.css:24-25`). `<main id="main" tabindex="-1">`.
- [ ] Programmatic focus: the shared pattern is `target.focus({ preventScroll: true })` after restoring (`media-sheets.tsx:13`, `app.js:44`). Headings that receive focus on route change suppress the ring (`.onboarding-panel h1:focus{outline:none}`, `app.css:39`). Follow that pairing, and do not suppress the ring on controls.
- [ ] Gap: the `.room :focus-visible` wine ring applies on the dark `room-focused` pages (reader chrome, player dock) unless a more specific rule changes it. The only dark-surface overrides are header, footer, nav and carousel. Whether the wine ring is visible enough on `#2A1820` surfaces is not recorded anywhere. Flag for review rather than change.
- [ ] `DESIGN.md` says focus is a 3 px `--binding` ring with 2 px paper offset. That differs from the shipped offsets (3 and 4). Take the shipped CSS as the convention.

## 7. Bengali text and language marking

- [ ] The interface is English only. `<html lang="en">` and `<body lang="en">` are fixed (`base.html:2, 11`). All book text is marked by its own `lang`.
- [ ] Book text carries `lang="{{ edition.locale }}"` on each text element, server side: reader meta, `<h1 class="edition-title">`, `.reading-text` (`reader.html:4-5`); title h1, description, language name, unit links (`title.html:1`); player island h1 (`player.html:1`).
- [ ] Client side: `lang={boot.locale}` on the player h1 and chapter title (`player.tsx:413-414`), `lang={boot.content_locale}` on the annotation quote (`reader.tsx:1086`). Home, downloads and video islands do the same (8 `lang={…}` uses across 5 files). The element that holds book text gets the lang attribute, the surrounding UI does not.
- [ ] A `lang` value is the bare code `bn` or `en` (`edition.locale`). CSS matches `[lang=bn]` (`app.css:10, 20-22`; `typography.css:52`) and `:lang(bn)` (`room.css:213, 359`).
- [ ] Fonts: Bengali reading = Noto Serif Bengali, Bengali UI-style text = Noto Sans Bengali (weights 400/500/600), English reading = Source Serif 4, English UI = DM Sans. Selected by `.reading-text[lang=bn]` and the `.sans` modifier class (`app.css:20-23`).
- [ ] Line height: Bengali reading text floor is 1.8 (`line-height:max(var(--reader-leading,1.8),1.8)`, `app.css:22`); English floor is 1.5 and default 1.65. The same floors are enforced in the React preference code (`reader.tsx:154, 417, 472, 943`).
- [ ] Headings in Bengali: `letter-spacing:normal; text-transform:none; line-height:1.45-1.5` (`app.css:6`, `typography.css:56-61`). Never apply letter-spacing or uppercase to Bengali text. The `.room-kicker` and `.eyebrow` rules are upper-case with tracking (`room.css:35`, `app.css:6`) and are reset for `[lang=bn]`; the reset is keyed on `.maison[lang=bn]` (the body), which is always `en` now. So a Bengali title in an `.eyebrow` or `.room-kicker` is not protected. Put book titles in headings or `lang`-marked spans, not in kickers.
- [ ] Reader controls (`--reader-size, --reader-leading, --reader-measure, --reader-alignment`) are CSS variables set on the `.reader` element (`reader.tsx:474-491`). Reader typeface options show the font name, which depends on `content_locale` (`reader.tsx:927-932`).
- [ ] Gap: no `word-break`, `hyphens` or `font-feature-settings` is set for Bengali. No `dir` handling (no RTL language is in scope).
- [ ] Gap: the `.maison[lang=bn]` rules (`app.css:2`, `typography.css:33, 52, 56`) are effectively dead because body `lang` is always `en`. Only the element-level `[lang=bn]` and `:lang(bn)` rules work. New Bengali styling must be written against the element-level `lang`.

## 8. Reduced motion

- [ ] Two switches, one result: the OS media query `@media(prefers-reduced-motion:reduce)` and the saved preference class `body.reduced-motion` (`app.css:15`, `room.css:257-261`). The class is set from account preferences (`client/shell.ts:66`, `client/account.tsx:165, 186`, server `web/views.py:59`, `base.html:11`), with a localStorage fallback `maison.local-appearance` (`account.tsx:166`).
- [ ] The app.css rules are global: `scroll-behavior:auto`, `transition:none`, `animation:none` on `*` for both switches. Any new transition or animation in Read/Listen is therefore disabled automatically for CSS. Do not re-implement this per component.
- [ ] JavaScript motion must check both: `matchMedia("(prefers-reduced-motion: reduce)").matches || document.body.classList.contains("reduced-motion")` (`room.js:12-13`). That `still()` helper lives in `room.js`, not in shared client code.
- [ ] Reader and player scroll programmatically with `behavior: "instant"` always (`reader.tsx:180, 707, 722`), so they are motion-free by construction. Keep `instant` for new scroll calls rather than testing the preference.
- [ ] Gap: `.room-page .book-row` has a 260 ms transform transition (`room.css:324-325`); it is covered by the global `transition:none` rule only where app.css is also loaded, which it is. The hover transform `translateY(-3px)` itself is only neutralised in the OS media query (`room.css:259`), not for `.reduced-motion`. Not Read/Listen, but do not copy it.
- [ ] Gap: no shared TypeScript helper for "is motion reduced". If a later task needs one in React, that is a new piece (section 10).

## 9. Adding a UI string (web/i18n.py)

- [ ] Strings live in one dict `STRINGS` in `web/i18n.py`. Each entry is `key: (English, second)`. The module is appended to in several places with `STRINGS.update({...})` or `STRINGS["key"] = (..., ...)`; add new keys at the end of the file in the same style (`i18n.py:360-463`).
- [ ] The interface is English only: `text()` returns `values[0]` always (`i18n.py:368-370`), and the catalogue sent to the browser is the English side (`catalogue("en")`, `web/templatetags/maison.py:8`, `web/views.py:60`). The second element is not shown. Per the owner's 22 Nov instruction the second element is either the same English or a Bengali string; keep English-or-Bengali as existing entries do. Write the English first.
- [ ] Both tuple elements must be non-empty strings and the tuple must have exactly two elements (`web/tests.py:46-50`).
- [ ] Every `{% ui 'key' %}` literal in a template must exist in `STRINGS` (`web/tests.py:36-43`).
- [ ] Templates use `{% ui 'key' %}` (`maison.py` `ui` tag). React uses `t("key")` from `client/api.ts:6`, reading the JSON that `base.html:57` emits as `#ui-catalogue`. `t()` falls back to the key with underscores turned into spaces, so a missing key shows as readable but unreviewed text. Check that the key exists.
- [ ] Key naming: lower_snake_case, verb or noun phrase, matches the visible text (`close_player`, `switch_to_listen`, `playback_speed`, `sleep_timer`, `preview_end`). Reuse an existing key when the words are the same: `close`, `back`, `cancel`, `retry`, `loading`, `continue`, `save`, `complete`, `contents`, `previous_chapter`, `next_chapter`, `switch_to_read`, `switch_to_listen`, `playback_speed`, `sleep_timer`, `reader_settings`, `buffering`, `media_retry`.
- [ ] Tone of existing copy: short sentence-case labels ("Switch to Listen", "Close player", "Playback speed"); help text is a full sentence ending in a full stop; no exclamation marks, no emoji.
- [ ] Dynamic values (counts, times) are concatenated in the component around a `t()` label (`player.tsx:526` `{m} {t("minutes")}`, `reader.tsx` `{t("page")} {pages.current} / {pages.total}`). There is no interpolation helper and no plural helper. Write labels so they read correctly with the number outside.
- [ ] Gap: `client/onboarding.tsx` uses a local `say(english, bengali)` helper with inline strings instead of the catalogue. It is not the pattern for Read/Listen.

## 10. Other conventions that affect Read/Listen

- [ ] Page holder for Read: `<div class="focus-toolbar">` (back link, edition title `<span lang>`, settings button) then `<article class="reader reader-paper">` (`reader.html:3-4`). The room-evening header above it already shows back link, title and mini logo (`base.html:29-33`), so the toolbar's back link and the header back link are two back controls on the same page. Do not add a third.
- [ ] Page holder for Listen: no toolbar, just a back link and the island (`player.html:1`).
- [ ] Reader chrome buttons: `reader-actions` row (annotate, use local, complete), `reader-page-controls` (back, `<output>` page status, continue), `unit-navigation` (previous/next chapter links, switch button) (`reader.tsx:669-731`). Page status uses `<output>` and is not a live region by itself.
- [ ] Save state strings go in `<p className="save-status">` with `role="status"` (`reader.tsx:786`, `app.css:10`).
- [ ] Loading: plain `<p>{t("loading")}</p>` or `<p role="status">` text. There is no spinner or skeleton component in `client/` (grep: no `spinner`/`skeleton`). Do not add one without a decision.
- [ ] Offline: a `navigator.onLine` listener with a `.notice` message in the sheet (`media-sheets.tsx:36-41, 66-70`). The page-level offline banner is `#connection-status` (`base.html:45`, `room.css:19`).
- [ ] Logo: `static/maison/logo.png` is never altered or filtered (shared rule).

## 11. Decisions to settle before the later tasks use them

1. Bottom sheet on mobile versus the existing centred `MediaSheet`: the code has only the second. Default for later tasks: reuse `MediaSheet`.
2. React icon button: no instance exists. Default: a 44 x 44 `button` with `aria-label={t(...)}` and `<svg aria-hidden="true"><use href="#i-..."/></svg>`, styled like `.turn-btn`. Ask the controller before creating a shared component for it.
3. Reduced-motion helper for React: none exists. Default: use CSS only and `behavior:"instant"` for scroll.
4. Whether the wine focus ring is acceptable on dark `room-focused` surfaces (not measured).

## 12. Per-task review lines (copy into each reviewer prompt)

- Colours and fills use variables from section 1, not new hex values.
- Spacing and radii match section 2; new mobile rule uses 767 px.
- Every button is at least 44 px high, primary and submit are 48 px; icon-only buttons are 44 x 44 and have `aria-label`.
- New dialogs are `MediaSheet`; focus returns to the trigger; text Close button in the heading row.
- Focus ring is not suppressed on any control.
- Book text sits in an element with its own `lang`; no tracking or upper-case on Bengali; Bengali line height is at least 1.8.
- No new animation outside CSS covered by the global reduced-motion rule; scrolling is `instant`.
- New strings are added in `web/i18n.py` as two-element tuples, with the English first; existing keys are reused where the words match; `t()` or `{% ui %}` is used, not inline text.
- Both `app.css` and `room.css` were checked for a rule that overrides the new one.
- `static/maison/logo.png` is untouched.

## What was read

Files opened: `AGENTS.md` (via context), `DESIGN.md` (head), `client/player.tsx` (parts), `client/reader.tsx` (parts), `client/media-sheets.tsx` (whole), `client/api.ts` (parts), `client/lifecycle.ts` (parts), `templates/web/base.html`, `title.html`, `reader.html`, `player.html`, `static/maison/app.css`, `static/maison/room/room.css` (parts), `static/maison/room/room.js`, `static/maison/fonts/typography.css` (parts), `web/i18n.py` (parts), `web/tests.py` (parts), `web/test_english_interface.py` (head). About 20 files opened and 21 searches run. Those counts are estimates. No file in the plugin skill folder (`words.md`, `checklist.md`) or other sub-skills was opened. Values, conventions, decisions and accessibility skills were not invoked: the checklist records what the project does and does not measure against a standard.
