# Maison Global Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Maison fully ready and lawfully available in India, the US, the UK, Brazil and Southeast Asia, then cut https://theearnalism.com over to it.

**Architecture:** Keep the approved single Django app on Render (Singapore), Neon PostgreSQL, Cloudflare CDN/R2/Stream. Availability stays a trusted-edge-country allowlist, now configured per territory with a per-territory account-capacity rule and notice, instead of the hard-coded India-only gate. Publication stays bound to `contracts/publication-policy.json` (47 regions, exact-edition clearance).

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL, Playwright 1.63 (`@playwright/test`), Cloudflare rulesets API, Render API.

**Spec:** `docs/superpowers/specs/2026-11-22-territory-accounts-design.md` (approved 22 Nov 2026; supersedes Phase 0 D1–D6 below), `AGENTS.md` (owner instructions), `contracts/LLD.md`, `contracts/publication-policy.json`, `contracts/india-first-service-policy.json`, `docs/evidence/public-doc-review-20261121/README.md`, `docs/APEX_CUTOVER_RUNBOOK.md`, `docs/PENDING_VALIDATIONS.md`.

## Global Constraints

- Approved stack only: Render + Neon + Cloudflare (CDN, R2, Stream). No Railway, Redis or new service; any new spend needs owner budget approval.
- Target territories must be a subset of the 47-region whitelist. Southeast Asia in the whitelist = BN, ID, KH, LA, MM, MY, PH, SG, TH. **Vietnam and Timor-Leste are not in the whitelist** and are not added by this plan.
- A book is published only with exact-edition compliance across every active publication region (now IN, US, GB, BR, SG, MY, ID, PH, TH) and offered format/action; incomplete titles stay draft.
- "Country" means trusted edge connection location, never citizenship or proof of age.
- No legal clearance is claimed by code or tests. Notices and per-country conditions need owner/counsel sign-off recorded as evidence.
- Free access stays on; paid checkout stays disabled (no merchant, tax or consumer-billing scope).
- TDD for every code change; PostgreSQL tests; `npm run e2e:production` after every production deploy.
- No force push, history rewrite, legacy deletion or DNS change outside `docs/APEX_CUTOVER_RUNBOOK.md`.

## Review Focus

- A visitor from a territory not on the service list gets the unavailable page before any account or data collection (Task 1 test `test_unlisted_territory_is_refused_before_session`).
- In an `adult_only` territory, signup without the 18+ declaration is refused with a clear message, including through Google sign-up; in an `open` territory no capacity field is asked or required (Task 2 tests).
- Enabling a territory without a notice row fails at startup rather than silently serving no notice (Task 3 `test_active_territory_without_notice_fails_startup`).
- Repeated sign-in attempts show a "please wait" message instead of failing silently (Task 5).
- Old theearnalism.com links (`/book/<slug>`, `/privacy`, `/library?category=…`) land on a sensible Maison page or an honest 410 (Task 6).

---

## Phase 0 — Owner decisions (blocking; one sitting)

| # | Decision | Recommended (quickest, simplest) | Why |
|---|---|---|---|
| D1 | Audience outside India | **Adults only (18+, self-declared) outside India**; keep India's existing guardian path | Removes the child-consent method work (US COPPA, UK children's code, BR LGPD art. 14, SG/MY/ID/PH/TH child rules) that left **0 countries qualified** for all-ages launch. The review says not to add adult-only *silently*: this is an explicit owner scope decision. |
| D2 | Launch territories | IN, US, GB, BR, SG, MY, ID, PH, TH (BN, KH, LA, MM later) | Largest Southeast Asian reader markets first; each added territory needs its notice row (Task 3). |
| D3 | First published title | A pre-1931 original-language Bengali or English work by an author who died before 1955 (e.g. a Rabindranath Tagore Bengali original), our own typesetting | Public domain in all 47 regions under life+70 and the US pre-1931 rule; no translator or illustrator rights. Clearance still recorded per region. |
| D4 | Legacy `/book/<slug>` URLs | 410 Gone, plus explicit redirects when a title is republished | LLD §4 rule for retired slugs. |
| D5 | Spend | $0 by default; optionally one more $7 Render instance for no-downtime deploys | Everything else in this plan uses existing services. |
| D6 | Privacy notice text per territory | Owner/counsel approves the Task 3 notice rows | Code cannot clear law; Brazil (LGPD controller and *encarregado* contact), UK GDPR (possible Art. 27 UK representative), SG/MY/PH/TH/ID data-protection officer and transfer statements need sign-off. |

