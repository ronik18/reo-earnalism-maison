# Maison implementation milestone

**P0 frontend integration,18November2026:** root integrated the owner-authorized frontend lane against3fdd742, including onboarding/member Home, collections/Series, gated Video, owned Checkout, preview/format dialogs, recovery states and premium gold artwork. Desktop/mobile-width Chromium evidence is retained in [frontend browser validation](evidence/frontend-browser-validation.json).The initial185 combined backend tests and26 frontend tests/typecheck/build pass; final source CI will additionally cover the database-outage regression. a separate failed-database regression validates the database-independent500page. Physical devices/Safari, real media/payment/Series data and backend pagination remain pending in the central register. Updated static release54files/7,258,380bytes is prepared locally only; the previously uploaded45-file release remains unchanged.

**Pending acceptance checks:** use the [central pending validation register](PENDING_VALIDATIONS.md) for provider, CDN HIT/MISS/purge, email, device and final release dependencies. Earlier milestone gaps below are historical; close items only with actual evidence.


**Latest update,18November2026:** [Neon validation and parallel handoff](NEON_VALIDATION_HANDOFF.md) supersedes the implementation-status paragraphs below where noted. React/TypeScript islands and provider adapter source now exist; the actual protected Selfish Giant journey passes against migrated Neon PostgreSQL18.7. Public release/provider/device qualifications remain open. The17November register below is retained as historical milestone evidence.

17 November 2026. All21 audit findings have a specific resolution. This closes the original proposed-contract/code gaps for the local first slice; it does not certify external providers or the full P0 product.

Four lanes ran in parallel; root Integration owns final contracts, combined tests and commits. The existing platform remains unchanged. No paid resources, customer migration, commercial publication or cutover occurred.

| Lane | Implemented local scope |
| --- | --- |
| A | Accounts, reset/device revocation, durable receipts/outbox, Reader state, Saved/Lists/Finished |
| B | Bilingual SSR discovery/auth/Reader/Vault/learning, fonts/logo/art, real browser mutations |
| C | Original EN/BN packets, rights/revision/package guards, upload adapter, learning and local billing state machines |
| D | PostgreSQL/runtime integration, contracts, concurrency/journey tests, backup/restore, packaging and evidence |

**73 tests pass on real PostgreSQL17 in both Python3.12 and the pinned Python3.13 container.** A local backup/restore compared all49 tables successfully.

The first technical journey passes: bounded guest preview -> signup -> queued local verification delivery -> explicit confirmation -> sign-in -> full Reader -> signed package/hash verification -> first progress v0/v1 -> replay/conflict -> annotation -> independent completion -> Vault -> resume -> logout denial. Original test-only editions are used; no commercial-launch-title clearance is inferred.

The full54-table reference SQL executes in a separate audit database. Actual application migrations own49 database tables including framework tables. These counts describe different scopes; they are not a claim of full ORM parity.

The target remains one Django application, PostgreSQL and direct object delivery. The local first slice currently uses dependency-free JavaScript. This is a known gap against the approved React/TypeScript islands, not an approved substitution; see APPROVED_BASELINE.md. Real R2/CDN/Stream, email/merchant adapters, trusted production territory, offline devices, production restore/failover/load and commercial launch content remain pending. Mobile emulation did not produce reliable acceptance evidence; physical/mobile and assistive-technology checks stay open.

## Finding resolution register

