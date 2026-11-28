# Release record: revenue Phases 5–9 (25 Nov 2026)

- **Merged:** ronik18/reo-earnalism-maison#64, squash commit `b5dc1ba62846b86427b27ddc9865cbac8189854d`, after both `postgres-acceptance` CI runs passed (PostgreSQL 18). Local full suite: 1125 tests; only the two PostgreSQL-major-version checks fail locally (PostgreSQL 16).
- **Owner instruction:** "merge the PR once CI is green" and "deploy the merged changes to production" (25 Nov 2026).
- **Database restore point (before migrations):** Neon project `quiet-cloud-63128335`, branch `br-nameless-rain-aok6bsea`, `2026-11-25T07:23:07.027Z`, WAL LSN `0/56C4130`, 72 applied migrations.
- **Migrations applied** by a Render pre-deploy command (`env MAISON_DATABASE_ROLE=direct python manage.py migrate --noinput`) at 07:23:48Z: billing 0012_revenue_ledger, 0013_institution_invoices, 0014_revenue_honesty; learning 0006_track_sponsor; library 0008_edition_translation; operations 0002_review_item. The pre-deploy command was removed afterwards.
- **Render deploy:** service `srv-dbunbd8jo6nc73akbng0`, deploy `dep-dc38pojrjlhs73f62c9g`, commit `b5dc1ba`, live at 07:24:12Z. It also carries the ক্ষুধিত পাষাণ packet merged in #63.
- **Static assets:** unchanged (no client/static changes); `STATIC_RELEASE_ID` kept.
- **New settings:** none set in production. `MAISON_REINVEST_SHARE_PERCENT` defaults to 30; `MAISON_REVIEW_STANDING_FROM` unset (standing permission off); `MAISON_SOCIAL_JOURNAL_DIR` default.
- **Live checks (theearnalism.com):** `/en/`, `/en/pass/`, `/en/explore/`, `/en/sign-in/` return 200; `/podcast/en.xml` and `/podcast/bn.xml` return 200 `application/rss+xml`, valid and empty (no title has cleared free audio yet); `/podcast/xx.xml` 404; `/en/staff/review/` 404 for anonymous visitors; the Pass page shows no founding offer (free access on, plans not created).
- **Nothing published, posted, uploaded or charged.** Founding plans not created; no review items; no store, podcast directory or licensing submission.

## Follow-up deploys (25 Nov 2026)

- **#65** (squash `fd4e61d`): eight Galpa-Dashak intake packets with draft clearance, converter extensions, `queue_intake_packets`, podcast preview enclosures (D10), `eav preview`. No migrations, no static change. Render deploy `dep-dc398e2fngtc73dbh7rg` live at 07:55:18Z. The first `queue_intake_packets` job queued only the 5 cover items: `.dockerignore` excluded the per-title clearance records from the image.
- **#66** (squash `f2f9ec6`): ship `docs/evidence/publication-clearance-*.json` in the image. Deploy live at 08:11:56Z; `/en/` and `/podcast/en.xml` 200, `/en/staff/review/` 404 anonymous.
- **Render job** `job-dc39gl68bjmc73f1kgf0` (`python manage.py queue_intake_packets`) succeeded at 08:12Z. Production review queue now holds 8 pending clearance items (nishithe, prayashchitta, apad, didi, thakurda, manbhanjan, pratihingsa, atithi) and 5 pending cover items (nishithe, didi, manbhanjan, atithi, kshudhita-pashan; the last is already approved in its clearance file). Nothing approved, imported or published.

## ক্ষুধিত পাষাণ draft import (25 Nov 2026)

- **Owner instruction:** "yes, import ক্ষুধিত পাষাণ as a draft".
- **Render job** `job-dc3c3ptg1s2s73d2hlg0` (`publish_cleared_editions import --book kshudhita-pashan`): edition `54f37caa-050b-47c3-95c2-3cbc214d6485`, revision `3cb6a0b9-f774-4822-92e7-d4fc99de2ef4` (state draft, no live revision), 1 unit, 2 cover assets, 1-entry preview (1,084 characters). Public title page 404, absent from explore.
- **Render job** `job-dc3c63afngtc73djhml0` (`publish_cleared_editions evidence --book kshudhita-pashan`): recorded the owner-approved clearance (`docs/evidence/publication-clearance-kshudhita-pashan.json`) on the draft revision so the audiovisual export carries public-domain evidence. No browser report; revision still draft, not published.
- **Render job** `job-dc3c6aafngtc73dji8d0` (read-only `export_audiovisual_source`): content_sha256 `5fe217851a7caa946d7e03890f03083d17377e62d94145873e6c38113db2949e`, 59 paragraphs, public_domain_evidence true.
- **Narration job** `narration-9187e43e` built with `eav` under `production/audiovisual/kshudhita-pashan/`: forecast 4.24 CU reserved, 55.76 CU left under the title cap. Inert until the owner runs it in Colab.

