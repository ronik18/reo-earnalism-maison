# Earnalism Maison — local implementation

A new, independent application repository for the approved Maison design. The existing Earnalism application and infrastructure remain operational and unchanged. This repository is not a production deployment.

## Audiovisual production skills

The [shared audiovisual workflow](docs/EARNALISM_AUDIOVISUAL_PIPELINE.md) coordinates the six [Earnalism skills](skills/) for Bengali/English books, tutorials and social content: source and rights, the owner's final voice roster, measured background score, visuals, covers and exact-candidate review. Reuse the existing Colab resources and accepted media. The guide identifies the Maison operations that exist and the historical adapters that still need a verified handoff; skill updates do not publish content or qualify unheard recordings.

Repository discovery uses `.agents/skills/` links to these canonical skill folders. Select the repository-scoped skill when another installed copy has the same name; duplicate skills are not merged, and a Git update does not automatically install or synchronize global/plugin copies.

## Run the local build

Use Python 3.13 (the current macOS verification environment also uses supported Python 3.12) and PostgreSQL 18. PostgreSQL 17 local data is retained for prior-work compatibility. Install `requirements.lock` into `.venv`. The existing isolated PostgreSQL container is `earnalism-maison-pg17`, bound only to `127.0.0.1:55432`. Its generated credentials are in ignored, mode-600 `.local/database.json`; never copy this directory into a review package.

From this repository:

```sh
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py seed_local_pilot
.venv/bin/python manage.py runserver 127.0.0.1:8008 --noreload
```

Open http://127.0.0.1:8008/en/ or `/bn/`. Sign-up is real; confirmation mail is delivered to ignored `.local/mail` after `.venv/bin/python manage.py run_maintenance`. Open the local confirmation link and explicitly confirm it. No external email provider is called. No test account password is embedded in the source.

`seed_local_pilot` installs an original, fictional English/Bengali **test-only** Reader packet and learning fixtures. It never imports, clears or publishes a commercial launch title. Test-only rights cannot authorize production delivery. The seed is idempotent and preserves modified existing fixtures instead of overwriting them.

## Verify

```sh
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test --noinput --verbosity 2
.venv/bin/python -m operations.validate_contract_sql
.venv/bin/python -m operations.backup_restore_local
```

PostgreSQL is required; SQLite is intentionally unsupported. The raw SQL audit creates a separate local database and executes the complete reference contract after real Django auth/session migrations. The running application's schema is owned by its Django migrations. Never execute `contracts/database.sql` on the application database or an existing database. The backup check creates a new local restore database, compares each table's row count and content hash, and leaves the private dump in `.local/backups`.

The private GitHub repository runs disposable PostgreSQL/Python3.13 CI. Refer to the exact commit run for current evidence. The Maison application has not been deployed to production.

## Application boundaries

One Django process serves SSR pages, same-origin JSON APIs and React/TypeScript interactive islands. One PostgreSQL database owns business state, operation receipts and outbox jobs. The official logo and licensed self-hosted fonts are preserved; Ford Gold art stays outside the calm Reader text area. Covers use whole, rectangular frames.

Interactive Reader, Player, Quiz, account and offline controls use React/TypeScript built with Node24. Run `npm ci`, `npm run check` and `npm run build` before Django web tests or packaging. The Docker image builds these assets in a separate stage; Node is absent from the runtime image. Private R2 and sandbox payment source adapters exist, but real provider qualification is separate from deterministic tests.

Audio/video, offline licensing, magic links, Google/phone sign-in, recurring billing and international checkout remain explicitly disabled until their configured adapters pass acceptance. There is no fake paid checkout, real refund, production publication or HA claim. Production configuration requires real secrets, an HTTPS public base URL and verified database TLS; it cannot fall back to local credentials.

See [implementation status](docs/IMPLEMENTATION_STATUS.md), [workspace provenance](docs/WORKSPACE_PROVENANCE.json) and [evidence](docs/evidence/).

Latest cleared-title draft: [The Selfish Giant handoff](docs/SELFISH_GIANT_HANDOFF.md), including cover/footer assets, staff browser acceptance and the [requested-country assessment](docs/SELFISH_GIANT_TERRITORIES.md). The active whitelist contains47 regions. UAE/Mainland China and all other pending regions are excluded; every published book must be legally compliant across the complete whitelist. See [publication policy](docs/BOOK_PUBLICATION_POLICY.md). Create your own local staff account with `.venv/bin/python manage.py createsuperuser` to review protected drafts; no development credentials are published.


## Existing Neon project

PostgreSQL18 was approved by the owner on18November2026. See [Neon setup](docs/NEON_SETUP.md). `.env.local` is ignored and loaded only with `MAISON_ENV_FILE=.env.local`; this prevents parallel local tests from accidentally using the cloud database. Web traffic uses pooled `DATABASE_URL`; migrations and streamed exports use `DATABASE_URL_UNPOOLED`.

Provision timeout defaults before first deployment, using the direct endpoint:

```sh
MAISON_ENV_FILE=.env.local MAISON_DATABASE_ROLE=direct .venv/bin/python manage.py configure_database_timeouts
MAISON_ENV_FILE=.env.local MAISON_DATABASE_ROLE=direct .venv/bin/python manage.py migrate --noinput
```

Pooled startup packets intentionally contain no timeout options. Database-scoped role defaults retain5s statement,2s lock and10s idle-transaction limits. Full certificate/hostname verification uses the platform CA bundle; `DATABASE_SSL_ROOT_CERT` may explicitly select a trusted bundle. Never disable TLS verification to fix a connection error.

## Production regression suite

`e2e/production/` is the browser regression suite for the live member journey. Run it after every production deploy:

```sh
npm ci
npx playwright install chromium
MAISON_E2E_EMAIL=<dedicated test account> MAISON_E2E_PASSWORD=<its password> npm run e2e:production
```

It covers liveness, the Home and title page, cover revalidation (`ETag` → `304`), opening a chapter and turning to the next one, progress reaching Vault "Continue", save/unsave and a learning track. Use a dedicated, verified test account without paid access, never a customer account; the suite never buys anything and removes its saved item.

Production serves the nine launch countries (IN, US, GB, BR, SG, MY, ID, PH, TH). From any other country only liveness runs and every other test is reported as skipped with that reason. `MAISON_E2E_BASE_URL` points the suite at another deployment, such as a local `runserver` with `seed_local_pilot` (cover revalidation is skipped there because covers are only edge-cacheable behind the HTTPS public origin). The HTML report is written to `.local/e2e-report`.

The suite signs in once per run, because the server allows five sign-in attempts per email per 15 minutes; after repeated failed attempts, wait 15 minutes before rerunning. Until a book is published the live catalog is empty, so book-dependent tests are skipped with that reason; once a book is live, set `MAISON_E2E_REQUIRE_BOOK=1` so an empty catalog fails as a regression.
