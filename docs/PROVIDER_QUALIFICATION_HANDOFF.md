# Provider qualification and parallel implementation handoff

18November2026. Integration Lane record; the [central pending validation register](PENDING_VALIDATIONS.md) owns remaining acceptance work. Current platform/DNS remain unchanged; The Selfish Giant remains draft. No additional paid infrastructure was provisioned.

## Qualified scope

Private R2 synthetic HTTP qualification passes all18checks plus cleanup. Real desktop browser qualification verifies64KiB GET, SHA256,206Range and private/no-store from loopback8010. Two dedicated Standard APAC buckets exist, both non-public; only the private bucket was exercised. Delivery and upload credentials are private-bucket-only24hour tokens stored in ignored mode0600 provider configuration. Public CDN and durable production credentials are not qualified. See evidence/r2-http-qualification.json and evidence/r2-browser-qualification.json.

A real SDK exhausted-socket error was fixed in object verification/copying: stop after the validated ContentLength, retain exact hash/type/size checks and close the stream. Unsigned R2 requests return400 with InvalidArgument; qualification accepts only the bounded expected XML denial and no canary bytes, never arbitrary400. All test canaries were cleaned; no book content was uploaded to public storage.

SMTP TLS/EHLO passes for the existing Google Workspace sender. Authentication, test account verification/reset submission and actual inbox receipt await the owner-provided app password in the ignored provider env. No mail/DNS settings were changed.

## Parallel source integration

Backend: validated client-IP rate limiting with truthful headers; single-purpose email retry identity/expiry; bounded bucket cleanup. Frontend: persistent Player across eligible navigation/history/language/Reader routes, stale-navigation cancellation, explicit audio conflict handling, rejected-note recovery controls, reload-safe scoped checkout retry/order state. Actual browser testing found a grant-route mismatch, now fixed to the existing /api/v1/media/grants contract; frontend tests audit API call routes against OpenAPI. Media: immutable intake preparation outside receipt locks, bounded immutable object operations, atomic live metadata/rights cache invalidation. Integration: PostgreSQL emitted-URL capture with generation locking, private/CDN header finalization, scoped R2/SMTP runtime settings and CSP, cache migration/maintenance.

Synthetic Player browser acceptance proves advancing180second original generated-tone playback through Explore, EN–BN, history and Reader,1.25x speed and timer selection retention, plus explicit close removing audio. It does not certify real audiobook content, physical devices, timer completion, exact DOM identity or full account/offline recovery.

## Validation

171 combined backend tests passed on isolated PostgreSQL18/Python3.12;20 frontend tests, strict TypeScript and production build pass. Seven focused configuration tests pass; no migration drift. The cache-ledger migration applied to the existing dedicated Neon project via direct TLS connection; the actual title retains draft/null live pointer. Logs are retained under evidence/provider-*. The existing pinned Python3.13 image also passed all171 combined tests on isolated PostgreSQL18 (evidence/provider-python313-suite.log); the final CDN-host configuration test passed separately in the seven-test configuration run. Exact-head CI remains pending until the source push completes.

Next integration action: finish final compatibility/CI, qualify the protected draft intake/Reader using R2, and continue the remaining grouped checks from PENDING_VALIDATIONS.md without changing the current platform or provisioning paid resources.