## #67 deploy (25 Nov 2026)

- **Owner instruction:** "yes, create the PR, merge and deploy once CI is green".
- **Merged:** ronik18/reo-earnalism-maison#67 after `postgres-acceptance` passed on head `f3f08a5`; squash commit `0a20d12d86927a9ed011a52431f621e5c67d405e`.
- **Restore point (before migration):** `2026-11-25T18:44:19Z`, WAL LSN `0/5AA7070`, 78 applied migrations; `maison_revenue_entry` held 0 rows, so the new constraint had nothing to reject.
- **Migration:** billing `0015_revenue_amount_positive` applied by the Render pre-deploy command at 18:55:28Z; the pre-deploy command was removed afterwards.
- **Render deploy** `dep-dc3itr95efls73c0hcp0` (commit `0a20d12`) live at 18:55:54Z. No static change; `STATIC_RELEASE_ID` kept.
- **Render job** `job-dc3j3vsipgvc738q56ag` (`queue_intake_packets`) succeeded: 6 new pending review items, a clearance and a cover each for মধ্যবর্ত্তিনী, শাস্তি and সমাপ্তি. No duplicate cover item for ক্ষুধিত পাষাণ.
- **Live checks:** `/en/`, `/en/explore/`, `/en/pass/`, `/podcast/en.xml` 200; `/en/staff/review/` 404 for anonymous visitors. Nothing published, posted or charged.

## #68 deploy and ক্ষুধিত পাষাণ publication (25 Nov 2026)

- **Owner instructions:** "a, add the footnote style for মেঘ ও রৌদ্র"; "yes, create the PR, merge and deploy once CI is green"; "Publish all titles which are ready."
- **Merged:** ronik18/reo-earnalism-maison#68 after both `postgres-acceptance` runs passed on head `f46cd0c`; squash commit `303d5aa51d717f3fe92be82c59e6c6a44ae3d8b0`.
- **Static release:**
  - Prepared from a clean frontend build: `ec6edfb364504cd0884a4b2fc49d9bf9c793d857fb2e4c8fe4e13cafd3048ab8`, 212 files, 9,354,336 bytes.
  - Compared with the live release `ceab4d26…`: 209 files byte-identical. Only `maison/app.css`, `maison/dist/manifest.json` and the new `maison/dist/downloads-M3PRRHIR.js` differ.
  - Uploaded under the new prefix through the Cloudflare R2 object API (212 × 200), then verified over public HTTPS: SHA-256, length, `Content-Type` and immutable `Cache-Control` match for 212 of 212.
  - Render `STATIC_RELEASE_ID` switched. Rollback: set it back to `ceab4d2603c2df9fd646b85fcfd258c83adfc4ebdc379580c6204b7812d87ec3` and redeploy.
- **Restore point (before migration):** `2026-11-25T19:27:00Z`, WAL LSN `0/5ADFAA8`, 79 applied migrations.
- **Migration:** library `0009_paragraph_note` (choices only) applied by the pre-deploy command at 19:27:44Z; the pre-deploy command was removed afterwards.
- **Render deploy:** `dep-dc3jd2e1egvs73dq8ih0` (commit `303d5aa`), live at 19:28:22Z. The live `app.css` carries the footnote rule.
- **ক্ষুধিত পাষাণ:**
  - Render job `job-dc3jdoeq1p3s73bcnno0` recorded the browser acceptance report (`docs/evidence/publication-browser-20261125-kshudhita-pashan.json`) on the draft.
  - Render job `job-dc3je2eq1p3s73bcoiog` published it: revision `3cb6a0b9-f774-4822-92e7-d4fc99de2ef4` live at 19:29:32Z.
  - Title page 200 and listed on Explore; the reader asks anonymous visitors to sign in (302).
