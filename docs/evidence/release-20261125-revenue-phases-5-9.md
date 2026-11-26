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
