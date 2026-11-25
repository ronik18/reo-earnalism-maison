# Earnalism Phases 1–9: completion plan (Claude-doable work)

**Spec:** `docs/superpowers/specs/2026-11-25-earnalism-revenue-phases-5-9-design.md` (decisions D1–D11) and `plans/pending/earnalism-revenue-growth.md` (Phases 1–4, steps and acceptance criteria).
**Owner instruction (25 Nov 2026):** "Use /superpowers:subagent-driven-development to complete Phase 1-9 and apply all possible claude's /skills to achieve 100% accuracy and efficiency."

Everything here is work Claude can finish without the owner. Owner-only items stay on `docs/OWNER_TASKS.md` (Monday approvals, Colab runs, YouTube authorisation, merchant/partner/finance accounts, US/UK trigger, standing-permission date).

## Global Constraints

- Publication only for editions whose owner-approved clearance record covers the exact source hash, every active region (IN, US, GB, BR, SG, MY, ID, PH, TH) and the offered format/action. Packets built here stay `DRAFT_PENDING_OWNER_APPROVAL` and are queued on the Monday review page; nothing is published by these tasks.
- Text intake only from Wikisource pages proofread at level 4 in a printing from 1930 or earlier; a level-0 ("without text") page may be left out of a range only when it carries no story text, and the source record says so. The converter fails closed; extend it only with a test and only for markup actually seen, and every earlier packet must still convert byte-identically.
- Covers: the owner's existing Cloudinary covers (`earnalism/covers/front/cover_<uuid>` with `earnalism/covers/back/back_cover_<uuid>`) through `intake_cover`.
- AI translations are labelled "AI translation" (method `ai`, model id recorded); the Bengali original is never altered.
- No paid calls beyond the owner's existing plans, no new services, no third-party trackers, no student accounts.
- English-only UI chrome is an owner decision (docs/UNIFIED_READER_JOURNEY.md); book text keeps its own language.
- Tests run on PostgreSQL: `MAISON_ENV=test DATABASE_URL='postgres://maison@127.0.0.1:55433/maison?sslmode=disable' .venv/bin/python manage.py test <labels> --noinput`, with a distinct `MAISON_TEST_DB_NAME` per run. The two PostgreSQL-major-version checks fail locally (PG16; CI runs PG18) and are expected.
- `skills/earnalism-audiovisual` and `.agents/skills/earnalism-audiovisual` stay byte-identical.

---

### Task 1: Early-edition packets for সুভা, খাতা, স্ত্রীর পত্র, একরাত্রি, হৈমন্তী

**Goal:** for each story, find a Bengali Wikisource transcription inside a scanned book printed in 1930 or earlier whose story pages are all proofread level 4; build an intake packet (`intake_wikisource --write`) and attach the owner's cover pair (`intake_cover`). Re-check পোস্টমাস্টার, ছুটি and কাবুলিওয়ালা for an earlier printing than the 1946 one.

**Covers (owner Cloudinary front ids; back is `earnalism/covers/back/back_cover_<same uuid>`):**
- সুভা: `earnalism/covers/front/cover_c528045d-56b1-4f5d-a768-59c6219ec2b8`
- খাতা: `earnalism/covers/front/cover_8dfc862e-b8c9-41e7-8d6c-4729f97806bd`
- স্ত্রীর পত্র: `earnalism/covers/front/cover_987ce2c8-de6d-408a-9d13-7a1063e44130`
- একরাত্রি: `earnalism/covers/front/cover_6ef80d34-2cc1-4aa6-80a0-aa350f674d7a`
- হৈমন্তী: `earnalism/covers/front/cover_478ccb3c-fc60-45ad-b356-6f319c4e59cb`
- পোস্টমাস্টার: `earnalism/covers/front/cover_14fff76d-4f51-4932-92e4-f0d2487e90ad`; কাবুলিওয়ালা: `…/cover_b33ba9ce-28b1-462a-9721-01a012424e4c`; ছুটি: `…/cover_ec396188-08a1-49b9-b210-13b3ef99a647` (only if an eligible printing is found)