- **Render job** `job-dc3jeaafngtc73a1bvpg` (`queue_intake_packets`): 2 new pending items, the clearance and cover for মেঘ ও রৌদ্র.

## #69 deploy (25 Nov 2026)

- **Merged:** ronik18/reo-earnalism-maison#69 after CI passed on head `9b3c84e`; merge commit `c5326ab`.
- **Render deploy:** `dep-dc3jnjp7lnhs73du2o0g` live at 19:50:22Z. No migrations and no static change.
- **Render job** `job-dc3jnvmi0phs73fkvb20` (`queue_intake_packets`): 4 cover items pending for আপদ, প্রতিহিংসা, প্রায়শ্চিত্ত and ঠাকুর্দ্দা.
- **Live checks:** `/en/`, `/en/explore/`, `/podcast/en.xml` 200; `/en/staff/review/` 404 for anonymous visitors. Nothing published, posted or charged.

## #70 and #71 deploys (26 Nov 2026)

- **#70** (squash `f2b50ff`): side-by-side reader, The Hungry Stone packet and cover, ক্ষুধিত পাষাণ companion track and film jobs, early-edition survey, and the 12 pipeline titles' replica browser reports.
  - **Static release:** `603e33a086435db6e0dc29f67016c9f2a8c77333af4818d37e32311221e05694`, 212 files, prepared from a clean build. Against the live release `ec6edfb3…`, 209 files are byte-identical; `app.css`, `dist/manifest.json` and the new `reader-7RBB3LF4.js` differ. Uploaded to R2 (212 × 200) and verified over public HTTPS (212/212).
  - **Switch and deploy:** `STATIC_RELEASE_ID` switched; deploy `dep-dc3r0oec6qcc73blibl0` live at 04:07:44Z. No migrations. Rollback: set `STATIC_RELEASE_ID` back to `ec6edfb364504cd0884a4b2fc49d9bf9c793d857fb2e4c8fe4e13cafd3048ab8` and redeploy.
  - **Render job `job-dc3r17p7lnhs73eis7cg`:** `publish_learning_track kshudhita-pashan-companion` succeeded; `/en/learn/` lists it.
  - **Render job `job-dc3r1d17lnhs73eisle0`:** `queue_intake_packets` succeeded, adding The Hungry Stone's review items.
  - **Live checks:** `/en/`, `/en/explore/`, `/en/learn/`, the ক্ষুধিত পাষাণ title page and `/podcast/en.xml` return 200; `/en/staff/review/` returns 404 for anonymous visitors. Pages load the new static release.
- **#71** (squash `84eb5cb`): narration Colab jobs for the 12 pipeline titles (64.70 CU; month 80.70/100) and the run sheet `production/audiovisual/RUN_SHEET-pipeline-narration.md`.
  - **Deploy:** `dep-dc3r7lff3r2c739f758g` live at 04:22:28Z.
  - **Live checks:** pages return 200, and the run sheet is reachable on `main`.
- **Not published:** The Hungry Stone and the 12 titles wait for the owner's Monday-page approval.

## Monday review access (26 Nov 2026)

