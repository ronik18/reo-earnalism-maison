# Reading-room design across every Maison screen — design

Owner instruction, 22 November 2026: "Rebuild all the screens belonging to the Admin and User Journey of the Earnalism as per the Maison project and its capabilities/functionalities… once everything looks good end-to-end, commit, push and merge." The visual direction is the owner-approved final design (`docs/design/final/index.html`, Superdesign draft v8) and the carousel spec (`2026-11-22-landing-carousel-design.md`).

## Intent

One coherent product: the light handmade-paper "reading room" for discovery, account and admin screens, and a dark "evening" surface for reading, listening and watching — without changing any route, permission, data flow or island behaviour.

## Goals, non-goals, anti-goals

- Goal: every user-journey route (home, welcome, explore/search, collection, title, reader, player, video, series, learn, track, lesson, interview, question, sign-in/up, password reset/verify, vault, lists, downloads, settings, pass, checkout, legal, status/offline/region pages) renders in the new shell.
- Goal: Django admin (staff journey: login with password-purpose consent, change lists, edit forms, password change) carries the Earnalism brand in the same palette.
- Non-goal: new features, copy rewrites beyond the home page, or changes to React island logic.
- Anti-goals: breaking the CSP (no inline styles/scripts), dropping a member's saved theme or reader preferences, any regression in the existing test suites, unreadable contrast.

## Approaches considered

1. **Shared shell + token layer (chosen).** Make `web/base.html` the reading-room shell and map the existing component tokens (`--canvas`, `--surface`, `--ink`, `--line`, `--accent`, `--gold`) to the new palette, porting the few interior rules the Peacock layer owned. One change reaches every page and every island; behaviour is untouched.
2. Rewrite each template's markup to the prototype's — consistent but ~30 rewrites, high regression risk to islands and tests for no user-visible gain over (1).
3. Keep the dark Peacock shell for inner pages and only reskin home — contradicts "all screens".

## Design decisions

- Shell: ivory header plate with the cropped official logo, capsule menu (Home, Explore, Learn, Series, Vault) with gold active pill, search, Sign in / Your account, gold capsule "Start reading free" for guests; dark footer with Library / Your account / Help links (Pass, Settings, legal). Handmade paper behind every page.
- Immersive routes (`focused=True`: reader, player, video): slim dark evening bar with Back and the edition title instead of the menu; reader keeps its own Paper/Sepia/Ink/True Black themes.
- Saved theme preference: Light is the default for everyone; a member's saved Dark or True Black keeps the header plate ivory (logo rule) and switches page interiors to the evening palette.
- Admin: `admin/base_site.html` brands the header and loads `maison/room/admin.css`, which sets Django admin's colour variables to burgundy/ivory/gold on paper.
- Standalone pages (password consent, region unavailable) adopt the same stylesheet.

## Left to the builder

Exact interior spacing and per-component polish, judged from screenshots at 390 px and 1440 px.