## Phase 1 — Engineering (autonomous, TDD)

### Task 1: Configurable service territories

**Files:**
- Modify: `config/settings.py:29-30`, `operations/middleware.py:130-145`
- Rename: `templates/web/india_unavailable.html` → `templates/web/region_unavailable.html`
- Test: `operations/test_service_territories.py`

**Interfaces:**
- Produces: `settings.MAISON_SERVICE_TERRITORIES: tuple[str, ...]` read from env `MAISON_SERVICE_TERRITORIES` (comma-separated; default `IN`); `settings.SERVICE_GATE_ENABLED: bool` (renames `INDIA_FIRST_LAUNCH_ENABLED`, which stays as an alias).

- [ ] **Step 1: Write failing tests** — `test_default_is_india_only` (no env → `('IN',)`); `test_env_list_must_be_subset_of_publication_whitelist` (env `IN,VN` → `ImproperlyConfigured`); `test_listed_territory_reaches_app` (territory `BR` with env `IN,BR` → not 403); `test_unlisted_territory_is_refused_before_session` (territory `FR` → 403 `service_region_unavailable`, no `Set-Cookie`); `test_refusal_copy_is_territory_neutral` (body lacks "India").
- [ ] **Step 2: Run** `python manage.py test operations.test_service_territories` — expect FAIL.
- [ ] **Step 3: Implement** — parse, upper-case, dedupe and validate env against `MAISON_PUBLICATION_TERRITORIES`; detail text "Earnalism is not yet available in your country."; rename template.
- [ ] **Step 4: Run** the test module plus `operations` and `web` suites — expect PASS.
- [ ] **Step 5: Commit** `Configure service territories per deployment`.

### Task 2: Per-territory account mode

**Files:**
- Modify: `config/settings.py`, `accounts/enrollment.py`, `accounts/google.py`, `accounts/views.py` (register), `templates/web/auth.html`
- Test: `accounts/test_territory_accounts.py`

**Interfaces:**
- Consumes: Task 1 `settings.MAISON_SERVICE_TERRITORIES`, `request.territory`.
- Produces: `settings.MAISON_ACCOUNT_MODES: dict[str, str]` = `{'IN':'open','US':'adult_only','GB':'adult_only','BR':'adult_only','SG':'adult_only','MY':'adult_only','ID':'adult_only','PH':'adult_only','TH':'adult_only'}` (startup error if an active territory has no mode or an unknown mode); `enrollment.account_mode(territory: str) -> str`; `enrollment.capacity_declaration(data: dict, territory: str) -> dict | None` (`open` → `None`, no fields required; `adult_only` → requires `account_capacity == 'adult'`, else `DomainError('adult_declaration_required', 'Confirm that you are 18 or older to create an account here.', 422)`).

- [ ] **Step 1: Failing tests** — `test_india_signup_needs_no_capacity_fields`; `test_brazil_signup_without_declaration_is_refused` (422, no user row); `test_brazil_signup_with_adult_declaration_records_audit`; `test_google_signup_in_adult_only_territory_requires_declaration`; `test_signup_page_shows_adult_checkbox_only_in_adult_only_territory`; `test_active_territory_without_mode_fails_startup`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement**; India's guardian signup is no longer offered while India is `open` (guardian code retained).
- [ ] **Step 4: Run** `accounts` and `web` suites — expect PASS; update India-first tests that assumed the guardian signup.
- [ ] **Step 5: Commit** `Choose account mode per territory`.

### Task 2b: Publication scope to the nine launch territories