- **Symptom:** the owner reported that `/en/staff/review/` showed "We could not find that page". The page returns 404 unless the user is signed in, active, staff, verified and holds `operations.decide_review`. Neither production staff account (#1, #4) held that permission, and neither is a superuser.
- **Owner choice:** grant it to account #4 (the company-domain staff account).
- **Change:** one row inserted into `auth_user_user_permissions` (user 4, permission `operations.decide_review`, id 300). It is idempotent and was verified afterwards: active, staff, verified, can_review = true. No other account or permission changed.
- **#73** (squash `c9d171d`): the Monday review page now sends signed-out visitors to sign-in and shows a 403 naming the account when it lacks review access. Deploy `dep-dc3tg8bl550s73fi7smg` live at 06:57:20Z. Anonymous `/en/staff/review/` now returns 302 to `/en/sign-in/?return_to=%2Fen%2Fstaff%2Freview%2F`; `/en/` and `/en/explore/` return 200.

## 13 titles published (26 Nov 2026)

- **Owner approval:** on the Monday page the owner approved 28 items: clearance and cover for each of the 12 pipeline titles, plus clearance, cover and the AI-translation label for The Hungry Stone. Claude recorded no approval.
- **Render jobs:** 39 jobs, all succeeded (import, then `evidence --browser-report docs/evidence/publication-browser-20261126-<slug>.json`, then `publish`) for nishithe, didi, manbhanjan, atithi, madhyabartini, shasti, samapti, megh-o-roudra, prayashchitta, apad, thakurda, pratihingsa and kshudhita-pashan-en. Run log: `job-dc3thmd6e07s73di2fdg` through `job-dc3tq0nf3r2c739mioa0`.
- **Neon:** all 13 editions have a live revision; the IDs match the deterministic replica IDs in the browser reports. `kshudhita-pashan-en` (`793553c3-b137-481d-9d27-8aa309a9373e`) has `translated_from` = ক্ষুধিত পাষাণ (`54f37caa-050b-47c3-95c2-3cbc214d6485`), which makes the side-by-side pair.
- **Live checks:** each title page returns 200, and each reader returns 200 after the redirect to its first chapter, showing the free preview to anonymous visitors. Full-text rendering, the মেঘ ও রৌদ্র footnote and the side-by-side toggle were verified signed in on the release-code replica before publishing (the browser reports above). No production test account was created for a signed-in recheck.
- Nothing posted or charged.

## #74 deploy (26 Nov 2026): live-site quality, covers, preview, Modal GPU runner

- **Merged:** ronik18/reo-earnalism-maison#74, squashed as `aa0c258`, after CI passed on head `90aa06b`. The CI timeout was raised from 12 to 25 minutes because the suite outgrew it.
- **Static release `6cff6d6c6eb137d393a49de203d4de75d7454ca93d0ebe771676f08c5898e2c2`:**
  - 212 files from a clean build.
  - Against the live release `603e33a0…`, only 3 files changed: `dist/manifest.json`, the reader bundle and `room/room.css`.
  - Uploaded to R2 (212 × 200) and verified over HTTPS (212/212).
  - Rollback: set `STATIC_RELEASE_ID` back to `603e33a086435db6e0dc29f67016c9f2a8c77333af4818d37e32311221e05694` and redeploy.
- **Deploy:** `dep-dc4a4au1egvs73fpltrg` is live.
  - Migration `library/0010` (help text only) was applied by Render job `job-dc4a4up7lnhs73fra6e0`, which succeeded. Setting a pre-deploy command through the API did not persist, so the migration ran as this job.
- **Cloudflare cache rule added**, as part of the owner's 26 Nov cover decision ("Maison public cover renditions"):
  - It covers `/api/v1/content/covers/*` with no query string, anonymous GET/HEAD requests, and the 9 whitelist countries.
  - Edge lifetime follows the origin headers, which are capped by rights.
  - Verified: the first request was a MISS and later ones HIT; a request with a query string returned 404 and was not cached; pages are still DYNAMIC.
- **Live checks:**
  - These return 200: `/en/`, `/en/explore/`, `/en/learn/`, `/sitemap.xml` (19 URLs) and `/robots.txt`. The robots file includes the Sitemap line, which Cloudflare's managed robots file merges in. `/favicon.ico` redirects to the logo.
  - Title pages carry a unique `<title>`, a UUID canonical and an `og:image` pointing at the w800 cover.
  - The w160 cover is 9.5 KB, against 172 KB for the original, and is served with `public, max-age=31536000, immutable` (capped by rights).
  - The anonymous বিচারক preview is about 550 words of about 1,988.
- **Owner decisions applied (26 Nov):**
  - covers cached and served in smaller sizes;
  - the preview is about a quarter of each story (400 to 1,500 words, never the protected end);
  - the duplicate Back link is removed (merged with W4 once the colours are approved).
- **Held for the owner:** the gold button colours (W4 is ready on its branch, with before/after screenshots sent) and the বিচারক narration listening review.

## #75 deploy (27 Nov 2026): lighter home hero, 44 px tap boxes, reader descriptions

- **Merge:** ronik18/reo-earnalism-maison#75, squash commit `7d98366`, merged after CI passed on head `c1d5e05`.
- **Static release `864a29c6e590bf096d29cfd4436a9460a24337c3dc034bf6cb56802c0a2059bc`:** 222 files, uploaded and verified (222/222). Against `6cff6d6c…` it adds 10 hero renditions and changes `asset-manifest.json` and `room.css`. To roll back, set `STATIC_RELEASE_ID` to `6cff6d6c6eb137d393a49de203d4de75d7454ca93d0ebe771676f08c5898e2c2` and redeploy.
- **Deploy:** `dep-dc4g6es9v7es73es5440` is live. No migrations.
- **Live measurement** (Chromium, CDP encodedDataLength, first load of `/en/`): mobile 390×844 is 1,004 KB (was about 3.8 MB) and loads `hero-480.avif`; desktop 1440×900 is 1,122 KB and loads `hero-640.avif`. No console errors and no horizontal overflow.
- **Still waiting on the owner:** gold button colours (W4), the site icon and share card (W6, previews sent), and the বিচারক narration listening review.

## #76 deploy (27 Nov 2026): ক্ষুধিত পাষাণ correction prepared, reader-state remap on revise

- **Merge:** ronik18/reo-earnalism-maison#76, squash commit `f4c28dd`, merged after CI passed on head `c62642b`.
- **Deploy:** `dep-dc4k8mlg1s2s73eomkhg` is live. No migrations, no static change, so the static release stays the same.
- **Render job** `job-dc4kb2vf3r2c73bn18vg` (`queue_intake_packets --slug kshudhita-pashan`) succeeded at 08:56Z. The draft clearance for the corrected text (two scan-verified insertions of " না") is pending on the Monday page. Nothing is approved, revised or published.
- **After the owner approves it:** run `publish_cleared_editions revise`, then the browser acceptance check, then `evidence` and `publish`. Reader positions, notes, highlights and bookmarks move to the corrected revision in the same transaction.

## #77 deploy (27 Nov 2026): wider side-by-side reader, one Back link, track sign-in redirect

- **Merge:** ronik18/reo-earnalism-maison#77, squash commit `24ae17d`, merged after CI passed on head `6f0bf75`.
- **Static release `99383d318667e1b130569d9094b907b19c0621f28405ec14a32417ba7619b62c`:**
  - 222 files from a clean build; 220 are byte-identical to `864a29c6…`, and only `app.css` and `room.css` differ.
  - Uploaded to R2 (222 × 200) and verified over HTTPS (222/222).
  - Rollback: set `STATIC_RELEASE_ID` to `864a29c6e590bf096d29cfd4436a9460a24337c3dc034bf6cb56802c0a2059bc` and redeploy.
- **Deploy:** `dep-dc4o8amc6qcc73ebucg0` is live. No migrations. `MAISON_REVIEW_STANDING_FROM=2027-11-30T00:00:00+05:30` takes effect with this deploy.
- **Live checks** (1440×900):
  - `/en/`, Explore, Learn, the ক্ষুধিত পাষাণ title page and its reader return 200 and load the new static release;
  - the reader shows one Back link;
  - a signed-out `/en/tracks/<id>/` redirects to sign-in with `return_to`;
  - no console errors.

## #78 deploy and the ক্ষুধিত পাষাণ correction (27 Nov 2026)

- **Merge:** ronik18/reo-earnalism-maison#78, squash commit `6f98e6a`, merged after CI passed on head `ef46d91`. It carries the W4 colours and W6 icons (owner-approved 28 Nov IST), the carousel `role=group` fix and the corrected-text browser report.
- **Static release `efe9bcff6780576ad5b3ec9227314b4cb21c01e513cc18919d847c173b443664`:**
  - 228 files, uploaded and verified (228/228).
  - Compared with `99383d31…`, it adds the icon set and the share card and changes `room.css`.
  - Rollback: switch `STATIC_RELEASE_ID` back to `99383d318667e1b130569d9094b907b19c0621f28405ec14a32417ba7619b62c` and redeploy.
- **Deploy:** `dep-dc4tk0k9v7es738bncag` is live. No migrations.
- **Correction:**
  1. The owner approved the clearance and cover items on the Monday page on 27 Nov at 18:54Z.
  2. `revise` (`job-dc4t68gu01pc73fa6o20`) built draft `335dd363-de06-427c-bd43-b57373553eee`, sha `7514f67a…`, changing ¶6 and ¶37.
  3. Browser report: `docs/evidence/publication-browser-20261127-kshudhita-pashan-r2.json` (pass).
  4. `evidence` (`job-dc4tlc7f3r2c73cnd1vg`) recorded it, then `publish` (`job-dc4tlmjl550s73ami9c0`) ran.
  5. `335dd363` went live at 19:33:12Z. `3cb6a0b9` is retired, and reader state moves with the switch.
  6. Live check: the reader shows "রাত্রিযাপন করিবেন না।" in ¶6, and the old wording is gone.

## #80 deploy and বিচারক Maison audio published (28 Nov 2026)

- **Merge:** ronik18/reo-earnalism-maison#80, squash commit `5476fcc`, merged after CI passed on head `69d5e4a`. It carries local audio-chapter streaming with byte ranges (parity with R2), the বিচারক audio browser report, the pipeline narration imports, the 13 casting files and the per-unit narration redo.
- **Deploy:** `dep-dc562kvf3r2c73dlsaeg` is live. No migrations. No static-release change.
- **Publish:** owner "Audio approved" (Claude session, 2026-11-27T20:53:37Z) → `attach_audiovisual_audio publish bicharak --publisher 649b8725-… --browser-report docs/evidence/publication-browser-20261128-bicharak-audio.json` (`job-dc566a8u01pc738rej20`, succeeded).
  - Edition `9481e1ad-dc15-4b8a-a81c-8752daebec61` (slug `bicharak`) now has live revision `67ad5cee-8afd-445d-8c32-b1bd3c8e0fae`; `5206c8ca-c195-44fa-aa37-711c764bb400` is retired.
- **Live checks:**
  - Read-only production job `job-dc5adk6c6qcc738b9gsg` (succeeded): the live revision's audio asset `39b42989…` is ready with prepared-audio evidence (1,252,560 ms); a 120 s presigned R2 GET returns 206 `audio/mpeg` for bytes 0–1023 and 7,000,000–7,000,999; the full 15,031,053 bytes match sha256 `af296d06…`.
  - Signed out: `/en/titles/bicharak/` returns 200; `/en/listen/<edition>/` redirects to sign-in with `return_to`; no page errors.
  - Not certified here: signed-in playback in a real browser on production (no test account is created on production); the replica browser report covers it.
- **Gap found:** `/en/listen/<edition>/preview/` returns 404. The owner-approved 1:53 public preview (`deliverables/bicharak/2026-11-27/preview.mp3`) is not attached to the revision as a `preview_audio` asset, and the release has no command that attaches one. Follow-up.

## #81/#82 deploys, বিচারক public sample published, audio switched on (28 Nov 2026)

- **Merges:**
  - ronik18/reo-earnalism-maison#81 (`71f1059`) carries `stage-preview`, the owner's voice pick, multi-voice casting and the expressive narration layer. Deployed as `dep-dc5bi80u01pc7385gd2g`.
  - ronik18/reo-earnalism-maison#82 (`d61b158`) carries the browser acceptance report for draft `59c213f9`. Deployed as `dep-dc5cvemi0phs73da5j9g`.
- **Sample:**
  - `stage-preview bicharak` (`job-dc5bllm1egvs73bbkc90`) staged draft `59c213f9-3c6d-4af2-84de-477a7ebf5608` (content_sha256 `733e0aa4…`) with preview_audio asset `01c1522f…`.
  - The browser report `docs/evidence/publication-browser-20261128-bicharak-preview.json` passed on an exact replica.
  - `publish` (`job-dc5d30ui0phs73dai4n0`) made `59c213f9` live; `67ad5cee` is retired.
- **Gap found and fixed:**
  - Production had `MAISON_AUDIO` unset, so the audio feature was off. Both the released chapter audio (since #80) and the sample answered "Audio samples are unavailable".
  - The earlier #80 live check verified the R2 object directly and missed this.
  - With the owner's yes (28 Nov), `MAISON_AUDIO=true` was set on Render and the service redeployed as `dep-dc5efvei0phs73dfe950` (same commit `d61b158`).
- **Live checks after the switch:**
  - `/en/listen/9481e1ad-…/preview/` returns 200 at 1440 and 390 px, signed out, with no overflow and no console errors.
  - The sample request returns 307 to a presigned R2 URL, then 206 audio/mpeg.
  - Duration is 113.669 s, and playback advanced 4.7 s.
  - The served bytes match sha256 `979938aa…`, the owner-approved clip.
  - Signed-in chapter playback on production is still not certified here, because no production test account exists.
