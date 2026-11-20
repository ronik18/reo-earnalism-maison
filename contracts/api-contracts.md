# Earnalism Maison API contracts

Implementation design • 17 November 2026 • proposed API v1

The machine-readable authority for paths, operation IDs, input/output fields and security requirements is `openapi.yaml` in this directory. It is OpenAPI 3.1 in JSON-compatible YAML so standard JSON tooling can also read it. This document defines the behavior that JSON Schema alone cannot express. Neither artifact claims a deployed or tested platform.

## Application and phase boundary

Implement these routes as conventional Django 5.2 LTS JSON views with shared JSON Schema validation and ordinary ORM transactions. Django also serves the public HTML and admin. Do not introduce a separate API service, global frontend store, GraphQL layer, bearer-JWT identity system or message broker. Provider HTTP clients and the PostgreSQL outbox are adapters inside the same application.

Every OpenAPI path is relative to `/api/v1`, including Google start/callback and the webhook. The API is same-origin. SSR page routes and auth landing/confirmation pages are defined in the root route contract, not duplicated here. Public catalogs require explicit `locale=en|bn` and ISO country `territory` selectors. Those selectors do not override actual rights or provider commercial eligibility. Checkout loads approved server terms; no price in a URL, client payload, screenshot or example becomes authoritative.

The selected P0 launch includes email/password with verification, Google sign-in, public discovery/previews, Reader/audio/video where cleared assets exist, basic measured Reader↔audio switching, progress, in-Reader annotations, Saved and custom Vault Lists, offline Reader/audio, learning/quiz and the reviewed SDE question bank/model answers/rubrics. Email magic-link and recurring-pass contracts are fully specified here but activation is gated. Phone OTP has a gated contract pending provider and abuse qualification. Gating prevents provider side effects and returns `409 feature_disabled`; it is distinct from deleting a required design.

P1 routes are deliberately absent: gifts, clips, timed/recorded interview practice, readiness scoring, dictionary, word-level read-along, video Trinity, a global searchable Notes/Highlights hub and external annotation exports. PM/EM interview tracks are later scope. AI interviewing and native apps are later phases. P0 SDE 7/30-day tracks and Company Packs reuse the track/question resources; no recorder or AI scoring service is implied.

## Identity, cookies and authorization

`GET /session` returns 200 for both guests and members and issues/refreshes Django's masked CSRF token. An anonymous response has `authenticated=false`, `member=null` and no transferable auth credential. This response is always `private, no-store`.

The opaque database-backed session cookie is `__Host-earnalism_session`: Secure, HttpOnly, SameSite=Lax, Path=/ and no Domain. The CSRF cookie is `__Host-earnalism_csrf`, Secure, SameSite=Lax, Path=/ and no Domain. Browser requests use `credentials: same-origin`. All unsafe same-origin routes require the CSRF cookie plus `X-CSRFToken` and Django Origin/Referer validation, including anonymous registration, login, reset, OTP and contact. No CORS wildcard is enabled. The OpenAPI security object puts session and CSRF in the **same object** for authenticated mutations, meaning both are required; it does not offer an anonymous alternative.

Only the provider webhook is CSRF-exempt. Its independent HMAC security is mandatory. Google redirect GETs instead validate a single-use session-bound OAuth state/nonce/PKCE challenge. Callback parameters never act as ordinary app tokens. The operator-only readiness endpoint uses a distinct probe secret; it is not browser authentication.

Every member resource is filtered by authenticated member UUID before lookup; other-member IDs return 404. The public `member_id` maps to `maison_member_profile.id`; Django's internal user key stays private. Staff operations additionally enforce the named `x-required-permissions`, object scope, privileged MFA, short staff sessions and a reason for financial/publication transitions. A client role field or enabled UI control never authorizes an action. Ordinary Django admin CRUD is protected by the same permissions and validation; it is not a second unrestricted API.

Email verification is server-owned. Login rotates the session and CSRF token; logout invalidates the current session/device binding. Password reset invalidates every session and prior action token. Password change checks the current password and invalidates other sessions. Google-only accounts reauthenticate through Google, rather than accepting an empty password.

Email action tokens are purpose-bound keyed hashes and consumed atomically once. Proposed lifetimes match `runtime-config.json`: magic link 600 seconds, password reset 1,800 seconds, verification 86,400 seconds. Request endpoints return the same 202 whether an address exists. A GET landing page never consumes or logs in; its explicit same-origin POST does. Email links bind to the initiating browser challenge or an explicit confirmation flow. A copied token must not silently log an unrelated browsing session into another account. Invalid, expired or used tokens return `410 action_token_invalid` without revealing account existence.