**Files:** Modify `contracts/publication-policy.json` (`whitelist` → IN, US, GB, BR, SG, MY, ID, PH, TH; new `deferred` list holds the other 38), `config/settings.py` (accept `deferred`), `docs/BOOK_PUBLICATION_POLICY.md`; Test `operations/test_publication_policy.py`.

- [ ] **Step 1: Failing tests** — `test_whitelist_is_the_nine_launch_territories`; `test_deferred_regions_are_not_publication_territories`; `test_deferred_and_whitelist_are_disjoint`.
- [ ] **Step 2–4:** Run (FAIL), change policy and loader, run full suite (fix tests that hard-code 47).
- [ ] **Step 5: Commit** `Limit active publication to the nine launch territories`.

### Task 3: Per-territory notices with a startup guard

**Files:**
- Create: `contracts/territory-notices.json`
- Modify: `config/settings.py`, `web/views.py` (privacy/terms), `web/i18n.py`
- Test: `web/test_territory_notices.py`

**Interfaces:**
- Produces: `contracts/territory-notices.json` rows `{"territory": "BR", "notice_version": "br-account-v1", "privacy_sections": ["controller","legal_bases","rights","dpo_contact","transfers"], "approved_by": "", "approved_on": ""}`; `settings.TERRITORY_NOTICES: dict[str, dict]`; `enrollment.notice_version(territory) -> str` replacing the fixed `ACCOUNT_NOTICE_VERSION` check.

- [ ] **Step 1: Write failing tests** — `test_active_territory_without_notice_fails_startup` (env `IN,BR`, no BR row → `ImproperlyConfigured`); `test_privacy_page_renders_territory_sections` (BR shows `dpo_contact`); `test_signup_requires_current_territory_notice_version`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** the loader, validation and rendering; seed the IN row from existing `india-account-v1`; add BR, GB, US, SG, MY, ID, PH, TH rows with empty approval fields (D6 fills them).
- [ ] **Step 4: Run** `web` and `accounts` suites — expect PASS.
- [ ] **Step 5: Commit** `Require an approved notice for every active territory`.

### Task 4: Accessibility gate (WCAG 2.2 AA)

**Files:**
- Create: `e2e/production/accessibility.spec.mjs`
- Modify: `package.json` (pin `@axe-core/playwright`), templates/static found by the scan
- Test: the spec itself

**Interfaces:**
- Consumes: `MAISON_E2E_BASE_URL`, test account variables from `e2e/production/journey.spec.mjs`.

- [ ] **Step 1: Write the spec** — for `/en/`, `/bn/`, `/en/explore/`, `/en/sign-in/`, `/en/sign-up/`, `/en/privacy/`, `/en/learn/`, a title page and a reader page: `expect(violations.filter(v => ['serious','critical'].includes(v.impact))).toEqual([])` with tags `wcag2a, wcag2aa, wcag21aa, wcag22aa`.
- [ ] **Step 2: Run** against local `runserver` + `seed_local_pilot` — record failures.
- [ ] **Step 3: Fix** each violation in templates/CSS; use the `ui-consistency:accessibility` skill for fixes.
- [ ] **Step 4: Run** until zero serious/critical; keyboard-only reader walk noted in evidence.
- [ ] **Step 5: Commit** `Gate pages on WCAG 2.2 AA serious and critical issues`.

### Task 5: Visible sign-in rate-limit message

**Files:** Modify `client/auth.tsx` (or the auth form script), `web/i18n.py`; Test `web/test_auth_rate_limit.py` + a suite assertion.

- [ ] **Step 1: Failing test** — sixth sign-in attempt within 15 minutes renders "Too many attempts. Wait a few minutes and try again." in `#auth-form-status`.
- [ ] **Step 2–4:** Run (FAIL), map the 429 `rate_limited` problem to that copy, run (PASS).
- [ ] **Step 5: Commit** `Tell members when sign-in is rate limited`.

### Task 6: Legacy theearnalism.com URL map (after D4)

