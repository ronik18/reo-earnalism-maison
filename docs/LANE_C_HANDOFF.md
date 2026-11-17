# Lane C implementation handoff

17 November 2026. Local technical implementation; no production data, provider call, merchant charge, imported book or commercial publication.

## Delivered code

- `library/`: UUID Work, Edition, Revision, Unit, Paragraph, Asset, Rights and TimingMap models; PostgreSQL migration guards; shared authorization/selectors; reviewed catalog, preview, manifest, package-grant and staff-action API shapes; protected local storage; Django admin; original bilingual fixtures; 13 acceptance tests.
- `learning/`: published tracks, lessons, SDE questions/model answers/rubrics, semantic quizzes, private scoring snapshots and per-member attempts/completion; APIs/admin; 6 acceptance tests. Quiz question/option saves increment their parent quiz version under a lock.
- `billing/`: reconciled transaction models and state-machine services, explicit free/paid entitlement authority, immutable financial snapshots, bounded refund approval, local synthetic capture/refund tests, and disabled merchant-facing routes; 8 acceptance tests. The shared outbox uses `refund_reconcile` for durable obligations.

No root configuration, shared contracts, templates, existing application or production resources were edited by this lane. Root owns shared integration and commits.

## Exact shared interfaces

`library.services.authorize_revision(user, revision_or_uuid, format='reader', action='read', territory='IN')` returns a freshly authorized Revision or raises `core.api.DomainError`. It requires an active verified member, the current live revision, an explicit per-format `free`/`paid` policy and current approved format/action/territory/time rights. Missing policy denies access. Paid access uses `billing.services.has_entitlement`; download also needs explicit download policy and rights. Test-only rights require the explicit local fixture profile.

`check_revision_rights(revision_or_uuid, format='reader', action='read', territory='IN')` and `authorize_purchase(user, revision_or_uuid, format='reader', territory='IN')` are internal billing checks, not member content grants.

Selectors: `catalog_cards`, `catalog_card`, `get_edition_by_slug` (globally unique slug when locale is None), `edition_detail`, `edition_units`, `get_reader_document`, `get_preview_document`, `get_reader_manifest`. Reader document selectors return semantic edition/unit/paragraph DTOs. Preview uses a separately stored maximum three paragraphs / 1,200 codepoints; the seeded preview is 130 codepoints and contains no full-package URL.

Billing exposes `has_entitlement`, `entitlement_expires_at`, `ensure_free_entitlement`, and `entitlement_data`. Free offline authority is a durable `source=free` grant bound to its member and exact revision; current rights are checked separately on every online authorization.

`learning.services` exposes `list_tracks`, `track_detail`, `lesson_detail`, `interview_questions`, `quiz_public`, `start_attempt`, `own_attempt`, `submit_attempt` and `attempt_dto`. Public quiz DTOs exclude correct-option flags, explanations and scoring snapshots. An attempt scores its server-owned snapshot, not client scores or a later edited answer key.

Root mounts `library.urls` and `learning.urls` beneath `/api/v1/`. Billing routes use that same prefix. Session cookies and CSRF remain shared middleware authority; only the dedicated disabled Razorpay webhook route is CSRF exempt.

## Data, files and publication

Run `python manage.py seed_local_pilot` only in the local profile. It preserves existing fixture revisions, writes original EN/BN content and an original raster cover, and never contacts an external service. Fixture editions:

| Locale | Edition | Revision | Unit |
|---|---|---|---|
| en | `20000000-0000-4000-8000-000000000001` | `30000000-0000-4000-8000-000000000001` | `40000000-0000-4000-8000-000000000001` |
| bn | `20000000-0000-4000-8000-000000000002` | `30000000-0000-4000-8000-000000000002` | `40000000-0000-4000-8000-000000000002` |

These fixtures are locally live solely to exercise the technical journey. Their rights are explicitly test-only and browser acceptance remains pending. Staff readiness will fail without actual exact-hash acceptance evidence. The seed does not establish a commercially cleared or browser-approved release.

Private local assets live under the ignored `.local/private-media/` directory. Package/media URLs are account/device/revision/action bound, cryptographically signed, capped at 120 seconds and at known rights/entitlement expiry, and reauthorize at read time. Byte length and SHA-256 are checked before delivery. Responses use private/no-store. Raw reader sources, timing-map inputs and rights evidence are never deliverables. API upload inputs use explicit kind-to-output mapping, narrow MIME allowlists and independent hash/size completion checks.

Frozen revision content and cross-revision asset/unit changes fail in PostgreSQL. Cloning creates separate revision-scoped locators and verifies copied bytes; Reader packages are rebuilt with new revision/unit/anchor identities. Clone rights approvals and browser acceptance reset. The original revision is retained.

The `r2_cors_policies.json` fixture separates private member GET/HEAD delivery from staff PUT and limits origin/method/header scope. It is a design fixture, not an applied bucket policy or a real preflight acceptance result.

## Verification status

Root observed these PostgreSQL 17 runs passing: library 13/13, learning 6/6, and billing 8/8. The initial library/learning result was terminal evidence rather than a retained standalone log. Billing results appear in `.local/integration-finance-tests.log`; that run also contained a separate cross-lane integration failure, so the log is not an overall green release certificate.

Local static checks pass: Python compileall, Django system checks, and migration drift check (`No changes detected`). Root is collecting the final combined suite and browser journey evidence. This handoff does not substitute for that final result.

The tests exercise explicit default deny, free/territory/account/test-rights gates, bounded previews, real bilingual package bytes and strict DTOs, revoked/logout delivery, wrong-revision/raw-asset denial, expiry caps, database freeze/version guards, clone hashes/locators, permission/CAS/readiness failures, raw upload completion/replay, SDE content, answer-key isolation, server scoring/ownership, duplicate capture, late capture compensation, partial-refund ceilings/immutability, financial snapshot guards and exact-byte HMAC helpers.

## Remaining external acceptance

Merchant checkout, live payment/webhook reconciliation, provider refund submission and recurring billing remain disabled. Synthetic facts can affect only explicitly test-only local orders; a callback signature alone never grants access. A late cancelled/expired capture records captured money, issues no entitlement, and retains one durable reconciliation obligation. No actual refund is claimed without a provider adapter.

R2/Stream uploads and signed transport, deployed CORS/CDN behavior, trusted deployment territory, real offline-device/storage behavior, external browser acceptance, rights ownership, tax/invoice configuration and merchant qualification are separate gates. Production local-storage grant endpoints fail closed. The original live platform and legacy balances/history remain untouched.

Razorpay signature mechanics were checked against [official webhook validation documentation](https://razorpay.com/docs/webhooks/validate-test) and [official integration source](https://github.com/razorpay/markdown-docs/blob/master/payments/payment-gateway/quick-integration/integration-steps.md). Only raw-body HMAC and callback authentication helpers are implemented locally; these references do not certify a merchant integration.

Next root command: `.venv/bin/python manage.py test --noinput --verbosity 2` with the isolated PostgreSQL profile and durable output capture, followed by the exact local browser journey. Root owns execution and the evidence location.


Final root Integration run: 71 tests passed in 36.119s on PostgreSQL17, including all14 library,6 learning,8 billing cases. Full suite evidence: docs/evidence/postgresql-suite.log. No external provider or commercial-publication acceptance is claimed.

Final current suite:73/73 in35.852s on Python3.12 and73/73 in53.135s in Python3.13, both PostgreSQL17. Includes14 library/6 learning/8 billing tests and the final strict nested-preference fixes.
