# Read and Listen Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the owner-approved Listen player and Read reader changes (spec sections 9 and 10), and let Maison accept the new audiobook bundle (64 kbps mono, chapters, sentence timing) so the audiobook can reach readers.

**Architecture:**
- **Backend:** the media lane widens the 48/96 kbps gates to admit 64. The importer stores `chapters` and sentence-precision `TimingMap` rows, which the existing `/content/mappings` endpoint exposes.
- **Frontend:** the frontend lane changes `client/player.tsx`, `client/reader.tsx`, `client/media-sheets.tsx` and their templates, and talks to the backend only through existing endpoints plus the additive contract fields.
- **Contracts:** root reconciles `contracts/openapi.yaml`.

**Tech Stack:** Django + PostgreSQL 18 (`python manage.py test`, Django unittest runner); TypeScript/Preact islands bundled by esbuild (`npm run check` = `tsc --noEmit` + `node:test`); Playwright for browser checks.

**Spec:** `docs/superpowers/specs/2026-11-27-earnalism-cinematic-film-design.md` §9 (Listen) and §10 (Read), approved by the owner on 27 Nov 2026 as a separate plan ("Approve now, separate plan"). Also `docs/interface-notes/2026-11-27-audio-bundle-sentences-chapters.md`, the bundle contract change produced by the skill.

## Global Constraints

- **Lanes (AGENTS.md):**
  - frontend: `client/`, `web/`, `templates/`, `static/`;
  - backend: `accounts/`, `reader/`, `core/`;
  - media: `library/`, `billing/`, `learning/`;
  - root: `contracts/`, `operations/`, docs.

  A task edits only its own lane's files plus its own tests. A change to another lane's interface goes through the contract in Task 1 first.
- **Tests:**
  - Python: `MAISON_ENV=test MAISON_TEST_DB_NAME=maison_test_<task> python manage.py test <labels>`. Use a distinct DB name per task, on PostgreSQL.
  - Client: `npm run check`.
  - CI also runs `python manage.py makemigrations --check --dry-run`; it must stay clean after each task's migration is committed.
- **Interface language:** the interface stays English-only (owner direction, 22 Nov 2026; `web/test_english_interface.py` must keep passing). Book text, titles and `lang` attributes keep the book's language.
- **Logo:** protect the official logo pixels (AGENTS.md). Never recolour, filter or re-encode `static/maison/logo.png`.
- **Old bundles:** existing paragraph-precision timing and 48/96 kbps renditions keep working unchanged.
- **Product copy, exactly:**
  - Preview ending: `Sign in free to finish {title} — your place is kept`.
  - Coming-soon label: `Coming soon`.
- **Touch targets:** at least 44 × 44 CSS px. Respect `prefers-reduced-motion`. Keyboard and screen-reader access is preserved for every hidden or animated control.
- **Spend:** no new paid services or providers.

## Rulings made while planning (spec silent or in conflict)