**Files:** Create `web/legacy_redirects.py`; Modify `web/urls.py`; Test `web/test_legacy_redirects.py`.

**Interfaces:** Produces `LEGACY_PAGES: dict[str, str]`; `LEGACY_TITLES` starts with `the-selfish-giant` → its Maison edition id once published (`/privacy`→`/en/privacy/`, `/terms`→`/en/terms/`, `/contact`→`/en/contact/`, `/library`→`/en/explore/`, `/pricing`→`/en/pass/`, `/about`, `/copyright`, `/journal`, `/micro-story`→`/en/`) and `LEGACY_TITLES: dict[str, str]` (slug → Maison edition id, empty until republished).

- [ ] **Step 1: Failing tests** — `test_static_pages_redirect_301` (query dropped for `/library?category=…`); `test_unknown_book_slug_is_410`; `test_republished_book_slug_redirects_to_title`; `test_maison_routes_unaffected`.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS) — all 119 sitemap paths from the legacy `sitemap.xml` as a data-driven test.
- [ ] **Step 5: Commit** `Map legacy theearnalism.com URLs`.

## Phase 2 — First published title (D3)

### Task 7: Publish one cleared title through the existing staff flow

- [ ] Import the chosen work with `library/general_import.py` (dry run first) into a draft edition; build Reader packages and cover.
- [ ] Record per-region public-domain evidence for all 47 active regions (author death year, first publication year, original-language edition) in `docs/evidence/<title>-clearance/`, signed off by the owner.
- [ ] Publish via `transition_revision` (staff MFA); then run `MAISON_E2E_REQUIRE_BOOK=1 npm run e2e:production` from India and expect all tests to pass.

## Phase 3 — Operational readiness ($0)

### Task 8: Prove recovery and monitoring

- [ ] Neon: create a branch from a past point in time, verify counts and checksums with `operations/backup_restore_local.py` against it, delete the branch; record evidence.
- [ ] Render: redeploy the previous live commit and roll forward again; record downtime.
- [ ] Uptime: Cloudflare health check or Render notification on `/api/v1/health/live`, alerting the owner email.
- [ ] Update `docs/PENDING_VALIDATIONS.md` rows "Full production HA/PITR/load" and "Operating evidence" with what was proven and what remains.

## Phase 4 — Open territories and cut over

### Task 9: Staged territory rollout

- [ ] Set `MAISON_SERVICE_TERRITORIES=IN,SG` (requires D6 rows approved), deploy, verify the unavailable page for an unlisted country and signup for SG through a tester or VPN; then add US, GB, BR, MY, ID, PH, TH in one change once their notices are approved.
- [ ] Run `npm run e2e:production` from India after each change.

### Task 10: Apex cutover

- [ ] Execute steps 3–6 of `docs/APEX_CUTOVER_RUNBOOK.md` (Google OAuth redirect URI added first by someone with Console access).
- [ ] Run the suite with `MAISON_E2E_BASE_URL=https://theearnalism.com`.
- [ ] After a stable week: switch the alias redirect to 301 and remove the domain from the Vercel project.

## Phase 5 — Retire the legacy platform (owner direction, 22 Nov 2026)

### Task 11: Decommission after a 7-day rollback window

- [ ] Inventory legacy resources and monthly cost: Vercel project serving `theearnalism.com`/`www`, Railway service(s) behind `api.theearnalism.com` (and any Railway database), legacy storage/CDN; record in `docs/evidence/legacy-decommission/inventory.md`.
- [ ] Export legacy data that has value (users: none per owner; content: books are re-onboarded from scratch) to the private R2 archive with a checksum manifest.
- [ ] Remove DNS records `api` (Railway) and `_railway-verify.api`; detach the domain from the Vercel project.
- [ ] Delete the Railway services/database and the Vercel project; cancel their plans. Archive (do not delete) legacy GitHub repositories.
- [ ] Keep Hostinger mail records (MX, SPF, DKIM, DMARC, autodiscover/autoconfig) and `ftp` unless the owner retires them separately.