| ID | Resolution | Local evidence | Remaining qualification |
| --- | --- | --- | --- |
| C01 | Explicit default-deny per-format access/download policy; independent rights/member/territory checks; exact-revision free authorization. | `library/tests.py; billing/tests.py` | R2/offline licensing and real cleared launch rights remain unqualified. |
| C02 | Persisted aggregate versions and CAS/receipt transitions; frozen revisions and financial snapshots reject bypasses. | `library/tests.py; reader/tests.py; billing/tests.py` | Full later-module ORM/API parity remains part of implementation. |
| C03 | UI/API/SQL use gold, mint, rose and lavender; unsupported colors rejected. | `reader/tests.py; contracts/openapi.yaml` | Separate release acceptance. |
| C04 | Explicit input-to-asset mapping, private nondeliverable raw sources and staff-only upload lifecycle; narrowly scoped PUT CORS. | `library/tests.py; library/fixtures/r2_cors_policies.json` | Real R2 CORS/PUT/multipart acceptance remains pending. |
| C05 | Refund proposal may reduce once at requested-to-approved, then freezes; payment lock and aggregate capture ceiling enforced by PostgreSQL. | `billing/tests.py; docs/evidence/contract-postgresql.json` | Real merchant refund submission/reconciliation remains disabled. |
| C06 | Actor-scoped input-hash receipts plus durable financial/outbox keys; unchanged concurrent/replayed mutations converge. | `reader/tests.py; library/tests.py; billing/tests.py` | Provider-side and offline-license adapters still require acceptance. |
| C07 | Verified late capture records captured money, refund_pending and one durable reconciliation obligation; no entitlement is granted. | `billing/tests.py` | Synthetic local provider facts only; real payments remain disabled. |
| C08 | Password reset revokes all prior sessions/devices and unused action tokens; fresh sign-in required. | `accounts/tests.py` | Configured external sender acceptance remains pending. |
| C09 | Executable flags are booleans with separate activation metadata; optional providers disabled and bad settings rejected. | `operations/tests.py; config/settings.py; contracts/runtime-config.json` | Enabled provider profiles are not qualified. |
| C10 | Completion is independently persisted/versioned; seek does not finish; explicit finish/unfinish and Vault.finished projection. | `reader/tests.py; web/tests.py; integration_tests/test_first_journey.py` | Separate release acceptance. |
| C11 | Absent v0 writes create final v1 atomically; actual concurrent PostgreSQL writes yield one write and one conflict/replay. | `reader/tests.py:ProgressConcurrencyTests` | Separate release acceptance. |
| C12 | Interrupted sync returns whole-batch503; stable IDs replay committed receipts without duplicating effects. | `reader/tests.py` | Real offline-device synchronization remains disabled/unqualified. |
| C13 | Revision-scoped verified copies retain distinct locators, byte accounting and fresh text-package identities. | `library/tests.py` | R2 server-side copy/retention cost measurements pending. |
| C14 | Known rights expiry caps public freshness and private grant expiry; no stale extension past clearance. | `library/tests.py; contracts/cache-policy.json` | Actual CDN cache/purge/clock behavior remains pending. |
| C15 | Gunicorn gthread timeout explicitly means worker heartbeat; provider/query/body/handler budgets are separately specified. | `Dockerfile; contracts/runtime-config.json; contracts/LLD.md` | Saturation, real adapter timeouts and resilience/load qualification remain pending. |
| U01 | P0 S18 includes real SDE question/model answer/rubric and semantic server-graded quiz; deferred S19 does not hide its destination. | `learning/tests.py; web/tests.py` | Editorial acceptance of actual launch learning content pending. |
| U02 | Saved, Lists and Finished are distinct actual server-backed Vault destinations; unavailable downloads are labeled truthfully. | `web/tests.py; reader/tests.py` | Offline downloads remain disabled. |
| U03 | Complete EN/BN first-slice UI catalogue; interface locale preserves edition UUID, script/fonts and reading state. | `web/tests.py; docs/evidence/bengali-reader-desktop.jpg` | Native Bengali editorial, physical device and complete P0 review pending. |
| U04 | Real password/register/confirmation/recovery routes preserve safe content return paths; GET does not consume action links. | `accounts/tests.py; web/tests.py; integration_tests/test_first_journey.py` | External sender delivery qualification pending. |
| U05 | Reader font/size/leading/margins/alignment/theme/layout and search/saved-filter preferences persist; six accepted Houses align across UI/API. | `web/tests.py; accounts/tests.py; contracts/openapi.yaml` | Full cross-device typography/device acceptance pending. |
| U06 | Semantic native quiz radios, fieldset labels, keyboard/focus controls, reduced-motion preference and nonfake results. | `web/tests.py; templates/web/quiz.html; static/maison/style.css` | Physical iOS/Android, screen-reader and full accessibility acceptance remain pending. |

## Next integration action

The Selfish Giant is now imported in draft with retained cover/browser evidence and named-country rights; see SELFISH_GIANT_HANDOFF.md. Continue the approved LLD sequence and close the baseline/provider/device gaps before production activation. Retain the existing platform throughout qualification and cutover.