Google uses authorization-code flow, server-side exchange, PKCE, nonce, state, configured issuer/client/audience/redirect, expiry and verified-email checks. Resolve identity by provider subject. A matching email alone must not attach Google to an existing password account: linking needs an existing authenticated account, fresh reauthentication and explicit `intent=link`. Only saved allowlisted local return paths are accepted. OAuth secrets, codes and ID tokens never enter browser app state or general logs. [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect), [Django CSRF](https://docs.djangoproject.com/en/5.2/howto/csrf/).

## Common wire rules

Application IDs and operation IDs are lowercase UUID4. Times are RFC3339 UTC ending `Z`; server time controls access, ordering and expiry. Request/response JSON keys use snake_case; locales are only `en` and `bn`. Integer milliseconds/Unicode code-point offsets represent locations. Money is integer minor units plus an ISO currency, exclusively loaded from immutable approved terms. No production price, membership count or real customer's record appears in the examples.

Client input schemas reject additional properties. Provider webhook payloads are intentionally extensible because they are an external contract. Their fields still require raw-byte authentication and validated merchant/environment mapping before business use. Unknown provider events can be safely persisted/acknowledged without a grant.

Default JSON request maximum is 256KiB; webhook maximum is 1MiB. Direct uploaded media bypasses Django. Page defaults are 20, maximum 100; Search caps at 50. Keyset cursors are opaque, signed and bind filter/sort/locale/territory/member scope. A mismatched or expired cursor is 400. Page responses contain `items`, `next_cursor` and `has_more`; collection and manifest projections expose their documented cursor directly. Do not implement unbounded offset scans or return entire personal libraries.

Public catalog responses may emit ETag/304 with short public TTLs and explicit locale/territory keys. All identity, money, notes, progress, grants, member-learning state and staff responses are `private, no-store`. Shared-cache behavior is defined in the CDN contract; merely being a GET does not make data public. Session cookies must not accidentally turn `/home` into personalized HTML/JSON. Member resume comes from `/me/vault`.

Responses carry `X-Request-ID`. Input correlation headers are never allowed to overwrite security logs arbitrarily. `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` and 429 `Retry-After` describe enforced policy. The OpenAPI `x-rate-policies` are initial configurable application limits, not vendor limits or proven capacity. Enforce sensitive counters across replicas with the bounded PostgreSQL rate-limit buckets; hash normalized identifiers, do not retain raw login/search/note text for throttling. Bot/WAF rules must not challenge Razorpay callbacks as if they were sign-in attempts. Overloaded webhook intake returns 503 so the provider can retry.

Errors use `application/problem+json` with `type`, `title`, HTTP `status`, stable `code`, safe `detail`, `request_id`, and `retryable`. Validation can include bounded field errors. 401 means sign-in, 403 CSRF/permission/verification/reauthentication failure, 404 absent or another owner's object, 409 conflicting action/state, 410 expired/revoked capability, 412 stale resource version, 422 semantically invalid input, 428 missing version precondition, 429 rate limit and 503 unavailable dependency. Do not render a provider outage as failed payment or expose raw provider errors/secrets.

Additive optional fields and new error codes may ship in v1 when clients remain compatible. Removing/renaming fields, changing field meaning or authorization, or changing a discriminated variant incompatibly requires a new API version and migration period. Financial semantics cannot be changed under old accepted terms merely by introducing v2.

## Retry, compare-and-swap and offline synchronization

`Idempotency-Key` is a fresh UUID4 per intentional action. Canonical path/action/member, validated input hash and the successful response are associated with the same business mutation. Repeating the same key/body replays; reusing a key for changed input returns `409 idempotency_key_reused`. An in-flight action returns 409 with bounded retry advice. Receipt creation and the local mutation commit together. Financial identifiers/provider references remain unique on durable business records even after generic operation receipts expire.

Keep operation receipts 35 days, matching the database/runtime contract. Repeated save/remove membership is intrinsically idempotent. An update with CAS may return 412 after a lost response; the client reloads and compares intent instead of blindly overwriting. For action endpoints carrying both idempotency and If-Match, replay lookup occurs **before** the new CAS comparison, so an already completed action can return its saved response after its own version increment.

Mutable resources expose strong ETags such as `"v3"`; send that exact value in `If-Match`. Missing precondition is 428 and stale is 412, optionally with the authorized current representation/version. Progress is scoped by member, edition and format. A never-written scope is returned as version0/locationnull with `ETag: "v0"`, allowing an unambiguous first write. `edition_revision_id` binds the immutable units/anchors; changed revisions are explicit `409 edition_revision_changed`, not silent re-anchoring. Reader offsets count Unicode code points and must lie on a valid grapheme boundary; viewport pages and UTF16 offsets are not portable storage locations.

Progress carries a body `operation_id`; the receipt/input/precondition and next version commit in one short row-locked transaction. An exact replay returns the prior result. Client `occurred_at` supports UX only; skewed client clocks do not defeat CAS. `fraction_complete` is derived from the validated location, not proof of learning time or money usage. Between-device conflicts require explicit user choice; do not discard an earlier/later intended rereading position with a blind furthest-position merge.

`POST /me/sync` accepts at most 100 operations and 256KiB, bound to the current device. Supported operation kinds are progress.set, annotation.create/patch/delete and saved.set. Every operation has its own UUID/receipt; updates/deletes include `base_version`. Process in submitted order with a separate short transaction per operation, returning applied/replayed/conflict/rejected and a per-operation status. HTTP200 means the batch was received, not that every item applied. One conflict must not undo earlier accepted entries. Tombstones/receipts prevent replay of an old annotation create after its deletion.

Notes are plain text capped at 8KiB UTF8, including Bengali byte length, independently of JSON Schema code-point maxLength. The server derives quoted_text from immutable source with at most2,048 code points/8KiB and exposes quoted_text_truncated; a bounded quote does not change the stable range.

The local queue is at most 500 operations/2MiB, matching runtime settings. Coalesce only unsent progress updates for the same edition/format; preserve notes and acknowledged operation IDs. Client limits prompt recoverable sync/storage UX. Authentication, checkout, refunds, entitlement mutation and license renewal are never queued offline. Device/member logout purges account-scoped cached secrets and licensed bytes best-effort without erasing another account's cache.

## Content, mapping and download authorization

Public previews are physically separate bounded objects. They do not contain hidden full text or use a player stop time to pretend full private audio is a bounded public preview. Public metadata never returns internal rights/source evidence or storage bucket keys.

`ReaderManifest` is a private authorized metadata projection, with `schema_version=1`, immutable `edition_revision_id`, `content_sha256`, `anchor_revision`, paginated units/chunk hashes and `next_cursor`. Bound each response to 64KiB; large units may continue across cursor pages. Reader chunks target at most 64KiB compressed/256KiB raw. `POST /content/packages/grants` accepts at most10 unit IDs and optional100 chunk IDs; a larger implicit chunk set returns `422 chunk_selection_required`. It returns up to100 authorized chunk URLs with exact hashes/bytes. No arbitrary client object key or URL is signed. For Reader chunk assets, chunk_id is the same UUID as maison_asset.id (and asset_id when both are present), not a separate chunk table.

Before every content/media URL issuance or renewal, check current account/device, Live revision, territory, per-format rights and effective entitlement. Online R2/Stream capability lifetime is at most120 seconds and no longer than access/rights validity. Private full packages/audio use direct signed R2 S3 URLs, not a public/custom-domain CDN cache. Stream signed playback is likewise renewable; its player must qualify token refresh without losing the saved position. Audio requests use Range directly; Django never becomes a byte proxy after expiry. URLs and provider tokens are not logged, persisted as stable identifiers or used as local cache keys.

Measured timing maps bind exact text and audio/video hashes. P0 Reader/audio switching returns mapped location only when an approved measured map exists. Unmapped/unreleased/disabled outcomes return a null target and UI offers a chapter choice. There is no estimated synchronization fallback. The map/segment API does not imply word-level highlighting or video Trinity is already P0.

`POST /me/downloads` creates a device/member/revision-bound offline license and authorizes only rights-permitted Reader/audio. `valid_until` is the minimum of issuance+24h, entitlement end and rights end. No full-video download is offered. License URLs still expire within120 seconds, so `/refresh` can reauthorize transfer URLs online without extending the license. `/renew` performs a fresh online rights/access check before issuing a new bounded lease. An expired/revoked license never silently renews offline.

Reader chunks use whole-object hashes. Audio has a private prepared piece manifest referenced by `OfflineAsset.piece_manifest`; the object conforms to `OfflinePiecePage` and contains ordered 1MiB piece hashes except the final piece, at most5,000 pieces and1MiB encoded manifest. Split larger audio assets/units before Ready. This avoids expanding thousands of hashes in each API license response. Download and validate the manifest before offline use. ETag is not assumed to be SHA256. The browser converts verified range pieces into account/device/revision-scoped synthetic200 cache entries; `Cache.put(206)` is not the design. Resume verifies retained pieces, storage quota/eviction is a recoverable client state, and the UI does not claim server knowledge of local downloaded bytes.

Revocation immediately blocks new origin authorizations and requests deletion at next online validation. Previously issued URLs can work until their <=120-second expiry; an offline honest client can retain access until its <=24-hour lease ends. Browser packages are not DRM and cannot guarantee physical recall. Device revoke invalidates its sessions and licenses; removing a single download does not delete Saved, annotations, purchases or another device's files.

## Commerce state machines and provider authority

An available offer/plan must have owner-approved server price, currency, duration, territorial eligibility and accepted terms version. A price_pending offer returns null price and cannot create checkout. Clients submit only offer/plan ID/version, accepted terms version and a safe return path. Any changed terms/price causes explicit reconfirmation. No card, UPI credential, provider secret or invented price is stored by the product UI.

One-time order transitions are `creating → created → pending → paid`; created means a provider order ID is known. Final creation/policy failure may become failed; nonpaid orders may expire/cancel only from verified server policy. A dismissed checkout modal is not proof of cancellation/failure. Payment attempts have their own pending/authorized/captured/failed/refund state; a failed attempt does not turn an order terminal if a valid payment remains pending. A historically paid order remains paid after a refund, with the payment/refund fields representing reversal.

Reserve the local order/idempotency association first, commit, then make the provider call outside locks. Keep the local UUID in provider receipt/notes and store provider IDs uniquely. An ambiguous timeout stays creating/pending and is reconciled, never followed by an uncorrelated second charge/order. Provider create APIs are not assumed to honor the application's Idempotency-Key. Fetch status/polling offers Retry only when a new intentional order is safe.

One-time verification computes `HMAC_SHA256(stored_provider_order_id + "|" + payment_id, key_secret)` with a constant-time compare, checking that callback order ID equals the stored value. Then verify provider merchant/environment, ownership, exact amount/currency and capture status. Valid signature alone does not grant access. A captured payment transition locks the order and writes unique payment, paid state, entitlement and receipt/outbox in one transaction. Delayed callbacks or duplicate webhook/verify races converge on the same rows. [Razorpay checkout verification](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps).

Member refund requests are policy-review intents, not immediate promises or client-selected amounts. Staff approval requires fresh authentication, permission, reason and CAS; lock captured payment and enforce amount not exceeding captured less pending/processed refunds. States are requested → approved → submitted → pending → processed or failed; a requested item may be rejected. Do not mark a pending provider response processed. An ambiguous provider request is reconciled before a retry. Full processed refund revokes the grants sourced by that purchase; partial refund preserves existing access by default, with any adjustment an explicit separately audited owner policy action, never an inferred duration conversion. Already-issued offline capability limits still apply.

### Recurring contracts: designed, initially disabled

`RECURRING_PASS_ENABLED_AND_MERCHANT_APPROVED` gates new subscription/authorization/charge work until legal entity, merchant support, payment methods, price, renewal notices, cancellation and terms have been accepted and sandbox-tested. This does not hide historical billing or prevent cancelling an existing obligation when new sales are disabled.

An immutable BillingPlan snapshots approved amount/currency/interval/count/provider plan and terms. Subscription creation stores explicit recurring consent and a local action UUID before creating provider authorization. API local statuses are pending, active, past_due, paused, cancelled, completed and expired; `provider_status` preserves the separately normalized provider state. Authorization/authenticated alone leaves pending and grants nothing. A verified captured paid invoice creates exactly one invoice allocation and paid-period entitlement; renewals extend to the agreed paid-through boundary once, not on every subscription.active event. Failed renewal becomes past_due with paid-through access unchanged; after its end access expires unless an explicitly approved grace policy exists. No unapproved free trial/grace or recurring amount is invented.

Recurring callback HMAC input is **different**: `payment_id + "|" + stored_provider_subscription_id`. Verify merchant ownership, plan and corresponding paid invoice/payment. Raw provider events use the same invariant checks and locked transition service. Duplicate/late activation cannot undo cancellation; a paid captured invoice may settle legitimate earlier obligations without re-enabling future collection. [Razorpay recurring verification](https://razorpay.com/docs/payments/subscriptions/integration-guide).

`POST /commerce/subscriptions/{id}/cancel` records cancellation intent with CAS and idempotency, sets cancel_at_period_end, and schedules provider `cancel_at_cycle_end=1`. Preserve paid-through access and show provider pending state during an outage; never silently drop the saved cancellation. `DELETE /commerce/mandates/{id}` requires fresh authentication and records revocation_pending until provider confirmation, which becomes cancelled. It stops future collection without erasing already-earned access. Existing cancellation/revocation endpoints work even when new recurring checkout is disabled. Pause/upgrade/proration are not initial API actions; provider paused state can still be represented honestly.

Invoice headers point to immutable numbered revisions, approved issuer/tax fields and payment allocations. Paid invoices are not edited in place; corrections/refunds use linked financial revisions/credit notes under staff policy. Private PDF grants expire<=120s. No client-provided invoice total, tax entity or arbitrary URL is accepted.

### Webhook transaction boundary

Authenticate `X-Razorpay-Signature` over **exact raw request bytes** with the independently configured/rotatable webhook secret before parsing. Validate configured merchant/account and test/live environment. Dedupe `x-razorpay-event-id`; do not depend on event arrival order. General request logs exclude raw signed payloads and customer payment fields. [Razorpay webhook validation/idempotency](https://razorpay.com/docs/webhooks/validate-test).

For a complete known verified event, perform the bounded receipt + payment/invoice + order + entitlement + notification-outbox transition in one DB transaction. No provider network call runs inside that transaction. Duplicate receipts return200 without repeated effects. For incomplete, unmatched or ambiguous/out-of-order facts, persist receipt and a reconciliation outbox intent atomically, then acknowledge200; keep purchase pending until authoritative reconciliation. The next one-minute maintenance run is the initial latency target, not a guaranteed upper bound; alert unresolved captured-payment grants after two minutes. Unknown signed event types persist/ack with no access grant. DB failure returns503 for provider retry. Never acknowledge an unpersisted event as accepted.

## Editorial actions and operations

Normal work/edition/localized-metadata/unit/rights/asset/track/quiz CRUD lives in customized Django admin, with model validation, permissions and versioned drafts. The API adds task-specific review, direct upload, validate/Ready/publish/schedule/withdraw and financial reconciliation actions; it does not recreate a headless CMS.

Publication is Draft → Ready → Live, with retirement/withdrawal explicit. Each action names exact immutable revision and SHA256 plus current edition ETag. Validation checks rights, metadata, text, anchors, cover, media, required map and browser evidence for that revision. Reader-only editions can pass without audio; missing media is not an invented fallback. New text/assets invalidate prior revision checks. A scheduled action stores one exact Ready revision and future time; the due job rechecks state/hash/rights and applies the same publish transition. Publication visibility/search and audit commit together; public cache purge is a durable outbox effect. Withdraw blocks new grants immediately, purges public metadata/previews and retains the already-issued capability expiry limits described above.

Direct upload intents validate staff scope, asset type/MIME/size/hash and edition revision. Authorize R2 PUT or managed Stream TUS; never accept arbitrary client object keys. UploadComplete does not declare the asset ready: inspect stored bytes/hash/MIME and provider processing, leaving processing/failed honestly. CreateUploadIntent returns an initial asset version/ETag; GetAssetState supports bounded polling and subsequent If-Match. Rights/source documents remain staff-private.

`/health/live` is minimal process liveness and is the native Render health-check route/origin-secret exception. It does not query the DB or expose versions/configuration. `/health/ready` is an optional operator/synthetic database/migration probe with a separate header secret; do not assume Render native health checks can supply it. No new monitoring service is required. 503 readiness is a signal, not authority to declare a payment failed.

## Privacy and legacy obligations

Contact accepts bounded plain text/email/category, queues one request and returns a generic receipt; supplying an order UUID does not authorize its disclosure. Privacy export/deletion requires fresh<=5min reauthentication and CSRF; record a typed outbox/audit request. Export includes only the member's portable data, never provider secrets, another member's data or internal rights evidence. Its artifact is private and short-lived. Deletion handles recurring cancellation/session/license revocation and permitted retention before completed; awaiting_resolution is honest when unresolved obligations block final disposal. A queued request can be cancelled; already processing/completed deletion is not reversed by a misleading Undo.

The Vault exposes only verified own legacy liabilities. Exact old seconds/access/payment/refund obligations must be migrated, settled/refunded or explicitly agreed before retirement. This API does not create a new minute wallet, top-up or consumption meter by default. If exact metered migration remains necessary, keep it behind an obligation-specific adapter flag and a separately reviewed compatibility contract; never quietly convert seconds to a new price/expiry rule.

## Screen-to-operation coverage

Operation IDs below are exact keys from OpenAPI; SSR composition is separate. A deferred screen does not acquire a fake P0 API merely because a visual frame exists.

| Screen | API operation IDs | Scope |
|---|---|---|
| S01 Welcome/onboarding | getSession, getPublicHome, updatePreferences, updateConsents | P0; member choices persisted after sign-in |
| S02 Sign in/up | register, login, emailVerificationRequest, emailVerificationConsume, passwordResetRequest, passwordResetConsume, googleStart, googleCallback, emailLinkRequest, emailLinkConsume, requestPhoneChallenge, verifyPhoneChallenge | P0; magic/phone activation gates explicit |
| S03 Home guest | getPublicHome, listCollections, getSession | P0 public data only |
| S04 Home member | getPublicHome, getVault, listProgress, getPreferences | P0 resume; goal-ring/Now embellishments later |
| S05 Explore | listCollections, getCollection, getWork, getEdition | P0 |
| S06 Search | searchCatalog | P0 text search; voice/command palette later |
| S07 Title | getWork, getEdition, listUnits, getPreview, listOffers, listEntitlements, saveEdition, unsaveEdition | P0 |
| S08 Reader | getReaderManifest, grantReaderPackage, getProgress, setProgress, syncOfflineOperations, listAnnotations, createAnnotation, updateAnnotation, deleteAnnotation, getPreferences, updatePreferences | P0; dictionary/word read-along later |
| S09 Reader preview end | getPreview, listOffers, getSession, createOrder | P0 overlay, no dedicated page API |
| S10 Audio | grantMedia, listUnits, getProgress, setProgress, getMappings, switchPosition, createDownloadLicense | P0 released audio only |
| S11 Audio preview end | getPreview, listOffers, createOrder | P0 bounded-preview overlay |
| S12 Video | grantMedia, getProgress, setProgress | P0 released video; offline/video switch later |
| S13 Series | getCollection, getEdition, saveEdition | P0 collection kind=series |
| S14 Clips | none | P1, no endpoint/active launch control |
| S15 Switch sheet | getMappings, switchPosition | P0 Reader/audio; unmapped explicit, video later |
| S16 Learn/track | listTracks, getTrack, getLesson, listEntitlements | P0 |
| S17 Lesson/quiz/result | getLesson, completeLesson, getQuiz, startQuizAttempt, getQuizAttempt, submitQuizAttempt | P0 server grading/snapshot |
| S18 Interview track | listTracks, getTrack, listInterviewQuestions | P0 SDE bank, plans, Company Packs |
| S19 Practice/readiness | none | P1 timed/recorded/readiness; no fake score API |
| S20 Pass | listOffers, listPlans, listEntitlements, listSubscriptions | P0; recurring plan sales gated |
| S21 Checkout/success | createOrder, getOrder, verifyPayment, createSubscription, getSubscription, verifySubscription | P0 one-time; recurring contract gated |
| S22 Vault | getVault, listSavedItems, listProgress, listDownloads, listPersonalLists, createPersonalList, getPersonalList, renamePersonalList, deletePersonalList, addListEdition, removeListEdition, reorderList | P0 personal library/custom Lists |
| S23 Notes/download family | listDownloads, getDownloadLicense, createDownloadLicense, refreshDownloadUrls, renewDownloadLicense, revokeDownloadLicense | P0 downloads; consolidated Notes/search/export later |
| S24 Settings/billing/privacy | getProfile, updateProfile, getPreferences, updatePreferences, getConsents, updateConsents, listDevices, revokeDevice, listOrders, listInvoices, downloadInvoice, listSubscriptions, cancelSubscription, listMandates, revokeMandate, requestRefund, listRefunds, createPrivacyRequest, getPrivacyRequest, downloadPrivacyExport, logout | P0; cancel only existing recurring contracts, no cancel for nonrenewing pass |
| S25 Gift | none | P1 |
| S26 System states | getSession, liveness plus each operation's Problem status | P0; readiness is operator-only, no fake client connectivity proof |

## Operation inventory

All paths below have the `/api/v1` prefix. The OpenAPI file contains exact statuses, schemas, security, rate-policy metadata, headers and request examples. The operation inventory is generated from that file to keep keys consistent.

| Operation ID | Method | Relative path | Phase/gate |
|---|---|---|---|
| getSession | GET | `/session` | P0 |
| logout | DELETE | `/session` | P0 |
| register | POST | `/auth/register` | P0 |
| login | POST | `/auth/login` | P0 |
| emailVerificationRequest | POST | `/auth/email-verifications/request` | P0 |
| emailVerificationConsume | POST | `/auth/email-verifications/confirm` | P0 |
| passwordResetRequest | POST | `/auth/password-resets/request` | P0 |
| passwordResetConsume | POST | `/auth/password-resets/confirm` | P0 |
| emailLinkRequest | POST | `/auth/email-links/request` | P0; EMAIL_MAGIC_LINK_ENABLED |
| emailLinkConsume | POST | `/auth/email-links/consume` | P0; EMAIL_MAGIC_LINK_ENABLED |
| googleStart | GET | `/auth/google` | P0 |
| googleCallback | GET | `/auth/google/callback` | P0 |
| requestPhoneChallenge | POST | `/auth/phone-challenges` | P0; PHONE_OTP_ENABLED_AND_VERIFIED_PROVIDER |
| verifyPhoneChallenge | POST | `/auth/phone-challenges/{challenge_id}/verify` | P0; PHONE_OTP_ENABLED_AND_VERIFIED_PROVIDER |
| getProfile | GET | `/me/profile` | P0 |
| updateProfile | PATCH | `/me/profile` | P0 |
| changePassword | POST | `/me/password` | P0 |
| reauthenticate | POST | `/me/reauthenticate` | P0 |
| getPreferences | GET | `/me/preferences` | P0 |
| updatePreferences | PATCH | `/me/preferences` | P0 |
| getConsents | GET | `/me/consents` | P0 |
| updateConsents | PUT | `/me/consents` | P0 |
| listDevices | GET | `/me/devices` | P0 |
| revokeDevice | DELETE | `/me/devices/{device_id}` | P0 |
| getPublicHome | GET | `/home` | P0 |
| listCollections | GET | `/catalog/collections` | P0 |
| getCollection | GET | `/catalog/collections/{collection_id}` | P0 |
| getWork | GET | `/catalog/works/{work_id}` | P0 |
| getEdition | GET | `/catalog/editions/{edition_id}` | P0 |
| listUnits | GET | `/catalog/editions/{edition_id}/units` | P0 |
| searchCatalog | GET | `/search` | P0 |
| getPreview | GET | `/content/previews/{edition_revision_id}` | P0 |
| getReaderManifest | GET | `/content/manifests/{edition_revision_id}` | P0 |
| grantReaderPackage | POST | `/content/packages/grants` | P0 |
| grantMedia | POST | `/media/grants` | P0 |
| getMappings | GET | `/content/mappings/{edition_revision_id}` | P0 |
| switchPosition | POST | `/content/switch-position` | P0 |
| listProgress | GET | `/me/progress` | P0 |
| getProgress | GET | `/me/progress/{edition_id}/{format}` | P0 |
| setProgress | PUT | `/me/progress/{edition_id}/{format}` | P0 |
| syncOfflineOperations | POST | `/me/sync` | P0 |
| listAnnotations | GET | `/me/annotations` | P0 |
| createAnnotation | POST | `/me/annotations` | P0 |
| getAnnotation | GET | `/me/annotations/{annotation_id}` | P0 |
| updateAnnotation | PATCH | `/me/annotations/{annotation_id}` | P0 |
| deleteAnnotation | DELETE | `/me/annotations/{annotation_id}` | P0 |
| listSavedItems | GET | `/me/saved-items` | P0 |
| saveEdition | PUT | `/me/saved-items/{edition_id}` | P0 |
| unsaveEdition | DELETE | `/me/saved-items/{edition_id}` | P0 |
| listPersonalLists | GET | `/me/lists` | P0 |
| createPersonalList | POST | `/me/lists` | P0 |
| getPersonalList | GET | `/me/lists/{list_id}` | P0 |
| renamePersonalList | PATCH | `/me/lists/{list_id}` | P0 |
| deletePersonalList | DELETE | `/me/lists/{list_id}` | P0 |
| addListEdition | PUT | `/me/lists/{list_id}/items/{edition_id}` | P0 |
| removeListEdition | DELETE | `/me/lists/{list_id}/items/{edition_id}` | P0 |
| reorderList | PUT | `/me/lists/{list_id}/order` | P0 |
| getVault | GET | `/me/vault` | P0 |
| listEntitlements | GET | `/me/entitlements` | P0 |
| listDownloads | GET | `/me/downloads` | P0 |
| createDownloadLicense | POST | `/me/downloads` | P0 |
| getDownloadLicense | GET | `/me/downloads/{license_id}` | P0 |
| revokeDownloadLicense | DELETE | `/me/downloads/{license_id}` | P0 |
| refreshDownloadUrls | POST | `/me/downloads/{license_id}/refresh` | P0 |
| renewDownloadLicense | POST | `/me/downloads/{license_id}/renew` | P0 |
| listTracks | GET | `/learning/tracks` | P0 |
| getTrack | GET | `/learning/tracks/{track_id}` | P0 |
| getLesson | GET | `/learning/lessons/{lesson_id}` | P0 |
| completeLesson | POST | `/learning/lessons/{lesson_id}/complete` | P0 |
| listInterviewQuestions | GET | `/learning/tracks/{track_id}/questions` | P0 |
| getQuiz | GET | `/learning/quizzes/{quiz_id}` | P0 |
| startQuizAttempt | POST | `/learning/quizzes/{quiz_id}/attempts` | P0 |
| getQuizAttempt | GET | `/learning/attempts/{attempt_id}` | P0 |
| submitQuizAttempt | POST | `/learning/attempts/{attempt_id}/submit` | P0 |
| listOffers | GET | `/commerce/offers` | P0 |
| listOrders | GET | `/commerce/orders` | P0 |
| createOrder | POST | `/commerce/orders` | P0 |
| getOrder | GET | `/commerce/orders/{order_id}` | P0 |
| verifyPayment | POST | `/commerce/orders/{order_id}/verify` | P0 |
| listRefunds | GET | `/commerce/refunds` | P0 |
| requestRefund | POST | `/commerce/refunds` | P0 |
| getRefund | GET | `/commerce/refunds/{refund_id}` | P0 |
| listPlans | GET | `/commerce/plans` | P0; RECURRING_PASS_ENABLED |
| listSubscriptions | GET | `/commerce/subscriptions` | P0 |
| createSubscription | POST | `/commerce/subscriptions` | P0; RECURRING_PASS_ENABLED_AND_MERCHANT_APPROVED |
| listMandates | GET | `/commerce/mandates` | P0 |
| listInvoices | GET | `/commerce/invoices` | P0 |
| getSubscription | GET | `/commerce/subscriptions/{subscription_id}` | P0 |
| verifySubscription | POST | `/commerce/subscriptions/{subscription_id}/verify` | P0; RECURRING_PASS_ENABLED_AND_MERCHANT_APPROVED |
| cancelSubscription | POST | `/commerce/subscriptions/{subscription_id}/cancel` | P0 |
| revokeMandate | DELETE | `/commerce/mandates/{mandate_id}` | P0 |
| getInvoice | GET | `/commerce/invoices/{invoice_id}` | P0 |
| downloadInvoice | POST | `/commerce/invoices/{invoice_id}/download` | P0 |
| receiveRazorpayWebhook | POST | `/webhooks/razorpay` | P0 |
| contactSupport | POST | `/contact` | P0 |
| listPrivacyRequests | GET | `/me/privacy/requests` | P0 |
| createPrivacyRequest | POST | `/me/privacy/requests` | P0 |
| getPrivacyRequest | GET | `/me/privacy/requests/{privacy_request_id}` | P0 |
| downloadPrivacyExport | POST | `/me/privacy/requests/{privacy_request_id}/download` | P0 |
| cancelPrivacyRequest | POST | `/me/privacy/requests/{privacy_request_id}/cancel` | P0 |
| reviewEdition | GET | `/staff/editions/{edition_id}/review` | P0 |
| getAssetState | GET | `/staff/assets/{asset_id}` | P0 |
| validateEdition | POST | `/staff/editions/{edition_id}/validate` | P0 |
| markEditionReady | POST | `/staff/editions/{edition_id}/mark-ready` | P0 |
| publishEdition | POST | `/staff/editions/{edition_id}/publish` | P0 |
| scheduleEdition | POST | `/staff/editions/{edition_id}/schedule` | P0 |
| withdrawEdition | POST | `/staff/editions/{edition_id}/withdraw` | P0 |
| createUploadIntent | POST | `/staff/assets/uploads` | P0 |
| completeUpload | POST | `/staff/assets/{asset_id}/complete` | P0 |
| approveRefund | POST | `/staff/refunds/{refund_id}/approve` | P0 |
| rejectRefund | POST | `/staff/refunds/{refund_id}/reject` | P0 |
| reconcileOrder | POST | `/staff/orders/{order_id}/reconcile` | P0 |
| liveness | GET | `/health/live` | P0 |
| readiness | GET | `/health/ready` | P0 |


## Contract verification and limits

Validate OpenAPI 3.1 structure, resolve every local schema reference, validate included request/response examples against their schemas, ensure every screen operation ID exists, and audit every unsafe operation's security requirements. These checks verify the design artifact, not Django behavior, provider credentials, commercial rights, migration readiness or live load. Implementation still needs cross-account/CSRF tests, real database CAS/idempotency concurrency, provider sandbox duplicate/out-of-order events, cache isolation, token refresh, offline device testing and a restore exercise.

Only synthetic UUIDs/example domains and clearly fictional account text are included. No numeric offer/plan/checkout price examples are supplied because no approved pricing decision was provided. Money schemas still define exact integer/currency types and server invariants. Provider schemas remain linked to official documentation and must be pinned/covered by sandbox fixtures at implementation. The API design does not authorize a payment, account deletion, publication or deployment.

## Draft1.1 corrections before implementation

Canonical highlight colors are gold/mint/rose/lavender across SQL, schemas and UI. Aggregate version sources are persisted for edition/revision, asset, device, order and refund. Explicit completion uses GET/PUT /me/completion/{edition_id}/{format}, its own CAS/version/operation ID and nullable completed_at. First absent v0 writes insert finalv1 directly.

A partially committed sync batch interrupted by dependency failure returns whole-batch503; replay the complete unchanged operation-ID batch. Durable receipts replay committed successes. No per-item503 result is promised.

Upload input-to-asset mapping and private raw kinds are defined in LLD; only qualified deliverable kinds get member grants. Local-only local_signed/local_put support technical validation with no provider-success claim.

For a verified capture after cancelled/expired, persist captured money and paid order, set fulfillment_status=refund_pending, grant nothing and schedule one durable approved compensating-refund/review action. Existing accepted terms and financial records remain immutable; no duplicate charge is issued. Refund amount changes once only at requested->approved, bounded by proposal and remaining capture.

Boolean flags and canonical rollout_gate_map govern actual enablement; activation prose is not executable truthiness. Search facets and Reader comfort/saved-filter preferences use the amended schemas. Known rights expiry caps public freshness. These are corrections to an undeployed draft; no legacy production API was changed.

### Prospective password-purpose choice — operating follow-up,20November2026

Public password registration, login, password-reset confirmation, member reauthentication and password change require `password_purpose_consent: true` (literal JSON boolean) plus `password_purpose_version: "password-account-v1"`. Missing,false,truthy-nonboolean or stale choice returns422 `password_purpose_consent_required` before password authentication/change. HTML forms require the corresponding unchecked affirmative checkbox/current version. Google identity has no invented password consent. Staff admin login/password-change use the same purpose gate.

The choice covers only disclosed password authentication/account security. Marketing/analytics remain separate/defaultfalse. A successful actual account action records minimal purpose/version/affirmative/collection-time evidence, never passwords/hashes. Duplicate registration, failed authentication and internal service calls do not fabricate consent. Existing accounts are not backfilled. Exact classified receipts expire after180days subject to holds; registration scaffolding does not defeat untouched signup cleanup. Declining stops that password action; withdrawal and supported account deletion remain available as described in the notice.
