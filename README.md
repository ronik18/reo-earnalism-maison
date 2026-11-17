# Earnalism Maison — local implementation

A new, independent application repository for the approved Maison design. The existing Earnalism application and infrastructure remain operational and unchanged. This repository is not a production deployment.

## Run the local build

Use Python 3.13 (the current macOS verification environment also uses supported Python 3.12) and PostgreSQL 17. Install `requirements.lock` into `.venv`. The existing isolated PostgreSQL container is `earnalism-maison-pg17`, bound only to `127.0.0.1:55432`. Its generated credentials are in ignored, mode-600 `.local/database.json`; never copy this directory into a review package.

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

The GitHub Actions file defines a disposable PostgreSQL/Python 3.13 check. Authoring the workflow does not mean a remote run has passed. No remote repository or deployment is configured by this local milestone.

## Application boundaries

One Django process serves SSR pages, same-origin JSON APIs and small, dependency-free browser interactions. One PostgreSQL database owns business state, operation receipts and outbox jobs. The official logo and licensed self-hosted fonts are preserved; Ford Gold art stays outside the calm Reader text area. Covers use whole, rectangular frames.

Interactive controls currently use plain JavaScript rather than introducing a React build for the first journey. This deliberate simplification retains the reviewed API contracts and accessible HTML. Large provider-backed media will use direct delivery; the local signed-asset transport is a development adapter, not an R2 implementation or performance claim.

Audio/video, offline licensing, magic links, Google/phone sign-in, recurring billing and international checkout remain explicitly disabled until their configured adapters pass acceptance. There is no fake paid checkout, real refund, production publication or HA claim. Production configuration requires real secrets, an HTTPS public base URL and verified database TLS; it cannot fall back to local credentials.

See [implementation status](docs/IMPLEMENTATION_STATUS.md), [workspace provenance](docs/WORKSPACE_PROVENANCE.json) and [evidence](docs/evidence/).

Latest cleared-title draft: [The Selfish Giant handoff](docs/SELFISH_GIANT_HANDOFF.md), including cover/footer assets, staff browser acceptance and remaining global-rights limitations. Create your own local staff account with `.venv/bin/python manage.py createsuperuser` to review protected drafts; no development credentials are published.