**Method:** follow how কথা-চতুষ্টয় was done: MediaWiki API (`https://bn.wikisource.org/w/api.php`, User-Agent `maison-intake/1.0`, sequential, back off on 429; `action=raw` for page text and `action=query&prop=revisions` for revision ids; batches ≤ 20 titles to avoid 414), save raw data under the scratchpad, assemble the API-shaped JSON that `intake_wikisource --api-json` reads (see `api_pages` in `operations/management/commands/intake_wikisource.py`), dry-run, then `--write`. Page-end hyphens rejoin unless the compound is attested mid-line in the same printing. Write a one-line Bengali description per title in the house style of existing manifests (no spoilers). `--first-published` is the printing year; `--source-edition` names the book, place, publisher/printer, year (BS and CE), scan page range and any conversion notes; `--source-ref` is the story page URL with `&oldid=`.

**Output:** packets under `library/intake/<slug>/`, drafts `docs/evidence/publication-clearance-<slug>-draft.json`, and a survey report `docs/evidence/early-edition-survey-20261125.json` listing every title as `packaged` or `hold` with the reason. Titles without an eligible printing are reported, never forced.

**Verify:** `operations.test_intake_wikisource operations.test_queue_intake_packets` pass; every earlier packet still converts byte-identically.

### Task 2: ক্ষুধিত পাষাণ stills and music Colab jobs

**Goal:** mirror বিচারক's film preparation for `production/audiovisual/kshudhita-pashan/`: `specs/world-bible.json`, `specs/stills-film-01.json` (keyframes for all 36 planned scenes, keyed `<scene_id>-<k>`), `specs/music-film-01.json`, then `eav job stills` and `eav job music` within the title's remaining 55.76 CU; update `RUN_SHEET.md` to list all three jobs in বিচারক's format.

**Rules:** read `skills/earnalism-audiovisual/SKILL.md` and `references/film-recipe.md` first; templates are `production/audiovisual/bicharak/specs/{world-bible,stills-film-01-r2,music-film-01}.json` and `production/audiovisual/bicharak/RUN_SHEET.md`. Respectful depiction: no nudity (the palace bathing scenes are shown through architecture, water, light and garments only), no gore. Never lower quality or split a job to fit the budget; stop and report instead.

**Verify:** eav tests pass; ledger totals stay within the 60 CU title cap.

### Task 3: ক্ষুধিত পাষাণ companion reading track

**Goal:** a `learning/intake/kshudhita-pashan-companion.json` track in the exact schema and voice of `learning/intake/bicharak-companion.json` (`earnalism.learning_track.v1`, Bengali, free, about 4 days, original lesson text written for Earnalism, quizzes whose answers are checkable against the published text), importable by the same command that imported the বিচারক track.

**Verify:** the learning import command's dry run and the `learning` tests pass; a worksheet PDF renders for the new track (`learning/worksheet.py`).

### Task 4: English AI translation of ক্ষুধিত পাষাণ

**Goal:** an English edition `kshudhita-pashan-en` ("The Hungry Stones" is a later, copyrighted-era title choice by other translators; use a neutral title such as "The Hungry Stone") produced in-session as a faithful, readable English translation of the exact published Bengali text, one English paragraph per Bengali paragraph in the same order and kinds, then packaged with `intake_translation --from kshudhita-pashan --method ai --model <model id>` and queued for the Monday page. Label: AI translation.

**Verify:** paragraph count and kinds match the Bengali source 1:1; `operations.test_intake_translation` (or the command's tests) pass; the clearance draft is `DRAFT_PENDING_OWNER_APPROVAL`.

### Task 5: Parallel bilingual read-along (Step 3.2)

**Goal:** per Step 3.2's acceptance criteria: a Reader toggle shows the Bengali and English paragraph pairs side by side (stacked on mobile), for an edition that has a published translation pair (`Edition.translated_from`); accessible markup; approved typography preserved; Pass gating follows Step 3.1 (free while `MAISON_FREE_ACCESS` is on). Pairs align by paragraph ordinal within the matching unit; if the pair's structure differs, the toggle is not offered.

**Verify:** `npm run check && npm run build`, then `web library` tests; browser check of the toggle on desktop and mobile with a local fixture pair.

### Task 6: Records

**Goal:** update `plans/pending/earnalism-revenue-growth.md` Progress, `docs/OWNER_TASKS.md` and the release record with what Tasks 1–5 delivered and what remains owner-only.