1. **Bengali labels and digits.** §9 asks for "Bengali labels and digits in the Bengali UI". There is no Bengali UI (owner direction, 22 Nov), so this item is not applicable. Durations shown next to Bengali book text stay in the English interface's digits. Cost if wrong: one small follow-up if a Bengali UI returns.
2. **"The logo dims in dark themes" (§10.1) conflicts with protecting the logo pixels.** In a dark header the logo is shown unaltered on its own small ivory plate (the reading-room design's logo rule). The header around it goes dark. Cost if wrong: the logo reads brighter than "dimmed".
3. **Listener audio-quality preference stays `[48, 96]`.** A unit with only a 64 kbps rendition plays that rendition whatever the preference. Grants and prepared-audio checks admit 64. Cost if wrong: a 64 option has to be added to preferences later.
4. **Night first (§10.1).** Night first means the system dark setting picks the reader's starting theme only when the reader has no saved theme. A saved choice (account or localStorage) always wins. Cost if wrong: none for existing readers.
5. **Text-follow highlighting (§9) lives in the reader.** When the persistent player is playing the same edition, the reader highlights the current sentence. With only paragraph timing it highlights the paragraph. The player page gets a "Follow in text" link. Cost if wrong: no follow-along on the player page itself.
6. **Funnel analytics are not in §9–10.** They stay out of this plan and need a separate owner decision.

## Review Focus

1. A reader who saved Light (or Sepia) must not be switched to dark by the system setting (ruling 4). Test: Task 7.
2. An old bundle with no `chapters`/`sentences` and 96 kbps renditions must import, play and seek exactly as before. Test: Tasks 2 and 3.
3. A unit whose sentences were left unmeasured (`sentences_unmeasured`) must fall back to paragraph highlighting, never to a wrong sentence. Test: Task 6.
4. The hide-on-scroll toolbar must reappear on keyboard focus and must never hide while a screen reader is focused inside it. Test: Task 8.
5. A sleep timer set to "end of part" on the last part must stop at the end, not loop or jump to the next title. Test: Task 5.

---

### Task 0: UI conventions inventory

**Files:**
- Create: `docs/superpowers/plans/2026-11-27-read-listen-ui-checklist.md`

- [ ] **Step 1:** Run the `ui-consistency:finding-patterns` skill over `client/player.tsx`, `client/reader.tsx`, `client/media-sheets.tsx`, `templates/web/{base,title,reader,player}.html` and `static/` CSS. Write the checklist: tokens, button sizes, sheet pattern, focus styles and Bengali text handling. Every later frontend task's reviewer checks against it.
- [ ] **Step 2:** Commit `docs: Read/Listen UI conventions checklist`.

### Task 1: Contract: 64 kbps, chapters, sentence timing (root)

**Files:**
- Modify: `contracts/openapi.yaml`:
  - `MediaGrantInput.quality_kbps` (~:19744), `MediaGrant.quality_kbps` (~:19824) and `AudioPreviewDescriptor.quality_kbps` (~:25166): enum `[48, 64, 96]`;
  - `TimingSegment` (~:19936): add optional `sentence_index: integer >= 0`;
  - new schema `AudioChapter {title: string, start_ms: integer >= 0}`;
  - the player chapter item gains optional `chapters: AudioChapter[]`.
- Modify: `contracts/api-contracts.md` and `contracts/payload-examples.json` to match.
- Test: `client/contracts.test.mjs`, plus the existing contract tests that validate examples against the schema.

**Interfaces:**
- Produces: the field names and shapes above, used verbatim by Tasks 2–6.

- [ ] **Step 1:** Add failing examples to `payload-examples.json`: a 64 kbps grant, a sentence-precision TimingMap with `sentence_index`, and a chapter list. Run `npm test` and the Python contract tests. Expected: FAIL on schema validation.
- [ ] **Step 2:** Edit the schema. Run the same tests. Expected: PASS.
- [ ] **Step 3:** Commit `contracts: 64 kbps renditions, audio chapters, sentence timing`.

### Task 2: Importer accepts audiobook bundles (root + media)

**Files:**
- Modify: `operations/management/commands/attach_audiovisual_audio.py`:
  - `read_bundle` (~:101–125) accepts optional `chapters`/`sentences` per row;
  - the `media_value` docstring (~:13–21, :251–256).
- Modify: `library/production_handoff.py`:
  - `measure_mp3` (:376, gate :392) admits 64000 mono;
  - proof at :493–495;
  - TimingMap at :513 writes the sentence-precision map.
- Modify: `library/models.py`: `TimingMap` (:192–210) gains `chapters = JSONField(default=list)`.
- Create: `library/migrations/0009_timingmap_chapters.py`.
- Tests: `operations/test_audiovisual_commands.py`, `library/test_production_handoff.py`.

**Interfaces:**
- Consumes: Task 1 shapes; the bundle rows from the interface note.
- Produces:
  - `TimingMap(precision="sentence", segments=[{anchor_id, sentence_index, start_ms, end_ms, start_offset_chars, end_offset_chars}], chapters=[{title, start_ms}])` per audio asset.
  - The existing paragraph map is still written. Sentence rows are written only for anchors not listed in `sentences_unmeasured`.

- [ ] **Step 1:** Write the failing tests:
  - `test_read_bundle_accepts_chapters_and_sentences`;
  - `test_read_bundle_rejects_chapters_not_increasing_or_past_duration`;
  - `test_read_bundle_rejects_sentence_index_gap_or_outside_anchor_segment`;
  - `test_measure_mp3_accepts_64k_mono`;
  - `test_old_bundle_without_new_keys_imports_unchanged` (Review Focus 2);
  - `test_sentence_map_skips_unmeasured_anchors`.
- [ ] **Step 2:** Run `MAISON_TEST_DB_NAME=maison_test_rl2 python manage.py test operations.test_audiovisual_commands library.test_production_handoff`. Expected: FAIL.
- [ ] **Step 3:** Implement. The sentence offsets come from splitting the anchor's text with the same rule as `eav.text.sentences`: split after `.`, `?`, `!` and `।`, keeping the mark with its sentence. Add a `library/sentences.py` `split_sentences(text) -> list[tuple[int, int]]` with a golden test shared with Task 6.
- [ ] **Step 4:** Run the tests again. Expected: PASS. Then run `python manage.py makemigrations --check --dry-run`. Expected: no changes.
- [ ] **Step 5:** Commit `maison: import audiobook bundles with chapters and sentence timing (64 kbps mono)`.

### Task 3: Serving 64 kbps and chapters (media)

**Files:**
- Modify: `library/services.py`:
  - `media_grant` (:534–560, check :544) and `prepared_audio` (:909–918, gate :916) admit 64;
  - `media_chapters` (:921–930) returns one entry per unit, choosing the rendition by preference, else the only one, else the nearest, and carries `chapters`.
- Modify: `library/audio_preview.py` gate (:27).
- Modify: `library/timing.py` `map_dto` (:35) to emit `sentence_index` when present.
- Tests: `library/test_media_providers.py`, `library/test_audio_preview.py`, `library/test_stream.py`.

**Interfaces:**
- Produces: player bootstrap chapters `[{asset_id, unit_id, duration_ms, sha256, quality_kbps, title, chapters: [{title, start_ms}]}]`, one per unit, not one per rendition. `/content/mappings/{revision}` returns sentence-precision maps when stored.

- [ ] **Step 1:** Write the failing tests:
  - `test_64k_only_unit_plays_for_96_preference` (ruling 3);
  - `test_media_chapters_lists_each_unit_once`;
  - `test_mappings_include_sentence_index`;
  - `test_48_96_assets_unchanged` (Review Focus 2).
- [ ] **Step 2:** Run `MAISON_TEST_DB_NAME=maison_test_rl3 python manage.py test library`. Expected: FAIL on the new tests.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit `maison: serve 64 kbps audiobooks, one part per unit, sentence timing`.

### Task 4: Player controls, speed memory and Media Session (frontend)

**Files:**
- Modify: `client/player.tsx` (`Player` :49; speed :55, :497–509; Media Session :258–297; `<audio controls>` :429–475).
- Modify: `client/state.ts`.
- Modify: `web/i18n.py` (new English strings).
- Tests: `client/state.test.ts`, `client/media-state.test.ts`.

**Interfaces:**
- Consumes: the Task 3 bootstrap.
- Produces:
  - `rememberSpeed(rate: number): void` and `recallSpeed(): number`, using localStorage key `maison.player.rate`, clamped to 0.75–2, default 1.
  - `mediaMetadataFor(boot, part): {title, artist, album, artwork}`.

- [ ] **Step 1:** Write the failing tests:
  - `test_speed_is_remembered_and_clamped`;
  - `test_media_metadata_has_author_part_and_artwork`;
  - `test_seek_back_15_forward_30_clamp_to_bounds`.
- [ ] **Step 2:** Run `npm run check`. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - on-screen −15 s and +30 s buttons, at least 44 px, with labels `Back 15 seconds` and `Forward 30 seconds`;
  - Media Session `seekbackward` = 15 s and `seekforward` = 30 s;
  - `setPositionState` on timeupdate and ratechange;
  - `previoustrack`/`nexttrack` to the adjacent part;
  - artwork from the edition cover.
- [ ] **Step 4:** Run `npm run check`. Expected: PASS.
- [ ] **Step 5:** Commit `player: skip buttons, remembered speed, full Media Session`.

### Task 5: Sleep timer, parts list, position prompt (frontend)

**Files:**
- Modify: `client/player.tsx` (timer :510–531, :245–250; parts :541–553; conflict prompt :479–493).
- Modify: `client/state.ts` (`sleepDeadline`, `timerExpired` :27, :35; `progressConflictDecision` :95).
- Tests: `client/state.test.ts`.

**Interfaces:**
- Produces: `sleepRemaining(playedMs, setAtPlayedMs, durationMs): number`. The timer is driven by playback time, not wall-clock time. `fadeGain(remainingMs): number` ramps linearly to 0 over the last 15 000 ms.

- [ ] **Step 1:** Write the failing tests:
  - `test_sleep_counts_playback_time_not_wall_time`;
  - `test_fade_is_15s_linear`;
  - `test_end_of_part_on_last_part_stops` (Review Focus 5);
  - `test_conflict_prompt_shows_both_positions` (chapter title plus mm:ss for server and device).
- [ ] **Step 2:** Run `npm run check`. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - the parts list renders one row per unit, with its `chapters` as a sub-list that seeks on click;
  - the timer option label is "End of part";
  - the fade restores the volume after stopping.
- [ ] **Step 4:** Run `npm run check`. Expected: PASS.
- [ ] **Step 5:** Commit `player: playback-time sleep timer with fade, parts and chapters, clearer position prompt`.

### Task 6: Follow-along highlighting in the reader (frontend)

**Files:**
- Modify: `client/reader.tsx`.
- Modify: `client/player.tsx` (a `Follow in text` link to the reader at the current anchor).
- Create: `client/sentences.ts` (`splitSentences(text): Array<[start, end]>`, the same rule as `library/sentences.py`).
- Tests: `client/state.test.ts` and the shared golden file `contracts/sentence-split-golden.json`, which Task 2's Python test also reads.

**Interfaces:**
- Consumes: Task 3 `/content/mappings/{revision}` and the persistent player's position event.
- Produces: `currentHighlight(maps, anchorId, ms): {anchorId, range: [start, end] | null}`. It returns `null` when only paragraph timing exists, and the whole paragraph is then highlighted.

- [ ] **Step 1:** Write the failing tests:
  - `test_split_matches_golden` (Bengali with `।`, `?`, `!`, quotes and conjuncts);
  - `test_highlight_sentence_at_time`;
  - `test_unmeasured_anchor_falls_back_to_paragraph` (Review Focus 3);
  - `test_no_autoscroll_within_5s_of_user_scroll`.
- [ ] **Step 2:** Run `npm run check`. Expected: FAIL.
- [ ] **Step 3:** Implement. The highlight uses a CSS class on a wrapping `<mark>` range, never rewriting the text nodes' content. `prefers-reduced-motion` disables smooth scroll.
- [ ] **Step 4:** Run `npm run check`. Expected: PASS. Then run `MAISON_TEST_DB_NAME=maison_test_rl6 python manage.py test library.test_production_handoff` for the shared golden. Expected: PASS.
- [ ] **Step 5:** Commit `reader: follow the narration sentence by sentence`.

### Task 7: Night first; the theme reaches the header (frontend)

**Files:**
- Modify: `client/reader.tsx` (default `reader_theme` :76–80; classes :492–494; settings read :144–160).
- Modify: `templates/web/base.html` (:11 body class, :29–34 header/logo), `templates/web/reader.html` (:3) and `static/` CSS (reader header theme rules; logo plate).
- Tests: `web/test_peacock_theme.py`, `reader/tests.py`.

**Interfaces:**
- Produces: `initialReaderTheme(saved: string | null, prefersDark: boolean): "light" | "sepia" | "dark" | "true_black"`, where a saved value wins (ruling 4). The `<body>` gets `reader-theme-<name>` on reader routes so the header follows. The logo sits in `.logo-plate`, an ivory background, with the image unaltered (ruling 2).

- [ ] **Step 1:** Write the failing tests:
  - `test_saved_light_wins_over_system_dark` (Review Focus 1);
  - `test_no_saved_theme_follows_system_dark`;
  - `test_reader_header_carries_theme_class`;
  - `test_logo_img_has_no_filter_and_same_src` (a CSS rule check that `.logo-plate img` sets no `filter`/`opacity`).
- [ ] **Step 2:** Run `npm run check` and `MAISON_TEST_DB_NAME=maison_test_rl7 python manage.py test web.test_peacock_theme reader`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same commands. Expected: PASS.
- [ ] **Step 5:** Commit `reader: night first, theme reaches the header, logo on its plate`.

### Task 8: One immersive toolbar with progress and a পরিচ্ছেদ (chapter) drawer (frontend)

**Files:**
- Modify: `templates/web/base.html` (:29–31 focused-shell Back/title) and `templates/web/reader.html` (:2 `.focus-toolbar`, :3 `.reader-meta`).
- Modify: `client/reader.tsx` (progress :696–728; unit links :669–695) and `static/` CSS.
- Tests: `reader/tests.py`, `web/tests.py`, `client/state.test.ts`.

**Interfaces:**
- Produces:
  - `progressFraction(scrollTop, scrollHeight, viewport): number`;
  - `minutesRemaining(charsLeft, charsPerMinute = 900): number`, rounded up;
  - `headingsFor(unitHtml): Array<{id, text}>`, read from the rendered `<h2>` পরিচ্ছেদ headings.

- [ ] **Step 1:** Write the failing tests:
  - `test_reader_has_single_back_and_title` (the rendered reader HTML has exactly one Back control and one title);
  - `test_toolbar_hides_on_scroll_down_shows_on_up_or_tap`;
  - `test_toolbar_shows_on_focus_within` (Review Focus 4);
  - `test_progress_hairline_2px_gold_and_minutes_remaining`;
  - `test_chapter_drawer_lists_headings_and_jumps`.
- [ ] **Step 2:** Run `npm run check` and `MAISON_TEST_DB_NAME=maison_test_rl8 python manage.py test reader web`. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - the hairline is `2px`, Maison gold token;
  - the drawer title is `Chapters`;
  - the toolbar uses `transform`, with no transition under reduced motion.
- [ ] **Step 4:** Run the same commands. Expected: PASS.
- [ ] **Step 5:** Commit `reader: one immersive toolbar, progress and chapters`.

### Task 9: Live "Reading comfort" bottom sheet (frontend)

**Files:**
- Modify: `client/reader.tsx` (settings dialog :891–1011, `saveSettings` :610–639).
- Modify: `client/media-sheets.tsx` (reuse its sheet pattern).
- Tests: `client/state.test.ts`, `accounts/tests.py` (existing preference constraints unchanged).

**Interfaces:**
- Produces: `stepFont(current, delta): 16 | 20 | 23 | 26 | 30` (the existing allowed sizes) and `alignmentOptions(locale): Array<"start" | "justify">` (justify omitted for `bn`).

- [ ] **Step 1:** Write the failing tests:
  - `test_font_stepper_walks_allowed_sizes_and_clamps`;
  - `test_justify_hidden_for_bengali`;
  - `test_changes_apply_live_and_save_debounced_500ms` (no Save button);
  - `test_width_narrow_medium_wide_map_to_55_65_72ch`.
- [ ] **Step 2:** Run `npm run check`. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - a bottom sheet titled `Reading comfort`, with A− and A+ steppers, theme swatches and Narrow/Medium/Wide;
  - signed-in readers still `PATCH /me/preferences` (debounced), and others use localStorage as now.
- [ ] **Step 4:** Run `npm run check`. Expected: PASS.
- [ ] **Step 5:** Commit `reader: live reading-comfort sheet`.

### Task 10: A preview ending that converts (frontend)

**Files:**
- Modify: `client/reader.tsx` (:889) and `client/media-sheets.tsx` (`PreviewBoundary` :37–72).
- Modify: `web/i18n.py` (:133, :227) and `web/views.py` (`sign_in_url` :253–257; the preview bootstrap supplies `remaining_minutes` and available formats).
- Tests: `web/test_free_pass.py`, `web/test_guardian_preview.py`, `library/test_free_access.py`.

**Interfaces:**
- Produces: preview bootstrap fields `remaining_minutes: int` and `formats: {listen: bool, watch: bool}`.

- [ ] **Step 1:** Write the failing tests:
  - `test_preview_end_copy_exact`: `Sign in free to finish {title} — your place is kept`, with the title in its own `lang` span;
  - `test_preview_end_shows_remaining_minutes`;
  - `test_preview_end_offers_listen_and_watch_when_available`;
  - `test_sign_in_returns_to_boundary_anchor` (existing return_to kept).
- [ ] **Step 2:** Run `MAISON_TEST_DB_NAME=maison_test_rl10 python manage.py test web library.test_free_access` and `npm run check`. Expected: FAIL.
- [ ] **Step 3:** Implement. The no-JS fallback at reader.html:5 gets the same copy.
- [ ] **Step 4:** Run the same commands. Expected: PASS.
- [ ] **Step 5:** Commit `reader: preview ending with the free sign-in path and other formats`.

### Task 11: Title page: format row, mobile primary action, length (frontend)

**Files:**
- Modify: `templates/web/title.html` (:2 actions, :3 contents) and `web/views.py` (`title` :196–223).
- Modify: `static/` CSS.
- Tests: `web/tests.py`, `web/test_room_home.py`.

**Interfaces:**
- Produces: title context `formats = [{"kind": "read" | "listen" | "film", "available": bool, "url": str | None}]` and `length = {"minutes": int, "parts": int}`.

- [ ] **Step 1:** Write the failing tests:
  - `test_title_shows_read_listen_film_row_with_coming_soon`;
  - `test_read_is_first_action_in_dom_order`;
  - `test_title_shows_length_and_parts`;
  - `test_reader_player_switch_keeps_position` (the reader's Listen/Watch switch passes the anchor through `/content/switch-position`).
- [ ] **Step 2:** Run `MAISON_TEST_DB_NAME=maison_test_rl11 python manage.py test web`. Expected: FAIL.
- [ ] **Step 3:** Implement. The row reads `Read · Listen · Film`; an unavailable format shows `Coming soon` and no link. Also add one Read/Listen/Watch switch to the reader toolbar (Task 8's toolbar, `client/reader.tsx`) that opens the other format at the current anchor through `/content/switch-position`.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5:** Commit `title page: format row, read first, length and parts`.

### Task 12: Latin-script search and `lang` on titles (media + frontend)

**Files:**
- Create: `library/romanize.py`.
- Modify: `library/search.py` (`search_editions` :57, a new stage after reviewed aliases).
- Modify: `templates/web/base.html` (:31 `lang` on `.room-evening-title`).
- Tests: `library/test_search_contract.py`, `web/tests.py`.

**Interfaces:**
- Produces: `romanize_bn(text: str) -> set[str]`, a simple Bengali→Latin scheme that yields both inherent-vowel variants. বিচারক yields `{"bicharak", "bicharok"}`. Reviewed `SearchAlias` rows still rank above it.

- [ ] **Step 1:** Write the failing tests:
  - `test_bicharak_finds_bicharak_edition`;
  - `test_bicharok_also_matches`;
  - `test_reviewed_alias_still_ranks_first`;
  - `test_header_title_has_book_lang`.
- [ ] **Step 2:** Run `MAISON_TEST_DB_NAME=maison_test_rl12 python manage.py test library.test_search_contract web`. Expected: FAIL.
- [ ] **Step 3:** Implement, matching on the romanized forms of published titles at query time. There is no new table, and no draft title is ever exposed.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5:** Commit `search: Latin-script queries find Bengali titles; book lang on header title`.

### Task 13: Browser acceptance (root)

**Files:**
- Modify: `integration_tests/` (a new `test_read_listen.py`).
- Modify: `e2e/production/accessibility.spec.mjs` (reader and player pages).

- [ ] **Step 1:** Write the browser tests:
  - one Playwright journey: title → read → preview end → sign in returns to the anchor → switch to Listen at the same place → −15/+30 → sleep timer → follow-along highlight;
  - an axe pass on the reader (all four themes) and the player.
- [ ] **Step 2:** Run `npm run build && MAISON_REQUIRE_BROWSER=1 MAISON_TEST_DB_NAME=maison_test_rl13 python manage.py test integration_tests`. Expected: PASS. Fix any regressions in the owning task's lane through that lane.
- [ ] **Step 3:** Commit `integration: Read/Listen browser acceptance`.

## After the plan

- Stage the বিচারক audiobook (`--profile audiobook`) once Tasks 1–3 are merged. Then remove the "staging needs `--profile film`" note from the skill (`skills/earnalism-audiovisual/references/publishing.md`).
- Funnel analytics (visit → preview → sign-in → finish → format switch) need a separate owner decision (ruling 6).
