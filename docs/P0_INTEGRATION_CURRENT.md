# Maison P0 integration — 19 November 2026

The isolated candidate adds allauth Google sign-in/link/reauthentication, email-link sign-in, typed keyset catalog/search, scheduled-publication execution, bounded physical audio previews, Stream signing and client renewal, durable webhook/order/refund reconciliation, and existing-subscription cancellation. Reader/audio semantic switching, offline delivery, learning-version provenance and account rate limits are covered by focused and combined checks.

## Validation and limits

The local combined suite passed 418 tests on PostgreSQL 18 in214.821s before final Google compressed-response and queued-subscription authority corrections. Changed-area regressions and exact-head CI qualify the final source. The production Docker build and migration drift check passed. Frontend/source hashes and scoped desktop/WebKit/Firefox/native Safari receipts are in [the frontend summary](evidence/p0-frontend-20261119/frontend-validation.json).

Google credentials and its isolated callback were configured with owner approval; existing redirects were preserved. The client remains Testing. Actual Google sign-in qualification is separate from local recovery/link tests. Controlled Stream SDK tests prove client lifecycle only; no Stream account activation, paid encoding/upload or actual video-provider qualification occurred.

Merchant LIVE credentials were reused with explicit approval. GET-only qualification matched two existing captured payments; no new order, charge or refund was performed. New paid checkout requires an exact approved issuer/tax/numbering/offer policy and retained finance documents. The empty MERCHANT_FINANCE_POLICY default does not invent an exemption, tax rate, approved numbering scheme or legal sign-off. Finance policy snapshots bind approved terms to an order and invoice. Applicable credit-note and final invoice-document acceptance remain pending. Existing verified funds are retained for reconciliation even when finance terms are incomplete.

Existing subscription cancellation binds actor, merchant mode and exact provider reference to durable intent. An uncertain POST is never blindly repeated and an active provider state does not prove a cancellation schedule was accepted. Mandate revocation remains an explicit pending obligation until verified provider customer/token identity is available; cancellation does not establish token revocation. Paid-through access remains intact.

The consolidated [checklist](PENDING_VALIDATIONS.md) remains authoritative. No book publication, apex cutover, additional infrastructure spending or DNS change is implied. The Selfish Giant remains draft; the legacy platform remains unchanged.

## Deployed candidate

Commit `e3f27a92f1f3b3354eb2110db0e293f25fcb42a8` passed exact-head CI44470671418 with426 backend tests, frontend check/build, migration execution and no drift. It is deployed on all three existing Maison services. Twenty Neon migrations preserved the exact draft/version42/32paragraphs/hash; the SELECT-only backup role reads67tables including new allauth/search tables. Actual automatic maintenance succeeded on the same commit. The archive worker retains its03:00UTC schedule; the earlier actual archive/restore proof remains historical and has not been relabeled as a new67-table restore.

Static release `3cec3a985cd2c4a93c9994d1fdf4a6669597ef11807678f4c03ff97563a98108` has55files/7,298,682bytes; upload/readback and HTTPS checksum/MISS→HIT passed. Independent deployed-browser acceptance passed27/27 checks. Actual Google business-account sign-in and reauthentication completed, with aggregate database audit proof; audience remains Testing. Protected readiness and draft exclusion passed; legacy apex remained HTTPS200.
