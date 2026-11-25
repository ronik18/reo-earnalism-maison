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
